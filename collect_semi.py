"""
반도체 탭: 해외 기업 분기 실적·capex (docs/semi-plan.md §2·§5.1) → db/semi.db

- 미국 상장(10-Q 를 내는 회사, semi_assets.json 의 src 'sec'): SEC EDGAR companyfacts(XBRL) — 매출·영업이익·유형자산 취득 5년치.
  손익은 3개월 값, 현금흐름은 누적이라 같은 시작일의 누적끼리 빼서 분기로 만든다(4분기 = 연간 − 9개월).
  User-Agent 는 .env 의 SEC_USER_AGENT (SEC 가 연락처를 요구한다).
- 그 밖(TSMC·ASML·도쿄일렉트론 등, src 'yf') 과 SEC 에 없는 항목: 야후 파이낸스 분기 손익·현금흐름 (최근 5~7분기).
- 회계연도가 달라(엔비디아 1월, 마이크론 8월 결산 …) 분기 끝에서 45일 앞이 든 달력 분기로 맞춘다 (cq '2026Q3').
- 시총: 야후 파이낸스 (상장 통화) + 달러 환산.

python3 collect_semi.py          # 전부
python3 collect_semi.py --tk MU  # 한 종목
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

import config  # noqa: F401  (.env → 환경변수)

ROOT = Path(__file__).parent
DB = ROOT / 'db' / 'semi.db'
ASSETS = ROOT / 'semi_assets.json'
log = logging.getLogger('semi')

SCHEMA = """
CREATE TABLE IF NOT EXISTS ov_q (
    tk TEXT, cq TEXT, metric TEXT,      -- metric: rev / op / capex (capex 는 양수)
    value REAL, cur TEXT, end TEXT, src TEXT,   -- value: 백만 (회사 통화), end: 실제 분기 끝
    PRIMARY KEY (tk, cq, metric)
);
CREATE TABLE IF NOT EXISTS ov_meta (
    tk TEXT PRIMARY KEY, name TEXT, cur TEXT, mcap REAL, mcap_cur TEXT, mcap_usd REAL, fx_usd REAL, at TEXT
);
"""

# SEC 항목 후보 — 회사마다 쓰는 이름이 달라 가장 최근까지 이어지는 것을 쓰고, 빈 기간은 다른 후보로 채운다
SEC_TAGS = {
    'rev': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'],
    'op': ['OperatingIncomeLoss'],
    'capex': ['PaymentsToAcquirePropertyPlantAndEquipment', 'PaymentsToAcquireProductiveAssets'],
}
YF_ROWS = {'rev': ('income', 'Total Revenue'), 'op': ('income', 'Operating Income'), 'capex': ('cash', 'Capital Expenditure')}
SINCE = '2021-01-01'


def connect(path=DB):
    conn = sqlite3.connect(str(path), timeout=30)
    conn.executescript(SCHEMA)
    return conn


def cal_q(end: str) -> str:
    """분기 끝 → 달력 분기 (끝에서 45일 앞이 든 분기). 2026-10-26 → 2026Q3, 2026-08-27 → 2026Q3"""
    d = date.fromisoformat(end) - timedelta(days=45)
    return f'{d.year}Q{(d.month - 1) // 3 + 1}'


def _days(st: str, en: str) -> int:
    return (date.fromisoformat(en) - date.fromisoformat(st)).days


def quarterize(facts: dict) -> dict:
    """{(시작, 끝): 값} → {끝: 3개월 값}. 3개월(80~100일) 값이 먼저, 없으면 같은 시작일의 누적끼리 뺀다"""
    q = {en: v for (st, en), v in facts.items() if 80 <= _days(st, en) <= 100}
    by_start = {}
    for (st, en), v in facts.items():
        by_start.setdefault(st, []).append((en, v))
    for st, rows in by_start.items():
        rows.sort()
        for (e0, v0), (e1, v1) in zip(rows, rows[1:]):
            if e1 not in q and 80 <= _days(e0, e1) <= 100:
                q[e1] = v1 - v0
    return q


def sec_series(facts_json: dict) -> dict:
    """companyfacts → {metric: {끝: 백만 달러}}"""
    g = facts_json.get('facts', {}).get('us-gaap', {})
    out = {}
    for m, tags in SEC_TAGS.items():
        merged = {}
        series = []
        for tag in tags:
            pts = {}
            for x in g.get(tag, {}).get('units', {}).get('USD', []):
                if x.get('form') not in ('10-Q', '10-K', '10-Q/A', '10-K/A') or not x.get('start') or x['end'] < SINCE:
                    continue
                k = (x['start'], x['end'])
                if k not in pts or x.get('filed', '') > pts[k][1]:       # 같은 기간은 최근 제출본
                    pts[k] = (x['val'], x.get('filed', ''))
            qs = quarterize({k: v for k, (v, _) in pts.items()})
            if qs:
                series.append(qs)
        series.sort(key=lambda s: max(s), reverse=True)      # 가장 최근까지 이어지는 이름이 먼저
        for s in series:
            for e, v in s.items():
                merged.setdefault(e, v)
        out[m] = {e: v / 1e6 * (-1 if m == 'capex' and v < 0 else 1) for e, v in merged.items()}
    return out


def yf_series(tk: str):
    """야후 파이낸스 → ({metric: {끝: 백만}}, 재무 통화, 시총, 시총 통화)"""
    import yfinance as yf
    t = yf.Ticker(tk)
    frames = {'income': t.quarterly_income_stmt, 'cash': t.quarterly_cashflow}
    out = {}
    for m, (f, row) in YF_ROWS.items():
        df = frames[f]
        if df is None or df.empty or row not in df.index:
            continue
        s = {}
        for col, v in df.loc[row].items():
            if v == v and v is not None:      # NaN 빼기
                s[str(col)[:10]] = abs(float(v)) / 1e6 if m == 'capex' else float(v) / 1e6
        out[m] = s
    info = {}
    try:
        info = t.info or {}
    except Exception:        # 야후 info 는 자주 막힌다 — 통화만 못 얻는다
        pass
    fi = t.fast_info
    return out, info.get('financialCurrency') or fi.get('currency'), fi.get('marketCap'), fi.get('currency')


_fx = {}


def fx_usd(cur: str) -> float:
    """1 통화 = ? 달러 (야후 환율). 실패하면 None"""
    if not cur or cur == 'USD':
        return 1.0
    if cur not in _fx:
        import yfinance as yf
        try:
            _fx[cur] = float(yf.Ticker(f'{cur}USD=X').fast_info['lastPrice'])
        except Exception:
            _fx[cur] = None
    return _fx[cur]


def save(conn, tk, series, cur, src):
    rows = []
    for m, s in series.items():
        for en, v in s.items():
            if en >= SINCE:
                rows.append((tk, cal_q(en), m, round(v, 3), cur, en, src))
    with conn:
        conn.executemany('INSERT OR REPLACE INTO ov_q VALUES (?, ?, ?, ?, ?, ?, ?)', rows)
    return len(rows)


KR_CAPEX = {'005930': '삼성전자', '000660': 'SK하이닉스', '000990': 'DB하이텍'}     # 국내 팹: 현금흐름표 유형자산 취득 (누적 → 분기)


def kr_capex(session, key, corp: str, years) -> dict:
    """DART 전체 재무제표(연결) 현금흐름표의 유형자산 취득 → {(시작, 끝): 백만원}. 분기보고서 값은 연초부터 누적"""
    out = {}
    for y in years:
        for rc, end in (('11013', f'{y}-03-31'), ('11012', f'{y}-06-30'), ('11014', f'{y}-09-30'), ('11011', f'{y}-12-31')):
            try:
                j = session.get('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json',
                                params={'crtfc_key': key, 'corp_code': corp, 'bsns_year': str(y), 'reprt_code': rc, 'fs_div': 'CFS'}, timeout=60).json()
            except (requests.RequestException, ValueError):
                continue
            time.sleep(0.15)
            for a in j.get('list') or []:
                if a.get('sj_div') == 'CF' and (a.get('account_id', '').startswith('ifrs-full_PurchaseOfPropertyPlantAndEquipment')
                                                or a.get('account_nm', '').replace(' ', '') == '유형자산의취득'):
                    v = str(a.get('thstrm_amount') or '').replace(',', '')
                    try:
                        out[(f'{y}-01-01', end)] = abs(float(v)) / 1e6
                    except ValueError:
                        pass
                    break
    return out


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    ap = argparse.ArgumentParser()
    ap.add_argument('--tk', help='이 티커만')
    args = ap.parse_args()
    stocks = [s for s in json.loads(ASSETS.read_text(encoding='utf-8'))['stocks'] if s.get('tk') and (not args.tk or s['tk'] == args.tk)]
    ua = os.environ.get('SEC_USER_AGENT', '').strip()
    conn = connect()
    sess = requests.Session()
    sess.headers['User-Agent'] = ua
    cik = {}
    if ua and any(s['src'] == 'sec' for s in stocks):
        try:
            m = sess.get('https://www.sec.gov/files/company_tickers.json', timeout=30).json()
            cik = {v['ticker']: v['cik_str'] for v in m.values()}
        except requests.RequestException as e:
            log.warning('SEC 티커 목록 실패: %s', type(e).__name__)
    elif not ua:
        log.info('SEC_USER_AGENT 없음 — 미국 회사도 야후 파이낸스로만')
    ok = fail = 0
    for s in stocks:
        tk = s['tk']
        try:
            series, cur, src = {}, 'USD', 'yf'
            if s['src'] == 'sec' and tk in cik:
                j = sess.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik[tk]:010d}.json', timeout=60).json()
                series, src = sec_series(j), 'sec'
                time.sleep(0.15)       # SEC: 초당 10회 이하
            yfs, ycur, mcap, mcur = yf_series(tk)
            if src == 'yf':
                series, cur = yfs, ycur or 'USD'
            else:            # SEC 에 없거나 끊긴 항목(KLA 영업이익 등)은 야후 값으로 최근 분기만 채운다
                for m, ys in yfs.items():
                    have = {cal_q(e) for e in series.get(m) or {}}
                    last = max(have, default='')
                    for en, v in ys.items():
                        if cal_q(en) > last:
                            series.setdefault(m, {})[en] = v
            n = save(conn, tk, series, cur, src)
            fx = fx_usd(mcur)
            with conn:
                conn.execute('INSERT OR REPLACE INTO ov_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                             (tk, s['n'], cur, mcap, mcur, mcap * fx if mcap and fx else None, fx_usd(cur),
                              datetime.now().isoformat(timespec='seconds')))
            log.info('%s %s: %d줄 (%s)', tk, s['n'], n, src)
            ok += 1
        except Exception as e:
            fail += 1
            log.warning('%s 실패: %s %s', tk, type(e).__name__, str(e)[:80])
    dkey = os.environ.get('DART_API_KEY', '')
    if dkey and not args.tk:        # 삼성·하이닉스·DB하이텍 설비투자 (증설 사이클의 공식 숫자)
        from collect_fund import corp_codes
        try:
            cc = corp_codes(sess, dkey)
            y0 = date.today().year
            for code, nm in KR_CAPEX.items():
                q = quarterize(kr_capex(sess, dkey, cc[code], range(y0 - 5, y0 + 1)))
                n = save(conn, code, {'capex': q}, 'KRW', 'dart')
                with conn:
                    conn.execute('INSERT OR REPLACE INTO ov_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                                 (code, nm, 'KRW', None, 'KRW', None, None, datetime.now().isoformat(timespec='seconds')))
                log.info('%s %s 설비투자: %d분기', code, nm, n)
        except Exception as e:
            log.warning('국내 설비투자 실패: %s', type(e).__name__)
    krw = fx_usd('KRW')           # 원화 환산용 (1원 = ? 달러)
    if krw:
        with conn:
            conn.execute('INSERT OR REPLACE INTO ov_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                         ('_KRW', '원화', 'KRW', None, None, None, krw, datetime.now().isoformat(timespec='seconds')))
    log.info('해외 %d종목, 실패 %d', ok, fail)
    return 1 if fail > len(stocks) // 3 else 0


if __name__ == '__main__':
    sys.exit(main())
