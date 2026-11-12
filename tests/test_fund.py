import unittest

import fund

OLD = """<TITLE ATOC="Y">3. 연결재무제표 주석</TITLE>
<P>19. 영업비용19-1 당분기와 전분기 중 발생한 비용을 성격별로 분류한 내역은 다음과 같습니다. (단위: 원)</P>
<TABLE><THEAD><TR><TH>구  분</TH><TH>당분기</TH><TH>전분기</TH></TR></THEAD><TBODY>
<TR><TD>재고자산의 변동</TD><TD>(1,105,319,877)</TD><TD>(2,625,220,515)</TD></TR>
<TR><TD>원재료의 사용 및 상품매입</TD><TD>283,995,492,379</TD><TD>250,062,171,179</TD></TR>
<TR><TD>급여</TD><TD>15,000,000,000</TD><TD>14,000,000,000</TD></TR>
<TR><TD>퇴직급여</TD><TD>3,000,000,000</TD><TD>3,000,000,000</TD></TR>
<TR><TD>매출원가와 판매비와관리비</TD><TD>338,726,439,738</TD><TD>303,704,855,654</TD></TR>
</TBODY></TABLE>
<P>19-2 종업원급여 내역 (단위: 원)</P>
<TABLE><TR><TH>구분</TH><TH>당분기</TH></TR><TR><TD>급여</TD><TD>1</TD></TR><TR><TD>퇴직급여</TD><TD>2</TD></TR><TR><TD>합계</TD><TD>3</TD></TR></TABLE>
<TITLE ATOC="Y">5. 재무제표 주석</TITLE>
<P>18. 비용의 성격별 분류: 당분기 및 전분기 중 비용의 성격별 분류 내역은 다음과 같습니다.</P>
<TABLE><TR><TD>(단위 : 백만원)</TD></TR></TABLE>
<TABLE><TR><TH>구분</TH><TH>당분기 3개월</TH><TH>당분기 누적</TH><TH>전분기 3개월</TH><TH>전분기 누적</TH></TR>
<TR><TD>원재료 등의 사용액</TD><TD>100</TD><TD>300</TD><TD>90</TD><TD>250</TD></TR>
<TR><TD>감가상각비</TD><TD>10</TD><TD>30</TD><TD>9</TD><TD>27</TD></TR>
<TR><TD>합  계</TD><TD>110</TD><TD>330</TD><TD>99</TD><TD>277</TD></TR></TABLE>
"""

NEW = """<TABLE-GROUP ACLASS="{XBRL}NT_C_D834300" ADELETETABLE="N">
<TITLE ATOC="Y">18. 비용의 성격별 분류 (연결)</TITLE>
<TABLE><TR><TD></TD></TR></TABLE>
<TABLE><TR><TE COLSPAN="2">비용의 성격별 분류 공시</TE></TR><TR><TE>당분기</TE><TE>(단위 : 원)</TE></TR></TABLE>
<TABLE><THEAD><TR><TH>　</TH><TH>공시금액</TH></TR></THEAD><TBODY>
<TR><TE>재고자산의 변동</TE><TE>(5,310,670,790)</TE></TR><TR><TE>원재료 등의 사용액</TE><TE>624,716,228,508</TE></TR>
<TR><TE>종업원급여</TE><TE>26,152,566,416</TE></TR><TR><TE>성격별 비용 합계</TE><TE>702,174,475,266</TE></TR></TBODY></TABLE>
<TABLE><TR><TE>전분기</TE><TE>(단위 : 원)</TE></TR></TABLE>
<TABLE><THEAD><TR><TH>　</TH><TH>공시금액</TH></TR></THEAD><TBODY>
<TR><TE>재고자산의 변동</TE><TE>4,392,937,382</TE></TR><TR><TE>원재료 등의 사용액</TE><TE>399,250,337,625</TE></TR>
<TR><TE>종업원급여</TE><TE>20,782,421,407</TE></TR><TR><TE>성격별 비용 합계</TE><TE>468,653,024,280</TE></TR></TBODY></TABLE>
<TABLE><TR><TE>당분기</TE><TE>(단위 : 원)</TE></TR></TABLE>
<TABLE><TR><TH></TH><TH>공시금액</TH></TR><TR><TE>급여</TE><TE>1</TE></TR><TR><TE>퇴직급여</TE><TE>2</TE></TR><TR><TE>합계</TE><TE>3</TE></TR></TABLE>
</TABLE-GROUP>"""


class TableTest(unittest.TestCase):
    def test_old_format_both_bases_and_unit_only_table(self):
        ts = fund.note_tables(OLD)
        self.assertEqual([t['basis'] for t in ts], ['C', 'S'])
        self.assertEqual(ts[0]['unit'], '원')
        self.assertEqual(ts[1]['unit'], '백만원')            # 설명 뒤의 단위만 든 표를 건너뛰고 단위를 이어받는다
        self.assertEqual(len(ts[0]['rows']), 5)              # 뒤의 종업원급여 내역 표는 안 섞인다

    def test_facts_cumulative_and_aggregated_keys(self):
        t = fund.note_tables(OLD)[0]
        f = {(k, st, en): v for k, _, st, en, v, _ in fund.table_facts(t, '2023-09-30', 'Q')}
        self.assertAlmostEqual(f[('raw', '2023-01-01', '2023-09-30')], 2839.95, places=1)
        self.assertAlmostEqual(f[('inv', '2022-01-01', '2022-09-30')], -26.25, places=1)
        self.assertAlmostEqual(f[('emp', '2023-01-01', '2023-09-30')], 180.0)       # 급여 + 퇴직급여
        self.assertIn(('total', '2023-01-01', '2023-09-30'), f)

    def test_three_month_and_cumulative_columns(self):
        t = fund.note_tables(OLD)[1]
        f = {(k, st, en): v for k, _, st, en, v, _ in fund.table_facts(t, '2023-09-30', 'Q')}
        self.assertAlmostEqual(f[('raw', '2023-07-01', '2023-09-30')], 1.0)          # 100 백만원
        self.assertAlmostEqual(f[('raw', '2023-01-01', '2023-09-30')], 3.0)
        self.assertAlmostEqual(f[('dep', '2022-07-01', '2022-09-30')], 0.09)

    def test_new_group_format_first_table_per_period(self):
        ts = fund.note_tables(NEW)
        self.assertEqual([(t['basis'], t['cols']) for t in ts], [('C', ['당기 공시금액']), ('C', ['전기 공시금액'])])
        f = {(k, st, en): v for t in ts for k, _, st, en, v, _ in fund.table_facts(t, '2026-09-30', 'Q')}
        self.assertAlmostEqual(f[('raw', '2026-01-01', '2026-09-30')], 6247.2, places=1)
        self.assertAlmostEqual(f[('total', '2025-01-01', '2025-09-30')], 4686.5, places=1)
        self.assertAlmostEqual(f[('emp', '2026-01-01', '2026-09-30')], 261.5, places=1)   # 딸린 표(1·2·3)가 덮어쓰지 않는다

    def test_two_label_columns_use_the_inner_name(self):
        html = """<TABLE><TR><TH></TH><TH></TH><TH>공시금액</TH></TR>
        <TR><TE COLSPAN="2">성격별 비용</TE><TE>100</TE></TR>
        <TR><TE ROWSPAN="3">성격별 비용</TE><TE>원재료 등의 사용액</TE><TE>70</TE></TR>
        <TR><TE>급여</TE><TE>20</TE></TR><TR><TE>기타 비용</TE><TE>10</TE></TR></TABLE>"""
        t = fund.parse_table(html)
        self.assertEqual(t['cols'], ['공시금액'])
        self.assertEqual([r[0] for r in t['rows']], ['성격별 비용', '원재료 등의 사용액', '급여', '기타 비용'])
        self.assertEqual([r[1][0] for r in t['rows']], [100, 70, 20, 10])

    def test_keys(self):
        self.assertEqual(fund.key_of('감가상각비(투자부동산감가상각비 포함)'), ('dep', '감가상각비'))
        self.assertEqual(fund.key_of('사용권자산상각비'), ('rou', '감가상각비'))
        self.assertEqual(fund.key_of('제품과 재공품의 감소(증가)'), ('inv', '원가'))
        self.assertEqual(fund.key_of('원재료와 소모품의 사용액'), ('raw', '원가'))
        self.assertEqual(fund.key_of('성격별 기타비용'), ('other', '기타'))
        self.assertEqual(fund.key_of('성격별 비용')[0], 'total')
        self.assertEqual(fund.key_of('경상연구개발비')[1], 'R&D')
        self.assertEqual(fund.key_of('포장비'), ('x:포장', '기타'))
        self.assertEqual(fund.key_of('전산비')[0], fund.key_of('전산 비용')[0])            # 표기가 달라도 같은 키
        self.assertEqual(fund.key_of('재고자산의 매입')[0], fund.key_of('재고자산 매입액')[0])
        self.assertEqual(fund.key_of('홍보비')[1], '광고선전비')

    def test_periods(self):
        self.assertEqual(fund.period_of('2023-09-30', 'ytd'), ('2023-01-01', '2023-09-30'))
        self.assertEqual(fund.period_of('2023-09-30', 'q'), ('2023-07-01', '2023-09-30'))
        self.assertEqual(fund.period_of('2023-09-30', 'ytd', prev=True), ('2022-01-01', '2022-09-30'))
        self.assertEqual(fund.period_of('2024-03-31', 'ytd', fy_end_month=6), ('2023-07-01', '2024-03-31'))   # 6월 결산
        self.assertEqual(fund.months_back('2024-03-31', 3), '2023-12-31')


class QuarterTest(unittest.TestCase):
    def test_quarterize_from_cumulative(self):
        v = {('2023-01-01', '2023-03-31'): 10, ('2023-01-01', '2023-06-30'): 25, ('2023-01-01', '2023-09-30'): 45, ('2023-01-01', '2023-12-31'): 70}
        self.assertEqual(fund.quarterize(v), {'2023-03-31': 10, '2023-06-30': 15, '2023-09-30': 20, '2023-12-31': 25})

    def test_three_month_wins_and_annual_minus_three_quarters(self):
        v = {('2023-01-01', '2023-03-31'): 10, ('2023-04-01', '2023-06-30'): 16, ('2023-01-01', '2023-06-30'): 25,
             ('2023-07-01', '2023-09-30'): 20, ('2023-01-01', '2023-12-31'): 70}
        q = fund.quarterize(v)
        self.assertEqual(q['2023-06-30'], 16)
        self.assertEqual(q['2023-12-31'], 70 - 10 - 16 - 20)

    def test_gap_stays_empty(self):
        v = {('2023-01-01', '2023-03-31'): 10, ('2023-01-01', '2023-09-30'): 45}
        self.assertEqual(fund.quarterize(v), {'2023-03-31': 10})      # 상반기가 없으면 3Q 를 지어내지 않는다

    def test_label(self):
        self.assertEqual(fund.qlabel('2026-09-30'), '3Q26')


class BridgeTest(unittest.TestCase):
    lines = {'raw': {'g': '원가', 'v': {'a': 80, 'b': 90}}, 'inv': {'g': '원가', 'v': {'a': 2, 'b': -1}}, 'emp': {'g': '인건비', 'v': {'a': 6, 'b': 6}},
             'total': {'g': '비용합계', 'v': {'a': 95, 'b': 99}}}

    def test_grouped_reconciles_to_total(self):
        g = fund.grouped(self.lines, 'a')
        self.assertEqual(g['원가'], 82)
        self.assertEqual(g['기타'], 95 - 82 - 6)
        self.assertAlmostEqual(sum(g.values()), 95)

    def test_bridge_sums_to_opm_change(self):
        g0, g1 = fund.grouped(self.lines, 'a'), fund.grouped(self.lines, 'b')
        br = dict(fund.bridge(g0, 100, g1, 100))
        self.assertAlmostEqual(br['원가'], 7.0)
        self.assertAlmostEqual(sum(br.values()), (99 - 95))          # 비용 비중 +4%p = OPM −4%p

    def test_model_fixed_amount_variable_ratio(self):
        hist = [(100, {'원가': 80, '인건비': 6, '기타': 4}), (200, {'원가': 150, '인건비': 8, '기타': 8})]
        m = fund.model(hist, 300)
        self.assertEqual(m['fix'], {'인건비': 8})                     # 직전 분기 금액
        self.assertAlmostEqual(m['var']['원가'], (0.8 + 0.75) / 2)
        self.assertAlmostEqual(m['op'], 300 - 8 - 300 * (0.775 + 0.04), places=1)


class ReportTest(unittest.TestCase):
    def test_quarter_of_report(self):
        ends = ['2026-06-30', '2026-09-30', '2026-12-31']
        self.assertEqual(fund.quarter_of_report('2026-10-28', ends), '2026-09-30')   # 3Q 리뷰
        self.assertEqual(fund.quarter_of_report('2026-09-15', ends), '2026-09-30')   # 분기 말 20일 전부터는 프리뷰
        self.assertEqual(fund.quarter_of_report('2026-08-20', ends), '2026-06-30')

    def test_evidence_tags_and_order(self):
        text = '3분기 영업이익은 컨센서스를 하회했다. DDR5 판가 하락과 원재료 가격 상승으로 원가율이 높아졌다. 성과급 충당으로 인건비도 늘었다. 수익성은 4분기에 회복될 전망이다.'
        ev = fund.evidence(text)
        self.assertEqual(ev[0][0], ['원가'])
        self.assertIn('판가', ev[0][1])
        self.assertTrue(any(g == ['인건비'] for g, _ in ev))
        self.assertEqual(ev[-1][0], ['마진'])                          # 일반 낱말만 든 문장은 뒤로


if __name__ == '__main__':
    unittest.main()
