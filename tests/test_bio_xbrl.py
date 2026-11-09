import unittest

import bio_xbrl as bx


def f(start, end, val, filed='2026-08-01'):
    d = {'end': end, 'val': val, 'filed': filed}
    if start:
        d['start'] = start
    return d


class TestQuarterly(unittest.TestCase):
    def test_direct_quarter_and_ytd_difference(self):
        facts = [
            f('2026-01-01', '2026-03-31', -33.0e6),          # 1분기 (3개월)
            f('2026-01-01', '2026-06-30', -62.8e6),          # 상반기 누적만 있음 → 2분기 = -29.8
            f('2025-01-01', '2025-12-31', -100e6),           # 연간
            f('2025-01-01', '2025-09-30', -75e6),            # 9개월 누적 → 4분기 = -25
        ]
        q = bx.quarterly(facts)
        self.assertAlmostEqual(q['2026-03-31'], -33.0e6)
        self.assertAlmostEqual(q['2026-06-30'], -29.8e6)
        self.assertAlmostEqual(q['2025-12-31'], -25e6)

    def test_latest_filing_wins(self):
        facts = [f('2026-04-01', '2026-06-30', 10e6, '2026-08-01'), f('2026-04-01', '2026-06-30', 11e6, '2026-11-01')]
        self.assertEqual(bx.quarterly(facts)['2026-06-30'], 11e6)

    def test_fiscal_year_not_calendar(self):
        # 3월 결산 회사: 4~6월(3개월), 4~9월(6개월) → 7~9월 = 6개월 - 3개월
        facts = [f('2026-04-01', '2026-06-30', -124.4e6), f('2026-04-01', '2026-09-30', -207.6e6)]
        self.assertAlmostEqual(bx.quarterly(facts)['2026-09-30'], -83.2e6)

    def test_label(self):
        self.assertEqual(bx.label('2026-09-30'), '2026 Q3')

    def test_summarize_runway(self):
        usd = lambda rows: {'units': {'USD': rows}}
        facts = {'facts': {'us-gaap': {
            'NetCashProvidedByUsedInOperatingActivities': usd([f('2026-01-01', '2026-03-31', -30e6), f('2026-01-01', '2026-06-30', -60e6)]),
            'CashAndCashEquivalentsAtCarryingValue': usd([f(None, '2026-06-30', 40e6)]),
            'ShortTermInvestments': usd([f(None, '2026-06-30', 140e6)]),
        }, 'dei': {'EntityCommonStockSharesOutstanding': {'units': {'shares': [{'end': '2026-08-01', 'val': 100e6, 'form': '10-Q'}]}}}}}
        s = bx.summarize(facts)
        self.assertEqual(s['balance']['cash_total'], 180.0)
        self.assertEqual(s['burn_quarter'], 30.0)
        self.assertEqual(s['runway_months'], 18.0)     # 180 / 30 × 3
        self.assertEqual(s['shares']['value'], 100.0)


if __name__ == '__main__':
    unittest.main()
