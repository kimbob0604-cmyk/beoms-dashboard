import unittest

import collect_semi as cs


class CalQTest(unittest.TestCase):
    def test_calendar_quarter_of_odd_fiscal_ends(self):
        self.assertEqual(cs.cal_q('2026-09-30'), '2026Q3')
        self.assertEqual(cs.cal_q('2026-10-26'), '2026Q3')     # 엔비디아 3분기
        self.assertEqual(cs.cal_q('2026-08-27'), '2026Q3')     # 마이크론 회계 4분기
        self.assertEqual(cs.cal_q('2026-01-25'), '2025Q4')
        self.assertEqual(cs.cal_q('2026-03-31'), '2026Q1')


class QuarterizeTest(unittest.TestCase):
    def test_cumulative_cash_flow_to_quarters(self):
        # 10-Q 현금흐름은 회계연도 누적: 3·6·9개월, 10-K 는 12개월 → 4분기 = 12개월 − 9개월
        f = {('2025-07-01', '2025-09-30'): 10, ('2025-07-01', '2025-12-31'): 25,
             ('2025-07-01', '2026-03-31'): 45, ('2025-07-01', '2026-06-30'): 70}
        self.assertEqual(cs.quarterize(f), {'2025-09-30': 10, '2025-12-31': 15, '2026-03-31': 20, '2026-06-30': 25})

    def test_three_month_value_wins(self):
        f = {('2026-04-01', '2026-06-30'): 7, ('2026-01-01', '2026-03-31'): 5, ('2026-01-01', '2026-06-30'): 13}
        self.assertEqual(cs.quarterize(f)['2026-06-30'], 7)


class SecSeriesTest(unittest.TestCase):
    def test_latest_tag_first_and_capex_positive(self):
        def pt(st, en, v, form='10-Q', filed='2026-10-30'):
            return {'start': st, 'end': en, 'val': v, 'form': form, 'filed': filed}
        j = {'facts': {'us-gaap': {
            'Revenues': {'units': {'USD': [pt('2022-01-01', '2022-03-31', 1e9)]}},
            'RevenueFromContractWithCustomerExcludingAssessedTax': {'units': {'USD': [pt('2026-07-01', '2026-09-30', 5e9)]}},
            'PaymentsToAcquirePropertyPlantAndEquipment': {'units': {'USD': [pt('2026-01-01', '2026-03-31', 2e9), pt('2026-01-01', '2026-06-30', 5e9)]}},
        }}}
        s = cs.sec_series(j)
        self.assertEqual(s['rev'], {'2026-09-30': 5000.0, '2022-03-31': 1000.0})   # 끊긴 옛 이름은 빈 기간만 채운다
        self.assertEqual(s['capex'], {'2026-03-31': 2000.0, '2026-06-30': 3000.0})



class AiNewsTest(unittest.TestCase):
    def test_rss_items_and_new_product_names(self):
        import re
        import collect_ai_news as an
        xml = ('<rss><channel><item><title><![CDATA[NVIDIA Announces Rubin HPC GPU]]></title><link>https://x/1</link>'
               '<pubDate>Mon, 16 Nov 2026 17:00:00 GMT</pubDate><description>HBM4</description></item>'
               '<item><title>Vera Rubin NVL72 MLPerf</title><link>https://x/2</link><pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>')
        it = an.items(xml)
        self.assertEqual([(t, l, d) for t, l, d, _ in it], [('NVIDIA Announces Rubin HPC GPU', 'https://x/1', '2026-11-16'),
                                                              ('Vera Rubin NVL72 MLPerf', 'https://x/2', '2026-11-16')])
        known = an.known_text({'racks': [{'id': 'Vera Rubin NVL72', 'gpu': {'name': 'Rubin (R200)'}, 'cpu': {'name': 'Vera'}}], 'chips': []})
        names = lambda t: sorted({m.group(0).strip() for m in re.finditer(an.FAMILY, t, re.I)})
        new = lambda t: [x for x in names(t) if x.lower().replace(' ', '') not in known]
        self.assertEqual(new(it[0][0]), ['Rubin HPC'])     # 규격표에 없는 새 제품
        self.assertEqual(new(it[1][0]), [])               # 이미 있는 제품

class DedupeFixedTest(unittest.TestCase):
    def test_only_corrections_replace(self):
        import build_semi as b
        key = lambda v: (v['c'], v['p'], v['s'])
        rows = [{'c': 'A', 'p': 'X', 's': '2026-08-07', 'amt': 35, 'fx': False},
                {'c': 'A', 'p': 'X', 's': '2026-08-07', 'amt': 19, 'fx': False},     # 같은 날 별개 공시 — 둘 다 남는다
                {'c': 'A', 'p': 'X', 's': '2026-08-07', 'amt': 20, 'fx': True}]      # 정정 — 바로 앞(19)을 대신한다
        self.assertEqual([r['amt'] for r in b.dedupe_fixed(rows, key)], [35, 20])

    def test_customer_groups(self):
        import build_semi as b
        self.assertEqual(b.cust_of('에스케이하이닉스 주식회사'), 'SK하이닉스')
        self.assertEqual(b.cust_of('Samsung Austin Semiconductor, LLC.'), '삼성전자')
        self.assertEqual(b.cust_of('Micron Memory Taiwan Co.,Ltd.'), '마이크론')
        self.assertEqual(b.cust_of('해외 Nand Flash Memory 제조사'), '해외 반도체(비공개)')
        self.assertEqual(b.cust_of(''), '미상')

class CorrectionBodyTest(unittest.TestCase):
    def test_correction_reads_body_not_change_table(self):
        from collectors import dart
        cells = ['x', '회사/단일판매ㆍ공급계약체결', '정정신고(보고)', '정정일자', '2025-12-30', '4. 정정사항', '정정항목', '정정전', '정정후',
                 '2. 계약내역', '계약금액(원)', '매출액대비(%)', '-', '386,146,954,369', '3. 계약상대', '-', '삼성SDI',
                 '단일판매ㆍ공급계약 체결', '1. 판매ㆍ공급계약 구분', '기타', '- 체결계약명', '일렉포일 장기공급계약', '2. 계약내역',
                 '계약금액(원)', '386,146,954,369', '최근매출액(원)', '550,214,159,127', '매출액대비(%)', '70.18', '3. 계약상대', '삼성SDI',
                 '4. 판매ㆍ공급지역', '국내', '5. 계약기간', '시작일', '2020-06-24', '종료일', '2025-12-31']
        x = dart.parse('contract', cells)
        self.assertEqual((x['amt'], x['pct'], x['party'], x['end']), (386146954369.0, 70.18, '삼성SDI', '2025-12-31'))


if __name__ == '__main__':
    unittest.main()
