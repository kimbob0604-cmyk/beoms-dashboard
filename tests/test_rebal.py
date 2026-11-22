import json
import unittest
from pathlib import Path

import build_rebal as R
from collectors import dart as D
from collectors import wisereport as wr


def P(d):
    """{코드: (수량, 금액)} → pdf() 모양"""
    tot = sum(v for _, v in d.values())
    return {c: {'n': c, 'qty': q, 'val': v, 'w': v / tot} for c, (q, v) in d.items()}


class AnchorRatioTest(unittest.TestCase):
    def test_same_free_float_gives_constant_ratio(self):
        T = P({f'A{i}': (100, 10.0 * (i + 1)) for i in range(8)})
        sub = P({f'A{i}': (50, 10.0 * (i + 1)) for i in range(6)} | {'N': (40, 30.0)})   # 같은 유동비율 → 비율 일정
        x, n = R.anchor_ratio(sub, T)
        self.assertEqual(n, 6)
        self.assertAlmostEqual(sub['A0']['w'] / T['A0']['w'], x)

    def test_capped_and_thin_anchors_dropped(self):
        T = P({f'A{i}': (100, 10.0) for i in range(8)})
        sub = P({f'A{i}': (50, 10.0) for i in range(6)} | {'A6': (50, 3.0), 'A7': (5, 10.0)})    # A6 상한, A7 수량 부족
        x, n = R.anchor_ratio(sub, T)
        self.assertEqual(n, 6)

    def test_too_few_anchors(self):
        T = P({f'A{i}': (100, 10.0) for i in range(4)})
        self.assertIsNone(R.anchor_ratio(T, T))


class EstimateTest(unittest.TestCase):
    def test_pdf_estimates_skip_capped_in_combine(self):
        sub = P({'N': (100, 10.0), 'B': (100, 90.0)})
        ests = R.pdf_estimates('N', {'KRX300': (sub, 0.5), '상한': (sub, 0.25)}, {'상한'})
        self.assertEqual(len(ests), 2)
        self.assertAlmostEqual(R.combine(ests), 0.1 / 0.5)               # 상한 지수 값(0.4)은 섞지 않는다
        self.assertIsNone(R.combine([e for e in ests if e[3]]))

    def test_combine_weights_by_quantity(self):
        ests = [('a', 0.010, 10, False), ('b', 0.012, 30, False)]
        self.assertAlmostEqual(R.combine(ests), (0.010 * 10 + 0.012 * 30) / 40)

    def test_calib_total(self):
        T = P({f'A{i}': (100, 1.0 * (i + 1)) for i in range(12)})
        fn = {c: {'sh': 1000, 'ff': 0.5} for c in T}
        px = {c: 2.0 * (i + 1) for i, c in enumerate(T)}               # 유동시총 1000×p×0.5 가 비중에 정비례
        cal = R.calib_total(T, fn, px)
        self.assertAlmostEqual(cal['med_abs'], 0.0)
        self.assertAlmostEqual(cal['T'], 1000 * 2.0 * 0.5 / T['A0']['w'])


class ChooseTest(unittest.TestCase):
    def test_default_fnguide_and_flag_big_gap(self):
        self.assertEqual(R.choose(0.65, 0.66), ('FnGuide', False))
        self.assertEqual(R.choose(0.56, 0.80), ('FnGuide', True))       # 9%p 넘게 다르면 DART 확인
        self.assertEqual(R.choose(0.835, 0.997, {'use': 'PDF', 'why': '정의 차이'}), ('PDF', False))

    def test_missing_side(self):
        self.assertEqual(R.choose(0.7, None), ('FnGuide', False))
        self.assertEqual(R.choose(None, 0.7), ('PDF', False))

    def test_denom_and_adv(self):
        self.assertAlmostEqual(R.denom([0.01, 0.02], [0.005]), 1.025)
        self.assertEqual(R.adv([10.0] * 20), 10.0)
        self.assertIsNone(R.adv([10.0] * 5))


class DartTest(unittest.TestCase):
    """DART 지분으로 유동비율 확인 (숫자는 2026-11 실제 공시에서)"""

    def test_auto_rule(self):
        self.assertEqual(R.dart_auto(-0.001, -0.162), 'PDF')       # 큐리언트: 지분 그대로 → KRX 정의 차이, 6월 값
        self.assertEqual(R.dart_auto(0.115, -0.242), 'FnGuide')    # 에이프릴바이오: 최대주주 쪽 지분 늘어 유동비율 줄어듦
        self.assertIsNone(R.dart_auto(-0.026, -0.098))             # 제이에스링크: 차이와 같은 방향 → 사람이 확인
        self.assertIsNone(R.dart_auto(0.02, -0.10))                # 1~3%p 사이
        self.assertIsNone(R.dart_auto(None, -0.10))

    def test_choose_with_auto(self):
        self.assertEqual(R.choose(0.835, 0.997, None, 'PDF'), ('PDF', False))
        self.assertEqual(R.choose(0.648, 0.746, None, None), ('FnGuide', True))
        self.assertEqual(R.choose(0.648, 0.746, {'use': 'FnGuide', 'why': 'x'}, 'PDF'), ('FnGuide', False))   # 사람이 정한 것이 먼저
        self.assertEqual(R.choose(0.69, 0.65, None, 'PDF'), ('FnGuide', False))                                # 9%p 안쪽은 자동 규칙을 안 씀

    def test_choose_dart_override(self):
        self.assertEqual(R.choose(0.188, None, {'use': 'DART', 'why': '주식교환'}), ('DART', False))   # PDF 가 없어도 사람이 정한 DART
        self.assertEqual(R.choose(None, 0.7, {'use': 'FnGuide', 'why': 'x'}), ('PDF', False))          # 고른 쪽 값이 없으면 무시

    def test_treasury_after(self):
        c = ['5. 취득후 자기주식등의 보유상황', '[', '2026년 10월 23일', '현재]', '주식의 종류', '보통주식',
             '7,409,861', '4.04', '100,083,710,485', '-', '-', '-', '7,409,861', '4.04', '100,083,710,485', '계']
        self.assertEqual(D.parse_treasury_after(c), {'qty': 7409861, 'rt': 0.0404})
        g = ['5. 처분후 자기주식등의 보유상황', '보통주식', '445,056', '2.41', '6,624,214,379', '105,907', '0.57', '5,000,000,000',
             '550,963', '2.99', '11,624,214,379', '계']
        self.assertEqual(D.parse_treasury_after(g)['rt'], 0.0299)                # 직접 + 신탁 합계
        self.assertIsNone(D.parse_treasury_after(['1. 취득예정주식', '보통주식', '100']))

    def test_quarter_periods(self):
        self.assertEqual(R.quarter_periods('2026-04-30', '2026-10-30'),
                         [('2025', '11011', '2025-12-31'), ('2026', '11013', '2026-03-31'), ('2026', '11012', '2026-06-30'), ('2026', '11014', '2026-09-30')])
        self.assertEqual([q for *_, q in R.quarter_periods('2026-10-30', '2027-04-30')], ['2026-09-30', '2026-12-31', '2027-03-31'])

    def test_holder_share(self):
        hy = [{'nm': '계', 'stock_knd': '보통주', 'trmend_posesn_stock_co': '8,520,456', 'trmend_posesn_stock_qota_rt': '26.31', 'stlm_dt': '2026-09-30'},
              {'nm': '계', 'stock_knd': '우선주', 'trmend_posesn_stock_co': '3,608,595', 'trmend_posesn_stock_qota_rt': '11.14', 'stlm_dt': '2026-09-30'}]
        tot = [{'se': '보통주식', 'istc_totqy': '27,558,782', 'tesstk_co': '-'}, {'se': '합계', 'istc_totqy': '32,389,631', 'tesstk_co': '-'}]
        v = D.holder_share(hy, tot)
        self.assertAlmostEqual(v['hold'], 8520456 / 27558782, places=4)    # 보통주 대비 (공시 지분율은 종류주 포함 총수 대비)
        self.assertEqual(v['tsy'], 0.0)
        q = D.holder_share([{'nm': '계', 'stock_knd': '보통주', 'trmend_posesn_stock_co': '16,189,786', 'trmend_posesn_stock_qota_rt': '32.76',
                             'stlm_dt': '2026-03-31'}], [{'se': '합계', 'istc_totqy': '-', 'tesstk_co': '-'}])
        self.assertEqual((q['hold'], q['tsy']), (0.3276, None))              # 분기보고서: 주식 총수 칸이 비면 공시 지분율
        self.assertIsNone(D.holder_share([{'nm': '계', 'stock_knd': '-', 'trmend_posesn_stock_co': '-', 'trmend_posesn_stock_qota_rt': '-'}], []))

    def test_holder_events(self):
        rows = [{'report_nm': '주식등의대량보유상황보고서(약식)', 'rcept_dt': '20261002', 'flr_nm': '국민연금공단', 'rcept_no': '1'},
                {'report_nm': '자기주식취득결과보고서', 'rcept_dt': '20261023', 'flr_nm': '현대지에프홀딩스', 'rcept_no': '2'},
                {'report_nm': '분기보고서 (2026.09)', 'rcept_dt': '20261113', 'flr_nm': 'x', 'rcept_no': '3'},
                {'report_nm': '[첨부정정]주요사항보고서(유상증자결정)', 'rcept_dt': '20260801', 'flr_nm': 'x', 'rcept_no': '4'},
                {'report_nm': '최대주주등소유주식변동신고서', 'rcept_dt': '20261106', 'flr_nm': '삼아알미늄', 'rcept_no': '5'}]
        self.assertEqual([e['no'] for e in D.holder_events(rows)], ['1', '2', '5'])

    def test_view(self):
        ser = [{'d': '2025-12-31', 'hold': 0.77154, 'tsy': 0.0}, {'d': '2026-03-31', 'hold': 0.771, 'tsy': None},
               {'d': '2026-06-30', 'hold': 0.65588, 'tsy': 0.0187}, {'d': '2026-09-30', 'hold': 0.656, 'tsy': None}]
        evs = [{'d': '2026-10-02', 't': '주식등의대량보유상황보고서(약식)', 'f': '국민연금공단', 'no': '1'},
               {'d': '2026-10-23', 't': '자기주식취득결과보고서', 'f': 'a', 'no': '2'},
               {'d': '2026-11-06', 't': '주식소각결정', 'f': 'a', 'no': '3'}]
        v = R.dart_view(ser, evs, ('2026-04-30', '2026-10-30'), 0.188, None)
        self.assertAlmostEqual(v['ff'], 1 - 0.656 - 0.0187, places=4)       # 9월 지분 + 6월 자사주(분기보고서는 비어 이어 씀)
        self.assertEqual((v['ff_d'], v['tsy_d'], v['d_from']), ('2026-09-30', '2026-06-30', '2026-03-31'))
        self.assertAlmostEqual(v['d'], (0.656 + 0.0187) - 0.771, places=4)
        self.assertEqual([(e[3], e[4]) for e in v['ev']], [('2', False), ('3', True)])   # 약식 대량보유 빠짐, 심사기준일 뒤 표시
        self.assertTrue(v['flag'])
        # 분기보고서 뒤 자기주식 취득 결과보고서(구간 안)가 있으면 그 보유 비율을 자사주로
        w = R.dart_view(ser, [{**evs[1], 'tsy': 0.0404}, {**evs[2], 'tsy': 0.01}], ('2026-04-30', '2026-10-30'), 0.188, None)
        self.assertAlmostEqual(w['ff'], 1 - 0.656 - 0.0404, places=4)
        self.assertEqual(w['tsy_d'], '2026-10-23')                              # 11/6 은 심사기준일 뒤라 안 씀
        # 알지노믹스: DART 83% 대 FnGuide 78% 지만 PDF(KRX)도 79% — KRX 도 빼는 몫(보호예수 등)이라 표시 안 함
        self.assertFalse(R.dart_view([{'d': '2026-09-30', 'hold': 0.169, 'tsy': 0.0}], [], ('2026-04-30', '2026-10-30'), 0.78, 0.789)['flag'])
        self.assertIsNone(R.dart_view([None, None], [], ('2026-04-30', '2026-10-30'), 0.7, None))


class EventConfigTest(unittest.TestCase):
    def test_lists_and_overrides(self):
        ev = json.loads((Path(R.__file__).parent / 'rebal_event.json').read_text(encoding='utf-8'))
        self.assertEqual(len(ev['index']['KQ150']['in']), 16)
        self.assertEqual(len(ev['index']['KQ150']['out']), 16)
        self.assertEqual(len(ev['index']['K200']['in']), 11)
        self.assertEqual(len(ev['index']['K200']['out']), 12)
        codes = [c for cfg in ev['index'].values() for c, _ in cfg['in'] + cfg['out']]
        self.assertEqual(len(codes), len(set(codes)))
        new = {c for cfg in ev['index'].values() for c, _ in cfg['in']}
        self.assertTrue(set(ev['overrides']) <= new)
        self.assertTrue(all(v['use'] in ('PDF', 'FnGuide', 'DART') and v['why'] for v in ev['overrides'].values()))
        a, b = ev['ff_window']
        self.assertTrue(a < ev['announced'] and b < ev['announced'] and a < b)


class ParseFloatTest(unittest.TestCase):
    def test_header_cell(self):
        page = '''<th scope="row" class="txt">발행주식수/유동비율</th>
            <td class="num">
                155,485,660주 / 85.40%
            </td>'''
        self.assertEqual(wr.parse_float(page), {'sh': 155485660, 'ff': 0.854})
        self.assertIsNone(wr.parse_float('<td>없음</td>'))


if __name__ == '__main__':
    unittest.main()
