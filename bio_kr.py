"""
바이오 탭 국장 데이터: KRX 가격 DB(price_daily) + Open DART(재무제표·공시).

- 단위: 금액은 억원, 주식 수는 억주로 둔다 → 억원 ÷ 억주 = 원/주 (미장 쪽 백만 달러 ÷ 백만 주와 같은 계산).
- 재무: DART 단일회사 전체 재무제표(fnlttSinglAcntAll). 연결(CFS) 우선, 없으면 별도(OFS).
  손익은 분기보고서의 3개월 값(thstrm_amount), 4분기는 사업보고서 연간 − 3분기 누적(thstrm_add_amount).
  현금흐름은 누적 값이라 앞 보고서와의 차이로 분기 값을 만든다.
- 회사마다 계정 이름이 달라서 표준 계정ID 를 먼저 보고, 없으면 한글 계정명으로 찾는다. 어떤 계정을 더했는지 결과에 남긴다.
- 공시: 대시보드가 이미 모으는 dart_event(목록)·dart_filing(원문 항목)을 쓴다.

  python3 bio_kr.py 196170
"""

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

import config  # noqa: F401
import db

ROOT = Path(__file__).resolve().parent
CORP = ROOT / '.cache' / 'dart_corp.json'
FIN_CACHE = ROOT / '.cache' / 'dart_fin.json'
API = 'https://opendart.fss.or.kr/api'
EOK = 1e8
REPORTS = [('11013', 3), ('11012', 6), ('11014', 9), ('11011', 12)]   # 1분기, 반기, 3분기, 사업보고서

FLOW_IDS = {
    'revenue': ['ifrs-full_Revenue'],
    'op_income': ['dart_OperatingIncomeLoss'],
    'net_income': ['ifrs-full_ProfitLoss'],
}
CF_IDS = {'opcf': ['ifrs-full_CashFlowsFromUsedInOperatingActivities']}
CASH_IDS = ['ifrs-full_CashAndCashEquivalents']
STI_IDS = ['ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents', 'dart_ShortTermDepositsNotClassifiedAsCashEquivalents',
           'ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLoss', 'dart_ShortTermInvestments']
STI_NAMES = ('단기금융상품', '단기투자', '당기손익-공정가치측정금융자산', '단기매매금융자산')
DEBT_NAMES = ('차입', '사채', '상환전환우선주부채', '전환우선주부채')
DEBT_SKIP = ('이자', '발행비', '할인', '할증', '상환할증', '전환권조정', '신주인수권조정')


def key() -> str:
    return os.environ.get('DART_API_KEY', '')


def corp_code(stock_code: str):
    try:
        m = json.loads(CORP.read_text())
    except (OSError, ValueError):
        m = {}
    if stock_code not in m:
        import io
        import xml.etree.ElementTree as ET
        import zipfile
        r = requests.get(f'{API}/corpCode.xml', params={'crtfc_key': key()}, timeout=60)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(z.read(z.namelist()[0]))
        m = {li.findtext('stock_code').strip(): li.findtext('corp_code') for li in root.iter('list') if (li.findtext('stock_code') or '').strip()}
        CORP.parent.mkdir(exist_ok=True)
        CORP.write_text(json.dumps(m))
    return m.get(stock_code)


def _fetch(cc: str, year: int, reprt: str, cache: dict):
    k = f'{cc}:{year}:{reprt}'
    if k in cache:
        return cache[k]
    out = None
    for fs in ('CFS', 'OFS'):
        time.sleep(0.2)
        j = requests.get(f'{API}/fnlttSinglAcntAll.json', params={'crtfc_key': key(), 'corp_code': cc, 'bsns_year': str(year),
                                                                  'reprt_code': reprt, 'fs_div': fs}, timeout=30).json()
        if j.get('status') == '000' and j.get('list'):
            out = {'fs': fs, 'list': j['list']}
            break
        if j.get('status') not in ('000', '013'):
            raise RuntimeError(f"DART {j.get('status')} {j.get('message')}")
    if out is not None:   # 제출 전(013)은 캐시하지 않고 다음 실행에서 다시 본다
        cache[k] = out
    return out


def _num(s):
    if s in (None, '', '-'):
        return None
    try:
        return float(str(s).replace(',', ''))
    except ValueError:
        return None


def _pick(rows, ids, sj=None, names=()):
    for r in rows:
        if (sj is None or r['sj_div'] in sj) and r['account_id'] in ids:
            return r
    for r in rows:
        if (sj is None or r['sj_div'] in sj) and any(n == r['account_nm'].replace(' ', '') for n in names):
            return r
    return None


def _bs_sum(rows, ids, names, skip=()):
    """재무상태표에서 계정ID 또는 한글 이름이 맞는 항목을 더한다. 더한 항목 이름도 돌려준다."""
    got, used = 0.0, []
    for r in rows:
        if r['sj_div'] != 'BS':
            continue
        nm = r['account_nm'].replace(' ', '')
        if r['account_id'] in ids or (any(n in nm for n in names) and not any(s in nm for s in skip)):
            v = _num(r.get('thstrm_amount'))
            if v:
                got += v
                used.append(r['account_nm'].strip())
    return got, used


def financials(stock_code: str, years=None, today: date | None = None) -> dict | None:
    today = today or date.today()
    cc = corp_code(stock_code)
    if not cc:
        return None
    try:
        cache = json.loads(FIN_CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    years = years or [today.year - 2, today.year - 1, today.year]
    reps = []
    for y in years:
        for reprt, m in REPORTS:
            end = date(y, m, 31 if m in (3, 12) else 30).isoformat()
            if end > today.isoformat():
                continue
            d = _fetch(cc, y, reprt, cache)
            if d:
                reps.append({'year': y, 'reprt': reprt, 'month': m, 'end': end, **d})
    FIN_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    if not reps:
        return None
    q = {}
    for r in reps:
        rows = r['list']
        rec = q.setdefault(r['end'], {'end': r['end']})
        for k, ids in FLOW_IDS.items():
            x = _pick(rows, ids, sj=('IS', 'CIS'))
            if not x:
                continue
            if r['reprt'] == '11011':   # 연간 − 3분기 누적
                prev = next((p for p in reps if p['year'] == r['year'] and p['reprt'] == '11014'), None)
                px = _pick(prev['list'], ids, sj=('IS', 'CIS')) if prev else None
                fy, ytd9 = _num(x.get('thstrm_amount')), _num(px.get('thstrm_add_amount')) if px else None
                rec[k] = (fy - ytd9) / EOK if fy is not None and ytd9 is not None else None
            else:
                v = _num(x.get('thstrm_amount'))
                rec[k] = v / EOK if v is not None else None
        for k, ids in CF_IDS.items():
            x = _pick(rows, ids, sj=('CF',))
            cum = _num(x.get('thstrm_amount')) if x else None
            if cum is None:
                continue
            if r['reprt'] == '11013':
                rec[k] = cum / EOK
            else:
                pm = {'11012': '11013', '11014': '11012', '11011': '11014'}[r['reprt']]
                prev = next((p for p in reps if p['year'] == r['year'] and p['reprt'] == pm), None)
                px = _pick(prev['list'], ids, sj=('CF',)) if prev else None
                pc = _num(px.get('thstrm_amount')) if px else None
                rec[k] = (cum - pc) / EOK if pc is not None else None
    last = max(reps, key=lambda r: r['end'])
    rows = last['list']
    cash_r = _pick(rows, CASH_IDS, sj=('BS',))
    cash = (_num(cash_r.get('thstrm_amount')) or 0) / EOK if cash_r else None
    sti, sti_used = _bs_sum(rows, STI_IDS, STI_NAMES)
    debt, debt_used = _bs_sum(rows, [], DEBT_NAMES, DEBT_SKIP)
    quarters = []
    for e in sorted(q)[-8:]:
        r = q[e]
        d = date.fromisoformat(e)
        quarters.append({'end': e, 'label': f'{d.year} Q{(d.month - 1) // 3 + 1}', 'revenue': r.get('revenue'), 'rnd': None, 'sga': None,
                         'op_income': r.get('op_income'), 'net_income': r.get('net_income'), 'opcf': r.get('opcf'), 'eps': None})
    cf = [x['opcf'] for x in quarters if x['opcf'] is not None][-2:]
    burn = -sum(cf) / len(cf) if cf and sum(cf) < 0 else None
    total = (cash or 0) + sti / EOK
    return {
        'quarters': quarters,
        'concepts': {'fs': '연결' if last['fs'] == 'CFS' else '별도', 'sti': ', '.join(sti_used) or '없음', 'debt': ', '.join(debt_used) or '없음'},
        'balance': {'end': last['end'], 'cash': cash, 'sti': sti / EOK, 'cash_total': total, 'debt': debt / EOK if debt_used else None},
        'shares': None, 'burn_quarter': burn, 'runway_months': total / burn * 3 if burn else None,
        'last_filed': f"{last['year']} {dict(REPORTS)[last['reprt']]}월 보고서", 'unit': '억원',
        'filings_url': f'https://dart.fss.or.kr/dsab007/main.do?option=corp&textCrpCik={cc}',
    }


def market(stock_code: str):
    """KRX 종가·시총(억원)·상장주식수(억주)와 직전 거래일 대비 등락률."""
    conn = db.connect()
    r = conn.execute('SELECT date, close, change_pct, mcap, shares, name, market FROM price_daily WHERE code=? ORDER BY date DESC LIMIT 1',
                     (stock_code,)).fetchone()
    if not r:
        return None
    return {'price': r[1], 'change_pct': r[2], 'mcap': r[3], 'shares': r[4] / EOK if r[4] else None,   # price_daily.mcap 은 이미 억원
            'cash': None, 'debt': None, 'op_cf': None, 'revenue_ttm': None, 'beta': None, 'currency': 'KRW', 'asof': r[0],
            'name_kr': r[5], 'exchange': r[6]}


def prices(stock_code: str):
    conn = db.connect()
    rows = conn.execute('SELECT date, close FROM price_daily WHERE code=? AND close IS NOT NULL ORDER BY date', (stock_code,)).fetchall()
    d = [[a, b] for a, b in rows][-260:]
    w = [[a, b] for i, (a, b) in enumerate(rows) if i % 5 == len(rows) % 5][-270:]
    return {'d': d, 'w': w}


BIZ_KEYS = ('임상', '품목허가', '허가', '기술이전', '라이선스', '라이센스', '계약', 'FDA', 'BLA', 'NDA', 'PDUFA', '승인', '결과')


def filings(stock_code: str, days: int = 365) -> list:
    """대시보드가 모은 DART 공시 (최근 days 일). 원문 링크와, 원문에서 읽은 항목(제목·주요내용)이 있으면 함께."""
    conn = db.connect()
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute('SELECT rcept_no, date, kind, title FROM dart_event WHERE code=? AND date>=? ORDER BY date DESC', (stock_code, since)).fetchall()
    out = []
    for no, d, kind, title in rows:
        f = conn.execute('SELECT data FROM dart_filing WHERE rcept_no=?', (no,)).fetchone()
        data = json.loads(f[0]) if f and f[0] else None
        out.append({'acc': no, 'filed': d, 'kind': kind, 'title': title, 'data': data,
                    'url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}'})
    return out


def market_screen(days: int = 30, today: date | None = None) -> list:
    """국장 전체: 최근 days 일 '투자판단 관련 주요경영사항' 중 임상·허가·기술이전 공시 (제목·주요내용은 원문 그대로)."""
    today = today or date.today()
    conn = db.connect()
    since = (today - timedelta(days=days)).isoformat()
    rows = conn.execute("""SELECT e.rcept_no, e.date, e.code, e.name, e.title, f.data FROM dart_event e
                           LEFT JOIN dart_filing f ON f.rcept_no=e.rcept_no WHERE e.kind='biz' AND e.date>=? ORDER BY e.date DESC""", (since,)).fetchall()
    out = []
    for no, d, code, name, title, data in rows:
        if not any(k in (title or '') for k in BIZ_KEYS):
            continue
        p = conn.execute('SELECT mcap, close FROM price_daily WHERE code=? ORDER BY date DESC LIMIT 1', (code,)).fetchone()
        body = (json.loads(data).get('body') if data else None) or ''
        kind = 'license' if any(k in title for k in ('기술이전', '라이선스', '라이센스')) else 'regulatory' if any(k in title for k in ('허가', '승인', 'FDA')) else 'readout'
        out.append({'kind': kind, 'company': name, 'ticker': code, 'filed': d, 'date': None, 'date_text': None, 'sentence': (title or '') + (' — ' + body if body else ''),
                    'url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}', 'mcap': p[0] if p and p[0] else None, 'price': p[1] if p else None})
    return out


if __name__ == '__main__':
    code = sys.argv[1] if len(sys.argv) > 1 else '196170'
    print(json.dumps(market(code), ensure_ascii=False))
    f = financials(code)
    print(json.dumps({k: v for k, v in (f or {}).items() if k != 'quarters'}, ensure_ascii=False, indent=1))
    for x in (f or {}).get('quarters', []):
        print(x['label'], {k: (round(v, 1) if isinstance(v, float) else v) for k, v in x.items() if k not in ('end', 'label')})
