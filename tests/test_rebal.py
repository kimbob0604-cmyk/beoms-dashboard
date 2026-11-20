import json
import unittest
from pathlib import Path

import build_rebal as R
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
        self.assertTrue(all(v['use'] in ('PDF', 'FnGuide') and v['why'] for v in ev['overrides'].values()))


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
