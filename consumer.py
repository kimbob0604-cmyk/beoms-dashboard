"""
소비재 탭 계산 (순수 함수, tests/test_consumer.py)

월별 수출 시리즈 → 전년 대비·3개월 전년 대비, 분기 합, 분기 매출과의 상관·회귀, 실적 프리뷰 판정, 지역 맞추기.
수집은 collect_trade.py, 화면 JSON 은 build_consumer.py.
"""

from typing import Dict, List, Optional, Sequence, Tuple

MIN_Q = 6            # 상관·회귀에 필요한 최소 분기 수
BAND = 0.05          # 프리뷰 판정 문턱: 컨센서스 대비 ±5%
R_OK = 0.6           # 이 상관 미만이면 대표 흐름·프리뷰에 쓰지 않는다
MIN_NQ = 8           # 상관을 믿을 최소 분기 수
COVER_MIN, COVER_MAX = 0.10, 1.2   # 최근 4분기 수출 ÷ 매출이 이 범위일 때만 '회사 수출'로 본다
MAE_OK = 0.10        # 지난 분기 되맞춤의 평균 절대 오차가 이 이하일 때만 컨센서스 대비 판정을 낸다
SCAN_R, SCAN_NQ = 0.75, 10   # 지역 자동 탐색: 수백 개 지역을 훑으므로 우연을 줄이려고 더 엄하게 본다


def months(start: str, end: str) -> List[str]:
    """'2021-01', '2021-03' → ['2021-01', '2021-02', '2021-03']"""
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while f'{y}-{m:02d}' <= end:
        out.append(f'{y}-{m:02d}')
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def yoy(v: Sequence[Optional[float]], i: int = -1, span: int = 1) -> Optional[float]:
    """i 번째 달까지 span 개월 합의 전년 같은 기간 대비. 값이 하나라도 없거나 전년 합이 0 이하면 None"""
    n = len(v)
    i = i if i >= 0 else n + i
    if i - span + 1 - 12 < 0:
        return None
    cur, prev = v[i - span + 1:i + 1], v[i - span + 1 - 12:i + 1 - 12]
    if any(x is None for x in cur) or any(x is None for x in prev) or sum(prev) <= 0:
        return None
    return sum(cur) / sum(prev) - 1


def quarter(ym: str) -> str:
    return f'{ym[:4]}Q{(int(ym[5:7]) - 1) // 3 + 1}'


def quarter_sums(ms: Sequence[str], v: Sequence[Optional[float]]) -> Dict[str, Tuple[float, int]]:
    """{분기: (합, 달 수)} — 값이 있는 달만 더한다. 달 수가 3 이 아니면 덜 찬 분기"""
    out = {}
    for ym, x in zip(ms, v):
        if x is None:
            continue
        s, k = out.get(quarter(ym), (0.0, 0))
        out[quarter(ym)] = (s + x, k + 1)
    return out


def single_quarters(rows: Sequence[dict]) -> Dict[str, float]:
    """
    DART 재무(history.db fin) 행 → {분기: 그 분기 석 달 값}.
    rows: [{'year', 'reprt', 'cur', 'cur_add'}] 한 종목·한 계정·한 재무제표.
    reprt 11013=1분기, 11012=반기, 11014=3분기, 11011=사업보고서(연간). 분기 보고서의 cur 는 석 달, cur_add 는 누적.
    cur 가 누적으로만 온 회사(cur == cur_add)는 앞 분기를 빼고, 4분기 = 연간 − 3분기 누적.
    """
    by = {(r['year'], r['reprt']): r for r in rows}
    out = {}
    for y in sorted({r['year'] for r in rows}):
        q1, h1, q3, fy = (by.get((y, k)) for k in ('11013', '11012', '11014', '11011'))
        cum = {}
        if q1 and q1['cur'] is not None:
            out[f'{y}Q1'] = cum[1] = q1['cur']
        if h1 and h1['cur'] is not None:
            c2 = h1['cur_add'] if h1['cur_add'] is not None else None
            if c2 is not None and h1['cur'] == c2 and 1 in cum:      # 누적만 준 경우
                out[f'{y}Q2'] = c2 - cum[1]
            else:
                out[f'{y}Q2'] = h1['cur']
            cum[2] = c2 if c2 is not None else (cum[1] + out[f'{y}Q2'] if 1 in cum else None)
        if q3 and q3['cur'] is not None:
            c3 = q3['cur_add'] if q3['cur_add'] is not None else None
            if c3 is not None and q3['cur'] == c3 and cum.get(2) is not None:
                out[f'{y}Q3'] = c3 - cum[2]
            else:
                out[f'{y}Q3'] = q3['cur']
            cum[3] = c3 if c3 is not None else (cum[2] + out[f'{y}Q3'] if cum.get(2) is not None else None)
        if fy and fy['cur'] is not None and cum.get(3) is not None:
            out[f'{y}Q4'] = fy['cur'] - cum[3]
    return out


def prev_year(q: str) -> str:
    return f'{int(q[:4]) - 1}{q[4:]}'


def corr(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx <= 0 or sy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) ** 0.5


def yoy_corr(exp_q: Dict[str, float], rev_q: Dict[str, float], last: int = 12) -> Tuple[Optional[float], int]:
    """분기 수출 전년비와 분기 매출 전년비의 상관 (최근 last 분기). 추세·계절성을 빼고 '같이 움직이는가'만 본다"""
    pts = yoy_points(exp_q, rev_q, last=last)
    if len(pts) < MIN_Q:
        return None, len(pts)
    return corr([p[0] for p in pts], [p[1] for p in pts]), len(pts)


def fit(xs: Sequence[float], ys: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    """y = a + b·x 최소제곱 → (a, b, R²)"""
    n = len(xs)
    if n < MIN_Q:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    if sx <= 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sx
    a = my - b * mx
    st = sum((y - my) ** 2 for y in ys)
    r2 = 1 - sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys)) / st if st > 0 else 0.0
    return a, b, r2


def qualified(r: Optional[float], nq: int, cover: Optional[float]) -> bool:
    """그 흐름을 '회사 수출'로 믿고 대표 흐름·프리뷰에 써도 되는가.
    상관만 높고 매출의 1~2%밖에 안 되는 흐름(우연), 수출이 매출보다 훨씬 큰 흐름(다른 회사 물량)은 거른다."""
    return (r is not None and r >= R_OK and nq >= MIN_NQ
            and cover is not None and COVER_MIN <= cover <= COVER_MAX)


def yoy_points(exp_q: Dict[str, float], rev_q: Dict[str, float], before: Optional[str] = None, last: int = 12) -> List[Tuple[float, float]]:
    """(분기 수출 전년비, 분기 매출 전년비) 짝. before 를 주면 그 분기 전까지만"""
    pts = []
    for q in sorted(set(exp_q) & set(rev_q)):
        p = prev_year(q)
        if (before is None or q < before) and p in exp_q and p in rev_q and exp_q[p] > 0 and rev_q[p] > 0:
            pts.append((exp_q[q] / exp_q[p] - 1, rev_q[q] / rev_q[p] - 1))
    return pts[-last:]


def estimate(exp_q: Dict[str, float], rev_q: Dict[str, float], q: str, last: int = 12) -> Optional[dict]:
    """q 분기 매출 추정. q 전까지의 '수출 전년비 → 매출 전년비' 직선을 맞추고,
    q 의 수출 전년비를 넣어 나온 매출 전년비를 전년 같은 분기 매출에 곱한다. 수준(금액)이 아니라 전년비로 맞추는 이유:
    수출 단가와 최종 판매가의 비율, 수출이 설명하는 비중이 달라도 '같이 움직이는 정도'만 쓰기 위해서다.

    계산식:  ① x = 수출(q) ÷ 수출(전년 같은 분기) − 1
             ② g = a + b·x          (a, b = 지난 last 분기의 (수출 전년비, 매출 전년비)에 맞춘 직선)
             ③ 매출 추정 = 매출(전년 같은 분기) × (1 + g)
    → {est, a, b, x(①), g(②), base(전년 같은 분기 매출), exp, exp_py, r2, n}"""
    p = prev_year(q)
    if q not in exp_q or p not in exp_q or p not in rev_q or exp_q[p] <= 0 or rev_q[p] <= 0:
        return None
    pts = yoy_points(exp_q, rev_q, before=q, last=last)
    f = fit([x for x, _ in pts], [y for _, y in pts])
    if not f:
        return None
    a, b, r2 = f
    x = exp_q[q] / exp_q[p] - 1
    g = a + b * x
    est = rev_q[p] * (1 + g)
    if est <= 0:
        return None
    return {'est': est, 'a': a, 'b': b, 'x': x, 'g': g, 'base': rev_q[p], 'exp': exp_q[q], 'exp_py': exp_q[p], 'r2': r2, 'n': len(pts)}


def hindcast(exp_q: Dict[str, float], rev_q: Dict[str, float], k: int = 4, last: int = 12) -> List[dict]:
    """지난 k 개 분기를 '그 분기 전까지의 자료만으로' 다시 추정해 실제 매출과 견준다 → [{q, est, act, err}].
    프리뷰가 과거에 얼마나 맞았는지 보여 주기 위한 것. 그 시점에 표본이 MIN_Q 미만이면 건너뛴다."""
    out = []
    for q in [x for x in sorted(set(exp_q) & set(rev_q))][-k:]:
        e = estimate(exp_q, rev_q, q, last)
        if e and rev_q[q] > 0:
            out.append({'q': q, 'est': e['est'], 'act': rev_q[q], 'err': e['est'] / rev_q[q] - 1})
    return out


def preview(exp_q: Dict[str, float], rev_q: Dict[str, float], q: str, consensus: Optional[float] = None, last: int = 12,
            opm: Optional[float] = None, cns_op: Optional[float] = None) -> Optional[dict]:
    """
    수출로 본 분기 매출 추정. q = 매출이 아직 없는 분기(수출은 exp_q 에 있어야 한다). 그 흐름이 qualified 인지는 부르는 쪽이 본다.
    판정(BEAT·IN LINE·MISS)은 지난 분기들을 같은 방법으로 다시 맞춘 평균 절대 오차(mae)가 MAE_OK 이하일 때만 낸다 —
    과거에 잘 안 맞던 방법으로 컨센서스 대비 판정을 내지 않는다.
    opm(영업이익률 가정)을 주면  ④ 영업이익 추정 = 매출 추정 × opm  까지 낸다 (cns_op = 영업이익 컨센서스).
    """
    if q in rev_q:
        return None
    e = estimate(exp_q, rev_q, q, last)
    if not e:
        return None
    past = hindcast(exp_q, rev_q, last=last)
    mae = sum(abs(h['err']) for h in past) / len(past) if len(past) >= 3 else None
    out = {'q': q, **e, 'cns': consensus, 'diff': None, 'verdict': None, 'mae': mae,
           'opm': opm, 'op': e['est'] * opm if opm is not None else None, 'cns_op': cns_op, 'op_diff': None}
    if consensus:
        out['diff'] = e['est'] / consensus - 1
        if mae is not None and mae <= MAE_OK:
            out['verdict'] = 'BEAT' if out['diff'] > BAND else 'MISS' if out['diff'] < -BAND else 'IN LINE'
    if out['op'] is not None and cns_op and cns_op > 0:
        out['op_diff'] = out['op'] / cns_op - 1
    return out


def partial_quarter(ms: Sequence[str], v: Sequence[Optional[float]]) -> Optional[Tuple[str, float, int]]:
    """진행 중인 분기(달이 1~2개만 들어온 마지막 분기)의 분기 합 어림 → (분기, 추정 합, 들어온 달 수).
    추정 합 = 들어온 달의 합 × (전년 같은 분기 합 ÷ 전년 같은 달들의 합) — 분기 안의 달별 비중이 전년과 같다고 본다.
    마지막 분기가 다 찼거나 전년 값이 없으면 None."""
    have = [(m, x) for m, x in zip(ms, v) if x is not None]
    if not have:
        return None
    q = quarter(have[-1][0])
    cur = {m: x for m, x in have if quarter(m) == q}
    if len(cur) >= 3:
        return None
    by = dict(zip(ms, v))
    py = lambda m: by.get(f'{int(m[:4]) - 1}{m[4:]}')
    y, mo = int(q[:4]), (int(q[5]) - 1) * 3
    full = [py(f'{y}-{mo + i:02d}') for i in (1, 2, 3)]
    same = [py(m) for m in cur]
    if any(x is None for x in full) or any(x is None for x in same) or sum(same) <= 0:
        return None
    return q, sum(cur.values()) * sum(full) / sum(same), len(cur)


def region_match(sido: str, sgg: str, regions: Sequence[str]) -> bool:
    """regions: ['11:송파구', '36:세종특별자치시'] — 시도 코드가 같고 시군구 이름이 그 이름으로 끝나면 같은 곳
    (관세청은 '서울특별시 송파구'처럼 시도 이름을 붙여 준다. 시도 이름이 바뀌어도 맞도록 끝말로 본다)"""
    for r in regions:
        code, _, name = r.partition(':')
        if sido == code and (sgg == name or sgg.endswith(' ' + name)):
            return True
    return False
