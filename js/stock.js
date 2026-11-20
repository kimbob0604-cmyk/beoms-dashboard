// 종목 상세 패널: 종목 이름을 누르면 오른쪽에서 열린다 (모든 탭 공통)
// - 차트: data/chart/{code}.json 일봉(최근 1년)을 직접 그려 마우스를 올린 날의 시가·고가·저가·종가·거래량을 보여준다
// - 리포트·키워드·목표가·수급: data/stocks/{code}.json (맥에서 매일 빌드)
// - 가격: 위 둘은 하루 한 번 빌드라 전날 종가에 머문다. 장중엔 data/quotes.json(10분마다 갱신)이 더 새로우면
//   그 값으로 헤더 가격·등락률·시총을 바꾸고 차트 끝에 임시 봉(종가만)을 붙인다
// - 시총 기준: 헤더·차트 축·52주 범위·목표가·수급 표를 주가가 아니라 시총으로 보여 준다. 과거 값은 '지금 주식 수'로
//   환산한 값(주가 × 지금 시총 ÷ 지금 주가)이라, 그 사이 증자·감자가 있었다면 당시 실제 시총과 다르다. 주가는 작은 글씨로 남긴다
// - POR: 시총 ÷ 영업이익을 전년 실적~내후년 추정까지 표로 (U.porTable). 평균 목표 시총 기준 POR 도 함께
// 이름 링크는 네이버 증권 주소라서 Ctrl/⌘+클릭하면 네이버가 새 탭으로 열린다.
const Stock = (() => {
  const CHARTS = [['3m', '3개월'], ['6m', '6개월'], ['1y', '1년'], ['w', '주봉']];
  const DAYS = { '3m': 63, '6m': 126, '1y': 260 };
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  let panel, code = null, hint = {}, chart = '6m', kwOpen = null, cdata = null, filings = null;
  let live = null;   // 이 종목의 최신 시세 {d: 20261110, p, ch, t: 장중 받은 시각 | null}
  let capK = null;   // 주가 1원당 시총(억) = 지금 시총 ÷ 지금 주가. 없으면(시총 모름) 주가로 보여 준다
  const cap = v => (v == null ? '–' : capK ? U.eok(v * capK) : num(v));   // 주가 → 시총 글자
  const capTitle = v => (capK && v != null ? ` title="주가 ${num(v)}원"` : '');

  // ---------- 관심종목 (이 브라우저에만 저장) ----------
  const WKEY = 'watch';
  const watchList = () => { try { return JSON.parse(localStorage.getItem(WKEY)) || []; } catch (e) { return []; } };
  const isWatched = c => watchList().some(w => w.c === c);
  function toggleWatch(s) {
    let ws = watchList();
    ws = ws.some(w => w.c === s.c) ? ws.filter(w => w.c !== s.c) : [...ws, { c: s.c, n: s.n, mk: s.mk }];
    try { localStorage.setItem(WKEY, JSON.stringify(ws)); } catch (e) { /* 저장 안 되는 브라우저 */ }
    document.dispatchEvent(new CustomEvent('watchchange'));
    return ws.some(w => w.c === s.c);
  }

  const naverUrl = c => `https://finance.naver.com/item/main.naver?code=${c}`;
  const researchUrl = id => `https://m.stock.naver.com/research/company/${id}`;

  function link(s) {
    return `<a href="${naverUrl(s.c)}" target="_blank" rel="noopener" data-code="${s.c}">${U.esc(s.n)}</a>`;
  }

  function ensurePanel() {
    if (panel) return;
    panel = document.createElement('aside');
    panel.id = 'stock';
    panel.className = 'drawer';
    panel.hidden = true;
    panel.setAttribute('aria-label', '종목 상세');
    document.body.append(panel);
    const scrim = document.createElement('div');
    scrim.className = 'scrim';
    scrim.hidden = true;
    scrim.addEventListener('click', close);
    document.body.append(scrim);
    panel.addEventListener('click', onPanelClick);
  }

  const num = v => (v == null ? '–' : Math.round(v).toLocaleString('ko-KR'));
  const vol = v => (v == null ? '–' : v >= 1e8 ? `${(v / 1e8).toFixed(1)}억주` : v >= 1e4 ? `${Math.round(v / 1e4).toLocaleString('ko-KR')}만주` : `${v}주`);

  function drawChart() {
    const el = panel.querySelector('.st-plot');
    if (!el) return;
    if (!cdata?.d?.length) {
      el.innerHTML = `<p class="muted st-loading">${cdata === undefined ? '차트 불러오는 중…' : '차트 데이터 없음'}</p>`;
      return;
    }
    const day = withLive(cdata);
    const all = chart === 'w' ? Plot.weekly(day) : day;
    const from = chart === 'w' ? 0 : Math.max(0, all.d.length - DAYS[chart]);
    const cut = k => all[k].slice(from);
    const d = cut('d'), c = cut('c'), o = cut('o'), h = cut('h'), l = cut('l'), v = cut('v');
    const mas = chart === 'w' ? [[13, 'var(--ma20)'], [26, 'var(--ma60)']] : [[5, 'var(--muted)'], [20, 'var(--ma20)'], [60, 'var(--ma60)']];
    const prev = i => (from + i > 0 ? all.c[from + i - 1] : null);
    const pch = i => (prev(i) ? (c[i] / prev(i) - 1) * 100 : null);
    // 52주 위치 (최근 250거래일 고가·저가 대비 현재 종가)
    const n52 = Math.max(0, day.d.length - 250);
    const hi = Math.max(...day.h.slice(n52).map((x, i) => x ?? day.c[n52 + i]));
    const lo = Math.min(...day.c.slice(n52).map((x, i) => day.l[n52 + i] ?? x));
    const last = day.c[day.c.length - 1];
    const pos = hi > lo ? (last - lo) / (hi - lo) : 0.5;
    const pos52 = panel.querySelector('.st-52');
    if (pos52) pos52.innerHTML = `<span class="muted">52주${capK ? ' 시총' : ''}</span> 최저 <b${capTitle(lo)}>${cap(lo)}</b>
      <span class="st-52-bar"><i style="left:${(pos * 100).toFixed(1)}%"></i></span> 최고 <b${capTitle(hi)}>${cap(hi)}</b>
      <span class="muted">고점 대비 <b class="${U.cls(last / hi - 1)}">${U.pct(last / hi - 1)}</b> · 저점 대비 <b class="${U.cls(last / lo - 1)}">${U.pct(last / lo - 1)}</b></span>`;
    panel.querySelector('.st-legend').innerHTML = mas.map(([k, col]) => `<i style="--c:${col}"></i>${k}${chart === 'w' ? '주' : '일'}`).join(' ') + ' 이동평균';
    Plot.chart(el, {
      n: d.length, height: 300, uid: 'stc',
      panes: [
        { h: 3.4, fmt: cap, series: [{ type: 'candle', o, h, l, c },
          ...mas.map(([k, col]) => ({ type: 'line', values: Plot.ma(all.c, k).slice(from), color: col, width: 1.1, nodot: true }))] },
        { h: 1, fmt: vol, series: [{ type: 'bar', values: v, cls: i => (pch(i) >= 0 ? 'up' : 'dn') }] },
      ],
      xTicks: Plot.monthTicks(d),
      tip: i => `<div class="tt-h">${Plot.dateStr(d[i])}${chart === 'w' ? ' 주' : ''}</div>
        <div class="tt-v">${cap(c[i])} ${chHtml(pch(i))}</div>
        ${capK ? `<div class="muted">주가 ${num(c[i])}</div>` : ''}
        ${o[i] == null ? `<div class="muted">${liveDay(d[i]) ? `${liveLabel()} 시세 (임시)` : 'KRX 공개 전 임시 종가'}</div>` : `<div class="tt-g"><span>시가</span><b>${cap(o[i])}</b><span>고가</span><b>${cap(h[i])}</b>
          <span>저가</span><b>${cap(l[i])}</b><span>거래량</span><b>${vol(v[i])}</b></div>`}`,
    });
  }

  // 장중 시세가 차트 마지막 날보다 새 날짜면 종가만 있는 임시 봉으로 붙인다 (주봉은 Plot.weekly 가 그 주에 합친다)
  function withLive(x) {
    if (!live || live.d <= x.d[x.d.length - 1]) return x;
    return { ...x, d: [...x.d, live.d], o: [...x.o, null], h: [...x.h, null], l: [...x.l, null], c: [...x.c, live.p], v: [...x.v, null] };
  }
  const liveDay = d => live && d === live.d;
  const liveLabel = () => (live?.t && U.marketHours() ? `장중 ${live.t.slice(11, 16)}` : '종가');

  // data/quotes.json: {_d: 시세 날짜, _t: 장중 받은 시각, 코드: [가격, 등락률]} — 1분 안이면 받은 것을 다시 쓴다
  let quotesP = null, quotesAt = 0;
  function loadQuotes() {
    if (!quotesP || Date.now() - quotesAt > 60000) {
      quotesAt = Date.now();
      quotesP = fetch(U.bust('data/quotes.json'), { cache: 'no-store' }).then(r => (r.ok ? r.json() : null)).catch(() => null);
    }
    return quotesP;
  }

  async function loadLive(c) {
    const q = await loadQuotes();
    const x = q?.[c];
    if (code !== c || !q?._d || x?.[0] == null) return;
    live = { d: +q._d.replace(/-/g, ''), p: x[0], ch: x[1], t: q._t || null };
  }

  async function loadChart(c) {
    cdata = undefined;
    drawChart();
    let x = null;
    try { x = await U.json(`data/chart/${c}.json`); } catch (e) { /* 차트 없는 종목 */ }
    if (code === c) { cdata = x; drawChart(); }
  }

  // ---------- 그리기 ----------
  const chHtml = ch => (ch == null ? '' : `<span class="${U.cls(ch)}">${ch > 0 ? '+' : ''}${ch.toFixed(2)}%</span>`);

  function headHtml(s) {
    return `<header class="st-head">
      <div>
        <h2>${U.esc(s.n || code)} <small class="muted">${code}</small></h2>
        <p class="muted small">${[MARKETS[s.mk], s.w].filter(Boolean).map(U.esc).join(' · ')}</p>
      </div>
      <div class="st-price">${s.mc ? `<small class="muted">시총</small><b>${U.eok(s.mc)}</b>${chHtml(s.ch)}<small class="muted">${s.p != null ? `주가 ${U.price(s.p)} · ` : ''}${s.pl || '종가'}</small>`
        : s.p != null ? `<b>${U.price(s.p)}</b>${chHtml(s.ch)}<small class="muted">${s.pl || '종가'}</small>` : ''}</div>
      <button class="icon-btn st-star${isWatched(code) ? ' on' : ''}" aria-label="관심종목" title="관심종목 (홈에 모아 보기)">${isWatched(code) ? '★' : '☆'}</button>
      <button class="icon-btn st-close" aria-label="닫기" title="닫기 (Esc)">✕</button>
    </header>
    <nav class="st-links small">
      <a href="${naverUrl(code)}" target="_blank" rel="noopener">네이버 증권 ↗</a>
      <a href="https://finance.naver.com/research/company_list.naver?searchType=itemCode&itemCode=${code}" target="_blank" rel="noopener">리포트 전체 ↗</a>
      <a href="https://navercomp.wisereport.co.kr/v2/company/c1050001.aspx?cmp_cd=${code}" target="_blank" rel="noopener">컨센서스 ↗</a>
    </nav>`;
  }

  function chartHtml() {
    return `<section class="st-sec st-chart">
      <div class="st-sec-head">
        <div class="seg" role="group">${CHARTS.map(([k, l]) => `<button data-chart="${k}" class="${k === chart ? 'on' : ''}">${l}</button>`).join('')}</div>
        <span class="muted small st-legend"></span>
      </div>
      <div class="st-plot"></div>
      <p class="small st-52"></p>
      <p class="muted small">${capK ? '차트·52주 범위는 시총 기준 (주가 × 지금 주식 수로 환산, 증자·감자 전 구간은 당시 실제 시총과 다를 수 있음) · ' : ''}일봉: KRX (마지막 날은 KRX 공개 전 네이버 종가, 장중엔 10분마다 받는 장중 시세일 수 있음) · <a href="${naverUrl(code)}" target="_blank" rel="noopener">네이버 실시간 차트 ↗</a></p>
    </section>`;
  }

  // 내년(올해 결산연도 + 1) 영업이익 추정치. POR 계산의 기준
  const nextOp = pv => pv?.ops?.find(x => x[0] === pv.fy0 + 1)?.[1];

  function growthHtml(s) {
    const gx = s.gx, por = U.porTable(s.mc, s.pv);
    if (!gx && !por) return '';
    const g = !gx ? '' : gx.k === 'turnaround' ? '흑자전환' : gx.k === 'loss' ? '적자 지속' : U.pct(gx.g);
    const gc = !gx ? '' : gx.k === 'turnaround' ? 'up' : gx.k === 'loss' ? 'down' : U.cls(gx.g);
    const op1 = nextOp(s.pv);
    const liveP = s.mc && op1 > 0 ? s.mc / op1 : gx?.por;   // 장중이면 지금 시총으로 다시 계산한 값
    return `${por ? `<div class="st-por">${por}</div>` : ''}${gx ? `<div class="st-kpis">
      <div><span>내년 영업이익 성장</span><b class="${gc}">${g}</b>${gx.lb ? '<small class="muted">기저</small>' : ''}</div>
      <div><span>내년 POR <small class="muted">시총 ÷ 내년 영업이익</small></span><b>${U.mult(liveP)}</b></div>
      <div><span>추정치 1개월 변화</span><b class="${U.cls(gx.r1)}">${U.pct(gx.r1)}</b></div>
    </div>` : ''}`;
  }

  // 목표가 → 목표 시총 (지금 주식 수 기준). 시총을 모르면 목표가 그대로
  function targetHtml(d) {
    const t = d.tgt;
    if (!t) return '';
    const upside = d.p ? t.avg / d.p - 1 : null;
    const op1 = nextOp(d.pv);
    const tPor = capK && op1 > 0 ? t.avg * capK / op1 : null;
    const what = capK ? '목표 시총' : '목표가';
    return `<div class="st-kpis">
      <div><span>평균 ${what} <small class="muted">${t.n}개 증권사</small></span><b${capTitle(t.avg)}>${cap(t.avg)}</b>
        ${upside != null ? `<small>지금 시총 대비 <b class="${U.cls(upside)}">${U.pct(upside)}</b></small>` : ''}</div>
      <div><span>${what} 범위</span><b class="st-range">${cap(t.lo)} ~ ${cap(t.hi)}</b>
        ${tPor != null ? `<small>평균 목표 시총이면 내년 POR <b>${U.mult(tPor)}</b></small>` : ''}</div>
      <div><span>90일 목표가 변경</span><b>상향 <span class="up">${t.up}</span> · 하향 <span class="down">${t.dn}</span></b>
        ${capK ? `<small class="muted">평균 목표가 ${U.price(t.avg)}원</small>` : ''}</div>
    </div>`;
  }

  function kwHtml(d) {
    if (!d.kws?.length) return '';
    return `<section class="st-sec">
      <div class="st-sec-head"><h3>키워드로 본 최근 리포트 <small class="muted">${d.reports.length}건 · 여러 리포트가 함께 짚은 말 순</small></h3></div>
      <div class="kw-list">${d.kws.map((k, i) => `
        <div class="kw${kwOpen === i ? ' open' : ''}">
          <button class="kw-name" data-kw="${i}"><b>${U.esc(k.kw)}</b><small class="muted">${k.n}건</small></button>
          <ul>${k.hits.map((h, j) => `<li class="${j ? 'more-hit' : ''}">${mark(h.s, k.kw)}
            <a class="muted small" href="${researchUrl(h.id)}" target="_blank" rel="noopener">${U.esc(h.broker)} ${U.md(h.date)}</a></li>`).join('')}</ul>
          ${k.hits.length > 1 ? `<button class="linkish small kw-more" data-kw="${i}">${kwOpen === i ? '접기' : `문장 ${k.hits.length - 1}개 더`}</button>` : ''}
        </div>`).join('')}
      </div>
    </section>`;
  }

  function mark(s, kw) {
    return U.esc(s).split(U.esc(kw)).join(`<mark>${U.esc(kw)}</mark>`);
  }

  function goalHtml(r) {
    if (!r.g) return '<span class="muted">목표가 없음</span>';
    const lbl = capK ? '<span class="muted">목표 시총</span> ' : '';
    if (!r.pg || r.pg === r.g) return `${lbl}<span${capTitle(r.g)}>${cap(r.g)}</span>${r.pg ? ' <span class="muted">유지</span>' : ''}`;
    const ch = r.g / r.pg - 1;
    return `${lbl}<span class="muted">${cap(r.pg)} →</span> <b${capTitle(r.g)}>${cap(r.g)}</b> <span class="${U.cls(ch)}">${U.pct(ch)}</span>`;
  }

  function reportsHtml(d) {
    if (!d.reports?.length) return `<section class="st-sec"><h3>최근 리포트</h3><p class="muted">최근 90일 리포트 없음</p></section>`;
    return `<section class="st-sec">
      <div class="st-sec-head"><h3>최근 리포트 <small class="muted">최근 90일 ${d.reports.length}건</small></h3></div>
      <ol class="rep-list">${d.reports.map(r => `
        <li>
          <div class="rep-meta small"><span class="muted">${U.md(r.d)}</span> <b>${U.esc(r.b)}</b>${r.op ? ` <span class="pill">${r.op}</span>` : ''}
            <span class="rep-goal">${goalHtml(r)}</span></div>
          <a class="rep-title" href="${researchUrl(r.id)}" target="_blank" rel="noopener">${U.esc(r.t)}</a>
          ${r.h.length ? `<ul class="rep-heads">${r.h.map(h => `<li>${U.esc(h)}</li>`).join('')}</ul>` : ''}
          <div class="rep-foot small">${r.kw.map(k => `<span class="tag">${U.esc(k)}</span>`).join('')}
            ${r.pdf ? `<a class="muted" href="${r.pdf}" target="_blank" rel="noopener">PDF ↗</a>` : ''}</div>
        </li>`).join('')}
      </ol>
    </section>`;
  }

  function flowHtml(d) {
    if (!d.flow?.length) return '';
    const sum = (i, n) => d.flow.slice(0, n).reduce((a, r) => a + (r[i] || 0), 0);
    const max = Math.max(...d.flow.map(r => Math.max(Math.abs(r[1] || 0), Math.abs(r[2] || 0))), 0.1);
    const bar = v => `<i class="${v >= 0 ? 'pos' : 'neg'}" style="width:${Math.abs(v || 0) / max * 50}%"></i>`;
    const fmt = v => `<span class="${U.cls(v)}">${U.eok(v, true)}</span>`;
    return `<section class="st-sec">
      <div class="st-sec-head"><h3>수급 <small class="muted">순매수 금액 (수량 × 종가로 어림)</small></h3></div>
      <div class="st-kpis">
        <div><span>외국인 5일 · 20일</span><b>${fmt(sum(1, 5))} · ${fmt(sum(1, 20))}</b></div>
        <div><span>기관 5일 · 20일</span><b>${fmt(sum(2, 5))} · ${fmt(sum(2, 20))}</b></div>
        <div><span>외국인 지분율</span><b>${d.flow[0][5] != null ? `${d.flow[0][5].toFixed(2)}%` : '–'}</b></div>
      </div>
      <table class="tbl flow-tbl">
        <thead><tr><th>날짜</th><th class="num">${capK ? '시총' : '종가'}</th><th class="num">외국인</th><th class="bar-cell"></th><th class="num">기관</th><th class="bar-cell"></th><th class="num">개인</th></tr></thead>
        <tbody>${d.flow.slice(0, 10).map(r => `<tr>
          <td class="muted">${U.md(r[0])}</td><td class="num"${capTitle(r[4])}>${cap(r[4])}</td>
          <td class="num">${fmt(r[1])}</td><td class="bar-cell"><span class="fbar">${bar(r[1])}</span></td>
          <td class="num">${fmt(r[2])}</td><td class="bar-cell"><span class="fbar">${bar(r[2])}</span></td>
          <td class="num">${fmt(r[3])}</td></tr>`).join('')}</tbody>
      </table>
    </section>`;
  }

  // 기관 세부 (build_naver.detail_table): 한국투자증권 API 실제 순매수 거래대금, 억원 [키, 1일, 5일, 20일, 60일]
  const DET_ROWS = [['f', '외국인'], ['i', '개인'], ['o', '기관 계'], ['sc', '금융투자', 1], ['pn', '연기금 등', 1], ['tr', '투신', 1],
    ['pe', '사모펀드', 1], ['in', '보험', 1], ['bk', '은행', 1], ['ef', '기타금융', 1], ['cp', '기타법인'], ['gv', '국가·지자체']];
  function flowDetailHtml(d) {
    const t = d.fdet?.t;
    if (!t?.length) return '';
    const by = Object.fromEntries(t.map(r => [r[0], r.slice(1)]));
    const fmt = v => (v == null ? '<span class="muted">–</span>' : `<span class="${U.cls(v)}">${U.eok(v, true)}</span>`);
    return `<section class="st-sec">
      <div class="st-sec-head"><h3>투자자 세부 <small class="muted">순매수 거래대금 · ${U.md(d.fdet.d)}까지</small></h3></div>
      <table class="tbl flow-det">
        <thead><tr><th>투자자</th><th class="num">1일</th><th class="num">5일</th><th class="num">20일</th><th class="num">60일</th></tr></thead>
        <tbody>${DET_ROWS.filter(([k]) => by[k] && (k !== 'gv' || by[k].some(v => v))).map(([k, n, sub]) => `<tr class="${sub ? 'sub' : ''}${k === 'o' ? ' tot' : ''}">
          <td>${sub ? '└ ' : ''}${n}</td>${by[k].map(v => `<td class="num">${fmt(v)}</td>`).join('')}</tr>`).join('')}</tbody>
      </table>
      <p class="note">한국투자증권 Open API 종목별 투자자 매매동향(KRX+넥스트레이드)의 실제 체결 대금. 위 표(수량 × 종가 어림)와 조금 다를 수 있습니다.</p>
    </section>`;
  }

  // 최근 90일 DART 주요 공시 (data/dart/s/{code}.json)
  function dartHtml() {
    if (!filings?.length || typeof DartFmt === 'undefined') return '<div class="st-dart-slot"></div>';
    return `<div class="st-dart-slot"><section class="st-sec st-dart">
      <div class="st-sec-head"><h3>최근 공시 <small class="muted">DART 주요 공시 ${filings.length}건</small></h3>
        <a class="linkish" href="https://dart.fss.or.kr/dsab007/main.do?textCrpNm=${encodeURIComponent(hint.n || '')}" target="_blank" rel="noopener">DART 전체 ↗</a></div>
      ${filings.slice(0, 8).map(x => `<article class="dt-item">
        <header><div class="dt-name"><span class="muted small">${U.md(x.date)}</span><b>${DartFmt.KIND_LABEL[x.k] || x.k}</b>
          ${DartFmt.tags(x).map(t => `<span class="dt-tag ${t === '서프' ? 'up' : t === '쇼크' ? 'down' : ''}">${t}</span>`).join('')}</div>
          <a class="muted small" href="${DartFmt.dartUrl(x.no)}" target="_blank" rel="noopener">원문 ↗</a></header>
        <p class="dt-kv">${U.esc(x.d && Object.keys(x.d).length ? DartFmt.body(x).split('\n')[0] : x.t)}</p>
      </article>`).join('')}
    </section></div>`;
  }

  async function loadFilings(c) {
    filings = null;
    let x = null;
    try { x = await U.json(`data/dart/s/${c}.json`); } catch (e) { /* 최근 주요 공시 없음 */ }
    if (code !== c) return;
    filings = x;
    const slot = panel.querySelector('.st-dart-slot');
    if (slot) slot.outerHTML = dartHtml();
  }

  function render(d) {
    const s = { c: code, ...hint, ...(d || {}) };
    if (live) {   // 하루 한 번 빌드한 종가보다 새 시세 (장중이면 10분마다)
      if (s.mc && s.p) s.mc = s.mc * live.p / s.p;
      Object.assign(s, { p: live.p, ch: live.ch, pl: liveLabel() });
    }
    capK = s.mc && s.p ? s.mc / s.p : null;
    panel.innerHTML = `${headHtml(s)}${chartHtml()}
      <div class="st-body">${d === undefined ? '<p class="muted st-loading">리포트·수급 불러오는 중…</p>'
        : `${growthHtml(s)}${targetHtml(s)}<div class="st-fund-slot"></div>${dartHtml()}${kwHtml(s)}${reportsHtml(s)}${flowHtml(s)}${flowDetailHtml(s)}
           <p class="muted small st-note">리포트: 네이버 증권 리서치(증권사 제공) 요약에서 키워드를 뽑았습니다. 원문은 제목·PDF 링크로 보세요.
           목표가 변경은 같은 증권사의 직전 리포트와 비교했습니다. 목표 시총 = 목표가 × 지금 주식 수(우선주 포함 회사 시총 기준 어림).</p>`}</div>`;
    drawChart();
  }

  async function open(c, h = {}) {
    ensurePanel();
    code = c;
    hint = h;
    kwOpen = null;
    panel.hidden = false;
    document.querySelector('.scrim').hidden = false;
    document.body.classList.add('drawer-open');
    if (location.hash !== `#${c}`) history.pushState(null, '', `${location.pathname}${location.search}#${c}`);
    cdata = undefined;
    live = null;
    render(undefined);
    panel.scrollTop = 0;
    loadChart(c);
    loadFilings(c);
    const [d] = await Promise.all([
      U.json(`data/stocks/${c}.json`).catch(() => null),   // 리포트·수급 데이터가 없는 종목은 null
      loadLive(c),
    ]);
    if (code === c) render(d || null);
    loadFund(c);
  }

  // 분기 비용 구조 (data/fund/{code}.json — 쌓아 둔 종목만). fund.js 가 그린다
  async function loadFund(c) {
    if (typeof Fund === 'undefined') return;
    const d = await Fund.load(c);
    const slot = panel.querySelector('.st-fund-slot');
    if (code === c && d && slot) Fund.render(slot, d);
  }

  function close() {
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    document.querySelector('.scrim').hidden = true;
    document.body.classList.remove('drawer-open');
    code = null;
    if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  }

  function onPanelClick(e) {
    if (e.target.closest('.st-close')) return close();
    const star = e.target.closest('.st-star');
    if (star) {
      const on = toggleWatch({ c: code, n: hint.n || panel.querySelector('.st-head h2')?.firstChild?.textContent?.trim(), mk: hint.mk });
      star.classList.toggle('on', on);
      star.textContent = on ? '★' : '☆';
      return;
    }
    const c = e.target.closest('[data-chart]');
    if (c) {
      chart = c.dataset.chart;
      panel.querySelectorAll('[data-chart]').forEach(b => b.classList.toggle('on', b === c));
      return drawChart();
    }
    const k = e.target.closest('[data-kw]');
    if (k) {
      const i = +k.dataset.kw;
      kwOpen = kwOpen === i ? null : i;
      panel.querySelectorAll('.kw').forEach((el, j) => {
        el.classList.toggle('open', j === kwOpen);
        const more = el.querySelector('.kw-more');
        if (more) more.textContent = j === kwOpen ? '접기' : `문장 ${el.querySelectorAll('li').length - 1}개 더`;
      });
    }
  }

  // 페이지 어디서든 data-code 링크를 누르면 패널 (수정키·가운데 버튼은 원래대로 네이버 새 탭)
  document.addEventListener('click', e => {
    const a = e.target.closest('a[data-code]');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    const row = a.closest('[data-hint]');
    open(a.dataset.code, row ? JSON.parse(row.dataset.hint) : { n: a.textContent });
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  window.addEventListener('popstate', () => {
    const c = location.hash.slice(1);
    if (/^[0-9A-Z]{6}$/.test(c)) { if (c !== code) open(c); } else close();
  });
  // 주소에 #종목코드 가 있으면 바로 연다 (공유한 링크)
  window.addEventListener('DOMContentLoaded', () => {
    const c = location.hash.slice(1);
    if (/^[0-9A-Z]{6}$/.test(c)) open(c);
  });

  // ---------- 헤더 검색: 어느 탭에서든 종목 이름·코드·초성으로 찾아 패널을 연다 ('/' 키) ----------
  const CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
  const chosung = s => [...s].map(ch => {
    const k = ch.charCodeAt(0) - 0xac00;
    return k >= 0 && k < 11172 ? CHO[Math.floor(k / 588)] : ch;
  }).join('');
  let names = null, hits = [], sel = 0;

  function search(q) {
    q = q.trim().toLowerCase().replace(/\s+/g, '');
    if (!q || !names) return [];
    const onlyCho = /^[ㄱ-ㅎ]+$/.test(q);
    const out = [];
    for (const r of names) {
      const n = r[1].toLowerCase().replace(/\s+/g, '');
      if (r[0].startsWith(q) || n.includes(q) || (onlyCho && r[3].includes(q))) out.push(r);
      if (out.length >= 8) break;
    }
    return out;
  }

  function mountSearch() {
    const host = document.querySelector('.top-right');
    if (!host || host.querySelector('.gsearch')) return;
    const box = document.createElement('div');
    box.className = 'gsearch';
    box.innerHTML = `<input type="search" placeholder="종목 검색 /" aria-label="종목 검색" autocomplete="off"><ul hidden></ul>`;
    host.prepend(box);
    const inp = box.querySelector('input'), ul = box.querySelector('ul');
    const draw = () => {
      ul.hidden = !hits.length;
      ul.innerHTML = hits.map((r, i) => `<li class="${i === sel ? 'on' : ''}" data-i="${i}"><b>${U.esc(r[1])}</b><small class="muted">${r[0]} · ${MARKETS[r[2]] || ''}</small></li>`).join('');
    };
    const pick = r => {
      if (!r) return;
      inp.value = '';
      hits = [];
      draw();
      inp.blur();
      open(r[0], { n: r[1], mk: r[2] });
    };
    inp.addEventListener('focus', async () => {
      if (names) return;
      try {
        names = (await U.json('data/names.json')).map(r => [...r, chosung(r[1])]);
      } catch (e) { names = []; }
      if (inp.value) { hits = search(inp.value); draw(); }
    });
    inp.addEventListener('input', () => { hits = search(inp.value); sel = 0; draw(); });
    inp.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        sel = (sel + (e.key === 'ArrowDown' ? 1 : hits.length - 1)) % Math.max(hits.length, 1);
        draw();
      } else if (e.key === 'Enter') {
        pick(hits[sel]);
      } else if (e.key === 'Escape') {
        inp.value = ''; hits = []; draw(); inp.blur();
      }
    });
    ul.addEventListener('mousedown', e => {
      const li = e.target.closest('li');
      if (li) { e.preventDefault(); pick(hits[+li.dataset.i]); }
    });
    inp.addEventListener('blur', () => setTimeout(() => { ul.hidden = true; }, 100));
    document.addEventListener('keydown', e => {
      if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); inp.focus(); }
    });
  }
  window.addEventListener('DOMContentLoaded', mountSearch);

  // 행에 붙여 둘 패널 첫 화면용 정보 (이름·시장·시총·가격)
  const hintAttr = s => `data-hint="${U.esc(JSON.stringify({ n: s.n, mk: s.mk, w: s.w, mc: s.mc, p: s.p, ch: s.ch }))}"`;

  return { open, close, link, hintAttr, watchList, toggleWatch };
})();
