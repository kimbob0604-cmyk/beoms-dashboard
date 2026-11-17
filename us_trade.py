"""
미국 화장품 수입 — 한국 vs 중국 (collect_us.py 가 받은 db/trade.db 의 us 표, UN Comtrade) → consumer.json 의 us

EU 카드(eu_trade.py)와 같은 모양으로 낸다 — 화면은 한 카드에서 EU ↔ 미국을 바꿔 본다.
'ext'(점유율 분모)는 미국의 세계 수입 합계, 'oth' 는 비교용 원산지(일본·프랑스). 보고국 표는 없다(rep 빈 목록).
"""

from collect_eu import BASKET, EXTRA
from collect_us import SCHEMA

N = 48


def ym_add(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + k
    return f'{y + m // 12:04d}-{m % 12 + 1:02d}'


def build(tconn):
    tconn.executescript(SCHEMA)
    last = tconn.execute("SELECT MAX(ym) FROM us WHERE partner = 'WLD'").fetchone()[0]
    if not last:
        return None
    months = [ym_add(last, -k) for k in range(N - 1, -1, -1)]
    idx = {m: i for i, m in enumerate(months)}
    basket = {h for h, _ in BASKET}
    have = {r[0] for r in tconn.execute("SELECT DISTINCT ym FROM us WHERE partner = 'WLD'")}
    zero = lambda: [0.0 if m in have else None for m in months]          # noqa: E731
    tot, per_hs = {}, {}
    for ym, par, hs, usd, kg in tconn.execute('SELECT * FROM us WHERE ym >= ?', (months[0],)):
        i = idx.get(ym)
        if i is None:
            continue
        if hs in basket:
            for k, v in (('usd', usd), ('kg', kg)):
                acc = tot.setdefault((par, k), zero())
                if v is not None and acc[i] is not None:
                    acc[i] += v
        acc = per_hs.setdefault((hs, par), zero())
        if usd is not None and acc[i] is not None:
            acc[i] += usd
    g = lambda par, k='usd': tot.get((par, k)) or zero()                 # noqa: E731
    rnd = lambda v: [None if x is None else round(x) for x in v]        # noqa: E731
    tox = EXTRA[0][0]
    return {
        'last_ym': last, 'months': months, 'cur': '$', 'src': 'UN Comtrade (미국 보고)',
        'kr': rnd(g('KR')), 'cn': rnd(g('CN')), 'ext': rnd(g('WLD')), 'ext_label': '세계 전체',
        'oth': [['일본산', rnd(g('JP'))], ['프랑스산', rnd(g('FR'))]],
        'kr_kg': rnd(g('KR', 'kg')), 'cn_kg': rnd(g('CN', 'kg')),
        'hs': [{'hs': h, 'label': lb, 'kr': rnd(per_hs.get((h, 'KR')) or zero()), 'cn': rnd(per_hs.get((h, 'CN')) or zero())}
               for h, lb in BASKET],
        'rep': [],
        'tox': {'kr': rnd(per_hs.get((tox, 'KR')) or zero()), 'ext': rnd(per_hs.get((tox, 'WLD')) or zero())},
    }
