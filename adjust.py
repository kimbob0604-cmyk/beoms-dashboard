"""
수정주가 수익률: KRX 일별 등락률(chg)은 권리락·무상증자·분할을 반영한 기준가 대비라서,
전날 값에 (1 + chg) 를 곱해 이어 붙이면 그런 날 기계적으로 떨어진 가격이 손익으로 잡히지 않는다.
chg 가 없는 날(KRX 공개 전 네이버로 채운 날 등)은 종가 비율로 잇는다.
"""

from collections import defaultdict


def adjusted_series(conn, pos=None, codes=None):
    """{code: [수정 가격]} — pos 를 주면 그 거래일 칸에 맞춘 배열(없는 날 None), 안 주면 날짜순 목록"""
    out = defaultdict(list) if pos is None else defaultdict(lambda: [None] * len(pos))
    prev = {}
    for code, d, close, chg in conn.execute(
            'SELECT code, date, close, chg FROM ohlc_daily WHERE close IS NOT NULL ORDER BY code, date'):
        if codes is not None and code not in codes:
            continue
        p = prev.get(code)
        if p is None:
            adj = close
        elif chg is not None:
            adj = p[0] * (1 + chg / 100)
        else:
            adj = p[0] * close / p[1]
        prev[code] = (adj, close)
        if pos is None:
            out[code].append(adj)
        elif d in pos:
            out[code][pos[d]] = adj
    return out
