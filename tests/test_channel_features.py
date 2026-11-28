"""교보·다올 채널 기능: 실적 공시 속보 (의료관광 알림·주간 모멘텀·섹터 뉴스는 Beom's Consumer 의 tests/test_channel_features.py)"""
import sqlite3
import unittest
from unittest import mock

import earn_alert as EA

POST = {'id': 10, 'ts': '2026-11-12 10:18:10', 'code': '483650', 'name': '달바글로벌', 'mcap': 17929.0,
        'report': '연결재무제표기준영업(잠정)실적(공정공시)', 'prelim': 'Y', 'period': '2026Q3', 'rcp': '20261112800251',
        's': 1556.0, 'se': 1716.0, 'o': 334.0, 'oe': 327.0, 'n': 148.0, 'ne': 259.0}


def earn_db(rows):
    c = sqlite3.connect(':memory:')
    c.execute("""CREATE TABLE earn_post (id INTEGER PRIMARY KEY, ts TEXT, code TEXT, name TEXT, mcap REAL, report TEXT, prelim TEXT,
                 period TEXT, rcp TEXT, s REAL, se REAL, o REAL, oe REAL, n REAL, ne REAL)""")
    c.executemany('INSERT INTO earn_post VALUES (:id,:ts,:code,:name,:mcap,:report,:prelim,:period,:rcp,:s,:se,:o,:oe,:n,:ne)', rows)
    return c


class EarnAlertTest(unittest.TestCase):
    def test_message_like_channel(self):
        m = EA.message(POST)
        self.assertIn('<b>달바글로벌</b> 26Q3 잠정 — <b>부합</b>', m)
        self.assertIn('매출액 1,556억 (예상 1,716억 / -9%) 🔻', m)
        self.assertIn('영업이익 334억 (예상 327억 / +2%)', m)
        self.assertIn('시총 1조 7,929억', m)
        self.assertIn('rcpNo=20261112800251', m)

    def test_eok(self):
        self.assertEqual(EA.eok(17929), '1조 7,929억')
        self.assertEqual(EA.eok(-42), '-42억')
        self.assertEqual(EA.eok(None), '-')

    def test_first_run_marks_baseline_then_sends_new_watched_once(self):
        c = earn_db([POST])
        codes = {'483650': '달바글로벌'}
        self.assertEqual(EA.pending(c, codes), [])                       # 처음: 기준만 잡는다
        c.executemany('INSERT INTO earn_post VALUES (:id,:ts,:code,:name,:mcap,:report,:prelim,:period,:rcp,:s,:se,:o,:oe,:n,:ne)', [
            {**POST, 'id': 11, 'code': '214450', 'name': '파마리서치'},                    # 관심 종목, 새 분기
            {**POST, 'id': 12, 'report': '분기보고서 (2026.09)'},                          # 같은 회사·같은 분기 → 뺀다
            {**POST, 'id': 13, 'code': '005930', 'name': '삼성전자'}])                     # 관심 밖
        got = EA.pending(c, {**codes, '214450': '파마리서치'})
        self.assertEqual([p['id'] for p in got], [11])

    def test_notify_marks_only_after_send(self):
        c = earn_db([POST])
        EA.pending(c, {'483650': 'x'})
        c.execute('INSERT INTO earn_post (id, ts, code, name, period, s) VALUES (20, "2026-11-17 09:00:00", "214450", "파마리서치", "2026Q3", 1)')
        with mock.patch.object(EA, 'watch_codes', return_value={'214450': '파마리서치'}), \
                mock.patch.object(EA, 'tg_target', return_value=('t', 'c', True)), \
                mock.patch.object(EA, 'send', side_effect=RuntimeError('x')):
            self.assertEqual(EA.notify(c, log=lambda *_: None), 1)
        self.assertEqual(c.execute("SELECT v FROM alert_meta WHERE k='last_id'").fetchone()[0], '10')
        with mock.patch.object(EA, 'watch_codes', return_value={'214450': '파마리서치'}), \
                mock.patch.object(EA, 'tg_target', return_value=('t', 'c', True)), mock.patch.object(EA, 'send') as send:
            self.assertEqual(EA.notify(c, log=lambda *_: None), 0)
        send.assert_called_once()
        self.assertEqual(c.execute("SELECT v FROM alert_meta WHERE k='last_id'").fetchone()[0], '20')


if __name__ == '__main__':
    unittest.main()
