import unittest

import earn

NEW = """2026.11.12 17:51:31
기업명: 나노신소재(시가총액: 9,197억) A121600
보고서명: 분기보고서 (2026.09)

잠정실적 : N

매출액 : 424억(예상치 : 377억, +12.5%)
영업익 : 66억(예상치 : 46억, +43.8%)
순이익 : 19억(예상치 : -)

**최근 실적 추이**
(기간/ 매출/ 영업익/ 순익)
2026.3Q 424억/ 66억/ 19억
2026.2Q 365억/ 53억/ 60억

공시링크: https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261112000741
"""

OLD = """20230731 15:31:03
기업명: 하츠(시가총액: 639억)
보고서명: 영업(잠정)실적(공정공시)

매출: 104억(예상치: 0억)
영업익: 17억(예상치: 20억)
순익: 16억(예상치: 0억)

** 최근 실적 추이 **
2023.2Q  104억 / 17억 / 16억

공시링크: https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230731900340
회사정보: https://finance.naver.com/item/main.nhn?code=066130
"""


class ParseTest(unittest.TestCase):
    def test_new_format(self):
        p = earn.parse_post(NEW)
        self.assertEqual(p['ts'], '2026-11-12 17:51:31')
        self.assertEqual((p['code'], p['name'], p['mcap']), ('121600', '나노신소재', 9197))
        self.assertEqual((p['s'], p['se'], p['o'], p['oe'], p['n'], p['ne']), (424, 377, 66, 46, 19, None))
        self.assertEqual((p['prelim'], p['period'], p['rcp']), ('N', '2026Q3', '20261112000741'))
        self.assertTrue(earn.first_release(p))

    def test_old_format_zero_estimate_is_none(self):
        p = earn.parse_post(OLD)
        self.assertEqual(p['ts'], '2023-07-31 15:31:03')
        self.assertEqual(p['code'], '066130')          # 네이버 링크에서
        self.assertEqual((p['s'], p['se'], p['oe']), (104, None, 20))
        self.assertTrue(earn.first_release(p))

    def test_amounts(self):
        self.assertEqual(earn.amount('4조 9,653억'), 49653)
        self.assertEqual(earn.amount('-42억'), -42)
        self.assertEqual(earn.amount('2조'), 20000)
        self.assertIsNone(earn.amount('-'))

    def test_trillion_rows_and_all_zero_dropped(self):
        t = NEW.replace('매출액 : 424억', '매출액 : 86조 1,000억')
        self.assertEqual(earn.parse_post(t)['s'], 861000)
        z = NEW.replace('424억(', '0억(').replace('66억(', '0억(').replace('19억(', '0억(')
        self.assertIsNone(earn.parse_post(z))

    def test_repeat_and_correction_not_first(self):
        self.assertFalse(earn.first_release({'report': '분기보고서 (2026.09)', 'prelim': 'Y'}))
        self.assertFalse(earn.first_release({'report': '[기재정정]연결재무제표기준영업(잠정)실적(공정공시)'}))
        self.assertIsNone(earn.first_release({'report': '분기보고서 (2023.06)', 'prelim': None}))


class JudgeTest(unittest.TestCase):
    def test_tags_and_cases(self):
        self.assertEqual(earn.tag(424, 377, earn.SALES_T), 'beat')
        self.assertEqual(earn.tag(100, 103, earn.SALES_T), 'inline')
        self.assertEqual(earn.tag(5, -10, earn.OP_T), 'beat')       # 적자 예상 → 흑자
        self.assertEqual(earn.tag(-1, 10, earn.OP_T), 'miss')
        self.assertEqual(earn.case_of('beat', 'beat'), 'both')
        self.assertEqual(earn.case_of('miss', 'beat'), 'op')
        self.assertEqual(earn.case_of('beat', 'inline'), 'sales')
        self.assertEqual(earn.case_of('beat', 'miss'), 'miss')
        self.assertEqual(earn.case_of('inline', None), 'inline')
        self.assertIsNone(earn.case_of(None, None))

    def test_sessions_and_reaction_day(self):
        days = ['2026-11-06', '2026-11-09', '2026-11-10']
        self.assertEqual(earn.reaction_day('2026-11-06 08:10:00', days), ('2026-11-06', '장전'))
        self.assertEqual(earn.reaction_day('2026-11-06 13:00:00', days), ('2026-11-06', '장중'))
        self.assertEqual(earn.reaction_day('2026-11-06 15:25:00', days), ('2026-11-09', '장후'))
        self.assertEqual(earn.reaction_day('2026-11-07 10:00:00', days), ('2026-11-09', '장전'))   # 토요일


class ReactionTest(unittest.TestCase):
    day0 = [['0850', 98], ['0900', 100], ['1029', 100], ['1030', 101], ['1035', 105], ['1100', 110], ['1530', 108], ['1600', 109], ['1959', 112]]
    day1 = [['0900', 115], ['1530', 120]]

    def test_intraday(self):
        r = earn.minute_reaction('2026-11-06 10:30:12', '장중', self.day0, [], None)
        self.assertEqual(r['base'], 100)                        # 발표 직전(10:29) 체결가
        self.assertAlmostEqual(r['m5'], 0.05)
        self.assertAlmostEqual(r['m30'], 0.10)
        self.assertAlmostEqual(r['close'], 0.08)

    def test_after_close(self):
        r = earn.minute_reaction('2026-11-06 15:45:00', '장후', self.day0, self.day1, None)
        self.assertEqual(r['base'], 108)
        self.assertAlmostEqual(r['nxt'], 112 / 108 - 1)
        self.assertAlmostEqual(r['open'], 115 / 108 - 1)
        self.assertAlmostEqual(r['close'], 120 / 108 - 1)

    def test_pre_open(self):
        r = earn.minute_reaction('2026-11-06 07:50:00', '장전', self.day0, [], 96)
        self.assertAlmostEqual(r['nxt'], 98 / 96 - 1)
        self.assertAlmostEqual(r['open'], 100 / 96 - 1)

    def test_daily(self):
        days = ['d0', 'd1', 'd2']
        adj = {'d0': 100, 'd1': 110, 'd2': 121}
        r = earn.daily_reaction(adj, {'d1': 105}, {'d0': 100}, {'d0': 10, 'd1': 10.1, 'd2': 10.2}, days, 'd1')
        self.assertAlmostEqual(r['gap'], 0.05)
        self.assertAlmostEqual(r['d0'], 0.10)
        self.assertAlmostEqual(r['x0'], 0.10 - 0.01)
        self.assertAlmostEqual(r['d1'], 0.21)
        self.assertIsNone(r['d5'])

    def test_active_trims_idle_minutes(self):
        bars = [['0800', 10, 0], ['0900', 10, 5], ['1530', 11, 3], ['1800', 11, 0]]
        self.assertEqual(earn.active(bars), bars[1:3])

    def test_summarize(self):
        s = earn.summarize([0.1, -0.05, 0.02, None, 2.0])
        self.assertEqual(s['n'], 4)
        self.assertEqual(s['up'], 75)
        self.assertEqual(s['avg'], round((0.1 - 0.05 + 0.02 + 0.5) / 4 * 100, 2))


if __name__ == '__main__':
    unittest.main()
