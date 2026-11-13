// 전략 트래커: data/st/summary.json (전략별 방법·최근 호 요약·지금 구성, 일별 누적·기간별 성과·신호 성적) + data/st/{전략}.json (지금 보유·최근 글)
(() => {
  const DEFAULTS = { per: '1y', bm: 'k', view: 'cum', hold: '60', s: '', x: '' };
  const BM = { k: '코스피', q: '코스닥' };
  const PERS = [['3m', '3개월', 63], ['6m', '6개월', 125], ['1y', '1년', 250], ['3y', '3년', 750], ['all', '전체', null]];
  const COLORS = ['#3182f6', '#f08a24', '#14a39a', '#d6457a', '#8b5cf6', '#65a30d', '#0ea5c4', '#c2410c'];
  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, () => render());
  const st = pg.state;
  let S = null, T = 0;
  const detail = {};

  const pct = (v, nd = 1) => (v == null ? '–' : `${v > 0 ? '+' : ''}${(+v).toFixed(nd)}%`);
  const pp = (v, nd = 1) => (v == null ? '–' : `${v > 0 ? '+' : ''}${(+v).toFixed(nd)}%p`);
  const dot = d => (d ? d.slice(2).replace(/-/g, '.') : '');
  const e2p = v => (Math.exp(v / 1e4) - 1) * 100;      // 누적 로그(×1만) → %

  // 전략 × 방향(살 종목 L / 피할 종목 S)마다 선 하나
  function tracks() {
    const out = [];
    S.series.forEach((s, i) => {
      for (const side of s.sides) {
        const h = s.kind === 'port' ? '0' : st.hold;
        const t = s.tracks[side] && s.tracks[side][h];
        if (!t) continue;
        out.push({ id: `${s.k}.${side}`, s, side, h, t, color: COLORS[i % COLORS.length], dash: side === 'S',
          label: s.l + (side === 'S' ? ' · 피할 종목' : s.sides.length > 1 ? ' · 살 종목' : '') });
      }
    });
    return out;
  }
  const flips = () => new Set(st.x ? st.x.split(',') : []);
  const shown = tr => (tr.side === 'L') !== flips().has(tr.id);       // 기본: 살 종목만 보인다
  const winLen = () => PERS.find(p => p[0] === st.per)[2];
  const W = tr => tr.t.w[st.per] || tr.t.w.all;

  function renderFilters() {
    $('filters').innerHTML = `
      <div class="frow"><span class="flabel">기간</span>${pg.seg('per', PERS.map(p => [p[0], p[1]]))}
        <span class="flabel">비교 지수</span>${pg.seg('bm', Object.entries(BM))}
        <span class="flabel">보기</span>${pg.seg('view', [['cum', '누적 수익', '전략과 지수를 같은 출발점에서 비교'], ['rel', '지수 대비', '전략 수익에서 지수 수익을 뺀 누적 — 올라가면 지수를 이기는 중']])}
        <span class="flabel">신호형 보유 기간</span>${pg.seg('hold', S.holds.map(h => [String(h), `${h}거래일`, `글에 실린 종목을 ${h}거래일 들고 간다고 가정 (신호형 전략에만 적용)`]))}</div>`;
  }

  // 창 안에서 선 하나의 값(%) — 누적: 늦게 시작한 전략은 그날의 지수 선 위에서 출발한다 / 지수 대비: 보유 종목이 없는 날은 지수도 쉰 것으로
  function lineOf(tr, a) {
    const { i0, nav, n } = tr.t, bm = S.bm[st.bm];
    const b = Math.max(a, i0 - 1);
    const at = i => (i >= i0 ? nav[i - i0] : 0);
    const vals = new Array(T - a).fill(null);
    if (st.view === 'cum') {
      const off = bm[b] - bm[a], base = at(b);
      for (let i = b; i < T; i++) vals[i - a] = e2p(off + at(i) - base);
    } else {
      let acc = 0;
      vals[b - a] = 0;
      for (let i = b + 1; i < T; i++) {
        const k = n[i - i0], inv = tr.s.kind === 'signal' ? Math.min(k, S.min_n) / S.min_n : k > 0 ? 1 : 0;   // 그날 투자한 비율만큼만 지수를 뺀다
        acc += (at(i) - at(i - 1)) - inv * (bm[i] - bm[i - 1]);
        vals[i - a] = e2p(acc);
      }
    }
    return { vals, b };
  }

  function renderChart() {
    const all = tracks(), vis = all.filter(shown);
    const len = winLen();
    const first = Math.min(...(vis.length ? vis : all).map(tr => tr.t.i0 - 1));
    const a = Math.max(0, len == null ? first : T - 1 - len);
    const days = S.days.slice(a), n = days.length;
    const lines = vis.map(tr => ({ tr, ...lineOf(tr, a) }));
    const bms = st.view === 'cum' ? Object.keys(BM).map(k => ({ k, vals: S.bm[k].slice(a).map(v => e2p(v - S.bm[k][a])) })) : [];
    $('chart').innerHTML = `<div class="sec-head"><div><h2>${st.view === 'cum' ? '전략별 누적 수익' : `${BM[st.bm]} 대비 누적 초과수익`}</h2>
        <p class="muted small">${dot(days[0])} ~ ${dot(S.end)} · ${st.view === 'cum'
    ? `창 안에서 늦게 시작한 전략은 그날의 ${BM[st.bm]} 선 위에서 출발 → ${BM[st.bm]} 선보다 위에 있으면 이긴 것`
    : `0 위로 올라가면 ${BM[st.bm]}를 이기는 중 · 보유 종목이 없는 날은 지수도 쉰 것으로 계산`}</p></div></div>
      <div class="sg-legend">${all.map(tr => `<button class="sg-leg${shown(tr) ? ' on' : ''}" data-flip="${tr.id}" title="눌러서 선 켜기·끄기"><i style="--c:${tr.color}" class="${tr.dash ? 'dash' : ''}"></i>${U.esc(tr.label)}</button>`).join('')}
        ${st.view === 'cum' ? `<span class="sg-leg static"><i style="--c:var(--text)"></i>코스피</span><span class="sg-leg static"><i style="--c:var(--muted)" class="dash"></i>코스닥</span>` : ''}</div>
      <div class="bt-plot"></div>`;
    const ticks = [];
    const byYear = n > 520;
    days.forEach((d, i) => {
      if (!i) return;
      const cut = byYear ? 4 : 7;
      if (d.slice(0, cut) !== days[i - 1].slice(0, cut)) ticks.push([i, byYear ? `'${d.slice(2, 4)}` : `${+d.slice(5, 7)}월`]);
    });
    const step = Math.ceil(ticks.length / ($('chart').clientWidth < 620 ? 6 : 12));
    Plot.chart($('chart').querySelector('.bt-plot'), {
      n, height: 380, uid: 'sg',
      panes: [{ h: 1, zero: true, fmt: v => `${v > 0 ? '+' : ''}${Math.round(v)}%`, series: [
        ...bms.map(b => ({ type: 'line', values: b.vals, color: b.k === 'k' ? 'var(--text)' : 'var(--muted)', width: b.k === st.bm ? 1.8 : 1.1, dash: b.k === 'q', nodot: true })),
        ...lines.map(l => ({ type: 'line', values: l.vals, color: l.tr.color, width: l.tr.id === st.s ? 2.6 : 1.7, dash: l.tr.dash, last: true }))] }],
      xTicks: ticks.filter((_, i) => i % step === 0),
      tip: i => `<div class="tt-h">${dot(days[i])}</div>${lines.filter(l => l.vals[i] != null).sort((p, q) => q.vals[i] - p.vals[i])
        .map(l => `<div><i style="--c:${l.tr.color}"></i>${U.esc(l.tr.label)}<b>${pct(l.vals[i])}</b></div>`).join('')}
        ${bms.map(b => `<div class="muted"><i style="--c:${b.k === 'k' ? 'var(--text)' : 'var(--muted)'}"></i>${BM[b.k]}<b>${pct(b.vals[i])}</b></div>`).join('')}`,
    });
  }

  function renderBoard() {
    const rows = tracks().map(tr => ({ tr, w: W(tr) })).map(r => ({ ...r, ex: r.w.ret - r.w[st.bm] }))
      .sort((p, q) => (p.tr.side === q.tr.side ? q.ex - p.ex : p.tr.side === 'L' ? -1 : 1));
    const len = winLen();
    $('board').innerHTML = `<div class="col-head bt-rhead"><div><h3>전략 성적표 <span class="muted">${PERS.find(p => p[0] === st.per)[1]} · ${BM[st.bm]} 대비</span></h3>
        <p class="muted small">전략이 고른 종목을 규칙대로 사서 들고 간 수익률과, 같은 기간 ${BM[st.bm]} 수익률입니다. 기간보다 늦게 시작한 전략은 시작일부터 셉니다.
          "피할 종목"은 SHORT 판정 종목을 샀다고 가정한 것이라 <b>낮을수록 판정이 맞은 것</b>입니다. 줄을 누르면 아래에 그 전략의 종목이 나옵니다.</p></div></div>
      <div class="tbl-wrap bt-rwrap"><table class="tbl bt-rank sg-board">
        <thead><tr><th>전략</th><th>방식</th><th class="num">수익률</th><th class="num">${BM[st.bm]}</th><th class="num">차이</th><th class="num">최대 낙폭</th>
          <th class="num" title="한 달 수익률이 ${BM[st.bm]}보다 높았던 달">이긴 달</th><th class="num">지금 보유</th><th>계산 시작</th><th>최근 글</th></tr></thead>
        <tbody>${rows.map(({ tr, w, ex }) => {
    const s = tr.s, short = len != null && w.days < len - 5;
    const wins = st.bm === 'k' ? w.wk : w.wq;
    return `<tr class="bt-row${tr.id === st.s ? ' on' : ''}${tr.side === 'S' ? ' sg-short' : ''}" data-track="${tr.id}">
            <td><i class="sg-dot${tr.dash ? ' dash' : ''}" style="--c:${tr.color}"></i><b>${U.esc(tr.label)}</b><small class="muted"> ${U.esc(s.house)}</small></td>
            <td class="muted small">${s.kind === 'port' ? `${s.cycle}마다 교체` : `${tr.h}거래일 보유`}</td>
            <td class="num"><b class="${U.cls(w.ret)}">${pct(w.ret)}</b></td><td class="num">${pct(w[st.bm])}</td>
            <td class="num" data-v="${ex}"><b class="${U.cls(ex)}">${pp(ex)}</b></td><td class="num down">${pct(w.mdd)}</td>
            <td class="num">${wins}/${w.nm}</td><td class="num">${tr.t.now}종목</td>
            <td class="muted small">${dot(w.from)}${short ? ' <span title="고른 기간보다 짧음">(짧음)</span>' : ''}</td>
            <td class="muted small">${dot(s.last)}${s.pend ? ' · 매수 예정' : ''}</td></tr>`;
  }).join('')}</tbody></table></div>`;
  }

  // 전략이 지금 무엇을 담고 있는지 한두 줄로
  function compLine(s) {
    const c = s.comp || {};
    const list = (a, n) => a.slice(0, n).map(U.esc).join(', ') + (a.length > n ? ` 외 ${a.length - n}` : '');
    const out = [];
    if (c.stats) {
      out.push(`<b>최근 20거래일 판정 ${c.stats.all}건</b> · 롱 ${c.stats.L} · 숏 ${c.stats.S} · 판정 없음 ${c.stats.all - c.stats.L - c.stats.S}`);
      if (c.names.length) out.push(`<span class="up">롱</span> ${list(c.names, 6)}`);
      if (c.short.length) out.push(`<span class="down">숏</span> ${list(c.short, 6)}`);
      return out;
    }
    if (c.groups) {
      out.push(`<b>${c.n}종목</b> · ${c.groups.map(g => `${U.esc(g[0])} ${g[1]}%`).join(' · ')}`);
      out.push(`비중 상위 ${c.top.map(t => `${U.esc(t[0])} ${t[1]}%`).join(', ')}`);
    } else if (c.blocks) {
      out.push(`<b>${c.n}종목</b>`);
      c.blocks.forEach(b => out.push(`<span class="muted">${U.esc(b[0])}</span> ${list(b[1], 6)}`));
    } else if (c.short) {
      out.push(`<span class="up">롱 ${c.n}</span> ${c.names.length ? list(c.names, 8) : '없음'}`);
      out.push(`<span class="down">숏 ${c.ns}</span> ${list(c.short, 8)} <span class="muted">(★ 강한 확신)</span>`);
    } else if (c.names) {
      out.push(`<b>${c.n}종목</b> ${list(c.names, 10)}`);
    }
    if (c.add && (c.add.length || c.del.length)) {
      out.push(`${c.add.length ? `<span class="muted">새로 넣음</span> ${list(c.add, 5)}` : ''}${c.add.length && c.del.length ? ' · ' : ''}${c.del.length ? `<span class="muted">뺌</span> ${list(c.del, 5)}` : ''}`);
    }
    return out;
  }
  const title = t => t.replace(/^\[(?:DAOL퀀트 김경훈|실전 퀀트\(Quant MP\)|QWER)\]\s*/, '').replace('포커 s', '포커스');
  function latestHtml(s) {
    const n = s.note;
    if (!n) return s.k === 'daol_bu' ? '' : `<div class="sg-latest"><span class="sg-lbl">최근 호 ${dot(s.last)}</span> <a href="${U.esc(s.last_u)}" target="_blank" rel="noopener">${U.esc(title(s.last_t))}</a></div>`;
    return `<div class="sg-latest"><span class="sg-lbl">최근 호 ${dot(n.d)}</span> <a href="${U.esc(n.u)}" target="_blank" rel="noopener">${U.esc(title(n.t))}</a>
      <p>${U.esc(n.x)}</p>${n.d < s.last ? `<p class="muted small">이 뒤에 새 글이 있습니다 (${dot(s.last)}). 요약은 ${dot(n.d)} 글 기준.</p>` : ''}</div>`;
  }

  function renderCards() {
    const trs = tracks().filter(tr => tr.side === 'L');
    $('cards').innerHTML = trs.map(tr => {
      const s = tr.s, w = W(tr), ex = w.ret - w[st.bm];
      return `<article class="card sg-card${tr.id === st.s ? ' on' : ''}" data-track="${tr.id}">
        <header><i class="sg-dot" style="--c:${tr.color}"></i><b>${U.esc(s.l)}</b><small class="muted">${U.esc(s.house)} · ${U.esc(s.cycle)}${s.kind === 'port' ? '마다 교체' : ''}</small></header>
        <p class="sg-how">${U.esc(s.how)}</p>
        ${latestHtml(s)}
        <div class="sg-comp"><span class="sg-lbl">지금 구성${s.comp && s.comp.as && !s.comp.stats ? ` ${dot(s.comp.as)}` : ''}</span>${compLine(s).map(x => `<p>${x}</p>`).join('')}</div>
        <footer><span>${PERS.find(p => p[0] === st.per)[1]} <b class="${U.cls(w.ret)}">${pct(w.ret)}</b></span><span>${BM[st.bm]} 대비 <b class="${U.cls(ex)}">${pp(ex)}</b></span><span class="muted">자세히 ↓</span></footer>
      </article>`;
    }).join('');
  }

  const kpi = (lbl, v, cls = '', sub = '') => `<div><span>${lbl}</span><b class="${cls}">${v}</b>${sub ? `<small>${sub}</small>` : ''}</div>`;
  const chip = (x, extra) => `<span class="chip" ${Stock.hintAttr(x)}>${Stock.link(x)}${extra}</span>`;
  const xOf = x => (st.bm === 'k' ? x.xk : x.xq);

  function evTable(s) {
    const sides = s.sides.filter(sd => s.ev[sd] && Object.keys(s.ev[sd]).length);
    if (!sides.length) return '';
    const cell = (e, k) => (e ? `<td class="num"><span class="${U.cls(e[k])}">${k.startsWith('w') ? `${e[k]}%` : pct(e[k])}</span></td>` : '<td class="num muted">–</td>');
    const x = `x${st.bm}`, w = `w${st.bm}`;
    return `<h3 class="bt-h3">신호 하나하나의 성적 <span class="muted small">글에 실린 뒤 N거래일 동안 · ${BM[st.bm]} 대비는 같은 기간 지수 등락을 뺀 값 · 비용 제외</span></h3>
      <div class="tbl-wrap"><table class="tbl sg-ev"><thead><tr><th>구분</th><th class="num">보유</th><th class="num">신호 수</th><th class="num">평균 수익</th><th class="num">중간값</th>
        <th class="num">${BM[st.bm]} 대비 평균</th><th class="num">${BM[st.bm]} 이긴 비율</th></tr></thead><tbody>
      ${sides.map(sd => S.holds.map(h => {
    const e = s.ev[sd][h];
    return `<tr><td>${sd === 'L' ? '살 종목' : '피할 종목'}</td><td class="num">${h}거래일</td><td class="num">${e ? e.n.toLocaleString() : '–'}</td>
          ${cell(e, 'avg')}${cell(e, 'med')}${cell(e, x)}${cell(e, w)}</tr>`;
  }).join('')).join('')}
      ${sides.length === 2 ? S.holds.map(h => {
    const l = s.ev.L[h], r = s.ev.S[h];
    return l && r ? `<tr class="sg-ls"><td>살 종목 − 피할 종목</td><td class="num">${h}거래일</td><td class="num"></td>
          <td class="num"><b class="${U.cls(l.avg - r.avg)}">${pp(l.avg - r.avg)}</b></td><td class="num"><span class="${U.cls(l.med - r.med)}">${pp(l.med - r.med)}</span></td><td></td><td></td></tr>` : '';
  }).join('') : ''}</tbody></table></div>`;
  }

  async function renderDetail() {
    const box = $('detail');
    const tr = tracks().find(t => t.id === st.s);
    if (!tr) { box.innerHTML = ''; return; }
    const s = tr.s;
    if (!detail[s.k]) {
      box.innerHTML = '<p class="msg">불러오는 중…</p>';
      try { detail[s.k] = await U.json(`data/st/${s.k}.json`); } catch (e) {
        box.innerHTML = `<p class="msg">불러오지 못했습니다. (${e.message})</p>`;
        return;
      }
      if (st.s !== tr.id) return;
    }
    const d = detail[s.k];
    const rule = s.kind === 'port'
      ? `글이 올라오면 살 수 있는 첫 종가에 목록 전체를 사고, 다음 호가 나오면 바꿉니다. 다음 호가 ${S.stale[s.k]}거래일 넘게 없으면 팝니다.`
      : `글에 실린 종목을 살 수 있는 첫 종가에 사서 ${tr.h}거래일 뒤 팝니다. 보유 중인 종목은 매일 같은 비중이고, 종목당 최대 1/${S.min_n} (종목이 ${S.min_n}개 미만이면 나머지는 현금).`;
    let hold = '';
    if (s.kind === 'port') {
      const now = d.now && d.now[tr.side];
      if (now && now.list.length) {
        hold = `<h3 class="bt-h3">지금 들고 있는 종목 <span class="muted small">${now.list.length}개 · ${dot(now.as)} 글 기준 · ${dot(now.buy)} 종가 매수${now.stale ? ' · <b>다음 호가 늦어 판 상태</b>' : ''} · 편입일 / 편입 뒤 수익률 (${BM[st.bm]} 대비)</span></h3>
          <div class="bt-chips">${now.list.map(x => chip(x, `${x.w ? `<small class="muted">${x.w}%</small>` : ''}<small class="muted">${dot(x.d)}</small>
            <small class="${U.cls(x.r)}">${pct(x.r)}</small><small class="${U.cls(xOf(x))}">(${pp(xOf(x))})</small>`)).join('')}</div>
          ${now.add.length || now.del.length ? `<p class="muted small sg-chg">지난 호 대비 ${now.add.length ? `<b>새로 넣음</b> ${now.add.map(U.esc).join(', ')}` : ''}${now.add.length && now.del.length ? ' · ' : ''}${now.del.length ? `<b>뺌</b> ${now.del.map(U.esc).join(', ')}` : ''}</p>` : ''}`;
      } else hold = '<p class="muted small bt-now">지금은 들고 있는 종목이 없습니다 (최근 호에 해당 방향 종목 없음).</p>';
      if (d.pend) {
        const pl = d.pend.list.filter(x => x.s === tr.side);
        hold += `<p class="muted small sg-chg"><b>다음 거래일 종가에 교체 예정</b> (${dot(d.pend.as)} 글) · ${pl.length}종목${pl.length ? `: ${pl.slice(0, 30).map(x => U.esc(x.n)).join(', ')}` : ''}</p>`;
      }
    } else {
      const act = d.sig.filter(x => x.s === tr.side && (x.age == null || x.age < +tr.h));
      const seen = new Set();
      const uniq = act.filter(x => !seen.has(x.c) && seen.add(x.c));     // 같은 종목이 여러 번 실렸으면 가장 최근 것
      hold = uniq.length ? `<h3 class="bt-h3">지금 들고 있는 종목 <span class="muted small">${uniq.length}개 · 최근 ${tr.h}거래일 안에 실린 종목 · 실린 날 / 매수 뒤 수익률 (${BM[st.bm]} 대비)</span></h3>
        <div class="bt-chips">${uniq.map(x => chip(x, `${x.g ? `<small class="muted">${U.esc(x.g.replace('CONVICTION ', '강한 ').replace('LONG', '롱').replace('SHORT', '숏'))}</small>` : ''}<small class="muted">${dot(x.d)}</small>
          ${x.b == null ? '<small class="muted">매수 예정</small>' : x.r == null ? '' : `<small class="${U.cls(x.r)}">${pct(x.r)}</small><small class="${U.cls(xOf(x))}">(${pp(xOf(x))})</small>`}`)).join('')}</div>`
        : '<p class="muted small bt-now">지금은 들고 있는 종목이 없습니다.</p>';
    }
    const wins = PERS.filter(p => tr.t.w[p[0]]);
    box.innerHTML = `<div class="sec-head"><div><h2><i class="sg-dot${tr.dash ? ' dash' : ''}" style="--c:${tr.color}"></i>${U.esc(tr.label)}</h2>
        <p class="muted small">${U.esc(s.d)} · 출처: ${U.esc(s.src)} · ${dot(s.first)}부터 ${s.docs.toLocaleString()}건</p>
        <p class="muted small">${rule} ${tr.side === 'S' ? '피할 종목 묶음은 비용 없이 계산.' : `살 때·팔 때 각 ${S.cost}% 비용.`}</p></div></div>
      <div class="sg-about"><div><span class="sg-lbl">무엇을 어떻게 고르나</span><p>${U.esc(s.how)}</p></div>${latestHtml(s)}</div>
      <div class="tbl-wrap"><table class="tbl sg-win"><thead><tr><th>기간</th><th class="num">수익률</th><th class="num">${BM[st.bm]}</th><th class="num">차이</th><th class="num">최대 낙폭</th><th class="num">이긴 달</th><th>계산 시작</th></tr></thead>
        <tbody>${wins.map(p => {
    const w = tr.t.w[p[0]], ex = w.ret - w[st.bm];
    return `<tr class="${p[0] === st.per ? 'on' : ''}"><td>${p[1]}</td><td class="num"><b class="${U.cls(w.ret)}">${pct(w.ret)}</b>${w.cagr != null && p[0] === 'all' ? `<small class="muted"> 연 ${pct(w.cagr)}</small>` : ''}</td>
            <td class="num">${pct(w[st.bm])}</td><td class="num"><b class="${U.cls(ex)}">${pp(ex)}</b></td><td class="num down">${pct(w.mdd)}</td>
            <td class="num">${st.bm === 'k' ? w.wk : w.wq}/${w.nm}</td><td class="muted small">${dot(w.from)}</td></tr>`;
  }).join('')}</tbody></table></div>
      ${evTable(s)}
      ${hold}
      <h3 class="bt-h3">최근 글 <span class="muted small">제목을 누르면 원문</span></h3>
      <div class="sg-docs">${d.docs.filter(x => s.sides.length < 2 || s.kind === 'port' || x.s.includes(tr.side)).slice(0, 12).map(x => `<a href="${U.esc(x.u)}" target="_blank" rel="noopener"><span class="muted">${dot(x.d)}</span> ${U.esc(title(x.t))} <small class="muted">${s.k === 'daol_bu' ? (x.s === 'L' ? '롱' : '숏') : `${x.n}종목`}</small></a>`).join('')}</div>`;
  }

  function renderFoot() {
    $('foot').innerHTML = `
      <p><b>읽는 법</b> · 리포트·채널 글에서 종목과 방향만 뽑아 "그대로 따라 샀다면"을 계산합니다. 네이버에 올라온 리포트는 게시일 <b>다음 거래일 종가</b>에, 텔레그램 글은 ${S.cutoff} 전이면 그날 종가, 아니면 다음 거래일 종가에 산다고 가정합니다.
        포트폴리오형은 리포트의 비중 그대로(없으면 같은 금액), 신호형은 보유 중인 종목을 매일 같은 비중으로 듭니다(종목당 최대 1/${S.min_n}, 모자라면 현금). 지수와 견줄 때는 그날 투자한 비율만큼만 지수를 셉니다. 살 때·팔 때 각 ${S.cost}% 비용. 지수는 종가 등락률이고 배당은 양쪽 다 뺐습니다.</p>
      <p><b>주의</b> · 증권사·애널리스트가 직접 운용한 성과가 아니라, 공개된 글을 기계적으로 따라 한 가정입니다. 네이버에 리포트를 올리지 않는 증권사는 빠져 있고, 대부분 2025년 이후라 기간이 짧습니다.
        종목 추출은 자동이라 일부 호는 표를 읽지 못해 빠집니다. 원문은 각 전략의 "최근 글"에서 확인하세요. 투자 권유가 아닙니다. ${S.built.replace('T', ' ').slice(0, 16)} 계산.</p>`;
  }

  function render() {
    renderCards();
    renderFilters();
    renderChart();
    renderBoard();
    renderDetail();
    renderFoot();
  }

  $('chart').addEventListener('click', e => {
    const b = e.target.closest('[data-flip]');
    if (!b) return;
    const f = flips();
    if (f.has(b.dataset.flip)) f.delete(b.dataset.flip); else f.add(b.dataset.flip);
    pg.set({ x: [...f].join(',') });
  });
  $('board').addEventListener('click', e => {
    const r = e.target.closest('[data-track]');
    if (!r) return;
    const patch = { s: r.dataset.track };
    const tr = tracks().find(t => t.id === patch.s);
    if (tr && !shown(tr)) { const f = flips(); if (f.has(tr.id)) f.delete(tr.id); else f.add(tr.id); patch.x = [...f].join(','); }   // 고른 전략은 차트에도 켠다
    pg.set(patch);
  });

  $('cards').addEventListener('click', e => {
    if (e.target.closest('a')) return;      // 원문 링크는 그대로 연다
    const c = e.target.closest('[data-track]');
    if (!c) return;
    pg.set({ s: c.dataset.track });
    $('detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  pg.bind($('filters'));
  U.initTheme($('theme'));
  (async () => {
    try {
      S = await U.json('data/st/summary.json');
    } catch (e) {
      $('msg').textContent = `전략 데이터를 불러오지 못했습니다. (${e.message})`;
      return;
    }
    T = S.days.length;
    $('msg').hidden = true;
    $('asof').textContent = `${dot(S.end)}까지`;
    if (!S.holds.map(String).includes(st.hold)) st.hold = DEFAULTS.hold;
    if (!tracks().some(t => t.id === st.s)) {
      const best = tracks().filter(t => t.side === 'L').sort((p, q) => (W(q).ret - W(q)[st.bm]) - (W(p).ret - W(p)[st.bm]))[0];
      if (best) st.s = best.id;
    }
    render();
  })();
})();
