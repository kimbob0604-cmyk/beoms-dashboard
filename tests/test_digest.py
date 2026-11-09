import unittest

import build_digest as G
import db


class DigestTest(unittest.TestCase):
    def test_summary_two_sentences(self):
        s = G.summary_of('첫 문장이다. 둘째 문장이다. 셋째 문장은 길어서 빠진다' + '가' * 300)
        self.assertTrue(s.startswith('첫 문장이다.'))
        self.assertNotIn('셋째', s)

    def test_history_prev_goal_and_opinion(self):
        conn = db.connect(':memory:')
        rows = [(1, 'A', 'X', '2026-01-02', 'Buy', 100), (2, 'A', 'Y', '2026-01-03', 'Buy', 150),
                (3, 'A', 'X', '2026-02-01', 'Hold', 80), (4, 'A', 'X', '2026-06-01', 'Buy', None)]
        conn.executemany('INSERT INTO research (id, code, broker, date, opinion, goal) VALUES (?, ?, ?, ?, ?, ?)', rows)
        h = {r['id']: r for r in G.history(conn)}
        self.assertEqual((h[3]['pg'], h[3]['pop']), (100, '매수'))   # 같은 증권사 직전
        self.assertIsNone(h[2]['pg'])                                 # 다른 증권사는 비교 안 함
        self.assertEqual(h[4]['pg'], 80)
        self.assertTrue(h[4]['lone'])                                 # 90일 넘게 리포트 없던 종목
        self.assertFalse(h[3]['lone'])


if __name__ == '__main__':
    unittest.main()
