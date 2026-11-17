import json
import tempfile
import unittest
from pathlib import Path

import build_etf_flow as EF
import collect_medical as CM
import collect_us as CU
import medical as MD
import us_trade as UT
from unittest import mock
import collect_tourism as CT
import collect_trade as T
import collect_trends as GT
import tourism as TO

OK_XML = """<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
<body><items>
<item><ed>방한외래관광객</ed><edCd>E</edCd><natCd>112</natCd><natKorNm>중국</natKorNm><num>500000</num><rnum>1</rnum><ym>202609</ym></item>
<item><ed>방한외래관광객</ed><edCd>E</edCd><natCd>130</natCd><natKorNm>일본</natKorNm><num>300,000</num><rnum>2</rnum><ym>202609</ym></item>
</items><numOfRows>999</numOfRows><pageNo>1</pageNo><totalCount>2</totalCount></body></response>"""
BAD_KEY = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><header><resultCode>30</resultCode><resultMsg>SERVICE KEY IS NOT REGISTERED ERROR.</resultMsg></header></response>"""


class TourismTest(unittest.TestCase):
    def test_parse_rows_and_errors(self):
        rows = CT.parse(OK_XML)
        self.assertEqual(rows[1], {'ym': '2026-09', 'nat_cd': '130', 'nat': '일본', 'num': 300000.0})
        with self.assertRaises(CT.NotRegistered):
            CT.parse(BAD_KEY)

    def test_months(self):
        self.assertEqual(CT.months('2025-11', '2026-02'), ['2025-11', '2025-12', '2026-01', '2026-02'])

    def test_aggregate_names(self):
        self.assertTrue(TO.is_aggregate('아시아주'))
        self.assertTrue(TO.is_aggregate('합계'))
        self.assertFalse(TO.is_aggregate('호주'))
        self.assertFalse(TO.is_aggregate('중국'))

    def db(self, rows):
        conn = T.connect(Path(':memory:'))
        conn.executescript(CT.SCHEMA)
        conn.executemany('INSERT INTO tour VALUES (?,?,?,?)', rows)
        return conn

    def test_build_sums_countries_without_total_row(self):
        conn = self.db([('2026-09', '112', '중국', 500.0), ('2026-09', '130', '일본', 300.0), ('2026-09', '100', '아시아주', 800.0),
                        ('2026-08', '112', '중국', 400.0)])
        t = TO.build(conn)
        self.assertEqual(t['last_ym'], '2026-09')
        self.assertEqual(t['total'][-1], 800)                     # 아시아주 소계는 두 번 세지 않는다
        self.assertEqual(t['total_src'], 'sum')
        self.assertEqual([x['n'] for x in t['nats']], ['중국', '일본'])
        self.assertEqual(t['nats'][1]['v'][-2], 0)                # 8월에 일본 줄이 없으면 0 (그 달 자료는 있다)
        self.assertIsNone(t['nats'][1]['v'][0])                   # 2019-01 은 자료 자체가 없다

    def test_build_prefers_total_row(self):
        t = TO.build(self.db([('2026-09', '000', '합계', 1000.0), ('2026-09', '112', '중국', 500.0)]))
        self.assertEqual(t['total'][-1], 1000)
        self.assertEqual(t['total_src'], 'row')
        self.assertIsNone(TO.build(self.db([])))


class TrendsTest(unittest.TestCase):
    def test_batches_carry_anchor(self):
        kws = ['A', 'b', 'c', 'd', 'e', 'f', 'g']
        self.assertEqual(GT.batches(kws[:5], 'A'), [kws[:5]])
        self.assertEqual(GT.batches(kws, 'A'), [['A', 'b', 'c', 'd', 'e'], ['A', 'f', 'g']])

    def test_stitch_scales_by_anchor(self):
        p1 = {'A': [100, 50], 'b': [10, 10]}
        p2 = {'A': [50, 25], 'f': [20, 40]}                       # 두 번째 묶음에서 A 가 절반 → f 를 두 배로
        out = GT.stitch([p1, p2], 'A')
        self.assertEqual(out['f'], [40.0, 80.0])
        self.assertEqual(out['A'], [100, 50])

    def test_blend_averages_geos(self):
        self.assertEqual(GT.blend([{'x': [10, 20]}, {'x': [30, 40]}]), {'x': [20.0, 30.0]})

    def test_json_prefix(self):
        self.assertEqual(GT._json(")]}',\n{\"a\": 1}"), {'a': 1})


class EtfFlowTest(unittest.TestCase):
    def test_src_names_match_kbj(self):
        self.assertEqual(EF.src_name(5, 'in'), 'stocks.json')
        self.assertEqual(EF.src_name(5, 'out'), 'stocks@sort-out.json')
        self.assertEqual(EF.src_name(1, 'in'), 'stocks@period-1.json')
        self.assertEqual(EF.src_name(20, 'pct'), 'stocks@period-20.sort-pct.json')

    def test_build_merges_sorts(self):
        def f(rows, period=5):
            return {'as_of': '2026-11-12T15:30:00+09:00', 'generated_at': 'g', 'notes': ['n'],
                    'data': {'period': period, 'start': 's', 'end': 'e', 'coverage_pct': 37.0, 'n_etfs_known': 352, 'n_total': 1235,
                             'holdings_asof': '2026-10-19', 'rows': rows}}
        r = lambda c, v: {'code': c, 'name': c, 'inflow': v, 'inflow_pct': 1.0, 'n_etfs': 3,  # noqa: E731
                          'top_etfs': [{'code': '069500', 'name': 'KODEX 200', 'inflow': v}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'stocks.json').write_text(json.dumps(f([r('A', 2e10)])))
            (p / 'stocks@sort-out.json').write_text(json.dumps(f([r('B', -3e10), r('A', 2e10)])))
            out = EF.build(p)
        self.assertEqual(list(out['periods']), ['5'])
        rows = {x['c']: x for x in out['periods']['5']['rows']}
        self.assertEqual(rows['A']['in'], 200.0)                   # 억원
        self.assertEqual(rows['B']['top'], [['KODEX 200', -300.0]])
        self.assertEqual(out['holdings_asof'], '2026-10-19')
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(EF.build(Path(d)))


class UsImportTest(unittest.TestCase):
    def test_parse_keeps_total_rows_only(self):
        base = {'flowCode': 'M', 'partner2Code': 0, 'motCode': 0, 'customsCode': 'C00', 'period': '202608'}
        d = {'data': [{**base, 'partnerCode': 410, 'cmdCode': '330499', 'primaryValue': 100.0, 'netWgt': 5.0},
                      {**base, 'partnerCode': 410, 'cmdCode': '330499', 'primaryValue': 7.0, 'netWgt': 1.0, 'motCode': 1000},
                      {**base, 'partnerCode': 999, 'cmdCode': '330499', 'primaryValue': 1.0, 'netWgt': 1.0}]}
        self.assertEqual(CU.parse(d), [('2026-08', 'KR', '330499', 100.0, 5.0)])
        with self.assertRaises(CU.ComtradeError):
            CU.parse({'error': 'Maximum number of periods for preview is 1'})

    def test_build_shape_matches_eu_card(self):
        conn = T.connect(Path(':memory:'))
        conn.executescript(CU.SCHEMA)
        rows = []
        for k in range(14):
            ym = CT.months('2025-07', '2026-08')[k]
            rows += [(ym, 'KR', '330499', 200.0, 10.0), (ym, 'WLD', '330499', 800.0, 80.0), (ym, 'KR', '300249', 9.0, 0.1),
                     (ym, 'JP', '330499', 50.0, 1.0)]
        conn.executemany('INSERT INTO us VALUES (?,?,?,?,?)', rows)
        u = UT.build(conn)
        self.assertEqual(u['last_ym'], '2026-08')
        self.assertEqual((u['kr'][-1], u['ext'][-1], u['tox']['kr'][-1]), (200, 800, 9))
        self.assertEqual(u['oth'][0][0], '일본산')
        self.assertEqual(u['oth'][0][1][-1], 50)
        self.assertEqual(u['rep'], [])
        self.assertIsNone(u['cn'][0])                            # 2022-09 등 자료 없는 달은 None


class MedicalTest(unittest.TestCase):
    def test_query_parses_amount_and_count(self):
        class R:
            status_code = 200
            def __init__(self, lst): self.lst = lst
            def json(self): return {'list': self.lst}
        s = mock.Mock()
        s.post.return_value = R([{'BASE_YM': '202609', 'KTO_CATE_SCLS_NM': '피부과', 'CARD_COMPT_AMT_SUM': 5e9},
                                 {'BASE_YM': '2026', 'KTO_CATE_SCLS_NM': '약국', 'CARD_COMPT_AMT_SUM': 1.0}])
        self.assertEqual(CM.query(s, 'AMT', '000', '2026-09', '2026-09'), [('2026-09', '피부과', 5e9)])
        self.assertEqual(s.post.call_args[1]['data']['qid'], 'BY_TH_MEDIC_003_001_AMT')
        s.post.return_value = R([{'BASE_YM': '202609', 'KTO_CATE_SCLS_NM': '약국', 'CARD_COMPT_CNT_SUM': 7.0}])
        self.assertEqual(CM.query(s, 'CNT', '392', '2026-09', '2026-09'), [('2026-09', '약국', 7.0)])

    def test_build_global_cats_and_nations(self):
        conn = T.connect(Path(':memory:'))
        conn.executescript(CM.SCHEMA)
        conn.executemany('INSERT INTO med VALUES (?,?,?,?,?,?)', [
            ('2026-09', '000', '글로벌', '피부과', 3e9, 100.0), ('2026-09', '000', '글로벌', '약국', 1e9, 50.0),
            ('2026-09', '392', '일본', '피부과', 2e9, 40.0), ('2026-09', '392', '일본', '치과', 1e9, 10.0),
            ('2026-09', '156', '중국', '약국', 5e8, 30.0)])
        m = MD.build(conn)
        self.assertEqual(m['last_ym'], '2026-09')
        self.assertEqual([c['cat'] for c in m['cats']], ['피부과', '약국'])
        self.assertEqual(m['cats'][0]['v'][-1], 3000)             # 백만원
        jp = m['nats'][0]
        self.assertEqual((jp['n'], jp['amt'][-1], jp['피부과'][-1], jp['cnt'][-1]), ('일본', 3000, 2000, 50))
        self.assertEqual(m['nats'][1]['피부과'][-1], 0)
        self.assertIsNone(MD.build(T.connect(Path(':memory:'))))


if __name__ == '__main__':
    unittest.main()
