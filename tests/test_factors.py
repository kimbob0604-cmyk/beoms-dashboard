import json
import unittest

import build_factors as F
import db


class FactorTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(':memory:')

    def add(self, no, code, kind, title, data, day='2026-11-04'):
        self.conn.execute('INSERT INTO dart_filing (rcept_no, date, code, kind, title, data) VALUES (?, ?, ?, ?, ?, ?)',
                          (no, day, code, kind, title, json.dumps(data)))

    def test_shareholder_return_rules(self):
        self.add('1', 'A', 'buyback', '자기주식취득결정', {'amt': 100e8})
        self.add('2', 'A', 'cancel', '주식소각결정', {'amt': 300e8, 'how': '장내매수'})        # 취득과 같은 돈 → 빼기
        self.add('3', 'B', 'cancel', '주식소각결정', {'amt': 50e8, 'how': '기취득 자기주식'})   # 이미 가진 것 → 세기
        self.add('4', 'B', 'cancel', '[기재정정]주식소각결정', {'amt': 50e8, 'how': '기취득 자기주식'})  # 정정 중복
        self.add('5', 'C', 'buyback', '자기주식취득결정(자회사의 주요경영사항)', {'amt': 999e8})   # 자회사 → 빼기
        r = F.shareholder_return(self.conn, '2026-08-01')
        self.assertEqual(dict(r), {'A': 100.0, 'B': 50.0})

    def test_price_factors(self):
        xs = [100.0] * 230 + [150.0] * 23   # 253일: 12개월 전 100, 22거래일 전부터 150
        self.conn.executemany('INSERT INTO ohlc_daily (date, code, close) VALUES (?, ?, ?)',
                              [(f'2026-{i // 28 + 1:02d}-{i % 28 + 1:02d}', 'A', c) for i, c in enumerate(xs)])
        f = F.price_factors(self.conn, {'A'})['A']
        self.assertEqual(f['mom'], 50.0)
        self.assertGreater(f['vol'], 0)   # 60일 안에 한 번 뛴 값

    def test_consensus_turnaround(self):
        g = {'stocks': [{'c': 'A', 'mc': 1000, 'k': {'y0': {'op': {'k': 'turnaround', 'n': 50, 'm1': 0.1, 'm3': None}}}}]}
        f = F.consensus_factors(g)['A']
        self.assertEqual((f['grow'], f['ey'], f['rev1']), (F.TURNAROUND * 100, 5.0, 10.0))
        self.assertNotIn('rev3', f)


if __name__ == '__main__':
    unittest.main()
