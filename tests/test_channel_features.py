"""교보·다올 채널 기능: 실적 공시 속보, 월간 의료관광 알림, 주간 모멘텀, 섹터 뉴스, 네이버 트렌드"""
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

import collect_medical as CM
import collect_news as CN
import collect_trade as T
import earn_alert as EA
import medical_alert as MA
import momentum as MO

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


class MedicalAlertTest(unittest.TestCase):
    def db(self):
        c = T.connect(Path(':memory:'))
        c.executescript(CM.SCHEMA)
        rows = []
        for ym, f in (('2025-10', 1.0), ('2026-09', 1.5), ('2026-10', 2.0)):
            rows += [(ym, '000', '글로벌', '피부과', 100e8 * f, 1), (ym, '000', '글로벌', '약국', 50e8 * f, 1),
                     (ym, '840', '미국', '피부과', 30e8 * f, 1), (ym, '392', '일본', '피부과', 20e8 * f, 1)]
        c.executemany('INSERT INTO med VALUES (?,?,?,?,?,?)', rows)
        return c

    def test_message(self):
        m = MA.message(MA.build(self.db()))
        self.assertIn('2026.10월 외국인 의료관광 소비', m)
        self.assertIn('전체 300억</b> (YoY +100%, MoM +33%)', m)
        self.assertIn('피부과 200억 (YoY +100%, MoM +33%) · 비중 67%', m)
        self.assertLess(m.index('미국'), m.index('일본'))

    def test_baseline_then_new_month(self):
        c = self.db()
        with mock.patch.object(MA, 'tg_target', return_value=('t', 'c', True)), mock.patch.object(MA, 'send') as send:
            MA.notify(c, log=lambda *_: None)
            send.assert_not_called()                                        # 처음은 기준만
            c.execute("INSERT INTO med VALUES ('2026-11', '000', '글로벌', '피부과', 1e10, 1)")
            self.assertEqual(MA.notify(c, log=lambda *_: None), 0)
            MA.notify(c, log=lambda *_: None)
        send.assert_called_once()


class MomentumTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(MO.classify(0.05, 0.1), 'up')
        self.assertEqual(MO.classify(0.05, -0.1), 'lead')
        self.assertEqual(MO.classify(-0.05, 0.1), 'hold')
        self.assertEqual(MO.classify(-0.05, -0.1), 'down')
        self.assertEqual(MO.classify(0.01, -0.3), 'flat')
        self.assertIsNone(MO.classify(None, 0.1))

    def test_rsi(self):
        self.assertIsNone(MO.rsi([1] * 10))
        self.assertEqual(MO.rsi(list(range(1, 40))), 100.0)                # 오르기만
        self.assertLess(MO.rsi(list(range(40, 1, -1))), 1)

    def test_est_change_prefers_next_year(self):
        g = {'fy0': 2026, 'k': {'y0': {'op': {'w1': 0.01, 'm1': 0.02}}, 'y1': {'op': {'w1': 0.03, 'm1': 0.04}}}}
        self.assertEqual(MO.est_change(g), (2027, 0.03, 0.04))
        self.assertEqual(MO.est_change({'fy0': 2026, 'k': {'y0': {'op': {'w1': 0.01, 'm1': 0.02}}}}), (2026, 0.01, 0.02))
        self.assertEqual(MO.est_change(None), (None, None, None))


class NewsTest(unittest.TestCase):
    def test_name_hit_short_names(self):
        self.assertTrue(CN.name_hit('디오, 3분기 실적 개선', '디오'))
        self.assertFalse(CN.name_hit('라디오 광고 시장', '디오'))
        self.assertTrue(CN.name_hit('[단독] 휴젤, 미국 진출', '휴젤'))
        self.assertTrue(CN.name_hit('아모레퍼시픽 배당 상향', '아모레퍼시픽'))

    def test_kw_hit(self):
        self.assertTrue(CN.kw_hit('K-뷰티 열풍에 공장 풀가동', 'K뷰티'))
        self.assertTrue(CN.kw_hit('10월 라면 수출 역대 최대', '라면 수출'))
        self.assertFalse(CN.kw_hit('라면 신제품 출시', '라면 수출'))

    def test_clean(self):
        self.assertEqual(CN.clean('<b>파마리서치</b> &quot;리쥬란&quot;'), '파마리서치 "리쥬란"')


if __name__ == '__main__':
    unittest.main()
