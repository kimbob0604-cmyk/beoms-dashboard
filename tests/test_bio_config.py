"""bio_assets.json 검증: 종목을 늘려도 원문 근거 없는 숫자가 들어가지 않게."""
import json
import re
import unittest
from pathlib import Path

CFG = json.loads((Path(__file__).resolve().parent.parent / 'bio_assets.json').read_text(encoding='utf-8'))
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class Config(unittest.TestCase):
    def test_verified_facts_have_source_link(self):
        for c in CFG['companies']:
            for f in c.get('facts', []):
                self.assertTrue(f.get('src'), f"{c['ticker']}: 출처 없는 사실 {f['text'][:30]}")
                if f.get('verified'):
                    self.assertTrue(f.get('url'), f"{c['ticker']}: 원문 확인이라면서 링크 없음 {f['text'][:30]}")

    def test_overrides_have_notes(self):
        for c in CFG['companies']:
            ov = c.get('overrides', {})
            for k in ov:
                if k.endswith('_musd') or k == 'shares_m':
                    base = k.replace('annual_', '').replace('other_liab', 'other').replace('_musd', '').replace('_m', '')
                    notes = [n for n in ov if n.endswith('_note') and n.startswith(base.split('_')[0])]
                    self.assertTrue(notes, f"{c['ticker']}: {k} 에 근거 메모 없음")

    def test_assets_have_basis_and_assumptions(self):
        for c in CFG['companies']:
            for a in c.get('assets', []):
                self.assertTrue(a.get('basis'), f"{c['ticker']} {a['id']}: 피크·금액 근거(basis) 없음")
                self.assertTrue(a.get('assumptions'), f"{c['ticker']} {a['id']}: 가정 설명 없음")
                for s in a['stages']:
                    self.assertTrue(0 < s['pos'] <= 1, a['id'])
                    if s.get('date'):
                        self.assertRegex(s['date'], DATE)

    def test_catalyst_dates(self):
        for c in CFG['companies']:
            for k in c.get('catalysts', []):
                self.assertRegex(k['date'], DATE, c['ticker'])

    def test_unique_ids(self):
        tickers = [c['ticker'] for c in CFG['companies']]
        self.assertEqual(len(tickers), len(set(tickers)))
        ids = [a['id'] for c in CFG['companies'] for a in c.get('assets', [])]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == '__main__':
    unittest.main()
