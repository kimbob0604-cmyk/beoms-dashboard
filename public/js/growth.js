// 이익 성장 탭: data/growth/{기준일}.json → 필터·정렬·합계·종목 목록
(() => {
  const BUCKETS = [
    ['turnaround', '흑자전환'], ['g100', '100% 이상'], ['g50', '50~100%'],
    ['g0', '0~50%'], ['decline', '감익'], ['loss', '적자 지속'],
  ];
  const METRICS = { op: ['영업이익', 'POR'], ni: ['순이익', 'PER'], revenue: ['매출', 'PSR'], eps: ['EPS', 'PER'] };
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };   // 억
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  const DEFAULTS = {
    date: '', period: 'y0', metric: 'op', sort: 'g', dir: '', market: 'all', cap: 'all', sector: '', bucket: '', q: '',
    nolb: '', st: '', up: '', view: '',
  };
  const PAGE = 40;           // 목록: 시장별 처음 보이는 수
  const PAGE_T = 100;        // 표: 처음 보이는 행 수
  const STREAK_MIN = 3;      // 연속 증익 배지: 화면 5개 연도 중 3년 이상
  const REV_BADGE = 0.01;    // 상향/하향 배지: 다음 연도 추정치 1개월 변화 ±1% 이상

  const $ = id => document.getElementById(id);
  let state = readState();
  let dates = [];
  let data = null;
  let shown = {};

  // ---------- 상태 ↔ URL ----------
  function readState() {
    const p = new URLSearchParams(location.search);
    const s = { ...DEFAULTS };
    for (const k in s) if (p.has(k)) s[k] = p.get(k);
    return s;
  }

  function writeState() {
    const p = new URLSearchParams();
    for (const k in state) {
      if (state[k] === DEFAULTS[k] || (k === 'date' && state.date === dates[0])) continue;
      p.set(k, state[k]);
    }
    const qs = p.toString();
    history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
  }

  function set(patch) {
    Object.assign(state, patch);
    shown = {};
    writeState();
    render();
  }

  // ---------- 계산 ----------
  // 현재 기간·지표의 계산값 (없으면 undefined)
  const pick = s => s.k[state.period]?.[state.metric];
  const isEps = () => state.metric === 'eps';
  const fmtVal = (v, signed) => (isEps() ? U.won(v, signed) : U.eok(v, signed));
  const streakYears = s => s.st[state.metric]?.years ?? 0;
  const fy2 = fy => String(fy).slice(2);
  const baseFy = () => data.fy0 + (state.period === 'y1' ? 1 : 0);   // 헤더 표기용 출발 연도

  // skip: 이 화면 요소에는 적용하지 않을 필터 (예: 요약 카운트는 구간 필터 무시)
  function filtered(skip = []) {
    const q = state.q.trim().toLowerCase();
    const cap = CAPS[state.cap];
    return data.stocks.filter(s => {
      const v = pick(s);
      if (!v) return false;
      if (state.market !== 'all' && s.mk !== state.market) return false;
      if (cap && (s.mc < cap[0] || s.mc >= cap[1])) return false;
      if (state.nolb && v.lb) return false;
      if (state.st && !(streakYears(s) >= STREAK_MIN)) return false;
      if (state.up && !(v.m1 >= REV_BADGE)) return false;
      if (!skip.includes('sector') && state.sector && s.w !== state.sector) return false;
      if (!skip.includes('q') && q && !s.n.toLowerCase().includes(q) && !s.c.includes(q)) return false;
      if (!skip.includes('bucket') && state.bucket && v.k !== state.bucket) return false;
      return true;
    });
  }

  // 합계 성장률 = Σ내년 / Σ올해 − 1. EPS는 더할 수 없어서 중앙값.
  function aggregate(list) {
    if (isEps()) {
      const gs = list.map(s => pick(s).g).filter(g => g != null).sort((a, b) => a - b);
      if (!gs.length) return { g: null };
      const m = gs.length >> 1;
      return { g: gs.length % 2 ? gs[m] : (gs[m - 1] + gs[m]) / 2 };
    }
    let b = 0, n = 0;
    for (const s of list) { const v = pick(s); b += v.b; n += v.n; }
    return { b, n, g: b > 0 ? (n - b) / b : null };
  }

  // ---------- 정렬 ----------
  // 각 키의 기본 방향(desc=큰 값 먼저)이 있고, dir='r'이면 뒤집는다. 값 없는 종목은 방향과 상관없이 맨 뒤.
  const reversed = () => state.dir === 'r';
  const byKey = (f, desc) => (a, b) => {
    const x = f(a), y = f(b);
    if (x == null) return y == null ? 0 : 1;
    if (y == null) return -1;
    return desc !== reversed() ? y - x : x - y;
  };
  // 성장률 순: 흑자전환 → 성장률 높은 순 → 기저(출발값이 작아 성장률 과장) → 적자 지속.
  // 흑자전환·적자는 성장률이 정의 안 돼서 증가액 순.
  const group = v => (v.k === 'turnaround' ? 0 : v.k === 'loss' ? 3 : v.lb ? 2 : 1);
  const growthCmp = (a, b) => {
    const x = pick(a), y = pick(b);
    return (group(x) - group(y))
      || (x.g != null && y.g != null ? y.g - x.g : (y.n - y.b) - (x.n - x.b));
  };
  const m1Cmp = byKey(s => pick(s).m1, true);
  const m3Cmp = byKey(s => pick(s).m3, true);
  const SORTS = {
    g: (a, b) => (reversed() ? growthCmp(b, a) : growthCmp(a, b)),
    por: byKey(s => pick(s).mn, false),
    // 내년 배수 ÷ 성장률(%) — PEG처럼 낮을수록 성장 대비 싸다. 역성장·적자는 뒤로.
    peg: byKey(s => { const v = pick(s); return v.g > 0 && v.mn != null ? v.mn / (v.g * 100) : null; }, false),
    // 컨센 상향 순: 1개월 변화, 같으면 3개월 변화
    rev: (a, b) => m1Cmp(a, b) || m3Cmp(a, b),
    m3: m3Cmp,
    delta: byKey(s => { const v = pick(s); return v.n - v.b; }, true),
    mc: byKey(s => s.mc, true),
    ch: byKey(s => s.ch, true),
    st: byKey(s => streakYears(s) || null, true),
    name: (a, b) => (reversed() ? -1 : 1) * a.n.localeCompare(b.n, 'ko'),
  };
  // 표의 다른 지표 성장률 열: g_revenue / g_op / g_ni
  const sorter = key => SORTS[key]
    || (key.startsWith('g_') && METRICS[key.slice(2)] ? byKey(s => s.k[state.period]?.[key.slice(2)]?.g, true) : SORTS.g);
  const DESC = key => ['g', 'rev', 'm3', 'delta', 'mc', 'ch', 'st'].includes(key) || key.startsWith('g_');

  function sortLabel() {
    const mult = METRICS[state.metric][1];
    const labels = {
      g: '성장률 순', por: `${mult} 낮은 순`, peg: `성장률+${mult} 순`, rev: '컨센 상향 순', m3: '3개월 상향 순',
      delta: '증가액 순', mc: '시총 순', ch: '등락률 순', st: '연속 증익 순', name: '이름 순',
    };
    const label = labels[state.sort] || (state.sort.startsWith('g_') ? `${METRICS[state.sort.slice(2)]?.[0] ?? ''} 성장률 순` : '성장률 순');
    return label + (reversed() ? ' (역순)' : '');
  }

  // ---------- 필터 ----------
  function seg(key, opts) {
    return `<div class="seg" role="group">${opts.map(([val, label, title]) =>
      `<button data-k="${key}" data-v="${val}" class="${state[key] === val ? 'on' : ''}"${title ? ` title="${title}"` : ''}>${label}</button>`).join('')}</div>`;
  }

  function chk(key, label, title) {
    return `<label class="chk${state[key] ? ' on' : ''}" title="${title}"><input type="checkbox" data-chk="${key}"${state[key] ? ' checked' : ''}> ${label}</label>`;
  }

  function renderFilters() {
    const mult = METRICS[state.metric][1];
    const sectors = {};
    for (const s of data.stocks) if (pick(s) && s.w) sectors[s.w] = (sectors[s.w] || 0) + 1;
    const sectorOpts = Object.keys(sectors).sort((a, b) => a.localeCompare(b, 'ko'))
      .map(w => `<option value="${U.esc(w)}"${w === state.sector ? ' selected' : ''}>${U.esc(w)} (${sectors[w]})</option>`).join('');
    $('filters').innerHTML = `
      <div class="frow">
        ${seg('period', [['y0', '올해→내년'], ['y1', '내년→내후년']])}
        ${seg('metric', Object.entries(METRICS).map(([k, [l]]) => [k, l]))}
        ${seg('sort', [['g', '성장률 순'], ['por', `${mult} 낮은 순`], ['peg', `성장률+${mult}`, `내년 ${mult} ÷ 성장률(%) 낮은 순`],
          ['rev', '컨센 상향', '내년 추정치 1개월 변화 큰 순 (같으면 3개월)']])}
      </div>
      <div class="frow">
        ${seg('market', [['all', '전체'], ['KOSPI', '코스피'], ['KOSDAQ', '코스닥']])}
        ${seg('cap', [['all', '시총 전체'], ['L', '1조 이상'], ['M', '3천억~1조'], ['S', '3천억 미만']])}
        <select id="sector" aria-label="업종"><option value="">업종 전체</option>${sectorOpts}</select>
        <input id="q" type="search" placeholder="종목명·코드 검색" value="${U.esc(state.q)}" autocomplete="off">
        ${chk('st', '연속 증익만', `화면 5개 연도 중 ${STREAK_MIN}년 이상 연속 증가`)}
        ${chk('up', '상향만', `내년 추정치가 1개월 전보다 ${REV_BADGE * 100}% 이상 상향`)}
        ${chk('nolb', '기저 제외', '출발값이 30억 미만이거나 시총의 1% 미만인 종목')}
      </div>`;
    $('view').innerHTML = seg('view', [['', '목록'], ['compact', '간단히', '연도별 실적 줄 숨기기'], ['table', '표', '한 줄에 한 종목, 열 제목으로 정렬']]);
  }

  const onSeg = e => {
    const b = e.target.closest('button[data-k]');
    if (!b) return;
    set(b.dataset.k === 'sort' ? { sort: b.dataset.v, dir: '' } : { [b.dataset.k]: b.dataset.v });
  };
  $('filters').addEventListener('click', onSeg);
  $('view').addEventListener('click', onSeg);
  $('filters').addEventListener('change', e => {
    if (e.target.id === 'sector') set({ sector: e.target.value });
    if (e.target.dataset.chk) set({ [e.target.dataset.chk]: e.target.checked ? '1' : '' });
  });
  let qTimer;
  $('filters').addEventListener('input', e => {
    if (e.target.id !== 'q') return;
    clearTimeout(qTimer);
    qTimer = setTimeout(() => {
      Object.assign(state, { q: e.target.value });
      shown = {};
      writeState();
      renderBody();   // 검색창 포커스를 유지하려고 필터 영역은 다시 그리지 않음
    }, 150);
  });

  // ---------- 요약 ----------
  function renderSummary() {
    const list = filtered(['bucket']);
    const counts = Object.fromEntries(BUCKETS.map(([k]) => [k, 0]));
    for (const s of list) counts[pick(s).k]++;
    const mName = METRICS[state.metric][0];
    const mult = METRICS[state.metric][1];
    const fy = baseFy();

    $('summary-head').innerHTML = `<h2>FY${fy2(fy)}→FY${fy2(fy + 1)} ${mName} 성장률</h2>
      <span class="muted small">컨센 ${U.dateLabel(data.cns_date)} 기준</span>`;

    const aggs = Object.entries(MARKETS).map(([m, label]) => {
      const l = list.filter(s => s.mk === m);
      if (!l.length) return '';
      const a = aggregate(l);
      const detail = isEps() ? `${l.length}종목, EPS 성장률 중앙값` : `${l.length}종목, ${U.eok(a.b)} → ${U.eok(a.n)}`;
      return `<span>${label} 합계 <b class="${U.cls(a.g)}">${U.pct(a.g)}</b> <span class="muted">(${detail})</span></span>`;
    }).join('');

    const multNote = state.metric === 'eps'
      ? 'PER = 주가 ÷ 그해 EPS 추정치.'
      : `${mult} = 시가총액 ÷ 그해 ${mName} 추정치 (${['순이익이면 PER', '매출이면 PSR', 'EPS면 주가 ÷ EPS'].filter(t => !t.startsWith(mName)).join(', ')}).`;

    $('summary').innerHTML = `
      <p class="sub">컨센서스는 <b>${U.dateLabel(data.cns_date)} 기준</b>입니다 (FnGuide 기준일). 마지막 확인 ${U.timeLabel(data.checked_at)}.</p>
      <div class="sum-row">
        <div class="buckets">${BUCKETS.map(([k, label]) => `
          <button class="bk ${k}${state.bucket === k ? ' on' : ''}" data-b="${k}" title="누르면 이 구간만 보기">
            <span>${label}</span><b>${counts[k]}<small>종목</small></b>
          </button>`).join('')}
        </div>
        <div class="dist">${BUCKETS.map(([k, label]) =>
          counts[k] ? `<i class="${k}" style="flex:${counts[k]}" title="${label} ${counts[k]}종목"></i>` : '').join('')}</div>
      </div>
      <p class="aggs">${aggs || '<span class="muted">해당 종목 없음</span>'}</p>
      <p class="note">${multNote} 기저 = 출발 연도 이익이 30억 미만이거나 시총의 1% 미만이라 성장률이 과장될 수 있는 종목.</p>`;
  }

  $('summary').addEventListener('click', e => {
    const b = e.target.closest('[data-b]');
    if (b) set({ bucket: state.bucket === b.dataset.b ? '' : b.dataset.b });
  });

  // ---------- 업종별 합계 ----------
  function renderSectors() {
    $('sectors-head').innerHTML = `<b>업종별 합계 성장률</b> <span class="muted">그 업종 종목들의 ${isEps() ? 'EPS 성장률 중앙값' : `${METRICS[state.metric][0]} 합계`} 기준, 2종목 이상 · 누르면 업종 필터</span>`;
    const groups = {};
    for (const s of filtered(['sector', 'bucket', 'q'])) if (s.w) (groups[s.w] ||= []).push(s);
    const rows = Object.entries(groups).filter(([, l]) => l.length >= 2)
      .map(([w, l]) => ({ w, l, a: aggregate(l) }))
      .sort((x, y) => (y.a.g ?? -Infinity) - (x.a.g ?? -Infinity));
    const maxAbs = Math.max(...rows.map(r => Math.abs(r.a.g ?? 0)), 0.01);

    $('sector-list').innerHTML = rows.length ? `<div class="sec-grid">${rows.map(r => `
      <button class="sec${r.w === state.sector ? ' on' : ''}" data-w="${U.esc(r.w)}">
        <span class="sec-name">${U.esc(r.w)} <small class="muted">${r.l.length}</small></span>
        <span class="sec-val muted">${isEps() ? '' : `${U.eok(r.a.b)} → ${U.eok(r.a.n)}`}</span>
        <span class="sec-bar"><i style="width:${Math.min(100, Math.abs(r.a.g ?? 0) / maxAbs * 100)}%"></i></span>
        <b class="${U.cls(r.a.g)}">${U.pct(r.a.g)}</b>
      </button>`).join('')}</div>` : '<p class="muted">해당 업종 없음</p>';
  }

  $('sector-list').addEventListener('click', e => {
    const b = e.target.closest('[data-w]');
    if (b) set({ sector: state.sector === b.dataset.w ? '' : b.dataset.w });
  });

  // ---------- 종목 목록 ----------
  function growthText(v) {
    if (v.k === 'turnaround') return '흑자전환';
    if (v.k === 'loss') return '적자 지속';
    if (v.n <= 0) return '적자전환';
    return U.pct(v.g);
  }

  const gClass = v => (v.k === 'turnaround' ? 'up' : v.k === 'loss' ? 'down' : U.cls(v.g));
  const nextFyOf = s => s.fy0 + (state.period === 'y1' ? 2 : 1);
  const naverLink = s => `<a href="https://finance.naver.com/item/main.naver?code=${s.c}" target="_blank" rel="noopener">${U.esc(s.n)}</a>`;
  const chHtml = s => `<span class="${U.cls(s.ch)}">${s.ch > 0 ? '+' : ''}${s.ch?.toFixed(2) ?? '–'}%</span>`;
  const streakBadge = s => {
    const st = s.st[state.metric];
    return st && st.years >= STREAK_MIN
      ? `<span class="badge">FY${fy2(st.from)}부터 ${st.years}년 연속 ${state.metric === 'revenue' ? '성장' : '증익'}</span>` : '';
  };
  const lowBadge = v => (v.lb ? '<span class="pill" title="출발값이 작아 성장률이 과장될 수 있음">기저</span>' : '');
  function revPill(s, v) {
    const title = `FY${fy2(nextFyOf(s))}E 추정치가 1개월 전보다 ${U.pct(v.m1)}`;
    if (v.m1 >= REV_BADGE) return `<span class="pill" title="${title}">상향</span>`;
    if (v.m1 <= -REV_BADGE) return `<span class="pill" title="${title}">하향</span>`;
    return '';
  }

  // FY24 484억 +37% · FY25 565억 +17% · ...
  function seriesHtml(s) {
    const arr = s.s[state.metric];
    return arr.map(([fy, val, est], i) => {
      const prev = i ? arr[i - 1][1] : null;
      const yoy = prev > 0 && val != null ? (val - prev) / prev : null;
      return `<span class="yr">FY${fy2(fy)}${est ? 'E' : ''} <b>${fmtVal(val)}</b>${yoy == null ? '' : ` <span class="${U.cls(yoy)}">${U.pct(yoy, 0)}</span>`}</span>`;
    }).join('');
  }

  function rowHtml(s, rank) {
    const v = pick(s);
    const [mName, mult] = METRICS[state.metric];
    return `<article class="row">
      <span class="rank">${rank}</span>
      <div class="r-main">
        <div class="r-top">
          <div class="r-name">${naverLink(s)}${s.w ? `<span class="tag">${U.esc(s.w)}</span>` : ''}<span class="muted">${U.eok(s.mc)}</span>${streakBadge(s)}</div>
          <div class="r-growth"><small>${fmtVal(v.n - v.b, true)}</small><b class="${gClass(v)}">${growthText(v)}</b></div>
        </div>
        <div class="r-line">${mName} ${fmtVal(v.b)} → <b>${fmtVal(v.n)}</b>, ${mult} ${U.mult(v.mb)} → ${U.mult(v.mn)}, 주가 ${U.price(s.p)}</div>
        <div class="r-series">${seriesHtml(s)}</div>
        <div class="r-rev" title="FY${fy2(nextFyOf(s))}E 추정치의 1개월 전·3개월 전 대비 변화">FY${fy2(nextFyOf(s))} 추정치
          <span class="chip">1개월 <b class="${U.cls(v.m1)}">${U.pct(v.m1)}</b></span>
          <span class="chip">3개월 <b class="${U.cls(v.m3)}">${U.pct(v.m3)}</b></span>
          ${revPill(s, v)}${lowBadge(v)}
        </div>
      </div>
    </article>`;
  }

  // ---------- 표 ----------
  function th(key, label, cls = '', title = '') {
    if (!key) return `<th class="${cls}">${label}</th>`;
    const on = state.sort === key;
    const arrow = on ? (DESC(key) !== reversed() ? ' ↓' : ' ↑') : '';
    return `<th class="sortable ${cls}${on ? ' on' : ''}" data-s="${key}"${title ? ` title="${title}"` : ''}>${label}${arrow}</th>`;
  }

  function renderTable(list) {
    const [mName, mult] = METRICS[state.metric];
    const fy = baseFy();
    const others = ['revenue', 'op', 'ni'].filter(m => m !== state.metric);
    const n = shown.table || PAGE_T;
    const rows = list.slice(0, n).map((s, i) => {
      const v = pick(s);
      const st = streakYears(s);
      const otherCells = others.map(m => {
        const o = s.k[state.period]?.[m];
        return `<td class="num ${o ? gClass(o) : ''}">${o ? growthText(o) : '–'}</td>`;
      }).join('');
      return `<tr>
        <td class="num muted">${i + 1}</td>
        <td class="name-cell">${naverLink(s)}<small class="muted">${MARKETS[s.mk]} · ${U.esc(s.w || '')}</small></td>
        <td class="num">${U.eok(s.mc)}</td>
        <td class="num">${U.price(s.p)}<small>${chHtml(s)}</small></td>
        <td class="num">${fmtVal(v.b)} → <b>${fmtVal(v.n)}</b></td>
        <td class="num strong ${gClass(v)}">${growthText(v)}</td>
        <td class="num muted">${fmtVal(v.n - v.b, true)}</td>
        ${otherCells}
        <td class="num">${U.mult(v.mb)} → ${U.mult(v.mn)}</td>
        <td class="num ${U.cls(v.m1)}">${U.pct(v.m1)}</td>
        <td class="num ${U.cls(v.m3)}">${U.pct(v.m3)}</td>
        <td class="num">${st >= STREAK_MIN ? `${st}년` : ''}</td>
        <td>${revPill(s, v)}${lowBadge(v)}</td>
      </tr>`;
    }).join('');
    const cols = 12 + others.length;
    $('table').innerHTML = `<div class="tbl-wrap card">
      <div class="col-head"><h3>전체 <span class="muted">${list.length}종목, ${sortLabel()} · 열 제목을 누르면 정렬, 한 번 더 누르면 반대로</span></h3></div>
      <table class="tbl">
      <thead><tr>
        ${th('', '#', 'num')}${th('name', '종목')}${th('mc', '시총', 'num')}${th('ch', '주가', 'num')}
        ${th('', `${mName} FY${fy2(fy)}→${fy2(fy + 1)}E`, 'num')}${th('g', `${mName} 성장`, 'num')}${th('delta', '증가액', 'num')}
        ${others.map(m => th(`g_${m}`, `${METRICS[m][0]} 성장`, 'num', `같은 기간 ${METRICS[m][0]} 성장률`)).join('')}
        ${th('por', mult, 'num')}${th('rev', '컨센 1M', 'num')}${th('m3', '3M', 'num')}${th('st', '연속', 'num')}${th('', '')}
      </tr></thead>
      <tbody>${rows || `<tr><td colspan="${cols}" class="muted empty">해당 종목 없음</td></tr>`}</tbody>
    </table></div>
    ${list.length > n ? `<button class="more" data-m="table">더 보기 (${list.length - n}개 남음)</button>` : ''}`;
  }

  $('table').addEventListener('click', e => {
    const h = e.target.closest('th[data-s]');
    if (h) set(state.sort === h.dataset.s ? { dir: state.dir ? '' : 'r' } : { sort: h.dataset.s, dir: '' });
    if (e.target.closest('.more')) {
      shown.table = (shown.table || PAGE_T) + PAGE_T * 2;
      renderList();
    }
  });

  function renderList() {
    const list = filtered().sort(sorter(state.sort));
    const table = state.view === 'table';
    const cols = document.querySelector('.cols');
    $('table').hidden = !table;
    cols.hidden = table;
    if (table) return renderTable(list);
    cols.classList.toggle('compact', state.view === 'compact');
    for (const [m, label] of Object.entries(MARKETS)) {
      const col = $(`col-${m}`);
      const items = list.filter(s => s.mk === m);
      const n = shown[m] || PAGE;
      col.hidden = state.market !== 'all' && state.market !== m;
      col.innerHTML = `<div class="col-head"><h3>${label} <span class="muted">${items.length}종목, ${sortLabel()}</span></h3></div>
        ${items.slice(0, n).map((s, i) => rowHtml(s, i + 1)).join('') || '<p class="muted empty">해당 종목 없음</p>'}
        ${items.length > n ? `<button class="more" data-m="${m}">더 보기 (${items.length - n}개 남음)</button>` : ''}`;
    }
  }

  document.querySelector('.cols').addEventListener('click', e => {
    const b = e.target.closest('.more');
    if (!b) return;
    shown[b.dataset.m] = (shown[b.dataset.m] || PAGE) + PAGE * 2;
    renderList();
  });

  // ---------- 출처 ----------
  function renderFoot() {
    const d = U.dateLabel(data.date);
    $('foot').innerHTML = `
      <p>컨센서스: FnGuide 종목별 컨센서스(네이버 종목분석, 연결 우선·없으면 별도), 기준일 ${U.dateLabel(data.cns_date)}. 1개월·3개월 비교는 FnGuide의 1개월 전·3개월 전 값.</p>
      <p>시세: ${d} KRX 정규장 종가(KRX Open API). 시총은 보통주+우선주.</p>
      <p>업종: WICS(네이버 금융). 금액 단위 억원, EPS·주가 원. 변화율 = (현재 − 이전) ÷ |이전|.</p>
      <p>컨센서스 데이터의 권리는 FnGuide에 있습니다. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  }

  // ---------- 진입 ----------
  function renderBody() {
    renderSummary();
    renderSectors();
    renderList();
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

  async function loadDate(d) {
    try {
      data = await U.json(`data/growth/${d}.json`);
    } catch (e) {
      showError(`${d} 데이터를 불러오지 못했습니다. (${e.message})`);
      return;
    }
    $('msg').hidden = true;
    render();
  }

  $('date').addEventListener('change', e => {
    state.date = e.target.value;
    shown = {};
    writeState();
    loadDate(state.date);
  });

  U.initTheme($('theme'));

  // 요약·업종 합계 펼침 상태 기억 (요약은 기본 펼침, 업종은 기본 접힘)
  for (const [id, key, dflt] of [['summary-box', 'summaryOpen', '1'], ['sectors', 'sectorsOpen', '']]) {
    try { $(id).open = (localStorage.getItem(key) ?? dflt) === '1'; } catch (e) {}
    $(id).addEventListener('toggle', () => {
      try { localStorage.setItem(key, $(id).open ? '1' : ''); } catch (e) {}
    });
  }

  (async () => {
    try {
      dates = await U.json('data/growth/dates.json');
    } catch (e) {
      showError('데이터 목록을 불러오지 못했습니다. 로컬 서버로 열었는지 확인하세요: python3 serve.py');
      return;
    }
    if (!dates.length) return showError('빌드된 날짜가 없습니다. python3 build_growth.py 를 먼저 실행하세요.');
    if (!dates.includes(state.date)) state.date = dates[0];
    $('date').innerHTML = dates.map(d => `<option value="${d}"${d === state.date ? ' selected' : ''}>${U.dateLabel(d)} 기준</option>`).join('');
    loadDate(state.date);
  })();
})();
