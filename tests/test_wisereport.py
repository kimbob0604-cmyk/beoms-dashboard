import json
import unittest
from pathlib import Path

from collectors import wisereport as wr

FIX = Path(__file__).parent / 'fixtures'


def load(name):
    return json.loads((FIX / name).read_text(encoding='utf-8'))


class ParseAnnualTest(unittest.TestCase):
    def test_pumtech(self):
        rows = {r['fy']: r for r in wr.parse_annual(load('annual_251970.json'))}
        self.assertEqual(sorted(rows), [2022, 2023, 2024, 2025, 2026, 2027, 2028])
        self.assertEqual(rows[2024]['op'], 484.0)
        self.assertEqual(rows[2025]['op'], 565.1)
        self.assertEqual(rows[2026]['op'], 753.0)
        self.assertEqual(rows[2027]['op'], 894.5)
        self.assertEqual(rows[2028]['op'], 1034.8)
        self.assertEqual(rows[2027]['revenue'], 5200.8)
        self.assertEqual(rows[2027]['eps'], 4930.0)
        self.assertEqual(rows[2025]['is_estimate'], 0)
        self.assertEqual(rows[2026]['is_estimate'], 1)
        self.assertEqual(rows[2026]['fy_month'], 12)
        self.assertEqual(rows[2026]['basis'], 'IFRS연결')

    def test_no_coverage_drops_empty_estimates(self):
        rows = wr.parse_annual(load('annual_000040.json'))
        self.assertTrue(rows)
        self.assertFalse([r for r in rows if r['is_estimate']])
        self.assertLess(rows[0]['op'], 0)  # 적자 실적은 음수 그대로

    def test_format_change_raises(self):
        with self.assertRaises(ValueError):
            wr.parse_annual({'JsonData': [{'YYMM': '2026/12'}]})
        with self.assertRaises(ValueError):
            wr.parse_annual({'rows': []})


class ParseTrendTest(unittest.TestCase):
    def test_pumtech_fy2027(self):
        t = {r['metric']: r for r in wr.parse_trend(load('trend_251970_2027.json'))}
        self.assertEqual(set(t), {'revenue', 'op', 'ni', 'eps', 'opinion'})
        op = t['op']
        self.assertEqual((op['now'], op['w1'], op['m1'], op['m3'], op['y1']),
                         (895.0, 895.0, 895.0, 868.0, 870.0))
        self.assertEqual(op['cns_date'], '2026-11-02')

    def test_zero_means_missing(self):
        payload = {'JsonData': [{'ACC_CD': '121500', 'DT': '20261102',
                                 'VAL1': 1035.0, 'VAL2': 1035.0, 'VAL3': 1035.0,
                                 'VAL4': 1002.0, 'VAL5': 0.0}]}
        op = wr.parse_trend(payload)[0]
        self.assertEqual(op['m3'], 1002.0)
        self.assertIsNone(op['y1'])


class ParseOverviewTest(unittest.TestCase):
    def test_header(self):
        meta = wr.parse_overview((FIX / 'overview_251970.html').read_text(encoding='utf-8'))
        self.assertEqual(meta, {'name': '펌텍코리아', 'market': 'KOSDAQ',
                                'market_sector': '코스닥 화학', 'wics': '포장재'})


class ToNumTest(unittest.TestCase):
    def test_values(self):
        self.assertEqual(wr.to_num('1,034.8'), 1034.8)
        self.assertEqual(wr.to_num('-62.3'), -62.3)
        self.assertIsNone(wr.to_num(''))
        self.assertIsNone(wr.to_num('-'))
        self.assertIsNone(wr.to_num(None))
        self.assertEqual(wr.to_num(4.0), 4.0)


if __name__ == '__main__':
    unittest.main()
