"""
지수 정기변경 패시브 유입 추정 → public/data/rebal.json (수급 탭 '지수 정기변경' 칸)

신한투자증권 방식(한국경제 2026-11-19): 예상 유입액 = 추종 ETF 순자산 × 편입 후 지수 내 유동시총 비중,
패시브 효과 = 예상 유입액 ÷ 최근 20일 평균 거래대금. 계획과 1단계 검증은 docs/passive-inflow-plan.md.
명단·일정·유동비율 예외는 rebal_event.json.

비중 구하기
- PDF 역산: KRX 가 만든 다른 지수(KRX300·KRX 헬스케어·코스닥 글로벌·KRX 섹터)는 코스피200·코스닥150 과 같은 유동비율을 쓴다
  (기준 종목의 비중 비율이 0.5% 안쪽으로 맞는다). 신규 종목 N 이 그 PDF 에 있으면
  r_N = N 의 그 PDF 비중 ÷ x, x = 기준 종목들의 (그 PDF 비중 ÷ 대상 지수 비중) 중앙값.
- FnGuide 보정: r_N = 유동시총(발행주식 × 종가 × FnGuide 유동비율) ÷ T,
  T = 기존 구성종목의 (FnGuide 유동시총 ÷ 지금 비중) 중앙값 = 지금 지수 유동시총 추정치.
- 편입 후 비중 w_N = r_N ÷ (1 + 신규 r 합 − 편출 종목 지금 비중 합).
- 고르기: 기본 FnGuide. 12월 정기변경 때 KRX 가 유동비율을 다시 매기는데, 최신 지분을 담은 FnGuide 가 신한 숫자에 더 가까웠다
  (오차 중앙 2.0% 대 PDF 5.3%). 두 유동비율이 9%p 넘게 다르면 rebal_event.json overrides(DART 로 확인한 사유)를 따르고,
  없으면 DART 자동 규칙(dart_auto)을 따르고, 그래도 못 정하면 FnGuide 를 쓰되 '확인 필요'로 표시한다.
- DART 근거: 정기보고서 최대주주 등·자사주(1 − 둘 = DART 유동비율)와 유동비율 기준 구간(rebal_event.json ff_window,
  6월·12월 정기변경 심사기준일 추정) 안의 지분 공시. FnGuide 와 4%p 넘게 다르면 'DART 다름'으로 표시만 한다.

자료
- KBJ 도커 DB(kbj-db-1): prv_etf.holding(운용사 PDF — 날짜 D 의 금액은 D−1 종가), prv_etf.etf_daily(기초지수·순자산), prv_etf.meta(배수)
- db/history.db hp: 종가·시총·거래대금
- FnGuide 유동비율: navercomp c1010001 '발행주식수/유동비율' (.cache/ff_cache.json 에 7일 보관)
- DART: hyslrSttus(최대주주 현황)·stockTotqySttus(주식 총수)·list.json (.cache/dart_hold.json, DART_API_KEY 없으면 건너뜀)
KBJ 컨테이너가 없으면(다른 컴퓨터) 아무것도 하지 않고 4로 끝난다. 설정의 show_until 이 지나도 4.

  python3 build_rebal.py                    # hp 최신 종가 기준
  python3 build_rebal.py --date 2026-11-17  # 기준일 지정
"""

import argparse
import csv
import io
import json
import sqlite3
import statistics as st
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVENT = ROOT / 'rebal_event.json'
OUT = ROOT / 'public' / 'data' / 'rebal.json'
HDB = ROOT / 'db' / 'history.db'
FF_CACHE = ROOT / '.cache' / 'ff_cache.json'
CONTAINER = 'kbj-db-1'
FF_TTL_DAYS = 7
MIN_QTY = 20          # PDF 1CU 수량이 이보다 작은 기준 종목은 반올림 오차가 커서 뺀다 (KODEX 200 중간값 47주, 적은 종목 1주)
ANCHOR_TOL = 0.03     # 기준 종목 비율이 중앙값에서 3% 넘게 벗어나면 뺀다 (상한이 걸린 종목)
GAP_PP = 0.09         # PDF·FnGuide 유동비율이 이보다 많이 다르면 DART 확인 대상
ADV_N = 20
PRICE_TOL = 1e-4
DART_CACHE = ROOT / '.cache' / 'dart_hold.json'
DART_MOVE = 0.03      # 자동 규칙: 비유동 지분이 이만큼 넘게 바뀌면 지분 변동으로 본다
DART_FLAT = 0.01      # 자동 규칙: 이 안쪽이면 지분 변동 없음
DART_GAP = 0.04       # DART 유동비율(1 − 최대주주 등 − 자사주)이 FnGuide 와 이보다 다르면 'DART 다름' 표시
DART_RETRY_DAYS = 3   # 정기보고서가 아직 없으면 이만큼 지나 다시 받는다


# ---------- 계산 (입출력 없음) ----------

def anchor_ratio(P: dict, T: dict, min_qty=MIN_QTY, tol=ANCHOR_TOL):
    """같은 유동비율을 쓰는 PDF P 와 대상 지수 PDF T 의 공통 종목으로 x = P 비중 ÷ T 비중 의 중앙값. (x, 기준 종목 수) 또는 None"""
    xs = [P[c]['w'] / T[c]['w'] for c in P if c in T and P[c]['qty'] >= min_qty and T[c]['qty'] >= min_qty and T[c]['w'] > 0]
    if len(xs) < 5:
        return None
    m = st.median(xs)
    xs = [x for x in xs if abs(x / m - 1) < tol]
    if len(xs) < 5:
        return None
    return st.median(xs), len(xs)


def calib_total(T: dict, fn: dict, px: dict, min_qty=MIN_QTY):
    """FnGuide 유동시총 ÷ 지금 비중 의 중앙값 = 지수 유동시총 추정치(원). 오차 분포도 같이"""
    v = [(fn[c]['sh'] * px[c] * fn[c]['ff'] / e['w']) for c, e in T.items()
         if fn.get(c) and px.get(c) and e['qty'] >= min_qty and e['w'] > 0]
    if len(v) < 10:
        return None
    m = st.median(v)
    dev = sorted(abs(x / m - 1) for x in v)
    return {'T': m, 'n': len(v), 'med_abs': st.median(dev), 'p75': dev[len(dev) * 3 // 4], 'p90': dev[len(dev) * 9 // 10]}


def pdf_estimates(code: str, pdfs: dict, capped: set):
    """같은 유동비율 PDF 마다 r = 그 PDF 비중 ÷ x. [(이름, r, 수량, 상한 지수 여부)]"""
    out = []
    for name, (P, x) in pdfs.items():
        if code in P and P[code]['w'] > 0:
            out.append((name, P[code]['w'] / x, P[code]['qty'], name in capped))
    return out


def combine(ests):
    """상한 지수를 뺀 PDF 추정치를 수량으로 가중 평균 (수량이 많을수록 1CU 반올림 오차가 작다)"""
    use = [e for e in ests if not e[3]]
    if not use:
        return None
    return sum(e[1] * e[2] for e in use) / sum(e[2] for e in use)


def choose(ff_fn, ff_pdf, override=None, auto=None):
    """(쓸 방법, 확인 필요 여부). override(사람이 DART 로 확인: FnGuide·PDF·DART)가 있으면 먼저 따른다.
    기본 FnGuide. 유동비율 차이가 GAP_PP 를 넘으면 auto(dart_auto 자동 규칙)를 따르고, 없으면 FnGuide 를 쓰되 확인 필요"""
    if override and {'FnGuide': ff_fn, 'PDF': ff_pdf, 'DART': True}.get(override['use']) is not None:
        return override['use'], False
    if ff_pdf is None or ff_fn is None:
        return ('PDF' if ff_fn is None and ff_pdf is not None else 'FnGuide'), False
    if abs(ff_fn - ff_pdf) <= GAP_PP:
        return 'FnGuide', False
    return (auto, False) if auto else ('FnGuide', True)


def dart_auto(d, gap):
    """두 유동비율이 GAP_PP 넘게 다를 때 DART 비유동 지분 변화 d(최대주주 등 + 자사주, 늘면 +)로 고르기.
    FnGuide − PDF 차이(gap)를 설명하는 방향으로 DART_MOVE 넘게 바뀌었으면 FnGuide(최신 지분 반영),
    DART_FLAT 안쪽이면 PDF(지분은 그대로라 KRX 정의 차이로 보고 6월 값 유지), 그 사이나 반대 방향이면 None(사람이 확인)"""
    if d is None or gap is None:
        return None
    if abs(d) >= DART_MOVE and d * gap < 0:
        return 'FnGuide'
    if abs(d) < DART_FLAT:
        return 'PDF'
    return None


def quarter_periods(start: str, end: str):
    """유동비율 기준 구간 [start, end] 를 보는 정기보고서 기들: start 120일 전 ~ end 사이 분기 말. [(사업연도, 보고서 코드, 분기 말)]"""
    lo = (date.fromisoformat(start) - timedelta(days=120)).isoformat()
    code = {3: '11013', 6: '11012', 9: '11014', 12: '11011'}
    out = []
    for y in range(int(lo[:4]), int(end[:4]) + 1):
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            q = f'{y}-{m:02d}-{d}'
            if lo <= q <= end:
                out.append((str(y), code[m], q))
    return out


def dart_view(ser, evs, win, ff_fn, ff_pdf):
    """정기보고서 지분 ser([{d, hold, tsy}] 기 순, 없으면 None)와 지분 공시 evs 로 DART 근거를 만든다.
    - ff: 1 − 최대주주 등 − 자사주 (기준 구간 끝 이전 마지막 기. 분기보고서는 자사주 칸이 비어 앞 기 값을 이어 쓰고,
      그 뒤 자기주식 결과보고서(evs 의 tsy)가 있으면 그 비율)
    - d: 기준 구간 시작 전 마지막 기 → 끝 이전 마지막 기 비유동 지분 변화
    - ev: 구간 시작 뒤 지분 공시 (기관의 약식 대량보유는 유동주식이라 뺀다), 구간 끝 뒤는 late
    - flag: FnGuide 와 DART_GAP 넘게 다를 때. PDF 와 FnGuide 가 2%p 안쪽으로 같으면(보호예수 등 KRX 도 빼는 몫) 안 함"""
    ser = [s for s in ser if s and s.get('hold') is not None]
    if not ser:
        return None
    rows, last, last_d = [], None, None
    for s in ser:
        if s.get('tsy') is not None:
            last, last_d = s['tsy'], s['d']
        rows.append((s['d'], s['hold'], last if last is not None else 0.0, last_d))
    base = [r for r in rows if r[0] <= win[0]]
    upto = [r for r in rows if r[0] <= win[1]] or rows
    cur = upto[-1]
    # 분기보고서에는 자사주 표가 없어, 그 기 뒤 ~ 구간 끝 사이 자기주식 취득·처분 결과보고서의 보유 비율이 있으면 그것을 쓴다
    tq = [e for e in evs if e.get('tsy') is not None and cur[0] < e['d'] <= win[1]]
    if tq:
        cur = (cur[0], cur[1], tq[-1]['tsy'], tq[-1]['d'])
    ff = 1 - cur[1] - cur[2]
    d = (cur[1] + cur[2]) - (base[-1][1] + base[-1][2]) if base and base[-1][0] != cur[0] else None
    ev = [[e['d'], e['t'], e['f'], e['no'], e['d'] > win[1]] for e in evs
          if e['d'] > win[0] and not ('대량보유' in e['t'] and '약식' in e['t'])]
    flag = ff_fn is not None and abs(ff - ff_fn) > DART_GAP and not (ff_pdf is not None and abs(ff_pdf - ff_fn) <= 0.02)
    return {'s': [[r[0], round(r[1], 4), round(r[2], 4)] for r in rows], 'ff': round(ff, 4), 'ff_d': cur[0],
            'tsy_d': cur[3], 'd': None if d is None else round(d, 4), 'd_from': base[-1][0] if d is not None else None, 'ev': ev, 'flag': flag}


def auto_why(auto, dv) -> str:
    """자동 규칙으로 고른 이유 (화면 '고른 이유')"""
    span = f"DART 최대주주 등+자사주 {dv['d_from'][2:7].replace('-', '.')}→{dv['ff_d'][2:7].replace('-', '.')} {dv['d'] * 100:+.1f}%p"
    if auto == 'FnGuide':
        return f'자동: {span} — 지분이 바뀌어 최신 지분을 담은 FnGuide'
    return f'자동: {span} — 지분이 그대로라 KRX 정의 차이로 보고 6월 값(PDF 역산)'


def denom(rs_new, w_out):
    """편입 후 지수 유동시총 ÷ 지금 지수 유동시총"""
    return 1 + sum(rs_new) - sum(w_out)


def adv(tvs):
    v = [x for x in tvs if x]
    return sum(v) / len(v) if len(v) >= 10 else None


# ---------- 입출력 ----------

def kbj_ok() -> bool:
    try:
        r = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', CONTAINER], capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and r.stdout.strip() == 'true'
    except Exception:
        return False


def kbj(sql: str) -> list:
    p = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'sh', '-c', 'psql -U ${POSTGRES_USER:-postgres} -d kbj --csv -q'],
                       input=sql, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:300])
    return list(csv.DictReader(io.StringIO(p.stdout)))


def lit(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


_pdf_cache = {}


def pdf(name: str, asof: str) -> dict:
    """운용사 PDF 의 주식 행 → {코드: {n, qty, val, w}} (w = 주식 금액 합 대비)"""
    key = (name, asof)
    if key not in _pdf_cache:
        rows = kbj(f"""select h.code, h.name, h.qty::float qty, h.val::float val from prv_etf.holding h
          where h.fund_id=(select fund_id from prv_etf.fund where name={lit(name)} limit 1) and h.asof={lit(asof)}""")
        rows = [r for r in rows if r['code'] and len(r['code']) == 6 and r['val'] not in ('', None) and float(r['val']) > 0]
        tot = sum(float(r['val']) for r in rows)
        _pdf_cache[key] = {r['code']: {'n': r['name'], 'qty': float(r['qty'] or 0), 'val': float(r['val']), 'w': float(r['val']) / tot}
                           for r in rows} if tot else {}
    return _pdf_cache[key]


def pdf_dates(names) -> dict:
    rows = kbj(f"""select f.name, h.asof::text a from prv_etf.holding h join prv_etf.fund f using(fund_id)
      where f.name in ({','.join(lit(n) for n in names)}) group by 1, 2""")
    out = {}
    for r in rows:
        out.setdefault(r['name'], []).append(r['a'])
    return {k: sorted(v) for k, v in out.items()}


def pdf_on_basis(name: str, basis: str, px: dict, dates: dict):
    """기준일 종가로 매긴 PDF 를 고른다 (보통 다음 거래일 날짜). (PDF, 날짜) 또는 (None, None)"""
    hi = (date.fromisoformat(basis) + timedelta(days=7)).isoformat()
    for a in [d for d in dates.get(name, []) if basis <= d <= hi]:
        P = pdf(name, a)
        if not P:
            continue
        hit = sum(1 for c, e in P.items() if e['qty'] and px.get(c) and abs(e['val'] / e['qty'] / px[c] - 1) < PRICE_TOL)
        if hit >= 0.6 * len(P):
            return P, a
    return None, None


def aum(cfg: dict, day: str) -> dict:
    """기초지수별 ETF 순자산(억). etf1·tr 은 1배·액티브 제외(신한식), act 는 같은 기초지수의 액티브, lev 는 2배"""
    bases = cfg['etf1'] + cfg['tr']
    rows = kbj(f"""with d as (select max(trade_date) t from prv_etf.etf_daily where trade_date<={lit(day)} and base_index in ({','.join(lit(b) for b in bases)}))
      select e.base_index b, e.name, coalesce(m.leverage, 1)::int lev, e.net_asset::float na, (select t from d)::text t
      from prv_etf.etf_daily e left join prv_etf.meta m on m.code=e.code
      where e.trade_date=(select t from d) and e.base_index in ({','.join(lit(b) for b in bases)}) and e.net_asset>0""")
    out = {'etf1': 0.0, 'tr': 0.0, 'act': 0.0, 'lev': 0.0, 'date': rows[0]['t'] if rows else None}
    for r in rows:
        v = r['na'] and float(r['na']) / 1e8
        if r['lev'] == '2':
            out['lev'] += v
        elif r['lev'] == '1':
            out['act' if '액티브' in r['name'] else ('tr' if r['b'] in cfg['tr'] else 'etf1')] += v
    return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in out.items()}


def fnguide(codes, log=print) -> dict:
    """FnGuide 발행주식수·유동비율. .cache/ff_cache.json 에 7일 보관"""
    import requests
    from collectors import wisereport as wr
    cache = json.loads(FF_CACHE.read_text()) if FF_CACHE.exists() else {}
    old = (date.today() - timedelta(days=FF_TTL_DAYS)).isoformat()
    need = [c for c in sorted(set(codes)) if c not in cache or cache[c].get('d', '') < old]
    if need:
        log(f'FnGuide 유동비율 {len(need)}종목 받는 중')
        s = requests.Session()
        s.headers['User-Agent'] = 'Mozilla/5.0'
        for i, c in enumerate(need):
            try:
                v = wr.fetch_float(s, c)
            except Exception:
                v = None
            cache[c] = {**(v or {}), 'd': date.today().isoformat()} if v else {**cache.get(c, {}), 'd': date.today().isoformat()}
            if i % 50 == 49:
                FF_CACHE.write_text(json.dumps(cache))
            time.sleep(0.25)
        FF_CACHE.write_text(json.dumps(cache))
    return {c: v for c, v in cache.items() if v.get('sh') and v.get('ff')}


def dart_holdings(codes, win, log=print) -> dict:
    """{코드: (정기보고서 지분 [{d, hold, tsy} 또는 None], 지분 공시 [...])}. .cache/dart_hold.json 에 보관:
    정기보고서는 한 번 받으면 그대로, 아직 없으면 DART_RETRY_DAYS 뒤 다시. 공시 목록은 하루 한 번.
    기준 구간 안 자기주식 취득·처분 결과보고서는 원문에서 보유 비율을 읽어 공시에 tsy 로 붙인다(접수번호별로 한 번).
    DART_API_KEY 가 없거나 고유번호를 못 받으면 빈 dict (DART 근거 없이 계산)"""
    import os
    import requests
    import config  # noqa: F401  (.env 로딩)
    from collect_fund import corp_codes
    from collectors import dart as D
    key = os.environ.get('DART_API_KEY')
    if not key:
        log('DART_API_KEY 없음 — DART 지분 확인 건너뜀')
        return {}
    s = requests.Session()
    try:
        cc = corp_codes(s, key)
    except Exception as e:
        log(f'DART 고유번호 못 받음 — 건너뜀: {e}')
        return {}
    cache = json.loads(DART_CACHE.read_text()) if DART_CACHE.exists() else {}
    P, E, Dc = cache.setdefault('p', {}), cache.setdefault('ev', {}), cache.setdefault('doc', {})
    today = date.today().isoformat()
    retry = (date.today() - timedelta(days=DART_RETRY_DAYS)).isoformat()
    pers = quarter_periods(*win)
    out, calls = {}, 0
    for c in sorted(set(codes)):
        corp = cc.get(c)
        if not corp:
            log(f'{c}: DART 고유번호 없음')
            continue
        ser = []
        for y, rc, _ in pers:
            k = f'{corp}:{y}:{rc}'
            hit = P.get(k)
            if not hit or (hit.get('v') is None and hit.get('f', '') < retry):
                try:
                    v = D.holder_share(D.fetch_periodic(s, key, 'hyslrSttus', corp, y, rc),
                                       D.fetch_periodic(s, key, 'stockTotqySttus', corp, y, rc))
                    P[k] = hit = {'f': today, 'v': v}
                except Exception as e:
                    log(f'{c} {y}/{rc} 지분 못 받음: {e}')
                    hit = hit or {'v': None}
                calls += 2
                time.sleep(0.12)
            ser.append(hit.get('v'))
        e = E.get(c)
        if not e or e.get('f') != today:
            try:
                E[c] = e = {'f': today, 'rows': D.holder_events(D.fetch_filings(s, key, corp, win[0].replace('-', ''), today.replace('-', '')))}
            except Exception as ex:
                log(f'{c} 공시 목록 못 받음: {ex}')
                e = e or {'rows': []}
            calls += 1
            time.sleep(0.12)
        rows = []
        for x in e['rows']:
            if '자기주식' in x['t'] and '결과보고서' in x['t'] and win[0] < x['d'] <= win[1]:
                if x['no'] not in Dc:
                    try:
                        Dc[x['no']] = D.parse_treasury_after(D.fetch_cells(s, key, x['no']))
                    except Exception as ex:
                        log(f'{c} {x["d"]} 자기주식 결과보고서 못 읽음: {ex}')
                    calls += 1
                    time.sleep(0.12)
                t = Dc.get(x['no'])
                x = {**x, 'tsy': t and t['rt']}
            rows.append(x)
        out[c] = (ser, rows)
    DART_CACHE.parent.mkdir(exist_ok=True)
    DART_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    if calls:
        log(f'DART 지분 {len(out)}종목 (API {calls}번)')
    return out


class Hist:
    def __init__(self, path=HDB):
        self.db = sqlite3.connect(str(path))

    def latest(self):
        return self.db.execute('select max(date) from hp').fetchone()[0]

    def on(self, d):
        rows = self.db.execute('select code, close, mcap from hp where date=?', (d,)).fetchall()
        return {c: p for c, p, _ in rows if p}, {c: m for c, _, m in rows if m}

    def adv(self, code, d):
        days = [r[0] for r in self.db.execute('select distinct date from hp where date<=? order by date desc limit ?', (d, ADV_N))]
        if not days:
            return None
        v = [r[0] for r in self.db.execute(f"select tv from hp where code=? and date in ({','.join('?' * len(days))})", (code, *days))]
        return adv(v)


# ---------- 한 기준일 계산 ----------

def build_basis(ev: dict, basis: str, hist: Hist, fn: dict, dates: dict, dh=None, log=print) -> dict:
    px, mc = hist.on(basis)
    dh, win = dh or {}, ev['ff_window']
    out = {}
    for key, cfg in ev['index'].items():
        T, t_asof = pdf_on_basis(cfg['target_pdf'], basis, px, dates)
        if not T:
            log(f'{key}: {basis} 종가 기준 {cfg["target_pdf"]} PDF 없음')
            continue
        cal = calib_total(T, fn, px)
        pdfs, used = {}, {}
        for name in cfg['same_ff_pdfs'] + cfg.get('capped_pdfs', []):
            P, a = pdf_on_basis(name, basis, px, dates)
            if not P:
                continue
            ar = anchor_ratio(P, T)
            if ar:
                pdfs[name] = (P, ar[0])
                used[name] = {'x': round(ar[0], 5), 'n': ar[1], 'asof': a}
        capped = set(cfg.get('capped_pdfs', []))
        new = []
        for c, n in cfg['in']:
            f, p = fn.get(c), px.get(c)
            sp = f['sh'] * p if f and p else None
            r_fn = sp * f['ff'] / cal['T'] if sp else None
            ests = pdf_estimates(c, pdfs, capped)
            r_pdf = combine(ests)
            ff_pdf = r_pdf * cal['T'] / sp if r_pdf and sp else None
            ff_fn = f and f['ff']
            dv = dart_view(*dh[c], win, ff_fn, ff_pdf) if c in dh else None
            gap = ff_fn - ff_pdf if ff_fn is not None and ff_pdf is not None else None
            auto = dart_auto(dv and dv['d'], gap) if gap is not None and abs(gap) > GAP_PP else None
            ov = ev.get('overrides', {}).get(c)
            r_dart = sp * dv['ff'] / cal['T'] if sp and dv else None
            src, check = choose(ff_fn, ff_pdf, ov, auto)
            if src == 'DART' and r_dart is None:
                src, check = 'FnGuide', True
            why = ov['why'] if ov else (auto_why(auto, dv) if auto and src == auto else None)
            if dv:
                dv['auto'] = auto
            r = r_pdf if src == 'PDF' else r_dart if src == 'DART' else r_fn
            new.append({'c': c, 'n': n, 'pb': p, 'mc': mc.get(c), 'sh': f and f['sh'], 'ff_fn': ff_fn, 'ff_pdf': ff_pdf,
                        'r': r, 'r_fn': r_fn, 'r_pdf': r_pdf, 'r_dart': r_dart, 'src': src, 'check': check, 'by': 'manual' if ov else ('auto' if why else None),
                        'why': why, 'ests': ests, 'tv20': hist.adv(c, basis), 'dart': dv})
        outs = [{'c': c, 'n': n, 'pb': px.get(c), 'mc': mc.get(c), 'w': T.get(c, {}).get('w'), 'tv20': hist.adv(c, basis)} for c, n in cfg['out']]
        dn = denom([x['r'] for x in new if x['r']], [o['w'] for o in outs if o['w']])
        for x in new:
            for k in ('r', 'r_fn', 'r_pdf', 'r_dart'):
                x['w' + k[1:]] = x[k] / dn if x[k] else None
            x['ests'] = [(e[0], e[1] / dn, e[2], e[3]) for e in x['ests']]
        out[key] = {'T': T, 't_asof': t_asof, 'cal': cal, 'pdfs': used, 'denom': dn, 'new': new, 'out': outs,
                    'aum': aum(cfg['aum'], basis), 'px': px}
    return out


def shinhan_check(ev: dict, B: dict) -> dict:
    """신한이 기사에 낸 숫자와 같은 기준일·같은 추종 자금으로 견줌"""
    rows = []
    for key, c, kind, v in ev['shinhan']['rows']:
        I = B.get(key)
        x = next((x for x in (I or {}).get('new', []) if x['c'] == c), None)
        if not x or not x['w']:
            continue
        A = I['aum']['etf1'] + I['aum']['tr']
        ours = x['w'] * 100 if kind == 'w' else A * x['w'] if kind == 'inflow' else (A * x['w'] / x['tv20'] * 100 if x['tv20'] else None)
        rows.append({'idx': key, 'c': c, 'n': x['n'], 'kind': kind, 'shinhan': v, 'ours': round(ours, 3 if kind == 'w' else 1), 'src': x['src'],
                     'err': round((ours / v - 1) * 100, 1)})
    errs = [abs(r['err']) for r in rows]
    return {'basis': ev['shinhan']['basis'], 'source': ev['shinhan']['source'], 'rows': rows,
            'med_abs': round(st.median(errs), 1) if errs else None}


def actual(ev: dict, dates: dict) -> dict:
    """적용일 뒤 대상 지수 PDF 에 신규 종목이 들어오면 실제 비중"""
    out = {}
    for key, cfg in ev['index'].items():
        ds = [d for d in dates.get(cfg['target_pdf'], []) if d > ev['effective']]
        if not ds:
            continue
        P = pdf(cfg['target_pdf'], ds[0])
        got = {c: P[c]['w'] for c, _ in cfg['in'] if c in P}
        if got:
            out[key] = {'asof': ds[0], 'w': got}
    return out


def r6(v):
    return None if v is None else round(v, 7)


def export(ev, basis, B, check, act) -> dict:
    idx = {}
    for key, I in B.items():
        cfg = ev['index'][key]
        A = act.get(key, {})
        idx[key] = {
            'name': cfg['name'], 'target_pdf': cfg['target_pdf'], 'pdf_asof': I['t_asof'],
            'aum': I['aum'], 'T': round(I['cal']['T'] / 1e8), 'denom': round(I['denom'], 5),
            'calib': {'n': I['cal']['n'], 'med_abs': round(I['cal']['med_abs'], 4), 'p75': round(I['cal']['p75'], 4), 'p90': round(I['cal']['p90'], 4)},
            'pdfs': I['pdfs'], 'actual_asof': A.get('asof'),
            'new': [{'c': x['c'], 'n': x['n'], 'pb': x['pb'], 'mc': x['mc'] and round(x['mc']), 'sh': x['sh'],
                     'ff_fn': x['ff_fn'], 'ff_pdf': x['ff_pdf'] and round(x['ff_pdf'], 4),
                     'w': r6(x['w']), 'w_fn': r6(x['w_fn']), 'w_pdf': r6(x['w_pdf']), 'w_dart': r6(x['w_dart']), 'src': x['src'], 'check': x['check'], 'why': x['why'],
                     'by': x['by'], 'dart': x['dart'],
                     'pdfs': [[e[0], r6(e[1]), int(e[2]), e[3]] for e in x['ests']],
                     'tv20': x['tv20'] and round(x['tv20'], 1), 'wa': r6(A.get('w', {}).get(x['c']))} for x in I['new']],
            'out': [{'c': o['c'], 'n': o['n'], 'pb': o['pb'], 'mc': o['mc'] and round(o['mc']), 'w': r6(o['w']),
                     'tv20': o['tv20'] and round(o['tv20'], 1)} for o in I['out']],
            # 장중 시세로 비중을 다시 매길 때 쓰는 기존 구성종목 [코드, 비중, 기준 종가]
            'cons': [[c, r6(e['w']), I['px'].get(c)] for c, e in I['T'].items() if I['px'].get(c)],
        }
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'basis': basis,
        'event': {k: ev[k] for k in ('id', 'title', 'announced', 'rebalance', 'effective', 'sources')},
        'gap_pp': GAP_PP, 'min_qty': MIN_QTY,
        'dart': {'win': ev['ff_window'], 'move': DART_MOVE, 'flat': DART_FLAT, 'gap': DART_GAP},
        'idx': idx, 'check': check,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', help='기준 종가 날짜 (기본: history.db 최신)')
    ap.add_argument('--out', default=str(OUT))
    a = ap.parse_args(argv)
    ev = json.loads(EVENT.read_text(encoding='utf-8'))
    if date.today().isoformat() > ev.get('show_until', '9999'):
        print(f'{ev["title"]}: 보여 줄 기간({ev["show_until"]})이 지남 — 건너뜀')
        return 4
    if not kbj_ok():
        print(f'KBJ DB 컨테이너({CONTAINER})가 없음 — 건너뜀')
        return 4
    hist = Hist()
    basis = a.date or hist.latest()
    names = sorted({n for cfg in ev['index'].values() for n in [cfg['target_pdf']] + cfg['same_ff_pdfs'] + cfg.get('capped_pdfs', [])})
    dates = pdf_dates(names)
    codes = {x[0] for cfg in ev['index'].values() for x in cfg['in'] + cfg['out']}
    px, _ = hist.on(basis)
    for cfg in ev['index'].values():
        T, _ = pdf_on_basis(cfg['target_pdf'], basis, px, dates)
        codes |= set(T or {})
    fn = fnguide(codes)
    dh = dart_holdings([c for cfg in ev['index'].values() for c, _ in cfg['in']], ev['ff_window'])
    B = build_basis(ev, basis, hist, fn, dates, dh)
    if not B:
        print('계산할 지수가 없음 (PDF 날짜 확인)')
        return 1
    sb = ev['shinhan']['basis']
    check = shinhan_check(ev, B if sb == basis else build_basis(ev, sb, hist, fn, dates, dh, log=lambda *_: None))
    data = export(ev, basis, B, check, actual(ev, dates))
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    for key, I in data['idx'].items():
        A = I['aum']['etf1'] + I['aum']['tr']
        top = sorted(I['new'], key=lambda x: -(A * x['w'] / x['tv20'] if x['w'] and x['tv20'] else 0))[:3]
        print(f"{I['name']}: 기준 {basis} · 추종 {A / 1e4:.1f}조 · 편입 {len(I['new'])} · "
              + ', '.join(f"{x['n']} {A * x['w']:.0f}억 ({A * x['w'] / x['tv20'] * 100:.0f}%)" for x in top))
    print(f"신한 대조 ({check['basis']}): {len(check['rows'])}개 오차 중앙 {check['med_abs']}% → {a.out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
