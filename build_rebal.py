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
  없으면 FnGuide 를 쓰되 '확인 필요'로 표시한다.

자료
- KBJ 도커 DB(kbj-db-1): prv_etf.holding(운용사 PDF — 날짜 D 의 금액은 D−1 종가), prv_etf.etf_daily(기초지수·순자산), prv_etf.meta(배수)
- db/history.db hp: 종가·시총·거래대금
- FnGuide 유동비율: navercomp c1010001 '발행주식수/유동비율' (.cache/ff_cache.json 에 7일 보관)
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


def choose(ff_fn, ff_pdf, override=None):
    """(쓸 방법, 확인 필요 여부). 기본 FnGuide. 유동비율 차이가 GAP_PP 를 넘으면 override 를 따르고, 없으면 확인 필요"""
    if ff_pdf is None or ff_fn is None:
        return ('PDF' if ff_fn is None and ff_pdf is not None else 'FnGuide'), False
    if override:
        return override['use'], False
    return 'FnGuide', abs(ff_fn - ff_pdf) > GAP_PP


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

def build_basis(ev: dict, basis: str, hist: Hist, fn: dict, dates: dict, log=print) -> dict:
    px, mc = hist.on(basis)
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
            src, check = choose(f and f['ff'], ff_pdf, ev.get('overrides', {}).get(c))
            r = r_pdf if src == 'PDF' else r_fn
            new.append({'c': c, 'n': n, 'pb': p, 'mc': mc.get(c), 'sh': f and f['sh'], 'ff_fn': f and f['ff'], 'ff_pdf': ff_pdf,
                        'r': r, 'r_fn': r_fn, 'r_pdf': r_pdf, 'src': src, 'check': check,
                        'why': ev.get('overrides', {}).get(c, {}).get('why'), 'ests': ests, 'tv20': hist.adv(c, basis)})
        outs = [{'c': c, 'n': n, 'pb': px.get(c), 'mc': mc.get(c), 'w': T.get(c, {}).get('w'), 'tv20': hist.adv(c, basis)} for c, n in cfg['out']]
        dn = denom([x['r'] for x in new if x['r']], [o['w'] for o in outs if o['w']])
        for x in new:
            for k in ('r', 'r_fn', 'r_pdf'):
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
                     'w': r6(x['w']), 'w_fn': r6(x['w_fn']), 'w_pdf': r6(x['w_pdf']), 'src': x['src'], 'check': x['check'], 'why': x['why'],
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
    B = build_basis(ev, basis, hist, fn, dates)
    if not B:
        print('계산할 지수가 없음 (PDF 날짜 확인)')
        return 1
    sb = ev['shinhan']['basis']
    check = shinhan_check(ev, B if sb == basis else build_basis(ev, sb, hist, fn, dates, log=lambda *_: None))
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
