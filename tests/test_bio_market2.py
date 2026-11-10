import json
import unittest
from pathlib import Path

import bio_market as bm

CFG = json.loads((Path(__file__).resolve().parent.parent / 'bio_assets.json').read_text(encoding='utf-8'))
G = {**CFG['global'], 'conv': 1.0}


def company(t):
    return next(c for c in CFG['companies'] if c['ticker'] == t)


class RoyaltyAndCommercial(unittest.TestCase):
    def test_royalty_base_equals_partner_base_times_rate(self):
        imvt = {a['id']: a for a in company('IMVT')['assets']}
        for a in company('009420')['assets']:
            m = a.get('market')
            if m and m.get('kind') == 'royalty':
                partner = sum(bm.peak_of(imvt[x]['market'], 'base') for x in m['links'])
                self.assertAlmostEqual(partner * m['rate'], a['peak_musd'], delta=0.5, msg=a['id'])

    def test_solve_growth_hits_target_peak(self):
        co = company('LQDA')
        for target in (1042.0, 1560.8, 2405.0):
            gm = bm.solve_growth(co, G, target)
            self.assertAlmostEqual(bm._dcf_peak(co, G, gm), target, delta=0.5)

    def test_commercial_cases_order(self):
        for t in ('LQDA', 'AXSM'):
            m = company(t)['commercial']['market']
            self.assertEqual(m['cases']['base']['pen'], 'model')
            self.assertLess(m['cases']['bear']['pen'], m['cases']['bull']['pen'])
            self.assertTrue(m['current']['url'])

    def test_qgrowth_judgement(self):
        trig = {'id': 'x', 'name': 'q', 'th': {}, 'collector': {'type': 'qgrowth', 'base_annual': 0.2}}
        row = lambda a, b: {'fin': {'quarters': [{'end': '2026-03-31', 'label': 'Q1', 'revenue': a}, {'end': '2026-06-30', 'label': 'Q2', 'revenue': b}]}}
        self.assertEqual(bm.collect(trig, row(100, 95), {}, {}, '2026-11-10')['scenario'], 'bear')
        self.assertEqual(bm.collect(trig, row(100, 104), {}, {}, '2026-11-10')['scenario'], 'base')
        self.assertEqual(bm.collect(trig, row(100, 110), {}, {}, '2026-11-10')['scenario'], 'bull')


if __name__ == '__main__':
    unittest.main()
