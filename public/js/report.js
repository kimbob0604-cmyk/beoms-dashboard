// 리포트 탭: data/digest/{작성일}.json — 그날 나온 증권사 종목 리포트를 종목별 카드로
(() => {
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };
  const GROUPS = {
    all: ['전체', () => true],
    up: ['목표가 상향', r => r.g && r.pg && r.g > r.pg],
    dn: ['목표가 하향', r => r.g && r.pg && r.g < r.pg],
    op: ['의견 변경', r => !!r.pop],
  };
  const SORTS = {
    n: ['리포트 많은 순', s => s.r.length * 1e6 + (s.mc || 0) / 1e6],
    chg: ['목표가 변화 큰 순', s => Math.max(...s.r.map(r => (r.g && r.pg ? Math.abs(r.g / r.pg - 1) : 0)))],
    mc: ['시총 순', s => s.mc || 0],
  };
  const SHOW = 3;   // 카드에 처음 보일 리포트 수
  const DEFAULTS = { date: '', v: 'day', wk: '0', side: 'up', g: 'all', market: 'all', cap: 'all', sort: 'n', q: '', kw: '', lone: '' };
  const VIEWS = [['day', '일별'], ['dates', '날짜별 한눈에'], ['week', '주간 핵심 리포트']];
  let idx = null, wkly = null;   // data/digest_index.json · digest_weekly.json (처음 볼 때 받음)
  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => (typing ? renderBody() : render()));
  const st = pg.state;
  let data = null;
  const open = new Set();   // '더 보기'를 연 종목

  const researchUrl = id => `https://m.stock.naver.com/research/company/${id}`;
  const chgPct = r => (r.g && r.pg ? r.g / r.pg - 1 : null);

  function filtered() {
    const q = st.q.trim().toLowerCase();
    const cap = CAPS[st.cap];
    const want = GROUPS[st.g][1];
    const kw = st.kw;
    const out = data.stocks.map(s => ({ ...s, r: s.r.filter(r => want(r) && (!kw || r.kw.includes(kw) || `${r.t} ${r.h.join(' ')} ${r.s}`.includes(kw))) }))
      .filter(s => s.r.length
        && (st.market === 'all' || s.mk === st.market)
        && (!cap || (s.mc != null && s.mc >= cap[0] && s.mc < cap[1]))
        && (!st.lone || s.lone)
        && (!q || s.n.toLowerCase().includes(q) || s.c.includes(q)));
    const key = SORTS[st.sort][1];
    return out.sort((a, b) => key(b) - key(a));
  }

  function renderFilters() {
    const views = pg.seg('v', VIEWS);
    if (st.v === 'dates') {
      $('filters').innerHTML = `<div class="frow">${views}<span class="muted small">카드를 누르면 그날 리포트로 들어갑니다</span></div>`;
      return;
    }
    if (st.v === 'week') {
      const ws = wkly ? wkly.weeks : [];
      $('filters').innerHTML = `<div class="frow">${views}<button class="btn-copy" id="copy" title="이번 주 핵심 리포트를 글로 복사">글로 복사</button></div>
        <div class="frow">${pg.seg('wk', ws.map((w, i) => [String(i), `${w.week.slice(5).replace('-', '/')}~${w.end.slice(5).replace('-', '/')}`]))}
          ${pg.seg('side', [['up', '목표가 상향 Top 10'], ['dn', '목표가 하향 Top 10']])}</div>`;
      return;
    }
    $('filters').innerHTML = `
      <div class="frow">${views}</div>
      <div class="frow">
        ${pg.seg('g', Object.entries(GROUPS).map(([k, [l]]) => [k, l]))}
        ${pg.seg('sort', Object.entries(SORTS).map(([k, [l]]) => [k, l]))}
        <button class="btn-copy" id="copy" title="보이는 리포트를 종목별 글로 복사">글로 복사</button>
      </div>
      <div class="frow">
        ${pg.seg('market', [['all', '전체'], ['KOSPI', '코스피'], ['KOSDAQ', '코스닥']])}
        ${pg.seg('cap', [['all', '시총 전체'], ['L', '1조 이상'], ['M', '3천억~1조'], ['S', '3천억 미만']])}
        <input type="search" data-q="q" placeholder="종목명·코드 검색" value="${U.esc(st.q)}" autocomplete="off">
        ${pg.chk('lone', '소외주 첫 리포트', '최근 90일 동안 리포트가 없던 종목')}
        ${st.kw ? `<button class="chip rp-kwon" data-k="kw" data-v="">키워드: ${U.esc(st.kw)} ✕</button>` : ''}
      </div>`;
  }

  function renderSummary(stocks) {
    const s = data.sum;
    const n = stocks.reduce((a, x) => a + x.r.length, 0);
    $('summary').innerHTML = `
      <div class="dt-sum-head">
        <div><h2>${DartFmt.md(data.date)} 신규 리포트 <span class="muted small">${s.n}건 · ${s.stocks}종목 · 증권사 ${s.brokers}곳 · 보이는 것 ${n}건</span></h2>
          <p class="muted small">${U.timeLabel(data.built)} 갱신 · 장중에는 10분마다 새 리포트를 받습니다</p></div>
        <div class="dt-kpis">
          <div><span>목표가 상향</span><b class="up">${s.up}</b></div>
          <div><span>목표가 하향</span><b class="down">${s.dn}</b></div>
          <div><span>유지</span><b>${s.keep}</b></div>
          <div><span>의견 변경</span><b>${s.opu + s.opd}</b></div>
          <div><span>소외주 첫 리포트</span><b>${s.lone}</b></div>
        </div>
      </div>
      ${data.kws.length ? `<div class="rp-kws"><span class="muted small">오늘 리포트들이 많이 쓴 말</span>
        ${data.kws.map(k => `<button class="chip${st.kw === k.kw ? ' on' : ''}" data-k="kw" data-v="${st.kw === k.kw ? '' : U.esc(k.kw)}" title="${U.esc(k.stocks.join(', '))}">${U.esc(k.kw)} <b>${k.n}</b></button>`).join('')}</div>` : ''}
      ${s.sec.length ? `<div class="rp-kws"><span class="muted small">업종</span>${s.sec.map(([w, c]) => `<span class="chip">${U.esc(w)} <b>${c}</b></span>`).join('')}</div>` : ''}`;
  }

  function goalHtml(r) {
    if (!r.g) return '<span class="muted">목표가 없음</span>';
    const c = chgPct(r);
    if (c == null) return `<b>${U.price(r.g)}</b>${r.same ? ' <span class="muted">유지</span>' : ''}`;
    return `<span class="muted">${U.price(r.pg)} →</span> <b>${U.price(r.g)}</b> <span class="pill-ch ${U.cls(c)}">${U.pct(c, 0)}</span>`;
  }

  function reportHtml(r, s) {
    const up = r.g && s.p ? r.g / s.p - 1 : null;
    return `<div class="rp-rep">
      <div class="rp-meta"><b>${U.esc(r.b)}</b>
        ${r.op ? `<span class="pill${r.pop ? ' rp-opchg' : ''}">${r.pop ? `${r.pop} → ` : ''}${r.op}</span>` : ''}
        ${r.init ? '<span class="dt-tag up">첫 커버</span>' : ''}
        <span class="rp-goal">${goalHtml(r)}</span></div>
      <a class="rp-title" href="${researchUrl(r.id)}" target="_blank" rel="noopener">${U.esc(r.t)}</a>
      ${r.h.length ? `<ul class="rp-heads">${r.h.map(h => `<li>${U.num(h)}</li>`).join('')}</ul>` : ''}
      ${r.s ? `<p class="rp-sum">${U.num(r.s)}</p>` : ''}
      <div class="rp-foot">${r.kw.map(k => `<button class="tag" data-k="kw" data-v="${U.esc(k)}">${U.esc(k)}</button>`).join('')}
        ${up != null ? `<span class="muted small">상승여력 <b class="${U.cls(up)}">${U.pct(up, 0)}</b></span>` : ''}
        ${r.pdf ? `<a class="muted small" href="${r.pdf}" target="_blank" rel="noopener">PDF ↗</a>` : ''}</div>
    </div>`;
  }

  function cardHtml(s) {
    const ups = s.r.filter(r => chgPct(r) > 0).length, dns = s.r.filter(r => chgPct(r) < 0).length;
    const all = open.has(s.c);
    return `<article class="rp-card" ${Stock.hintAttr(s)}>
      <header class="rp-head">
        <div class="rp-name">${Stock.link(s)}<small class="muted">${[s.mk === 'KOSPI' ? '코스피' : s.mk === 'KOSDAQ' ? '코스닥' : '', s.w, s.mc != null ? U.eok(s.mc) : ''].filter(Boolean).map(U.esc).join(' · ')}</small></div>
        <div class="rp-px">${s.p != null ? `<b>${U.price(s.p)}</b>` : ''}${s.ch != null ? `<span class="${U.cls(s.ch)}">${s.ch > 0 ? '+' : ''}${s.ch.toFixed(2)}%</span>` : ''}</div>
      </header>
      <div class="rp-badges"><span class="chip">리포트 ${s.r.length}건</span>
        ${ups ? `<span class="dt-tag up">목표가 ↑${ups}</span>` : ''}${dns ? `<span class="dt-tag down">목표가 ↓${dns}</span>` : ''}
        ${s.lone ? '<span class="dt-tag">소외주 첫 리포트</span>' : ''}</div>
      ${(all ? s.r : s.r.slice(0, SHOW)).map(r => reportHtml(r, s)).join('')}
      ${s.r.length > SHOW ? `<button class="more rp-more" data-open="${s.c}">${all ? '접기' : `리포트 ${s.r.length - SHOW}건 더`}</button>` : ''}
    </article>`;
  }

  function renderBody() {
    const stocks = filtered();
    renderSummary(stocks);
    $('deck').innerHTML = stocks.length ? stocks.map(cardHtml).join('') : '<p class="msg">조건에 맞는 리포트가 없습니다.</p>';
  }

  function renderFoot() {
    $('foot').innerHTML = `
      <p>리포트: 네이버 증권 리서치(증권사 제공 종목분석). 요약은 리포트 본문 요약의 앞부분, 키워드는 최근 90일 리포트에 비해 이 리포트가 유난히 많이 쓴 말입니다. 원문은 제목·PDF 링크로 보세요.</p>
      <p>목표가 변화는 같은 증권사의 직전 리포트 대비, 상승여력은 지금 주가 대비. '소외주 첫 리포트'는 최근 90일 동안 리포트가 없던 종목입니다.</p>`;
  }

  function render() {
    if (st.v !== 'day') return renderOther();
    if (!data) return load(st.date);   // 다른 보기로 시작했다가 일별로 바꾼 경우
    $('date').hidden = false;
    renderFilters();
    renderBody();
    renderFoot();
  }

  // ---------- 날짜별 한눈에 ----------
  async function renderOther() {
    $('date').hidden = true;
    try {
      if (st.v === 'dates' && !idx) idx = await U.json('data/digest_index.json');
      if (st.v === 'week' && !wkly) {
        wkly = await U.json('data/digest_weekly.json');
        // 이번 주가 막 시작해 목표가 변경 리포트가 적으면 지난주를 먼저 보여 준다
        if (!new URLSearchParams(location.search).has('wk') && wkly.weeks[0]?.rated < 20 && wkly.weeks[1]) st.wk = '1';
      }
    } catch (e) {
      $('deck').innerHTML = `<p class="msg">불러오지 못했습니다. (${e.message})</p>`;
      return;
    }
    renderFilters();
    if (st.v === 'dates') renderDates(); else renderWeek();
    renderFoot();
  }

  const goalPill = r => `<span class="muted">${U.price(r.pg)} →</span> <b>${U.price(r.g)}</b> <span class="pill-ch ${U.cls(r.r)}">${U.pct(r.r, 0)}</span>`;

  function renderDates() {
    const days = idx.days;
    const tot = days.reduce((a, d) => ({ n: a.n + d.n, up: a.up + d.up, dn: a.dn + d.dn }), { n: 0, up: 0, dn: 0 });
    $('summary').innerHTML = `<div class="dt-sum-head"><div><h2>최근 ${days.length}거래일 리포트 <span class="muted small">${DartFmt.md(days[days.length - 1].date)} ~ ${DartFmt.md(days[0].date)}</span></h2>
        <p class="muted small">날짜 카드를 누르면 그날 종목별 카드로 들어갑니다</p></div>
      <div class="dt-kpis"><div><span>리포트</span><b>${tot.n.toLocaleString('ko-KR')}</b></div>
        <div><span>목표가 상향</span><b class="up">${tot.up}</b></div><div><span>목표가 하향</span><b class="down">${tot.dn}</b></div></div></div>`;
    $('deck').innerHTML = days.map(d => `<article class="rp-card rp-day" data-day="${d.date}">
      <header class="rp-head"><div class="rp-name"><b class="rp-date">${DartFmt.md(d.date)}</b>
        <small class="muted">${d.n}건 · ${d.stocks}종목 · 증권사 ${d.brokers}곳</small></div>
        <div class="rp-badges"><span class="dt-tag up">↑${d.up}</span><span class="dt-tag down">↓${d.dn}</span>${d.lone ? `<span class="dt-tag">소외주 ${d.lone}</span>` : ''}</div></header>
      ${d.kws.length ? `<div class="rp-foot">${d.kws.map(k => `<span class="tag">${U.esc(k)}</span>`).join('')}</div>` : ''}
      ${d.most.length ? `<p class="small rp-most"><span class="muted">많이 다룬 종목</span> ${d.most.map(m => `<b>${U.esc(m.n)}</b> ${m.k}건`).join(' · ')}</p>` : ''}
      ${d.movers.length ? `<ul class="rp-movers">${d.movers.map(m => `<li ${Stock.hintAttr({ n: m.n })}>${Stock.link(m)} <small class="muted">${U.esc(m.b)}</small>
        <span class="rp-goal">${goalPill(m)}</span></li>`).join('')}</ul>` : ''}
    </article>`).join('');
  }

  // ---------- 주간 핵심 리포트 ----------
  function renderWeek() {
    const w = wkly.weeks[+st.wk] || wkly.weeks[0];
    const list = w[st.side];
    $('summary').innerHTML = `<div class="dt-sum-head"><div><h2>주간 핵심 리포트 <span class="muted small">${DartFmt.md(w.week)} ~ ${DartFmt.md(w.end)}</span></h2>
        <p class="muted small">같은 증권사 직전 대비 목표가 변경률이 가장 큰 리포트 (종목당 한 건). 오른쪽 위는 종목의 지금 컨센서스 리비전(내년 영업이익).</p></div>
      <div class="dt-kpis"><div><span>리포트</span><b>${w.n}</b></div><div><span>목표가 변경</span><b>${w.rated}</b></div>
        <div><span>상향</span><b class="up">${w.nup}</b></div><div><span>하향</span><b class="down">${w.ndn}</b></div></div></div>`;
    $('deck').innerHTML = list.length ? list.map((r, i) => {
      const up = r.g && r.p ? r.g / r.p - 1 : null;
      const cns = [r.cw1 != null && r.cw1 !== 0 ? `1주 ${U.pct(r.cw1)}` : '', r.cm1 != null && r.cm1 !== 0 ? `1개월 ${U.pct(r.cm1)}` : ''].filter(Boolean).join(' · ');
      return `<article class="rp-card" ${Stock.hintAttr(r)}>
        <header class="rp-head"><div class="rp-name"><span class="rp-rank">${i + 1}</span>${Stock.link(r)}
          <small class="muted">${[r.w, r.mc != null ? U.eok(r.mc) : ''].filter(Boolean).map(U.esc).join(' · ')}</small></div>
          <div class="rp-px"><span class="pill-ch ${U.cls(r.r)} rp-big">${U.pct(r.r, 0)}</span>${cns ? `<small class="muted">컨센 ${cns}</small>` : ''}</div></header>
        <div class="rp-rep">
          <div class="rp-meta"><span class="muted">${U.md(r.d)}</span><b>${U.esc(r.b)}</b>
            ${r.op ? `<span class="pill${r.pop ? ' rp-opchg' : ''}">${r.pop ? `${r.pop} → ` : ''}${r.op}</span>` : ''}
            <span class="rp-goal">${goalPill(r)}</span></div>
          <a class="rp-title" href="${researchUrl(r.id)}" target="_blank" rel="noopener">${U.esc(r.t)}</a>
          ${r.h.length ? `<ul class="rp-heads">${r.h.map(h => `<li>${U.num(h)}</li>`).join('')}</ul>` : ''}
          ${r.s ? `<p class="rp-sum">${U.num(r.s)}</p>` : ''}
          <div class="rp-foot">${r.more.length ? `<span class="muted small">같은 주 ${st.side === 'up' ? '상향' : '하향'}: ${r.more.slice(0, 4).map(U.esc).join(', ')}${r.more.length > 4 ? ` 외 ${r.more.length - 4}곳` : ''}</span>` : ''}
            ${up != null ? `<span class="muted small">지금 주가 ${U.price(r.p)} · 상승여력 <b class="${U.cls(up)}">${U.pct(up, 0)}</b></span>` : ''}
            ${r.pdf ? `<a class="muted small" href="${r.pdf}" target="_blank" rel="noopener">PDF ↗</a>` : ''}</div>
        </div></article>`;
    }).join('') : '<p class="msg">이 주에는 목표가를 바꾼 리포트가 없습니다.</p>';
  }

  function weekDigest() {
    const w = wkly.weeks[+st.wk] || wkly.weeks[0];
    const out = [`[주간 핵심 리포트 ${DartFmt.md(w.week)} ~ ${DartFmt.md(w.end)} · 목표가 ${st.side === 'up' ? '상향' : '하향'} Top ${w[st.side].length}]`];
    w[st.side].forEach((r, i) => {
      out.push('', `${i + 1}. ${r.n} (${r.mc != null ? DartFmt.eok(r.mc) : '시총 –'}) ${U.pct(r.r, 0)}`,
        `- ${U.md(r.d)} ${r.b} | ${r.op || '의견 없음'} | 목표가 ${U.price(r.pg)} → ${U.price(r.g)} | ${r.t}`);
      for (const h of r.h) out.push(`  · ${h}`);
      if (r.more.length) out.push(`  (같은 주 ${st.side === 'up' ? '상향' : '하향'}: ${r.more.join(', ')})`);
    });
    return out.join('\n');
  }

  // 글로 복사: 종목별로 증권사 | 의견 | 목표가 | 제목 + 소제목
  function digest(stocks) {
    const s = data.sum;
    const out = [`[${DartFmt.md(data.date)} 신규 리포트 · ${s.n}건 / ${s.stocks}종목]`, `목표가 상향 ${s.up} · 하향 ${s.dn} · 유지 ${s.keep}`];
    for (const x of stocks) {
      out.push('', `■ ${x.n} (${x.mc != null ? DartFmt.eok(x.mc) : '시총 –'}) — ${x.r.length}건`);
      for (const r of x.r) {
        const c = chgPct(r);
        const goal = r.g ? (c != null ? `목표가 ${U.price(r.pg)} → ${U.price(r.g)} (${U.pct(c, 0)})` : `목표가 ${U.price(r.g)}${r.same ? ' 유지' : ''}`) : '목표가 없음';
        out.push(`- ${r.b} | ${r.pop ? `${r.pop}→${r.op}` : r.op || '의견 없음'} | ${goal} | ${r.t}`);
        for (const h of r.h.slice(0, 2)) out.push(`  · ${h}`);
      }
    }
    return out.join('\n');
  }

  $('filters').addEventListener('click', async e => {
    const b = e.target.closest('#copy');
    if (!b) return;
    try {
      await navigator.clipboard.writeText(st.v === 'week' ? weekDigest() : digest(filtered()));
      b.textContent = '복사됨 ✓';
    } catch (err) { b.textContent = '복사 실패'; }
    setTimeout(() => { b.textContent = '글로 복사'; }, 1600);
  });
  // 키워드 칩·태그는 필터 영역 밖에도 있어서 따로 연결
  for (const id of ['summary', 'deck']) {
    $(id).addEventListener('click', e => {
      const day = e.target.closest('[data-day]');
      if (day && !e.target.closest('a')) {   // 날짜 카드 → 그날 일별 보기
        st.v = 'day';
        st.date = day.dataset.day;
        $('date').value = st.date;
        pg.write();
        window.scrollTo({ top: 0 });
        return load(st.date);
      }
      const k = e.target.closest('[data-k="kw"]');
      if (k) { pg.set({ kw: k.dataset.v }); window.scrollTo({ top: 0, behavior: 'smooth' }); return; }
      const m = e.target.closest('[data-open]');
      if (m) {
        open.has(m.dataset.open) ? open.delete(m.dataset.open) : open.add(m.dataset.open);
        renderBody();
      }
    });
  }

  async function load(d) {
    try {
      data = await U.json(`data/digest/${d}.json`);
    } catch (e) {
      $('msg').hidden = false;
      $('msg').textContent = `${d} 리포트를 불러오지 못했습니다. (${e.message})`;
      return;
    }
    $('msg').hidden = true;
    open.clear();
    render();
  }

  pg.bind($('filters'));
  U.initTheme($('theme'));
  (async () => {
    try {
      await U.dates('digest', pg, $('date'), load);
    } catch (e) {
      $('msg').textContent = '리포트 목록을 불러오지 못했습니다.';
      return;
    }
    if (st.v === 'day') load(st.date); else render();
  })();
})();
