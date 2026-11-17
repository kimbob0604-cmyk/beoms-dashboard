// Beom's Study 재구성 차트 (SVG, 외부 라이브러리 없음)
// SChart.html(spec) → 범례 + SVG + 데이터 표 HTML.  spec 종류:
//   bar   { x:[항목], series:[{name, values}], orient:'v'|'h', unit, dec, color_by:[항목별 그룹], groups:[색 고정 순서], mark:{max,last} }
//   stack { x, series(아래→위), unit, dec }
//   range { x:[행], series:[{name, lo:[], hi:[]}], unit }
//   scatter { points:[{id,label,x,y,r}], xlab, ylab, rlab, labels:[항상 이름 붙일 id], quad:{x,y,tr,bl} }
// 색: 범주형 고정 순서 --s1..--s8 (dataviz 기본 팔레트, 검증 통과). '대조' 가 들어간 계열은 회색(맥락).
// 마크: 막대 굵기 ≤24, 끝 4px 둥글게(바닥은 각지게), 맞닿는 막대 사이 2px 틈, 얇은 격자. 값은 마우스를 올리면 보인다.
const SChart = (() => {
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (v, dec) => v == null ? '–' : v.toLocaleString('ko-KR', { minimumFractionDigits: dec ?? 0, maximumFractionDigits: dec ?? 1 });
  const SRC = { label: '원본 숫자 라벨을 옮김', pixel: '그림에서 픽셀로 읽음', table: '표에서 옮김', calc: '읽은 값으로 계산' };

  // 0 부터 max 를 덮는 눈금 (마지막 눈금이 max 보다 작으면 한 칸 더)
  function niceTicks(max, n = 4) {
    let t;
    if (typeof Plot !== 'undefined' && Plot.ticks) t = Plot.ticks(0, max, n);
    else { const st = Math.pow(10, Math.floor(Math.log10(max / n))); t = []; for (let v = 0; v <= max * 1.0001; v += st) t.push(v); }
    const step = t.length > 1 ? t[1] - t[0] : max;
    while (t[t.length - 1] < max) t.push(+(t[t.length - 1] + step).toPrecision(12));
    return t;
  }

  // 시리즈 색: groups 에 이름이 있으면 그 자리, '대조' 는 회색, 아니면 순서대로
  const slotOf = (spec, name, i) => {
    if (/대조/.test(name)) return 'ctl';
    const g = spec.groups ? spec.groups.indexOf(name) : -1;
    return g >= 0 ? g + 1 : i + 1;
  };
  const fill = slot => slot === 'ctl' ? 'var(--s-ctl)' : `var(--s${Math.min(slot, 8)})`;

  // 끝만 둥근 막대 경로 (v: 위쪽, h: 오른쪽)
  function barPath(x, y, w, h, orient, round = true) {
    const r = round ? Math.min(4, w / 2, h) : 0;
    if (h <= 0 || w <= 0) return '';
    if (orient === 'h') {   // x=시작, y=위, w=길이, h=두께
      return `M${x},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} H${x} Z`;
    }
    return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
  }

  const tip = (s) => `data-tip="${esc(s)}"`;
  const lines = s => String(s).split('\n');

  function legend(items) {
    if (items.length < 2) return '';
    return `<div class="sc-legend">${items.map(([name, slot]) => `<span><i style="background:${fill(slot)}"></i>${esc(name)}</span>`).join('')}</div>`;
  }

  // ---------- 세로 막대 (묶음) ----------
  function vbar(spec) {
    const W = 640, H = 270, L = 46, R = 10, T = 22, B = spec.x.some(x => String(x).includes('\n')) ? 46 : 30;
    const S = spec.series, n = spec.x.length, k = S.length;
    const max = Math.max(...S.flatMap(s => s.values)) || 1;
    const ticks = niceTicks(max * 1.08), top = ticks[ticks.length - 1];
    const y = v => T + (H - T - B) * (1 - v / top);
    const band = (W - L - R) / n;
    const bw = Math.min(24 * (k > 1 ? 1 : 1.6), (band * 0.72 - 2 * (k - 1)) / k);
    const gw = bw * k + 2 * (k - 1);
    const total = n * k;
    const dec = spec.dec;
    let g = ticks.map(t => `<line x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}" class="sc-grid"/><text x="${L - 6}" y="${y(t) + 4}" class="sc-ax" text-anchor="end">${fmt(t)}</text>`).join('');
    const imax = S[0].values.indexOf(Math.max(...S[0].values));
    S.forEach((s, si) => {
      const slot = slotOf(spec, s.name, si);
      s.values.forEach((v, i) => {
        const x = L + band * i + (band - gw) / 2 + si * (bw + 2);
        const yy = y(v);
        g += `<path d="${barPath(x, yy, bw, y(0) - yy, 'v')}" fill="${fill(slot)}" ${tip(`${String(spec.x[i]).replace('\n', ' ')} · ${s.name}: ${fmt(v, dec)}${spec.unit ? ' ' + spec.unit : ''}`)}/>`;
        const show = total <= 10 || (k === 1 && spec.mark && ((spec.mark.max && i === imax) || (spec.mark.last && i === n - 1) || i === 0));
        if (show) g += `<text x="${x + bw / 2}" y="${yy - 5}" class="sc-val" text-anchor="middle">${fmt(v, dec)}</text>`;
      });
    });
    spec.x.forEach((c, i) => {
      const cx = L + band * i + band / 2;
      g += lines(c).map((ln, j) => `<text x="${cx}" y="${H - B + 16 + j * 14}" class="sc-ax" text-anchor="middle">${esc(ln)}</text>`).join('');
    });
    g += `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" class="sc-base"/>`;
    return svgWrap(W, H, g, spec);
  }

  // ---------- 가로 막대 ----------
  function hbar(spec) {
    const S = spec.series, n = spec.x.length, k = S.length;
    const row = k > 1 ? 30 : 22, L = Math.min(170, 14 + Math.max(...spec.x.map(x => String(x).length)) * 11.5), R = 54, T = 6;
    const W = 640, H = T + n * row + 22;
    const max = Math.max(...S.flatMap(s => s.values)) || 1;
    const ticks = niceTicks(max * 1.05), top = ticks[ticks.length - 1];
    const x = v => L + (W - L - R) * v / top;
    const bh = Math.min(k > 1 ? 11 : 16, (row - 6 - 2 * (k - 1)) / k);
    let g = ticks.map(t => `<line x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${H - 20}" class="sc-grid"/><text x="${x(t)}" y="${H - 6}" class="sc-ax" text-anchor="middle">${fmt(t)}</text>`).join('');
    spec.x.forEach((c, i) => {
      const y0 = T + i * row + (row - (bh * k + 2 * (k - 1))) / 2;
      g += `<text x="${L - 8}" y="${T + i * row + row / 2 + 4}" class="sc-lab" text-anchor="end">${esc(c)}</text>`;
      S.forEach((s, si) => {
        const v = s.values[i];
        const slot = spec.color_by ? slotOf(spec, spec.color_by[i], 0) : slotOf(spec, s.name, si);
        const yy = y0 + si * (bh + 2);
        g += `<path d="${barPath(L, yy, x(v) - L, bh, 'h')}" fill="${fill(slot)}" ${tip(`${c} · ${s.name}: ${fmt(v, spec.dec)}${spec.unit ? ' ' + spec.unit : ''}`)}/>`;
        g += `<text x="${x(v) + 5}" y="${yy + bh / 2 + 4}" class="sc-val">${fmt(v, spec.dec)}</text>`;
      });
    });
    g += `<line x1="${L}" x2="${L}" y1="${T}" y2="${H - 20}" class="sc-base"/>`;
    // 기준선 (예: HR = 1 — 왼쪽일수록 실험군이 좋다)
    if (spec.ref != null) g += `<line x1="${x(spec.ref)}" x2="${x(spec.ref)}" y1="${T}" y2="${H - 20}" class="sc-ref"/>`
      + `<text x="${x(spec.ref) + 4}" y="${T + 10}" class="sc-ax">${esc(spec.ref_label || '')}</text>`;
    return svgWrap(W, H, g, spec);
  }

  // ---------- 쌓은 막대 ----------
  function stack(spec) {
    const W = 640, H = 280, L = 46, R = 10, T = 22, B = 30;
    const S = spec.series, n = spec.x.length;
    const tot = spec.x.map((_, i) => S.reduce((a, s) => a + s.values[i], 0));
    const ticks = niceTicks(Math.max(...tot) * 1.08), top = ticks[ticks.length - 1];
    const sc = v => (H - T - B) * v / top, base = H - B;
    const band = (W - L - R) / n, bw = Math.min(30, band * 0.6);
    let g = ticks.map(t => `<line x1="${L}" x2="${W - R}" y1="${base - sc(t)}" y2="${base - sc(t)}" class="sc-grid"/><text x="${L - 6}" y="${base - sc(t) + 4}" class="sc-ax" text-anchor="end">${fmt(t)}</text>`).join('');
    const imax = tot.indexOf(Math.max(...tot));
    spec.x.forEach((c, i) => {
      const x = L + band * i + (band - bw) / 2;
      let acc = 0;
      S.forEach((s, si) => {
        const v = s.values[i];
        const y1 = base - sc(acc), h = sc(v) - (si < S.length - 1 ? 2 : 0);   // 위 구간과 2px 틈
        acc += v;
        g += `<path d="${barPath(x, y1 - h, bw, h, 'v', si === S.length - 1)}" fill="${fill(slotOf(spec, s.name, si))}" ${tip(`${c} · ${s.name}: ${fmt(v, spec.dec)} ${spec.unit || ''} (합 ${fmt(tot[i], spec.dec)})`)}/>`;
      });
      if (i === 0 || i === imax || i === n - 1) g += `<text x="${x + bw / 2}" y="${base - sc(tot[i]) - 5}" class="sc-val" text-anchor="middle">${fmt(tot[i], spec.dec)}</text>`;
      g += `<text x="${L + band * i + band / 2}" y="${H - B + 16}" class="sc-ax" text-anchor="middle">${esc(c)}</text>`;
    });
    g += `<line x1="${L}" x2="${W - R}" y1="${base}" y2="${base}" class="sc-base"/>`;
    return svgWrap(W, H, g, spec);
  }

  // ---------- 범위 (가로) ----------
  function range(spec) {
    const S = spec.series, n = spec.x.length, k = S.length;
    const W = 640, row = 18 + 14 * k, L = 90, R = 60, T = 6, H = T + n * row + 22;
    const max = Math.max(...S.flatMap(s => s.hi));
    const ticks = niceTicks(max * 1.05), top = ticks[ticks.length - 1];
    const x = v => L + (W - L - R) * v / top;
    let g = ticks.map(t => `<line x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${H - 20}" class="sc-grid"/><text x="${x(t)}" y="${H - 6}" class="sc-ax" text-anchor="middle">${fmt(t)}${spec.unit === '%' ? '%' : ''}</text>`).join('');
    spec.x.forEach((c, i) => {
      g += `<text x="${L - 10}" y="${T + i * row + row / 2 + 4}" class="sc-lab" text-anchor="end">${esc(c)}</text>`;
      S.forEach((s, si) => {
        const yy = T + i * row + 12 + si * 14, lo = s.lo[i], hi = s.hi[i], col = fill(slotOf(spec, s.name, si));
        const t = `${c} · ${s.name}: ${lo === hi ? fmt(lo) : `${fmt(lo)}~${fmt(hi)}`}${spec.unit || ''}`;
        g += hi > lo ? `<line x1="${x(lo)}" x2="${x(hi)}" y1="${yy}" y2="${yy}" stroke="${col}" stroke-width="6" stroke-linecap="round" ${tip(t)}/>` : '';
        g += `<circle cx="${x(lo)}" cy="${yy}" r="4.5" fill="${col}" class="sc-ring" ${tip(t)}/>${hi > lo ? `<circle cx="${x(hi)}" cy="${yy}" r="4.5" fill="${col}" class="sc-ring" ${tip(t)}/>` : ''}`;
        g += `<text x="${x(hi) + 9}" y="${yy + 4}" class="sc-val">${lo === hi ? fmt(lo) : `${fmt(lo)}~${fmt(hi)}`}</text>`;
      });
    });
    return svgWrap(W, H, g, spec);
  }

  // ---------- 산점도 (크기 = 세 번째 값) ----------
  function scatter(spec) {
    const W = 640, H = 420, L = 50, R = 16, T = 24, B = 40;
    const P = spec.points;
    const xs = P.map(p => p.x), ys = P.map(p => p.y);
    const x0 = Math.floor(Math.min(...xs) * 2) / 2, x1 = Math.ceil(Math.max(...xs) * 2) / 2;
    const yt = niceTicks(Math.max(...ys) * 1.05), y1 = yt[yt.length - 1];
    const X = v => L + (W - L - R) * (v - x0) / (x1 - x0), Y = v => H - B - (H - T - B) * v / y1;
    const rmax = Math.max(...P.map(p => p.r)) || 1;
    const rad = r => 4 + 14 * Math.sqrt(r / rmax);
    let g = yt.map(t => `<line x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}" class="sc-grid"/><text x="${L - 6}" y="${Y(t) + 4}" class="sc-ax" text-anchor="end">${fmt(t, 2)}</text>`).join('');
    for (let v = x0; v <= x1 + 1e-9; v += 0.5) g += `<line x1="${X(v)}" x2="${X(v)}" y1="${T}" y2="${H - B}" class="sc-grid"/><text x="${X(v)}" y="${H - B + 16}" class="sc-ax" text-anchor="middle">${fmt(v, 1)}</text>`;
    if (spec.quad) {
      const q = spec.quad;
      g += `<line x1="${X(q.x)}" x2="${X(q.x)}" y1="${T}" y2="${H - B}" class="sc-ref"/><line x1="${L}" x2="${W - R}" y1="${Y(q.y)}" y2="${Y(q.y)}" class="sc-ref"/>`;
      g += `<text x="${W - R - 6}" y="${T + 14}" class="sc-quad" text-anchor="end">${esc(q.tr)} ↗</text><text x="${L + 6}" y="${H - B - 8}" class="sc-quad">↙ ${esc(q.bl)}</text>`;
    }
    [...P].sort((a, b) => b.r - a.r).forEach(p => {
      g += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="${rad(p.r)}" fill="var(--s1)" fill-opacity=".55" class="sc-ring" ${tip(`${p.label} (${p.id}) · TMB ${fmt(p.x, 2)} · CD8 ${fmt(p.y, 3)} · ${spec.rlab} ${fmt(p.r * 100, 1)}%`)}/>`;
    });
    // 이름표: 오른쪽·왼쪽·위·아래 중 다른 점·이름표와 안 겹치는 자리 (글자 폭은 어림)
    const boxes = P.map(p => ({ x0: X(p.x) - rad(p.r), x1: X(p.x) + rad(p.r), y0: Y(p.y) - rad(p.r), y1: Y(p.y) + rad(p.r) }));
    const hit = b => boxes.some(o => b.x0 < o.x1 && b.x1 > o.x0 && b.y0 < o.y1 && b.y1 > o.y0) || b.x0 < L || b.x1 > W - R || b.y0 < T || b.y1 > H - B;
    P.filter(p => (spec.labels || []).includes(p.id)).sort((a, b) => b.r - a.r).forEach(p => {
      const txt = `${p.label} ${fmt(p.r * 100, 0)}%`, tw = [...txt].reduce((a, ch) => a + (/[가-힣]/.test(ch) ? 11.6 : ch === ' ' ? 3.5 : 6.8), 4), cx = X(p.x), cy = Y(p.y), rr = rad(p.r) + 3;
      const cand = [[cx + rr, cy - 7, 'start'], [cx - rr - tw, cy - 7, 'end'], [cx - tw / 2, cy - rr - 15, 'middle'], [cx - tw / 2, cy + rr + 1, 'middle'],
                    [cx + rr, cy - 20, 'start'], [cx + rr, cy + 6, 'start'], [cx - rr - tw, cy - 20, 'end'], [cx - rr - tw, cy + 6, 'end']];
      const pick = cand.find(([x, y]) => !hit({ x0: x, x1: x + tw, y0: y, y1: y + 14 })) || cand[0];
      const [x, y, anchor] = pick;
      boxes.push({ x0: x, x1: x + tw, y0: y, y1: y + 14 });
      const tx = anchor === 'start' ? x : anchor === 'end' ? x + tw : x + tw / 2;
      g += `<text x="${tx}" y="${y + 11}" class="sc-lab" text-anchor="${anchor}">${esc(txt)}</text>`;
    });
    g += `<text x="${(L + W - R) / 2}" y="${H - 6}" class="sc-ax" text-anchor="middle">${esc(spec.xlab)}</text>`;
    g += `<text x="14" y="${(T + H - B) / 2}" class="sc-ax" text-anchor="middle" transform="rotate(-90 14 ${(T + H - B) / 2})">${esc(spec.ylab)}</text>`;
    const key = `<div class="sc-legend"><span><i class="dot s"></i><i class="dot l"></i>점 크기 = ${esc(spec.rlab)}</span><span class="muted">이름은 일부만, 나머지는 마우스를 올리면</span></div>`;
    return key + `<svg class="sc-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="재구성 산점도">${g}</svg>`;
  }

  function svgWrap(W, H, g, spec) {
    const items = spec.color_by
      ? [...new Set(spec.color_by)].map(n => [n, slotOf(spec, n, 0)])
      : spec.series.map((s, i) => [s.name, slotOf(spec, s.name, i)]);
    return legend(items) + `<svg class="sc-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(spec.title || '재구성 차트')}">${g}</svg>`;
  }

  // 데이터 표 (색만으로 읽지 않게 + 대비가 낮은 색의 보완)
  function table(spec) {
    let head, body;
    if (spec.type === 'scatter') {
      head = ['암종', '약자', 'TMB(log10)', 'CD8 T세포', spec.rlab];
      body = spec.points.map(p => [p.label, p.id, fmt(p.x, 2), fmt(p.y, 3), fmt(p.r * 100, 1) + '%']);
    } else if (spec.type === 'range') {
      head = ['', ...spec.series.map(s => s.name)];
      body = spec.x.map((c, i) => [c, ...spec.series.map(s => s.lo[i] === s.hi[i] ? fmt(s.lo[i]) : `${fmt(s.lo[i])}~${fmt(s.hi[i])}`)]);
    } else {
      head = ['', ...spec.series.map(s => s.name), ...(spec.color_by ? ['구분'] : [])];
      body = spec.x.map((c, i) => [String(c).replace('\n', ' '), ...spec.series.map(s => fmt(s.values[i], spec.dec)), ...(spec.color_by ? [spec.color_by[i]] : [])]);
    }
    return `<details class="sc-data"><summary>데이터 보기${spec.unit ? ` (단위: ${esc(spec.unit)})` : ''}</summary><div class="sd-tblwrap"><table class="sd-tbl">
      <thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
      <tbody>${body.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
  }

  function html(spec) {
    const body = spec.type === 'scatter' ? scatter(spec)
      : spec.type === 'stack' ? stack(spec)
      : spec.type === 'range' ? range(spec)
      : spec.orient === 'h' ? hbar(spec) : vbar(spec);
    return `<div class="sc">
      ${spec.title ? `<p class="sc-title">${esc(spec.title)}</p>` : ''}
      ${spec.unit && spec.type !== 'scatter' ? `<p class="sc-unit">단위: ${esc(spec.unit)}</p>` : ''}
      ${body}
      <p class="sc-src"><span class="sc-badge">${SRC[spec.src] || ''}</span>${spec.note ? esc(spec.note) : ''}</p>
      ${table(spec)}
    </div>`;
  }

  // 툴팁: data-tip 이 붙은 마크 위에서 따라다닌다
  let tipEl;
  document.addEventListener('mousemove', e => {
    const t = e.target.closest && e.target.closest('[data-tip]');
    if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'sc-tip'; tipEl.hidden = true; document.body.appendChild(tipEl); }
    if (!t) { tipEl.hidden = true; return; }
    tipEl.textContent = t.getAttribute('data-tip');
    tipEl.hidden = false;
    const w = tipEl.offsetWidth;
    tipEl.style.left = `${Math.min(e.clientX + 14, innerWidth - w - 8)}px`;
    tipEl.style.top = `${e.clientY + 16}px`;
  });

  return { html };
})();
