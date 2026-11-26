"""
ETF 기계적 수급 — KBJ 종목별 ETF 흐름 → public/data/etf_flow.json

KBJ(kbj/engines/etf/stock_flows.py)가 ETF 순설정·환매 금액에 운용사 PDF 구성 비중을 곱해 종목마다 더한 값이다.
'순유입 몫' = 설정·환매로 생긴 바스켓 매매 추정(LP·운용사가 실제로 사고판 금액). 주가 움직임 중 펀더멘털이 아닌 부분이 얼마인지 본다.
구성종목을 아는 ETF 만 들어가서(덮은 비율 coverage) 값은 하한이다.

기간(1·5·20일) × 정렬(순유입·순유출·거래대금 대비)마다 상위 100종목을 받아 기간마다 합쳐 한 파일로 만든다.
2026-11-26 부터 KBJ 사이트(com.kbj.site)를 굴리지 않으므로 KBJ 컨테이너에서 kbj_etf_periods.py 로 직접 받는다.
컨테이너가 꺼져 있으면 예전 사이트 내보내기(~/kbj-site/data/etf/stocks*.json)가 남아 있을 때만 그걸 쓴다.

하루 판정(day 블록, 2026-11-20 — newsbot 커버리지의 '기계적 수급'을 본뜸):
- KBJ 컨테이너(kbj-scheduler-1)가 돌면 kbj_etf_days.py 로 날짜별·전 종목 1일 순유입 몫을 받아 db/etf_flow.db 에 쌓는다
  (구성종목 PDF 가 처음 쌓인 2026-10-20 부터. 한 번 받은 날은 다시 받지 않고, 최근 2일은 늘 다시 받는다).
- 판정 = 그날 ETF 몫 ÷ 직전 20거래일 평균 거래대금(ADV20). ±5% 이상 매수·매도, ±10% 이상 강한 매수·매도, 그 아래는 영향 작음.
  (2026-10-20~11-19 에 ±2% 를 넘는 종목이 하루 100~360개라 5%·10% 로 잡았다. 화면에서 문턱을 바꾸면 다시 판정한다)
  몫이 1억 미만이면 비율이 커도 영향 작음. 주가 움직임 가운데 펀더멘털이 아닌 바스켓 매매가 얼마나 되는지 본다. 구성종목을 아는 ETF 만 더하므로 하한.
- 종목마다 일별 이력(최근 30거래일)·5·20일 누적, RSI(14)와 그 RSI 의 1년 중 위치(백분위), 
  순유입 큰 ETF 가운데 구성 비중(PDF)이 7일 넘게 묵은 것.

  python3 build_etf_flow.py
  python3 build_etf_flow.py --refetch     # 쌓인 날을 모두 다시 받기
"""

import json
import sqlite3
import subprocess
import sys
from bisect import bisect_left
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = Path.home() / 'kbj-site' / 'data' / 'etf'
OUT = ROOT / 'public' / 'data' / 'etf_flow.json'
DB = ROOT / 'db' / 'etf_flow.db'
MARKET_DB = ROOT / 'db' / 'dashboard.db'
CONTAINER = 'kbj-scheduler-1'           # KBJ 파이썬이 있는 컨테이너 (사이트용 kbj-api-1 은 2026-11-26 부터 안 띄운다)
FIRST_DAY = date(2026, 10, 20)        # KBJ 가 운용사 PDF 를 처음 쌓은 다음 날 — 이보다 앞은 구성 비중이 없다
TH = (0.05, 0.10)                     # 판정 문턱: ETF 몫 ÷ ADV20 (영향 작음 / 매수·매도 / 강한). 화면에서 바꿀 수 있다
MIN_EOK = 1.0                         # 억 — 판정에 필요한 최소 몫
KEEP_R = 0.02                         # 화면 파일에 싣는 종목: |몫 ÷ ADV20| 이 이 이상이거나 순유입 몫 상위 keep_top
ADV_N, ADV_MIN = 20, 10               # ADV = 직전 20거래일 평균 거래대금 (10일 미만이면 모름)
HIST, RSI_HIST = 30, 60               # 화면에 싣는 일별 이력·RSI 이력 길이
PERIODS = (1, 5, 20)
SORTS = ('in', 'out', 'pct')
DEFAULT_PERIOD, DEFAULT_SORT = 5, 'in'           # KBJ 기본값 — 파일 이름에서 빠진다


def src_name(period: int, sort: str) -> str:
    parts = ([f'period-{period}'] if period != DEFAULT_PERIOD else []) + ([f'sort-{sort}'] if sort != DEFAULT_SORT else [])
    return 'stocks' + ('@' + '.'.join(parts) if parts else '') + '.json'


def eok(v):
    return None if v is None else round(v / 1e8, 1)


def row(r: dict) -> dict:
    return {'c': r['code'], 'n': r.get('name'), 'in': eok(r.get('inflow')), 'pct': r.get('inflow_pct'),
            'tp': r.get('turnover_pct'), 'ne': r.get('n_etfs'),
            'top': [[e.get('name') or e['code'], eok(e.get('inflow'))] for e in (r.get('top_etfs') or [])]}


def fetch_periods(top=100) -> dict:
    """KBJ 컨테이너에서 {"기간:정렬": 사이트 내보내기와 같은 모양} (kbj_etf_periods.py)"""
    script = (ROOT / 'kbj_etf_periods.py').read_text(encoding='utf-8')
    r = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'python', '-', str(top)], input=script, capture_output=True,
                       text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f'kbj_etf_periods 실패 (종료 {r.returncode}): {r.stderr.strip().splitlines()[-1:]}')
    return json.loads(r.stdout or '{}')


def build(src: Path = SRC, live: dict | None = None):
    """live = fetch_periods() 결과. 없으면 src 의 사이트 내보내기 파일"""
    out, meta = {}, None
    for p in PERIODS:
        rows, head = {}, None
        for s in SORTS:
            if live is not None:
                d = live.get(f'{p}:{s}')
                if d is None:
                    continue
            else:
                f = src / src_name(p, s)
                if not f.exists():
                    continue
                d = json.loads(f.read_text(encoding='utf-8'))
            head = head or d
            for r in d['data']['rows']:
                rows.setdefault(r['code'], row(r))
        if head is None:
            continue
        meta = meta or head
        dd = head['data']
        out[str(p)] = {'start': dd.get('start'), 'end': dd.get('end'), 'coverage': dd.get('coverage_pct'),
                       'n_etfs': dd.get('n_etfs_known'), 'n_total': dd.get('n_total'), 'rows': list(rows.values())}
    if not out:
        return None
    return {'as_of': meta.get('as_of'), 'generated_at': meta.get('generated_at'), 'holdings_asof': meta['data'].get('holdings_asof'),
            'notes': meta.get('notes', []), 'periods': out}


# ---------- 하루 판정 ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS etf_day (date TEXT PRIMARY KEY, coverage REAL, n_etfs INTEGER, n_total INTEGER, holdings_asof TEXT, stale TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS etf_stock_day (
    date TEXT, code TEXT, name TEXT, inflow REAL, etf_turnover REAL, stock_turnover REAL, n_etfs INTEGER, top TEXT,
    PRIMARY KEY (date, code)
);
"""


def judge(r, th=TH, amt=None):
    """ETF 몫 ÷ ADV20 → 판정 키. b2 강한 매수 · b1 매수 · n 영향 작음 · s1 매도 · s2 강한 매도 · u 모름(ADV 없음)
    amt(억)가 MIN_EOK 보다 작으면 비율이 커도 영향 작음 — 거래가 거의 없는 종목은 몇천만 원으로도 수십 %가 된다 (화면 flow.js 와 같은 규칙)"""
    if r is None:
        return 'u'
    a = abs(r)
    if a < th[0] or (amt is not None and abs(amt) < MIN_EOK):
        return 'n'
    return ('b' if r > 0 else 's') + ('2' if a >= th[1] else '1')


def adv(series, d: str, n=ADV_N, least=ADV_MIN):
    """series = [(날짜, 거래대금 억)] 날짜순. d 보다 앞선 n 거래일 평균 (그날은 넣지 않는다 — 그날 거래가 분모를 부풀리지 않게)"""
    i = bisect_left(series, (d,))
    vals = [v for _, v in series[max(0, i - n):i] if v]
    return sum(vals) / len(vals) if len(vals) >= least else None


def rsi_series(closes, n=14):
    """Wilder RSI 를 날마다 (closes 와 같은 길이, 앞 n 개는 None)"""
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    ch = [b - a for a, b in zip(closes, closes[1:])]
    ag = sum(max(c, 0) for c in ch[:n]) / n
    al = sum(max(-c, 0) for c in ch[:n]) / n
    for i in range(n, len(closes)):
        if i > n:
            c = ch[i - 1]
            ag, al = (ag * (n - 1) + max(c, 0)) / n, (al * (n - 1) + max(-c, 0)) / n
        out[i] = 100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 1)
    return out


def pct_rank(vals, v):
    """v 가 vals(1년 치) 가운데 어디쯤인지 0~1 (작을수록 낮음)"""
    vals = [x for x in vals if x is not None]
    if v is None or len(vals) < 60:
        return None
    return round(sum(1 for x in vals if x < v) / len(vals) + 0.5 * sum(1 for x in vals if x == v) / len(vals), 3)


def trading_days(start: date, end: date):
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def container_up() -> bool:
    try:
        r = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', CONTAINER], capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and r.stdout.strip() == 'true'
    except (OSError, subprocess.SubprocessError):
        return False


def fetch_days(days) -> list:
    """KBJ 컨테이너에서 날짜별 1일 순유입 몫 (kbj_etf_days.py)"""
    script = (ROOT / 'kbj_etf_days.py').read_text(encoding='utf-8')
    r = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'python', '-', *days], input=script, capture_output=True,
                       text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f'kbj_etf_days 실패 (종료 {r.returncode}): {r.stderr.strip().splitlines()[-1:] }')
    return json.loads(r.stdout or '[]')


def store(conn, days: list):
    from datetime import datetime
    at = datetime.now().isoformat(timespec='seconds')
    with conn:
        for x in days:
            m = x['meta']
            conn.execute('DELETE FROM etf_stock_day WHERE date = ?', (x['date'],))
            conn.execute('INSERT OR REPLACE INTO etf_day VALUES (?, ?, ?, ?, ?, ?, ?)',
                         (x['date'], m.get('coverage'), m.get('n_etfs'), m.get('n_total'), m.get('holdings_asof'),
                          json.dumps(x.get('stale') or {}), at))
            conn.executemany('INSERT INTO etf_stock_day VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                             [(x['date'], c, n, inf, et, stt, ne, json.dumps(top, ensure_ascii=False))
                              for c, n, inf, et, stt, ne, top in x['rows']])


def collect(conn, refetch=False) -> int:
    """빈 날(그리고 최근 2거래일)을 KBJ 컨테이너에서 받아 쌓는다. 받은 날 수"""
    if not container_up():
        return 0
    have = {r[0] for r in conn.execute('SELECT date FROM etf_day')}
    days = trading_days(FIRST_DAY, date.today())
    want = [d for d in days if refetch or d not in have] + [d for d in days[-2:] if d in have and not refetch]
    if not want:
        return 0
    got = fetch_days(sorted(set(want)))
    store(conn, got)
    return len(got)


def turnover_series(codes, since: str) -> dict:
    """{종목: [(날짜, 거래대금 억)]} — price_daily 거래대금, 없는 날은 ohlc_daily 종가×거래량 어림"""
    if not MARKET_DB.exists():
        return {}
    m = sqlite3.connect(str(MARKET_DB))
    qs = ','.join('?' * len(codes))
    tv = {}
    for c, d, v in m.execute(f'SELECT code, date, close * volume / 1e8 FROM ohlc_daily WHERE date >= ? AND code IN ({qs})', (since, *codes)):
        if v:
            tv[(c, d)] = v
    for c, d, v in m.execute(f'SELECT code, date, trd_val FROM price_daily WHERE date >= ? AND code IN ({qs})', (since, *codes)):
        if v:
            tv[(c, d)] = v
    out = {}
    for (c, d), v in tv.items():
        out.setdefault(c, []).append((d, v))
    return {c: sorted(v) for c, v in out.items()}


def closes_of(codes, since: str) -> dict:
    if not MARKET_DB.exists():
        return {}
    m = sqlite3.connect(str(MARKET_DB))
    qs = ','.join('?' * len(codes))
    out = {}
    for c, d, v in m.execute(f'SELECT code, date, close FROM ohlc_daily WHERE date >= ? AND code IN ({qs}) AND close > 0 ORDER BY date', (since, *codes)):
        out.setdefault(c, []).append((d, v))
    return out


def day_block(conn, keep_top=120):
    """가장 최근 날의 판정 표 + 종목별 이력 (화면용)"""
    dates = [r[0] for r in conn.execute('SELECT date FROM etf_day ORDER BY date')]
    if not dates:
        return None
    last = dates[-1]
    m = conn.execute('SELECT coverage, n_etfs, n_total, holdings_asof, stale FROM etf_day WHERE date = ?', (last,)).fetchone()
    stale = json.loads(m[4] or '{}')
    today = {r[0]: r for r in conn.execute('SELECT code, name, inflow, n_etfs, top FROM etf_stock_day WHERE date = ?', (last,))}
    codes = list(today)
    if not codes:
        return None
    hd = dates[-HIST:]
    since = (date.fromisoformat(dates[0]) - timedelta(days=45)).isoformat()
    tv = turnover_series(codes, since)
    inflow = {}
    qs = ','.join('?' * len(hd))
    for d, c, v in conn.execute(f'SELECT date, code, inflow FROM etf_stock_day WHERE date IN ({qs})', hd):
        inflow[(c, d)] = v
    rows = []
    for c, (_, name, inf, ne, top) in today.items():
        a = adv(tv.get(c, []), last)
        r = inf / 1e8 / a if a else None
        rows.append({'c': c, 'n': name, 'in': eok(inf), 'adv': round(a, 1) if a else None, 'r': None if r is None else round(r, 4),
                     'st': judge(r, TH, inf / 1e8), 'ne': ne, 'top': [[e[1] or e[0], eok(e[2]), stale.get(e[0])] for e in json.loads(top or '[]')]})
    # 판정이 난 종목 + 순유입 몫이 큰 종목만 싣는다 (전 종목은 파일이 커진다)
    big = {x['c'] for x in sorted(rows, key=lambda x: -abs(x['in'] or 0))[:keep_top]}
    rows = [x for x in rows if (x['r'] is not None and abs(x['r']) >= KEEP_R) or x['c'] in big]
    sel = [x['c'] for x in rows]
    cl = closes_of(sel, (date.fromisoformat(last) - timedelta(days=560)).isoformat())
    for x in rows:
        c = x['c']
        h = []                                          # hd(날짜 목록)와 같은 순서: [몫 억, 몫 ÷ ADV20]
        for d in hd:
            v = inflow.get((c, d), 0.0)
            a = adv(tv.get(c, []), d)
            h.append([eok(v), None if not a else round(v / 1e8 / a, 4)])
        x['h'] = h
        x['c5'] = round(sum(v for v, _ in h[-5:]), 1) if len(h) >= 5 else None
        x['c20'] = round(sum(v for v, _ in h[-20:]), 1) if len(h) >= 20 else None
        ser = cl.get(c, [])
        rs = rsi_series([v for _, v in ser])
        x['rsi'] = rs[-1] if rs else None
        x['rp'] = pct_rank(rs[-250:], x['rsi']) if rs else None
        x['rh'] = [rs[i] for i in range(max(0, len(ser) - RSI_HIST), len(ser)) if rs[i] is not None]   # 마지막 값 = rd 날
        x['rd'] = ser[-1][0] if ser else None         # RSI 기준일 (시세가 그날까지 안 쌓였으면 앞날)
    cnt = {}
    for x in rows:
        cnt[x['st']] = cnt.get(x['st'], 0) + 1
    return {'date': last, 'coverage': m[0], 'n_etfs': m[1], 'n_total': m[2], 'holdings_asof': m[3], 'n_stale': len(stale),
            'th': list(TH), 'adv_n': ADV_N, 'days': len(dates), 'first': dates[0], 'n_rows': len(today), 'cnt': cnt,
            'hd': hd, 'rows': rows}


def main() -> int:
    refetch = '--refetch' in sys.argv
    conn = sqlite3.connect(str(DB))
    conn.executescript(SCHEMA)
    try:
        n = collect(conn, refetch)
        if n:
            print(f'KBJ 1일 ETF 몫: {n}일 받음')
    except (RuntimeError, subprocess.SubprocessError, ValueError) as e:
        print(f'KBJ 컨테이너에서 받기 실패 — 쌓인 날로 만든다: {type(e).__name__} {e}')
    day = day_block(conn)
    live = None
    if container_up():
        try:
            live = fetch_periods()
        except (RuntimeError, subprocess.SubprocessError, ValueError) as e:
            print(f'KBJ 컨테이너에서 기간 합 받기 실패 — 예전 내보내기 파일을 본다: {type(e).__name__} {e}')
    data = build(live=live)
    if data is None and day is None:
        print(f'KBJ ETF 내보내기가 없습니다 ({SRC}). 건너뜁니다.')
        return 0
    if data is None:
        data = {'as_of': None, 'generated_at': None, 'holdings_asof': None, 'notes': [], 'periods': {}}
    data['day'] = day
    if day:
        print(f"하루 판정 {day['date']}: {len(day['rows'])}종목 · " + ' '.join(f'{k}={v}' for k, v in sorted(day['cnt'].items())) + f" · 쌓인 날 {day['days']}")
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"etf_flow.json: {data['as_of']} · " + ' · '.join(f"{p}일 {len(v['rows'])}종목(덮은 비율 {v['coverage']:.0f}%)" for p, v in data['periods'].items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
