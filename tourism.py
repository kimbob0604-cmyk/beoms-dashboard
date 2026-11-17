"""
방한 외래관광객 (collect_tourism.py 가 받은 db/trade.db 의 tour 표) → consumer.json 의 tour

- 전체 월 입국자: 응답에 합계 줄(합계·전체·총계)이 있으면 그 줄, 없으면 국적 줄의 합(대륙 소계 '…주' 는 빼고)
- 국적 상위: 최근 12개월 합이 큰 12개 국적의 월 시리즈
- 화면에서 전년 동월비·2019년 같은 달 대비(코로나 이전 수준)·1월~최신월 누계를 계산한다
"""

from collect_tourism import SCHEMA, months

TOTAL_NAMES = ('합계', '전체', '총계', '계', '총합계')
FROM = '2019-01'         # 2019년 같은 달과 비교하려고 여기부터 싣는다
TOP = 12


def is_aggregate(nat: str) -> bool:
    """대륙 소계(아시아주·미주·구주·대양주·아프리카주)와 합계 줄"""
    return nat in TOTAL_NAMES or (nat.endswith('주') and len(nat) <= 6 and nat != '호주')


def build(tconn):
    tconn.executescript(SCHEMA)
    last = tconn.execute('SELECT MAX(ym) FROM tour').fetchone()[0]
    if not last:
        return None
    ms = months(FROM, last)
    idx = {m: i for i, m in enumerate(ms)}
    have = {r[0] for r in tconn.execute('SELECT DISTINCT ym FROM tour WHERE ym >= ?', (FROM,))}
    total = [None] * len(ms)
    explicit = [None] * len(ms)
    nats = {}
    for ym, cd, nat, num in tconn.execute('SELECT ym, nat_cd, nat, num FROM tour WHERE ym >= ?', (FROM,)):
        i = idx[ym]
        if nat in TOTAL_NAMES:
            explicit[i] = num
            continue
        if is_aggregate(nat):
            continue
        total[i] = (total[i] or 0) + num
        nats.setdefault((cd, nat), [None if m not in have else 0.0 for m in ms])[i] = num
    total = [e if e is not None else t for e, t in zip(explicit, total)]
    last12 = lambda v: sum(x or 0 for x in v[-12:])           # noqa: E731
    top = sorted(((k, v) for k, v in nats.items() if k[1] not in ('교포', '기타', '승무원')), key=lambda kv: -last12(kv[1]))[:TOP]
    rnd = lambda v: [None if x is None else round(x) for x in v]   # noqa: E731
    return {'last_ym': last, 'months': ms, 'total': rnd(total), 'total_src': 'row' if any(e is not None for e in explicit) else 'sum',
            'nats': [{'cd': cd, 'n': nat, 'v': rnd(v)} for (cd, nat), v in top]}
