import json
import tempfile
import unittest
from pathlib import Path

import bio_market as bm


def co(tk, tracking, st, sc):
    return {'ticker': tk, 'name': tk, 'market_code': 'US', 'kind': 'pipeline',
            'markets': [{'id': 'a', 'indication': 'X', 'tracking': tracking,
                         'triggers': [{'id': 't1', 'name': 'T', 'status': st, 'scenario': sc, 'date': '2026-11-10',
                                       'hits': [{'date': '2026-11-10', 'text': 'approved', 'url': 'u'}] if st == 'hit' else []}]}]}


class Digest(unittest.TestCase):
    def test_inbox_and_weekly_changes(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / 'hist.json'
            first = bm.digest([co('AAA', 'base', 'wait', None)], h, today='2026-11-01')
            self.assertEqual(first['inbox'], [])
            self.assertIsNone(first['since'])
            nxt = bm.digest([co('AAA', 'bull', 'hit', None)], h, today='2026-11-09')
            self.assertEqual(len(nxt['inbox']), 1)
            self.assertEqual(nxt['since'], '2026-11-01')
            whats = {c['what'] for c in nxt['changes']}
            self.assertIn('추적 시나리오', whats)
            self.assertIn('트리거 t1', whats)
            # 오래된 기록은 지운다
            bm.digest([co('AAA', 'bull', 'hit', None)], h, today='2026-12-15')
            self.assertNotIn('2026-11-01', json.loads(h.read_text()))


if __name__ == '__main__':
    unittest.main()
