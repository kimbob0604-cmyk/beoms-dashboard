// 컨센 리비전 탭
// - 추정치: 이익 성장 JSON(data/growth)에 들어 있는 연도별 추정치 변화(현재 vs 1주·1개월·3개월 전)
// - 목표가: data/reports/recent.json (최근 30일 리포트, 같은 증권사 직전 목표가와 비교)
(() => {
  const METRICS = { op: '영업이익', ni: '순이익', revenue: '매출', eps: 'EPS' };
  const PERIODS = { w1: '1주', m1: '1개월', m3: '3개월' };
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  const FLAT = 0.001;        // ±0.1% 미만은 변화 없음으로 센다
  const PAGE = 40;
  const DEFAULTS = { date: '', view: '', fy: 'f1', metric: 'op', per: 'm1', dir: 'up', market: 'all', cap: 'all', q: '', tdays: '7' };

  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => { shown = {}; typing ? renderBody() : render(); });
  const st = pg.state;
  let data = null, reports = null, shown = {};

  // ---------- 계산 ----------
  // 선택 연도의 추정치와 변화율. f0 = 올해(출발 연도), f1 = 내년, f2 = 내후년
  function est(s) {
    const y0 = s.k.y0?.[st.metric], y1 = s.k.y1?.[st.metric];
    if (st.fy === 'f0') return y0 && { fy: s.fy0, now: y0.b, w1: y0.bw1, m1: y0.bm1, m3: y0.bm3 };
    if (st.fy === 'f1') return y0 && { fy: s.fy0 + 1, now: y0.n, w1: y0.w1, m1: y0.m1, m3: y0.m3 };
    return y1 && { fy: s.fy0 + 2, now: y1.n, w1: y1.w1, m1: y1.m1, m3: y1.m3 };
  }
  // 변화율에서 이전 값 되돌리기 (이전 값이 양수일 때만 정확)
  const prevOf = (now, r) => (now != null && r != null && r > -1 ? now / (1 + r) : null);
  const fy2 = fy => String(fy).slice(2);
  const fyLabel = () => (data ? `FY${fy2(data.fy0 + { f0: 0, f1: 1, f2: 2 }[st.fy])}` : '');
  const fmtVal = (v, signed) => (st.metric === 'eps' ? U.won(v, signed) : U.eok(v, signed));

  function base(skipQ) {
    const q = st.q.trim().toLowerCase();
    const cap = CAPS[st.cap];
    return data.stocks.filter(s => {
      const e = est(s);
      if (!e || e.now == null || e[st.per] == null) return false;
      if (st.market !== 'all' && s.mk !== st.market) return false;
      if (cap && (s.mc < cap[0] || s.mc >= cap[1])) return false;
      if (!skipQ && q && !s.n.toLowerCase().includes(q) && !s.c.includes(q)) return false;
      return true;
    });
  }
  const dirOk = r => (st.dir === 'up' ? r >= FLAT : r <= -FLAT);

  function breadth(list) {
    let up = 0, dn = 0, now = 0, prev = 0;
    for (const s of list) {
      const e = est(s), r = e[st.per];
      if (r >= FLAT) up++; else if (r <= -FLAT) dn++;
      const p = prevOf(e.now, r);
      if (st.metric !== 'eps' && e.now > 0 && p > 0) { now += e.now; prev += p; }
    }
    return { up, dn, flat: list.length - up - dn, n: list.length, g: prev > 0 ? now / prev - 1 : null, now, prev };
  }

  // ---------- 필터 ----------
  function renderFilters() {
    const fy0 = data.fy0;
    $('view').innerHTML = pg.seg('view', [['', '추정치'], ['tgt', '목표가', '최근 리포트의 목표가 변경']]);
    if (st.view === 'tgt') {
      $('filters').innerHTML = `<div class="frow">
        ${pg.seg('dir', [['up', '목표가 상향'], ['dn', '목표가 하향']])}
        ${pg.seg('tdays', [['1', '오늘'], ['7', '1주'], ['30', '1개월']])}
        ${pg.seg('market', [['all', '전체'], ['KOSPI', '코스피'], ['KOSDAQ', '코스닥']])}
        ${pg.seg('cap', [['all', '시총 전체'], ['L', '1조 이상'], ['M', '3천억~1조'], ['S', '3천억 미만']])}
        <input type="search" data-q="q" placeholder="종목명·코드 검색" value="${U.esc(st.q)}" autocomplete="off">
      </div>`;
      return;
    }
    $('filters').innerHTML = `
      <div class="frow">
        ${pg.seg('fy', [['f0', `FY${fy2(fy0)} 올해`], ['f1', `FY${fy2(fy0 + 1)} 내년`], ['f2', `FY${fy2(fy0 + 2)} 내후년`]])}
        ${pg.seg('metric', Object.entries(METRICS))}
        ${pg.seg('per', Object.entries(PERIODS).map(([k, l]) => [k, `${l} 변화`]))}
        ${pg.seg('dir', [['up', '상향'], ['dn', '하향']])}
      </div>
      <div class="frow">
        ${pg.seg('market', [['all', '전체'], ['KOSPI', '코스피'], ['KOSDAQ', '코스닥']])}
        ${pg.seg('cap', [['all', '시총 전체'], ['L', '1조 이상'], ['M', '3천억~1조'], ['S', '3천억 미만']])}
        <input type="search" data-q="q" placeholder="종목명·코드 검색" value="${U.esc(st.q)}" autocomplete="off">
      </div>`;
  }

  // ---------- 추정치 ----------
  function renderSummary() {
    const list = base(true);
    const mName = METRICS[st.metric];
    $('summary-head').innerHTML = `<h2>${fyLabel()} ${mName} 추정치 ${PERIODS[st.per]} 변화</h2>
      <span class="muted small">컨센 ${U.dateLabel(data.cns_date)} 기준</span>`;
    const cards = Object.entries(MARKETS).map(([m, label]) => {
      const b = breadth(list.filter(s => s.mk === m));
      if (!b.n) return '';
      const w = x => (b.n ? (x / b.n) * 100 : 0);
      return `<div class="rv-mk">
        <div class="rv-mk-head"><b>${label}</b><span class="muted">${b.n}종목</span>
          ${st.metric !== 'eps' ? `<span>합계 <b class="${U.cls(b.g)}">${U.pct(b.g, 2)}</b> <span class="muted small">(${U.eok(b.prev)} → ${U.eok(b.now)})</span></span>` : ''}</div>
        <div class="rv-bar"><i class="up-bg" style="width:${w(b.up)}%"></i><i class="flat-bg" style="width:${w(b.flat)}%"></i><i class="dn-bg" style="width:${w(b.dn)}%"></i></div>
        <div class="rv-cnt small"><span>상향 <b class="up">${b.up}</b></span><span class="muted">변화 없음 ${b.flat}</span><span>하향 <b class="down">${b.dn}</b></span></div>
      </div>`;
    }).join('');
    $('summary').innerHTML = `
      <p class="sub">FnGuide 컨센서스의 ${fyLabel()} ${mName} 추정치를 ${PERIODS[st.per]} 전과 비교했습니다. ±0.1% 미만은 변화 없음으로 셉니다.</p>
      <div class="rv-mks">${cards || '<span class="muted">해당 종목 없음</span>'}</div>
      <p class="note">합계 = 해당 종목 추정치의 합 (이전 값이 적자인 종목은 합계에서 뺌). 마지막 확인 ${U.timeLabel(data.checked_at)}.</p>`;
  }

  function renderSectors() {
    $('sectors').hidden = st.view === 'tgt';
    if (st.view === 'tgt') return;
    $('sectors-head').innerHTML = `<b>업종별 리비전</b> <span class="muted">${fyLabel()} ${METRICS[st.metric]} ${PERIODS[st.per]} 변화, 3종목 이상 · 상향−하향 종목 수 순</span>`;
    const groups = {};
    for (const s of base(true)) if (s.w) (groups[s.w] ||= []).push(s);
    const rows = Object.entries(groups).filter(([, l]) => l.length >= 3)
      .map(([w, l]) => ({ w, b: breadth(l) }))
      .sort((x, y) => (y.b.up - y.b.dn) - (x.b.up - x.b.dn) || (y.b.g ?? 0) - (x.b.g ?? 0));
    $('sector-list').innerHTML = rows.length ? `<div class="sec-grid">${rows.map(({ w, b }) => `
      <div class="sec rv-sec">
        <span class="sec-name">${U.esc(w)} <small class="muted">${b.n}</small></span>
        <span class="sec-val"><span class="up">▲${b.up}</span> <span class="down">▼${b.dn}</span></span>
        <span class="rv-bar sm"><i class="up-bg" style="width:${b.up / b.n * 100}%"></i><i class="flat-bg" style="width:${b.flat / b.n * 100}%"></i><i class="dn-bg" style="width:${b.dn / b.n * 100}%"></i></span>
        <b class="${U.cls(b.g)}">${st.metric === 'eps' ? '' : U.pct(b.g)}</b>
      </div>`).join('')}</div>` : '<p class="muted">해당 업종 없음</p>';
  }

  function otherYears(s) {
    const keep = st.fy;
    const out = [];
    for (const f of ['f0', 'f1', 'f2']) {
      if (f === keep) continue;
      st.fy = f;
      const e = est(s);
      if (e && e[st.per] != null) out.push(`FY${fy2(e.fy)} <b class="${U.cls(e[st.per])}">${U.pct(e[st.per])}</b>`);
    }
    st.fy = keep;
    return out;
  }

  function estRow(s, rank) {
    const e = est(s), r = e[st.per], prev = prevOf(e.now, r);
    const g = s.k.y0?.op;
    return `<article class="row" ${Stock.hintAttr(s)}>
      <span class="rank">${rank}</span>
      <div class="r-main">
        <div class="r-top">
          <div class="r-name">${Stock.link(s)}${s.w ? `<span class="tag">${U.esc(s.w)}</span>` : ''}<span class="muted">${U.eok(s.mc)}</span></div>
          <div class="r-growth"><small>${PERIODS[st.per]}</small><b class="${U.cls(r)}">${U.pct(r)}</b></div>
        </div>
        <div class="r-line">FY${fy2(e.fy)}E ${METRICS[st.metric]} ${prev != null ? `${fmtVal(prev)} → ` : ''}<b>${fmtVal(e.now)}</b>, 주가 ${U.price(s.p)}</div>
        <div class="r-rev">FY${fy2(e.fy)} ${Object.entries(PERIODS).map(([k, l]) =>
          `<span class="chip">${l} <b class="${U.cls(e[k])}">${U.pct(e[k])}</b></span>`).join('')}</div>
        <div class="r-sub">${otherYears(s).map(t => `<span>${t}</span>`).join('')}
          ${g ? `<span>내년 영업이익 성장 <b class="${g.k === 'turnaround' ? 'up' : U.cls(g.g)}">${g.k === 'turnaround' ? '흑자전환' : U.pct(g.g)}</b></span><span>POR <b>${U.mult(g.mn)}</b></span>` : ''}</div>
      </div>
    </article>`;
  }

  function renderEst() {
    const list = base().filter(s => dirOk(est(s)[st.per]))
      .sort((a, b) => (st.dir === 'up' ? est(b)[st.per] - est(a)[st.per] : est(a)[st.per] - est(b)[st.per]));
    for (const [m, label] of Object.entries(MARKETS)) {
      const items = list.filter(s => s.mk === m);
      const n = shown[m] || PAGE;
      const col = $(`col-${m}`);
      col.hidden = st.market !== 'all' && st.market !== m;
      col.innerHTML = `<div class="col-head"><h3>${label} <span class="muted">${items.length}종목, ${st.dir === 'up' ? '상향' : '하향'} 큰 순</span></h3></div>
        ${items.slice(0, n).map((s, i) => estRow(s, i + 1)).join('') || '<p class="muted empty">해당 종목 없음</p>'}
        ${items.length > n ? `<button class="more" data-m="${m}">더 보기 (${items.length - n}개 남음)</button>` : ''}`;
    }
  }

  // ---------- 목표가 ----------
  function tgtList(skipDir) {
    const since = new Date(new Date(reports.date + 'T00:00:00') - (+st.tdays - 1) * 864e5).toISOString().slice(0, 10);
    const q = st.q.trim().toLowerCase();
    const cap = CAPS[st.cap];
    return reports.reports.filter(r => {
      if (r.d < since || !r.g) return false;
      if (st.market !== 'all' && r.mk !== st.market) return false;
      if (cap && (r.mc == null || r.mc < cap[0] || r.mc >= cap[1])) return false;
      if (q && !r.n.toLowerCase().includes(q) && !r.c.includes(q)) return false;
      if (skipDir) return true;
      return r.pg && (st.dir === 'up' ? r.g > r.pg : r.g < r.pg);
    });
  }

  function renderTgtSummary() {
    const list = tgtList(true);
    const up = list.filter(r => r.pg && r.g > r.pg), dn = list.filter(r => r.pg && r.g < r.pg);
    const same = list.filter(r => r.pg && r.g === r.pg).length, first = list.filter(r => !r.pg).length;
    const label = { 1: '오늘', 7: '최근 1주', 30: '최근 1개월' }[st.tdays];
    // 목표가를 올린 증권사가 많은 종목
    const cnt = {};
    for (const r of (st.dir === 'up' ? up : dn)) (cnt[r.c] ||= { r, n: 0 }).n++;
    const top = Object.values(cnt).sort((a, b) => b.n - a.n).slice(0, 12);
    $('summary-head').innerHTML = `<h2>목표가 변경 <span class="muted small">${label} 리포트</span></h2>
      <span class="muted small">${U.dateLabel(reports.date)}까지</span>`;
    $('summary').innerHTML = `
      <p class="sub">${label} 나온 리포트 ${list.length}건 중 목표가 상향 <b class="up">${up.length}</b> · 하향 <b class="down">${dn.length}</b> · 유지 ${same} · 직전 비교 없음 ${first}</p>
      ${top.length ? `<div class="tgt-top">${top.map(({ r, n }) =>
        `<span class="chip" ${Stock.hintAttr({ n: r.n, mk: r.mk, w: r.w, mc: r.mc, p: r.cp })}>${Stock.link({ c: r.c, n: r.n })} <b class="${st.dir === 'up' ? 'up' : 'down'}">${n}건</b></span>`).join('')}</div>` : ''}
      <p class="note">직전 목표가 = 같은 증권사가 최근 90일 안에 낸 바로 앞 리포트의 목표가. 그 기간에 앞 리포트가 없으면 비교하지 않습니다.</p>`;
  }

  function tgtRow(r) {
    const ch = r.g / r.pg - 1;
    const upside = r.cp ? r.g / r.cp - 1 : null;
    return `<article class="row" ${Stock.hintAttr({ n: r.n, mk: r.mk, w: r.w, mc: r.mc, p: r.cp })}>
      <div class="r-main">
        <div class="r-top">
          <div class="r-name">${Stock.link({ c: r.c, n: r.n })}${r.w ? `<span class="tag">${U.esc(r.w)}</span>` : ''}<span class="muted">${U.eok(r.mc)}</span></div>
          <div class="r-growth"><small>${U.price(r.pg)} → ${U.price(r.g)}</small><b class="${U.cls(ch)}">${U.pct(ch)}</b></div>
        </div>
        <div class="r-line"><span class="muted">${U.md(r.d)}</span> <b>${U.esc(r.b)}</b>${r.op ? ` · ${r.op}` : ''} · ${U.esc(r.t)}</div>
        <div class="r-sub"><span>현재가 <b>${U.price(r.cp)}</b></span>${upside != null ? `<span>목표가까지 <b class="${U.cls(upside)}">${U.pct(upside)}</b></span>` : ''}</div>
      </div>
    </article>`;
  }

  function renderTgt() {
    const list = tgtList().sort((a, b) => (b.d > a.d ? 1 : b.d < a.d ? -1 : Math.abs(b.g / b.pg - 1) - Math.abs(a.g / a.pg - 1)));
    for (const [m, label] of Object.entries(MARKETS)) {
      const items = list.filter(r => r.mk === m);
      const n = shown[m] || PAGE;
      const col = $(`col-${m}`);
      col.hidden = st.market !== 'all' && st.market !== m;
      col.innerHTML = `<div class="col-head"><h3>${label} <span class="muted">${items.length}건, 최신순</span></h3></div>
        ${items.slice(0, n).map(tgtRow).join('') || '<p class="muted empty">해당 리포트 없음</p>'}
        ${items.length > n ? `<button class="more" data-m="${m}">더 보기 (${items.length - n}개 남음)</button>` : ''}`;
    }
  }

  document.querySelector('.cols').addEventListener('click', e => {
    const b = e.target.closest('.more');
    if (!b) return;
    shown[b.dataset.m] = (shown[b.dataset.m] || PAGE) + PAGE * 2;
    renderBody();
  });

  // ---------- 진입 ----------
  function renderFoot() {
    $('foot').innerHTML = `
      <p>추정치: FnGuide 종목별 컨센서스(네이버 종목분석), 기준일 ${U.dateLabel(data.cns_date)}. 1주·1개월·3개월 비교는 FnGuide의 그 시점 값.</p>
      <p>목표가: 네이버 증권 리서치 종목분석 리포트(증권사 제공). 현재가는 KRX 종가 (다음 날 아침 KRX 공개 전까지는 네이버 시세로 임시 표시).</p>
      <p>컨센서스 데이터의 권리는 FnGuide에, 리포트의 권리는 각 증권사에 있습니다. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  }

  function renderBody() {
    if (st.view === 'tgt') {
      if (!reports) return;
      renderTgtSummary();
      renderSectors();
      return renderTgt();
    }
    renderSummary();
    renderSectors();
    renderEst();
  }

  function render() {
    renderFilters();
    renderBody();
    renderFoot();
  }

  function showError(msg) {
    $('msg').hidden = false;
    $('msg').textContent = msg;
  }

  async function load(d) {
    try {
      data = await U.json(`data/growth/${d}.json`);
    } catch (e) {
      return showError(`${d} 데이터를 불러오지 못했습니다. (${e.message})`);
    }
    $('msg').hidden = true;
    render();
  }

  pg.bind($('filters'));
  pg.bind($('view'));
  U.initTheme($('theme'));
  for (const [id, key, dflt] of [['summary-box', 'rvSummaryOpen', '1'], ['sectors', 'rvSectorsOpen', '']]) {
    try { $(id).open = (localStorage.getItem(key) ?? dflt) === '1'; } catch (e) {}
    $(id).addEventListener('toggle', () => { try { localStorage.setItem(key, $(id).open ? '1' : ''); } catch (e) {} });
  }

  (async () => {
    try {
      await U.dates('growth', pg, $('date'), load);
    } catch (e) {
      return showError('데이터 목록을 불러오지 못했습니다.');
    }
    U.json('data/reports/recent.json').then(r => { reports = r; if (st.view === 'tgt' && data) render(); }).catch(() => {});
    load(st.date);
  })();
})();
