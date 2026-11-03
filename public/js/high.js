// 신고가 탭: data/high/{거래일}.json — 네이버 52주 신고가 목록 + 최근 20거래일 기록
(() => {
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  const SORTS = {
    ch: ['등락률 순', s => s.ch],
    mc: ['시총 순', s => s.mc],
    n20: ['신고가 횟수 순', s => s.n20 * 1000 + (s.run || 0)],
    g: ['이익 성장률 순', s => (s.gx ? (s.gx.k === 'turnaround' ? 99 : s.gx.g) : null)],
    flow: ['외국인+기관 5일 순', s => (s.f5 == null && s.o5 == null ? null : (s.f5 || 0) + (s.o5 || 0))],
  };
  const DEFAULTS = { date: '', sort: 'ch', market: 'all', cap: 'all', q: '', growth: '' };

  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => (typing ? renderBody() : render()));
  const st = pg.state;
  let data = null;

  function filtered(list) {
    const q = st.q.trim().toLowerCase();
    const cap = CAPS[st.cap];
    const key = SORTS[st.sort][1];
    return list.filter(s => {
      if (st.market !== 'all' && s.mk !== st.market) return false;
      if (cap && (s.mc < cap[0] || s.mc >= cap[1])) return false;
      if (st.growth && !(s.gx && (s.gx.k === 'turnaround' || s.gx.g > 0))) return false;
      if (q && !s.n.toLowerCase().includes(q) && !s.c.includes(q)) return false;
      return true;
    }).sort((a, b) => {
      const x = key(a), y = key(b);
      if (x == null) return y == null ? 0 : 1;
      if (y == null) return -1;
      return y - x;
    });
  }

  function renderFilters() {
    $('view').innerHTML = '';
    $('filters').innerHTML = `
      <div class="frow">
        ${pg.seg('sort', Object.entries(SORTS).map(([k, [l]]) => [k, l]))}
      </div>
      <div class="frow">
        ${pg.seg('market', [['all', '전체'], ['KOSPI', '코스피'], ['KOSDAQ', '코스닥']])}
        ${pg.seg('cap', [['all', '시총 전체'], ['L', '1조 이상'], ['M', '3천억~1조'], ['S', '3천억 미만']])}
        <input type="search" data-q="q" placeholder="종목명·코드 검색" value="${U.esc(st.q)}" autocomplete="off">
        ${pg.chk('growth', '이익 성장만', '내년 영업이익 증가 또는 흑자전환 추정 종목')}
      </div>`;
  }

  function renderSummary() {
    const t = data.today;
    const by = m => t.filter(s => s.mk === m).length;
    const grow = t.filter(s => s.gx && (s.gx.k === 'turnaround' || s.gx.g > 0)).length;
    const sectors = {};
    for (const s of t) if (s.w) sectors[s.w] = (sectors[s.w] || 0) + 1;
    const topSec = Object.entries(sectors).sort((a, b) => b[1] - a[1]).slice(0, 8);
    // 장중(15:40 전)에 받은 목록이면 그 시각을 붙인다. 저녁·다음 날 아침 실행이 마감 목록으로 덮어쓴다.
    const intraday = data.at && data.at.slice(0, 10) === data.date && data.at.slice(11, 16) < '15:40';
    $('summary-head').innerHTML = `<h2>${U.dateLabel(data.date)} 52주 신고가 <span class="muted small">${t.length}종목${intraday ? ` · 장중 ${data.at.slice(11, 16)} 기준` : ''}</span></h2>
      <span class="muted small">기록 ${data.days}거래일 (${data.from ? U.dateLabel(data.from) : '–'}부터)</span>`;
    $('summary').innerHTML = `
      <p class="sub">코스피 <b>${by('KOSPI')}</b> · 코스닥 <b>${by('KOSDAQ')}</b>종목. 그중 내년 영업이익 증가(흑자전환 포함) 추정 종목 <b>${grow}</b>개.</p>
      ${topSec.length ? `<div class="tgt-top">${topSec.map(([w, n]) => `<span class="chip">${U.esc(w)} <b>${n}</b></span>`).join('')}</div>` : ''}
      <p class="note">네이버 증권 '52주 신고가' 목록을 매일 저장해 쌓습니다. 신고가 횟수·연속 일수는 저장을 시작한 뒤의 기록만 셉니다.</p>`;
  }

  function rowHtml(s, rank, recent) {
    const gx = s.gx;
    const sinceHigh = recent && s.p && s.hp ? s.p / s.hp - 1 : null;
    return `<article class="row" ${Stock.hintAttr(s)}>
      <span class="rank">${rank}</span>
      <div class="r-main">
        <div class="r-top">
          <div class="r-name">${Stock.link(s)}${s.w ? `<span class="tag">${U.esc(s.w)}</span>` : ''}<span class="muted">${U.eok(s.mc)}</span>
            ${s.run >= 2 ? `<span class="badge">${s.run}일 연속</span>` : ''}</div>
          <div class="r-growth">${recent
            ? `<small>신고가 뒤</small><b class="${U.cls(sinceHigh)}">${U.pct(sinceHigh)}</b>`
            : `<small>${U.price(s.p)}</small><b class="${U.cls(s.ch)}">${s.ch > 0 ? '+' : ''}${s.ch?.toFixed(2) ?? '–'}%</b>`}</div>
        </div>
        <div class="r-line">${recent ? `마지막 신고가 ${U.dateLabel(s.last)} (종가 ${U.price(s.hp)}) → 현재 ${U.price(s.p)}, ` : ''}최근 ${data.days}거래일 중 <b>${s.n20}회</b> 신고가${s.first && s.n20 > 1 ? ` (첫 ${U.md(s.first)})` : ''}</div>
        <div class="r-sub">
          ${gx ? `<span>내년 영업이익 <b class="${gx.k === 'turnaround' ? 'up' : U.cls(gx.g)}">${gx.k === 'turnaround' ? '흑자전환' : gx.k === 'loss' ? '적자' : U.pct(gx.g)}</b></span>
            <span>POR <b>${U.mult(gx.por)}</b></span><span>추정치 1개월 <b class="${U.cls(gx.r1)}">${U.pct(gx.r1)}</b></span>` : '<span>컨센서스 없음</span>'}
          ${s.f5 != null ? `<span>외국인 5일 <b class="${U.cls(s.f5)}">${U.eok(s.f5, true)}</b></span><span>기관 5일 <b class="${U.cls(s.o5)}">${U.eok(s.o5, true)}</b></span>` : ''}
        </div>
      </div>
    </article>`;
  }

  function renderCols(prefix, list, recent) {
    for (const [m, label] of Object.entries(MARKETS)) {
      const items = list.filter(s => s.mk === m);
      const col = $(`${prefix}-${m}`);
      col.hidden = st.market !== 'all' && st.market !== m;
      col.innerHTML = `<div class="col-head"><h3>${label} <span class="muted">${items.length}종목${recent ? ', 마지막 신고가 최신순' : `, ${SORTS[st.sort][0]}`}</span></h3></div>
        ${items.map((s, i) => rowHtml(s, i + 1, recent)).join('') || `<p class="muted empty">${recent ? '해당 종목 없음' : '이날 신고가 종목 없음'}</p>`}`;
    }
  }

  function renderBody() {
    renderSummary();
    renderCols('col', filtered(data.today), false);
    const recent = filtered(data.recent).sort((a, b) => (b.last > a.last ? 1 : b.last < a.last ? -1 : b.n20 - a.n20));
    $('recent-title').innerHTML = `<h2>최근 ${data.days}거래일 신고가</h2><span class="muted small">이날은 신고가가 아니었던 종목 ${recent.length}개 · 오른쪽 숫자는 마지막 신고가일 종가 대비 현재가</span>`;
    $('recent-title').hidden = $('recent-cols').hidden = !data.recent.length;
    renderCols('rc', recent, true);
  }

  function renderFoot() {
    $('foot').innerHTML = `
      <p>신고가: 네이버 증권 52주 신고가 목록(${U.dateLabel(data.date)}), 보통주만. 등락률·주가는 KRX 종가 기준 (KRX가 자료를 여는 다음 날 아침 전까지는 네이버 시세로 임시 표시).</p>
      <p>이익 성장: FnGuide 컨센서스(네이버 종목분석). 수급: 네이버 증권 투자자별 매매동향, 금액은 수량 × 종가 어림.</p>
      <p>투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
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
      data = await U.json(`data/high/${d}.json`);
    } catch (e) {
      return showError(`${d} 데이터를 불러오지 못했습니다. (${e.message})`);
    }
    $('msg').hidden = true;
    render();
  }

  pg.bind($('filters'));
  U.initTheme($('theme'));
  try { $('summary-box').open = (localStorage.getItem('hiSummaryOpen') ?? '1') === '1'; } catch (e) {}
  $('summary-box').addEventListener('toggle', () => { try { localStorage.setItem('hiSummaryOpen', $('summary-box').open ? '1' : ''); } catch (e) {} });

  (async () => {
    try {
      await U.dates('high', pg, $('date'), load);
    } catch (e) {
      return showError('데이터 목록을 불러오지 못했습니다.');
    }
    load(st.date);
  })();
})();
