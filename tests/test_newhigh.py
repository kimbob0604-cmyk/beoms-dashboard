import unittest
from datetime import date, timedelta

import numpy as np

import newhigh as N


def bdays(n, end=date(2026, 11, 10)):
    """주말을 뺀 거래일 n개 (오름차순 ISO)"""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


class ChainTest(unittest.TestCase):
    def test_split_does_not_look_like_a_drop(self):
        # 5:1 액면분할: 종가 50,000 → 10,100 이지만 KRX 등락률은 +1%
        adj = N.chain([(50000, None), (10100, 1.0), (10201, 1.0)])
        self.assertAlmostEqual(adj[1], 50500)
        self.assertAlmostEqual(adj[2], 51005)

    def test_missing_chg_uses_close_ratio_and_continues(self):
        self.assertEqual(N.chain([(110, None)], start=(200.0, 100.0)), [220.0])
        self.assertEqual(N.chain([(100, None), (90, None)]), [100, 90.0])


class EvaluateTest(unittest.TestCase):
    def setUp(self):
        self.days = bdays(300)
        self.T = len(self.days)

    def mat(self, *rows):
        return np.array(rows, dtype=float)

    def test_axes_nest_and_label_is_highest(self):
        t = self.T - 1
        base = np.full(self.T, 100.0)
        d60 = base.copy(); d60[t - 100] = 120; d60[t] = 110            # 100일 전 고점 120 → 60일만 신고가
        d120 = base.copy(); d120[t - 200] = 120; d120[t] = 110         # 200일 전 고점 → 120일까지 신고가
        w52 = base.copy(); w52[t] = 110                                # 행렬 전체(300일 > 52주)에서 최고
        none = base.copy(); none[t - 10] = 111; none[t] = 110          # 10일 전이 더 높다
        C = self.mat(d60, d120, w52, none)
        pre = np.array([np.nan, np.nan, 150.0, np.nan])                # 세 번째 종목은 2년 전 150 이 있었다
        bars = np.array([500, 500, 500, 500])
        hits = N.evaluate(C, self.days, t, pre, bars)
        self.assertEqual(N.labels(hits).tolist(), [N.RANK['d60'], N.RANK['d120'], N.RANK['w52'], -1])
        self.assertTrue(hits['d60'][1] and hits['d60'][2])             # 위 축이 서면 아래 축도 선다
        pre[2] = 105.0                                                 # 과거 고점이 더 낮으면 역사적
        self.assertEqual(N.labels(N.evaluate(C, self.days, t, pre, bars))[2], N.RANK['hist'])

    def test_equal_is_not_a_new_high_and_today_is_outside_window(self):
        t = self.T - 1
        a = np.full(self.T, 100.0)                                     # 내내 100 → 같은 값은 신고가 아님
        b = np.full(self.T, 100.0); b[t] = 100.01
        hits = N.evaluate(self.mat(a, b), self.days, t, None, np.array([400, 400]))
        self.assertEqual([bool(hits['d60'][0]), bool(hits['d60'][1])], [False, True])

    def test_new_listing_only_gets_axes_it_covers(self):
        t = self.T - 1
        c = np.full(self.T, np.nan); c[t - 80:] = 100; c[t] = 130      # 상장 81거래일째
        hits = N.evaluate(self.mat(c), self.days, t)
        self.assertTrue(hits['d60'][0])
        self.assertFalse(hits['d120'][0] or hits['w52'][0])            # 창을 못 채움
        self.assertTrue(hits['hist'][0])                               # 상장 뒤 전체 최고 (60거래일 이상)
        young = np.full(self.T, np.nan); young[t - 30:] = 100; young[t] = 130
        self.assertEqual(N.labels(N.evaluate(self.mat(young), self.days, t))[0], -1)   # 30거래일째는 판정 안 함

    def test_suspension_does_not_stretch_window(self):
        t = self.T - 1
        c = np.full(self.T, 100.0); c[t - 70] = 150                    # 70거래일 전 고점
        c[t - 50:t - 10] = np.nan                                      # 그 사이 40일 거래정지
        c[t] = 120
        self.assertTrue(N.evaluate(self.mat(c), self.days, t, None, np.array([400]))['d60'][0])   # 창은 시장 거래일 60일

    def test_w52_is_calendar_based_and_needs_coverage(self):
        t = self.T - 1
        c = np.full(self.T, 100.0); c[t] = 120
        s = (date.fromisoformat(self.days[t]) - timedelta(days=364)).isoformat()
        i0 = next(i for i, d in enumerate(self.days) if d >= s)
        c[i0 - 1] = 130                                                # 창 바로 앞날의 고점은 52주 밖
        self.assertTrue(N.evaluate(self.mat(c), self.days, t, None, np.array([400]))['w52'][0])
        c[i0] = 130                                                    # 창 첫날이면 안
        self.assertFalse(N.evaluate(self.mat(c), self.days, t, None, np.array([400]))['w52'][0])
        short = self.days[-200:]                                       # 행렬이 52주에 못 미치면 판정 안 함
        self.assertFalse(N.evaluate(self.mat(np.r_[np.full(199, 100.0), 120.0]), short, 199, None, np.array([400]))['w52'][0])

    def test_history_and_run_length(self):
        t = self.T - 1
        c = np.full(self.T, 100.0); c[t - 2:] = [101, 102, 103]        # 사흘 연속 신고가
        d = np.full(self.T, 100.0); d[t - 2:] = [101, 100, 103]        # 하루 쉬고 다시
        L = N.history(self.mat(c, d), self.days, 5, None, np.array([400, 400]))
        self.assertEqual((L[0] >= 0).tolist(), [False, False, True, True, True])
        self.assertEqual(N.run_length(L >= 0).tolist(), [3, 1])
        self.assertEqual(N.run_length(np.array([[True, True], [False, False]])).tolist(), [2, 0])


if __name__ == '__main__':
    unittest.main()
