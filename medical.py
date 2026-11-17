"""
외국인 의료 소비 (collect_medical.py 가 받은 db/trade.db 의 med 표) → consumer.json 의 med

- 글로벌(외국인 전체) 진료과목별 월 소비액(원)
- 국적별(25개국 + 기타) 월 소비액 합계와 피부과·성형외과·약국 소비액, 소비건수 합계
화면에서 전년비·비중·누계를 계산한다. 2019-01 부터 싣는다.
"""

from collect_medical import SCHEMA

FROM = '2019-01'
FOCUS = ('피부과', '성형외과', '약국')


def months(a: str, b: str) -> list:
    out, (y, m) = [], (int(a[:4]), int(a[5:]))
    while f'{y}-{m:02d}' <= b:
        out.append(f'{y}-{m:02d}')
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out


def build(tconn):
    tconn.executescript(SCHEMA)
    last = tconn.execute('SELECT MAX(ym) FROM med').fetchone()[0]
    if not last:
        return None
    ms = months(FROM, last)
    idx = {m: i for i, m in enumerate(ms)}
    have = {r[0] for r in tconn.execute("SELECT DISTINCT ym FROM med WHERE nat_cd = '000'")}
    zero = lambda: [0.0 if m in have else None for m in ms]          # noqa: E731
    cats, nats, names = {}, {}, {}
    for ym, cd, nat, cat, amt, cnt in tconn.execute('SELECT ym, nat_cd, nat, cat, amt, cnt FROM med WHERE ym >= ?', (FROM,)):
        i = idx[ym]
        names[cd] = nat
        if cd == '000':
            acc = cats.setdefault(cat, zero())
            if acc[i] is not None:
                acc[i] += amt or 0
            continue
        n = nats.setdefault(cd, {'amt': zero(), 'cnt': zero(), **{c: zero() for c in FOCUS}})
        for k, v in [('amt', amt), ('cnt', cnt)] + ([(cat, amt)] if cat in FOCUS else []):
            if v is not None and n[k][i] is not None:
                n[k][i] += v
    rnd = lambda v: [None if x is None else round(x / 1e6) for x in v]       # 백만원
    rc = lambda v: [None if x is None else round(x) for x in v]               # noqa: E731
    order = sorted(nats, key=lambda c: -sum(x or 0 for x in nats[c]['amt'][-12:]))
    return {
        'last_ym': last, 'months': ms, 'unit': '백만원',
        'cats': [{'cat': c, 'v': rnd(v)} for c, v in sorted(cats.items(), key=lambda kv: -sum(x or 0 for x in kv[1][-12:]))],
        'nats': [{'cd': c, 'n': names[c], 'amt': rnd(nats[c]['amt']), 'cnt': rc(nats[c]['cnt']), **{k: rnd(nats[c][k]) for k in FOCUS}}
                 for c in order],
    }
