import unittest

import build_naver as B
from collectors import kis


def kis_row(d, **kw):
    """KIS output2 한 줄 (문자열 값). 2026-11-11 삼성전자 통합 응답에서 세부 대금만 옮김"""
    base = {'stck_bsop_date': d, 'acml_tr_pbmn': '3290131669961', 'frgn_ntby_tr_pbmn': '742000', 'prsn_ntby_tr_pbmn': '-620000',
            'orgn_ntby_tr_pbmn': '-137700', 'scrt_ntby_tr_pbmn': '-181597', 'ivtr_ntby_tr_pbmn': '-9150', 'pe_fund_ntby_tr_pbmn': '26574',
            'bank_ntby_tr_pbmn': '-3514', 'insu_ntby_tr_pbmn': '8173', 'mrbn_ntby_tr_pbmn': '-608', 'fund_ntby_tr_pbmn': '29171',
            'etc_corp_ntby_tr_pbmn': '8049', 'etc_orgt_ntby_tr_pbmn': '0'}
    base.update(kw)
    return base


class ParseTest(unittest.TestCase):
    def test_parse_fields_and_date(self):
        rows = kis.parse_investor('005930', [kis_row('20261111')])
        r = rows[0]
        self.assertEqual(r['date'], '2026-11-11')
        self.assertEqual(r['code'], '005930')
        self.assertEqual(r['sec'], -181597)
        self.assertEqual(r['pension'], 29171)
        self.assertEqual(r['etcfin'], -608)
        self.assertEqual(set(kis.FIELDS) - set(r), set())

    def test_skips_no_trade_days(self):
        rows = kis.parse_investor('005930', [kis_row('20261111'), kis_row('20261110', acml_tr_pbmn='0'), {'stck_bsop_date': ''}])
        self.assertEqual([r['date'] for r in rows], ['2026-11-11'])


class DetailTest(unittest.TestCase):
    def rows(self, n):
        return kis.parse_investor('005930', [kis_row(f'202611{30 - i:02d}') for i in range(n)])

    def test_summarize_periods_and_streak(self):
        out = B.summarize_detail(self.rows(5))
        self.assertEqual(out['sc1'], -1816.0)          # 백만원 → 억원
        self.assertEqual(out['sc5'], round(-181597 * 5 / 100, 1))
        self.assertIsNone(out['sc20'])                 # 20거래일이 안 되면 비운다
        self.assertEqual(out['scs'], -5)
        self.assertEqual(out['pns'], 5)

    def test_detail_table_rows(self):
        t = {r[0]: r[1:] for r in B.detail_table(self.rows(20))}
        self.assertEqual(list(t)[:3], ['f', 'i', 'o'])
        self.assertNotIn('nx', t)
        self.assertIn('gv', t)
        self.assertEqual(t['pn'][0], 291.7)
        self.assertEqual(t['pn'][2], round(29171 * 20 / 100, 1))
        self.assertIsNone(t['pn'][3])


if __name__ == '__main__':
    unittest.main()
