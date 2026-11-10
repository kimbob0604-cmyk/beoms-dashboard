import json
import unittest
from datetime import date
from pathlib import Path

import build_consumer as B
import collect_trade as T
import consumer as K
import consumer_draft as D
from collectors import customs as C

ROOT = Path(__file__).resolve().parent.parent


class SeriesTest(unittest.TestCase):
    def test_months_and_quarter(self):
        self.assertEqual(K.months('2025-11', '2026-02'), ['2025-11', '2025-12', '2026-01', '2026-02'])
        self.assertEqual([K.quarter(m) for m in ('2026-01', '2026-03', '2026-04', '2026-12')], ['2026Q1', '2026Q1', '2026Q2', '2026Q4'])

    def test_yoy_one_month_and_three_months(self):
        v = [100] * 12 + [100, 110, 120, 150]
        self.assertAlmostEqual(K.yoy(v), 0.5)                       # 150 / 100
        self.assertAlmostEqual(K.yoy(v, span=3), 380 / 300 - 1)
        self.assertIsNone(K.yoy([1] * 12))                           # 전년 값이 없다
        self.assertIsNone(K.yoy([0] * 12 + [5]))                     # 전년이 0
        self.assertIsNone(K.yoy([100] * 12 + [None]))                # 이번 달이 없다

    def test_quarter_sums_counts_months(self):
        ms = K.months('2026-01', '2026-05')
        self.assertEqual(K.quarter_sums(ms, [1, 2, 3, 10, None]), {'2026Q1': (6.0, 3), '2026Q2': (10.0, 1)})


class FinTest(unittest.TestCase):
    def test_single_quarters_from_three_month_values(self):
        rows = [{'year': 2025, 'reprt': '11013', 'cur': 100, 'cur_add': 100},
                {'year': 2025, 'reprt': '11012', 'cur': 120, 'cur_add': 220},
                {'year': 2025, 'reprt': '11014', 'cur': 130, 'cur_add': 350},
                {'year': 2025, 'reprt': '11011', 'cur': 500, 'cur_add': None}]
        self.assertEqual(K.single_quarters(rows), {'2025Q1': 100, '2025Q2': 120, '2025Q3': 130, '2025Q4': 150})

    def test_single_quarters_when_only_cumulative_is_reported(self):
        rows = [{'year': 2025, 'reprt': '11013', 'cur': 100, 'cur_add': 100},
                {'year': 2025, 'reprt': '11012', 'cur': 220, 'cur_add': 220},      # 누적만
                {'year': 2025, 'reprt': '11014', 'cur': 350, 'cur_add': 350}]
        self.assertEqual(K.single_quarters(rows), {'2025Q1': 100, '2025Q2': 120, '2025Q3': 130})

    def test_q4_needs_q3_cumulative(self):
        rows = [{'year': 2025, 'reprt': '11011', 'cur': 500, 'cur_add': None}]
        self.assertEqual(K.single_quarters(rows), {})                # 3분기 누적이 없으면 4분기를 지어내지 않는다


class RelationTest(unittest.TestCase):
    def setUp(self):
        # 매출 전년비 = 2% + 0.5 × 수출 전년비 가 정확히 성립하는 자료
        qs = [f'{y}Q{q}' for y in (2022, 2023, 2024, 2025) for q in (1, 2, 3, 4)] + ['2026Q1', '2026Q2']
        g = [0.10, 0.30, -0.05, 0.20, 0.50, 0.15, 0.00, 0.40, 0.25, -0.10, 0.35, 0.05, 0.45, 0.20]   # 2023Q1 부터의 수출 전년비
        self.exp = {q: 100.0 + 10 * i for i, q in enumerate(qs[:4])}
        self.rev = {q: 1000.0 + 50 * i for i, q in enumerate(qs[:4])}
        for q, x in zip(qs[4:], g):
            p = K.prev_year(q)
            self.exp[q] = self.exp[p] * (1 + x)
            self.rev[q] = self.rev[p] * (1 + 0.02 + 0.5 * x)

    def test_yoy_corr_needs_enough_quarters(self):
        r, n = K.yoy_corr(self.exp, self.rev)
        self.assertEqual(n, 12)                                       # 최근 12분기만 본다
        self.assertGreater(r, 0.999)
        few = {q: v for q, v in self.exp.items() if q >= '2025Q1'}
        self.assertEqual(K.yoy_corr(few, self.rev), (None, 2))

    def test_qualified_needs_correlation_and_meaningful_share(self):
        self.assertTrue(K.qualified(0.8, 12, 0.6))
        self.assertFalse(K.qualified(0.8, 12, 0.01))                  # 매출의 1% — 우연히 같이 움직였을 뿐
        self.assertFalse(K.qualified(0.8, 12, 6.8))                   # 수출이 매출의 몇 배 — 다른 회사 물량
        self.assertFalse(K.qualified(0.5, 12, 0.6))
        self.assertFalse(K.qualified(0.9, 6, 0.6))                    # 분기 수가 적다
        self.assertFalse(K.qualified(None, 0, None))

    def test_preview_estimates_from_yoy_and_judges(self):
        exp = dict(self.exp, **{'2026Q3': self.exp['2025Q3'] * 1.30})         # 수출 전년비 +30%
        want = self.rev['2025Q3'] * (1 + 0.02 + 0.5 * 0.30)
        p = K.preview(exp, self.rev, '2026Q3', consensus=want / 1.125)
        self.assertAlmostEqual(p['est'], want, places=6)
        self.assertAlmostEqual(p['mae'], 0.0, places=9)
        self.assertEqual((p['verdict'], round(p['diff'], 3), p['n']), ('BEAT', 0.125, 12))
        self.assertEqual(K.preview(exp, self.rev, '2026Q3', consensus=want * 1.01)['verdict'], 'IN LINE')
        self.assertEqual(K.preview(exp, self.rev, '2026Q3', consensus=want * 1.2)['verdict'], 'MISS')
        self.assertIsNone(K.preview(exp, self.rev, '2026Q3', consensus=None)['verdict'])

    def test_preview_gives_no_verdict_when_past_fit_was_poor(self):
        exp = dict(self.exp, **{'2026Q3': self.exp['2025Q3'] * 1.30})
        noisy = dict(self.rev)
        for q, k in (('2025Q3', 1.5), ('2025Q4', 0.6), ('2026Q1', 1.4), ('2026Q2', 0.7)):   # 최근 4분기 매출이 수출과 따로 놀았다
            noisy[q] = self.rev[q] * k
        p = K.preview(exp, noisy, '2026Q3', consensus=1000.0)
        self.assertGreater(p['mae'], K.MAE_OK)
        self.assertIsNone(p['verdict'])                               # 추정은 보여 주되 판정은 내지 않는다
        self.assertIsNotNone(p['diff'])

    def test_preview_refuses_reported_or_missing(self):
        exp = dict(self.exp, **{'2026Q3': 300.0})
        self.assertIsNone(K.preview(exp, self.rev, '2026Q2', 800.0))             # 이미 매출이 나온 분기
        self.assertIsNone(K.preview(self.exp, self.rev, '2026Q3', 800.0))        # 수출이 아직 없다
        short = {q: v for q, v in exp.items() if q >= '2025Q1'}
        self.assertIsNone(K.preview(short, self.rev, '2026Q3', 800.0))           # 표본 부족

    def test_hindcast_uses_only_earlier_quarters(self):
        h = K.hindcast(self.exp, self.rev, k=3)
        self.assertEqual([x['q'] for x in h], ['2025Q4', '2026Q1', '2026Q2'])
        self.assertTrue(all(abs(x['err']) < 1e-9 for x in h))
        rev = dict(self.rev, **{'2026Q2': self.rev['2026Q2'] * 1.1})             # 마지막 분기만 실제가 10% 높았다면
        self.assertAlmostEqual(K.hindcast(self.exp, rev, k=1)[0]['err'], 1 / 1.1 - 1)
        self.assertEqual(K.hindcast({q: v for q, v in self.exp.items() if q < '2024Q2'}, self.rev), [])   # 표본 부족

    def test_region_match_by_suffix_and_sido(self):
        self.assertTrue(K.region_match('11', '서울특별시 송파구', ['11:송파구']))
        self.assertTrue(K.region_match('51', '강원특별자치도 원주시', ['48:밀양시', '51:원주시']))
        self.assertTrue(K.region_match('36', '세종특별자치시', ['36:세종특별자치시']))
        self.assertFalse(K.region_match('26', '부산광역시 북구', ['29:북구']))        # 다른 시도의 같은 이름
        self.assertFalse(K.region_match('11', '서울특별시 성북구', ['11:북구']))      # 끝말만 같은 다른 구


class CustomsTest(unittest.TestCase):
    XML = ('<response><header><resultCode>00</resultCode><resultMsg>NORMAL</resultMsg></header><body><items>'
           '<item><year>총계</year><hsCode>-</hsCode><expDlr>300</expDlr><expWgt>30</expWgt></item>'
           '<item><year>2026.09</year><hsCode>3304991000</hsCode><statKor>기초화장용 제품류</statKor><expDlr>200</expDlr><expWgt>20</expWgt></item>'
           '<item><year>2026.09</year><hsCode>304870000</hsCode><statKor>x</statKor><expDlr>100</expDlr><expWgt>10</expWgt></item>'
           '</items></body></response>')

    def test_parse_and_normalize(self):
        rows = C.parse_items(self.XML)
        self.assertEqual(len(rows), 3)
        self.assertEqual(C.period('2026.09'), '2026-09')
        self.assertIsNone(C.period('총계'))
        self.assertEqual(C.hs_norm('304870000'), '0304870000')       # 숫자로 와서 빠진 앞자리 0
        self.assertEqual(C.hs_norm('330499'), '330499')
        self.assertEqual(C.parse_items('<response><header><resultCode>03</resultCode></header></response>'), [])
        with self.assertRaises(C.CustomsError):
            C.parse_items('<response><header><resultCode>99</resultCode><resultMsg>조회기간</resultMsg></header></response>')

    def test_sido_codes_follow_2026_reform(self):
        self.assertIn('29', C.sido_for('202601', '202606'))
        self.assertNotIn('12', C.sido_for('202601', '202606'))
        self.assertIn('12', C.sido_for('202607', '202612'))
        self.assertNotIn('46', C.sido_for('202607', '202612'))


class PlanTest(unittest.TestCase):
    def test_windows_split_2026_and_skip_future(self):
        today = date(2026, 11, 10)
        self.assertEqual(T.windows(2025, today), [('202501', '202512')])
        self.assertEqual(T.windows(2026, today), [('202601', '202606'), ('202607', '202611')])
        self.assertEqual(T.windows(2027, today), [])

    def test_due_schedule(self):
        conn = T.connect(Path(':memory:'))
        self.assertTrue(T.due(conn, date(2026, 11, 10)))             # 받은 적 없음
        conn.execute("INSERT INTO meta VALUES ('refreshed_at', '2026-11-10T09:00:00')")
        self.assertFalse(T.due(conn, date(2026, 11, 10)))            # 오늘 이미 받음
        self.assertFalse(T.due(conn, date(2026, 11, 12)))            # 이틀 뒤, 발표 주간이 아님
        self.assertTrue(T.due(conn, date(2026, 11, 15)))             # 발표 주간(14~21일)은 날마다
        self.assertTrue(T.due(conn, date(2026, 12, 1)))              # 7일 넘게 지났다


class BuildTest(unittest.TestCase):
    HS = {'start_year': 2024, 'countries': ['US'], 'groups': [
        {'id': 'ramen', 'sector': '식음료', 'label': '라면', 'hs6': ['190230']},
        {'id': 'device', 'sector': '화장품', 'label': '미용기기', 'hs6': ['854370'], 'hs10': ['8543702020']}]}

    def setUp(self):
        self.t = T.connect(Path(':memory:'))
        ms = K.months('2024-01', '2026-09')
        self.t.executemany('INSERT INTO item VALUES (?,?,?,?,?)',
                           [(m, '1902301010', '라면', 100.0 + i, 10.0) for i, m in enumerate(ms)]
                           + [(m, '1902309000', '기타', 5.0, 1.0) for m in ms]
                           + [(m, '8543702020', '미용기기', 50.0, 1.0) for m in ms]
                           + [(m, '8543709090', '기타', 999.0, 1.0) for m in ms])          # 미용기기 묶음에 들어가면 안 된다
        self.t.executemany('INSERT INTO sgg VALUES (?,?,?,?,?,?)',
                           [(m, '48', '경상남도 밀양시', '190230', 60.0 + i, 1) for i, m in enumerate(ms)]
                           + [(m, '51', '강원특별자치도 원주시', '190230', 30.0, 1) for m in ms[:-1]]   # 마지막 달은 원주 값 없음
                           + [(m, '26', '부산광역시 사상구', '190230', 40.0, 1) for m in ms])
        self.trade = B.Trade(self.t, self.HS)

    def test_national_uses_hs10_when_given(self):
        usd, kg = self.trade.national('ramen')
        self.assertEqual((usd[0], kg[0]), (105.0, 11.0))             # 190230 아래 HS10 둘의 합
        self.assertEqual(self.trade.national('device')[0][0], 50.0)  # hs10 지정 묶음은 그 품목만

    def test_regional_sums_matching_regions_only(self):
        v = self.trade.regional('ramen', ['48:밀양시', '51:원주시'])
        self.assertEqual(v[0], 90.0)
        self.assertEqual(v[-1], 60.0 + 32)                           # 시군구 통계가 있는 달인데 원주 값이 없으면 0 으로 더한다
        self.assertIsNone(self.trade.regional('ramen', ['11:강남구']))  # 그 지역에 이 품목 수출이 없다

    def test_flow_stats_and_main_pick(self):
        fx = {m: 1000.0 for m in self.trade.months}
        usd = self.trade.regional('ramen', ['48:밀양시'])
        exp_q = {q: s for q, (s, k) in K.quarter_sums(self.trade.months, [u * 1000 / 1e8 for u in usd]).items() if k == 3}
        rev = {q: 5.0 + 3.0 * v for q, v in exp_q.items() if q < '2026Q3'}     # 매출 = 5 + 3 × 수출, 3분기는 아직 없음
        st = B.flow_stats(self.trade, usd, fx, rev)
        self.assertEqual(st['nq'], 6)
        self.assertGreater(st['r'], 0.99)
        self.assertAlmostEqual(st['yoy'], (60 + 32) / (60 + 20) - 1)
        mk = lambda i, kind, basis, r, cover=0.5: {'id': i, 'kind': kind, 'basis': basis, 'r': r, 'nq': 12, 'cover': cover}
        flows = [mk('n', 'national', 'national', 0.9), mk('h', 'sigungu', 'hq', 0.2), mk('c', 'sigungu', 'channel', None)]
        self.assertEqual(B.pick_main(flows)['id'], 'c')              # 확인된 지역 흐름이 없으면 채널 근거 지역
        flows[1] = mk('h', 'sigungu', 'hq', 0.8)
        self.assertEqual(B.pick_main(flows)['id'], 'h')              # 상관·비중이 확인되면 그 흐름
        flows[1] = mk('h', 'sigungu', 'hq', 0.8, cover=0.01)
        self.assertEqual(B.pick_main(flows)['id'], 'c')              # 상관이 높아도 매출의 1% 면 대표가 아니다
        self.assertEqual(B.pick_main([flows[0], flows[1]])['id'], 'n')   # 확인 안 된 본사 흐름보다 전국 업황
        self.assertIsNone(B.pick_main([]))


class ConfigTest(unittest.TestCase):
    """consumer_hs.json · consumer_assets.json 이 서로 맞는가 (손으로 고치다 틀리는 것을 잡는다)"""

    def setUp(self):
        self.hs = json.loads((ROOT / 'consumer_hs.json').read_text(encoding='utf-8'))
        self.assets = json.loads((ROOT / 'consumer_assets.json').read_text(encoding='utf-8'))

    def test_hs_dictionary(self):
        ids = [g['id'] for g in self.hs['groups']]
        self.assertEqual(len(ids), len(set(ids)))
        for g in self.hs['groups']:
            self.assertIn(g['sector'], self.assets['chains'])
            self.assertTrue(all(len(h) == 6 and h.isdigit() for h in g['hs6']), g['id'])
            self.assertTrue(all(len(h) == 10 and h[:6] in g['hs6'] for h in g.get('hs10', [])), g['id'])
        self.assertTrue(all(len(c) == 2 and c.isupper() for c in self.hs['countries']))

    def test_stocks(self):
        groups = {g['id'] for g in self.hs['groups']}
        codes = [s['code'] for s in self.assets['stocks']]
        self.assertEqual(len(codes), len(set(codes)))
        for s in self.assets['stocks']:
            self.assertRegex(s['code'], r'^[0-9A-Z]{6}$')
            self.assertIn(s['stage'], self.assets['chains'][s['sector']], s['name'])
            self.assertLessEqual(set(s['groups']), groups, s['name'])
            fids = [f['id'] for f in s['flows']]
            self.assertEqual(len(fids), len(set(fids)), s['name'])
            for f in s['flows']:
                self.assertIn(f['group'], s['groups'])
                self.assertIn(f['basis'], ('channel', 'hq', 'national'))
                if f['kind'] == 'sigungu':
                    self.assertTrue(f['regions'] and all(':' in r and r.split(':')[0].isdigit() for r in f['regions']), s['name'])

    def test_region_of_address(self):
        self.assertEqual(D.region_of('경기도 성남시 분당구 판교역로 255'), '41:성남시')
        self.assertEqual(D.region_of('서울특별시 용산구 한강대로 100'), '11:용산구')
        self.assertEqual(D.region_of('대전 유성구 탑립동 928번지'), '30:유성구')
        self.assertEqual(D.region_of('세종특별자치시  전의면 덕고개길'), '36:세종특별자치시')
        self.assertIsNone(D.region_of(''))


if __name__ == '__main__':
    unittest.main()
