// 홈 탭: data/home.json
// - 지수: 당일 1분봉·투자자별 순매수 흐름·일봉을 직접 그려, 마우스를 올린 시각·날짜의 값을 보여준다
// - 맥이 10분마다 home.json 을 새로 올리고(live.py), 화면은 평일 07:00~20:00 1분마다·탭으로 돌아올 때 바뀌었는지 확인해 다시 그린다
(() => {
  const POLL_MS = 60000;
  const RANGES = [['1d', '당일'], ['3m', '3개월'], ['1y', '1년']];
  const INV = [['개인', 3, 'var(--inv-ind)'], ['외국인', 1, 'var(--inv-frgn)'], ['기관', 2, 'var(--inv-org)']];
  // 09:00 ~ 15:30 (선물은 15:45)
  const session = x => (x.c === 'FUT' ? 406 : 391);
  const isFut = x => x.c === 'FUT';
  // 선물 순매수는 네이버가 단위를 표시하지 않아 받은 숫자 그대로 (지수는 억원)
  const signed = v => (v == null ? '–' : `${v > 0 ? '+' : ''}${Math.round(v).toLocaleString('ko-KR')}`);
  const flowFmt = x => (isFut(x) ? signed : v => U.eok(v, true));
  const contracts = v => (v >= 1e4 ? `${(v / 1e4).toFixed(1)}만` : Math.round(v).toLocaleString('ko-KR'));

  const $ = id => document.getElementById(id);
  const range = { KOSPI: '1d', KOSDAQ: '1d', FUT: '1d' };
  const tabs = {};          // 카드별 선택 탭
  let map = 'sector', mapPer = 'ch', mabMk = 'KOSPI';
  // 지도 기간: 키, 이름, 가장 진한 색이 되는 등락률
  const MAP_PERS = [['ch', '1일', 3], ['w1', '1주', 7], ['m1', '1개월', 15], ['m3', '3개월', 25]];
  let data = null;

  const chg = ch => (ch == null ? '–' : `${ch > 0 ? '+' : ''}${ch.toFixed(2)}%`);
  const chgHtml = ch => `<span class="${U.cls(ch)}">${chg(ch)}</span>`;
  const pill = ch => `<span class="pill-ch ${U.cls(ch)}">${chg(ch)}</span>`;
  const hm = ts => ts.slice(11, 16);
  const idxNum = v => (v == null ? '–' : v.toLocaleString('ko-KR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const minIdx = t => (+t.slice(0, 2) - 9) * 60 + +t.slice(3, 5);
  const minLabel = i => `${String(9 + Math.floor(i / 60)).padStart(2, '0')}:${String(i % 60).padStart(2, '0')}`;
  // 지수 거래량은 천주 단위
  const idxVol = v => (v >= 1e5 ? `${(v / 1e5).toFixed(1)}억` : `${Math.round(v / 1e3).toLocaleString('ko-KR')}백만`);
  const isLive = () => data.live && U.marketHours();

  // ---------- 지수 ----------
  function idxCard(x) {
    const b = x.up != null ? { up: x.up, dn: x.dn, fl: x.fl } : data.breadth[x.c];
    const total = b ? b.up + b.dn + b.fl || 1 : 1;
    const intraday = x.at && x.at.slice(0, 10) === x.d && hm(x.at) < (isFut(x) ? '15:50' : '15:40');
    const flows = [['개인', x.i, 'ind'], ['외국인', x.f, 'frgn'], ['기관', x.o, 'org'],
      ...(isFut(x) ? [] : [['프로그램', x.pg, 'prog']])];
    const ff = flowFmt(x);
    return `<article class="card hm-ix" data-ix="${x.c}">
      <header class="hm-ix-head">
        <div>
          <h2>${x.n}</h2>
          <span class="muted small hm-ix-when">${U.dateLabel(x.d)} ${intraday ? `장중 ${hm(x.at)}` : '종가'}</span>
        </div>
        <div class="hm-ix-val"><b>${idxNum(x.v)}</b><span class="hm-ix-ch">${chgHtml(x.ch)}</span></div>
      </header>
      <div class="hm-ix-bar">
        <div class="seg" role="group">${RANGES.map(([k, l]) =>
          `<button data-range="${k}" class="${range[x.c] === k ? 'on' : ''}">${l}</button>`).join('')}</div>
        <span class="muted small hm-legend"></span>
      </div>
      <div class="hm-ix-chart"></div>
      ${x.f != null ? `<div class="hm-ix-flow${isFut(x) ? ' three' : ''}">${flows.map(([n, v, k]) =>
        `<div class="inv-${k}"><span>${n}</span><b class="${U.cls(v)}">${ff(v)}</b></div>`).join('')}</div>` : ''}
      ${isFut(x) ? `<p class="muted small">최근월물 · 투자자별 순매수는 네이버 값 그대로 (네이버가 단위를 표시하지 않음)</p>` : b ? `<div class="hm-breadth">
        <div class="hm-bd-bar"><i class="up-bg" style="flex:${b.up}"></i><i class="flat-bg" style="flex:${b.fl}"></i><i class="dn-bg" style="flex:${b.dn}"></i></div>
        <div class="small hm-bd-txt"><span class="up">상승 ${b.up}</span><span class="muted">보합 ${b.fl}</span><span class="down">하락 ${b.dn}</span>
          <span class="muted">상승 비율 ${Math.round(b.up / total * 100)}%</span></div>
      </div>` : ''}
    </article>`;
  }

  // 헤더 숫자를 마우스가 가리키는 값으로 (떠나면 원래대로)
  function readout(card, x, v, ch, when) {
    card.querySelector('.hm-ix-val b').textContent = idxNum(v ?? x.v);
    card.querySelector('.hm-ix-ch').innerHTML = chgHtml(v == null ? x.ch : ch);
    const w = card.querySelector('.hm-ix-when');
    if (!w.dataset.orig) w.dataset.orig = w.textContent;
    w.textContent = v == null ? w.dataset.orig : when;
    card.classList.toggle('hovering', v != null);
    if (v == null) setTimeout(applyPending, 0);
  }

  function drawIntraday(card, x) {
    const n = session(x);
    const ff = flowFmt(x);
    const price = Array(n).fill(null);
    for (const [t, p] of x.min) { const i = minIdx(t); if (i >= 0 && i < n) price[i] = p; }
    const base = x.prev;
    const snaps = x.snap || [];
    const inv = INV.map(([name, k, color]) => {
      const vals = Array(n).fill(null);
      for (const s of snaps) { const i = Math.min(n - 1, Math.max(0, minIdx(s[0]))); vals[i] = s[k]; }
      return { name, color, vals };
    });
    const hasFlow = snaps.length >= 2;
    const panes = [{ h: 3, baseline: base, fmt: v => idxNum(v),
      series: [{ type: 'line', values: price, split: true, area: true, width: 1.7 }] }];
    if (hasFlow) {
      panes.push({ h: 1.6, zero: true, label: `투자자별 누적 순매수${isFut(x) ? '' : ' (억원)'}`, fmt: ff,
        series: inv.map(s => ({ type: 'line', values: s.vals, color: s.color, connect: true, width: 1.6, last: true })) });
    }
    const last = (arr, i) => { for (let k = i; k >= 0; k--) if (arr[k] != null) return arr[k]; return null; };
    card.querySelector('.hm-legend').innerHTML = hasFlow
      ? INV.map(([n, , c]) => `<i style="--c:${c}"></i>${n}`).join(' ') + ' <span>순매수</span>'
      : `전일 종가 ${idxNum(base)} 기준`;
    Plot.chart(card.querySelector('.hm-ix-chart'), {
      n, height: hasFlow ? 300 : 230, panes, uid: `ix${x.c}`,
      xTicks: [0, 60, 120, 180, 240, 300, 360].map(i => [i, minLabel(i)]),
      has: i => price[i] != null,
      tip: i => {
        const v = price[i];
        const rows = hasFlow ? inv.map(s => {
          const fv = last(s.vals, i);
          return fv == null ? '' : `<div><i style="--c:${s.color}"></i>${s.name}<b class="${U.cls(fv)}">${ff(fv)}</b></div>`;
        }).join('') : '';
        return `<div class="tt-h">${minLabel(i)}</div><div class="tt-v">${idxNum(v)} ${chgHtml(base ? (v / base - 1) * 100 : null)}</div>${rows}`;
      },
      onHover: i => readout(card, x, i == null ? null : price[i], i == null ? null : (price[i] / base - 1) * 100,
        i == null ? '' : `${U.dateLabel(x.d)} ${minLabel(i)}`),
    });
  }

  function drawDaily(card, x, days, candle) {
    const o = x.ohlc;
    const from = Math.max(0, o.d.length - days);
    const cut = k => o[k].slice(from);
    const d = cut('d'), c = cut('c');
    const ma = k => Plot.ma(o.c, k).slice(from);
    const prevC = i => (from + i > 0 ? o.c[from + i - 1] : null);
    const pchg = i => (prevC(i) ? (c[i] / prevC(i) - 1) * 100 : null);
    const price = candle
      ? [{ type: 'candle', o: cut('o'), h: cut('h'), l: cut('l'), c },
        { type: 'line', values: ma(20), color: 'var(--ma20)', width: 1.2, nodot: true },
        { type: 'line', values: ma(60), color: 'var(--ma60)', width: 1.2, nodot: true }]
      : [{ type: 'line', values: c, color: 'var(--text)', area: true, width: 1.5 }];
    const vol = cut('v');
    card.querySelector('.hm-legend').innerHTML = candle
      ? '<i style="--c:var(--ma20)"></i>20일 <i style="--c:var(--ma60)"></i>60일 이동평균' : '종가';
    Plot.chart(card.querySelector('.hm-ix-chart'), {
      n: d.length, height: 270, uid: `ix${x.c}`,
      panes: [{ h: 3.2, fmt: v => idxNum(v), series: price },
        { h: 1, fmt: isFut(x) ? contracts : idxVol, series: [{ type: 'bar', values: vol, cls: i => (pchg(i) >= 0 ? 'up' : 'dn') }] }],
      xTicks: Plot.monthTicks(d),
      tip: i => `<div class="tt-h">${Plot.dateStr(d[i])}</div>
        <div class="tt-v">${idxNum(c[i])} ${chgHtml(pchg(i))}</div>
        ${candle ? `<div class="tt-g"><span>시가</span><b>${idxNum(o.o[from + i])}</b><span>고가</span><b>${idxNum(o.h[from + i])}</b>
          <span>저가</span><b>${idxNum(o.l[from + i])}</b><span>거래량</span><b>${isFut(x) ? `${Math.round(vol[i]).toLocaleString('ko-KR')}계약` : `${idxVol(vol[i])}주`}</b></div>` : ''}`,
      onHover: i => readout(card, x, i == null ? null : c[i], i == null ? null : pchg(i),
        i == null ? '' : U.dateLabel(`${String(d[i]).slice(0, 4)}-${String(d[i]).slice(4, 6)}-${String(d[i]).slice(6, 8)}`)),
    });
  }

  function drawIdx(card) {
    const x = data.idx.find(t => t.c === card.dataset.ix);
    const r = range[x.c];
    if (r === '1d' && x.min?.length) drawIntraday(card, x);
    else if (r === '3m') drawDaily(card, x, 63, true);
    else drawDaily(card, x, 260, false);
  }

  function renderIdx() {
    $('idx').innerHTML = data.idx.map(idxCard).join('');
    document.querySelectorAll('.hm-ix').forEach(drawIdx);
  }

  $('idx').addEventListener('click', e => {
    const b = e.target.closest('[data-range]');
    if (!b) return;
    const card = b.closest('.hm-ix');
    range[card.dataset.ix] = b.dataset.range;
    card.querySelectorAll('[data-range]').forEach(x => x.classList.toggle('on', x === b));
    drawIdx(card);
  });

  // ---------- 지도 (업종 / 시총 상위) ----------
  function memberTip(t) {
    return `<div class="tt-row"><span>${U.esc(t.n)}</span>${chgHtml(t.ch)}</div>`;
  }

  // 시총 차이가 너무 커서(반도체·삼성전자) 면적은 시총의 0.6제곱에 비례시킨다
  const area = mc => Math.pow(mc, 0.6);

  function renderMap() {
    const sec = map === 'sector';
    const [pk, pl, pmax] = MAP_PERS.find(x => x[0] === mapPer);
    const val = x => x[pk];
    const items = sec
      ? data.sectors.all.map(s => ({
        v: area(s.mc), color: Plot.heat(val(s), pmax), hot: Math.abs(val(s) ?? 0) >= pmax / 3,
        html: `<b>${U.esc(s.w)}</b><span>${chg(val(s))}</span>`,
        tip: `<div class="tt-h">${U.esc(s.w)} <span class="muted">${s.k}종목 · 시총 ${U.eok(s.mc)}</span></div>
          <div class="tt-v">${pl} ${chgHtml(val(s))}</div>${s.top.map(t => memberTip({ ...t, ch: val(t) })).join('')}`,
      }))
      : data.big.map(s => ({
        v: area(s.mc), color: Plot.heat(val(s), pmax), hot: Math.abs(val(s) ?? 0) >= pmax / 3,
        html: `<a href="https://finance.naver.com/item/main.naver?code=${s.c}" target="_blank" rel="noopener" data-code="${s.c}"><b>${U.esc(s.n)}</b></a><span>${chg(val(s))}</span>`,
        attrs: Stock.hintAttr(s),
        tip: `<div class="tt-h">${U.esc(s.n)} <span class="muted">${s.w ? U.esc(s.w) : ''}</span></div>
          <div class="tt-v">${U.price(s.p)} ${chgHtml(s.ch)}</div>
          <div class="tt-g"><span>1주</span><b>${chgHtml(s.w1)}</b><span>1개월</span><b>${chgHtml(s.m1)}</b><span>3개월</span><b>${chgHtml(s.m3)}</b></div>
          <div class="muted">시총 ${U.eok(s.mc)}</div>`,
      }));
    $('map').innerHTML = `<div class="sec-head">
        <div><h2>${sec ? '업종 지도' : '시총 상위 지도'}</h2>
          <p class="muted small">${sec ? `WICS 업종 ${data.sectors.n}개 · 크기 = 업종 시총(큰 업종은 줄여 표시) · 색 = 시총 가중 등락률` : `시총 상위 ${data.big.length}종목 · 크기 = 시총(큰 종목은 줄여 표시) · 색 = 등락률 · 누르면 종목 상세`}</p></div>
        <div class="sec-tools">
          <div class="seg" role="group">${MAP_PERS.map(([k, l]) => `<button data-per="${k}" class="${k === mapPer ? 'on' : ''}">${l}</button>`).join('')}</div>
          <div class="seg" role="group"><button data-map="sector" class="${sec ? 'on' : ''}">업종</button><button data-map="big" class="${sec ? '' : 'on'}">시총 상위</button></div>
        </div>
      </div>
      <div class="tm-wrap"></div>
      <div class="tm-scale small muted"><span>-${pmax}%</span>${[-3, -2, -1, 0, 1, 2, 3].map(v => `<i style="background:${Plot.heat(v * pmax / 3, pmax)}"></i>`).join('')}<span>+${pmax}%</span></div>`;
    const wrap = $('map').querySelector('.tm-wrap');
    Plot.treemap(wrap, { items, height: window.innerWidth < 560 ? 340 : 400 });
  }

  $('map').addEventListener('click', e => {
    const b = e.target.closest('[data-map]'), p = e.target.closest('[data-per]');
    if (b) map = b.dataset.map;
    else if (p) mapPer = p.dataset.per;
    else return;
    renderMap();
  });

  // ---------- 카드 ----------
  function item(s, right, sub = '', rank = null) {
    return `<li ${Stock.hintAttr(s)}>
      ${rank != null ? `<span class="hm-rank">${rank}</span>` : ''}
      <div class="hm-it-main">${Stock.link(s)}${sub ? `<small class="muted">${sub}</small>` : ''}</div>
      <div class="hm-it-right">${right}</div>
    </li>`;
  }
  const list = (rows, empty = '해당 종목 없음') => (rows && rows.length
    ? `<ol class="hm-list">${rows.join('')}</ol>` : `<p class="muted small hm-empty">${empty}</p>`);

  // tabs: [[key, label, cls, html]]
  function card(id, { title, meta, href, tabs: tb, body, wide }) {
    const on = tabs[id] || (tb && tb[0][0]);
    return `<article class="card hm-card${wide ? ' wide' : ''}" data-card="${id}">
      <header class="hm-card-head">
        <div><h3>${title}</h3><p class="muted small">${meta}</p></div>
        ${href ? `<a class="hm-more" href="${href}" title="자세히">더 보기 <span aria-hidden="true">›</span></a>` : ''}
      </header>
      ${tb ? `<div class="hm-tabs" role="tablist">${tb.map(([k, l, c]) =>
        `<button role="tab" data-tab="${k}" class="${c || ''}${k === on ? ' on' : ''}">${l}</button>`).join('')}</div>
        ${tb.map(([k, , , html]) => `<div class="hm-pane" data-pane="${k}"${k === on ? '' : ' hidden'}>${html}</div>`).join('')}` : body}
    </article>`;
  }

  function moversCard() {
    const m = data.movers;
    const row = (s, i) => item(s, pill(s.ch), [s.w && U.esc(s.w), U.eok(s.mc)].filter(Boolean).join(' · '), i + 1);
    return card('movers', { title: '급등 · 급락', meta: `시총 3,000억 이상${isLive() ? ` · 장중 ${hm(data.live)}` : ''}`,
      tabs: [['up', `상승 ${m.up.length}`, 'up', list(m.up.map(row))], ['dn', `하락 ${m.dn.length}`, 'down', list(m.dn.map(row))]] });
  }

  function flowCard() {
    const f = data.flow;
    if (!f) return '';
    const row = (s, i) => item(s, `<b class="${U.cls(s.f + s.o)}">${U.eok(s.f + s.o, true)}</b>`,
      `외국인 ${U.eok(s.f, true)} · 기관 ${U.eok(s.o, true)}`, i + 1);
    // 네이버가 그날 종목별 수급을 아직 안 올렸으면 이전 거래일 것 (올라오면 10분 안에 자동으로 바뀜)
    const late = f.d < data.date ? ` · ${U.dateLabel(data.date)} 종목별 수급은 네이버 공개 전` : '';
    return card('flow', { title: '외국인 + 기관', meta: `${U.dateLabel(f.d)} 하루 순매수 금액${late}`, href: 'flow.html?who=fo&days=1',
      tabs: [['buy', '순매수', 'up', list(f.buy.map(row))], ['sell', '순매도', 'down', list(f.sell.map(row))]] });
  }

  function revCard() {
    const r = data.rev;
    if (!r) return '';
    const fy = `FY${String(r.fy).slice(2)}`;
    const row = (s, i) => item(s, `<b class="${U.cls(s.r)}">${U.pct(s.r)}</b>`, `${fy} 영업이익 ${U.eok(s.now)}`, i + 1);
    return card('rev', { title: '추정치 리비전', meta: `${fy} 영업이익 1주 변화`, href: 'revision.html?per=w1',
      tabs: [['up', `상향 ${r.nup}`, 'up', list(r.up.map(row))], ['dn', `하향 ${r.ndn}`, 'down', list(r.dn.map(row))]] });
  }

  function tgtCard() {
    const t = data.tgt;
    if (!t) return '';
    const row = (s, i) => item(s, `<b class="${U.cls(s.r)}">${U.pct(s.r, 0)}</b>`,
      `${U.esc(s.b)} · ${U.price(s.pg)} → ${U.price(s.g)}`, i + 1);
    return card('tgt', { title: '목표가 변경', meta: `최근 1주 리포트 ${t.n}건 · 같은 증권사 직전 대비`, href: 'revision.html?view=tgt',
      tabs: [['up', `상향 ${t.nup}`, 'up', list(t.up.map(row))], ['dn', `하향 ${t.ndn}`, 'down', list(t.dn.map(row))]] });
  }

  function highCard() {
    const h = data.high;
    if (!h) return '';
    const intraday = h.at && h.at.slice(0, 10) === h.d && hm(h.at) < '15:40';
    return card('high', { title: '52주 신고가', meta: `${U.dateLabel(h.d)} ${h.n}종목${intraday ? ` · 장중 ${hm(h.at)}` : ''} · 시총 순`, href: 'high.html',
      body: list(h.list.map((s, i) => item(s, pill(s.ch),
        [s.w && U.esc(s.w), U.eok(s.mc), s.run >= 2 ? `${s.run}일 연속` : ''].filter(Boolean).join(' · '), i + 1)),
      '이날 신고가 종목 없음') });
  }

  function reportsCard() {
    if (!data.reports) return '';
    const rows = data.reports.map(r => `<li ${Stock.hintAttr(r)}>
      <div class="hm-rep-meta small"><span class="muted">${U.md(r.d)}</span><span>${U.esc(r.b)}</span>
        ${r.op ? `<span class="pill">${U.esc(r.op)}</span>` : ''}
        ${r.g ? `<span class="hm-rep-g">목표 ${U.price(r.g)}${r.g && r.pg && r.g !== r.pg
          ? ` <span class="${U.cls(r.g - r.pg)}">${r.g > r.pg ? '▲' : '▼'}${U.pct(r.g / r.pg - 1, 0)}</span>` : ''}</span>` : ''}</div>
      <div class="hm-rep-main">${Stock.link(r)}
        <a class="hm-rep-t" href="https://m.stock.naver.com/research/company/${r.id}" target="_blank" rel="noopener">${U.esc(r.t)}</a></div>
    </li>`);
    return card('rep', { title: '최신 리포트', meta: '네이버 증권 종목분석 · 제목을 누르면 원문', href: 'revision.html?view=tgt&tdays=1',
      body: `<ul class="hm-reps">${rows.slice(0, 8).join('')}</ul>` });
  }

  // 관심종목: 종목 패널의 ☆로 담은 종목 (이 브라우저에 저장). 시세는 data/quotes.json
  let quotes = null;
  function watchCard() {
    const ws = Stock.watchList();
    if (!ws.length) {
      return card('watch', { title: '관심종목', meta: '이 브라우저에만 저장',
        body: '<p class="muted small hm-empty">종목 이름을 눌러 상세 패널을 열고 ☆를 누르면 여기에 모입니다. 오른쪽 위 검색(/)으로도 찾을 수 있습니다.</p>' });
    }
    const rows = ws.map(w => {
      const q = quotes?.[w.c];
      const s = { ...w, p: q?.[0], ch: q?.[1] };
      return item(s, q ? `<span class="muted">${U.price(s.p)}</span> ${pill(s.ch)}` : '<span class="muted small">시세 없음</span>');
    });
    return card('watch', { title: '관심종목', meta: `${ws.length}종목 · ${isLive() ? `장중 ${hm(data.live)}` : U.dateLabel(data.date)}`, body: list(rows) });
  }

  async function loadQuotes() {
    if (!Stock.watchList().length) return;
    try {
      quotes = await (await fetch(U.bust('data/quotes.json', 1), { cache: 'no-store' })).json();
    } catch (e) { quotes = {}; }
    const el = document.querySelector('[data-card="watch"]');
    if (el) el.outerHTML = watchCard();
  }
  document.addEventListener('watchchange', () => {
    const el = document.querySelector('[data-card="watch"]');
    if (el) el.outerHTML = watchCard();
    if (!quotes) loadQuotes();
  });

  // 시장 폭: 이동평균 위 종목 비율 (stock-vcpscreener 류의 breadth 지표)
  function mabCard() {
    if (!data.mab) return '';
    return card('mab', { title: '시장 폭', meta: '이동평균 위에 있는 종목 비율 · 높을수록 고르게 오름',
      body: `<div class="hm-mab-bar"><div class="seg" role="group">${[['KOSPI', '코스피'], ['KOSDAQ', '코스닥']].map(([k, l]) =>
        `<button data-mab="${k}" class="${k === mabMk ? 'on' : ''}">${l}</button>`).join('')}</div>
        <span class="muted small hm-legend"><i style="--c:var(--ma20)"></i>20일 <i style="--c:var(--inv-org)"></i>60일 <i style="--c:var(--ma60)"></i>120일</span></div>
        <div class="hm-mab-chart"></div><div class="hm-mab-now small"></div>` });
  }

  function drawMab() {
    const el = document.querySelector('.hm-mab-chart');
    if (!el || !data.mab) return;
    const m = data.mab, x = m[mabMk];
    const ser = [['20', 'var(--ma20)', '20일'], ['60', 'var(--inv-org)', '60일'], ['120', 'var(--ma60)', '120일']];
    Plot.chart(el, {
      n: m.d.length, height: 200, uid: 'mab',
      panes: [{ fmt: v => `${Math.round(v)}%`, series: ser.map(([k, c]) => ({ type: 'line', values: x[k], color: c, width: 1.6, last: true })) }],
      xTicks: Plot.monthTicks(m.d),
      tip: i => `<div class="tt-h">${Plot.dateStr(m.d[i])}</div>${ser.map(([k, c, l]) =>
        `<div><i style="--c:${c}"></i>${l} 위<b>${x[k][i] ?? '–'}%</b></div>`).join('')}`,
    });
    const last = k => x[k][x[k].length - 1];
    document.querySelector('.hm-mab-now').innerHTML = ser.map(([k, , l]) => `<span>${l} 위 <b>${last(k) ?? '–'}%</b></span>`).join('');
  }

  // 거래대금 급증 (stocking 류의 거래량 급증 알림)
  function spikeCard() {
    const t = data.spike;
    if (!t) return '';
    const row = (s, i) => item(s, `<b class="hm-x">${s.x}배</b> ${pill(s.ch)}`, `거래대금 ${U.eok(s.tv)} · 20일 평균 ${U.eok(s.av)}`, i + 1);
    return card('spike', { title: '거래대금 급증', meta: `${t.live ? `장중 ${hm(data.live)}까지` : U.dateLabel(t.d)} · 20일 평균의 3배 이상 ${t.n}종목`,
      body: list(t.list.map(row), '오늘은 급증한 종목 없음') });
  }

  function dartCard() {
    const t = data.dart;
    if (!t) return '';
    const F = DartFmt;
    const rows = t.items.map(x => `<li ${Stock.hintAttr(x)}>
      <div class="hm-it-main"><div class="dt-name">${Stock.link(x)}<small class="muted">${F.KIND_LABEL[x.k]}</small>
        ${F.tags(x).filter(g => g !== '정정').map(g => `<span class="dt-tag ${g === '서프' ? 'up' : g === '쇼크' ? 'down' : ''}">${g}</span>`).join('')}</div>
        <small class="muted hm-dart-line">${U.esc(F.body(x).split('\n')[0])}</small></div>
    </li>`);
    const next = t.next.length ? `<p class="small hm-dart-next"><b>${F.md(t.next[0].date)} 실적발표 예정</b>
      ${t.next.filter(e => e.date === t.next[0].date).slice(0, 12).map(e => `<span ${Stock.hintAttr(e)}>${Stock.link(e)}</span>`).join(' · ')}</p>` : '';
    return card('dart', { title: '오늘의 공시', meta: `${U.dateLabel(t.d)} ${t.n}건 · 잠정실적 ${t.earn}건 (서프 ${t.sp} · 쇼크 ${t.sk})`,
      href: 'dart.html', body: `${list(rows, '눈에 띄는 공시 없음')}${next}`, wide: true });
  }

  function renderGrid() {
    $('grid').innerHTML = [dartCard(), watchCard(), mabCard(), spikeCard(), moversCard(), flowCard(), highCard(),
      revCard(), tgtCard(), reportsCard()].join('');
    drawMab();
    loadQuotes();
  }

  $('grid').addEventListener('click', e => {
    const mb = e.target.closest('[data-mab]');
    if (mb) {
      mabMk = mb.dataset.mab;
      document.querySelectorAll('[data-mab]').forEach(x => x.classList.toggle('on', x === mb));
      return drawMab();
    }
    const b = e.target.closest('[data-tab]');
    if (!b) return;
    const c = b.closest('[data-card]');
    tabs[c.dataset.card] = b.dataset.tab;
    c.querySelectorAll('[data-tab]').forEach(x => x.classList.toggle('on', x === b));
    c.querySelectorAll('[data-pane]').forEach(p => { p.hidden = p.dataset.pane !== b.dataset.tab; });
  });

  function renderFoot() {
    $('foot').innerHTML = `
      <p>지수·분봉·투자자별 순매수·상승/하락 종목 수: 네이버 증권. 장중에는 10분마다 받아 올립니다 (당일 순매수 흐름은 그 10분 간격 값을 이은 선).</p>
      <p>종목 시세: KRX 종가 (KRX 공개 전·장중에는 네이버 시세). 업종: WICS. 추정치: FnGuide 컨센서스(네이버 종목분석, 컨센 ${U.dateLabel(data.rev?.cns || data.date)}).</p>
      <p>목표가·리포트: 네이버 증권 리서치(증권사 제공). 수급 금액은 순매수 수량 × 종가 어림. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  }

  // 위쪽 기준 시각. 장중인데 20분 넘게 새 시세가 없으면(맥이 꺼짐·잠듦 등) 지연이라고 분명히 보여 준다
  const STALE_MIN = 20;
  function stamp() {
    const ago = U.minsAgo(data.live);
    let html;
    if (U.marketHours() && ago <= STALE_MIN) {
      html = `<span class="live-dot"></span>장중 ${hm(data.live)} 시세 · 10분마다 갱신`;
    } else if (U.marketHours()) {
      html = `<span class="stale">⚠ 갱신 지연</span> 마지막 ${data.live ? U.timeLabel(data.live) : U.timeLabel(data.built)}`;
    } else if (data.live && data.live.slice(0, 10) > data.date) {
      html = `${U.timeLabel(data.live)} 장중 시세 <span class="muted">(그날 종가 반영 전)</span>`;
    } else {
      html = `${U.dateLabel(data.date)} 종가 기준 · ${U.timeLabel(data.built)} 갱신`;
    }
    $('asof').innerHTML = html;
  }

  function renderAll() {
    stamp();
    renderIdx();
    renderMap();
    renderGrid();
    renderFoot();
  }

  async function fetchHome() {
    // CDN 10분 캐시를 피하려고 주소에 시각을 붙인다
    const r = await fetch(U.bust('data/home.json', 1), { cache: 'no-store' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  async function load() {
    try {
      data = await fetchHome();
    } catch (e) {
      $('msg').textContent = `데이터를 불러오지 못했습니다. (${e.message})`;
      return;
    }
    $('msg').hidden = true;
    renderAll();
  }

  // 새로 올라왔으면 다시 그린다. 차트에 마우스를 올려 둔 중이면 받아만 두고, 마우스를 떼면 바로 그린다
  let pending = null;
  function applyPending() {
    if (!pending || document.querySelector('.hm-ix.hovering')) return;
    data = pending;
    pending = null;
    renderAll();
  }
  async function poll(force) {
    stamp();   // 시간이 흐르면 '갱신 지연' 표시가 바뀌므로 매번
    if (document.hidden || (!force && !U.busyHours())) return;
    try {
      const d = await fetchHome();
      if (d.built !== data.built) { pending = d; applyPending(); }
    } catch (e) { /* 다음 확인 때 */ }
  }

  U.initTheme($('theme'));
  setInterval(poll, POLL_MS);
  // 다른 창에 있다가 돌아오면 바로 확인 (밤에 켜 둔 화면도 아침에 보면 최신)
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(true); });
  load();
})();
