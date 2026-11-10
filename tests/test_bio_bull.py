import json
import unittest
from pathlib import Path

import build_bio as bb

CFG = json.loads((Path(__file__).resolve().parent.parent / 'bio_assets.json').read_text(encoding='utf-8'))
MK = {'price': 10.0, 'shares': 100.0, 'cash': 50.0, 'debt': 0.0, 'op_cf': -20.0}
G = {**CFG['global'], 'conv': 1.0}


def co():
    return {'kind': 'pipeline', 'burn_years': 1.0, 'assets': [
        {'id': 'a', 'name': 'A', 'indication': '', 'stage': '2상', 'method': 'rnpv', 'peak_musd': 1000, 'margin': 0.4,
         'ramp_years': 4, 'exclusivity_years': 10, 'launch_in': 4.0,
         'stages': [{'name': '2상', 't': 1.0, 'pos': 0.5, 'x': 50}, {'name': '허가', 't': 4.0, 'pos': 0.9, 'x': 0}]}],
        'bull_steps': [{'label': 'peak', 'ops': [{'op': 'mult_peak', 'factor': 1.5, 'ids': None}]},
                       {'label': 'pos', 'ops': [{'op': 'stage_pos', 'id': 'a', 'idx': 0, 'value': 0.7}]}]}


class BullBridge(unittest.TestCase):
    def test_steps_accumulate_and_do_not_mutate_config(self):
        c = co()
        base = bb.value_company(c, MK, G, 0.04, CFG['scenarios']['base'])['per_share']
        r = bb.bull_bridge(c, MK, G, 0.04, CFG, base, 40.0)
        self.assertEqual(c['assets'][0]['peak_musd'], 1000)          # 원본 그대로
        self.assertEqual(c['assets'][0]['stages'][0]['pos'], 0.5)
        self.assertEqual(G['wacc'], CFG['global']['wacc'])
        self.assertAlmostEqual(r['base'] + sum(s['delta'] for s in r['steps']), r['bull'], places=9)
        self.assertTrue(all(s['delta'] > 0 for s in r['steps']))
        self.assertAlmostEqual(r['gap'], 40.0 - r['bull'], places=9)

    def test_implied_scale_hits_target(self):
        c = co()
        k = bb.implied_rev_scale(c, MK, G, 0.04, 30.0)
        ps = bb.value_company(c, MK, G, 0.04, {'pos_mult': 1.0, 'peak_mult': k, 'growth_mult': 1.0, 'rev_mult': k})['per_share']
        self.assertAlmostEqual(ps, 30.0, places=4)

    def test_add_asset_and_set_path(self):
        c, g = co(), dict(G)
        c['commercial'] = {'years': 15}
        bb.apply_op(c, g, {'op': 'set', 'path': 'commercial.years', 'value': 20})
        bb.apply_op(c, g, {'op': 'global', 'key': 'wacc', 'value': 0.09})
        bb.apply_op(c, g, {'op': 'add_asset', 'asset': {'id': 'b'}})
        self.assertEqual((c['commercial']['years'], g['wacc'], c['assets'][-1]['id']), (20, 0.09, 'b'))

    def test_config_steps_reference_real_assets(self):
        for c in CFG['companies']:
            ids = {a['id'] for a in c.get('assets', [])}
            for st in c.get('bull_steps', []):
                for op in st['ops']:
                    if op['op'] == 'add_asset':
                        ids.add(op['asset']['id'])
                    if op['op'] == 'stage_pos':
                        self.assertIn(op['id'], ids, c['ticker'])
                    if op['op'] == 'mult_peak' and op.get('ids'):
                        self.assertTrue(set(op['ids']) <= ids, c['ticker'])
                self.assertTrue(st.get('src'), f"{c['ticker']} {st['label']}: 근거 없음")


if __name__ == '__main__':
    unittest.main()
