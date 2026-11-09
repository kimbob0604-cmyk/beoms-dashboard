import unittest

import adjust
import build_events as E
import db


class AdjustTest(unittest.TestCase):
    def test_bonus_issue_not_a_loss(self):
        conn = db.connect(':memory:')
        # 무상증자 권리락: 종가 10000 → 5000 이지만 KRX 등락률은 기준가(5000) 대비 +2%
        conn.executemany('INSERT INTO ohlc_daily (date, code, close, chg) VALUES (?, ?, ?, ?)',
                         [('2026-01-05', 'A', 10000, 0.0), ('2026-01-06', 'A', 5100, 2.0), ('2026-01-07', 'A', 5100, None)])
        xs = adjust.adjusted_series(conn)['A']
        self.assertAlmostEqual(xs[1] / xs[0] - 1, 0.02)
        self.assertAlmostEqual(xs[2], xs[1])   # 등락률 없는 날은 종가 비율로


class CarTest(unittest.TestCase):
    def test_excess_return(self):
        px = [100, 100, 110, 121]
        mx = [1000, 1000, 1010, 1020]
        self.assertAlmostEqual(E.car(px, mx, 2, -1, 1), (121 / 100 - 1) - (1020 / 1000 - 1))
        self.assertIsNone(E.car(px, mx, 2, -1, 5))              # 아직 안 지난 구간
        self.assertIsNone(E.car([100, None, 1, 1], mx, 2, -1, 0))

    def test_stats_clip(self):
        s = E.stats([0.1, 0.2, 3.0, None])   # 3.0 → 0.5 로 자름
        self.assertEqual(s['n'], 3)
        self.assertAlmostEqual(s['mean'], round((0.1 + 0.2 + 0.5) / 3 * 100, 2))
        self.assertEqual(s['med'], 20.0)
        self.assertEqual(s['hit'], 100.0)


if __name__ == '__main__':
    unittest.main()
