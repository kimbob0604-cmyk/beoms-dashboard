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

  // ---------- ETF 편입 (data/etf/{code}.json — build_etf_by_stock.py) ----------
  // 이 종목을 담은 ETF 마다 비중·보유액·등락률·순설정·환매, 그리고 ETF 가 이 종목을 사고판 금액을 두 몫으로:
  //   설정·환매 몫 = ETF 순설정·환매 × 그날 바스켓 비중 (LP·운용사가 바스켓째 사고판 금액)
  //   리밸런싱 몫 = 1 CU 당 수량 변화 × 좌수 × 주가 (설정·환매 없이 바스켓을 바꾼 매매 — 지수 변경·비중 조정·액티브 교체)
  // 기간은 1·5·20일. 마지막 거래일 리밸런싱은 다음 거래일 PDF 가 와야 안다(rb 가 null)
  const ETF_P = [[1, '1일'], [5, '5일'], [20, '20일']];
  const ETF_SHOW = 12;
  let etfData = null, etfP = 1, etfSort = 'held', etfAll = false, etfMc = null;
  const EI = { c: 0, n: 1, wt: 2, held: 3, r: { 1: 4, 5: 5, 20: 6 }, f: { 1: 7, 5: 8, 20: 9 }, asof: 10, stale: 11, base: 12,
    cr: { 1: 13, 5: 14, 20: 15 }, rb: { 1: 16, 5: 17, 20: 18 }, ev: 19 };
  const EV_TXT = { NEW: '편입', DROP: '편출', ADD: '수량↑', CUT: '수량↓' };
  const etfSum = (a, b) => (a == null && b == null ? null : (a || 0) + (b || 0));
  const etfTot = (r, p) => etfSum(r[EI.cr[p]], r[EI.rb[p]]);
  const lastSum = (xs, p) => { const v = xs.slice(-p).filter(x => x != null); return v.length ? v.reduce((a, x) => a + x, 0) : null; };

  function etfEvTag(r) {
    const ev = r[EI.ev];
    if (!ev) return '';
    const [kind, day, q0, q1, wt, eok] = ev;
    const pct = q0 && q1 ? ` ${((q1 / q0 - 1) * 100).toFixed(1)}%` : '';
    const tip = `${U.md(day)} 리밸런싱 · 1 CU 당 ${q0.toLocaleString('ko-KR')} → ${q1.toLocaleString('ko-KR')}주${wt != null ? ` · 비중 ${wt.toFixed(2)}%` : ''} · ${U.eok(eok, true)}`;
    return `<small class="etf-ev ${kind === 'NEW' || kind === 'ADD' ? 'up' : 'dn'}" title="${U.esc(tip)}">${EV_TXT[kind]}${kind === 'ADD' || kind === 'CUT' ? pct : ''} ${U.md(day)}</small>`;
  }

  // 지수 정기변경 편입·편출 예정 한 줄 (data/rebal.json → build_etf_by_stock 이 종목 파일에 붙인다)
  function etfRebal(m) {
    if (!m) return '';
    const days = m.tv ? Math.abs(m.exp) / m.tv : null;
    const act = m.act != null ? ` · 실측(${U.md(m.rd)} 리밸런싱 몫) <b class="${U.cls(m.act)}">${U.eok(m.act, true)}</b>` : '';
    const wa = m.wa != null ? ` · 실제 비중 ${m.wa.toFixed(3)}%` : '';
    return `<div class="etf-rebal"><b>${U.md(m.rd)} ${U.esc(m.idx)} ${m.k === 'in' ? '편입' : '편출'} 예정</b>
      · 예상 패시브 <b class="${U.cls(m.exp)}">${U.eok(m.exp, true)}</b>${days != null ? ` (거래대금 ${days.toFixed(1)}일치)` : ''}${act}${wa}
      <small class="muted" title="${U.esc(`${m.t} · 추종 자금(1배+TR ETF) ${U.eok(m.aum)} × ${m.k === 'in' ? '편입 후 비중' : '지금 비중'} ${m.w}% · 거래대금은 20일 평균 · 적용일 ${m.ed} — 수급 탭 '지수 정기변경' 칸 기본값(신한식)과 같은 식`)}">계산식</small></div>`;
  }

  function etfHtml() {
    const d = etfData;
    if (d === undefined) return '<section class="st-sec"><h3>ETF 편입</h3><p class="muted st-loading">불러오는 중…</p></section>';
    if (d?.none) return `<section class="st-sec st-etf"><h3>ETF 편입 <small class="muted">ETF 없음</small></h3>
      <p class="muted small">구성(PDF)을 받는 국내 주식형·레버리지 ETF 가운데 이 종목을 담은 ETF 가 없습니다 — ETF 를 통한 기계적 수급은 0 입니다.
        안 받는 운용사(WON·파워·IBK 등 작은 곳)의 ETF 는 빠집니다.</p></section>`;
    if (!d?.rows?.length) return d?.rebal ? `<section class="st-sec st-etf"><h3>ETF 편입 <small class="muted">담은 ETF 없음</small></h3>${etfRebal(d.rebal)}</section>` : '';
    const p = etfP;
    const fmt = v => (v == null ? '<span class="muted">–</span>' : v === 0 ? '<span class="muted">0</span>' : `<span class="${U.cls(v)}">${U.eok(v, true)}</span>`);
    const pctH = v => (v == null ? '<span class="muted">–</span>' : `<span class="${U.cls(v)}">${v > 0 ? '+' : ''}${v.toFixed(2)}%</span>`);
    const held = d.rows.reduce((a, r) => a + (r[EI.held] || 0), 0);
    const cr = lastSum(d.h, p), rb = lastSum(d.rb || [], p), rl = lastSum(d.rl || [], p);
    const rbLate = d.rb && d.rb[d.rb.length - 1] == null;      // 마지막 날 리밸런싱은 아직 모름
    const gap = (d.g || []).slice(-p).some(x => x);
    const key = etfSort === 'share' ? r => -Math.abs(etfTot(r, p) || 0) : etfSort === 'rb' ? r => -Math.abs(r[EI.rb[p]] || 0)
      : etfSort === 'ret' ? r => -(r[EI.r[p]] ?? -1e9) : r => -(r[EI.held] || 0);
    const rows = [...d.rows].sort((a, b) => key(a) - key(b));
    const shown = etfAll ? rows : rows.slice(0, ETF_SHOW);
    const th = (k, l) => `<th class="num"><button class="linkish${etfSort === k ? ' on' : ''}" data-etfsort="${k}">${l}${etfSort === k ? ' ▾' : ''}</button></th>`;
    const nStale = d.rows.filter(r => r[EI.stale]).length;
    const nEv = d.rows.filter(r => r[EI.ev]).length;
    return `<section class="st-sec st-etf">
      <div class="st-sec-head"><h3>ETF 편입 <small class="muted">${d.rows.length}개 ETF · ${U.md(d.d)} 기준</small></h3>
        <div class="seg" role="group">${ETF_P.map(([k, l]) => `<button data-etfp="${k}" class="${k === p ? 'on' : ''}">${l}</button>`).join('')}</div></div>
      ${etfRebal(d.rebal)}
      <div class="st-kpis">
        <div><span>ETF 보유액 합</span><b>${U.eok(held)}</b>${etfMc ? `<small>시총의 ${(held / etfMc * 100).toFixed(2)}%</small>` : ''}</div>
        <div><span>ETF 매매 ${p}일</span><b>${fmt(etfSum(cr, rb))}</b><small>설정·환매 ${fmt(cr)} · 리밸런싱 ${fmt(rb)}${rl ? ` <span title="리밸런싱 가운데 레버리지 ETF 가 배수를 맞추느라 사고판 몫(값이 내리면 판다)">(레버리지 조정 ${fmt(rl)})</span>` : ''}${rbLate ? '<sup title="마지막 거래일 리밸런싱은 다음 거래일 PDF 가 와야 압니다">*</sup>' : ''}${gap ? ' <span title="PDF 가 빈 날이 있어 그 사이 변화를 다음 날에 몰아 적었습니다">(구간 합)</span>' : ''}</small></div>
        <div><span>담은 ETF</span><b>${d.rows.length}개</b><small>${nEv ? `20일 안 리밸런싱 ${nEv}개 · ` : ''}${nStale ? `비중 묵은 ETF ${nStale}개` : '모두 7일 안 PDF'}</small></div>
      </div>
      <div class="st-etf-plot"></div>
      <div class="tbl-wrap"><table class="tbl etf-tbl">
        <thead><tr><th>ETF</th><th class="num">비중</th>${th('held', '보유액')}${th('ret', `등락 ${p}일`)}<th class="num" title="ETF 순설정·환매 × 그날 비중">설정·환매 몫</th>${th('rb', '리밸런싱 몫')}${th('share', '합')}</tr></thead>
        <tbody>${shown.map(r => `<tr>
          <td class="etf-name"><a href="${naverUrl(r[EI.c])}" target="_blank" rel="noopener" title="${U.esc(r[EI.base] || '')}">${U.esc(r[EI.n] || r[EI.c])}</a>
            ${etfEvTag(r)}${r[EI.stale] ? `<small class="muted" title="운용사 PDF 가 ${r[EI.asof]} 이후 안 들어와 그때 비중을 씁니다">비중 ${U.md(r[EI.asof])}</small>` : ''}</td>
          <td class="num">${r[EI.wt] ? `${r[EI.wt].toFixed(2)}%` : '<span class="muted">편출</span>'}</td>
          <td class="num">${U.eok(r[EI.held])}</td>
          <td class="num">${pctH(r[EI.r[p]])}</td>
          <td class="num" title="ETF 순설정·환매 ${r[EI.f[p]] == null ? '–' : U.eok(r[EI.f[p]], true)} × 비중">${fmt(r[EI.cr[p]])}</td>
          <td class="num">${fmt(r[EI.rb[p]])}</td>
          <td class="num"><b>${fmt(etfTot(r, p))}</b></td></tr>`).join('')}</tbody>
      </table></div>
      ${rows.length > ETF_SHOW ? `<button class="linkish etf-more">${etfAll ? '접기' : `나머지 ${rows.length - ETF_SHOW}개 더 보기`}</button>` : ''}
      <p class="note">ETF 가 이 종목을 사고판 금액을 둘로 나눴습니다.
        <b>설정·환매 몫</b> = ETF 순설정·환매(상장좌수 변화 × NAV, KBJ 원장 — 칸에 마우스를 올리면 보입니다) × 그날 바스켓 비중 — LP·운용사가 바스켓째 사고판 금액.
        <b>리밸런싱 몫</b> = 1 CU 당 수량 변화 × 좌수(상장좌수 ÷ CU) × 주가 — 설정·환매 없이 운용사가 바스켓을 바꾼 매매(지수 변경·비중 조정·액티브 교체,
        그리고 레버리지 ETF 가 배수를 맞추는 일일 조정 — 값이 내리면 팔고 오르면 산다).
        PDF 날짜의 바스켓은 직전 거래일 장 마감 뒤 것이라, 수량 변화는 그 직전 거래일 매매로 적습니다.${rbLate ? ' * 마지막 거래일 리밸런싱은 다음 거래일 PDF 가 와야 압니다.' : ''}
        PDF 가 빈 날 뒤 첫 PDF 는 그 사이 변화를 한 날에 몰아 적습니다(구간 합).
        운용사 PDF 를 받는 ETF(KODEX·TIGER·RISE·ACE·SOL·HANARO·PLUS·KoAct·TIMEFOLIO·KIWOOM·1Q, 레버리지는 현물을 담는 몫만)만 들어가서 합계는 하한이고,
        인버스와 레버리지의 선물·스왑 노출은 빠집니다.${nStale ? ` 비중이 ${U.md(d.d)}보다 7일 넘게 묵은 ETF ${nStale}개는 날짜를 함께 적었습니다.` : ''}</p>
    </section>`;
  }

  function drawEtf() {
    const el = panel.querySelector('.st-etf-plot');
    const d = etfData;
    if (!el || !d?.h?.length) return;
    const h = d.h, rb = d.rb || h.map(() => null), rl = d.rl || h.map(() => 0), g = d.g || [], n = h.length;
    const from = rb.map((v, i) => (v != null && h[i] != null && (v >= 0) === (h[i] >= 0) ? h[i] : 0));   // 같은 방향이면 위에 쌓는다
    Plot.chart(el, {
      n, height: 130, uid: 'ste',
      panes: [{ h: 1, zero: true, fmt: v => U.eok(v, true), series: [
        { type: 'bar', values: h, cls: i => (h[i] >= 0 ? 'up' : 'dn') },
        { type: 'bar', values: rb, from, cls: () => 'rb' }] }],
      xTicks: d.days.map((x, i) => [i, U.md(x)]).filter((_, i) => i % 5 === (n - 1) % 5),
      tip: i => `<div class="tt-h">${U.md(d.days[i])}${g[i] ? ' <small>(구간 합)</small>' : ''}</div>
        <div class="tt-v">설정·환매 몫 <b class="${U.cls(h[i])}">${U.eok(h[i], true)}</b></div>
        <div class="tt-v">리밸런싱 몫 ${rb[i] == null ? '<b class="muted">다음 PDF 뒤</b>' : `<b class="${U.cls(rb[i])}">${U.eok(rb[i], true)}</b>`}${rl[i] ? ` <small>(레버리지 조정 ${U.eok(rl[i], true)})</small>` : ''}</div>
        <div class="tt-v">합 <b class="${U.cls(etfSum(h[i], rb[i]))}">${U.eok(etfSum(h[i], rb[i]), true)}</b></div>`,
    });
  }

  function paintEtf() {
    const slot = panel.querySelector('.st-etf-slot');
    if (!slot) return;
    slot.innerHTML = etfHtml();
    drawEtf();
  }

  async function loadEtf(c) {
    etfData = undefined;
    etfAll = false;
    let x = null;
    try { x = await U.json(`data/etf/${c}.json`); } catch (e) { x = { none: true }; /* 어느 ETF 도 담지 않은 종목 (파일 없음) */ }
    if (code !== c) return;
    etfData = x;
    paintEtf();
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
    etfMc = s.mc || null;
    panel.innerHTML = `${headHtml(s)}${chartHtml()}
      <div class="st-body">${d === undefined ? '<p class="muted st-loading">리포트·수급 불러오는 중…</p>'
        : `${growthHtml(s)}${targetHtml(s)}<div class="st-fund-slot"></div>${dartHtml()}${kwHtml(s)}${reportsHtml(s)}${flowHtml(s)}${flowDetailHtml(s)}<div class="st-etf-slot">${etfHtml()}</div>
           <p class="muted small st-note">리포트: 네이버 증권 리서치(증권사 제공) 요약에서 키워드를 뽑았습니다. 원문은 제목·PDF 링크로 보세요.
           목표가 변경은 같은 증권사의 직전 리포트와 비교했습니다. 목표 시총 = 목표가 × 지금 주식 수(우선주 포함 회사 시총 기준 어림).</p>`}</div>`;
    drawChart();
    drawEtf();
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
    loadEtf(c);
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
    const ep = e.target.closest('[data-etfp]');
    if (ep) { etfP = +ep.dataset.etfp; return paintEtf(); }
    const es = e.target.closest('[data-etfsort]');
    if (es) { etfSort = es.dataset.etfsort; return paintEtf(); }
    if (e.target.closest('.etf-more')) { etfAll = !etfAll; return paintEtf(); }
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

  // 카드용 기업 로고(네이버 증권 종목코드별 SVG) + 순위 배지. 로고가 없으면(404) 종목명 첫 글자 원형 배지로 대체
  function rankLogo(rank, s) {
    const ini = U.esc([...String(s.n || '?').replace(/^[(（][^)）]*[)）]/, '')][0] || '?');
    const ok = /^\d{6}$/.test(s.c || '');   // ETF·해외·빈 코드는 요청 없이 바로 글자 배지
    if (!ok) return `<div class="lg-wrap"><span class="rank">${rank}</span><span class="logo nologo" data-i="${ini}"></span></div>`;
    return `<div class="lg-wrap"><span class="rank">${rank}</span><span class="logo" data-i="${ini}"><img src="https://ssl.pstatic.net/imgstock/fn/real/logo/stock/Stock${s.c}.svg" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.parentNode.classList.add('nologo');this.remove()"></span></div>`;
  }

  return { open, close, link, hintAttr, watchList, toggleWatch, rankLogo };
})();
