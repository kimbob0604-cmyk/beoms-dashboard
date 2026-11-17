"""
주간 모멘텀 체크 — 관심 종목(소비재·미용 의료·의료기기)의 추정치 변화 × 주가 × 수급 × RSI (다올 '주간 모멘텀 체크' 모양) → consumer.json 의 mom

- 추정치: 이익 성장 탭(public/data/growth/{날짜}.json)의 내년(FY+1) 영업이익 컨센서스 1주·1개월 변화. 내년 값이 없으면 올해
- 주가: 1주·1개월 수익률(price_daily 종가), RSI(14일, 와일더)
- 수급: 수급 탭(public/data/flow/{날짜}.json)의 외국인·기관 5일·20일 순매수(억원, 수량×종가 어림)
- 분류(1개월 기준, 추정 ±2% 를 움직임으로 본다):
  동행 상향(추정↑·주가↑) · 추정 선행(추정↑·주가↓ — 주가가 아직 안 따라옴) · 추정 하향(추정↓·주가↑ — 주가가 버팀) · 동행 하향(추정↓·주가↓) · 추정 보합
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'public' / 'data'
EST_T = 0.02
CLASSES = [('up', '동행 상향'), ('lead', '추정 선행'), ('hold', '추정 하향'), ('down', '동행 하향'), ('flat', '추정 보합')]


def latest(folder: str):
    files = sorted((DATA / folder).glob('20*.json'))
    return json.loads(files[-1].read_text(encoding='utf-8')) if files else None


def rsi(closes: list, n: int = 14):
    """종가(오래된 → 최근) → RSI. 모자라면 None"""
    if len(closes) < n + 1:
        return None
    gains = [max(b - a, 0) for a, b in zip(closes, closes[1:])]
    losses = [max(a - b, 0) for a, b in zip(closes, closes[1:])]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


def ret(closes: list, k: int):
    return closes[-1] / closes[-1 - k] - 1 if len(closes) > k and closes[-1 - k] else None


def classify(est, r1m):
    if est is None or r1m is None:
        return None
    if abs(est) < EST_T:
        return 'flat'
    if est > 0:
        return 'up' if r1m >= 0 else 'lead'
    return 'hold' if r1m >= 0 else 'down'


def est_change(g: dict):
    """growth 종목 → (FY, 1주, 1개월) 영업이익 컨센서스 변화. 내년 우선"""
    k = (g or {}).get('k') or {}
    for key, add in (('y1', 1), ('y0', 0)):
        op = (k.get(key) or {}).get('op')
        if op and op.get('m1') is not None:
            return g['fy0'] + add, op.get('w1'), op.get('m1')
    return None, None, None


def build(conn, codes: dict, sectors: dict = None) -> dict:
    """codes {코드: 이름}, sectors {코드: 분야} → {date, rows, classes}"""
    gr, fl = latest('growth'), latest('flow')
    gmap = {s['c']: {**s, 'fy0': s.get('fy0') or (gr or {}).get('fy0')} for s in (gr or {}).get('stocks', [])}
    fmap = {s['c']: s for s in (fl or {}).get('stocks', [])}
    rows = []
    for c, n in codes.items():
        closes = [r[0] for r in conn.execute('SELECT close FROM price_daily WHERE code = ? AND close > 0 ORDER BY date DESC LIMIT 80', (c,))][::-1]
        if not closes:
            continue
        fy, w1, m1 = est_change(gmap.get(c))
        f = fmap.get(c, {})
        r1m = ret(closes, 20)
        rows.append({'c': c, 'n': n, 'sec': (sectors or {}).get(c), 'mc': (gmap.get(c) or f).get('mc'),
                     'r1w': ret(closes, 5), 'r1m': r1m, 'rsi': rsi(closes), 'fy': fy, 'ew1': w1, 'em1': m1,
                     'f5': f.get('f5'), 'o5': f.get('o5'), 'f20': f.get('f20'), 'o20': f.get('o20'), 'k': classify(m1, r1m)})
    return {'date': (fl or {}).get('date'), 'cns_date': (gr or {}).get('cns_date'), 'est_t': EST_T, 'classes': CLASSES, 'rows': rows}
