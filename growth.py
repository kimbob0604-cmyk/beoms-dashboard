"""
이익 성장 계산 (순수 함수 — DB/네트워크 없음)

용어
- fy0   : '올해' 회계연도 = 기준일 이후(같은 달 포함) 처음 끝나는 결산기
- 기간  : y0 = 올해→내년 (fy0 → fy0+1), y1 = 내년→내후년 (fy0+1 → fy0+2)
- 지표  : revenue / op / ni(지배) / eps
"""

from datetime import date
from typing import Dict, List, Optional

METRICS = ('revenue', 'op', 'ni', 'eps')
PERIODS = {'y0': 0, 'y1': 1}

LOW_BASE_EOK = 30          # 출발 연도 이익이 30억 미만이면 기저
LOW_BASE_MCAP_RATIO = 0.01  # 또는 시총의 1% 미만이면 기저


def this_fy(rows: List[Dict], as_of: date) -> Optional[int]:
    """rows(연도별, fy·fy_month 포함) 중 '올해' 결산연도."""
    for r in sorted(rows, key=lambda r: (r['fy'], r['fy_month'])):
        if (r['fy'], r['fy_month']) >= (as_of.year, as_of.month):
            return r['fy']
    return None


def bucket(base: Optional[float], nxt: Optional[float]) -> Optional[str]:
    """turnaround(흑자전환) / g100 / g50 / g0 / decline(감익·적자전환) / loss(적자 지속)"""
    if base is None or nxt is None:
        return None
    if base <= 0:
        return 'turnaround' if nxt > 0 else 'loss'
    g = (nxt - base) / base
    if g < 0:
        return 'decline'
    if g >= 1:
        return 'g100'
    if g >= 0.5:
        return 'g50'
    return 'g0'


def growth(base: Optional[float], nxt: Optional[float]) -> Optional[float]:
    """성장률(소수). 출발값이 0 이하면 정의 안 함."""
    if base is None or nxt is None or base <= 0:
        return None
    return (nxt - base) / base


def pct_change(now: Optional[float], prev: Optional[float]) -> Optional[float]:
    if now is None or prev is None or prev == 0:
        return None
    return (now - prev) / abs(prev)


def multiple(metric: str, value: Optional[float], mcap: float, price: float) -> Optional[float]:
    """POR(op) / PER(ni) / PSR(revenue) = 시총 ÷ 값,  EPS 는 주가 ÷ EPS. 음수·0 은 None."""
    if value is None or value <= 0:
        return None
    if metric == 'eps':
        return price / value
    return mcap / value


def is_low_base(metric: str, base: Optional[float], mcap: float, price: float) -> bool:
    if base is None or base <= 0:
        return False
    if metric == 'eps':
        return base / price < LOW_BASE_MCAP_RATIO
    return base < LOW_BASE_EOK or base < mcap * LOW_BASE_MCAP_RATIO


def streak(series: List[tuple]) -> Optional[Dict]:
    """
    series: [(fy, value), ...] 오름차순. 마지막 연도부터 거꾸로 '흑자 상태에서 증가'가 몇 년 이어졌나.
    예) FY24 484 → 565 → 753 → 895 → FY28 1035  ⇒ {'from': 2024, 'years': 4}
    """
    vals = [(fy, v) for fy, v in series if v is not None]
    years = 0
    for i in range(len(vals) - 1, 0, -1):
        (fy_prev, prev), (fy_cur, cur) = vals[i - 1], vals[i]
        if fy_cur != fy_prev + 1 or prev <= 0 or cur <= prev:
            break
        years += 1
    if not years:
        return None
    return {'from': vals[len(vals) - 1 - years][0], 'years': years}


def compute_stock(annual: List[Dict], trend: List[Dict], mcap: float, price: float,
                  as_of: date) -> Optional[Dict]:
    """
    한 종목의 기간×지표별 계산 결과. 계산할 게 없으면 None.
    annual: consensus_annual 행들, trend: consensus_trend 행들 (같은 스냅샷)
    결산월 변경·반기 결산으로 결산월이 섞여 있으면 최신 결산월 행만 쓴다.
    """
    if not annual:
        return None
    latest_month = max(annual, key=lambda r: (r['fy'], r['fy_month']))['fy_month']
    annual = [r for r in annual if r['fy_month'] == latest_month]
    fy0 = this_fy(annual, as_of)
    if fy0 is None:
        return None
    by_fy = {r['fy']: r for r in annual}
    trend_by = {(t['fy'], t['metric']): t for t in trend}

    calc = {}
    for pname, offset in PERIODS.items():
        b_fy, n_fy = fy0 + offset, fy0 + offset + 1
        b_row, n_row = by_fy.get(b_fy), by_fy.get(n_fy)
        if not b_row or not n_row or not n_row['is_estimate']:
            continue
        calc[pname] = {}
        for m in METRICS:
            base, nxt = b_row[m], n_row[m]
            if base is None or nxt is None:
                continue
            t = trend_by.get((n_fy, m), {})
            calc[pname][m] = {
                'base': base,
                'next': nxt,
                'g': growth(base, nxt),
                'bucket': bucket(base, nxt),
                'mult_base': multiple(m, base, mcap, price),
                'mult_next': multiple(m, nxt, mcap, price),
                'low_base': is_low_base(m, base, mcap, price),
                # 다음 연도 추정치의 리비전 (현재 vs 1주/1개월/3개월 전)
                'rev_w1': pct_change(t.get('now'), t.get('w1')),
                'rev_m1': pct_change(t.get('now'), t.get('m1')),
                'rev_m3': pct_change(t.get('now'), t.get('m3')),
            }
    if not any(calc.values()):
        return None

    shown = sorted(r['fy'] for r in annual)[-5:]  # 화면 시계열: 최근 5개 연도
    return {
        'fy0': fy0,
        'series': {m: [[fy, by_fy[fy][m], by_fy[fy]['is_estimate']] for fy in shown] for m in METRICS},
        # 연속 증익도 화면 시계열 범위 안에서만 센다 (예: FY24부터 4년)
        'streak': {m: streak([(fy, by_fy[fy][m]) for fy in shown]) for m in METRICS},
        'calc': calc,
    }
