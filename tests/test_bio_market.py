import json
import unittest
from pathlib import Path

import bio_market as bm

CFG = json.loads((Path(__file__).resolve().parent.parent / 'bio_assets.json').read_text(encoding='utf-8'))


class Market(unittest.TestCase):
    def test_base_case_matches_model_peak(self):
        n = 0
        for c in CFG['companies']:
            for a in c.get('assets', []):
                if a.get('market') and a['market'].get('kind') != 'royalty':
                    n += 1
                    self.assertAlmostEqual(bm.peak_of(a['market'], 'base'), a['peak_musd'], delta=0.5, msg=a['id'])
                    pk = [bm.peak_of(a['market'], k) for k in bm.CASES]
                    self.assertTrue(pk[0] < pk[1] < pk[2], a['id'])
        self.assertGreaterEqual(n, 5)

    def test_triggers_have_thresholds_and_collectors(self):
        for c in CFG['companies']:
            for a in c.get('assets', []):
                for t in (a.get('market') or {}).get('triggers', []):
                    self.assertIn(t['collector']['type'], ('ctgov', 'sec', 'revenue', 'manual'), t['id'])
                    self.assertEqual(set(t['th']), set(bm.CASES), t['id'])
                    ev = t.get('evidence')
                    if ev:
                        self.assertTrue(ev.get('url'), f"{t['id']}: 판정에 원문 링크 없음")

    def test_judge_ct(self):
        s = {'status': 'RECRUITING', 'pcd': '2027-05'}
        self.assertEqual(bm.judge_ct(s, '2027-05'), ('live', 'base'))
        self.assertEqual(bm.judge_ct({**s, 'pcd': '2027-12'}, '2027-05'), ('live', 'bear'))
        self.assertEqual(bm.judge_ct({**s, 'pcd': '2027-01'}, '2027-05'), ('live', 'bull'))
        self.assertEqual(bm.judge_ct({**s, 'status': 'TERMINATED'}, '2027-05'), ('done', 'bear'))
        self.assertEqual(bm.judge_ct({**s, 'status': 'COMPLETED'}, None), ('done', 'base'))

    def test_sec_hits_needs_all_terms_and_alternatives(self):
        row = {'auto': {'ir': [{'filed': '2026-12-01', 'title': 'X', 'url': 'u', 'highlights': ['Graves topline met primary endpoint']}], 'events': []}}
        self.assertEqual(len(bm.sec_hits(row, ['Graves', 'top-line|topline'], '2026-11-01')), 1)
        self.assertEqual(bm.sec_hits(row, ['Graves', 'BLA'], '2026-11-01'), [])
        self.assertEqual(bm.sec_hits(row, ['Graves', 'topline'], '2026-12-02'), [])

    def test_tracking(self):
        self.assertEqual(bm.tracking([{'status': 'done', 'scenario': 'bull'}, {'status': 'live', 'scenario': 'bear'}])[0], 'bear')
        self.assertEqual(bm.tracking([{'status': 'done', 'scenario': 'bull'}])[0], 'bull')
        self.assertEqual(bm.tracking([{'status': 'wait'}]), ('base', 0))


if __name__ == '__main__':
    unittest.main()
