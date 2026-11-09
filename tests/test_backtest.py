import math
import sqlite3
import unittest
from datetime import date, timedelta

import numpy as np

import build_backtest as B
import collect_history as H


def days_from(start, n):
    out, d = [], date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def make_sim(P, X=None):
    """P: [D, N] 가격. 첫 행은 START 전날(전일 가격용)"""
    D, N = P.shape
    days = days_from('2006-11-09', D)
    R = np.vstack([np.zeros((1, N)), P[1:] / P[:-1] - 1]).astype(np.float32)
    x = {'days': np.array(days), 'P': P.astype(np.float32), 'R': R, 'MC': np.full((D, N), 1000, np.float32),
         'idx': np.ones((2, D))}
    univ = np.ones((D, N), bool)
    return B.Sim(x, univ, np.zeros((D, N), bool) if X is None else X)


class SimTest(unittest.TestCase):
    def test_fixed_hold_one_trade(self):
        D = 400
        P = (1.01 ** np.arange(D))[:, None]
        sim = make_sim(P)
        S = np.zeros((sim.T, 1), bool)
        S[10] = True                                    # 신호 10일 → 11일 종가 매수 → 12일부터 수익
        r = sim.run(S, 'h120')
        m = r['m']
        self.assertEqual((m['tr'], m['hd'], m['win']), (1, 121, 100))   # 10+120 까지 보유 판단 → 132일까지 수익
        c = B.COST
        want = math.log((1.01 - c) * 1.01 ** 119 * 1.01 * (1 - c))
        self.assertAlmostEqual(r['nav'][-1] / 1000, want, places=2)
        self.assertEqual(max(r['n']), 1)

    def test_signal_repeats_extend_hold(self):
        P = np.ones((400, 1))
        sim = make_sim(P)
        S = np.zeros((sim.T, 1), bool)
        S[[10, 100]] = True                             # 120일 안에 다시 만족 → 한 번의 거래로 이어진다
        m = sim.run(S, 'h120')['m']
        self.assertEqual((m['tr'], m['hd']), (1, 211))

    def test_trend_exit_and_no_reentry_without_signal(self):
        D = 300
        P = np.ones((D, 2))
        X = np.zeros((D, 2), bool)
        X[51:, 0] = True                                # START 뒤 50일째부터 120일선 아래
        sim = make_sim(P, X)
        S = np.zeros((sim.T, 2), bool)
        S[5, 0] = True
        S[60, 0] = True                                 # 120일선 아래에서 나온 신호는 사지 않는다
        S[5, 1] = True                                  # 이탈이 없으면 끝까지 보유
        r = sim.run(S, 'trend', ['가', '나'], ['000010', '000020'])
        self.assertEqual(r['m']['tr'], 2)
        self.assertEqual(r['n'][0], 0)
        held = np.zeros(sim.T, int)
        held[sim.widx] = r['n']
        self.assertEqual(held[sim.widx[-1]], 1)
        self.assertEqual((r['nnow'], r['now'][0]['c']), (1, '000020'))

    def test_equal_money_no_rebalance(self):
        """두 종목을 같은 날 같은 금액 사면, 오른 종목 비중이 커진 채로 간다"""
        D = 200
        P = np.ones((D, 2))
        P[20:, 0] = 2.0                                 # START 뒤 19일째 A만 2배
        P[30:, 1] = 0.5 * 1.0                           # 그 뒤 B 반토막
        sim = make_sim(P)
        S = np.zeros((sim.T, 2), bool)
        S[2] = True
        r = sim.run(S, 'h250')
        nav = math.exp(r['nav'][-1] / 1000)
        self.assertAlmostEqual(nav, (2 + 0.5) / 2 * (1 - B.COST) ** 2, delta=0.02)


class FinTest(unittest.TestCase):
    def test_turnaround_and_growth_from_day_after_filing(self):
        conn = sqlite3.connect(':memory:')
        conn.executescript(H.SCHEMA)
        rows = [  # code, year, reprt, fs, acc, cur, cur_add, prev, prev_add, rcept
            ('000010', 2016, '11013', 'CFS', 'op', 10, 10, -5, -5, '20160516000001'),      # 적자 → 흑자
            ('000020', 2016, '11013', 'CFS', 'op', 30, 30, 10, 10, '20160516000002'),      # 3배
            ('000020', 2016, '11013', 'CFS', 'sales', 200, 200, 100, 100, '20160516000002'),
            ('000030', 2016, '11013', 'OFS', 'op', 11, 11, 10, 10, '20160516000003'),      # +10% 뿐
        ]
        conn.executemany('INSERT INTO fin VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
        days = days_from('2016-05-09', 120)
        cidx = {'000010': 0, '000020': 1, '000030': 2}
        E = B.fin_states(conn, cidx, days)
        i = days.index('2016-05-17')                    # 공시(5/16) 다음 거래일
        self.assertFalse(E['e_turn'][i - 1, 0])
        self.assertTrue(E['e_turn'][i, 0])
        self.assertTrue(E['e_up'][i, 1])
        self.assertFalse(E['e_up'][i, 2])
        self.assertFalse(E['e_turn'][i, 1])
        self.assertTrue(E['e_turn'][i + B.FIN_HOLD - 1, 0])
        self.assertFalse(E['e_turn'][i + B.FIN_HOLD, 0])   # 다음 공시가 없으면 100거래일까지만


class ParseTest(unittest.TestCase):
    def test_sise_rows(self):
        text = "[['날짜', '시가'],\n [\"20061101\", 12360, 12400, 12260, 12300, 279048, 49.71],\n [\"19900103\", 44000, 45000, 43200, 44800, 26240, ]]"
        rows = H.parse_sise(text)
        self.assertEqual(rows[0], ('2006-11-01', 12360.0, 12400.0, 12260.0, 12300.0, 279048.0, 49.71))
        self.assertIsNone(rows[1][6])


if __name__ == '__main__':
    unittest.main()
