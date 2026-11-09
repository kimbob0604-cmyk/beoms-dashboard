import unittest

import bio_valuation as bv

STAGES = [{'t': 1, 'pos': 0.6, 'x': 30}, {'t': 3, 'pos': 0.35, 'x': 120}, {'t': 6, 'pos': 0.55, 'x': 20}]


class TestBioValuation(unittest.TestCase):
    def test_forced_rnpv_negative(self):
        self.assertAlmostEqual(bv.rnpv_forced(300, 0.035, STAGES), -7.349, places=2)

    def test_option_value_rises_with_sigma(self):
        lo = bv.option_value(300, 0.20, 0.035, STAGES, dt=1)
        mid = bv.option_value(300, 0.35, 0.035, STAGES, dt=1)
        hi = bv.option_value(300, 0.50, 0.035, STAGES, dt=1)
        self.assertAlmostEqual(lo, 0.0, places=3)      # 깊은 OTM: 포기가 맞다
        self.assertAlmostEqual(mid, 2.892, places=2)
        self.assertAlmostEqual(hi, 6.231, places=2)
        self.assertLess(lo, mid)
        self.assertLess(mid, hi)

    def test_tree_rnpv_abandons(self):
        val, steps = bv.rnpv_tree(300, 0.035, STAGES)
        self.assertAlmostEqual(val, 0.0, places=6)
        self.assertFalse(steps[0]['go'])               # t=1: 계속가치 < 비용
        self.assertTrue(steps[1]['go'])

    def test_tree_rnpv_positive_when_deep_itm(self):
        val, steps = bv.rnpv_tree(2000, 0.035, STAGES)
        self.assertGreater(val, 0)
        self.assertTrue(all(s['go'] for s in steps))

    def test_option_ge_tree(self):
        tree, _ = bv.rnpv_tree(300, 0.035, STAGES)
        self.assertGreaterEqual(bv.option_value(300, 0.35, 0.035, STAGES, dt=1), tree)

    def test_launch_value(self):
        # 1년 뒤 출시, 매출 100, 마진 50%, 세율 0, 독점 2년, 램프 1년, WACC 10%
        v = bv.launch_value(100, 0.5, 0, 0.10, 1, 1, 2)
        self.assertAlmostEqual(v, 50 / 1.1 ** 2 + 50 / 1.1 ** 3, places=6)

    def test_breakeven(self):
        self.assertAlmostEqual(bv.breakeven_pos(200, 50), 0.25)
        self.assertIsNone(bv.breakeven_pos(0, 50))

    def test_implied_scale(self):
        target = bv.option_value(300, 0.5, 0.035, STAGES, dt=1)
        k = bv.implied_pos_scale(target, 300, 0.5, 0.035, STAGES, dt=1)
        self.assertAlmostEqual(k, 1.0, places=2)
        self.assertIsNone(bv.implied_pos_scale(1e9, 300, 0.5, 0.035, STAGES, dt=1))

    def test_dcf_no_terminal_value(self):
        pv, rows = bv.dcf_commercial(100, [0.0], 0.4, 0.4, 1, 0.0, 0.10, 2, 0.5, years=3)
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[0]['rev'], 100)
        self.assertAlmostEqual(rows[1]['rev'], 50)     # 2년차부터 침식 50%
        self.assertGreater(pv, 0)


if __name__ == '__main__':
    unittest.main()
