// 수급 탭: data/flow/{거래일}.json — 종목별 외국인·기관 순매수 금액(억원, 수량×종가 어림)
// - 수급 시그널 카드: 쌍끌이 순매수·순매도, 외국인 연속 순매수·순매도, 수급 반전 (build_naver.flow_signals 가 고른 종목)
//   아래 필터(주체·기간·시장)와 상관없이 그날 전 종목에서 고른다
// - ETF 기계적 수급: data/etf_flow.json (build_etf_flow.py ← KBJ). ETF 순설정·환매 × 구성 비중을 종목에 나눈 금액
// - 수급 지도(찬집·빈집): 가로 = 중기(60·120일) 누적 순매수 ÷ 시총, 세로 = 단기(5·20일) ÷ 시총. 주체·시장·시총·검색 필터를 따른다
(() => {
  const MAIN = { f: '외국인', o: '기관', fo: '외국인+기관' };
  // 기관 세부·기타법인: build_naver.DETAIL (KIS 실제 거래대금, KRX+넥스트레이드). data.det 가 있을 때만 고를 수 있다
  const DET = { sc: '금융투자', pn: '연기금', tr: '투신', pe: '사모', in: '보험', bk: '은행', ef: '기타금융', cp: '기타법인' };
  const WHO = { ...MAIN, ...DET };
  const DAYS = { 1: '1일', 5: '5일', 20: '20일', 60: '60일' };
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  const STREAK_MIN = 3;
  const PAGE = 40;
  const DEFAULTS = { date: '', who: 'f', days: '5', dir: 'buy', unit: 'amt', market: 'all', cap: 'all', q: '', streak: '', both: '', growth: '', mapS: '20', mapM: '120', ep: '5', es: 'in' };

  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => { shown = {}; typing ? renderBody() : render(); });
  const st = pg.state;
  let data = null, shown = {}, etf = null;

  // 선택한 주체·기간의 순매수 금액. 시총 대비면 % (소수)
  const amt = (s, who = st.who, d = st.days) =>
    (who === 'fo' ? (s[`f${d}`] == null || s[`o${d}`] == null ? null : s[`f${d}`] + s[`o${d}`]) : s[`${who}${d}`]);
  const val = s => { const a = amt(s); return a == null ? null : st.unit === 'pct' ? a / s.mc : a; };
  const streakOf = s => (DET[st.who] ? s[`${st.who}s`] || 0 : st.who === 'o' ? s.os : st.who === 'f' ? s.fs
    : Math.sign(s.fs) === Math.sign(s.os) ? Math.min(Math.abs(s.fs), Math.abs(s.os)) * Math.sign(s.fs) : 0);
  const fmtVal = v => (v == null ? '–' : st.unit === 'pct' ? `${v > 0 ? '+' : ''}${(v * 100).toFixed(2)}%` : U.eok(v, true));

  function filtered(skipQ) {
    const q = st.q.trim().toLowerCase();
    const cap = CAPS[st.cap];
    const sign = st.dir === 'buy' ? 1 : -1;
    return data.stocks.filter(s => {
      const v = val(s);
      if (v == null || Math.sign(v) !== sign) return false;
      if (st.market !== 'all' && s.mk !== st.market) return false;
      if (cap && (s.mc < cap[0] || s.mc >= cap[1])) return false;
      if (st.streak && !(streakOf(s) * sign >= STREAK_MIN)) return false;
      if (st.both && !(amt(s, 'f') * sign > 0 && amt(s, 'o') * sign > 0)) return false;
      if (st.growth && !(s.gx && (s.gx.k === 'turnaround' || s.gx.g > 0))) return false;
      if (!skipQ && q && !s.n.toLowerCase().includes(q) && !s.c.includes(q)) return false;
      return true;
    });
  }

  function renderFilters() {
    $('view').innerHTML = '';
    $('filters').innerHTML = `
      <div class="frow">
        ${pg.seg('who', Object.entries(MAIN))}
        ${pg.seg('days', Object.entries(DAYS))}
        ${pg.seg('dir', [['buy', '순매수'], ['sell', '순매도']])}
        ${pg.seg('unit', [['amt', '금액 순'], ['pct', '시총 대비 순', '순매수 금액 ÷ 시가총액']])}
      </div>
      ${data?.det ? `<div class="frow"><span class="muted small">기관 세부</span>${pg.seg('who', Object.entries(DET))}</div>` : ''}
      <div class="frow">
        ${pg.seg('market', [['all', '전체'], ['KOSPI', '코스피'], ['KOSDAQ', '코스닥']])}
        ${pg.seg('cap', [['all', '시총 전체'], ['L', '1조 이상'], ['M', '3천억~1조'], ['S', '3천억 미만']])}
        <input type="search" data-q="q" placeholder="종목명·코드 검색" value="${U.esc(st.q)}" autocomplete="off">
        ${pg.chk('streak', `연속 ${STREAK_MIN}일+`, `${STREAK_MIN}거래일 이상 연속 ${st.dir === 'buy' ? '순매수' : '순매도'}`)}
        ${pg.chk('both', '외국인·기관 동반', '같은 기간 외국인과 기관이 같은 방향')}
        ${pg.chk('growth', '이익 성장만', '내년 영업이익 증가 또는 흑자전환 추정 종목')}
      </div>`;
  }

  function renderSummary() {
    const d = st.days;
    const list = data.stocks.filter(s => (st.market === 'all' || s.mk === st.market));
    $('summary-head').innerHTML = `<h2>${DAYS[d]} 순매수 합계</h2>
      <span class="muted small">${U.dateLabel(data.date)}까지 · 대상 ${data.stocks.length}종목</span>`;
    const sum = (l, k) => l.reduce((a, s) => a + (s[`${k}${d}`] || 0), 0);
    const cards = Object.entries(MARKETS).map(([m, label]) => {
      const l = list.filter(s => s.mk === m);
      if (!l.length) return '';
      const cnt = k => l.filter(s => (s[`${k}${d}`] || 0) > 0).length;
      return `<div class="rv-mk">
        <div class="rv-mk-head"><b>${label}</b><span class="muted">${l.length}종목</span></div>
        <div class="fl-sum">
          ${[['f', '외국인'], ['o', '기관'], ['i', '개인']].map(([k, n]) => `<div><span>${n}</span><b class="${U.cls(sum(l, k))}">${U.eok(sum(l, k), true)}</b>
            <small class="muted">순매수 ${cnt(k)} · 순매도 ${l.filter(s => (s[`${k}${d}`] || 0) < 0).length}종목</small></div>`).join('')}
        </div>
        ${data.det ? `<div class="fl-det">${Object.entries(DET).map(([k, n]) => `<button type="button" class="fl-det-i${st.who === k ? ' on' : ''}" data-who="${k}"
            title="${n} ${DAYS[d]} 순매수 순위 보기"><span>${n}</span><b class="${U.cls(sum(l, k))}">${U.eok(sum(l, k), true)}</b></button>`).join('')}</div>` : ''}
      </div>`;
    }).join('');
    $('summary').innerHTML = `
      <p class="sub">시총 1,000억 이상 보통주와 컨센서스·리포트가 있는 종목의 합입니다 (시장 전체 합계와 다름).</p>
      <div class="rv-mks">${cards}</div>
      <p class="note">금액 = 그날 순매수 수량 × 정규장 종가, ${DAYS[d]} 합. 출처 네이버 증권 투자자별 매매동향(KRX+넥스트레이드).
        ${data.det ? `기관 세부(금융투자~기타금융)와 기타법인은 한국투자증권 API의 실제 체결 대금입니다 — 세부를 더하면 그쪽 기관 합계와 맞고, 위 기관 합계(수량 × 종가 어림)와는 조금 다릅니다. 세부가 있는 종목 ${data.det}개.` : '기관은 금융투자·연기금 등 합계.'}</p>`;
  }

  const SIGNALS = [
    ['dual_buy', '🤝 쌍끌이 순매수', s => `외국인·기관이 함께 ${data.sig_min}억 이상 순매수`, s => s.f1 + s.o1, '외국인+기관'],
    ['dual_sell', '💥 쌍끌이 순매도', s => `외국인·기관이 함께 ${data.sig_min}억 이상 순매도`, s => s.f1 + s.o1, '외국인+기관'],
    ['streak_buy', '🔼 외국인 연속 순매수', s => `${data.sig_streak}거래일 이상 연속, 당일 ${data.sig_min / 2}억 이상`, s => s.f1, '외국인'],
    ['streak_sell', '🔽 외국인 연속 순매도', s => `${data.sig_streak}거래일 이상 연속, 당일 ${data.sig_min / 2}억 이상`, s => s.f1, '외국인'],
    ['reversal', '🔁 수급 반전', s => `직전 3거래일 외국인 순매도 → 당일 ${data.sig_min}억 이상 순매수`, s => s.f1, '외국인'],
  ];

  function sigRow(s, key, val, who) {
    const streak = key.startsWith('streak') ? `<span class="badge">${Math.abs(s.fs)}일 연속</span>`
      : Math.abs(s.fs) >= data.sig_streak ? `<span class="badge">외국인 ${Math.abs(s.fs)}일 연속 ${s.fs > 0 ? '순매수' : '순매도'}</span>` : '';
    return `<article class="row" ${Stock.hintAttr(s)}>
      <div class="r-main">
        <div class="r-top">
          <div class="r-name">${Stock.link(s)}${s.w ? `<span class="tag">${U.esc(s.w)}</span>` : ''}${streak}</div>
          <div class="r-growth"><small>${who}</small><b class="${U.cls(val(s))}">${U.eok(val(s), true)}</b></div>
        </div>
        <div class="r-line">외국인 <b class="${U.cls(s.f1)}">${U.eok(s.f1, true)}</b> · 기관 <b class="${U.cls(s.o1)}">${U.eok(s.o1, true)}</b>${key === 'reversal' ? ` · 직전 3일 외국인 <b class="${U.cls(s.fp3)}">${U.eok(s.fp3, true)}</b>` : ''}</div>
        <div class="r-sub"><span>시총 <b>${U.eok(s.mc)}</b></span><span class="${U.cls(s.ch)}">${s.ch > 0 ? '+' : ''}${s.ch?.toFixed(2) ?? '–'}%</span>
          <span>5일 외국인 <b class="${U.cls(s.f5)}">${U.eok(s.f5, true)}</b> · 기관 <b class="${U.cls(s.o5)}">${U.eok(s.o5, true)}</b></span></div>
      </div>
    </article>`;
  }

  function renderSignals() {
    const sig = data.sig;
    $('sig-title').hidden = $('signals').hidden = !sig;
    if (!sig) return;
    const by = Object.fromEntries(data.stocks.map(s => [s.c, s]));
    const total = SIGNALS.reduce((a, [k]) => a + (sig[k]?.length || 0), 0);
    $('sig-title').innerHTML = `<h2>수급 시그널</h2><span class="muted small">${U.dateLabel(data.date)} 하루 수급 · 전 종목에서 고름 · ${total ? '종목을 누르면 상세' : '오늘은 잡힌 시그널 없음'}</span>`;
    $('signals').innerHTML = SIGNALS.map(([key, label, tip, val, who]) => {
      const items = (sig[key] || []).map(c => by[c]).filter(Boolean);
      if (!items.length) return '';
      return `<div class="col"><div class="col-head"><h3>${label} <span class="muted">${items.length}종목</span></h3><span class="muted small">${tip()}</span></div>
        ${items.map(s => sigRow(s, key, val, who)).join('')}</div>`;
    }).join('');
    $('list-title').innerHTML = '<h2>순매수 순위</h2><span class="muted small">위 필터(주체·기간·시장)를 따릅니다</span>';
  }

  function streakText(n, who) {
    if (Math.abs(n) < 2) return '';
    return `${who} ${Math.abs(n)}일 연속 ${n > 0 ? '순매수' : '순매도'}`;
  }

  function rowHtml(s, rank) {
    const v = val(s);
    const d = st.days;
    const gx = s.gx;
    return `<article class="row" ${Stock.hintAttr(s)}>
      <span class="rank">${rank}</span>
      <div class="r-main">
        <div class="r-top">
          <div class="r-name">${Stock.link(s)}${s.w ? `<span class="tag">${U.esc(s.w)}</span>` : ''}<span class="muted">${U.eok(s.mc)}</span></div>
          <div class="r-growth"><small>${WHO[st.who]} ${DAYS[d]}</small><b class="${U.cls(v)}">${fmtVal(v)}</b></div>
        </div>
        <div class="r-line">${DET[st.who] ? `${DET[st.who]} <b class="${U.cls(s[`${st.who}${d}`])}">${U.eok(s[`${st.who}${d}`], true)}</b> · ` : ''}외국인 <b class="${U.cls(s[`f${d}`])}">${U.eok(s[`f${d}`], true)}</b> · 기관 <b class="${U.cls(s[`o${d}`])}">${U.eok(s[`o${d}`], true)}</b> · 개인 <b class="${U.cls(s[`i${d}`])}">${U.eok(s[`i${d}`], true)}</b>, 시총 ${U.eok(s.mc)} <span class="${U.cls(s.ch)}">${s.ch > 0 ? '+' : ''}${s.ch?.toFixed(2) ?? '–'}%</span></div>
        <div class="r-sub">
          ${[streakText(s.fs, '외국인'), streakText(s.os, '기관'), DET[st.who] ? streakText(s[`${st.who}s`] || 0, DET[st.who]) : ''].filter(Boolean).map(t => `<span>${t}</span>`).join('')}
          ${s.fr != null ? `<span>외국인 지분 <b>${s.fr.toFixed(1)}%</b>${s.frd != null ? ` (20일 <span class="${U.cls(s.frd)}">${s.frd > 0 ? '+' : ''}${s.frd.toFixed(2)}%p</span>)` : ''}</span>` : ''}
          ${gx ? `<span>내년 영업이익 <b class="${gx.k === 'turnaround' ? 'up' : U.cls(gx.g)}">${gx.k === 'turnaround' ? '흑자전환' : gx.k === 'loss' ? '적자' : U.pct(gx.g)}</b></span>` : ''}
        </div>
      </div>
    </article>`;
  }

  function renderList() {
    const sign = st.dir === 'buy' ? 1 : -1;
    const list = filtered().sort((a, b) => (val(b) - val(a)) * sign);
    const head = `${WHO[st.who]} ${DAYS[st.days]} ${st.dir === 'buy' ? '순매수' : '순매도'} ${st.unit === 'pct' ? '시총 대비' : '금액'} 순`;
    for (const [m, label] of Object.entries(MARKETS)) {
      const items = list.filter(s => s.mk === m);
      const n = shown[m] || PAGE;
      const col = $(`col-${m}`);
      col.hidden = st.market !== 'all' && st.market !== m;
      col.innerHTML = `<div class="col-head"><h3>${label} <span class="muted">${items.length}종목, ${head}</span></h3></div>
        ${items.slice(0, n).map((s, i) => rowHtml(s, i + 1)).join('') || '<p class="muted empty">해당 종목 없음</p>'}
        ${items.length > n ? `<button class="more" data-m="${m}">더 보기 (${items.length - n}개 남음)</button>` : ''}`;
    }
  }

  $('summary').addEventListener('click', e => {
    const b = e.target.closest('.fl-det-i');
    if (b) pg.set({ who: b.dataset.who });
  });

  document.querySelector('main .cols').addEventListener('click', e => {
    const b = e.target.closest('.more');
    if (!b) return;
    shown[b.dataset.m] = (shown[b.dataset.m] || PAGE) + PAGE * 2;
    renderList();
  });

  function renderFoot() {
    $('foot').innerHTML = `
      <p>수급: 네이버 증권 종목별 투자자별 매매동향(KRX+넥스트레이드), ${U.dateLabel(data.date)}까지. 금액은 순매수 수량 × 그날 종가로 어림한 값이라 실제 거래대금과 다를 수 있습니다.</p>
      ${data.det ? '<p>기관 세부·기타법인: 한국투자증권 Open API 종목별 투자자 매매동향의 순매수 거래대금(KRX+넥스트레이드).</p>' : ''}
      <p>시총·주가: KRX 종가 (다음 날 아침 KRX 공개 전까지는 네이버 시세로 임시 표시). 이익 성장: FnGuide 컨센서스(네이버 종목분석).</p>
      <p>투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  }

  // ---------- 수급 지도 · 찬집 / 빈집 ----------
  // 얼마나 찼나(중기 누적 ÷ 시총)와 지금 담나 비우나(단기 누적 ÷ 시총)를 한 장에. 점이 너무 많으면 시총 큰 순으로 MAP_N 개
  const MAP_N = 250;
  const QUADS = [
    ['emptyIn', '빈집에 담기 시작', '중기로는 덜어냈는데 최근에 다시 담는 종목', (x, y) => x < 0 && y > 0],
    ['fullIn', '찬집에 더 담는 중', '중기로 많이 담았고 최근에도 담는 종목', (x, y) => x >= 0 && y > 0],
    ['fullOut', '찬집에서 비우는 중', '중기로 많이 담았는데 최근에 덜어내는 종목', (x, y) => x >= 0 && y <= 0],
    ['emptyOut', '빈집에서 더 빠지는 중', '중기로 덜어냈고 최근에도 빠지는 종목', (x, y) => x < 0 && y <= 0],
  ];
  function renderMap() {
    const box = $('flowmap');
    const mid = +st.mapM, short = +st.mapS;
    const who = MAIN[st.who] ? st.who : 'fo';
    if (mid === 120 && !data.map_mid) {                     // 예전 날짜 파일에는 120일 누적이 없다
      $('map-title').innerHTML = '<h2>수급 지도</h2>';
      box.innerHTML = '<p class="muted small" style="padding:12px 16px">이 날짜 데이터에는 120일 누적이 없습니다. 60일을 고르거나 최근 날짜로 보세요.</p>' + mapSeg();
      return;
    }
    const q = st.q.trim().toLowerCase(), cap = CAPS[st.cap];
    const pts = data.stocks.filter(s => s.mc > 0 && (st.market === 'all' || s.mk === st.market) && (!cap || (s.mc >= cap[0] && s.mc < cap[1]))
        && (!q || s.n.toLowerCase().includes(q) || s.c.includes(q)))
      .map(s => ({ s, x: amt(s, who, mid), y: amt(s, who, short) }))
      .filter(p => p.x != null && p.y != null)
      .sort((a, b) => b.s.mc - a.s.mc).slice(0, MAP_N)
      .map(p => ({ ...p, x: p.x / p.s.mc, y: p.y / p.s.mc }));
    $('map-title').innerHTML = `<h2>수급 지도 · 찬집 / 빈집</h2><span class="muted small">${MAIN[who]} · 가로 ${mid}일 누적 ÷ 시총(얼마나 찼나) · 세로 ${short}일 누적 ÷ 시총(지금 담나 비우나) · ${pts.length}종목${pts.length === MAP_N ? ' (시총 큰 순)' : ''}</span>`;
    if (!pts.length) { box.innerHTML = mapSeg() + '<p class="muted small" style="padding:12px 16px">해당 종목 없음</p>'; return; }
    // 축은 원점 대칭, 양 끝 3% 는 가장자리에 붙인다(속이 빈 점) — 한두 종목 때문에 나머지가 한 점에 뭉치지 않게
    const lim = (vs) => { const a = vs.map(Math.abs).sort((u, v) => u - v); return Math.max(a[Math.floor(a.length * 0.97)] || a[a.length - 1], 1e-4); };
    const LX = lim(pts.map(p => p.x)), LY = lim(pts.map(p => p.y));
    const W = 760, H = 420, P = 34;
    const X = v => P + (Math.max(-LX, Math.min(LX, v)) + LX) / (2 * LX) * (W - 2 * P);
    const Y = v => H - P - (Math.max(-LY, Math.min(LY, v)) + LY) / (2 * LY) * (H - 2 * P);
    const mcMax = Math.max(...pts.map(p => p.s.mc));
    const r = mc => 2.5 + Math.sqrt(mc / mcMax) * 9;
    const qOf = p => QUADS.find(qd => qd[3](p.x, p.y))[0];
    const pc = v => `${v > 0 ? '+' : ''}${(v * 100).toFixed(2)}%`;
    const named = new Set([...pts].sort((a, b) => b.s.mc - a.s.mc).slice(0, 12).map(p => p.s.c));
    const dots = pts.map(p => {
      const out = Math.abs(p.x) > LX || Math.abs(p.y) > LY;
      return `<a href="https://finance.naver.com/item/main.naver?code=${p.s.c}" data-code="${p.s.c}" target="_blank" rel="noopener"><circle class="fm-${qOf(p)}${out ? ' out' : ''}" cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="${r(p.s.mc).toFixed(1)}"><title>${U.esc(p.s.n)} · 시총 ${U.eok(p.s.mc).replace(/<[^>]+>/g, '')}\n${mid}일 ${pc(p.x)} · ${short}일 ${pc(p.y)}</title></circle>${named.has(p.s.c) ? `<text x="${(X(p.x) + r(p.s.mc) + 2).toFixed(1)}" y="${(Y(p.y) + 3).toFixed(1)}">${U.esc(p.s.n)}</text>` : ''}</a>`;
    }).join('');
    const axis = `<line class="fm-axis" x1="${P}" x2="${W - P}" y1="${Y(0)}" y2="${Y(0)}"/><line class="fm-axis" x1="${X(0)}" x2="${X(0)}" y1="${P}" y2="${H - P}"/>
      <text class="fm-lab" x="${W - P}" y="${Y(0) - 6}" text-anchor="end">찬집 → ${pc(LX)}</text><text class="fm-lab" x="${P}" y="${Y(0) - 6}">← 빈집 ${pc(-LX)}</text>
      <text class="fm-lab" x="${X(0) + 6}" y="${P - 8}">담는 중 ${pc(LY)}</text><text class="fm-lab" x="${X(0) + 6}" y="${H - P + 18}">비우는 중 ${pc(-LY)}</text>`;
    const lists = QUADS.map(([k, label, tip]) => {
      const xs = pts.filter(p => qOf(p) === k).sort((a, b) => Math.abs(b.y) - Math.abs(a.y)).slice(0, 6);
      return `<div class="fm-q"><h4 class="fm-${k}" title="${tip}">${label} <small class="muted">${pts.filter(p => qOf(p) === k).length}</small></h4>
        <ol>${xs.map(p => `<li>${Stock.link(p.s)} <small class="muted">${mid}일 ${pc(p.x)} · ${short}일</small> <b class="${p.y > 0 ? 'up' : 'down'}">${pc(p.y)}</b></li>`).join('') || '<li class="muted">없음</li>'}</ol></div>`;
    }).join('');
    box.innerHTML = `${mapSeg()}<svg class="fm-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${axis}${dots}</svg><div class="fm-qs">${lists}</div>
      <p class="muted small fm-note">순매수 금액은 수량 × 종가 어림. 점 크기 = 시총, 이름은 시총 상위 12종목. 속이 빈 점은 축 범위를 넘어 가장자리에 붙인 것. 주체가 기관 세부일 때는 외국인+기관으로 그립니다.</p>`;
  }
  const mapSeg = () => `<div class="frow fm-ctl">${pg.seg('mapM', [['120', '중기 120일'], ['60', '중기 60일']])}${pg.seg('mapS', [['20', '단기 20일'], ['5', '단기 5일']])}</div>`;

  // ---------- ETF 기계적 수급 (KBJ 내보내기) ----------
  const ESORT = { in: ['순유입 큰 순', r => -(r.in ?? 0)], out: ['순유출 큰 순', r => r.in ?? 0], pct: ['거래대금 대비 큰 순', r => -Math.abs(r.pct ?? 0)] };
  function renderEtf() {
    const box = $('etfflow');
    if (!etf) { $('etf-title').innerHTML = ''; box.hidden = true; return; }
    box.hidden = false;
    const P = etf.periods[st.ep] || etf.periods['5'];
    const by = Object.fromEntries(data.stocks.map(s => [s.c, s]));
    const q = st.q.trim().toLowerCase(), cap = CAPS[st.cap];
    const rows = P.rows.filter(r => { const s = by[r.c]; if (st.market !== 'all' && s && s.mk !== st.market) return false;
        if (cap && s && (s.mc < cap[0] || s.mc >= cap[1])) return false; return !q || (r.n || '').toLowerCase().includes(q) || r.c.includes(q); })
      .filter(r => (st.es === 'out' ? r.in < 0 : st.es === 'in' ? r.in > 0 : true))
      .sort((a, b) => ESORT[st.es][1](a) - ESORT[st.es][1](b)).slice(0, 30);
    const d = +st.ep, fo = s => (s && s[`f${d}`] != null && s[`o${d}`] != null ? s[`f${d}`] + s[`o${d}`] : null);
    const pc = v => (v == null ? '–' : `<b class="${U.cls(v)}">${v > 0 ? '+' : ''}${v.toFixed(1)}%</b>`);
    $('etf-title').innerHTML = `<h2>ETF 기계적 수급</h2><span class="muted small">ETF 설정·환매 × 구성 비중 → 종목 · ${P.start}~${P.end} · 구성종목을 아는 ETF ${P.n_etfs}개가 순유입의 ${P.coverage?.toFixed(0)}% 를 덮음(값은 하한) · KBJ ${U.timeLabel(etf.generated_at)} 내보냄 · PDF ${etf.holdings_asof}</span>`;
    box.innerHTML = `<div class="frow fm-ctl">${pg.seg('ep', [['1', '1일'], ['5', '5일'], ['20', '20일']])}${pg.seg('es', Object.entries(ESORT).map(([k, v]) => [k, v[0]]))}</div>
      <div class="tbl-wrap"><table class="tbl" data-nosort><thead><tr><th>종목</th><th class="num">시총</th><th class="num">ETF 순유입 몫</th><th class="num" title="순유입 몫 ÷ 같은 기간 종목 거래대금">÷ 거래대금</th><th class="num">÷ 시총</th>
        <th class="num" title="같은 기간 외국인+기관 순매수(수량×종가 어림) — 수급 탭 날짜 기준">외국인+기관</th><th class="num">ETF 수</th><th>순유입 큰 ETF</th></tr></thead>
      <tbody>${rows.map(r => { const s = by[r.c];
        return `<tr><td>${Stock.link({ c: r.c, n: r.n || s?.n || r.c })}</td><td class="num">${s ? U.eok(s.mc) : '–'}</td><td class="num">${r.in == null ? '–' : U.eok(r.in, true)}</td><td class="num">${pc(r.pct)}</td>
          <td class="num">${s && r.in != null ? pc(r.in / s.mc * 100) : '–'}</td><td class="num">${fo(s) == null ? '–' : U.eok(fo(s), true)}</td><td class="num">${r.ne ?? '–'}</td>
          <td class="small">${r.top.map(t => `${U.esc(t[0])} <span class="muted">${t[1] == null ? '' : `${t[1] > 0 ? '+' : ''}${t[1].toLocaleString('ko-KR')}억`}</span>`).join(' · ')}</td></tr>`; }).join('') || '<tr><td colspan="8" class="muted empty">해당 없음</td></tr>'}</tbody></table></div>
      <p class="muted small fm-note">순유입 몫 = ETF 순설정(+)·환매(−) 금액 × 그 ETF 가 담은 이 종목 비중(운용사 PDF). LP·운용사의 바스켓 매매 추정이라 외국인·기관 순매수에 섞여 있을 수 있습니다. 선물·스왑으로 담는 레버리지·인버스 노출은 빠집니다. 시장·시총·검색 필터를 따릅니다.</p>`;
  }

  function renderBody() {
    renderSummary();
    renderList();
    renderMap();
    renderEtf();
  }

  function render() {
    renderFilters();
    renderBody();
    renderSignals();
    renderFoot();
  }

  function showError(msg) {
    $('msg').hidden = false;
    $('msg').textContent = msg;
  }

  async function load(d) {
    try {
      data = await U.json(`data/flow/${d}.json`);
    } catch (e) {
      return showError(`${d} 데이터를 불러오지 못했습니다. (${e.message})`);
    }
    $('msg').hidden = true;
    if (!data.det && DET[st.who]) { st.who = 'f'; pg.write(); }   // 세부가 없는 날짜로 옮기면 외국인으로
    render();
  }

  pg.bind($('filters'));
  pg.bind($('flowmap'));
  pg.bind($('etfflow'));
  U.initTheme($('theme'));
  try { $('summary-box').open = (localStorage.getItem('flSummaryOpen') ?? '1') === '1'; } catch (e) {}
  $('summary-box').addEventListener('toggle', () => { try { localStorage.setItem('flSummaryOpen', $('summary-box').open ? '1' : ''); } catch (e) {} });

  (async () => {
    try {
      await U.dates('flow', pg, $('date'), load);
    } catch (e) {
      return showError('데이터 목록을 불러오지 못했습니다.');
    }
    try { etf = await U.json('data/etf_flow.json'); } catch (e) { etf = null; }
    load(st.date);
  })();
})();
