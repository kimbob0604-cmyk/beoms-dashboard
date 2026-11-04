// 차트 (SVG): 마우스·손가락을 올린 자리의 값을 따라가며 보여준다. 외부 라이브러리 없음.
// Plot.chart(el, spec)   여러 칸(가격·거래량·순매수…)을 x 축 하나로 묶어 그린다
// Plot.treemap(el, spec) 면적 = 크기, 색 = 등락
// Plot.weekly(cols)      일봉 열 배열 → 주봉
const Plot = (() => {
  const PAD_L = 6, PAD_R = 58, PAD_T = 8, AXIS_H = 20, GAP = 10;

  // 보기 좋은 눈금 (1·2·5 배수)
  function ticks(min, max, n = 4) {
    const span = max - min || Math.abs(max) || 1;
    const raw = span / n, mag = 10 ** Math.floor(Math.log10(raw)), e = raw / mag;
    const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
    const out = [];
    for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) out.push(+v.toPrecision(12));
    return out;
  }

  const defined = v => v != null && !Number.isNaN(v);
  const fmtDefault = v => (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('ko-KR')
    : v.toLocaleString('ko-KR', { maximumFractionDigits: 2 }));

  function extent(pane, from, to) {
    let lo = Infinity, hi = -Infinity;
    const take = v => { if (defined(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } };
    for (const s of pane.series) {
      if (s.type === 'candle') {
        for (let i = from; i < to; i++) { take(s.h[i] ?? s.c[i]); take(s.l[i] ?? s.c[i]); }
      } else {
        for (let i = from; i < to; i++) take(s.values[i]);
        if (s.type === 'bar') take(0);
      }
    }
    if (pane.baseline != null) take(pane.baseline);
    if (pane.zero) take(0);
    if (lo === Infinity) { lo = 0; hi = 1; }
    if (lo === hi) { lo -= Math.abs(lo) * 0.01 || 1; hi += Math.abs(hi) * 0.01 || 1; }
    const m = (hi - lo) * 0.08;
    return [pane.series.some(s => s.type === 'bar') && lo >= 0 ? 0 : lo - m, hi + m];
  }

  function linePath(vals, X, Y, connect) {
    let d = '', pen = false;
    vals.forEach((v, i) => {
      if (!defined(v)) { if (!connect) pen = false; return; }
      d += `${pen ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  }

  // ---------- 여러 칸 차트 ----------
  // spec: { n, panes: [{h, series, baseline, zero, fmt}], xTicks: [[i, label]], tip(i) → html, onHover(i|null),
  //         height, uid }
  // series: {type:'line', values, color, width, area, split(기준선 위·아래 색), connect, dash}
  //         {type:'candle', o,h,l,c} · {type:'bar', values, color(i)}
  function chart(el, spec) {
    el.classList.add('plot');
    el._spec = spec;
    if (!el._ro) {
      el._ro = new ResizeObserver(() => {
        if (el.clientWidth && el.clientWidth !== el._w) draw(el);
      });
      el._ro.observe(el);
    }
    draw(el);
  }

  function draw(el) {
    const spec = el._spec;
    const W = el._w = el.clientWidth || 600;
    const H = spec.height || 240;
    const n = spec.n;
    const plotW = W - PAD_L - PAD_R;
    const step = plotW / Math.max(n, 1);
    const X = i => PAD_L + (i + 0.5) * step;
    const totalH = H - PAD_T - AXIS_H - GAP * (spec.panes.length - 1);
    const hsum = spec.panes.reduce((a, p) => a + (p.h || 1), 0);
    const uid = spec.uid || (el._uid = el._uid || `p${Math.random().toString(36).slice(2, 8)}`);
    let y0 = PAD_T, svg = '';
    const layout = [];

    spec.panes.forEach((p, k) => {
      const ph = totalH * (p.h || 1) / hsum;
      const [lo, hi] = extent(p, 0, n);
      const Y = v => y0 + ph - (v - lo) / (hi - lo) * ph;
      const fmt = p.fmt || fmtDefault;
      layout.push({ top: y0, h: ph, lo, hi, Y, fmt, p });
      // 눈금
      for (const t of ticks(lo, hi, ph > 100 ? 4 : 2)) {
        if (t < lo || t > hi) continue;
        svg += `<line class="pl-grid" x1="${PAD_L}" x2="${W - PAD_R}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}"/>
          <text class="pl-ylab" x="${W - PAD_R + 6}" y="${(Y(t) + 4).toFixed(1)}">${fmt(t)}</text>`;
      }
      if (p.zero && lo < 0 && hi > 0) {
        svg += `<line class="pl-zero" x1="${PAD_L}" x2="${W - PAD_R}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}"/>`;
      }
      const by = p.baseline != null ? Y(p.baseline) : null;
      if (by != null) {
        svg += `<line class="pl-base" x1="${PAD_L}" x2="${W - PAD_R}" y1="${by.toFixed(1)}" y2="${by.toFixed(1)}"/>
          <defs><clipPath id="${uid}a${k}"><rect x="0" y="0" width="${W}" height="${by.toFixed(1)}"/></clipPath>
          <clipPath id="${uid}b${k}"><rect x="0" y="${by.toFixed(1)}" width="${W}" height="${H}"/></clipPath></defs>`;
      }
      for (const s of p.series) {
        if (s.type === 'candle') {
          const bw = Math.max(1, Math.min(step * 0.7, 14));
          for (let i = 0; i < n; i++) {
            const c = s.c[i];
            if (!defined(c)) continue;
            const o = s.o[i], x = X(i);
            if (!defined(o)) {   // 종가만 있는 날 (KRX 공개 전)
              svg += `<line class="pl-prov" x1="${x - bw / 2}" x2="${x + bw / 2}" y1="${Y(c)}" y2="${Y(c)}"/>`;
              continue;
            }
            const up = c >= o, cls = c > o ? 'pl-up' : c < o ? 'pl-dn' : 'pl-eq';
            const top = Y(Math.max(o, c)), bot = Y(Math.min(o, c));
            svg += `<line class="${cls}" x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${Y(s.h[i]).toFixed(1)}" y2="${Y(s.l[i]).toFixed(1)}"/>
              <rect class="${cls}${up ? '' : ' fill'}" x="${(x - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, bot - top).toFixed(1)}"/>`;
          }
        } else if (s.type === 'bar') {
          const bw = Math.max(1, Math.min(step * 0.7, 14));
          const z = Y(Math.max(lo, 0));
          s.values.forEach((v, i) => {
            if (!defined(v)) return;
            const y = Y(v);
            svg += `<rect class="pl-bar ${s.cls ? s.cls(i) : ''}" x="${(X(i) - bw / 2).toFixed(1)}" y="${Math.min(y, z).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0.5, Math.abs(z - y)).toFixed(1)}"/>`;
          });
        } else {
          const d = linePath(s.values, X, Y, s.connect);
          if (!d) continue;
          if (s.area && by != null) {
            const idx = s.values.map((v, i) => (defined(v) ? i : -1)).filter(i => i >= 0);
            const area = `${d}L${X(idx[idx.length - 1]).toFixed(1)},${by.toFixed(1)}L${X(idx[0]).toFixed(1)},${by.toFixed(1)}Z`;
            svg += `<path class="pl-area up" clip-path="url(#${uid}a${k})" d="${area}"/>
              <path class="pl-area dn" clip-path="url(#${uid}b${k})" d="${area}"/>`;
          } else if (s.area) {
            const idx = s.values.map((v, i) => (defined(v) ? i : -1)).filter(i => i >= 0);
            const yb = y0 + ph;
            svg += `<path class="pl-area" style="--c:${s.color}" d="${d}L${X(idx[idx.length - 1]).toFixed(1)},${yb}L${X(idx[0]).toFixed(1)},${yb}Z"/>`;
          }
          if (s.split && by != null) {
            svg += `<path class="pl-line up" clip-path="url(#${uid}a${k})" d="${d}" style="stroke-width:${s.width || 1.6}"/>
              <path class="pl-line dn" clip-path="url(#${uid}b${k})" d="${d}" style="stroke-width:${s.width || 1.6}"/>`;
          } else {
            svg += `<path class="pl-line" d="${d}" style="stroke:${s.color};stroke-width:${s.width || 1.6}${s.dash ? ';stroke-dasharray:3 3' : ''}"/>`;
          }
          // 마지막 점
          if (s.last) {
            const li = s.values.length - 1 - [...s.values].reverse().findIndex(defined);
            if (li < s.values.length) svg += `<circle class="pl-last" cx="${X(li)}" cy="${Y(s.values[li])}" r="3" style="fill:${s.color || 'currentColor'}"/>`;
          }
        }
      }
      if (p.label) svg += `<text class="pl-plab" x="${PAD_L + 2}" y="${y0 + 12}">${p.label}</text>`;
      y0 += ph + GAP;
    });

    // x 축 눈금
    const axisY = H - AXIS_H + 14;
    let lastX = -1e9;
    for (const [i, lab] of spec.xTicks || []) {
      const x = X(i);
      if (x - lastX < 46) continue;
      lastX = x;
      svg += `<line class="pl-vgrid" x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${PAD_T}" y2="${H - AXIS_H}"/>
        <text class="pl-xlab" x="${x.toFixed(1)}" y="${axisY}">${lab}</text>`;
    }

    el.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${svg}
      <g class="pl-cross" visibility="hidden">
        <line class="pl-cx" y1="${PAD_T}" y2="${H - AXIS_H}"/><line class="pl-cy" x1="${PAD_L}" x2="${W - PAD_R}"/>
        <g class="pl-ytag"><rect x="${W - PAD_R + 1}" width="${PAD_R - 2}" height="18" rx="4"/><text x="${W - PAD_R + 6}"></text></g>
        <g class="pl-dots"></g>
      </g>
      <rect class="pl-hit" x="${PAD_L}" y="0" width="${plotW}" height="${H - AXIS_H}"/></svg>
      <div class="pl-tip" hidden></div>`;
    el._layout = { X, step, layout, W, H };
    bind(el);
  }

  function bind(el) {
    const svg = el.querySelector('svg');
    const hit = svg.querySelector('.pl-hit');
    const cross = svg.querySelector('.pl-cross');
    const tip = el.querySelector('.pl-tip');
    const move = e => {
      const spec = el._spec, L = el._layout;
      const r = svg.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      let i = Math.round((mx - PAD_L) / L.step - 0.5);
      i = Math.max(0, Math.min(spec.n - 1, i));
      // 값이 없는 칸이면 가까운 값 있는 칸으로
      if (spec.has && !spec.has(i)) {
        let k = 1;
        while (k < spec.n && !(spec.has(i - k) || spec.has(i + k))) k++;
        i = spec.has(i - k) ? i - k : spec.has(i + k) ? i + k : i;
        if (!spec.has(i)) return leave();
      }
      const x = L.X(i);
      cross.setAttribute('visibility', 'visible');
      cross.querySelector('.pl-cx').setAttribute('x1', x);
      cross.querySelector('.pl-cx').setAttribute('x2', x);
      // 가로선 + 오른쪽 값 표시 (커서가 있는 칸)
      const pane = L.layout.find(p => my >= p.top && my <= p.top + p.h);
      const cy = cross.querySelector('.pl-cy'), tag = cross.querySelector('.pl-ytag');
      if (pane) {
        const v = pane.lo + (pane.top + pane.h - my) / pane.h * (pane.hi - pane.lo);
        cy.setAttribute('y1', my); cy.setAttribute('y2', my); cy.style.display = '';
        tag.style.display = '';
        tag.querySelector('rect').setAttribute('y', my - 9);
        const t = tag.querySelector('text');
        t.setAttribute('y', my + 4);
        t.textContent = pane.fmt(v);
      } else { cy.style.display = 'none'; tag.style.display = 'none'; }
      // 선 위의 점
      let dots = '';
      for (const p of L.layout) {
        for (const s of p.p.series) {
          if (s.type !== 'line' || s.nodot) continue;
          const v = s.values[i];
          if (!defined(v)) continue;
          const col = s.split && p.p.baseline != null ? (v >= p.p.baseline ? 'var(--up)' : 'var(--down)') : s.color;
          dots += `<circle cx="${x}" cy="${p.Y(v)}" r="3.5" style="fill:${col}"/>`;
        }
      }
      cross.querySelector('.pl-dots').innerHTML = dots;
      if (spec.tip) {
        tip.innerHTML = spec.tip(i);
        tip.hidden = false;
        const tw = tip.offsetWidth, th = tip.offsetHeight;
        let tx = x + 14;
        if (tx + tw > L.W - PAD_R) tx = x - tw - 14;
        tip.style.left = `${Math.max(0, tx)}px`;
        tip.style.top = `${Math.max(0, Math.min(my - th / 2, L.H - AXIS_H - th))}px`;
      }
      spec.onHover?.(i);
    };
    const leave = () => {
      cross.setAttribute('visibility', 'hidden');
      tip.hidden = true;
      el._spec.onHover?.(null);
    };
    hit.addEventListener('pointermove', move);
    hit.addEventListener('pointerdown', move);
    hit.addEventListener('pointerleave', leave);
    hit.addEventListener('pointercancel', leave);
  }

  // ---------- 트리맵 (squarified) ----------
  function squarify(items, x, y, w, h, out) {
    if (!items.length) return;
    const total = items.reduce((a, it) => a + it.area, 0);
    if (items.length === 1) { out.push({ ...items[0], x, y, w, h }); return; }
    const short = Math.min(w, h);
    let row = [], rowSum = 0, best = Infinity;
    const worst = (sum, maxA, minA) => Math.max(short * short * maxA / (sum * sum), (sum * sum) / (short * short * minA));
    let k = 0;
    for (; k < items.length; k++) {
      const a = items[k].area;
      const s = rowSum + a;
      const r = worst(s, Math.max(a, ...row.map(t => t.area)), Math.min(a, ...row.map(t => t.area)));
      if (row.length && r > best) break;
      row.push(items[k]); rowSum = s; best = r;
    }
    const thick = rowSum / short;
    let off = 0;
    for (const it of row) {
      const len = it.area / thick;
      if (w >= h) out.push({ ...it, x, y: y + off, w: thick, h: len });
      else out.push({ ...it, x: x + off, y, w: len, h: thick });
      off += len;
    }
    const rest = items.slice(k);
    if (w >= h) squarify(rest, x + thick, y, w - thick, h, out);
    else squarify(rest, x, y + thick, w, h - thick, out);
    void total;
  }

  // spec: { items: [{v, html, tip, attrs, color}], height }
  function treemap(el, spec) {
    el.classList.add('tmap');
    el._tm = spec;
    if (!el._ro) {
      el._ro = new ResizeObserver(() => { if (el.clientWidth !== el._w) drawTm(el); });
      el._ro.observe(el);
    }
    drawTm(el);
  }

  function drawTm(el) {
    const spec = el._tm;
    const W = el._w = el.clientWidth || 600, H = spec.height || 320;
    const sum = spec.items.reduce((a, it) => a + it.v, 0) || 1;
    const items = spec.items.filter(it => it.v > 0).sort((a, b) => b.v - a.v)
      .map(it => ({ ...it, area: it.v / sum * W * H }));
    const cells = [];
    squarify(items, 0, 0, W, H, cells);
    el.style.height = `${H}px`;
    el.innerHTML = cells.map(c => {
      const size = Math.min(c.w, c.h);
      const sz = size > 90 ? 'xl' : size > 60 ? 'l' : size > 38 ? 'm' : 's';
      return `<div class="tm-cell ${sz}${c.hot ? ' hot' : ''}" style="left:${c.x}px;top:${c.y}px;width:${c.w}px;height:${c.h}px;background:${c.color}" ${c.attrs || ''}>${c.html}</div>`;
    }).join('') + '<div class="pl-tip tm-tip" hidden></div>';
    const tip = el.querySelector('.tm-tip');
    const cellsEl = [...el.querySelectorAll('.tm-cell')];
    cellsEl.forEach((node, k) => {
      node.addEventListener('pointerenter', () => { tip.innerHTML = cells[k].tip || ''; tip.hidden = !cells[k].tip; });
      node.addEventListener('pointermove', e => {
        const r = el.getBoundingClientRect();
        let tx = e.clientX - r.left + 14, ty = e.clientY - r.top + 14;
        if (tx + tip.offsetWidth > W) tx = e.clientX - r.left - tip.offsetWidth - 14;
        if (ty + tip.offsetHeight > H) ty = e.clientY - r.top - tip.offsetHeight - 14;
        tip.style.left = `${Math.max(0, tx)}px`;
        tip.style.top = `${Math.max(0, ty)}px`;
      });
      node.addEventListener('pointerleave', () => { tip.hidden = true; });
    });
  }

  // 등락률(%) → 배경색 (빨강·파랑, 3% 이상은 가장 진하게)
  function heat(ch, max = 3) {
    if (ch == null) return 'var(--chip)';
    const a = Math.min(Math.abs(ch) / max, 1);
    if (Math.abs(ch) < 0.05) return 'var(--tm-flat)';
    const c = ch > 0 ? 'var(--up)' : 'var(--down)';
    return `color-mix(in srgb, ${c} ${Math.round(30 + a * 66)}%, var(--tm-base))`;
  }

  // ---------- 일봉 → 주봉 ----------
  function weekly(x) {
    const out = { d: [], o: [], h: [], l: [], c: [], v: [] };
    let key = null;
    x.d.forEach((d, i) => {
      const t = new Date(`${String(d).slice(0, 4)}-${String(d).slice(4, 6)}-${String(d).slice(6, 8)}T00:00:00`);
      const mon = new Date(t); mon.setDate(t.getDate() - ((t.getDay() + 6) % 7));
      const k = mon.toISOString().slice(0, 10);
      if (k !== key) {
        key = k;
        out.d.push(d); out.o.push(x.o[i]); out.h.push(x.h[i] ?? x.c[i]); out.l.push(x.l[i] ?? x.c[i]);
        out.c.push(x.c[i]); out.v.push(x.v[i] || 0);
        return;
      }
      const j = out.d.length - 1;
      out.d[j] = d;
      if (out.o[j] == null) out.o[j] = x.o[i];
      out.h[j] = Math.max(out.h[j], x.h[i] ?? x.c[i]);
      out.l[j] = Math.min(out.l[j], x.l[i] ?? x.c[i]);
      out.c[j] = x.c[i];
      out.v[j] += x.v[i] || 0;
    });
    return out;
  }

  // 이동평균 (앞쪽 모자란 칸은 null)
  function ma(vals, k) {
    let s = 0, cnt = 0;
    const q = [];
    return vals.map(v => {
      q.push(v); if (defined(v)) { s += v; cnt++; }
      if (q.length > k) { const r = q.shift(); if (defined(r)) { s -= r; cnt--; } }
      return q.length === k && cnt === k ? s / k : null;
    });
  }

  // 날짜 정수 배열 → 월이 바뀌는 자리 눈금
  function monthTicks(d) {
    const out = [];
    let prev = null;
    d.forEach((x, i) => {
      const s = String(x), ym = s.slice(0, 6);
      if (ym !== prev) {
        if (prev) out.push([i, s.slice(4, 6) === '01' ? `${s.slice(2, 4)}년` : `${+s.slice(4, 6)}월`]);
        prev = ym;
      }
    });
    return out;
  }

  const dateStr = x => { const s = String(x); return `${s.slice(2, 4)}.${s.slice(4, 6)}.${s.slice(6, 8)}`; };

  return { chart, treemap, heat, weekly, ma, monthTicks, dateStr, ticks };
})();
