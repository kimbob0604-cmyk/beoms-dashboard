// 신고가 탭: data/high/{거래일}.json (build_newhigh.py) — 가격 이력으로 직접 계산한 역사적·52주·120일·60일 신고가
// - 종가 기준, 시총 1,000억 이상 보통주. 종목은 가장 높은 축 하나에만 들어간다 (역사적 > 52주 > 120일 > 60일)
// - 장중·장 마감 직후에는 그때 시세를 종가로 본 잠정 판정(prov)이다. 다음 날 아침 KRX 확정 종가로 다시 계산된다
// - 수급(외국인·기관 순매수)은 그날 값이 올라와 있으면 당일, 아니면 최근 5일 합
(() => {
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  const AXES = [
    ['hist', '역사적 신고가', '🏔', '보유 이력 전체(2010년 이후 또는 상장 이후)의 최고 종가를 넘었다'],
    ['w52', '52주 신고가', '📈', '최근 52주(달력 364일) 최고 종가를 넘었다'],
    ['d120', '120일 신고가', '📊', '직전 120거래일 최고 종가를 넘었다'],
    ['d60', '60일 신고가', '📌', '직전 60거래일 최고 종가를 넘었다'],
  ];
  const SORTS = {
    mc: ['시총 순', s => s.mc],
    ch: ['등락률 순', s => s.ch],
    tv: ['거래대금 순', s => s.tv],
    n20: ['신고가 횟수 순', s => (s.n20 || 0) * 1000 + (s.run || 0)],
    g: ['이익 성장률 순', s => (s.gx ? (s.gx.k === 'turnaround' ? 99 : s.gx.g) : null)],
    flow: ['외국인+기관 순', s => { const [f, o] = fo(s); return f == null && o == null ? null : (f || 0) + (o || 0); }],
  };
  const DEFAULTS = { date: '', sort: 'mc', market: 'all', cap: 'all', q: '', growth: '', fresh: '' };

  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => (typing ? renderBody() : render()));
  const st = pg.state;
  let data = null;

  // 그날 수급이 있으면 당일, 없으면 5일 합
  const today1 = () => data.flow_date === data.date;
  const fo = s => (today1() && s.f1 != null ? [s.f1, s.o1] : [s.f5, s.o5]);

  function filtered(list) {
    const q = st.q.trim().toLowerCase();
    const cap = CAPS[st.cap];
    const key = SORTS[st.sort][1];
    return list.filter(s => {
      if (st.market !== 'all' && s.mk !== st.market) return false;
      if (cap && (s.mc < cap[0] || s.mc >= cap[1])) return false;
      if (st.growth && !(s.gx && (s.gx.k === 'turnaround' || s.gx.g > 0))) return false;
      if (st.fresh && !s.new) return false;
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
        ${pg.chk('fresh', '오늘 새로 낸 종목만', '전 거래일에는 신고가가 아니었던 종목')}
      </div>`;
  }

  function renderSummary() {
    const t = data.today;
    const n = ax => t.filter(s => s.ax === ax).length;
    const sectors = {};
    for (const s of t) if (s.w) sectors[s.w] = (sectors[s.w] || 0) + 1;
    const topSec = Object.entries(sectors).sort((a, b) => b[1] - a[1]).slice(0, 8);
    const intraday = data.prov && data.at && data.at.slice(0, 10) === data.date;
    $('summary-head').innerHTML = `<h2>${U.dateLabel(data.date)} 신고가 <span class="muted small">${t.length}종목${data.prov ? ` · 잠정${intraday ? ` (${data.at.slice(11, 16)} 시세)` : ''}` : ''}</span></h2>
      <span class="muted small">시총 ${data.min_mc.toLocaleString('ko-KR')}억 이상 ${data.universe.toLocaleString('ko-KR')}종목 대상 · 종가 기준</span>`;
    $('summary').innerHTML = `
      <div class="nh-counts">${AXES.map(([ax, label, icon, tip]) => `<a href="#col-${ax}" class="nh-count" title="${tip}"><small>${icon} ${label}</small><b>${n(ax)}</b></a>`).join('')}</div>
      ${topSec.length ? `<div class="tgt-top">${topSec.map(([w, k]) => `<span class="chip">${U.esc(w)} <b>${k}</b></span>`).join('')}</div>` : ''}
      <div class="nh-chart" id="nh-chart"></div>
      <p class="note">${data.prov ? '지금 시세를 종가로 본 잠정 판정입니다. 다음 날 아침 KRX 확정 종가가 나오면 다시 계산합니다. ' : ''}
        막대 = 52주 이상(역사적 + 52주) 신고가 종목 수, 선 = 60일 이상 전체. 날짜별 종목 수는 지금 시총 기준 대상으로 다시 센 값입니다.</p>`;
    drawCounts();
  }

  function drawCounts() {
    const cs = data.counts.filter(c => c.slice(1).some(v => v > 0) || true);
    const d = cs.map(c => +c[0].replace(/-/g, ''));
    const top = cs.map(c => c[1] + c[2]), all = cs.map(c => c[1] + c[2] + c[3] + c[4]);
    Plot.chart($('nh-chart'), {
      n: cs.length, height: 150, uid: 'nhc',
      panes: [{ h: 1, fmt: v => `${Math.round(v)}`, series: [
        { type: 'bar', values: top, cls: () => 'up' },
        { type: 'line', values: all, color: 'var(--muted)', width: 1.3 }] }],
      xTicks: Plot.monthTicks(d),
      tip: i => `<div class="tt-h">${Plot.dateStr(d[i])}</div>
        <div class="tt-g"><span>역사적</span><b>${cs[i][1]}</b><span>52주</span><b>${cs[i][2]}</b><span>120일</span><b>${cs[i][3]}</b><span>60일</span><b>${cs[i][4]}</b></div>`,
    });
  }

  const pct = v => (v == null ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`);

  function flowHtml(s) {
    const [f, o] = fo(s);
    if (f == null && o == null) return '<span class="muted">수급 없음</span>';
    const lbl = today1() && s.f1 != null ? '' : '5일 ';
    return `외국인 ${lbl}<b class="${U.cls(f)}">${U.eok(f, true)}</b> · 기관 ${lbl}<b class="${U.cls(o)}">${U.eok(o, true)}</b>`;
  }

  function rowHtml(s, rank, recent) {
    const gx = s.gx;
    return `<article class="row" ${Stock.hintAttr(s)}>
      <span class="rank">${rank}</span>
      <div class="r-main">
        <div class="r-top">
          <div class="r-name">${Stock.link(s)}${s.w ? `<span class="tag">${U.esc(s.w)}</span>` : ''}
            ${!recent && s.new ? '<span class="badge nh-new">신규</span>' : ''}${s.run >= 2 ? `<span class="badge">${s.run}일 연속</span>` : ''}</div>
          <div class="r-growth">${recent
            ? `<small>신고가 뒤</small><b class="${U.cls(s.since)}">${U.pct(s.since)}</b>`
            : `<small>시총 ${U.eok(s.mc)}</small><b class="${U.cls(s.ch)}">${pct(s.ch)}</b>`}</div>
        </div>
        <div class="r-line">${recent
          ? `마지막 ${AXES.find(a => a[0] === s.ax)[1]} ${U.dateLabel(s.last)} · 시총 ${U.eok(s.mc / (1 + s.since))} → 지금 ${U.eok(s.mc)} · 오늘 <span class="${U.cls(s.ch)}">${pct(s.ch)}</span>`
          : `${flowHtml(s)}${s.tv ? ` · 거래대금 ${U.eok(s.tv)}` : ''}`}</div>
        <div class="r-sub">
          ${gx ? `<span>내년 영업이익 <b class="${gx.k === 'turnaround' ? 'up' : U.cls(gx.g)}">${gx.k === 'turnaround' ? '흑자전환' : gx.k === 'loss' ? '적자' : U.pct(gx.g)}</b></span>
            <span>POR <b>${U.mult(gx.por)}</b></span><span>추정치 1개월 <b class="${U.cls(gx.r1)}">${U.pct(gx.r1)}</b></span>` : '<span>컨센서스 없음</span>'}
          ${s.n20 > 1 ? `<span>최근 ${data.days}거래일 중 <b>${s.n20}회</b></span>` : ''}
          ${recent ? `<span>${flowHtml(s)}</span>` : ''}
        </div>
      </div>
    </article>`;
  }

  function renderBody() {
    renderSummary();
    const list = filtered(data.today);
    for (const [ax, label, icon, tip] of AXES) {
      const items = list.filter(s => s.ax === ax);
      $(`col-${ax}`).innerHTML = `<div class="col-head"><h3>${icon} ${label} <span class="muted">${items.length}종목 · ${SORTS[st.sort][0]}</span></h3><span class="muted small">${tip}</span></div>
        ${items.map((s, i) => rowHtml(s, i + 1, false)).join('') || '<p class="muted empty">해당 종목 없음</p>'}`;
    }
    const recent = filtered(data.recent).sort((a, b) => (b.last > a.last ? 1 : b.last < a.last ? -1 : b.mc - a.mc));
    $('recent-title').innerHTML = `<h2>최근 ${data.days}거래일 안에 52주 이상 신고가</h2><span class="muted small">오늘은 52주 신고가가 아닌 종목 ${recent.length}개 · 오른쪽 숫자는 마지막 신고가일 종가 대비 지금</span>`;
    $('recent-title').hidden = $('recent-cols').hidden = !data.recent.length;
    $('rc').innerHTML = recent.map((s, i) => rowHtml(s, i + 1, true)).join('') || '<p class="muted empty">해당 종목 없음</p>';
  }

  function renderFoot() {
    $('foot').innerHTML = `
      <p><b>판정 규칙</b> · 종가 기준, 당일 종가가 창의 최고 종가보다 높아야 신고가입니다(같으면 아님). 역사적 = 보유 이력 전체(${data.hist_from} 이후 또는 상장 이후, 상장 60거래일 미만은 제외),
        52주 = 달력 364일, 120일·60일 = 시장 거래일. 권리락·분할은 KRX 등락률로 이어 붙인 수정주가로 비교합니다. 종목은 가장 높은 축 하나에만 넣습니다.</p>
      <p>대상: 보통주, 회사 시총(우선주 포함) ${data.min_mc.toLocaleString('ko-KR')}억 이상. 가격: KRX 종가 — 다음 날 아침 KRX 공개 전까지는 네이버 시세(장중 10분마다, 저녁에는 정규장 종가)로 잠정 계산합니다.</p>
      <p>이익 성장: FnGuide 컨센서스(네이버 종목분석). 수급: 네이버 증권 투자자별 매매동향${data.flow_date ? ` (${U.dateLabel(data.flow_date)}까지)` : ''}, 금액은 수량 × 종가 어림. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
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
