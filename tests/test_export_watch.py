import json
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import collect_eu as CE
import collect_trade as T
import eu_trade as EUT
import export_watch as W

ROOT = Path(__file__).resolve().parent.parent


def trade_db(rows):
    """rows: (ym, sido, sgg, hs6, usd)"""
    conn = T.connect(Path(':memory:'))
    conn.executemany('INSERT INTO sgg VALUES (?,?,?,?,?,0)', rows)
    return conn


CFG = {'link': 'https://example/consumer.html#watch', 'cats': [
    {'name': '톡신', 'hs6': ['300249'], 'items': [{'n': '휴젤', 'c': '145020', 'regions': ['51:춘천시'], 'label': '춘천시'}]},
    {'name': '화장품', 'hs6': ['330499'], 'items': [
        {'n': '실리콘투', 'c': '257720', 'regions': ['41:성남시', '28:중구'], 'label': '성남시+인천 중구'}]},
]}


class SeriesTest(unittest.TestCase):
    def test_ym_add(self):
        self.assertEqual(W.ym_add('2026-01', -1), '2025-12')
        self.assertEqual(W.ym_add('2026-10', 3), '2027-01')
        self.assertEqual(W.ym_add('2026-10', -12), '2025-10')

    def test_region_series_sums_regions_and_keeps_missing_months(self):
        conn = trade_db([
            ('2026-09', '41', '경기도 성남시', '330499', 10.0), ('2026-09', '28', '인천광역시 중구', '330499', 5.0),
            ('2026-09', '11', '서울특별시 중구', '330499', 99.0),            # 서울 중구는 다른 곳
            ('2026-10', '41', '경기도 성남시', '330499', 7.0),
        ])
        v = W.region_series(conn, ['330499'], ['41:성남시', '28:중구'], ['2026-08', '2026-09', '2026-10'])
        self.assertEqual(v, [None, 15.0, 7.0])                       # 8월은 통계가 없다(None), 0 과 다르다

    def test_quarters_qtd_compares_same_months(self):
        ms = [W.ym_add('2024-01', k) for k in range(34)]             # 2024-01 ~ 2026-10
        v = [100.0] * 21 + [200.0] * 12 + [300.0]                    # 2025-10 부터 200, 2026-10 은 300
        qs = W.quarters(ms, v)
        self.assertEqual(qs[0]['q'], '4Q26')
        self.assertTrue(qs[0]['qtd'])
        self.assertEqual(qs[0]['nm'], 1)
        self.assertAlmostEqual(qs[0]['yoy'], 300 / 200 - 1)          # 작년 10월 한 달과 비교
        self.assertIsNone(qs[0]['qoq'])                              # 진행 중인 분기는 전분기비를 내지 않는다
        self.assertEqual(qs[1]['q'], '3Q26')
        self.assertEqual(qs[1]['v'], 600)
        self.assertAlmostEqual(qs[1]['yoy'], 600 / 300 - 1)
        self.assertAlmostEqual(qs[1]['qoq'], 0.0)                    # 3Q26(600) vs 2Q26(600)
        self.assertEqual((qs[4]['q'], qs[4]['v'], qs[5]['v']), ('4Q25', 600, 300))
        self.assertAlmostEqual(qs[4]['qoq'], 600 / 300 - 1)          # 4Q25 vs 3Q25
        self.assertEqual(len(qs), W.N_QUARTERS + 1)

    def test_build_uses_complete_month_and_message(self):
        rows = []
        for k in range(26):
            ym = W.ym_add('2024-09', k)                              # 2024-09 ~ 2026-10
            rows.append((ym, '51', '강원특별자치도 춘천시', '300249', 1_000_000.0 * (2 if ym == '2026-10' else 1)))
            rows.append((ym, '41', '경기도 성남시', '330499', 3_000_000.0))
        rows.append(('2026-11', '51', '강원특별자치도 춘천시', '300249', 9e9))   # 반쪽 수집된 달
        conn = trade_db(rows)
        conn.execute("INSERT INTO meta VALUES ('complete_ym', '2026-10')")
        w = W.build(conn, CFG)
        self.assertEqual(w['last_ym'], '2026-10')
        it = w['cats'][0]['items'][0]
        self.assertEqual(it['usd'], 2_000_000.0)
        self.assertAlmostEqual(it['yoy'], 1.0)
        self.assertAlmostEqual(it['mom'], 1.0)
        self.assertEqual(len(it['m']), W.N_MONTHS)
        text = W.message(w)
        self.assertIn('2026.10월 수출 확정치', text)
        self.assertIn('휴젤 춘천시 2.0백만달러 (YoY +100.0%, MoM +100.0%)', text)
        self.assertIn('실리콘투 성남시+인천 중구 3.0백만달러 (YoY +0.0%, MoM +0.0%)', text)
        self.assertTrue(text.endswith('https://example/consumer.html#watch'))


class NotifyTest(unittest.TestCase):
    def setUp(self):
        rows = [(W.ym_add('2025-09', k), '51', '강원특별자치도 춘천시', '300249', 1e6) for k in range(14)]
        self.conn = trade_db(rows)
        self.conn.execute("INSERT INTO meta VALUES ('complete_ym', '2026-10')")
        p = mock.patch.object(W, 'load_cfg', return_value=CFG)
        p.start()
        self.addCleanup(p.stop)

    def env(self, **kw):
        base = {'TELEGRAM_BOT_TOKEN': 't', 'TELEGRAM_CHAT_ID': 'c', 'EXPORT_TG_ENABLED': '1'}
        return mock.patch.dict('os.environ', {**base, **kw}, clear=False)

    def test_sends_once_per_month(self):
        with self.env(), mock.patch.object(W, 'send') as send:
            self.assertEqual(W.notify(self.conn, log=lambda *_: None), 0)
            self.assertEqual(W.notify(self.conn, log=lambda *_: None), 0)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(W.get_meta(self.conn, 'watch_notified'), '2026-10')

    def test_disabled_does_not_send_or_mark(self):
        with self.env(EXPORT_TG_ENABLED='0'), mock.patch.object(W, 'send') as send:
            self.assertEqual(W.notify(self.conn, log=lambda *_: None), 4)
        send.assert_not_called()
        self.assertIsNone(W.get_meta(self.conn, 'watch_notified'))

    def test_failure_keeps_month_unsent(self):
        with self.env(), mock.patch.object(W, 'send', side_effect=RuntimeError('x')):
            self.assertEqual(W.notify(self.conn, log=lambda *_: None), 1)
        self.assertIsNone(W.get_meta(self.conn, 'watch_notified'))

    def test_own_chat_overrides(self):
        with self.env(EXPORT_TG_CHAT_ID='mine'), mock.patch.object(W, 'send') as send:
            W.notify(self.conn, log=lambda *_: None)
        self.assertEqual(send.call_args[0][2], 'mine')


class DueTest(unittest.TestCase):
    def test_probe_only_in_release_week_until_month_arrives(self):
        conn = T.connect(Path(':memory:'))
        conn.execute("INSERT INTO meta VALUES ('refreshed_at', '2026-11-16T07:10:00')")
        yes, no = (lambda ym: True), (lambda ym: False)
        self.assertFalse(T.due(conn, date(2026, 11, 16), probe=no))     # 오늘 받았고 아직 안 올라옴
        self.assertTrue(T.due(conn, date(2026, 11, 16), probe=yes))     # 오늘 받았지만 그 뒤에 올라옴
        conn.execute("INSERT INTO sgg VALUES ('2026-10', '11', '서울특별시 강남구', '330499', 1, 1)")
        self.assertFalse(T.due(conn, date(2026, 11, 16), probe=yes))    # 이미 들어왔다
        conn.execute("UPDATE meta SET v = '2026-11-12T07:10:00' WHERE k = 'refreshed_at'")
        self.assertFalse(T.due(conn, date(2026, 11, 12), probe=yes))    # 발표 주간이 아니면 찔러 보지 않는다

    def test_prev_ym(self):
        self.assertEqual(T.prev_ym(date(2026, 1, 15)), '2025-12')
        self.assertEqual(T.prev_ym(date(2026, 11, 15)), '2026-10')


class ConfigTest(unittest.TestCase):
    def test_watch_config_uses_collected_hs_and_valid_regions(self):
        cfg = json.loads((ROOT / 'export_watch.json').read_text(encoding='utf-8'))
        hs = json.loads((ROOT / 'consumer_hs.json').read_text(encoding='utf-8'))
        collected = {h for g in hs['groups'] for h in g['hs6']}
        for c in cfg['cats']:
            for h in c['hs6']:
                self.assertIn(h, collected, f'{c["name"]} 의 HS {h} 를 collect_trade 가 받지 않는다')
            for it in c['items']:
                self.assertTrue(it['regions'])
                for r in it['regions']:
                    code, _, name = r.partition(':')
                    self.assertTrue(code.isdigit() and len(code) == 2 and name, r)
                self.assertTrue(it['c'] is None or (len(it['c']) == 6 and it['c'].isdigit()), it)


class EUTest(unittest.TestCase):
    CSV = """DATAFLOW,LAST UPDATE,freq,reporter,partner,product,flow,indicators,TIME_PERIOD,OBS_VALUE
ESTAT:DS-045409(1.0),x,M,EU27_2020,KR,330499,1,VALUE_IN_EUROS,2026-09,1000
ESTAT:DS-045409(1.0),x,M,EU27_2020,KR,330499,1,QUANTITY_IN_100KG,2026-09,2.5
ESTAT:DS-045409(1.0),x,M,EU27_2020,CN,330499,1,VALUE_IN_EUROS,2026-09,
"""

    def test_parse_values_and_kg(self):
        out = CE.parse(self.CSV)
        self.assertEqual(out[('2026-09', 'EU27_2020', 'KR', '330499')], [1000.0, 250.0])
        self.assertNotIn(('2026-09', 'EU27_2020', 'CN', '330499'), out)   # 빈 값(비밀 보호)은 뺀다

    def test_build_sums_basket_and_shares(self):
        conn = T.connect(Path(':memory:'))
        conn.executescript(CE.SCHEMA)
        rows = []
        for k in range(15):
            ym = W.ym_add('2025-07', k)                                     # 2025-07 ~ 2026-09
            f = 2 if ym >= '2026-07' else 1
            rows += [(ym, 'EU27_2020', 'KR', '330499', 100.0 * f, 10.0), (ym, 'EU27_2020', 'KR', '340130', 50.0 * f, 5.0),
                     (ym, 'EU27_2020', 'CN', '330499', 80.0, 40.0), (ym, 'EU27_2020', 'EXT_EU27_2020', '330499', 600.0, 1.0),
                     (ym, 'EU27_2020', 'KR', '300249', 7.0, None)]
        conn.executemany('INSERT INTO eu VALUES (?,?,?,?,?,?)', rows)
        e = EUT.build(conn)
        self.assertEqual(e['last_ym'], '2026-09')
        self.assertEqual(e['kr'][-1], 300)                                  # 바스켓 = 330499 + 340130, 톡신은 빠진다
        self.assertEqual(e['tox']['kr'][-1], 7)
        eu27 = e['rep'][0]
        self.assertEqual(eu27['r'], 'EU27_2020')
        self.assertAlmostEqual(eu27['kr_yoy3'], 1.0)
        self.assertAlmostEqual(eu27['kr_sh3'], 900 / 1800)
        self.assertIsNone(e['rep'][1]['kr3'])                               # 독일 자료가 없다 → 0 합 아님
        self.assertIsNone(EUT.build(T.connect(Path(':memory:'))))


if __name__ == '__main__':
    unittest.main()
