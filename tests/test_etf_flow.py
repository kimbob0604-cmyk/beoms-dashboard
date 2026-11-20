import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build_etf_flow as E
import momentum


class JudgeTest(unittest.TestCase):
    def test_thresholds_and_minimum_amount(self):
        th = (0.05, 0.10)
        self.assertEqual(E.judge(None, th), 'u')
        self.assertEqual(E.judge(0.049, th, 50), 'n')
        self.assertEqual(E.judge(0.05, th, 50), 'b1')
        self.assertEqual(E.judge(0.10, th, 50), 'b2')
        self.assertEqual(E.judge(-0.07, th, -50), 's1')
        self.assertEqual(E.judge(-0.43, th, -0.2), 'n')       # 몫 0.2억 — 거래 거의 없는 종목은 비율이 커도 영향 작음


class AdvTest(unittest.TestCase):
    def test_prior_days_only_and_minimum_count(self):
        s = [(f'2026-10-{d:02d}', 10.0) for d in range(1, 21)] + [('2026-10-21', 1000.0)]
        self.assertEqual(E.adv(s, '2026-10-21'), 10.0)        # 그날(1000억)은 분모에 넣지 않는다
        self.assertIsNone(E.adv(s[:5], '2026-10-21'))         # 10일 미만이면 모름
        s2 = [(f'2026-10-{d:02d}', float(d)) for d in range(1, 31)]
        self.assertEqual(E.adv(s2, '2026-10-31'), sum(range(11, 31)) / 20)   # 직전 20일만


class RsiTest(unittest.TestCase):
    def test_series_matches_single_value_and_percentile(self):
        closes = [100 + (i % 7) * 1.5 - (i % 3) for i in range(80)]
        rs = E.rsi_series(closes)
        self.assertIsNone(rs[13])
        self.assertEqual(rs[-1], momentum.rsi(closes))
        self.assertEqual(E.pct_rank(list(range(100)), 90), 0.905)
        self.assertIsNone(E.pct_rank([50] * 10, 50))          # 이력이 짧으면 백분위 없음


class DayBlockTest(unittest.TestCase):
    def test_store_and_build_day(self):
        with tempfile.TemporaryDirectory() as d:
            mk = Path(d) / 'm.db'
            m = sqlite3.connect(str(mk))
            m.executescript('CREATE TABLE price_daily (date TEXT, code TEXT, trd_val REAL); CREATE TABLE ohlc_daily (date TEXT, code TEXT, close REAL, volume REAL);')
            days = [f'2026-10-{i:02d}' for i in range(1, 31)]
            for i, dd in enumerate(days):
                m.execute('INSERT INTO price_daily VALUES (?, ?, ?)', (dd, '000001', 100.0))
                m.execute('INSERT INTO ohlc_daily VALUES (?, ?, ?, ?)', (dd, '000001', 1000 + i, 1))
            m.commit()
            conn = sqlite3.connect(':memory:')
            conn.executescript(E.SCHEMA)
            top = [['069500', 'KODEX 200', 8e8], ['999999', '옛 비중 ETF', 1e8]]
            E.store(conn, [{'date': '2026-10-29', 'meta': {'coverage': 30, 'n_etfs': 2, 'n_total': 2, 'holdings_asof': '2026-10-01'},
                            'stale': {}, 'rows': [['000001', 'A', 3e8, 0, 0, 2, top]]},
                           {'date': '2026-10-30', 'meta': {'coverage': 30, 'n_etfs': 2, 'n_total': 2, 'holdings_asof': '2026-10-01'},
                            'stale': {'999999': '2026-10-01'}, 'rows': [['000001', 'A', 12e8, 0, 0, 2, top], ['000002', 'B', 1e6, 0, 0, 1, []]]}])
            with mock.patch.object(E, 'MARKET_DB', mk):
                b = E.day_block(conn)
            self.assertEqual((b['date'], b['n_stale'], b['hd']), ('2026-10-30', 1, ['2026-10-29', '2026-10-30']))
            x = next(r for r in b['rows'] if r['c'] == '000001')
            self.assertEqual((x['in'], x['adv'], x['r'], x['st']), (12.0, 100.0, 0.12, 'b2'))
            self.assertEqual(x['h'], [[3.0, 0.03], [12.0, 0.12]])
            self.assertEqual(x['top'][1][2], '2026-10-01')       # 순유입 큰 ETF 의 비중이 묵었다는 표시
            self.assertEqual(json.loads(json.dumps(b))['th'], list(E.TH))


if __name__ == '__main__':
    unittest.main()
