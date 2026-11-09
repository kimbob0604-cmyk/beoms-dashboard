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
  const DEFAULTS = { date: '', g: 'all', market: 'all', cap: 'all', sort: 'n', q: '', kw: '', lone: '' };
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
    $('filters').innerHTML = `
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
    renderFilters();
    renderBody();
    renderFoot();
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
      await navigator.clipboard.writeText(digest(filtered()));
      b.textContent = '복사됨 ✓';
    } catch (err) { b.textContent = '복사 실패'; }
    setTimeout(() => { b.textContent = '글로 복사'; }, 1600);
  });
  // 키워드 칩·태그는 필터 영역 밖에도 있어서 따로 연결
  for (const id of ['summary', 'deck']) {
    $(id).addEventListener('click', e => {
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
    load(st.date);
  })();
})();
