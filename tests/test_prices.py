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

    def test_regular_close_from_flow_replaces_integrated_price(self):
        # 2026-11-26 디앤디파마텍: 네이버 목록 37,200 (+9.9%, 시간외 포함) / 정규장 36,450 / 기준가 33,850
        conn = self._conn()
        conn.execute("INSERT INTO flow_daily (date, code, close) VALUES ('2026-11-19', '347850', 36450)")
        rows = [{**_row('347850', 37200.0), 'change_pct': 9.9, 'base': 33850.0, 'shares': 45996189},
                {**_row('000002', 500.0), 'base': 490.0, 'shares': 1000}]
        self.assertEqual(P.regular_close(conn, rows, date(2026, 11, 19)), 1)
        self.assertEqual(rows[0]['close'], 36450)
        self.assertEqual(rows[0]['change_pct'], 7.68)            # KRX FLUC_RT 와 같다
        self.assertAlmostEqual(rows[0]['mcap'], 16765.611, places=2)
        self.assertEqual(rows[1]['close'], 500.0)                # 수급에 없는 종목은 그대로


class KrxHealTest(unittest.TestCase):
    """가장 최근 날만 받으면, 그날이 '가장 최근'인 동안 실행이 다 실패했을 때 임시 종가가 남는다 (2026-11-20·11-26)"""

    def _conn(self):
        return NaverListTest._conn(self)

    def test_one_market_empty_writes_nothing(self):
        from unittest import mock
        conn = self._conn()
        conn.execute("INSERT INTO price_daily (date, code, close) VALUES ('2026-11-26', '347850', 37200)")
        krx_row = {**_row('005930', 1000.0, '2026-11-26'), 'shares': 1, 'open': 1, 'high': 1, 'low': 1, 'volume': 1}
        with mock.patch.object(P.krx, 'fetch_daily', lambda s, k, d, m: [krx_row] if m == 'KOSPI' else []), \
             mock.patch.object(P.time, 'sleep', lambda s: None):
            self.assertEqual(P.collect_date(conn, None, date(2026, 11, 26)), 0)
        self.assertEqual(tuple(conn.execute('SELECT code, close FROM price_daily').fetchone()), ('347850', 37200))
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM price_daily').fetchone()[0], 1)

    def test_heal_refetches_unconfirmed_weekdays_only(self):
        from unittest import mock
        conn = self._conn()
        # 11-25 확정(시가 있음), 11-26 네이버 임시(시가 없음), 11-24 는 아예 없음, 11-27 이 가장 최근 KRX 날
        conn.executemany('INSERT INTO ohlc_daily (date, code, open, close) VALUES (?, ?, ?, ?)', [
            ('2026-11-25', '000001', 10, 10), ('2026-11-26', '000001', None, 11), ('2026-11-27', '000001', 12, 12)])
        for d in ('2026-11-23', '2026-11-20', '2026-11-19', '2026-11-18', '2026-11-17', '2026-11-16', '2026-11-13'):
            conn.execute('INSERT INTO ohlc_daily (date, code, open, close) VALUES (?, ?, ?, ?)', (d, '000001', 1, 1))
        called = []
        with mock.patch.object(P, 'collect_date', lambda c, s, d: called.append(d.isoformat()) or 5):
            fixed = P.heal(conn, None, date(2026, 11, 27))
        self.assertEqual(called, ['2026-11-26', '2026-11-24'])  # 주말·확정된 날은 부르지 않는다
        self.assertEqual([d.isoformat() for d in fixed], called)


class Base52Test(unittest.TestCase):
    def test_base_price_from_signed_diff(self):
        from collectors import naver
        s = lambda code, close, diff: {'stockEndType': 'stock', 'itemCode': code, 'localTradedAt': '2026-11-27T20:20:00+09:00',
                                       'closePriceRaw': str(close), 'compareToPreviousClosePriceRaw': str(diff),
                                       'fluctuationsRatio': '0', 'marketValueRaw': '0', 'accumulatedTradingValueRaw': '0'}
        rows = naver.parse_high52({'stocks': [s('A', 42650, 6200), s('B', 84000, -700)], 'totalCount': 2}, 'KOSPI')['rows']
        self.assertEqual([r['base'] for r in rows], [36450, 84700])


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
