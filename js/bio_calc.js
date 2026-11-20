/* 바이오 탭: 트리거 결과를 눌러 다시 계산하는 엔진. bio_valuation.py · build_bio.value_asset 과 같은 계산식.
   tests/test_bio_calc_js.py 가 node 로 돌려 Python 값과 맞는지 확인한다. */
(function (root) {
  'use strict';
  const CASES = ['bear', 'base', 'bull'];

  // 파이썬 round (반올림 짝수) 와 같게
  function pyRound(x) {
    const f = Math.floor(x), d = x - f;
    if (Math.abs(d - 0.5) < 1e-12) return f % 2 === 0 ? f : f + 1;
    return Math.round(x);
  }

  function launchValue(peak, margin, tax, wacc, launchIn, ramp, excl) {
    let pv = 0;
    for (let k = 0; k < Math.trunc(excl); k++) {
      const sales = peak * Math.min(1, (k + 1) / ramp);
      pv += sales * margin * (1 - tax) / Math.pow(1 + wacc, launchIn + k + 1);
    }
    return pv;
  }

  function applyGroup(cont, group) {
    for (let i = group.length - 1; i >= 0; i--) cont = group[i].pos * Math.max(cont - group[i].x, 0);
    return cont;
  }

  function optionValue(v0, sigma, rf, stages, dt = 0.25) {
    const sorted = [...stages].sort((a, b) => a.t - b.t);
    const n = Math.max(1, Math.trunc(pyRound(Math.max(...stages.map(s => s.t)) / dt)));
    const at = {};
    for (const s of sorted) (at[Math.trunc(pyRound(s.t / dt))] = at[Math.trunc(pyRound(s.t / dt))] || []).push(s);
    const growth = Math.pow(1 + rf, dt), u = Math.exp(sigma * Math.sqrt(dt)), d = 1 / u, p = (growth - d) / (u - d);
    let vals = [];
    for (let j = 0; j <= n; j++) vals.push(v0 * Math.pow(u, j) * Math.pow(d, n - j));
    if (at[n]) vals = vals.map(v => applyGroup(v, at[n]));
    for (let t = n - 1; t >= 0; t--) {
      const nv = [];
      for (let j = 0; j <= t; j++) nv.push((p * vals[j + 1] + (1 - p) * vals[j]) / growth);
      vals = at[t] ? nv.map(v => applyGroup(v, at[t])) : nv;
    }
    return vals[0];
  }

  function rnpvTree(v0, rf, stages) {
    const o = [...stages].sort((a, b) => a.t - b.t);
    let cont = v0;
    for (let i = o.length - 1; i >= 0; i--) {
      const pvx = o[i].x / Math.pow(1 + rf, o[i].t);
      cont = o[i].pos * Math.max(cont - pvx, 0);
    }
    return cont;
  }

  function dcf(D, tax, wacc, gm, loe) {
    let rev = D.run_rate, pv = 0, peak = 0;
    const L = loe != null ? loe : D.loe;
    for (let y = 1; y <= D.years; y++) {
      const g = y >= L ? -D.erosion : D.growth[Math.min(y - 1, D.growth.length - 1)] * gm;
      rev *= 1 + g;
      const m = D.margin_now + (D.margin_target - D.margin_now) * Math.min(1, y / Math.max(1, D.margin_years));
      pv += rev * m * (1 - tax) / Math.pow(1 + wacc, y - 0.5);
      peak = Math.max(peak, rev);
    }
    return { pv, peak };
  }

  function solveGrowth(D, tax, wacc, target, loe) {
    let lo = -1, hi = 20;
    for (let i = 0; i < 80; i++) {
      const mid = (lo + hi) / 2;
      if (dcf(D, tax, wacc, mid, loe).peak < target) lo = mid; else hi = mid;
    }
    return (lo + hi) / 2;
  }

  // 자산 하나의 가치. over: {peak, pos0, pos_last, delay}. 설정 PoS 는 0.99 상한(파이썬과 같게), 눌러서 정한 PoS 는 그대로.
  function assetValue(A, g, over) {
    const o = over || {};
    const delay = o.delay || 0;
    const st = A.stages.map(s => ({ t: Math.max(0.01, s.t + delay), pos: Math.min(0.99, s.pos), x: s.x * g.conv }));
    const order = st.map((s, i) => i).sort((a, b) => st[a].t - st[b].t);
    if (o.pos0 != null) st[order[0]].pos = o.pos0;
    if (o.pos_last != null) st[order[order.length - 1]].pos = o.pos_last;
    const launchIn = Math.max(0.01, A.launch_in + delay);
    const peak = o.peak != null ? o.peak : A.peak;
    const v0 = A.lump ? A.lump * g.conv / Math.pow(1 + g.wacc, launchIn)
      : launchValue(peak * g.conv, A.margin, g.tax, g.wacc, launchIn, A.ramp, A.excl);
    return A.method === 'rov' ? optionValue(v0, g.sigma, g.rf, st) : rnpvTree(v0, g.rf, st);
  }

  // m: 시장(calc 포함), k: 위 버튼 시나리오, sel: {트리거 id: 'bear'|'base'|'bull'}
  function compute(m, k, sel) {
    const C = m.calc;
    if (!C) return null;
    const P = Object.assign({}, (C.params || {})[k] || {});
    const L = (C.links || []).map(l => ({ ...l, P: Object.assign({}, l.params[k]), dead: false }));
    const O = {};
    const applied = [];
    for (const t of m.triggers || []) {
      const s = sel && sel[t.id];
      if (!s || !t.effect) continue;
      for (const e of t.effect) {
        let v = e.values[s];
        if (v === 'keep' || v == null) continue;
        const link = t.link ? L.find(x => x.id === t.link) : null;
        if (v === 'case') v = (link ? link.params : C.params)[s][e.param];
        if (v == null) continue;
        if (link && ['sam', 'pen', 'price_k'].includes(e.param)) link.P[e.param] = v;
        else if (link && ['pos0', 'pos_last'].includes(e.param)) { if (v === 0) link.dead = true; }
        else if (['sam', 'pen', 'price_k', 'share'].includes(e.param)) P[e.param] = v;
        else O[e.param] = (e.param === 'delay' ? (O.delay || 0) + v : v);
        applied.push({ trigger: t.name, case: s, param: e.param, value: v });
      }
    }
    const g = C.g;
    let peak, newVal, extra = {};
    const pk = (tam, Q, gm) => tam * Q.sam * Q.pen * Q.price_k * 1000 / 1e6 * (gm || 1);
    if (m.kind === 'pipeline') {
      peak = pk(C.tam_patients, P, C.global_mult);
      newVal = assetValue(C.asset, g, { ...O, peak });
    } else if (m.kind === 'dollar') {
      peak = C.tam_usd * P.sam * P.pen;
      newVal = assetValue(C.asset, g, { ...O, peak });
    } else if (m.kind === 'royalty') {
      const parts = L.map(l => ({ id: l.id, indication: l.indication, peak: l.dead ? 0 : pk(l.tam_patients, l.P, l.global_mult), P: l.P, dead: l.dead }));
      const partner = parts.reduce((a, b) => a + b.peak, 0);
      peak = partner * C.rate;
      extra = { partner, parts };
      newVal = assetValue(C.asset, g, { ...O, peak });
    } else if (m.kind === 'product_royalty') {
      const sales = C.base_sales * P.share * (O.sales_mult != null ? O.sales_mult : 1);
      peak = sales * C.rate;
      extra = { sales };
      newVal = assetValue(C.asset, g, { ...O, peak });
    } else if (m.kind === 'commercial') {
      const product = pk(C.tam_patients, P, 1);
      peak = product;
      const total = product / C.share;
      const same = k === 'base' && !applied.length;
      const gm = same ? 1 : solveGrowth(C.dcf, g.tax, g.wacc, total, O.loe);
      newVal = dcf(C.dcf, g.tax, g.wacc, gm, O.loe).pv;
      extra = { total, gm };
    } else if (m.kind === 'triggers') {
      peak = C.asset.peak;
      newVal = assetValue(C.asset, g, O);
    } else return null;
    const eq = C.equity_base - C.base_value + newVal;
    const ps = C.shares ? Math.max(0, eq) / C.shares : null;
    return { P, O, peak, value: newVal, equity: eq, per_share: ps, upside: ps != null && C.price ? ps / C.price - 1 : null, applied, ...extra };
  }

  const api = { CASES, launchValue, optionValue, rnpvTree, dcf, solveGrowth, assetValue, compute };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BioCalc = api;
})(typeof window !== 'undefined' ? window : globalThis);
