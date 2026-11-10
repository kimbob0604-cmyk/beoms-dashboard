"""
신고가 탭 데이터: 가격 이력으로 역사적·52주·120일·60일 신고가를 직접 계산 → public/data/high/{거래일}.json

예전에는 네이버 '52주 신고가' 목록을 날마다 저장해 썼다 (장중 고가 기준, 시총 제한 없음, 저장을 시작한 뒤의 기록만).
지금은 종가 기준으로 직접 계산한다. 판정 규칙은 newhigh.py.

가격:
- 화면용 DB(dashboard.db) price_daily 가 있는 날(첫날 = cut)은 그 값을 쓴다 — KRX 확정 종가·등락률.
- 그 전은 과거 가격 DB(history.db hp, 2010-01-04~). cut 전 이력은 바뀌지 않으므로 한 번 읽어 .cache/newhigh/ 에 둔다(약 10초).
- price_daily 보다 새 날짜의 시세(quote_live — 장중 10분마다, 장 마감 뒤 KRX 공개 전)가 있으면 그날을 마지막 칸으로 붙인다
  → 장중에는 '지금 가격이 종가라면' 기준의 잠정 판정이다(prov).

대상: 보통주, 회사 시총(우선주 포함) MIN_MCAP 억 이상.

  python3 build_newhigh.py          # 단독 실행 (build_naver.py 가 평소에 부른다)
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

import db
import newhigh as N
from universe import is_common

ROOT = Path(__file__).resolve().parent
HISTORY_DB = ROOT / 'db' / 'history.db'
CACHE = ROOT / '.cache' / 'newhigh'
KEEP = 420            # cut 전 이력에서 행렬로 들고 갈 거래일 수 (52주 창 + 최근 기록 계산용)
MIN_MCAP = 1000       # 억
RECENT = 20           # 최근 신고가 기록(횟수·연속)을 세는 거래일 수
SPAN = 120            # 날짜별 신고가 종목 수를 보여 줄 거래일 수


def load_base(cut: str, hist_path: Path = HISTORY_DB, cache: Path = CACHE) -> dict:
    """cut 전 이력 → {days, codes, C[종목, KEEP], pre, pre_bars, last_adj, last_raw}. cut 이 같으면 캐시를 읽는다."""
    f = cache / f'base_{cut}.npz'
    if f.exists():
        z = np.load(f, allow_pickle=False)
        return {k: (z[k].tolist() if k in ('days', 'codes') else z[k]) for k in z.files}
    h = sqlite3.connect(f'file:{hist_path}?mode=ro', uri=True)
    days = [r[0] for r in h.execute('SELECT DISTINCT date FROM hp WHERE date < ? ORDER BY date DESC LIMIT ?', (cut, KEEP))][::-1]
    pos = {d: i for i, d in enumerate(days)}
    start = days[0] if days else cut
    codes, rows_c, pre, pre_bars, last_adj, last_raw = [], [], [], [], [], []
    cur, buf = None, []

    def flush():
        if cur is None or not buf:
            return
        adj = N.chain([(c, g) for _, c, g in buf])
        row = [np.nan] * len(days)
        before = [a for (d, _, _), a in zip(buf, adj) if d < start]
        for (d, _, _), a in zip(buf, adj):
            if d in pos:
                row[pos[d]] = a
        codes.append(cur)
        rows_c.append(row)
        pre.append(max(before) if before else np.nan)
        pre_bars.append(len(before))
        last_adj.append(adj[-1])
        last_raw.append(buf[-1][1])

    for code, d, close, chg in h.execute(
            'SELECT code, date, close, chg FROM hp WHERE close IS NOT NULL AND date < ? ORDER BY code, date', (cut,)):
        if code != cur:
            flush()
            cur, buf = code, []
        buf.append((d, close, chg))
    flush()
    h.close()
    base = {'days': days, 'codes': codes, 'C': np.array(rows_c, dtype=float).reshape(len(codes), len(days)),
            'pre': np.array(pre, dtype=float), 'pre_bars': np.array(pre_bars, dtype=int),
            'last_adj': np.array(last_adj, dtype=float), 'last_raw': np.array(last_raw, dtype=float)}
    cache.mkdir(parents=True, exist_ok=True)
    for old in cache.glob('base_*.npz'):
        old.unlink()
    np.savez_compressed(f, **{k: (np.array(v) if k in ('days', 'codes') else v) for k, v in base.items()})
    return base


def recent_days(conn) -> list:
    """화면용 DB 의 날짜별 시세 [(날짜, {code: (종가, 등락률)}, 잠정 여부)] 오름차순. 마지막에 더 새 장중 시세가 있으면 붙인다."""
    out = []
    by = {}
    for d, code, close, chg in conn.execute(
            """SELECT p.date, p.code, p.close, COALESCE(o.chg, p.change_pct)
               FROM price_daily p LEFT JOIN ohlc_daily o ON o.date = p.date AND o.code = p.code
               WHERE p.close IS NOT NULL ORDER BY p.date"""):
        by.setdefault(d, {})[code] = (close, chg)
    final = {r[0] for r in conn.execute('SELECT DISTINCT date FROM ohlc_daily WHERE open IS NOT NULL')}
    for d in sorted(by):
        out.append((d, by[d], d not in final))
    live = conn.execute('SELECT MAX(date) FROM quote_live').fetchone()[0]
    if live and (not out or live > out[-1][0]):
        rows = {r[0]: (r[1], r[2]) for r in conn.execute(
            'SELECT code, close, change_pct FROM quote_live WHERE date = ? AND close IS NOT NULL', (live,))}
        # 저녁에 네이버 수급이 올라오면 그 응답의 정규장 종가가 있다. 통합 시세(넥스트레이드 포함)보다 KRX 종가에 가깝다
        for code, close in conn.execute('SELECT code, close FROM flow_daily WHERE date = ? AND close IS NOT NULL', (live,)):
            rows[code] = (close, None)
        if rows:
            out.append((live, rows, True))
    return out


def matrix(conn, base: dict, upto: str = None) -> dict:
    """base 뒤에 화면용 DB 의 날짜를 이어 붙인 행렬. cut 뒤에 상장한 종목은 줄을 새로 만든다. upto 를 주면 그날까지만."""
    extra = [x for x in recent_days(conn) if upto is None or x[0] <= upto]
    days = list(base['days']) + [d for d, _, _ in extra]
    idx = {c: i for i, c in enumerate(base['codes'])}
    codes = list(base['codes'])
    n0, k0 = len(codes), len(base['days'])
    for _, rows, _ in extra:
        for c in rows:
            if c not in idx:
                idx[c] = len(codes)
                codes.append(c)
    n = len(codes)
    C = np.full((n, len(days)), np.nan)
    C[:n0, :k0] = base['C']
    pre = np.full(n, np.nan); pre[:n0] = base['pre']
    pre_bars = np.zeros(n, dtype=int); pre_bars[:n0] = base['pre_bars']
    last = {c: (base['last_adj'][i], base['last_raw'][i]) for c, i in list(idx.items())[:n0] if i < n0}
    for j, (_, rows, _) in enumerate(extra):
        for c, (close, chg) in rows.items():
            adj = N.chain([(close, chg)], start=last.get(c))[0]
            last[c] = (adj, close)
            C[idx[c], k0 + j] = adj
    return {'days': days, 'codes': codes, 'idx': idx, 'C': C, 'pre': pre, 'pre_bars': pre_bars,
            'prov': bool(extra and extra[-1][2])}


def stock_info(conn, d: str) -> dict:
    """{code: n, mk, mc(회사 시총), p, ch, w, tv}. d 가 price_daily 보다 새 날(장중 시세)이면 가격·등락률·시총을 그 값으로 맞춘다."""
    from build_naver import market_info
    info, pd = market_info(conn, d)
    tv = {r[0]: r[1] for r in conn.execute('SELECT code, trd_val FROM price_daily WHERE date = ?', (pd,))}
    for c, i in info.items():
        i['tv'] = tv.get(c)
    if pd and d > pd:
        for code, name, market, close, chg, mcap, trd in conn.execute(
                'SELECT code, name, market, close, change_pct, mcap, trd_val FROM quote_live WHERE date = ?', (d,)):
            if not close:
                continue
            i = info.setdefault(code, {'n': name, 'mk': market, 'mc': round(mcap or 0), 'p': None, 'ch': None, 'w': None})
            i['tv'] = trd
            if i.get('pd') == d:          # market_info 가 이미 그날 정규장 종가(수급 응답)로 맞췄다
                continue
            if i.get('p') and i.get('mc'):
                i['mc'] = round(i['mc'] * close / i['p'])
            i.update(p=close, ch=chg, pd=d)
    return info


def build(conn, m: dict = None, flows: dict = None, gx: dict = None) -> dict:
    cut = conn.execute('SELECT MIN(date) FROM price_daily').fetchone()[0]
    m = m or matrix(conn, load_base(cut))
    days, C = m['days'], m['C']
    d = days[-1]
    info = stock_info(conn, d)
    uni = [c for c in m['codes'] if is_common(c) and (info.get(c) or {}).get('mc', 0) >= MIN_MCAP
           and not np.isnan(C[m['idx'][c], -1])]
    rows = np.array([m['idx'][c] for c in uni], dtype=int)
    Cu, pre, pb = C[rows], m['pre'][rows], m['pre_bars'][rows]
    L = N.history(Cu, days, SPAN, pre, pb)                    # [종목, SPAN] 라벨 (-1 없음)
    any20 = L[:, -RECENT:] >= 0
    run, n20 = N.run_length(any20), any20.sum(axis=1)
    top20 = (L[:, -RECENT:] >= 0) & (L[:, -RECENT:] <= N.RANK['w52'])    # 52주 이상
    fd = (flows or {}).get('date')

    def row(k, extra):
        c = uni[k]
        i = info[c]
        f = (flows or {}).get('by', {}).get(c) or {}
        return {'c': c, 'n': i['n'], 'mk': i['mk'], 'w': i.get('w'), 'mc': i['mc'], 'p': i['p'], 'ch': i['ch'],
                'tv': round(i['tv']) if i.get('tv') else None,
                'f1': f.get('f1') if fd == d else None, 'o1': f.get('o1') if fd == d else None,
                'f5': f.get('f5'), 'o5': f.get('o5'), 'gx': (gx or {}).get(c), **extra}

    today, recent = [], []
    for k in range(len(uni)):
        lab = int(L[k, -1])
        if lab >= 0:
            today.append(row(k, {'ax': N.AXES[lab], 'run': int(run[k]), 'n20': int(n20[k]),
                                 'new': bool(L.shape[1] < 2 or L[k, -2] < 0)}))
        if not (0 <= lab <= N.RANK['w52']) and top20[k].any():
            j = int(np.flatnonzero(top20[k])[-1])              # 최근 20일 안 마지막 52주 이상 신고가
            t = len(days) - RECENT + j
            recent.append(row(k, {'ax': N.AXES[int(L[k, -RECENT + j])], 'last': days[t], 'n20': int(top20[k].sum()),
                                  'since': round(float(Cu[k, -1] / Cu[k, t] - 1), 4)}))
    counts = [[days[len(days) - L.shape[1] + j]] + [int((L[:, j] == r).sum()) for r in range(len(N.AXES))]
              for j in range(L.shape[1])]
    at = conn.execute('SELECT MAX(at) FROM quote_live WHERE date = ?', (d,)).fetchone()[0]
    return {'date': d, 'at': at, 'prov': m['prov'], 'basis': 'close', 'min_mc': MIN_MCAP, 'universe': len(uni),
            'days': RECENT, 'hist_from': '2010-01-04', 'flow_date': fd,
            'today': today, 'recent': recent, 'counts': counts}


def write_all(conn, backfill: int = 0) -> dict:
    """가장 최근 날 + (backfill 이 있으면) 그 전 backfill 거래일을 새 형식으로 쓴다. 가장 최근 날의 데이터를 돌려준다."""
    from build_naver import DATA, build_flow, growth_extract, write_dates, write_json
    cut = conn.execute('SELECT MIN(date) FROM price_daily').fetchone()[0]
    base = load_base(cut)
    last = recent_days(conn)[-1][0]
    targets = [last] + [r[0] for r in conn.execute(
        'SELECT DISTINCT date FROM price_daily WHERE date < ? ORDER BY date DESC LIMIT ?', (last, backfill))]
    out = None
    for d in targets:
        fd = conn.execute('SELECT MAX(date) FROM flow_daily WHERE date <= ?', (d,)).fetchone()[0]
        flows = {'date': fd, 'by': {s['c']: s for s in build_flow(conn, fd)['stocks']}} if fd else None
        data = build(conn, matrix(conn, base, d), flows, growth_extract(d))
        write_json(DATA / 'high' / f'{d}.json', data)
        out = out or data
    keep = {p.stem for p in (DATA / 'high').glob('20*.json')}
    for p in (DATA / 'high').glob('20*.json'):          # 옛 형식(네이버 목록) 파일은 지운다
        try:
            if 'counts' not in json.loads(p.read_text(encoding='utf-8')):
                p.unlink()
        except ValueError:
            p.unlink()
    write_dates(DATA / 'high')
    return out


def main() -> int:
    conn = db.connect()
    if '--backfill' in sys.argv:
        n = int(sys.argv[sys.argv.index('--backfill') + 1])
        data = write_all(conn, n)
        print(f'high/: {n + 1}일 다시 씀')
    else:
        data = build(conn)
    by = {a: sum(1 for s in data['today'] if s['ax'] == a) for a in N.AXES}
    print(f"{data['date']}{' (잠정)' if data['prov'] else ''}: 대상 {data['universe']}종목 · "
          + ' · '.join(f'{N.LABEL[a]} {by[a]}' for a in N.AXES) + f" · 최근 {len(data['recent'])}")
    for a in N.AXES:
        print(f'  {N.LABEL[a]}:', ', '.join(f"{s['n']} {s['ch']:+.1f}%" for s in sorted(
            (s for s in data['today'] if s['ax'] == a), key=lambda s: -s['mc'])[:14]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
