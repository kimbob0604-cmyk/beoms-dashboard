import unittest
from datetime import date, datetime

import collect_prices as P


class ExpectedSessionTest(unittest.TestCase):
    def test_after_close_is_today(self):
        self.assertEqual(P.expected_session(datetime(2026, 11, 3, 18, 40)), date(2026, 11, 3))

    def test_early_morning_is_previous_weekday(self):
        self.assertEqual(P.expected_session(datetime(2026, 11, 4, 7, 10)), date(2026, 11, 3))
        self.assertEqual(P.expected_session(datetime(2026, 11, 9, 7, 10)), date(2026, 11, 6))  # 월요일 → 금요일

    def test_market_hours_is_none(self):
        self.assertIsNone(P.expected_session(datetime(2026, 11, 3, 12, 10)))

    def test_weekend_evening_is_friday(self):
        self.assertEqual(P.expected_session(datetime(2026, 11, 7, 18, 40)), date(2026, 11, 6))


def _row(code, close=1000.0, d='2026-11-19'):
    return {'date': d, 'code': code, 'name': f'가상{code}', 'market': 'KOSPI', 'close': close,
            'change_pct': 0.0, 'mcap': 100.0, 'trd_val': 1.0}


class NaverListTest(unittest.TestCase):
    """네이버 목록은 시총순이라 쪽을 넘기는 사이 순위가 바뀌면 같은 종목이 두 번 온다"""

    def _conn(self):
        import sqlite3
        from pathlib import Path
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript((Path(P.__file__).parent / 'db' / 'schema.sql').read_text(encoding='utf-8'))
        return conn

    def _run(self, passes):
        """passes: 받을 때마다 돌려줄 목록들 (한 번 = 시장 하나 한 쪽으로 친다)"""
        from unittest import mock
        it = iter(passes)
        conn = self._conn()
        with mock.patch.object(P, 'naver_list', lambda session: next(it)), mock.patch.object(P, 'NAVER_MIN_ROWS', 2):
            n = P.collect_naver(conn, None, date(2026, 11, 19))
        return n, conn, it

    def test_unique_by_code_keeps_last(self):
        rows, dup = P.unique_by_code([_row('000001', 10), _row('000002'), _row('000001', 11)])
        self.assertEqual(dup, 1)
        self.assertEqual({r['code']: r['close'] for r in rows}, {'000001': 11, '000002': 1000.0})
        self.assertEqual(P.unique_by_code([_row('000001'), _row('000002')])[1], 0)

    def test_duplicate_does_not_crash_and_refetch_fills_skipped(self):
        # 첫 번째: 000001 이 두 번 오고 000003 이 밀려 빠짐 → 두 번째를 받아 합친다
        first = [_row('000001', 10), _row('000002'), _row('000001', 11)]
        second = [_row('000001', 12), _row('000002'), _row('000003')]
        n, conn, it = self._run([first, second, []])
        self.assertEqual(n, 3)
        got = {r['code']: r['close'] for r in conn.execute('SELECT code, close FROM price_daily')}
        self.assertEqual(got, {'000001': 12, '000002': 1000.0, '000003': 1000.0})
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM ohlc_daily').fetchone()[0], 3)
        self.assertEqual(next(it), [])          # 겹침 없는 두 번째에서 멈췄다 (세 번째는 받지 않음)

    def test_clean_list_is_fetched_once(self):
        n, conn, it = self._run([[_row('000001'), _row('000002')], []])
        self.assertEqual(n, 2)
        self.assertEqual(next(it), [])

    def test_always_duplicated_stops_after_tries(self):
        dup = [_row('000001'), _row('000002'), _row('000001')]
        n, conn, it = self._run([dup] * P.NAVER_TRIES + [[]])
        self.assertEqual(n, 2)
        self.assertEqual(next(it), [])          # NAVER_TRIES 번만 받는다


if __name__ == '__main__':
    unittest.main()


class LiveTest(unittest.TestCase):
    def test_in_session(self):
        import live
        self.assertTrue(live.in_session(datetime(2026, 11, 5, 9, 0)))
        self.assertTrue(live.in_session(datetime(2026, 11, 5, 15, 50)))
        self.assertFalse(live.in_session(datetime(2026, 11, 5, 8, 59)))
        self.assertFalse(live.in_session(datetime(2026, 11, 5, 16, 0)))
        self.assertFalse(live.in_session(datetime(2026, 11, 7, 10, 0)))   # 토요일
