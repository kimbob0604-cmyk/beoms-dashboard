import unittest
from datetime import date

import growth as g


def row(fy, op, est, month=12, revenue=None, ni=None, eps=None):
    return {'fy': fy, 'fy_month': month, 'is_estimate': est,
            'revenue': revenue, 'op': op, 'ni': ni, 'eps': eps}


# 펌텍코리아 (2026-11-02 스냅샷)
PUMTECH = [
    row(2022, 264.8, 0), row(2023, 352.9, 0), row(2024, 484.0, 0), row(2025, 565.1, 0),
    row(2026, 753.0, 1), row(2027, 894.5, 1), row(2028, 1034.8, 1),
]
PUMTECH_TREND = [
    {'fy': 2027, 'metric': 'op', 'now': 895.0, 'w1': 895.0, 'm1': 895.0, 'm3': 868.0},
]


class BucketTest(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(g.bucket(-10, 5), 'turnaround')
        self.assertEqual(g.bucket(0, 5), 'turnaround')
        self.assertEqual(g.bucket(-10, -5), 'loss')
        self.assertEqual(g.bucket(100, 250), 'g100')
        self.assertEqual(g.bucket(100, 200), 'g100')
        self.assertEqual(g.bucket(100, 150), 'g50')
        self.assertEqual(g.bucket(100, 149), 'g0')
        self.assertEqual(g.bucket(100, 100), 'g0')
        self.assertEqual(g.bucket(100, 99), 'decline')
        self.assertEqual(g.bucket(100, -5), 'decline')   # 적자전환도 감익
        self.assertIsNone(g.bucket(None, 5))

    def test_growth_undefined_for_nonpositive_base(self):
        self.assertIsNone(g.growth(-10, 5))
        self.assertAlmostEqual(g.growth(753.0, 894.5), 0.18791, places=4)


class ThisFyTest(unittest.TestCase):
    def test_december(self):
        self.assertEqual(g.this_fy(PUMTECH, date(2026, 11, 2)), 2026)
        self.assertEqual(g.this_fy(PUMTECH, date(2026, 12, 30)), 2026)
        self.assertEqual(g.this_fy(PUMTECH, date(2027, 1, 5)), 2027)

    def test_march_fiscal_year(self):
        rows = [row(2026, 1, 0, 3), row(2027, 1, 1, 3), row(2028, 1, 1, 3)]
        self.assertEqual(g.this_fy(rows, date(2026, 11, 2)), 2027)


class StreakTest(unittest.TestCase):
    def test_pumtech(self):
        self.assertEqual(g.streak([(r['fy'], r['op']) for r in PUMTECH]), {'from': 2022, 'years': 6})

    def test_break_and_loss(self):
        self.assertEqual(g.streak([(2024, 484), (2025, 400), (2026, 500), (2027, 600)]),
                         {'from': 2025, 'years': 2})
        self.assertIsNone(g.streak([(2026, -10), (2027, 5)]))   # 흑자전환은 증익 연속 아님
        self.assertIsNone(g.streak([(2026, 10), (2027, 5)]))


class MultipleAndLowBaseTest(unittest.TestCase):
    def test_multiple(self):
        self.assertAlmostEqual(g.multiple('op', 753.0, 7986, 64400), 10.6, places=1)
        self.assertAlmostEqual(g.multiple('op', 894.5, 7986, 64400), 8.9, places=1)
        self.assertAlmostEqual(g.multiple('eps', 4930, 7986, 64400), 13.06, places=2)
        self.assertIsNone(g.multiple('op', -5, 7986, 64400))

    def test_low_base(self):
        self.assertTrue(g.is_low_base('op', 25, 1000, 1))       # 30억 미만
        self.assertTrue(g.is_low_base('op', 50, 10000, 1))      # 시총 1% 미만
        self.assertFalse(g.is_low_base('op', 753, 7986, 64400))
        self.assertFalse(g.is_low_base('op', -5, 7986, 64400))  # 적자는 기저 아님(버킷이 따로 처리)
        self.assertTrue(g.is_low_base('eps', 500, 0, 64400))    # EPS/주가 < 1%


class ComputeStockTest(unittest.TestCase):
    def test_pumtech_matches_screenshot(self):
        r = g.compute_stock(PUMTECH, PUMTECH_TREND, mcap=7986, price=64400, as_of=date(2026, 11, 2))
        op = r['calc']['y0']['op']
        self.assertEqual(r['fy0'], 2026)
        self.assertEqual((op['base'], op['next']), (753.0, 894.5))
        self.assertEqual(round(op['g'] * 100, 1), 18.8)          # 스크린샷 +18.8%
        self.assertEqual(op['bucket'], 'g0')
        self.assertEqual(round(op['mult_base'], 1), 10.6)        # POR 10.6배
        self.assertEqual(round(op['mult_next'], 1), 8.9)         # → 8.9배
        self.assertFalse(op['low_base'])
        self.assertEqual(op['rev_m1'], 0.0)
        self.assertAlmostEqual(op['rev_m3'], 27 / 868)
        y1 = r['calc']['y1']['op']
        self.assertEqual((y1['base'], y1['next']), (894.5, 1034.8))
        self.assertEqual([s[0] for s in r['series']['op']], [2024, 2025, 2026, 2027, 2028])
        self.assertEqual(r['streak']['op'], {'from': 2024, 'years': 4})  # "FY24부터 4년 연속 증익"

    def test_fiscal_year_change_uses_latest_month(self):
        # 2023년에 3월 → 12월 결산 변경: 2023.03 행은 버리고 계산
        rows = [row(2023, 4, 0, 3), row(2023, -9, 0, 12), row(2024, -118, 0), row(2025, -375, 0),
                row(2026, -370, 1), row(2027, -330, 1), row(2028, -320, 1)]
        r = g.compute_stock(rows, [], 100, 1, date(2026, 11, 2))
        self.assertEqual(r['calc']['y0']['op']['bucket'], 'loss')
        self.assertEqual([s[0] for s in r['series']['op']], [2024, 2025, 2026, 2027, 2028])

    def test_no_estimates(self):
        rows = [row(2024, 10, 0), row(2025, 12, 0)]
        self.assertIsNone(g.compute_stock(rows, [], 100, 1, date(2026, 11, 2)))


if __name__ == '__main__':
    unittest.main()
