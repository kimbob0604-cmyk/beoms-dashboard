// 수급 탭: data/flow/{거래일}.json — 종목별 외국인·기관 순매수 금액(억원, 수량×종가 어림)
// - 수급 시그널 카드: 쌍끌이 순매수·순매도, 외국인 연속 순매수·순매도, 수급 반전 (build_naver.flow_signals 가 고른 종목)
//   아래 필터(주체·기간·시장)와 상관없이 그날 전 종목에서 고른다
(() => {
  const WHO = { f: '외국인', o: '기관', fo: '외국인+기관' };
  const DAYS = { 1: '1일', 5: '5일', 20: '20일', 60: '60일' };
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  const STREAK_MIN = 3;
  const PAGE = 40;
  const DEFAULTS = { date: '', who: 'f', days: '5', dir: 'buy', unit: 'amt', market: 'all', cap: 'all', q: '', streak: '', both: '', growth: '' };

  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => { shown = {}; typing ? renderBody() : render(); });
  const st = pg.state;
  let data = null, shown = {};

  // 선택한 주체·기간의 순매수 금액. 시총 대비면 % (소수)
  const amt = (s, who = st.who, d = st.days) =>
    (who === 'fo' ? (s[`f${d}`] == null || s[`o${d}`] == null ? null : s[`f${d}`] + s[`o${d}`]) : s[`${who}${d}`]);
  const val = s => { const a = amt(s); return a == null ? null : st.unit === 'pct' ? a / s.mc : a; };
  const streakOf = s => (st.who === 'o' ? s.os : st.who === 'f' ? s.fs : Math.sign(s.fs) === Math.sign(s.os) ? Math.min(Math.abs(s.fs), Math.abs(s.os)) * Math.sign(s.fs) : 0);
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
        ${pg.seg('who', Object.entries(WHO))}
        ${pg.seg('days', Object.entries(DAYS))}
        ${pg.seg('dir', [['buy', '순매수'], ['sell', '순매도']])}
        ${pg.seg('unit', [['amt', '금액 순'], ['pct', '시총 대비 순', '순매수 금액 ÷ 시가총액']])}
      </div>
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
      </div>`;
    }).join('');
    $('summary').innerHTML = `
      <p class="sub">시총 1,000억 이상 보통주와 컨센서스·리포트가 있는 종목의 합입니다 (시장 전체 합계와 다름).</p>
      <div class="rv-mks">${cards}</div>
      <p class="note">금액 = 그날 순매수 수량 × 정규장 종가, ${DAYS[d]} 합. 기관은 금융투자·연기금 등 합계. 출처 네이버 증권 투자자별 매매동향.</p>`;
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
        <div class="r-line">외국인 <b class="${U.cls(s[`f${d}`])}">${U.eok(s[`f${d}`], true)}</b> · 기관 <b class="${U.cls(s[`o${d}`])}">${U.eok(s[`o${d}`], true)}</b> · 개인 <b class="${U.cls(s[`i${d}`])}">${U.eok(s[`i${d}`], true)}</b>, 시총 ${U.eok(s.mc)} <span class="${U.cls(s.ch)}">${s.ch > 0 ? '+' : ''}${s.ch?.toFixed(2) ?? '–'}%</span></div>
        <div class="r-sub">
          ${[streakText(s.fs, '외국인'), streakText(s.os, '기관')].filter(Boolean).map(t => `<span>${t}</span>`).join('')}
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

  document.querySelector('main .cols').addEventListener('click', e => {
    const b = e.target.closest('.more');
    if (!b) return;
    shown[b.dataset.m] = (shown[b.dataset.m] || PAGE) + PAGE * 2;
    renderList();
  });

  function renderFoot() {
    $('foot').innerHTML = `
      <p>수급: 네이버 증권 종목별 투자자별 매매동향(KRX 정규장), ${U.dateLabel(data.date)}까지. 금액은 순매수 수량 × 그날 종가로 어림한 값이라 실제 거래대금과 다를 수 있습니다.</p>
      <p>시총·주가: KRX 종가 (다음 날 아침 KRX 공개 전까지는 네이버 시세로 임시 표시). 이익 성장: FnGuide 컨센서스(네이버 종목분석).</p>
      <p>투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  }

  function renderBody() {
    renderSummary();
    renderList();
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
    render();
  }

  pg.bind($('filters'));
  U.initTheme($('theme'));
  try { $('summary-box').open = (localStorage.getItem('flSummaryOpen') ?? '1') === '1'; } catch (e) {}
  $('summary-box').addEventListener('toggle', () => { try { localStorage.setItem('flSummaryOpen', $('summary-box').open ? '1' : ''); } catch (e) {} });

  (async () => {
    try {
      await U.dates('flow', pg, $('date'), load);
    } catch (e) {
      return showError('데이터 목록을 불러오지 못했습니다.');
    }
    load(st.date);
  })();
})();
