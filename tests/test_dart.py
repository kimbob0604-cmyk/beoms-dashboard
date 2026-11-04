import json
import unittest
from pathlib import Path

import build_dart as B
from collectors import dart as D

CELLS = json.loads((Path(__file__).parent / 'fixtures' / 'dart_cells.json').read_text(encoding='utf-8'))


class KindTest(unittest.TestCase):
    def test_kind_of(self):
        self.assertEqual(D.kind_of('연결재무제표기준영업(잠정)실적(공정공시)'), 'earn')
        self.assertEqual(D.kind_of('[기재정정]단일판매ㆍ공급계약체결(자율공시)'), 'contract')
        self.assertEqual(D.kind_of('주요사항보고서(전환사채권발행결정)'), 'cb')
        self.assertEqual(D.kind_of('기업설명회(IR)개최(안내공시)'), 'ir')
        self.assertIsNone(D.kind_of('최대주주등소유주식변동신고서(최대주주변경시)'))
        self.assertIsNone(D.kind_of('전환사채(해외전환사채포함)발행후만기전사채취득'))
        self.assertIsNone(D.kind_of('[첨부정정]주요사항보고서(유상증자결정)'))


class ParseTest(unittest.TestCase):
    def test_contract_both_forms(self):
        a = D.parse('contract', CELLS['contract_kospi'])
        self.assertEqual((a['name'], a['amt'], a['pct']), ('용인 Y1 Ph-2 MCC/MCP 설치공사', 8849800000, 23.18))
        self.assertEqual(a['party'], '에스케이하이닉스(주)')
        b = D.parse('contract', CELLS['contract_kosdaq'])
        self.assertEqual(b['name'], '호남고속철도 2단계 고막원 무안공항간 전차선로 신설공사')
        self.assertEqual((b['amt'], b['party'], b['end']), (2824081600, '(주)삼원전력', '2029-01-15'))

    def test_earn_in_eok(self):
        e = D.parse('earn', CELLS['earn'])
        self.assertEqual(e['period'], '2026년 3분기')
        self.assertEqual(e['rows']['op']['v'], -263.1)      # -26,310 백만원
        self.assertEqual(e['rows']['cnp']['v'], -265.4)

    def test_cb(self):
        x = D.parse('cb', CELLS['cb'])
        self.assertEqual((x['amt'], x['price'], x['floor'], x['how']), (29200000000, 48061, 33643, '사모'))
        self.assertEqual((x['from'], x['to']), ('2027-11-12', '2031-10-12'))
        self.assertIn('중소기업은행', x['investors'])
        self.assertNotIn('600,000,000', x['investors'])

    def test_holder(self):
        x = D.parse('holder', CELLS['holder'])
        self.assertEqual((x['after'], x['after_pct'], x['before_pct']), ('호반건설 외 3인', 20.69, 20.58))


class SurpriseTest(unittest.TestCase):
    def rows(self, sales, op, np):
        return {'basis': '연결', 'rows': {'sales': {'v': sales}, 'op': {'v': op}, 'np': {'v': np}}}

    def test_tags(self):
        cns = {'sales': 1000, 'op': 100, 'np': 80, 'cnp': None}
        self.assertEqual(B.surprise(self.rows(1000, 111, 80), cns)['tag'], '서프')
        self.assertEqual(B.surprise(self.rows(1000, 89, 80), cns)['tag'], '쇼크')
        self.assertIsNone(B.surprise(self.rows(1000, 105, 80), cns)['tag'])
        self.assertEqual(B.surprise(self.rows(1000, -5, 80), cns)['tag'], '쇼크')               # 적자전환
        self.assertEqual(B.surprise(self.rows(1000, 5, 80), {**cns, 'op': -10})['tag'], '서프')  # 흑자전환

    def test_loss_diff_uses_abs(self):
        s = B.surprise(self.rows(691, -263, -140), {'sales': 764, 'op': -259, 'np': -319, 'cnp': None})
        self.assertAlmostEqual(s['d']['op'], -0.0154, places=3)   # 손실 1.5% 확대
        self.assertIsNone(s['tag'])

    def test_separate_vs_consolidated_skipped(self):
        x = {'basis': '별도', 'rows': {'sales': {'v': 8420}, 'op': {'v': 521}, 'np': {'v': 100}}}
        self.assertEqual(B.surprise(x, {'sales': 199678, 'op': 17579, 'np': 8100, 'cnp': None}), {'mismatch': True})


if __name__ == '__main__':
    unittest.main()
