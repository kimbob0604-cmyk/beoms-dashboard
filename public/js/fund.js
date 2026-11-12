// 펀더: 분기 비용 구조 (data/fund/{code}.json — build_fund.py). 종목 패널과 펀더 탭이 같이 쓴다
//   Fund.render(el, d)  표(금액 ↔ 매출 대비 %, 묶음 ↔ 원본 줄) · OPM 브리지 · 리포트 문장 · 비용 구조 계산
//   Fund.load(code)     없으면 null
const Fund = (() => {
  const st = new WeakMap();   // el → {d, mode, unit, sel}
  const n1 = v => (v == null ? '–' : Math.abs(v) >= 100 ? Math.round(v).toLocaleString('ko-KR') : v.toFixed(1));
  const pp = (v, d = 1) => (v == null ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%p`);
  const esc = s => U.esc(s);

  async function load(code) {
    try { return await U.json(`data/fund/${code}.json`); } catch (e) { return null; }
  }

  const opm = (d, i) => (d.op[i] != null && d.rev[i] ? d.op[i] / d.rev[i] * 100 : null);

  // i 분기와 j 분기의 묶음별 매출 대비 비중 변화 (%p, 양수 = 비용 비중이 늘어 OPM 을 깎음)
  function bridge(d, i, j) {
    if (j < 0 || !d.rev[i] || !d.rev[j]) return [];
    return d.groups.map(g => [g.g, ((g.v[i] || 0) / d.rev[i] - (g.v[j] || 0) / d.rev[j]) * 100])
      .filter(([, v]) => Math.abs(v) >= 0.05).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  }

  function tableHtml(s) {
    const { d, mode, unit, sel } = s;
    const rows = mode === 'grp' ? d.groups.map(g => [g.g, g.v, g.fix]) : d.lines.map(l => [l.l, l.v, false, l.g]);
    const cell = (v, i, cls = '') => {
      if (v == null) return `<td class="num muted${i === sel ? ' sel' : ''}">–</td>`;
      const t = unit === 'pct' ? (d.rev[i] ? `${(v / d.rev[i] * 100).toFixed(Math.abs(v / d.rev[i]) < 0.1 ? 1 : 0)}%` : '–') : n1(v);
      return `<td class="num${v < 0 ? ' down' : ''}${i === sel ? ' sel' : ''} ${cls}">${t}</td>`;
    };
    const tag = e => {
      const x = d.earn?.[e];
      if (!x || !x.case || x.case === 'inline') return '';
      const up = x.case !== 'miss';
      return `<i class="fd-earn ${up ? 'up' : 'down'}" title="실적 발표 덱: 영업이익 예상 대비 ${x.or == null ? '–' : (x.or * 100).toFixed(0) + '%'}, 매출 ${x.sr == null ? '–' : (x.sr * 100).toFixed(0) + '%'}">${up ? '서프' : '미스'}</i>`;
    };
    return `<div class="tbl-wrap fd-wrap"><table class="tbl fd-tbl">
      <thead><tr><th>${unit === 'pct' ? '매출액 대비 비중' : '억원'}</th>${d.q.map((e, i) => `<th class="num${i === sel ? ' sel' : ''}" data-fq="${i}" title="${e} · 누르면 아래 분석이 이 분기로 바뀝니다${d.xb.includes(e) ? ' · 주석 XBRL 값' : ''}${d.chk[e] ? ` · 검증: ${esc(d.chk[e])}` : ''}">
        ${d.ql[i]}${d.chk[e] ? '<i class="fd-warn">!</i>' : ''}${tag(e)}</th>`).join('')}</tr></thead>
      <tbody>
        <tr class="fd-rev"><td>매출액</td>${d.rev.map((v, i) => `<td class="num${i === sel ? ' sel' : ''}">${v == null ? '–' : n1(v)}</td>`).join('')}</tr>
        ${rows.map(([l, v, fix, g]) => `<tr><td title="${g ? `묶음: ${g}` : fix ? '고정비성(계산에서 금액 유지)' : ''}">${esc(l)}</td>${v.map((x, i) => cell(x, i)).join('')}</tr>`).join('')}
        <tr class="fd-tot"><td>비용합계</td>${d.tot.map((v, i) => cell(v, i)).join('')}</tr>
        <tr class="fd-op"><td>OP</td>${d.op.map((v, i) => `<td class="num${v < 0 ? ' down' : ''}${i === sel ? ' sel' : ''}">${v == null ? '–' : n1(v)}</td>`).join('')}</tr>
        <tr class="fd-opm"><td>OPM</td>${d.q.map((e, i) => { const m = opm(d, i); return `<td class="num${m < 0 ? ' down' : ''}${i === sel ? ' sel' : ''}">${m == null ? '–' : m.toFixed(1) + '%'}</td>`; }).join('')}</tr>
      </tbody></table></div>`;
  }

  function bars(list, title, from, to) {
    if (!list.length) return `<div class="fd-br"><h4>${title}</h4><p class="muted small">비교할 분기가 없습니다.</p></div>`;
    const max = Math.max(...list.map(([, v]) => Math.abs(v)), 0.5);
    const net = to == null || from == null ? null : to - from;
    return `<div class="fd-br"><h4>${title} <span class="muted small">OPM ${from == null ? '–' : from.toFixed(1) + '%'} → ${to == null ? '–' : to.toFixed(1) + '%'}</span>
        <b class="${U.cls(net)}">${pp(net)}</b></h4>
      ${list.slice(0, 7).map(([g, v]) => `<div class="fd-bar"><span>${esc(g)}</span>
        <i><em class="${v > 0 ? 'neg' : 'pos'}" style="width:${Math.abs(v) / max * 100}%"></em></i>
        <b class="${v > 0 ? 'down' : 'up'}" title="매출 대비 비중 변화. 비중이 늘면 그만큼 OPM 이 줄어듭니다">${pp(v)}</b></div>`).join('')}</div>`;
  }

  function evHtml(d, e, top) {
    const list = d.ev?.[e] || [];
    const earn = d.earn?.[e];
    const head = earn ? `<p class="small">실적 발표 ${earn.ts.slice(5, 16)} · 영업이익 예상 대비 <b class="${U.cls(earn.or)}">${earn.or == null ? '–' : (earn.or > 0 ? '+' : '') + (earn.or * 100).toFixed(0) + '%'}</b>
      · 매출 <b class="${U.cls(earn.sr)}">${earn.sr == null ? '–' : (earn.sr > 0 ? '+' : '') + (earn.sr * 100).toFixed(0) + '%'}</b> <span class="muted">(실적 발표 덱)</span></p>` : '';
    if (!list.length) return `<div class="fd-ev"><h4>증권사는 뭐라고 썼나</h4>${head}<p class="muted small">이 분기를 다룬 리포트에서 비용·마진 요인을 말한 문장이 없습니다 (리포트는 2026-08 부터 모았습니다).</p></div>`;
    const said = {};
    for (const r of list) for (const [gs] of r.s) for (const g of gs) said[g] = (said[g] || 0) + 1;
    const tops = top.slice(0, 2).map(([g]) => g);
    const miss = tops.filter(g => !said[g]);
    return `<div class="fd-ev"><h4>증권사는 뭐라고 썼나 <span class="muted small">${list.length}건 · 요인 낱말이 든 문장</span></h4>${head}
      <p class="small">리포트가 말한 요인: ${Object.entries(said).sort((a, b) => b[1] - a[1]).map(([g, n]) => `<span class="fd-chip${tops.includes(g) ? ' on' : ''}">${g} ${n}</span>`).join('')}
        ${miss.length ? `<span class="muted"> · 숫자가 크게 움직인 <b>${miss.join('·')}</b>은(는) 리포트에 언급이 없습니다</span>` : ''}</p>
      ${list.map(r => `<article class="fd-rep"><header><span class="muted small">${r.d.slice(5)} · ${esc(r.b)}</span>
          ${r.pdf ? `<a href="${esc(r.pdf)}" target="_blank" rel="noopener">${esc(r.t)} ↗</a>` : `<b>${esc(r.t)}</b>`}</header>
        ${r.s.map(([gs, t]) => `<p>${gs.map(g => `<span class="fd-chip${tops.includes(g) ? ' on' : ''}">${g}</span>`).join('')}${esc(t)}</p>`).join('')}</article>`).join('')}</div>`;
  }

  // 비용 구조 계산: 변동비 = 매출 × 비율, 고정비 = 금액. 입력을 바꾸면 다시 계산
  function calcHtml(s) {
    const { d } = s;
    const nx = d.cns?.next?.[0];
    const m = (nx && nx.m) || d.cns?.base;
    if (!m) return '';
    const c = s.calc || (s.calc = {
      rev: nx ? nx.sales : d.rev[d.rev.length - 1],
      cogs: (m.var['원가'] || 0) * 100,
      ovar: Object.entries(m.var).filter(([g]) => g !== '원가').reduce((a, [, v]) => a + v, 0) * 100,
      fix: Object.values(m.fix).reduce((a, v) => a + v, 0),
    });
    const cost = c.rev * (c.cogs + c.ovar) / 100 + c.fix, op = c.rev - cost;
    const last = d.q.length - 1;
    const lastCogs = d.rev[last] ? ((d.groups.find(g => g.g === '원가')?.v[last] || 0) / d.rev[last] * 100) : null;
    const need = nx && nx.op != null && c.rev ? (c.rev - nx.op - c.fix) / c.rev * 100 - c.ovar : null;
    const inp = (k, v, step, suf) => `<label>${suf[0]}<input type="number" data-fc="${k}" value="${(+v).toFixed(step < 1 ? 1 : 0)}" step="${step}"><small>${suf[1]}</small></label>`;
    return `<div class="fd-calc"><h4>비용 구조로 본 ${nx ? nx.pl : '다음 분기'} 영업이익 <span class="muted small">변동비 = 매출 × 비율(최근 4분기 평균), 고정비(인건비·감가상각·임차료) = 직전 분기 금액 · 숫자를 바꾸면 다시 계산</span></h4>
      <div class="fd-inputs">
        ${inp('rev', c.rev, 10, ['매출 ', '억' + (nx ? ` · 컨센서스 ${n1(nx.sales)}` : ' · 직전 분기')])}
        ${inp('cogs', c.cogs, 0.1, ['원가(원재료·재고) 비율 ', `% · 직전 ${lastCogs == null ? '–' : lastCogs.toFixed(1)}%`])}
        ${inp('ovar', c.ovar, 0.1, ['그 밖의 변동비 ', '%'])}
        ${inp('fix', c.fix, 1, ['고정비 ', '억'])}
      </div>
      <p class="fd-out">비용 <b>${n1(cost)}억</b> → 영업이익 <b class="${U.cls(op)}">${n1(op)}억</b> · OPM <b class="${U.cls(op)}">${c.rev ? (op / c.rev * 100).toFixed(1) : '–'}%</b>
        ${nx && nx.op != null ? ` <span class="muted">|</span> 컨센서스 ${n1(nx.op)}억 (OPM ${(nx.op / nx.sales * 100).toFixed(1)}%) → 차이 <b class="${U.cls(op - nx.op)}">${op - nx.op > 0 ? '+' : ''}${n1(op - nx.op)}억</b>` : ''}</p>
      ${need != null ? `<p class="small muted">컨센서스 영업이익이 맞으려면 이 매출·고정비에서 원가(원재료·재고) 비율이 <b>${need.toFixed(1)}%</b> 여야 합니다 (최근 4분기 평균 ${((m.var['원가'] || 0) * 100).toFixed(1)}%${lastCogs == null ? '' : `, 직전 ${lastCogs.toFixed(1)}%`}).</p>` : ''}</div>`;
  }

  function draw(el) {
    const s = st.get(el), d = s.d, i = s.sel, e = d.q[i];
    const j1 = i - 1, j4 = d.q.indexOf(prevYear(e));
    const b1 = bridge(d, i, j1), b4 = bridge(d, i, j4);
    el.innerHTML = `<section class="st-sec fd-sec">
      <div class="st-sec-head"><h3>비용 구조 <small class="muted">성격별 비용 · ${d.basis} · 분기(3개월) · DART 정기보고서 주석</small></h3>
        <div class="fd-ctl">
          <div class="seg">${[['grp', '묶음'], ['raw', '원본 줄']].map(([k, l]) => `<button data-fm="${k}" class="${s.mode === k ? 'on' : ''}">${l}</button>`).join('')}</div>
          <div class="seg">${[['amt', '금액'], ['pct', '매출 대비 %']].map(([k, l]) => `<button data-fu="${k}" class="${s.unit === k ? 'on' : ''}">${l}</button>`).join('')}</div>
          <button class="btn-copy" data-fcopy title="표를 엑셀에 붙일 수 있게 복사">복사</button>
        </div></div>
      ${tableHtml(s)}
      <p class="muted small">분기 값 = 3개월 값, 없으면 누적끼리 뺀 값(4Q = 연간 − 3Q 누적). ${d.xb.length ? `${d.ql[d.q.indexOf(d.xb[0])]} 부터는 주석 XBRL 값. ` : ''}분기 머리글을 누르면 아래가 그 분기로 바뀝니다.
        ${d.rep?.[e] ? `<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${d.rep[e]}" target="_blank" rel="noopener">${d.ql[i]} 보고서 원문 ↗</a>` : ''}
        ${Object.keys(d.chk).length ? `<span class="down"> · 검증이 어긋난 분기 ${Object.keys(d.chk).length}개 (머리글의 ! 표시)</span>` : ' · 줄의 합 = 합계, 매출 − 비용 = 영업이익 검증 통과'}</p>
      <div class="fd-brs"><div class="fd-br-head"><h4>${d.ql[i]} 영업이익률은 왜 변했나</h4><span class="muted small">비용 묶음의 매출 대비 비중 변화를 더하면 OPM 변화가 됩니다 (부호 반대)</span></div>
        <div class="fd-br-grid">${bars(b1, '직전 분기 대비', j1 >= 0 ? opm(d, j1) : null, opm(d, i))}${bars(b4, '전년 동기 대비', j4 >= 0 ? opm(d, j4) : null, opm(d, i))}</div></div>
      ${evHtml(d, e, b1.filter(([, v]) => v > 0).concat(b1.filter(([, v]) => v <= 0)))}
      ${i === d.q.length - 1 ? calcHtml(s) : ''}
    </section>`;
    const w = el.querySelector('.fd-wrap');
    if (w && !s.scrolled) { w.scrollLeft = w.scrollWidth; s.scrolled = true; } else if (w) w.scrollLeft = s.left || w.scrollWidth;
  }

  function prevYear(e) { return `${+e.slice(0, 4) - 1}${e.slice(4)}`; }

  function tsv(s) {
    const { d, mode, unit } = s;
    const rows = mode === 'grp' ? d.groups.map(g => [g.g, g.v]) : d.lines.map(l => [l.l, l.v]);
    const f = (v, i) => (v == null ? '' : unit === 'pct' ? (d.rev[i] ? (v / d.rev[i] * 100).toFixed(1) + '%' : '') : v.toFixed(1));
    return [['', ...d.ql], ['매출액', ...d.rev.map(v => (v == null ? '' : v.toFixed(1)))], ...rows.map(([l, v]) => [l, ...v.map(f)]),
      ['비용합계', ...d.tot.map(f)], ['OP', ...d.op.map(v => (v == null ? '' : v.toFixed(1)))],
      ['OPM', ...d.q.map((_, i) => { const m = opm(d, i); return m == null ? '' : m.toFixed(1) + '%'; })]].map(r => r.join('\t')).join('\n');
  }

  function bind(el) {
    if (el._fd) return;
    el._fd = true;
    el.addEventListener('click', async ev => {
      const s = st.get(el);
      if (!s) return;
      const keep = () => { s.left = el.querySelector('.fd-wrap')?.scrollLeft; };
      const m = ev.target.closest('[data-fm]'), u = ev.target.closest('[data-fu]'), q = ev.target.closest('[data-fq]'), c = ev.target.closest('[data-fcopy]');
      if (m) { keep(); s.mode = m.dataset.fm; draw(el); }
      else if (u) { keep(); s.unit = u.dataset.fu; draw(el); }
      else if (q) { keep(); s.sel = +q.dataset.fq; draw(el); }
      else if (c) {
        try { await navigator.clipboard.writeText(tsv(s)); c.textContent = '복사됨 ✓'; } catch (e) { c.textContent = '복사 실패'; }
        setTimeout(() => { c.textContent = '복사'; }, 1500);
      }
    });
    el.addEventListener('change', ev => {
      const s = st.get(el), k = ev.target.dataset.fc;
      if (!s || !k) return;
      s.calc[k] = +ev.target.value || 0;
      s.left = el.querySelector('.fd-wrap')?.scrollLeft;
      draw(el);
    });
  }

  function render(el, d) {
    if (!d || !d.q?.length) { el.innerHTML = ''; return; }
    st.set(el, { d, mode: 'grp', unit: 'amt', sel: d.q.length - 1 });
    bind(el);
    draw(el);
  }

  return { load, render };
})();
