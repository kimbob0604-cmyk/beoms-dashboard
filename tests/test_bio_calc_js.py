"""화면 계산 엔진(public/js/bio_calc.js)이 Python 계산과 같은 값을 내는지 node 로 확인한다.
public/data/bio.json 이 있어야 돌고, node 가 없으면 건너뛴다."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'public' / 'data' / 'bio.json'
JS = '''
const C = require(process.argv[1] + '/public/js/bio_calc.js');
const d = require(process.argv[1] + '/public/data/bio.json');
const out = [];
for (const c of d.companies) for (const m of c.markets || []) {
  if (!m.calc) continue;
  if (m.cases) for (const k of C.CASES) out.push([c.ticker, m.id, k, C.compute(m, k, {}).per_share, m.cases[k].per_share]);
  else out.push([c.ticker, m.id, 'base', C.compute(m, 'base', {}).per_share, c.valuation ? c.valuation.per_share : null]);
}
console.log(JSON.stringify(out));
'''


@unittest.skipUnless(shutil.which('node') and DATA.exists(), 'node 또는 bio.json 없음')
class CalcJs(unittest.TestCase):
    def test_js_matches_python(self):
        r = subprocess.run(['node', '-e', JS, str(ROOT)], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertGreater(len(rows), 30)
        for t, mid, k, js, py in rows:
            if py is None:
                continue
            self.assertAlmostEqual(js, py, delta=max(1e-6, abs(py) * 1e-6), msg=f'{t} {mid} {k}')

    def test_trigger_choice_moves_value(self):
        d = json.loads(DATA.read_text(encoding='utf-8'))
        m = next(m for c in d['companies'] if c['ticker'] == 'AXSM' for m in c['markets'] if m['id'] == 'commercial')
        js = '''
const C = require(process.argv[1] + '/public/js/bio_calc.js');
const m = JSON.parse(process.argv[2]);
console.log(JSON.stringify([C.compute(m, 'base', {}).per_share, C.compute(m, 'base', {'ax-p4': 'bear'}).per_share, C.compute(m, 'base', {'ax-trx': 'bull'}).per_share]));
'''
        r = subprocess.run(['node', '-e', js, str(ROOT), json.dumps(m)], capture_output=True, text=True, timeout=60)
        base, loe_bear, trx_bull = json.loads(r.stdout)
        self.assertLess(loe_bear, base)      # 조기 제네릭 → 낮아짐
        self.assertGreater(trx_bull, base)   # 처방 Bull → 침투율 Bull 값 → 높아짐


if __name__ == '__main__':
    unittest.main()
