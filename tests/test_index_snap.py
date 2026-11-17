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


if __name__ == '__main__':
    unittest.main()
