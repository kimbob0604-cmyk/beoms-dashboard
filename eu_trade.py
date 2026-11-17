"""
EU 화장품 수입 — 한국 vs 중국 (collect_eu.py 가 받은 db/trade.db 의 eu 표) → consumer.json 의 eu

화면에 싣는 것 (금액은 유로, 원산지 기준):
- 바스켓(9개 HS6) 월 수입액: 한국·중국·일본·미국·역외 전체, 한국·중국 물량(kg)
- HS 별 한국·중국 월 수입액 (화면에서 바스켓 전년비 기여도를 계산한다: (올해 − 작년) ÷ 작년 바스켓)
- 보고국(EU 합·독일·프랑스·이탈리아·스페인·네덜란드·폴란드)별 최근 3개월 한국·중국 금액과 전년비, 역외 대비 점유율
- 보툴리눔 톡신(300249) 한국산 EU 수입
"""

from collect_eu import BASKET, EXTRA, SCHEMA

N = 48            # 화면 36개월 + 전년비용 12개월
REP_NAMES = {'EU27_2020': 'EU 27', 'DE': '독일', 'FR': '프랑스', 'IT': '이탈리아', 'ES': '스페인', 'NL': '네덜란드', 'PL': '폴란드'}


def ym_add(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + k
    return f'{y + m // 12:04d}-{m % 12 + 1:02d}'


def _sum3(v, end):
    xs = v[end - 3:end]
    return None if len(xs) < 3 or any(x is None for x in xs) else sum(xs)


def ratio(a, b):
    return None if a is None or not b else a / b - 1


def build(tconn):
    tconn.executescript(SCHEMA)
    last = tconn.execute("SELECT MAX(ym) FROM eu WHERE reporter = 'EU27_2020' AND partner = 'EXT_EU27_2020'").fetchone()[0]
    if not last:
        return None
    months = [ym_add(last, -k) for k in range(N - 1, -1, -1)]
    idx = {m: i for i, m in enumerate(months)}
    basket = {h for h, _ in BASKET}
    have = {}                                    # 보고국마다 자료가 있는 달 — 없는 달은 None(0 과 다르다)
    for rep, ym in tconn.execute('SELECT DISTINCT reporter, ym FROM eu'):
        have.setdefault(rep, set()).add(ym)
    zero = lambda rep='EU27_2020': [0.0 if m in have.get(rep, ()) else None for m in months]          # noqa: E731
    tot = {}                                     # (reporter, partner, 'eur'|'kg') → 바스켓 월 합
    per_hs = {}                                  # (hs, partner) → EU27 월 금액
    for ym, rep, par, hs, eur, kg in tconn.execute('SELECT * FROM eu WHERE ym >= ?', (months[0],)):
        i = idx.get(ym)
        if i is None:
            continue
        if hs in basket:
            for k, v in (('eur', eur), ('kg', kg)):
                acc = tot.setdefault((rep, par, k), zero(rep))
                if v is not None and acc[i] is not None:
                    acc[i] += v
        if rep == 'EU27_2020':
            acc = per_hs.setdefault((hs, par), zero())
            if eur is not None and acc[i] is not None:
                acc[i] += eur
    g = lambda rep, par, k='eur': tot.get((rep, par, k)) or zero(rep)      # noqa: E731
    rnd = lambda v: [None if x is None else round(x) for x in v]        # noqa: E731
    n = len(months)
    reps = []
    for rep, name in REP_NAMES.items():
        kr3, cn3, ext3 = _sum3(g(rep, 'KR'), n), _sum3(g(rep, 'CN'), n), _sum3(g(rep, 'EXT_EU27_2020'), n)
        reps.append({'r': rep, 'name': name, 'kr3': kr3, 'cn3': cn3,
                     'kr_yoy3': ratio(kr3, _sum3(g(rep, 'KR'), n - 12)), 'cn_yoy3': ratio(cn3, _sum3(g(rep, 'CN'), n - 12)),
                     'kr_sh3': kr3 / ext3 if kr3 is not None and ext3 else None,
                     'cn_sh3': cn3 / ext3 if cn3 is not None and ext3 else None})
    return {
        'last_ym': last, 'months': months,
        'kr': rnd(g('EU27_2020', 'KR')), 'cn': rnd(g('EU27_2020', 'CN')), 'jp': rnd(g('EU27_2020', 'JP')),
        'us': rnd(g('EU27_2020', 'US')), 'ext': rnd(g('EU27_2020', 'EXT_EU27_2020')),
        'cur': '€', 'src': 'Eurostat Comext', 'ext_label': '역외 전체',
        'oth': [['일본산', rnd(g('EU27_2020', 'JP'))], ['미국산', rnd(g('EU27_2020', 'US'))]],
        'kr_kg': rnd(g('EU27_2020', 'KR', 'kg')), 'cn_kg': rnd(g('EU27_2020', 'CN', 'kg')),
        'hs': [{'hs': h, 'label': lb, 'kr': rnd(per_hs.get((h, 'KR')) or zero()), 'cn': rnd(per_hs.get((h, 'CN')) or zero())}
               for h, lb in BASKET],
        'rep': reps,
        'tox': {'kr': rnd(per_hs.get((EXTRA[0][0], 'KR')) or zero()), 'ext': rnd(per_hs.get((EXTRA[0][0], 'EXT_EU27_2020')) or zero())},
    }
