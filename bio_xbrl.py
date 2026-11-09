"""
SEC XBRL companyfacts → 분기 재무·재무상태 (회사가 공시한 원문 수치, 키 없이 data.sec.gov 에서 받음).

- 손익·현금흐름은 공시가 3개월(분기) 값 또는 연초부터 누적(YTD) 값으로 올라온다.
  분기 값이 있으면 그대로 쓰고, 없으면 같은 시작일의 누적 값끼리 빼서 분기 값을 만든다(예: 6개월 − 3개월).
- 같은 기간이 여러 공시에 다시 나오면(정정·비교 표시) 가장 나중에 제출된 값을 쓴다.
- 회사마다 쓰는 항목 이름이 달라서 후보 목록 중 가장 최근까지 쓰인 이름을 고른다. 어떤 이름을 썼는지 결과에 남긴다.

  python3 bio_xbrl.py 1819576
"""

import sys
from datetime import date

FLOW = {
    'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'RevenueFromContractWithCustomerIncludingAssessedTax'],
    'rnd': ['ResearchAndDevelopmentExpense', 'ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost'],
    'sga': ['SellingGeneralAndAdministrativeExpense', 'GeneralAndAdministrativeExpense'],
    'op_income': ['OperatingIncomeLoss'],
    'net_income': ['NetIncomeLoss'],
    'opcf': ['NetCashProvidedByUsedInOperatingActivities'],
}
INSTANT = {
    'cash': ['CashAndCashEquivalentsAtCarryingValue'],
    'sti': ['ShortTermInvestments', 'AvailableForSaleSecuritiesDebtSecuritiesCurrent', 'MarketableSecuritiesCurrent'],
    'debt_current': ['LongTermDebtCurrent'],
    'debt_noncurrent': ['LongTermDebtNoncurrent'],
}
EPS = ['EarningsPerShareDiluted', 'EarningsPerShareBasicAndDiluted', 'EarningsPerShareBasic']
N_QUARTERS = 8


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _span(f) -> int:
    return (_d(f['end']) - _d(f['start'])).days


def _latest_by_period(facts: list) -> dict:
    """(start, end) → 가장 나중에 제출된 사실."""
    out = {}
    for f in facts:
        k = (f.get('start'), f['end'])
        if k not in out or f.get('filed', '') > out[k].get('filed', ''):
            out[k] = f
    return out


def quarterly(facts: list, derive: bool = True) -> dict:
    """기간 값 목록 → {분기 종료일: 값}. 분기(80~100일) 값 우선, 없으면 같은 시작일 누적 값의 차이.
    주당순이익은 주식 수가 분기마다 달라 누적 값끼리 빼면 틀리므로 derive=False 로 분기 값만 쓴다."""
    per = _latest_by_period([f for f in facts if f.get('start')])
    q = {}
    for (s, e), f in per.items():
        if 80 <= _span(f) <= 100:
            q[e] = f['val']
    if not derive:
        return q
    by_start = {}
    for (s, e), f in per.items():
        by_start.setdefault(s, []).append((e, f['val']))
    for s, rows in by_start.items():
        rows.sort()
        for i in range(1, len(rows)):
            e, v = rows[i]
            pe, pv = rows[i - 1]
            gap = (_d(e) - _d(pe)).days
            if e not in q and 80 <= gap <= 100:
                q[e] = v - pv
    return q


def instants(facts: list) -> dict:
    per = _latest_by_period([f for f in facts if not f.get('start')])
    return {e: f['val'] for (_, e), f in per.items()}


def pick(gaap: dict, names: list):
    """후보 이름 중 가장 최근 날짜까지 쓰인 것 (같으면 목록 앞쪽)."""
    best, best_end = None, ''
    for n in names:
        units = gaap.get(n, {}).get('units', {}).get('USD')
        if not units:
            continue
        end = max(u['end'] for u in units)
        if end > best_end:
            best, best_end = n, end
    return best


def label(end: str) -> str:
    d = _d(end)
    return f'{d.year} Q{(d.month - 1) // 3 + 1}'


def summarize(facts: dict) -> dict:
    gaap = facts.get('facts', {}).get('us-gaap', {})
    dei = facts.get('facts', {}).get('dei', {})
    used, series = {}, {}
    for key, names in FLOW.items():
        n = pick(gaap, names)
        used[key] = n
        series[key] = quarterly(gaap[n]['units']['USD']) if n else {}
    ends = sorted(set().union(*[set(v) for v in series.values()]))[-N_QUARTERS:]
    eps_name = next((n for n in EPS if gaap.get(n, {}).get('units', {}).get('USD/shares')), None)
    used['eps'] = eps_name
    eps = quarterly(gaap[eps_name]['units']['USD/shares'], derive=False) if eps_name else {}
    quarters = [{'end': e, 'label': label(e), **{k: (series[k][e] / 1e6 if e in series[k] else None) for k in FLOW},
                 'eps': eps.get(e)} for e in ends]
    inst, inst_used = {}, {}
    for key, names in INSTANT.items():
        n = pick(gaap, names)
        inst_used[key] = n
        inst[key] = instants(gaap[n]['units']['USD']) if n else {}
    bal_end = max(inst['cash']) if inst['cash'] else None
    g = lambda k: (inst[k].get(bal_end) / 1e6) if bal_end and bal_end in inst[k] else None
    sh = dei.get('EntityCommonStockSharesOutstanding', {}).get('units', {}).get('shares', [])
    sh_last = max(sh, key=lambda x: (x['end'], x.get('filed', ''))) if sh else None
    debt = None
    if g('debt_current') is not None or g('debt_noncurrent') is not None:
        debt = (g('debt_current') or 0) + (g('debt_noncurrent') or 0)
    recent_cf = [q['opcf'] for q in quarters if q['opcf'] is not None][-2:]
    burn_q = -sum(recent_cf) / len(recent_cf) if recent_cf and sum(recent_cf) < 0 else None
    cash_total = (g('cash') or 0) + (g('sti') or 0) if bal_end else None
    filed = max((f.get('filed', '') for n in used.values() if n for us in gaap[n]['units'].values() for f in us), default=None)
    return {
        'quarters': quarters, 'concepts': {**used, **inst_used},
        'balance': {'end': bal_end, 'cash': g('cash'), 'sti': g('sti'), 'cash_total': cash_total, 'debt': debt},
        'shares': {'value': sh_last['val'] / 1e6, 'date': sh_last['end'], 'form': sh_last.get('form')} if sh_last else None,
        'burn_quarter': burn_q,
        'runway_months': (cash_total / burn_q * 3) if burn_q and cash_total else None,
        'last_filed': filed,
    }


def fetch(cik: int) -> dict:
    import bio_events as be
    return be.sec_get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json').json()


if __name__ == '__main__':
    import json
    s = summarize(fetch(int(sys.argv[1] if len(sys.argv) > 1 else 1819576)))
    print(json.dumps({k: v for k, v in s.items() if k != 'quarters'}, ensure_ascii=False, indent=1))
    for q in s['quarters']:
        print(q['label'], {k: (round(v, 1) if v is not None else None) for k, v in q.items() if k not in ('end', 'label')})
