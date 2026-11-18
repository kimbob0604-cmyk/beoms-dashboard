"""맥이 잘 때 Actions 가 사이트 홈을 장중 시세로 갱신 (cloud_live.py)"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import cloud_live as CL

BASE = {'d': '2026-11-17', 'w': ['반도체', '화장품'],
        's': {'005930': [0, 10000, 100.0, 0, 50.0], '000660': [0, 8000, 200.0, 0, 10.0], '278470': [1, 4000, 50.0, 1, 2.0]}}
QUOTES = [{'date': '2026-11-18', 'code': '005930', 'name': '삼성전자', 'market': 'KOSPI', 'close': 110.0, 'change_pct': 10.0,
           'mcap': 0, 'trd_val': 400.0},
          {'date': '2026-11-18', 'code': '000660', 'name': 'SK하이닉스', 'market': 'KOSPI', 'close': 190.0, 'change_pct': -5.0,
           'mcap': 0, 'trd_val': 5.0},
          {'date': '2026-11-18', 'code': '278470', 'name': '에이피알', 'market': 'KOSDAQ', 'close': 50.0, 'change_pct': 0.0,
           'mcap': 0, 'trd_val': 1.0},
          {'date': '2026-11-18', 'code': '999999', 'name': '새 상장', 'market': 'KOSDAQ', 'close': 10.0, 'change_pct': 1.0,
           'mcap': 0, 'trd_val': 1.0}]


class LiveInfoTest(unittest.TestCase):
    def test_mcap_scaled_by_price_and_unknown_dropped(self):
        info = CL.live_info(BASE, QUOTES)
        self.assertEqual(set(info), {'005930', '000660', '278470'})
        self.assertEqual(info['005930']['mc'], 11000)
        self.assertEqual(info['000660']['mc'], 7600)
        self.assertEqual(info['278470']['mk'], 'KOSDAQ')
        self.assertEqual(info['278470']['w'], '화장품')

    def test_periods_follow_price(self):
        info = CL.live_info(BASE, QUOTES)
        old = {'big': [{'c': '005930', 'p': 100.0, 'w1': 10.0, 'm1': None, 'm3': -50.0}]}
        per = CL.periods_now(old, info)['005930']
        self.assertEqual(per['w1'], 21.0)          # 1.1 × 1.1 − 1
        self.assertIsNone(per['m1'])
        self.assertEqual(per['m3'], -45.0)         # 0.5 × 1.1 − 1

    def test_spike_uses_20d_average(self):
        info = CL.live_info(BASE, QUOTES)
        sp = CL.spike({c: {**i, 'mc': 1000} for c, i in info.items()})
        self.assertEqual([r['c'] for r in sp['list']], ['005930'])     # 400 ≥ 50×3, 하이닉스 5 < 30
        self.assertEqual(sp['list'][0]['x'], 8.0)

    def test_patch_rows_keeps_null_change(self):
        info = CL.live_info(BASE, QUOTES)
        rest = {'tgt': {'up': [{'c': '005930', 'p': 1.0, 'mc': 1, 'ch': None}]}, 'flow': {'buy': [{'c': '000660', 'p': 1.0, 'mc': 1, 'ch': 3.0}]}}
        CL.patch_rows(rest, info)
        self.assertEqual(rest['tgt']['up'][0], {'c': '005930', 'p': 110.0, 'mc': 11000, 'ch': None})
        self.assertEqual(rest['flow']['buy'][0]['ch'], -5.0)


class SiteTest(unittest.TestCase):
    def folder(self, home):
        d = Path(tempfile.mkdtemp()) / 'data'
        d.mkdir()
        (d / 'home.json').write_text(json.dumps(home))
        (d / 'quotes.json').write_text('{}')
        (d / 'live_base.json').write_text(json.dumps(BASE))
        return d.parent

    def test_skips_outside_hours_and_when_mac_fresh(self):
        f = self.folder({'built': '2026-11-18T10:50:00'})
        self.assertEqual(CL.site(f, now=datetime(2026, 11, 18, 8, 30)), CL.SKIP)
        self.assertEqual(CL.site(f, now=datetime(2026, 11, 21, 10, 0)), CL.SKIP)       # 토요일
        self.assertEqual(CL.site(f, now=datetime(2026, 11, 18, 11, 0)), CL.SKIP)       # 맥이 10분 전에 배포

    def test_mac_fresh(self):
        now = datetime(2026, 11, 18, 11, 0)
        self.assertTrue(CL.mac_fresh({'built': '2026-11-18T10:50:00'}, now))
        self.assertFalse(CL.mac_fresh({'built': '2026-11-18T10:40:00'}, now))
        self.assertFalse(CL.mac_fresh({'built': '2026-11-18T10:58:00', 'by': 'cloud'}, now))


if __name__ == '__main__':
    unittest.main()
