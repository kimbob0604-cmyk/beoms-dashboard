import unittest

import db
from build_growth import pick_snapshot


def add_snapshot(conn, as_of, cns_date, n_est):
    """추정치 보유 종목 n_est개짜리 스냅샷"""
    with conn:
        conn.execute(
            """INSERT INTO consensus_trend (as_of, code, fy, fy_month, metric, cns_date, now)
               VALUES (?, '000000', 2027, 12, 'op', ?, 1)""", (as_of, cns_date))
        conn.executemany(
            """INSERT INTO consensus_annual (as_of, code, fy, fy_month, is_estimate, op)
               VALUES (?, ?, 2027, 12, 1, 1)""",
            [(as_of, f'{i:06d}') for i in range(n_est)])


class PickSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(':memory:')

    def test_latest_without_lookahead(self):
        add_snapshot(self.conn, '2026-11-03', '2026-11-02', 100)
        add_snapshot(self.conn, '2026-11-04', '2026-11-03', 100)
        self.assertEqual(pick_snapshot(self.conn, '2026-11-02'), ('2026-11-03', '2026-11-02'))
        self.assertEqual(pick_snapshot(self.conn, '2026-11-03'), ('2026-11-04', '2026-11-03'))
        self.assertEqual(pick_snapshot(self.conn, '2026-10-30'), (None, None))

    def test_skips_partial_snapshot(self):
        # 11/4 수집이 서버 차단으로 중간에 끊김 → 11/3 스냅샷을 쓴다
        add_snapshot(self.conn, '2026-11-03', '2026-11-02', 100)
        add_snapshot(self.conn, '2026-11-04', '2026-11-03', 30)
        self.assertEqual(pick_snapshot(self.conn, '2026-11-03'), ('2026-11-03', '2026-11-02'))


if __name__ == '__main__':
    unittest.main()
