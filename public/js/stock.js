// 종목 상세 패널: 종목 이름을 누르면 오른쪽에서 열린다 (모든 탭 공통)
// - 차트: data/chart/{code}.json 일봉(최근 1년)을 직접 그려 마우스를 올린 날의 시가·고가·저가·종가·거래량을 보여준다
// - 리포트·키워드·목표가·수급: data/stocks/{code}.json (맥에서 매일 빌드)
// 이름 링크는 네이버 증권 주소라서 Ctrl/⌘+클릭하면 네이버가 새 탭으로 열린다.
const Stock = (() => {
  const CHARTS = [['3m', '3개월'], ['6m', '6개월'], ['1y', '1년'], ['w', '주봉']];
  const DAYS = { '3m': 63, '6m': 126, '1y': 260 };
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  let panel, code = null, hint = {}, chart = '6m', kwOpen = null, cdata = null, filings = null;

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
    const all = chart === 'w' ? Plot.weekly(cdata) : cdata;
    const from = chart === 'w' ? 0 : Math.max(0, all.d.length - DAYS[chart]);
    const cut = k => all[k].slice(from);
    const d = cut('d'), c = cut('c'), o = cut('o'), h = cut('h'), l = cut('l'), v = cut('v');
    const mas = chart === 'w' ? [[13, 'var(--ma20)'], [26, 'var(--ma60)']] : [[5, 'var(--muted)'], [20, 'var(--ma20)'], [60, 'var(--ma60)']];
    const prev = i => (from + i > 0 ? all.c[from + i - 1] : null);
    const pch = i => (prev(i) ? (c[i] / prev(i) - 1) * 100 : null);
    panel.querySelector('.st-legend').innerHTML = mas.map(([k, col]) => `<i style="--c:${col}"></i>${k}${chart === 'w' ? '주' : '일'}`).join(' ') + ' 이동평균';
    Plot.chart(el, {
      n: d.length, height: 300, uid: 'stc',
      panes: [
        { h: 3.4, fmt: num, series: [{ type: 'candle', o, h, l, c },
          ...mas.map(([k, col]) => ({ type: 'line', values: Plot.ma(all.c, k).slice(from), color: col, width: 1.1, nodot: true }))] },
        { h: 1, fmt: vol, series: [{ type: 'bar', values: v, cls: i => (pch(i) >= 0 ? 'up' : 'dn') }] },
      ],
      xTicks: Plot.monthTicks(d),
      tip: i => `<div class="tt-h">${Plot.dateStr(d[i])}${chart === 'w' ? ' 주' : ''}</div>
        <div class="tt-v">${num(c[i])} ${chHtml(pch(i))}</div>
        ${o[i] == null ? '<div class="muted">KRX 공개 전 임시 종가</div>' : `<div class="tt-g"><span>시가</span><b>${num(o[i])}</b><span>고가</span><b>${num(h[i])}</b>
          <span>저가</span><b>${num(l[i])}</b><span>거래량</span><b>${vol(v[i])}</b></div>`}`,
    });
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
        <p class="muted small">${[MARKETS[s.mk], s.w, s.mc != null ? `시총 ${U.eok(s.mc)}` : ''].filter(Boolean).map(U.esc).join(' · ')}</p>
      </div>
      <div class="st-price">${s.p != null ? `<b>${U.price(s.p)}</b>${chHtml(s.ch)}<small class="muted">종가</small>` : ''}</div>
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
      <p class="muted small">일봉: KRX (마지막 날은 KRX 공개 전 네이버 종가일 수 있음) · <a href="${naverUrl(code)}" target="_blank" rel="noopener">네이버 실시간 차트 ↗</a></p>
    </section>`;
  }

  function growthHtml(gx) {
    if (!gx) return '';
    const g = gx.k === 'turnaround' ? '흑자전환' : gx.k === 'loss' ? '적자 지속' : U.pct(gx.g);
    const gc = gx.k === 'turnaround' ? 'up' : gx.k === 'loss' ? 'down' : U.cls(gx.g);
    return `<div class="st-kpis">
      <div><span>내년 영업이익 성장</span><b class="${gc}">${g}</b>${gx.lb ? '<small class="muted">기저</small>' : ''}</div>
      <div><span>내년 POR</span><b>${U.mult(gx.por)}</b></div>
      <div><span>추정치 1개월 변화</span><b class="${U.cls(gx.r1)}">${U.pct(gx.r1)}</b></div>
    </div>`;
  }

  function targetHtml(d) {
    const t = d.tgt;
    if (!t) return '';
    const upside = d.p ? t.avg / d.p - 1 : null;
    return `<div class="st-kpis">
      <div><span>평균 목표가 <small class="muted">${t.n}개 증권사</small></span><b>${U.price(t.avg)}</b>
        ${upside != null ? `<small>상승여력 <b class="${U.cls(upside)}">${U.pct(upside)}</b></small>` : ''}</div>
      <div><span>목표가 범위</span><b class="st-range">${U.price(t.lo)} ~ ${U.price(t.hi)}</b></div>
      <div><span>90일 목표가 변경</span><b>상향 <span class="up">${t.up}</span> · 하향 <span class="down">${t.dn}</span></b></div>
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
    if (!r.pg || r.pg === r.g) return `${U.price(r.g)}${r.pg ? ' <span class="muted">유지</span>' : ''}`;
    const ch = r.g / r.pg - 1;
    return `<span class="muted">${U.price(r.pg)} →</span> <b>${U.price(r.g)}</b> <span class="${U.cls(ch)}">${U.pct(ch)}</span>`;
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
        <thead><tr><th>날짜</th><th class="num">종가</th><th class="num">외국인</th><th class="bar-cell"></th><th class="num">기관</th><th class="bar-cell"></th><th class="num">개인</th></tr></thead>
        <tbody>${d.flow.slice(0, 10).map(r => `<tr>
          <td class="muted">${U.md(r[0])}</td><td class="num">${U.price(r[4])}</td>
          <td class="num">${fmt(r[1])}</td><td class="bar-cell"><span class="fbar">${bar(r[1])}</span></td>
          <td class="num">${fmt(r[2])}</td><td class="bar-cell"><span class="fbar">${bar(r[2])}</span></td>
          <td class="num">${fmt(r[3])}</td></tr>`).join('')}</tbody>
      </table>
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
    panel.innerHTML = `${headHtml(s)}${chartHtml()}
      <div class="st-body">${d === undefined ? '<p class="muted st-loading">리포트·수급 불러오는 중…</p>'
        : `${growthHtml(s.gx)}${targetHtml(s)}${dartHtml()}${kwHtml(s)}${reportsHtml(s)}${flowHtml(s)}
           <p class="muted small st-note">리포트: 네이버 증권 리서치(증권사 제공) 요약에서 키워드를 뽑았습니다. 원문은 제목·PDF 링크로 보세요.
           목표가 변경은 같은 증권사의 직전 리포트와 비교했습니다.</p>`}</div>`;
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
    render(undefined);
    panel.scrollTop = 0;
    loadChart(c);
    loadFilings(c);
    let d = null;
    try {
      d = await U.json(`data/stocks/${c}.json`);
    } catch (e) { /* 리포트·수급 데이터가 없는 종목 */ }
    if (code === c) render(d || null);
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

  return { open, close, link, hintAttr };
})();
