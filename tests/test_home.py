import unittest
from datetime import date, timedelta

import build_home as H
import db


def days(n):
    d, out = date(2026, 1, 5), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


class SignalTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(':memory:')
        self.ds = days(130)
        rows = []
        for i, d in enumerate(self.ds):
            rows.append((d, 'A', 100 + i))       # 꾸준히 오름 → 이동평균 위
            rows.append((d, 'B', 300 - i))       # 꾸준히 내림 → 이동평균 아래
        self.conn.executemany('INSERT INTO ohlc_daily (date, code, close) VALUES (?, ?, ?)', rows)

    def test_breadth(self):
        m = H.ma_breadth(self.conn, {'A': 'KOSPI', 'B': 'KOSPI'})
        self.assertEqual(len(m['d']), H.MAB_DAYS)
        self.assertEqual(m['KOSPI']['20'][-1], 50.0)     # 2종목 중 1종목
        self.assertEqual(m['KOSPI']['120'][-1], 50.0)
        self.assertIsNone(m['KOSDAQ']['20'][-1])         # 종목 없음

    def test_period_returns(self):
        info = {'A': {'p': 100 + 129}, 'B': {'p': 300 - 129}}
        r = H.period_returns(self.conn, info, self.ds[-1])
        self.assertAlmostEqual(r['A']['w1'], (229 / 224 - 1) * 100, places=1)   # 5거래일 전 종가 224
        r2 = H.period_returns(self.conn, info, '2099-01-01')   # 오늘 일봉이 아직 없는 장중
        self.assertAlmostEqual(r2['A']['w1'], (229 / 225 - 1) * 100, places=1)

    def test_spike(self):
        pd = days(21)
        rows = [(d, 'A', 'A', 'KOSPI', 10.0) for d in pd[:-1]] + [(pd[-1], 'A', 'A', 'KOSPI', 40.0)]
        rows += [(d, 'B', 'B', 'KOSPI', 10.0) for d in pd]
        self.conn.executemany('INSERT INTO price_daily (date, code, name, market, trd_val) VALUES (?, ?, ?, ?, ?)', rows)
        info = {'A': {'n': 'A', 'mk': 'KOSPI', 'mc': 1000, 'p': 1, 'ch': 1}, 'B': {'n': 'B', 'mk': 'KOSPI', 'mc': 1000, 'p': 1, 'ch': 0}}
        s = H.trd_spike(self.conn, info, None)
        self.assertEqual([(x['c'], x['x']) for x in s['list']], [('A', 4.0)])


if __name__ == '__main__':
    unittest.main()
