// 홈 탭: data/home.json — 지수·업종·시총 상위와 각 탭의 오늘 핵심만 모아 보여준다
// 지수 차트만 네이버 이미지를 직접 불러와 장중 30초마다 갱신하고, 나머지는 맥에서 하루 세 번 빌드한 값이다.
(() => {
  const REFRESH_MS = 30000;
  const CHARTS = { day: '당일', candle: '일봉' };
  // 네이버 당일 지수 차트의 순매수 선 색 (지수 선은 초록)
  const LEGEND = [['개인', '#9b6bd3'], ['외국인', '#f08a24'], ['기관', '#3d8bdb']];
  const SECTOR_NOTE = '5종목 이상 업종, 오른쪽은 업종 시총 상위 3종목';

  const $ = id => document.getElementById(id);
  const chart = { KOSPI: 'day', KOSDAQ: 'day' };
  let data = null;

  const chg = ch => (ch == null ? '–' : `${ch > 0 ? '+' : ''}${ch.toFixed(2)}%`);
  const chgHtml = ch => `<span class="${U.cls(ch)}">${chg(ch)}</span>`;
  const hm = ts => ts.slice(11, 16);
  const idxNum = v => (v == null ? '–' : v.toLocaleString('ko-KR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

  function chartSrc(c) {
    const t = Math.floor(Date.now() / 10000);
    return chart[c] === 'day'
      ? `https://ssl.pstatic.net/imgfinance/chart/sise/siseMain${c}.png?t=${t}`
      : `https://ssl.pstatic.net/imgfinance/chart/mobile/candle/day/${c}_end.png?t=${t}`;
  }

  // ---------- 지수 ----------
  function idxHtml(x) {
    // 장중에 받은 값이면 그 시각, 마감 뒤 받은 값이면 종가
    const intraday = x.at && x.at.slice(0, 10) === x.d && hm(x.at) < '15:40';
    const b = x.up != null ? { up: x.up, dn: x.dn, fl: x.fl } : data.breadth[x.c];
    const total = b.up + b.dn + b.fl || 1;
    const flows = [['개인', x.i], ['외국인', x.f], ['기관', x.o], ['프로그램', x.pg]];
    return `<article class="card hm-ix" data-ix="${x.c}">
      <header class="hm-ix-head">
        <div><h2>${x.n}</h2><span class="muted small">${U.dateLabel(x.d)} ${intraday ? `장중 ${hm(x.at)} 기준` : '종가'}</span></div>
        <div class="hm-ix-val"><b>${idxNum(x.v)}</b>${chgHtml(x.ch)}</div>
      </header>
      <div class="hm-ix-bar">
        <div class="seg" role="group">${Object.entries(CHARTS).map(([k, l]) =>
          `<button data-chart="${k}" class="${chart[x.c] === k ? 'on' : ''}">${l}</button>`).join('')}</div>
        <span class="muted small hm-legend">${chart[x.c] === 'day'
          ? `지수 <i style="--c:#3fae2a"></i> 순매수 ${LEGEND.map(([n, c]) => `${n} <i style="--c:${c}"></i>`).join(' ')}`
          : '5·20·60일 이동평균'}</span>
      </div>
      <img class="hm-ix-chart" src="${chartSrc(x.c)}" alt="${x.n} 차트">
      <p class="muted small hm-ix-time"></p>
      ${x.f != null ? `<div class="hm-ix-flow">${flows.map(([n, v]) =>
        `<div><span>${n}</span><b class="${U.cls(v)}">${U.eok(v, true)}</b></div>`).join('')}</div>
        <p class="muted small">${x.fd !== x.d ? `${U.dateLabel(x.fd)} ` : ''}투자자별 순매수${x.at ? ` · ${hm(x.at)} 집계` : ''}</p>` : ''}
      <div class="hm-breadth">
        <div class="hm-bd-bar"><i class="up-bg" style="flex:${b.up}"></i><i class="flat-bg" style="flex:${b.fl}"></i><i class="dn-bg" style="flex:${b.dn}"></i></div>
        <div class="small"><span class="up">상승 ${b.up}</span> · 보합 ${b.fl} · <span class="down">하락 ${b.dn}</span>
          <span class="muted">(${Math.round(b.up / total * 100)}% 상승)</span></div>
      </div>
    </article>`;
  }

  function stampCharts() {
    const t = new Date();
    const txt = `차트 ${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')} 불러옴${U.marketHours() ? ' · 장중 30초마다 갱신' : ''}`;
    document.querySelectorAll('.hm-ix-time').forEach(p => { p.textContent = txt; });
  }

  function refreshCharts() {
    document.querySelectorAll('.hm-ix').forEach(card => { card.querySelector('.hm-ix-chart').src = chartSrc(card.dataset.ix); });
    stampCharts();
  }

  function renderIdx() {
    $('idx').innerHTML = data.idx.map(idxHtml).join('');
    stampCharts();
  }

  $('idx').addEventListener('click', e => {
    const b = e.target.closest('[data-chart]');
    if (!b) return;
    chart[b.closest('.hm-ix').dataset.ix] = b.dataset.chart;
    renderIdx();
  });

  // ---------- 업종 ----------
  function secRow(s) {
    return `<div class="hm-sec-row">
      <span class="hm-sec-name">${U.esc(s.w)} <small class="muted">${s.k}</small></span>
      <b class="${U.cls(s.ch)}">${chg(s.ch)}</b>
      <span class="hm-sec-top small">${s.top.map(t => `<span ${Stock.hintAttr(t)}>${Stock.link(t)} ${chgHtml(t.ch)}</span>`).join('')}</span>
    </div>`;
  }

  function renderSectors() {
    const s = data.sectors;
    $('sectors').innerHTML = `<div class="hm-head"><h2>업종 등락 <span class="muted small">${U.dateLabel(data.date)} · WICS 업종 시총 가중 · ${SECTOR_NOTE}</span></h2></div>
      <div class="hm-two">
        <div><h3 class="hm-sub up">강세 업종</h3>${s.up.map(secRow).join('')}</div>
        <div><h3 class="hm-sub down">약세 업종</h3>${s.dn.map(secRow).join('')}</div>
      </div>`;
  }

  // ---------- 카드 ----------
  function item(s, right, sub = '') {
    return `<li ${Stock.hintAttr(s)}>
      <div class="hm-it-main">${Stock.link(s)}${sub ? `<small class="muted">${sub}</small>` : ''}</div>
      <div class="hm-it-right">${right}</div>
    </li>`;
  }
  const list = (rows, empty = '해당 종목 없음') => (rows && rows.length ? `<ul class="hm-list">${rows.join('')}</ul>` : `<p class="muted small hm-empty">${empty}</p>`);

  function card(title, meta, href, body, wide = false) {
    return `<article class="card hm-card${wide ? ' wide' : ''}">
      <div class="hm-head"><h2>${title} <span class="muted small">${meta}</span></h2>${href ? `<a class="hm-more small" href="${href}">더 보기 →</a>` : ''}</div>
      ${body}
    </article>`;
  }

  const two = (a, b) => `<div class="hm-two">${a}${b}</div>`;
  const half = (label, cls, body) => `<div><h3 class="hm-sub ${cls}">${label}</h3>${body}</div>`;

  function bigCard() {
    return card('시총 상위', U.dateLabel(data.date), 'growth.html',
      list(data.big.map(s => item(s, `<span class="muted">${U.price(s.p)}</span> ${chgHtml(s.ch)}`, U.eok(s.mc)))));
  }

  function moversCard() {
    const m = data.movers;
    return card('급등·급락', '시총 3,000억 이상', null, two(
      half('상승률 상위', 'up', list(m.up.map(s => item(s, chgHtml(s.ch), s.w ? U.esc(s.w) : '')))),
      half('하락률 상위', 'down', list(m.dn.map(s => item(s, chgHtml(s.ch), s.w ? U.esc(s.w) : ''))))));
  }

  function revCard() {
    const r = data.rev;
    if (!r) return '';
    const fy = `FY${String(r.fy).slice(2)}`;
    const row = s => item(s, `<b class="${U.cls(s.r)}">${U.pct(s.r)}</b>`, `${fy} 영업이익 ${U.eok(s.now)}`);
    return card('추정치 리비전', `${fy} 영업이익 1주 변화 · 상향 ${r.nup} / 하향 ${r.ndn}종목`, 'revision.html?per=w1',
      two(half('상향', 'up', list(r.up.map(row))), half('하향', 'down', list(r.dn.map(row)))));
  }

  function tgtCard() {
    const t = data.tgt;
    if (!t) return '';
    const row = s => item(s, `<b class="${U.cls(s.r)}">${U.pct(s.r, 0)}</b>`,
      `${U.esc(s.b)} ${U.price(s.pg)} → ${U.price(s.g)}`);
    return card('목표가 변경', `최근 1주 리포트 ${t.n}건 · 상향 ${t.nup} / 하향 ${t.ndn}건`, 'revision.html?view=tgt',
      two(half('상향', 'up', list(t.up.map(row))), half('하향', 'down', list(t.dn.map(row)))));
  }

  function flowCard() {
    const f = data.flow;
    if (!f) return '';
    const row = s => item(s, `<b class="${U.cls(s.f + s.o)}">${U.eok(s.f + s.o, true)}</b>`,
      `외 ${U.eok(s.f, true)} · 기 ${U.eok(s.o, true)}`);
    return card('외국인+기관 수급', `${U.dateLabel(f.d)} 하루`, 'flow.html?who=fo&days=1',
      two(half('순매수', 'up', list(f.buy.map(row))), half('순매도', 'down', list(f.sell.map(row)))));
  }

  function highCard() {
    const h = data.high;
    if (!h) return '';
    const intraday = h.at && h.at.slice(0, 10) === h.d && hm(h.at) < '15:40';
    return card('52주 신고가', `${U.dateLabel(h.d)} ${h.n}종목${intraday ? ` · 장중 ${hm(h.at)}` : ''}`, 'high.html',
      list(h.list.map(s => item(s, chgHtml(s.ch), [s.w && U.esc(s.w), U.eok(s.mc), s.run >= 2 ? `${s.run}일 연속` : ''].filter(Boolean).join(' · '))),
        '이날 신고가 종목 없음'));
  }

  function reportsCard() {
    if (!data.reports) return '';
    const rows = data.reports.map(r => `<li ${Stock.hintAttr(r)}>
      <div class="hm-it-main"><span class="muted small">${U.md(r.d)} ${U.esc(r.b)}</span>${Stock.link(r)}
        <a class="hm-rep-t small" href="https://m.stock.naver.com/research/company/${r.id}" target="_blank" rel="noopener">${U.esc(r.t)}</a></div>
      <div class="hm-it-right small">${r.op ? U.esc(r.op) : ''}${r.g ? ` ${U.price(r.g)}` : ''}${r.g && r.pg && r.g !== r.pg
        ? ` <span class="${U.cls(r.g - r.pg)}">${r.g > r.pg ? '▲' : '▼'}</span>` : ''}</div>
    </li>`);
    return card('최신 리포트', '네이버 증권 종목분석', 'revision.html?view=tgt&tdays=1', `<ul class="hm-list">${rows.join('')}</ul>`, true);
  }

  function renderGrid() {
    $('grid').innerHTML = [bigCard(), moversCard(), revCard(), tgtCard(), flowCard(), highCard(), reportsCard()].join('');
  }

  function renderFoot() {
    $('foot').innerHTML = `
      <p>지수·투자자별 순매수·상승/하락 종목 수: 네이버 증권 (지수 차트는 네이버 이미지 실시간, 숫자는 ${U.timeLabel(data.built)} 빌드 시점).</p>
      <p>종목 시세: KRX 종가 (다음 날 아침 KRX 공개 전까지는 네이버 시세로 임시 표시). 업종: WICS. 추정치: FnGuide 컨센서스(네이버 종목분석, 컨센 ${U.dateLabel(data.rev?.cns || data.date)}).</p>
      <p>목표가·리포트: 네이버 증권 리서치(증권사 제공). 수급 금액은 순매수 수량 × 종가 어림. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  }

  async function load() {
    try {
      data = await U.json('data/home.json');
    } catch (e) {
      $('msg').textContent = `데이터를 불러오지 못했습니다. (${e.message})`;
      return;
    }
    $('msg').hidden = true;
    $('asof').textContent = `${U.dateLabel(data.date)} 종가 기준 · ${U.timeLabel(data.built)} 갱신`;
    renderIdx();
    renderSectors();
    renderGrid();
    renderFoot();
  }

  U.initTheme($('theme'));
  setInterval(() => { if (!document.hidden && U.marketHours()) refreshCharts(); }, REFRESH_MS);
  load();
})();
