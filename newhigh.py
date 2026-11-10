"""
신고가 판정 (순수 계산, tests/test_newhigh.py) — 네이버 '52주 신고가' 목록 대신 가격 이력으로 직접 계산한다.

정의 (KBJ 보드 엔진·장마감 시황과 같은 규칙):
  기준          종가. 수정주가(권리락·분할 반영 — 전날 값 × (1 + KRX 등락률))로 비교한다
  역사적 hist   보유 이력 전체(2010-01-04 이후 또는 상장 이후)의 최고 종가 초과. 이력이 MIN_BARS_HIST 거래일 미만이면 판정하지 않는다
  52주  w52     판정일 − 364일 ≤ 날짜 < 판정일 창의 최고 종가 초과 (달력 기준)
  120일 d120    판정일 직전 120 시장 거래일 창의 최고 종가 초과
  60일  d60     판정일 직전 60 시장 거래일 창의 최고 종가 초과
  비교          당일 종가 > 창 최고 종가 (같은 값은 신고가가 아니다). 당일은 창에 넣지 않는다
  창 못 채움    종목의 첫 봉이 창의 첫 거래일보다 뒤면(상장한 지 얼마 안 됨) 그 축은 판정하지 않는다
  라벨          역사적 > 52주 > 120일 > 60일 가운데 가장 높은 것 하나
  거래정지      창의 경계는 시장 거래일로 정하고 그 안에 있는 그 종목의 봉만 본다

행렬: C[종목, 날짜] = 수정 종가(없는 날 nan). 날짜 축 days 는 시장 거래일 오름차순.
"""

from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

import numpy as np

AXES = ('hist', 'w52', 'd120', 'd60')          # 우선순위 순
LABEL = {'hist': '역사적', 'w52': '52주', 'd120': '120일', 'd60': '60일'}
TRADING = {'d120': 120, 'd60': 60}
W52_DAYS = 364
MIN_BARS_HIST = 60                              # 상장 직후 종목이 날마다 역사적 신고가로 잡히지 않게
RANK = {a: i for i, a in enumerate(AXES)}


def chain(rows: Sequence[tuple], start: Optional[tuple] = None) -> List[float]:
    """한 종목의 (종가, 등락률%) 날짜순 → 수정 종가. 등락률이 없으면 종가 비율로 잇는다.
    start = (직전 수정 종가, 직전 종가) 를 주면 그 뒤에 이어 붙인다."""
    out, prev = [], start
    for close, chg in rows:
        if prev is None:
            adj = close
        elif chg is not None:
            adj = prev[0] * (1 + chg / 100)
        else:
            adj = prev[0] * close / prev[1]
        prev = (adj, close)
        out.append(adj)
    return out


def _window_max(C: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """C[:, lo:hi] 의 종목별 최대 (전부 nan 이면 nan)"""
    if hi <= lo:
        return np.full(C.shape[0], np.nan)
    w = C[:, lo:hi]
    out = np.full(C.shape[0], np.nan)
    ok = ~np.isnan(w).all(axis=1)
    out[ok] = np.nanmax(w[ok], axis=1)
    return out


def evaluate(C: np.ndarray, days: Sequence[str], t: int, pre: Optional[np.ndarray] = None,
             pre_bars: Optional[np.ndarray] = None) -> Dict[str, np.ndarray]:
    """
    t 번째 날의 축별 신고가 여부 {축: bool[종목]}.
    pre      행렬이 시작되기 전 이력의 최고 수정 종가 (없으면 nan) — 역사적 신고가용
    pre_bars 행렬 시작 전 봉 수 (0 이면 행렬 안의 첫 봉이 그 종목의 첫 봉)
    """
    n = C.shape[0]
    cur = C[:, t]
    has = ~np.isnan(cur)
    pre = np.full(n, np.nan) if pre is None else pre
    pre_bars = np.zeros(n, dtype=int) if pre_bars is None else pre_bars
    valid = ~np.isnan(C[:, :t + 1])
    first = np.where(valid.any(axis=1), valid.argmax(axis=1), t + 1)     # 행렬 안 첫 봉의 칸
    first = np.where(pre_bars > 0, -1, first)                             # 행렬 전에 봉이 있으면 처음부터 덮는다
    out = {}
    # 역사적: 지금까지 전부
    ref = np.fmax(pre, _window_max(C, 0, t))
    bars = pre_bars + valid[:, :t].sum(axis=1)
    out['hist'] = has & (bars >= MIN_BARS_HIST) & (cur > ref)
    # 52주 (달력)
    s = (date.fromisoformat(days[t]) - timedelta(days=W52_DAYS)).isoformat()
    i0 = next((i for i, d in enumerate(days[:t]) if d >= s), t)
    covered = days[0] <= s                                                # 행렬이 창의 시작까지 닿는가
    ref = _window_max(C, i0, t)
    out['w52'] = has & (first <= i0) & (cur > ref) if covered and i0 < t else np.zeros(n, bool)
    # 거래일 창
    for ax, k in TRADING.items():
        if t < k:
            out[ax] = np.zeros(n, bool)
            continue
        ref = _window_max(C, t - k, t)
        out[ax] = has & (first <= t - k) & (cur > ref)
    return out


def labels(hits: Dict[str, np.ndarray]) -> np.ndarray:
    """축별 여부 → 종목별 가장 높은 축의 순위 (0=역사적 … 3=60일, 없으면 -1)"""
    n = len(next(iter(hits.values())))
    out = np.full(n, -1, dtype=int)
    for ax in reversed(AXES):
        out[hits[ax]] = RANK[ax]
    return out


def history(C: np.ndarray, days: Sequence[str], span: int, pre=None, pre_bars=None) -> np.ndarray:
    """마지막 span 거래일의 라벨 행렬 [종목, span] (labels 와 같은 값). 판정할 수 없는 앞쪽 날은 -1"""
    T = C.shape[1]
    span = min(span, T)
    L = np.full((C.shape[0], span), -1, dtype=int)
    for j in range(span):
        L[:, j] = labels(evaluate(C, days, T - span + j, pre, pre_bars))
    return L


def run_length(flags: np.ndarray) -> np.ndarray:
    """[종목, 날짜] 불리언 → 마지막 날부터 거꾸로 연속으로 참인 일수"""
    rev = flags[:, ::-1]
    stop = (~rev).argmax(axis=1)
    return np.where(rev.all(axis=1), flags.shape[1], stop)
