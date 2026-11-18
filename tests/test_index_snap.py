import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import index_snap as I


def reply(biz, frgn='-12,485', org='+4,795', ind='+3,369', prog='-6,968'):
    return {'dealTrendInfo': {'bizdate': biz, 'personalValue': ind, 'foreignValue': frgn, 'institutionalValue': org},
            'programTrendInfo': prog and {'bizdate': biz, 'indexTotalReal': prog}}


class ParseTest(unittest.TestCase):
    def test_values_in_eok(self):
        self.assertEqual(I.parse(reply('20261117')), ('2026-11-17', [-12485.0, 4795.0, 3369.0, -6968.0]))
        self.assertEqual(I.parse(reply('20261117', prog=None))[1][3], None)      # 선물은 프로그램이 없다
        self.assertEqual(I.parse({'dealTrendInfo': None}), (None, None))
        self.assertEqual(I.parse(reply('20261117', frgn='')), (None, None))      # 개장 직후 값이 비어 있을 때


class TakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, day='2026-11-17'):
        return json.loads((self.dir / f'{day}.json').read_text())

    def test_appends_by_time_and_skips_outside_session(self):
        fetch = lambda url: reply('20261117')
        self.assertEqual(I.take(self.dir, datetime(2026, 11, 17, 8, 55), fetch), 0)        # 개장 전
        self.assertEqual(I.take(self.dir, datetime(2026, 11, 14, 10, 0), fetch), 0)        # 토요일
        self.assertFalse(list(self.dir.glob('*.json')))
        self.assertEqual(I.take(self.dir, datetime(2026, 11, 17, 9, 5), fetch), 3)
        self.assertEqual(I.take(self.dir, datetime(2026, 11, 17, 9, 10), lambda url: reply('20261117', frgn='-500')), 3)
        d = self.read()
        self.assertEqual([r[0] for r in d['KOSPI']], ['09:05', '09:10'])
        self.assertEqual(d['KOSPI'][1], ['09:10', -500.0, 4795.0, 3369.0, -6968.0])
        self.assertEqual(set(d) - {'date'}, {'KOSPI', 'KOSDAQ', 'FUT'})

    def test_holiday_and_fetch_failure_write_nothing(self):
        self.assertEqual(I.take(self.dir, datetime(2026, 11, 17, 10, 0), lambda url: reply('20261116')), 0)      # 어제 값 = 휴장일
        def boom(url):
            raise OSError('연결 실패')
        self.assertEqual(I.take(self.dir, datetime(2026, 11, 17, 10, 0), boom), 0)
        self.assertFalse(list(self.dir.glob('*.json')))

    def test_after_close_goes_to_closing_slot_once(self):
        fetch = lambda url: reply('20261117')
        I.take(self.dir, datetime(2026, 11, 17, 15, 35), fetch)
        d = self.read()
        self.assertEqual((d['KOSPI'][-1][0], d['FUT'][-1][0]), ('15:30', '15:35'))       # 선물은 15:45 마감
        self.assertEqual(I.take(self.dir, datetime(2026, 11, 17, 15, 40), fetch), 1)       # 주식 지수는 같은 값 → 선물만 새 칸
        I.take(self.dir, datetime(2026, 11, 17, 15, 55), lambda url: reply('20261117', frgn='-13,000'))
        self.assertEqual(self.read()['KOSPI'], [['15:30', -13000.0, 4795.0, 3369.0, -6968.0]])      # 확정값으로 덮어쓴다

    def test_old_files_removed(self):
        (self.dir / '2026-10-01.json').write_text('{}')
        (self.dir / '2026-11-10.json').write_text('{}')
        I.take(self.dir, datetime(2026, 11, 17, 9, 5), lambda url: reply('20261117'))
        self.assertEqual(sorted(f.name for f in self.dir.glob('*.json')), ['2026-11-10.json', '2026-11-17.json'])


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.executescript("""
            CREATE TABLE index_minute (date TEXT, code TEXT, t TEXT, price REAL, PRIMARY KEY (date, code, t));
            CREATE TABLE index_snap (date TEXT, code TEXT, t TEXT, close REAL, frgn REAL, org REAL, ind REAL, prog REAL,
                                     PRIMARY KEY (date, code, t));""")
        self.conn.executemany("INSERT INTO index_minute VALUES ('2026-11-17', 'KOSPI', ?, ?)",
                              [('09:01', 5030.0), ('09:05', 5040.0), ('09:20', 5055.0)])
        self.conn.execute("INSERT INTO index_snap VALUES ('2026-11-17', 'KOSPI', '10:23', 5044.0, -3662, 2286, 362, -2071)")

    def snaps(self, code='KOSPI'):
        return self.conn.execute('SELECT t, close, frgn FROM index_snap WHERE code = ? ORDER BY t', (code,)).fetchall()

    def test_fills_only_missing_times(self):
        data = {'date': '2026-11-17',
                'KOSPI': [['09:06', -100.0, 50.0, 40.0, -30.0], ['09:25', -900.0, 1.0, 2.0, 3.0], ['10:23', -9999.0, 0, 0, 0],
                          ['14:00', -5.0, 0, 0, 0]],
                'FUT': [['09:06', 10.0, -5.0, -5.0, None]]}
        self.assertEqual(I.merge(self.conn, data, '2026-11-17', upto='13:00'), 3)
        # 종가는 그 시각까지의 마지막 분봉. 맥이 직접 받은 10:23 은 그대로. 아직 오지 않은 14:00 은 넣지 않는다
        self.assertEqual(self.snaps(), [('09:06', 5040.0, -100.0), ('09:25', 5055.0, -900.0), ('10:23', 5044.0, -3662.0)])
        self.assertEqual(self.snaps('FUT'), [('09:06', None, 10.0)])
        self.assertEqual(I.merge(self.conn, data, '2026-11-17', upto='13:00'), 0)      # 다시 돌려도 늘지 않는다

    def test_other_day_ignored(self):
        self.assertEqual(I.merge(self.conn, {'date': '2026-11-16', 'KOSPI': [['09:06', 1, 1, 1, 1]]}, '2026-11-17'), 0)


DAUM_KOSPI = {'data': [
    {'date': '2026-11-18 15:35:00', 'foreignStraightPurchasePrice': -2e11, 'institutionStraightPurchasePrice': 3e11, 'individualStraightPurchasePrice': -1e11},
    {'date': '2026-11-18 15:31:00', 'foreignStraightPurchasePrice': -1e11, 'institutionStraightPurchasePrice': 3e11, 'individualStraightPurchasePrice': -2e11},
    {'date': '2026-11-18 09:03:00', 'foreignStraightPurchasePrice': 65_312_000_000, 'institutionStraightPurchasePrice': -5.68e10, 'individualStraightPurchasePrice': -1.07e10},
    {'date': '2026-11-17 15:30:00', 'foreignStraightPurchasePrice': 1, 'institutionStraightPurchasePrice': 1, 'individualStraightPurchasePrice': 1}]}
DAUM_FUT = {'data': [
    {'date': '2026-11-18 08:45:00', 'foreignSettlement': 10, 'institutionalSettlement': -5, 'privateSettlement': -5},
    {'date': '2026-11-18 09:10:00', 'foreignSettlement': 1000, 'institutionalSettlement': -400, 'privateSettlement': -600}]}


class DaumTest(unittest.TestCase):
    def test_rows_in_eok_today_only_and_close_slot(self):
        rows = I.daum_rows('KOSPI', DAUM_KOSPI, '2026-11-18')
        self.assertEqual(rows, [['09:03', 653, -568, -107, None], ['15:30', -2000, 3000, -1000, None]])   # 마감 뒤는 마지막 값 하나

    def test_futures_contracts_to_eok(self):
        rows = I.daum_rows('FUT', DAUM_FUT, '2026-11-18', I.price_at([['09:00', 780.0], ['09:30', 790.0]]))
        self.assertEqual(rows, [['09:10', 1950, -780, -1170, None]])        # 1000계약 × 780 × 25만 ÷ 1억, 09:00 전은 뺀다
        self.assertEqual(I.daum_rows('FUT', DAUM_FUT, '2026-11-18'), [])    # 가격이 없으면 못 바꾼다

    def test_combine(self):
        naver = [['09:05', 1.0, 2.0, 3.0, 4.0], ['10:00', 5.0, 6.0, 7.0, 8.0]]
        daum = [['09:03', 9, 9, 9, None], ['09:05', 0, 0, 0, None], ['09:30', 1, 1, 1, None]]
        self.assertEqual(I.combine('KOSPI', naver, daum),
                         [['09:03', 9, 9, 9, None], ['09:05', 1.0, 2.0, 3.0, 4.0], ['09:30', 1, 1, 1, None], ['10:00', 5.0, 6.0, 7.0, 8.0]])
        self.assertEqual(I.combine('FUT', naver, daum), daum + [['10:00', 5.0, 6.0, 7.0, 8.0]])   # 선물: 다음 구간은 다음만
        self.assertEqual(I.combine('KOSPI', naver, []), naver)

    def test_merge_daum_fills_and_replaces_futures(self):
        c = sqlite3.connect(':memory:')
        c.executescript("""
            CREATE TABLE index_minute (date TEXT, code TEXT, t TEXT, price REAL, PRIMARY KEY (date, code, t));
            CREATE TABLE index_snap (date TEXT, code TEXT, t TEXT, close REAL, frgn REAL, org REAL, ind REAL, prog REAL,
                                     PRIMARY KEY (date, code, t));""")
        c.execute("INSERT INTO index_minute VALUES ('2026-11-18', 'KOSPI', '09:00', 5000.0)")
        c.execute("INSERT INTO index_snap VALUES ('2026-11-18', 'KOSPI', '10:00', 5010, 5, 6, 7, 8)")
        c.execute("INSERT INTO index_snap VALUES ('2026-11-18', 'FUT', '09:20', 780, 99, 99, 99, NULL)")   # 늦게 들어온 네이버 선물
        daum = {'KOSPI': [['09:03', 9, 9, 9, None], ['10:00', 0, 0, 0, None], ['13:00', 1, 1, 1, None]],
                'FUT': [['09:10', 1, 2, 3, None], ['09:30', 4, 5, 6, None]]}
        self.assertEqual(I.merge_daum(c, daum, '2026-11-18', upto='12:00'), 4)
        rows = c.execute('SELECT code, t, close, frgn, prog FROM index_snap ORDER BY code, t').fetchall()
        self.assertEqual(rows, [('FUT', '09:10', None, 1.0, None), ('FUT', '09:30', None, 4.0, None),
                                ('KOSPI', '09:03', 5000.0, 9.0, None), ('KOSPI', '10:00', 5010.0, 5.0, 8.0)])
        self.assertEqual(I.merge_daum(c, daum, '2026-11-18', upto='12:00'), 0)          # 두 번째는 바뀐 것 없음

    def test_take_keeps_daum_series(self):
        with tempfile.TemporaryDirectory() as d:
            got = {'KOSPI': [['09:03', 1, 2, 3, None]]}
            I.take(Path(d), datetime(2026, 11, 18, 9, 5), lambda url: reply('20261118'), daum=lambda: got)
            self.assertEqual(json.loads((Path(d) / '2026-11-18.json').read_text())['daum'], got)
            self.assertEqual(I.take(Path(d), datetime(2026, 11, 18, 9, 5), lambda url: reply('20261118'), daum=lambda: got), 0)


if __name__ == '__main__':
    unittest.main()
