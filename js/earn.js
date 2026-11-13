// 공시 탭 · 실적 발표 덱: data/earn/{발표일}.json (카드) · data/earn/stats.json (과거 반응 평균)
// 출처: @darthacking 실적 글(감지 시각·예상치) + KIS 통합 1분봉 + 일봉. build_earn.py 참고
// dart.js 가 EarnDeck.show(날짜, 필터 상태)를 부른다
const EarnDeck = (() => {
  const CASE_COLOR = { both: '#d6453d', op: '#f08c00', sales: '#8a63d2', miss: '#3a6fd8', inline: '#8b95a1' };
  const SS = [['all', '전체'], ['장전', '장전'], ['장중', '장중'], ['장후', '장후']];
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };
  const $ = id => document.getElementById(id);
  let day = null, cards = null, stats = null, opt = {}, ss = 'all', xs = false, cur = '';

  const pct = (v, d = 1) => (v == null ? '–' : `${v > 0 ? '+' : ''}${(v * 100).toFixed(d)}%`);
  const pc = (v, d = 1) => `<b class="${U.cls(v)}">${pct(v, d)}</b>`;
  const eok = v => (v == null ? '–' : `${Math.round(v).toLocaleString('ko-KR')}억`);
  const hm = ts => ts.slice(11, 16);

  // 미니 차트: 5분 종가, 기준가 가로선, 발표 시각 세로선, 장후면 날짜 경계
  function spark(ch) {
    if (!ch?.p?.length) return '<div class="ed-nochart muted small">분봉 없음</div>';
    const W = 300, H = 64, p = ch.p, vals = p.map(x => x[2]);
    const lo = Math.min(...vals, ch.base ?? Infinity), hi = Math.max(...vals, ch.base ?? -Infinity), span = hi - lo || 1;
    const X = i => (i / Math.max(1, p.length - 1)) * W, Y = v => H - 3 - ((v - lo) / span) * (H - 6);
    const pts = p.map((x, i) => `${X(i).toFixed(1)},${Y(x[2]).toFixed(1)}`).join(' ');
    const split = p.findIndex(x => x[0] === 1);
    const last = vals[vals.length - 1];
    const up = ch.base ? last >= ch.base : last >= vals[0];
    const lab = (i, t) => `<text x="${Math.min(W - 24, Math.max(0, X(i) - 12)).toFixed(1)}" y="${H - 1}" class="ed-xl">${t}</text>`;
    return `<svg class="ed-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      ${ch.base ? `<line x1="0" x2="${W}" y1="${Y(ch.base).toFixed(1)}" y2="${Y(ch.base).toFixed(1)}" class="b"/>` : ''}
      ${split > 0 ? `<line x1="${X(split).toFixed(1)}" x2="${X(split).toFixed(1)}" y1="0" y2="${H}" class="d"/>` : ''}
      <line x1="${X(ch.at).toFixed(1)}" x2="${X(ch.at).toFixed(1)}" y1="0" y2="${H}" class="t0"/>
      <polyline points="${pts}" class="${up ? 'up' : 'dn'}"/></svg>
      <div class="ed-ax small muted"><span>${p[0][1].slice(0, 2)}:${p[0][1].slice(2)}</span>${split > 0 ? `<span>다음 날 ${p[split][1].slice(0, 2)}:${p[split][1].slice(2)}</span>` : ''}<span>${p[p.length - 1][1].slice(0, 2)}:${p[p.length - 1][1].slice(2)}</span></div>`;
  }

  function vsEst(label, a, e, r, t) {
    if (a == null) return '';
    const flip = e != null && Math.sign(a) !== Math.sign(e) && e !== 0;
    const d = e == null ? '<small class="muted">예상 없음</small>'
      : `<small class="muted">예상 ${eok(e)}</small> <b class="${t === 'beat' ? 'up' : t === 'miss' ? 'down' : 'muted'}">${flip ? (a > 0 ? '흑전' : '적전') : pct(r)}</b>`;
    return `<span>${label} <b class="${a < 0 ? 'down' : ''}">${eok(a)}</b> ${d}</span>`;
  }

  // 대표 반응: 장중·장전 = 반응일 종가(분봉 기준가 대비), 장후 = 다음 날 종가. 분봉이 없으면 일봉 반응일
  function headline(c) {
    const m = c.mr || {}, d = c.dr || {};
    const v = m.close ?? d.d0;
    const lab = c.ss === '장후' ? '다음 날' : '당일';
    return [v, lab];
  }

  function cardHtml(c) {
    const m = c.mr || {}, d = c.dr || {};
    const [hv, hl] = headline(c);
    const steps = c.ss === '장중' ? [['+5분', m.m5], ['+30분', m.m30], ['+60분', m.m60], ['종가', m.close]]
      : c.ss === '장후' ? [['시간외 +5분', m.m5], ['시간외 +30분', m.m30], ['시간외 마지막', m.nxt], ['다음 날 시가', m.open], ['다음 날 종가', m.close]]
        : [['장 전 시간외', m.nxt], ['시가', m.open], ['09:30', m.m30], ['종가', m.close]];
    return `<article class="row ed-card" ${Stock.hintAttr(c)} style="--cc:${CASE_COLOR[c.case]}">
      <div class="r-main">
        <div class="r-top">
          <div class="r-name">${Stock.link(c)}<span class="muted">${c.mc != null ? U.eok(c.mc) : ''}</span>
            <span class="badge" title="${U.esc(c.ts)} (채널이 공시를 잡은 시각)">${c.ss} ${hm(c.ts)}</span><span class="tag">${c.rep}${c.per ? ` ${c.per.replace('Q', ' ')}Q` : ''}</span></div>
          <div class="r-growth"><small>${hl} 반응</small>${pc(hv)}</div>
        </div>
        <div class="r-line ed-vs">${vsEst('매출', c.s, c.se, c.sr, c.st)}${vsEst('영업익', c.o, c.oe, c.or, c.ot)}</div>
        ${spark(c.ch)}
        <div class="r-sub ed-steps">${steps.filter(([, v]) => v !== undefined).map(([l, v]) => `<span>${l} ${pc(v)}</span>`).join('')}
          ${d.d1 !== undefined ? `<span>D+1 ${pc(d.d1)}</span><span>D+5 ${pc(d.d5)}</span>` : ''}
          ${c.rcp ? `<a class="muted" href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${c.rcp}" target="_blank" rel="noopener">원문 ↗</a>` : ''}</div>
      </div>
    </article>`;
  }

  function filtered() {
    const q = (opt.q || '').trim().toLowerCase(), cap = CAPS[opt.cap];
    return (cards || []).filter(c => (opt.market === 'all' || !opt.market || c.mk === opt.market)
      && (!cap || (c.mc != null && c.mc >= cap[0] && c.mc < cap[1]))
      && (!q || c.n.toLowerCase().includes(q) || c.c.includes(q)));
  }

  function renderDeck() {
    const box = $('earn-deck');
    if (!cards?.length) { box.innerHTML = ''; box.hidden = true; return; }
    box.hidden = false;
    const list = filtered();
    const cases = (stats?.cases || [['both', '동반 서프'], ['op', '영업이익 서프'], ['sales', '매출 서프'], ['miss', '영업이익 미스'], ['inline', '부합']]);
    const th = stats?.th || { sales: 0.05, op: 0.1 };
    box.innerHTML = `<div class="sec-title"><h2>실적 발표 덱 <span class="muted small">${U.dateLabel(day)} · 예상치가 있는 첫 발표 ${cards.length}건${list.length !== cards.length ? ` · 보이는 것 ${list.length}` : ''}</span></h2>
        <span class="muted small">매출 ±${th.sales * 100}% · 영업이익 ±${th.op * 100}%(흑적자 전환 포함)로 판정 · 미니 차트 세로선 = 발표 시각, 가로선 = 기준가</span></div>
      <section class="sig-deck ed-deck">${cases.map(([k, label]) => {
        const items = list.filter(c => c.case === k);
        if (!items.length) return '';
        return `<div class="col"><div class="col-head"><h3><i class="ed-dot" style="background:${CASE_COLOR[k]}"></i>${label} <span class="muted">${items.length}종목</span></h3></div>
          ${items.map(cardHtml).join('')}</div>`;
      }).join('')}</section>`;
  }

  // ---------- 과거 반응 통계 ----------
  function cell(s, title) {
    if (!s) return '<td class="num muted">–</td>';
    return `<td class="num" title="${title}: ${s.n}건 · 중앙값 ${s.med > 0 ? '+' : ''}${s.med}% · 오른 비율 ${s.up}%"><b class="${U.cls(s.avg)}">${s.avg > 0 ? '+' : ''}${s.avg.toFixed(1)}%</b><small class="muted">${s.up}%↑</small></td>`;
  }

  function renderStats() {
    const box = $('earn-stats');
    if (!stats) { box.hidden = true; return; }
    box.hidden = false;
    const T = stats.table;
    const dcols = xs ? [['x0', '반응일'], ['x1', 'D+1'], ['x5', 'D+5'], ['x20', 'D+20']] : [['gap', '시가 갭'], ['d0', '반응일'], ['d1', 'D+1'], ['d5', 'D+5'], ['d20', 'D+20']];
    const mcols = ss === '장후' ? [['m_m30', '시간외 +30분'], ['m_nxt', '시간외 마지막'], ['m_open', '다음 날 시가'], ['m_close', '다음 날 종가']]
      : ss === '장전' ? [['m_nxt', '장 전 시간외'], ['m_open', '시가'], ['m_close', '종가']]
        : ss === '장중' ? [['m_m5', '+5분'], ['m_m30', '+30분'], ['m_m60', '+60분'], ['m_close', '종가']] : [['m_close', '반응일 종가']];
    const open = box.open;
    box.innerHTML = `<summary><h2>서프·미스별 주가 반응 <span class="muted small">과거 평균 · 일봉 ${stats.from?.slice(0, 7)} ~ · 분봉 최근 1년 · ${stats.n.toLocaleString('ko-KR')}건</span></h2></summary>
      <div class="frow ed-ctl">
        <div class="seg" role="group">${SS.map(([k, l]) => `<button data-ess="${k}" class="${ss === k ? 'on' : ''}">${l}</button>`).join('')}</div>
        <label class="chk${xs ? ' on' : ''}" title="같은 시장 지수 수익률을 뺀 값 (일봉)"><input type="checkbox" data-exs${xs ? ' checked' : ''}> 지수 대비(초과)</label>
      </div>
      <div class="tbl-wrap"><table class="tbl ed-tbl">
        <thead><tr><th>묶음</th><th class="num">건수</th>${dcols.map(([, l]) => `<th class="num">${l}</th>`).join('')}
          <th class="num ed-sep">분봉 n</th>${mcols.map(([, l]) => `<th class="num">${l}</th>`).join('')}</tr></thead>
        <tbody>${stats.cases.map(([k, label]) => {
          const r = T[k]?.[ss];
          if (!r) return '';
          return `<tr><td><i class="ed-dot" style="background:${CASE_COLOR[k]}"></i>${label}</td><td class="num">${r.n.toLocaleString('ko-KR')}</td>
            ${dcols.map(([c, l]) => cell(r[c], l)).join('')}<td class="num ed-sep muted">${r.nm}</td>${mcols.map(([c, l]) => cell(r[c], l)).join('')}</tr>`;
        }).join('')}</tbody></table></div>
      <p class="muted small">칸 = 평균(±50%에서 자름), 작은 글씨 = 오른 비율. 일봉은 반응일 전 거래일 종가 기준(장중 발표는 발표 전 움직임도 섞임).
        분봉은 장중 = 발표 직전 체결가, 장후 = 그날 정규장 종가, 장전 = 전날 종가 기준. 장후 발표는 넥스트레이드 애프터마켓(~20:00)에서 먼저 반응합니다.</p>
      <div class="ed-path-head"><h3>장중 발표 전후 평균 경로 <span class="muted small">발표 직전 체결가 = 0, 5분 간격 · 최근 1년</span></h3>
        <div class="ed-legend small">${stats.cases.filter(([k]) => stats.paths.cases[k]).map(([k, l]) => `<span><i class="ed-dot" style="background:${CASE_COLOR[k]}"></i>${l} ${stats.paths.cases[k].n}</span>`).join('')}</div></div>
      <div class="ed-path"></div>`;
    box.open = open;
    const P = stats.paths, T2 = P.t;
    const ks = stats.cases.map(([k]) => k).filter(k => P.cases[k]);
    if (!ks.length) return;
    Plot.chart(box.querySelector('.ed-path'), {
      n: T2.length, height: 240, uid: 'edp',
      panes: [{ zero: true, fmt: v => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`, series: ks.map(k => ({ type: 'line', values: P.cases[k].v, color: CASE_COLOR[k], width: k === 'inline' ? 1.2 : 2 })) }],
      marks: [{ i: T2.indexOf(0) }],
      xTicks: T2.map((t, i) => [i, t === 0 ? '발표' : `${t > 0 ? '+' : ''}${t}분`]).filter(([, l], i) => T2[i] % 30 === 0),
      tip: i => `<div class="tt-h">발표 ${T2[i] >= 0 ? '+' : ''}${T2[i]}분</div>${ks.map(k => `<div class="tt-v"><i class="ed-dot" style="background:${CASE_COLOR[k]}"></i>${stats.cases.find(c => c[0] === k)[1]} ${P.cases[k].v[i] == null ? '–' : `${P.cases[k].v[i] > 0 ? '+' : ''}${P.cases[k].v[i].toFixed(2)}%`}</div>`).join('')}`,
    });
  }

  document.addEventListener('click', e => {
    const b = e.target.closest('[data-ess]');
    if (b) { ss = b.dataset.ess; renderStats(); }
  });
  document.addEventListener('change', e => {
    if (e.target.matches('[data-exs]')) { xs = e.target.checked; renderStats(); }
  });

  async function show(d, state) {
    opt = state || {};
    if (!stats) {
      try { stats = await U.json('data/earn/stats.json'); renderStats(); } catch (e) { stats = null; }
    }
    if (d !== cur) {
      cur = d;
      try { const j = await U.json(`data/earn/${d}.json`); day = j.date; cards = j.cards; } catch (e) { day = d; cards = null; }
    }
    renderDeck();
  }

  // 장중: 보고 있는 날짜의 카드가 바뀌면(새 발표·분봉) 다시
  async function refresh() {
    if (!cur || !U.busyHours?.()) return;
    try {
      const j = await U.fresh(`data/earn/${cur}.json`);
      if (j && j.date === cur) { cards = j.cards; renderDeck(); }
    } catch (e) { /* 다음 때 */ }
  }
  setInterval(refresh, 120000);

  return { show };
})();
