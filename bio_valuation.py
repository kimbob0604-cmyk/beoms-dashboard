"""
바이오 밸류에이션 계산 (순수 함수, 입출력 없음). 방법론: Notion 'Bio기업 Valuation 방법론'.

- 시장위험: V0(오늘 가치)를 만들 때 WACC로 한 번만 (launch_value).
- 임상위험: 이항트리 노드의 PoS (실제확률). 시장과 무관하니 위험프리미엄 없음.
- 트리 안 할인: Rf. V의 상승확률 p 는 위험중립확률 (V를 복제 가능한 자산으로 가정, MAD).
- 임상 발표 노드 가치 = PoS × max(계속가치 − X, 0). X는 성공 뒤 내는 다음 단계 비용.

stage = {'t': 발표까지 남은 햇수, 'pos': 성공확률, 'x': 성공 뒤 비용}. 마지막 stage 가 출시(허가) 노드이고
그 뒤 V_T(출시 시점 가치)를 받는다.
"""

import math


def launch_value(peak, margin, tax, wacc, launch_in, ramp_years, exclusivity_years):
    """출시 후 세후 이익 흐름의 오늘 가치. 매출은 ramp_years 에 걸쳐 peak 까지 선형 상승, 독점기간 끝나면 0.
    연말 현금흐름, 출시 후 첫 해 말부터 센다."""
    pv = 0.0
    for k in range(int(exclusivity_years)):
        sales = peak * min(1.0, (k + 1) / ramp_years)
        pv += sales * margin * (1 - tax) / (1 + wacc) ** (launch_in + k + 1)
    return pv


def _grid(stages, dt):
    n = max(1, int(round(max(s['t'] for s in stages) / dt)))
    at = {}
    for s in sorted(stages, key=lambda s: s['t']):
        at.setdefault(int(round(s['t'] / dt)), []).append(s)
    return n, at


def _apply(cont, group):
    """한 시점에 겹친 stage 를 뒤에서부터 적용."""
    for s in reversed(group):
        cont = s['pos'] * max(cont - s['x'], 0.0)
    return cont


def option_value(v0, sigma, rf, stages, dt=0.25):
    """이항모형 실물옵션가치(ROV). 매 스텝 dt년, 위험중립확률 p."""
    n, at = _grid(stages, dt)
    growth = (1 + rf) ** dt
    u = math.exp(sigma * math.sqrt(dt))
    d = 1 / u
    p = (growth - d) / (u - d)
    if not 0 < p < 1:
        raise ValueError(f'위험중립확률이 범위를 벗어남 (p={p:.3f}); σ를 키우거나 dt를 줄이세요')
    vals = [v0 * u ** j * d ** (n - j) for j in range(n + 1)]
    if n in at:
        vals = [_apply(v, at[n]) for v in vals]
    for t in range(n - 1, -1, -1):
        vals = [(p * vals[j + 1] + (1 - p) * vals[j]) / growth for j in range(t + 1)]
        if t in at:
            vals = [_apply(v, at[t]) for v in vals]
    return vals[0]


def rnpv_forced(v0, rf, stages):
    """진행을 강제하는 rNPV (포기옵션 없음): 비용을 반드시 낸다."""
    ordered = sorted(stages, key=lambda s: s['t'])
    total, cum = 0.0, 1.0
    for s in ordered:
        cum *= s['pos']
        total += cum * -s['x'] / (1 + rf) ** s['t']
    return cum * v0 + total   # 위험중립 기대 V_T 를 Rf 로 되돌리면 V0


def rnpv_tree(v0, rf, stages):
    """트리형 rNPV: V는 불확실하지 않고(σ→0), 단계마다 계속가치가 X보다 작으면 포기. 계속가치도 함께 돌려준다."""
    ordered = sorted(stages, key=lambda s: s['t'])
    t_last = ordered[-1]['t']
    value = v0                                    # 출시 시점 V_T 를 지금 가치로 환산해 둔 값
    # 뒤에서 앞으로: 각 stage 의 (계속가치, 포기 여부)
    steps, cont = [], value
    for i in range(len(ordered) - 1, -1, -1):
        s = ordered[i]
        t_next = ordered[i + 1]['t'] if i + 1 < len(ordered) else t_last
        # 현재 노드 시점 기준 가치 = 오늘 가치 기준으로 유지하되 비용은 오늘 가치로 할인
        pv_x = s['x'] / (1 + rf) ** s['t']
        go = cont > pv_x
        steps.append({'t': s['t'], 'pos': s['pos'], 'x': s['x'], 'pv_x': pv_x, 'cont': cont, 'go': go,
                      'margin': cont / pv_x if pv_x > 0 else None})
        cont = s['pos'] * max(cont - pv_x, 0.0)
    steps.reverse()
    return cont, steps


def breakeven_pos(cont, pv_x):
    """다음 단계 비용을 감당하려면 이후 누적 성공확률이 최소 몇 %여야 하나(이후 가치 cont 는 PoS 1 기준)."""
    return pv_x / cont if cont > 0 else None


def implied_pos_scale(target, v0, sigma, rf, stages, hi=3.0, dt=0.25):
    """시장이 요구하는 PoS 배수: 모든 stage 의 PoS 에 같은 배수를 곱해 옵션가치가 target 과 같아지게 한다.
    배수는 PoS 가 1을 넘지 않는 범위로 자른다. 닿지 못하면 None."""
    def val(k):
        sc = [dict(s, pos=min(1.0, s['pos'] * k)) for s in stages]
        return option_value(v0, sigma, rf, sc, dt)
    lo, hi_ = 0.0, hi
    if val(hi_) < target:
        return None
    for _ in range(60):
        mid = (lo + hi_) / 2
        if val(mid) < target:
            lo = mid
        else:
            hi_ = mid
    return (lo + hi_) / 2


def dcf_commercial(run_rate, growth, margin_now, margin_target, margin_years, tax, wacc, loe_year_index, erosion, years=10):
    """상업화 제품 DCF. 영구 TV 없음: 정해진 연수까지만 센다.
    growth: 연도별 성장률 리스트(모자라면 마지막 값 유지, LOE 뒤에는 -erosion).
    loe_year_index: 몇 번째 해부터 침식이 시작되나(1부터)."""
    rev, pv, rows = run_rate, 0.0, []
    for y in range(1, years + 1):
        if y >= loe_year_index:
            g = -erosion
        else:
            g = growth[min(y - 1, len(growth) - 1)]
        rev *= 1 + g
        m = margin_now + (margin_target - margin_now) * min(1.0, y / max(1, margin_years))
        fcf = rev * m * (1 - tax)
        pv += fcf / (1 + wacc) ** (y - 0.5)
        rows.append({'y': y, 'rev': rev, 'margin': m, 'fcf': fcf})
    return pv, rows
