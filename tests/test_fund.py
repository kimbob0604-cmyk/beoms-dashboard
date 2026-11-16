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
        every = fund.note_tables(OLD)
        ts = [t for t in every if t['first']]
        self.assertEqual([t['basis'] for t in ts], ['C', 'S'])
        self.assertEqual([t['first'] for t in every], [True, False, True])    # 뒤따르는 표(종업원급여 내역)는 first 가 아니다 — 기준값과 맞을 때만 쓰인다
        self.assertEqual(fund.table_facts(every[1], '2023-09-30', 'Q', first=False), [])
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
        t = [x for x in fund.note_tables(OLD) if x['first']][1]
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

    def test_columns_assigned_by_income_statement_totals(self):
        # 기능별 행렬(판관비 / 매출원가 / 합계): 합계 열만 기준값(매출원가+판관비)과 맞는다
        t = {'mult': 1.0, 'cols': ['판매비와관리비', '매출원가', '합 계'],
             'rows': [('원재료 사용', [0, 70, 70]), ('급여', [10, 15, 25]), ('기타', [2, 3, 5]), ('합 계', [12, 88, 100])]}
        orc = {('2026-01-01', '2026-03-31'): [100.0, 101.5], ('2025-01-01', '2025-03-31'): [90.0]}
        f = {(k, st, en): v for k, _, st, en, v, _ in fund.table_facts(t, '2026-03-31', 'Q', oracle=orc)}
        self.assertEqual(f[('raw', '2026-01-01', '2026-03-31')], 70)
        self.assertEqual(f[('total', '2026-01-01', '2026-03-31')], 100)
        self.assertEqual({k[2] for k in f}, {'2026-03-31'})                 # 매출원가·판관비 열은 버린다
        # '제24기 반기 / 제23기 / 제22기': 첫 열만 이번 누적과 맞고, 지난 사업연도 열은 기준값이 없어 버린다 (전년 동기로 잘못 넣지 않는다)
        t2 = {'mult': 1.0, 'cols': ['제24기 반기', '제23기', '제22기'], 'rows': [('상품', [40, 90, 80]), ('급여', [10, 25, 22]), ('합계', [50, 115, 102])]}
        orc2 = {('2026-01-01', '2026-06-30'): [50.2], ('2025-01-01', '2025-06-30'): [44.0], ('2026-04-01', '2026-06-30'): [27.0]}
        f2 = {(k, st, en) for k, _, st, en, v, _ in fund.table_facts(t2, '2026-06-30', 'Q', oracle=orc2)}
        self.assertEqual({(st, en) for _, st, en in f2}, {('2026-01-01', '2026-06-30')})
        # 3개월·누적 표시가 사라진 4열: 숫자로 3개월과 누적을 가른다
        t3 = {'mult': 1.0, 'cols': ['당반기', '당반기', '전반기', '전반기'], 'rows': [('원재료', [30, 55, 20, 45]), ('합계', [40, 75, 28, 60])]}
        orc3 = {('2026-04-01', '2026-06-30'): [40.0], ('2026-01-01', '2026-06-30'): [75.0], ('2025-04-01', '2025-06-30'): [28.0], ('2025-01-01', '2025-06-30'): [60.0]}
        f3 = {(k, st, en): v for k, _, st, en, v, _ in fund.table_facts(t3, '2026-06-30', 'Q', oracle=orc3)}
        self.assertEqual(f3[('raw', '2026-04-01', '2026-06-30')], 30)
        self.assertEqual(f3[('raw', '2025-01-01', '2025-06-30')], 45)
        # 기준값이 없으면 머리말로: 표시 없는 당·전 두 쌍은 3개월·누적 순서
        f4 = {(k, st, en): v for k, _, st, en, v, _ in fund.table_facts(t3, '2026-06-30', 'Q')}
        self.assertEqual(f4[('raw', '2026-04-01', '2026-06-30')], 30)
        self.assertEqual(fund.col_role('당반기 당2분기'), ('cur', 'q'))
        self.assertEqual(fund.col_role('당반기 누적'), ('cur', 'ytd'))

    def test_subtotals_are_not_summed_into_total(self):
        t = {'mult': 1.0, 'cols': ['당기', '전기'], 'rows': [('원재료', [60, 50]), ('매출원가 소계', [60, 50]), ('급여', [40, 30]), ('합계', [100, 80])]}
        f = {(k, en): v for k, _, st, en, v, _ in fund.table_facts(t, '2025-12-31', 'A')}
        self.assertEqual(f[('total', '2025-12-31')], 100)                    # 소계 + 합계 = 160 이 아니라 합계

    def test_section_header_rows_are_dropped(self):
        # 구역 제목 줄 '연구개발비'(= 아래 두 줄의 합)를 비용 줄로 세면 합계보다 그만큼 많아진다
        t = {'mult': 1.0, 'cols': ['당기', '전기'], 'rows': [('원재료', [60, 50]), ('급여', [20, 15]), ('연구개발비', [10, 8]), ('급여', [7, 6]), ('기타비용', [3, 2]), ('합계', [90, 73])]}
        f = {(k, en): v for k, _, st, en, v, _ in fund.table_facts(t, '2025-12-31', 'A')}
        self.assertNotIn(('rnd', '2025-12-31'), f)
        self.assertEqual(f[('emp', '2025-12-31')], 27)
        self.assertEqual(sum(v for (k, en), v in f.items() if en == '2025-12-31' and k != 'total'), 90)
        # 합이 맞는 표에서는 아무것도 빼지 않는다 (감가상각비 10 = 그 아래 5 + 5 여도)
        ok = {'mult': 1.0, 'cols': ['당기'], 'rows': [('감가상각비', [10]), ('급여', [5]), ('기타비용', [5]), ('합계', [20])]}
        self.assertEqual(fund.section_rows(ok, 0, None), set())

    def test_discontinued_operations_row_is_excluded(self):
        t = {'mult': 1.0, 'cols': ['당기 공시금액'], 'rows': [('원재료', [70]), ('급여', [20]), ('중단영업으로부터 발생한 비용', [15]), ('성격별 비용(중단영업 포함) 합계', [105])]}
        f = {k: v for k, _, st, en, v, _ in fund.table_facts(t, '2025-12-31', 'A', oracle={('2025-01-01', '2025-12-31'): [90.2]})}
        self.assertEqual(f['total'], 90)                     # 105 − 15: 계속영업 비용 (기준값 90.2 와 맞는다)
        self.assertEqual(set(f), {'raw', 'emp', 'total'})

    def test_keys(self):
        self.assertEqual(fund.key_of('감가상각비(투자부동산감가상각비 포함)'), ('dep', '감가상각비'))
        self.assertEqual(fund.key_of('사용권자산상각비'), ('rou', '감가상각비'))
        self.assertEqual(fund.key_of('제품과 재공품의 감소(증가)'), ('inv', '원가'))
        self.assertEqual(fund.key_of('원재료와 소모품의 사용액'), ('raw', '원가'))
        self.assertEqual(fund.key_of('성격별 기타비용'), ('other', '기타'))
        self.assertEqual(fund.key_of('성격별 비용')[0], 'total')
        self.assertEqual(fund.key_of('경상연구개발비')[1], 'R&D')
        self.assertEqual(fund.key_of('종업원급여비용 합계'), ('emp', '인건비'))          # 특정 비용의 합계는 그 비용 줄
        self.assertEqual(fund.key_of('성격별 비용 합계')[0], 'total')
        self.assertEqual(fund.key_of('매출원가 소계')[0], 'total')
        self.assertEqual(fund.key_of('총비용')[0], 'total')
        self.assertEqual(fund.key_of('대손상각비')[1], '기타')                          # 감가상각이 아니다
        self.assertEqual(fund.key_of('판매비와관리비')[0], 'total')                     # 기능별 소계
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

    def test_annual_minus_three_month_quarters_beats_restated_cumulative(self):
        # 9개월 누적이 나중에 재작성돼 작아졌어도(55), 그해 분기 보고서의 3개월 값(18·24·21)으로 4Q 를 만든다
        v = {('2024-01-01', '2024-03-31'): 18, ('2024-04-01', '2024-06-30'): 24, ('2024-07-01', '2024-09-30'): 21,
             ('2024-01-01', '2024-09-30'): 55, ('2024-01-01', '2024-12-31'): 95}
        self.assertEqual(fund.quarterize(v)['2024-12-31'], 95 - 18 - 24 - 21)

    def test_year_header_table(self):
        html = """<TABLE><THEAD><TR><TH>구 분</TH><TH>2023</TH><TH>2022</TH></TR></THEAD><TBODY>
        <TR><TD>원재료 및 상품의 사용</TD><TD>5,628</TD><TD>5,288</TD></TR><TR><TD>종업원급여</TD><TD>1,495</TD><TD>1,171</TD></TR>
        <TR><TD>합 계</TD><TD>7,123</TD><TD>6,459</TD></TR></TBODY></TABLE>"""
        t = fund.parse_table(html)
        self.assertEqual(t['cols'], ['2023', '2022'])
        self.assertEqual(len(t['rows']), 3)
        self.assertEqual(fund.key_of('성격별 비용(중단영업 포함) 합계')[0], 'total')

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



class SegmentTest(unittest.TestCase):
    def test_axis_classification(self):
        import fund_xbrl as X
        ops = (X.AX_CONS, X.M_OPSEG)
        self.assertEqual(X.seg_class([ops, (X.AX_SEG, 'e:DS')]), ('seg', 'e:DS'))                 # 삼성전자: 영업부문 + 부문 축
        self.assertEqual(X.seg_class([(X.AX_CONS, 'e:Manufacturing')]), ('seg', 'e:Manufacturing'))   # 한양디지텍: 조정 축에 직접
        self.assertEqual(X.seg_class([(X.AX_CONS, 'ifrs-full:MaterialReconcilingItemsMember')]), ('seg', '__adj__'))
        self.assertEqual(X.seg_class([ops, (X.AX_GEO, 'e:China')]), ('geo*', 'e:China'))            # 지역이 부문인지 나중에 정한다
        self.assertEqual(X.seg_class([(X.AX_PROD, 'e:Memory')]), ('prod', 'e:Memory'))
        self.assertIsNone(X.seg_class([ops]))                                                       # 부문 합계
        self.assertIsNone(X.seg_class([(X.AX_GEO, 'ifrs-full:GeographicalAreasMember')]))            # 축 전체
        self.assertIsNone(X.seg_class([(X.AX_SEG, 'e:A'), (X.AX_GEO, 'e:B')]))                       # 두 축 교차는 안 쓴다

    def test_settle_views(self):
        import fund_xbrl as X
        p = ('C', '2026-01-01', '2026-06-30')
        only_geo = {('geo*', 'rev', '미국', '외국', *p): 10.0, ('geo*', 'rev', '국내', '', *p): 30.0}
        self.assertEqual({k[0] for k in X.settle_views(only_geo)}, {'seg'})                          # 삼양식품: 지역이 곧 부문
        mixed = {('seg', 'rev', 'DS 부문', '보고부문', *p): 100.0, ('geo*', 'rev', '미주', '외국', *p): 40.0, ('geo', 'rev', '미주', '외국', *p): 35.0}
        out = X.settle_views(mixed)
        self.assertEqual(out[('geo', 'rev', '미주', '외국', *p)], 35.0)                               # 표시 없는 값과
        self.assertEqual(out[('geo', 'rev', '미주', 'x|외국', *p)], 40.0)                             # 표시 있는 값은 다른 벌로 따로 둔다

    def test_leaves_only(self):
        import fund_xbrl as X
        p = ('C', 's', 'e')
        raw = {('geo', 'rev', 'x:Foreign', *p): 50.0, ('geo', 'rev', 'x:US', *p): 30.0, ('geo', 'rev', 'x:CN', *p): 20.0, ('geo', 'rev', 'x:KR', *p): 50.0,
               ('geo', 'rev', 'x:Foreign', 'C', 's2', 'e2'): 7.0}
        out = X.leaves_only(raw, {'x:Foreign': {'x:US', 'x:CN'}})
        self.assertNotIn(('geo', 'rev', 'x:Foreign', *p), out)                 # 아래 줄이 있으면 상위는 뺀다
        self.assertIn(('geo', 'rev', 'x:Foreign', 'C', 's2', 'e2'), out)       # 아래 줄이 없는 기간에는 상위가 줄

    def test_members_and_check(self):
        q = {'국내': {'a': 50}, '해외': {'a': 50}, '미국': {'a': 30}, '중국': {'a': 20}, '합계': {'a': 100}, '조정': {'a': -5}}
        self.assertEqual(fund.pick_members(q), ['국내', '미국', '중국'])                              # 해외는 나라들의 합이라 뺀다
        self.assertEqual(fund.pick_members({'국내': {'a': 1}, '해외': {'a': 2}}), ['국내', '해외'])
        self.assertIsNone(fund.seg_check({'A': 60, 'B': 45}, -5, 100))
        self.assertIn('≠', fund.seg_check({'A': 60, 'B': 45}, None, 100))

    def test_merge_similar_names(self):
        vals = {'Harman': {('a', 'b'): 1, ('c', 'd'): 2}, 'Haman': {('c', 'd'): 3, ('e', 'f'): 4}, 'DS 부문': {('a', 'b'): 9}, '미국': {('a', 'b'): 5}, '미주': {('e', 'f'): 6}}
        out = fund.merge_similar(vals, {'Harman': '2025', 'Haman': '2026', 'DS 부문': '2026', '미국': '2025', '미주': '2026'})
        self.assertEqual(out['Haman'], {('a', 'b'): 1, ('c', 'd'): 3, ('e', 'f'): 4})   # 최근 이름이 대표, 겹치면 대표 값
        self.assertNotIn('Harman', out)
        self.assertIn('미국', out)                                                       # 짧고 뜻이 다른 이름은 안 합친다
        self.assertIsNone(fund.seg_check({'A': 40}, None, 100, partial_ok=True))        # 주요 제품만 적은 경우
        self.assertIn('≠', fund.seg_check({'A': 140}, None, 100, partial_ok=True))

    def test_best_subset_when_two_breakdowns_share_a_table(self):
        qs = ['a', 'b', 'c', 'd']
        z = lambda xs: dict(zip(qs, [x * 100 for x in xs]))
        tot = z([100, 110, 121, 133])
        rev = {'상품': z([80, 90, 97, 108]), '제품': z([15, 16, 19, 20]), '기타': z([5, 4, 5, 5]), '재화의 판매': z([94, 105, 114, 126]), '용역의 제공': z([6, 5, 7, 7])}
        self.assertEqual(sorted(fund.best_subset(rev, list(rev), {}, tot, qs)), ['기타', '상품', '제품'])   # 맞는 묶음 중 줄이 많은 쪽
        self.assertEqual(sorted(fund.best_subset(rev, list(rev), {}, tot, qs[:2])), ['기타', '상품', '제품'])    # 분기가 적어도 전부 정확히 맞으면
        loose = {**rev, '상품': z([80.4, 90, 97, 108])}
        self.assertIsNone(fund.best_subset(loose, ['상품', '제품', '기타', '재화의 판매'], {}, tot, qs[:2]))        # 0.1% 넘게 어긋나면 안 고른다
        self.assertIsNone(fund.best_subset({n: {q: 1 for q in qs} for n in 'ABC'}, list('ABC'), {}, tot, qs))

    def test_verdict_over_is_warning_under_is_note(self):
        self.assertEqual(fund.seg_verdict({'A': 60, 'B': 39.5}, None, 100), (None, None))
        w, i = fund.seg_verdict({'A': 60, 'B': 60}, None, 100)
        self.assertIn('>', w)
        self.assertIsNone(i)
        w, i = fund.seg_verdict({'A': 60}, None, 100)                       # 국내 매출이 표시 안 된 분기 등
        self.assertIsNone(w)
        self.assertIn('작음', i)
        w, i = fund.seg_verdict({'A': 60, 'B': 60}, 0.0, 100, has_adj_elsewhere=True)   # 조정이 이 분기만 없음
        self.assertIsNone(w)
        self.assertIn('조정', i)
        self.assertEqual(fund.seg_name('대한민국'), '국내')
        self.assertEqual(fund.pick_members({'A부문': {'q': 1}, 'B부문': {'q': 2}, '중요한 조정사항 전 금액': {'q': 3}}), ['A부문', 'B부문'])

    def test_rename_map_links_names_by_equal_values(self):
        tb = {('s', 'e'): {'r1': {'캡슐 등': 20.0, '원료': 3.0}, 'r2': {'캡슐': 20.0, '원료': 3.0}},
              ('s2', 'e2'): {'r2': {'캡슐': 22.0, '원료': 4.0}}}
        self.assertEqual(fund.rename_map(tb), {'캡슐 등': '캡슐'})

    def test_contribution(self):
        c = dict(fund.contribution({'DS': 150, 'DX': 90}, {'DS': 100, 'DX': 100}))
        self.assertAlmostEqual(c['DS'], 25.0)
        self.assertAlmostEqual(c['DX'], -5.0)
        self.assertAlmostEqual(sum(c.values()), (240 / 200 - 1) * 100)

    def test_mentions(self):
        self.assertEqual(fund.mention_key('DS 부문'), 'DS')
        self.assertEqual(fund.mention_key('제조부문'), '제조')
        self.assertIsNone(fund.mention_key('국내'))
        text = 'DS 부문은 HBM 출하 확대로 분기 최대 실적을 기록했다. 스마트폰 등 세트 수요는 부진했다. ADS 광고는 무관하다고 봤다.'
        got = fund.mentions(text, ['DS 부문', '스마트폰 등', '국내'])
        self.assertEqual([n for n, _ in got], ['DS 부문', '스마트폰 등'])                              # 'ADS' 는 DS 로 잡지 않는다


if __name__ == '__main__':
    unittest.main()
