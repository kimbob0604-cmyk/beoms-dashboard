"""
종목 패널 차트 JSON: public/data/chart/{code}.json (보통주 전부, 최근 CHART_DAYS 거래일 일봉)

{"code": 코드, "d": [20261104, …], "o": [...], "h": [...], "l": [...], "c": [...], "v": [...]}
- 열 단위 배열이라 파일이 작다 (종목당 10KB 안팎).
- KRX 공개 전 네이버로 채운 날은 o·h·l·v 가 null (화면에서 종가만 점으로 그린다).

  python3 build_charts.py
"""

from collections import defaultdict

import db
from build_naver import DATA, write_json
from universe import is_common

CHART_DAYS = 260
OUT = DATA / 'chart'


def build(conn) -> int:
    dates = [r[0] for r in conn.execute(
        'SELECT DISTINCT date FROM ohlc_daily ORDER BY date DESC LIMIT ?', (CHART_DAYS,))]
    if not dates:
        return 0
    latest = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    codes = {r[0] for r in conn.execute('SELECT code FROM price_daily WHERE date = ?', (latest,)) if is_common(r[0])}
    cols = defaultdict(lambda: {k: [] for k in 'dohlcv'})
    for r in conn.execute('SELECT * FROM ohlc_daily WHERE date >= ? ORDER BY code, date', (dates[-1],)):
        if r['code'] not in codes or not r['close']:
            continue
        x = cols[r['code']]
        x['d'].append(int(r['date'].replace('-', '')))
        for k, f in (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'volume')):
            v = r[f]
            x[k].append(None if v is None else (int(v) if v == int(v) else v))
    OUT.mkdir(parents=True, exist_ok=True)
    for code, x in cols.items():
        write_json(OUT / f'{code}.json', {'code': code, **x})
    for p in OUT.glob('*.json'):   # 상장폐지 등으로 빠진 종목
        if p.stem not in cols:
            p.unlink()
    return len(cols)


def main():
    n = build(db.connect())
    print(f'chart: {n}종목')


if __name__ == '__main__':
    main()
