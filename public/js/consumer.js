// 소비재 탭: data/consumer.json (build_consumer.py) — 화장품·식음료 상장사를 관세청 수출 통계로 본다
// - 업황 카드: 품목 묶음별 전국 월 수출·전년 대비. 누르면 월 차트·국가별·세부 품목·수출 상위 시군구
// - 밸류체인 보드: 분야의 단계(원료 → 용기 → ODM → 브랜드 → 유통 …)마다 종목. 시총·내년 POR·대표 흐름의 3개월 전년비
// - 종목 표와 상세: 수출 흐름(지역×품목 / 전국 묶음), 분기 수출과 분기 매출, 수출로 본 분기 매출 추정(프리뷰), POR 표
// - 급등 탐색: 시군구×품목 수출이 크게 뛴 곳 / 컨콜: DART 기업설명회 공시 + 텔레그램 컨콜 노트(data/consumer_calls.json — 로컬에만 있다)
// 금액은 달러(통관 기준), 분기 비교는 월평균 환율로 바꾼 억원. 주가가 아니라 시총·POR 로 본다.
(() => {
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  const BASIS = { channel: ['채널 근거', '수출입 채널이 이 종목·지역·품목을 짝지어 다뤘다'], hq: ['본사 소재지 · 검수 전', 'DART 본사 주소의 시군구 — 공장이 아닐 수 있다'], national: ['전국 업황', '여러 회사가 섞인 전국 품목 묶음'] };
  const DEFAULTS = { sector: 'all', g: '', s: '', f: '', q: '' };
  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => (typing ? renderTable() : render()));
  const st = pg.state;
  let data = null, calls = null;

  // ---------- 포맷 ----------
  const usd = v => (v == null ? '–' : Math.abs(v) >= 1e8 ? `${(v / 1e8).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억$` : `${Math.round(v / 1e4).toLocaleString('ko-KR')}만$`);
  const pctB = (v, nd = 1) => (v == null ? '<span class="muted">–</span>' : `<b class="${U.cls(v)}">${U.pct(v, nd)}</b>`);
  const ymInt = m => +(m.replace('-', '') + '01');
  const ymLabel = m => `${m.slice(2, 4)}.${m.slice(5, 7)}`;
  const inSector = x => st.sector === 'all' || x.sector === st.sector;
  const opNext = s => s.ops?.find(x => x[0] === s.fy0 + 1)?.[1];
  const porNext = s => (s.mc && opNext(s) > 0 ? s.mc / opNext(s) : null);
  const mainFlow = s => s.flows.find(f => f.id === s.main) || null;

  function spark(v, w = 96, h = 26, cls = '') {
    const xs = v.map((x, i) => [i, x]).filter(p => p[1] != null);
    if (xs.length < 2) return `<svg class="cs-spark" width="${w}" height="${h}"></svg>`;
    const lo = Math.min(...xs.map(p => p[1])), hi = Math.max(...xs.map(p => p[1]));
    const X = i => 1 + i / (v.length - 1) * (w - 2), Y = y => h - 2 - (hi > lo ? (y - lo) / (hi - lo) : 0.5) * (h - 4);
    return `<svg class="cs-spark ${cls}" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${xs.map(p => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ')}"/></svg>`;
  }

  // ---------- 필터 ----------
  function renderFilters() {
    const sectors = Object.keys(data.chains);
    $('filters').innerHTML = `<div class="frow">
      ${pg.seg('sector', [['all', '전체'], ...sectors.map(s => [s, s])])}
      <input type="search" data-q="q" placeholder="종목명·코드 검색" value="${U.esc(st.q)}" autocomplete="off">
      <span class="muted small">수출 통계 ${ymLabel(data.last_ym)}월까지 · 시군구 ${data.sgg_from ? `${ymLabel(data.sgg_from)}~${ymLabel(data.sgg_to)}` : '없음'} · 환율 ${data.fx_last.toLocaleString('ko-KR')}원</span>
    </div>`;
  }

  // ---------- 업황 ----------
  function renderGroups() {
    const gs = data.groups.filter(inSector);
    $('groups').innerHTML = gs.map(g => `<button class="card cs-g${st.g === g.id ? ' on' : ''}" data-g="${g.id}">
        <header><b>${U.esc(g.label)}</b>${g.mixed ? '<span class="pill" title="소비재가 아닌 물량이 많이 섞이는 묶음">혼합</span>' : ''}<small class="muted">${g.sector}</small></header>
        <div class="cs-g-main"><div><small class="muted">${ymLabel(data.last_ym)}월</small><b>${usd(g.usd[g.usd.length - 1])}</b></div>
          <div><small class="muted">전년비</small>${pctB(g.yoy)}</div><div><small class="muted">3개월</small>${pctB(g.yoy3)}</div></div>
        ${spark(g.usd.slice(-24), 220, 34, U.cls(g.yoy3))}
      </button>`).join('');
    renderGroupDetail();
  }

  function renderGroupDetail() {
    const g = data.groups.find(x => x.id === st.g);
    const box = $('group-detail');
    box.hidden = !g;
    if (!g) return;
    const ms = data.months, n = ms.length;
    const yoys = g.usd.map((_, i) => (i >= 12 && g.usd[i] != null && g.usd[i - 12] > 0 ? (g.usd[i] / g.usd[i - 12] - 1) * 100 : null));
    box.innerHTML = `<div class="cs-d-head"><h3>${U.esc(g.label)} <small class="muted">HS ${g.hs6.join(' · ')}${g.note ? ` · ${U.esc(g.note)}` : ''}</small></h3>
        <button class="linkish" data-g="">닫기 ✕</button></div>
      <div class="cs-kpis">
        <div><span>최근 12개월 수출</span><b>${usd(g.usd12)}</b></div>
        <div><span>3개월 전년비 (금액)</span>${pctB(g.yoy3)}</div>
        <div><span>물량 (중량)</span>${pctB(g.kg_yoy3)}</div>
        <div><span>단가 (금액 ÷ 중량)</span>${pctB(g.price_yoy3)}</div>
      </div>
      <div id="g-chart"></div>
      <div class="cs-cols3">
        <div><h4>국가별 <small class="muted">최근 12개월 비중 · 3개월 전년비</small></h4>
          <table class="cs-mini">${g.countries.map(c => `<tr><td>${U.esc(c.n)}</td><td class="num">${c.share != null ? `${(c.share * 100).toFixed(0)}%` : '–'}</td>
            <td class="num">${pctB(c.yoy3, 0)}</td><td>${spark(c.usd.slice(-24), 80, 20, U.cls(c.yoy3))}</td></tr>`).join('') || '<tr><td class="muted">국가별 통계 없음</td></tr>'}</table></div>
        <div><h4>세부 품목 <small class="muted">최근 12개월</small></h4>
          <table class="cs-mini">${g.items.map(i => `<tr><td title="HS ${i.hs}">${U.esc(i.n)}</td><td class="num">${usd(i.usd12)}</td></tr>`).join('')}</table></div>
        <div><h4>수출 상위 시군구 <small class="muted">신고인 소재지 · 12개월</small></h4>
          <table class="cs-mini">${g.sgg.map(x => `<tr><td>${U.esc(x.n)}</td><td class="num">${usd(x.usd12)}</td><td class="num">${pctB(x.yoy3, 0)}</td></tr>`).join('') || '<tr><td class="muted">시군구 통계 없음</td></tr>'}</table></div>
      </div>`;
    Plot.chart($('g-chart'), {
      n, height: 250, uid: 'csg',
      panes: [
        { h: 2.4, fmt: v => usd(v), series: [{ type: 'bar', values: g.usd, cls: i => (yoys[i] == null ? '' : yoys[i] >= 0 ? 'up' : 'dn') }] },
        { h: 1, zero: true, fmt: v => `${Math.round(v)}%`, label: '전년비', series: [{ type: 'line', values: yoys, color: 'var(--text)', width: 1.4 }] },
      ],
      xTicks: Plot.monthTicks(ms.map(ymInt)),
      tip: i => `<div class="tt-h">${ymLabel(ms[i])}</div><div class="tt-v">${usd(g.usd[i])}</div>${yoys[i] != null ? `<div>전년비 <b class="${U.cls(yoys[i])}">${yoys[i] > 0 ? '+' : ''}${yoys[i].toFixed(1)}%</b></div>` : ''}`,
    });
  }

  // ---------- 밸류체인 ----------
  function chipHtml(s) {
    const f = mainFlow(s);
    return `<button class="cs-chip${st.s === s.c ? ' on' : ''}" data-s="${s.c}" title="${U.esc(s.memo || '')}">
      <b>${U.esc(s.n)}</b>
      <span class="muted">${U.eok(s.mc)}${porNext(s) ? ` · POR ${U.mult(porNext(s))}` : ''}</span>
      <span>${f ? `${f.kind === 'national' ? '업황' : '수출'} 3개월 ${pctB(f.yoy3, 0)}` : '<span class="muted">맞는 품목 없음</span>'}
        ${s.preview?.verdict ? `<i class="cs-v ${s.preview.verdict.replace(' ', '')}">${s.preview.verdict}</i>` : ''}</span>
    </button>`;
  }

  function renderChain() {
    const sectors = Object.keys(data.chains).filter(sec => st.sector === 'all' || st.sector === sec);
    $('chain').innerHTML = sectors.map(sec => {
      const stages = data.chains[sec].map(stage => [stage, data.stocks.filter(s => s.sector === sec && s.stage === stage).sort((a, b) => (b.mc || 0) - (a.mc || 0))]).filter(x => x[1].length);
      return `<div class="card cs-chain"><div class="cs-d-head"><h3>${sec} 밸류체인 <small class="muted">단계마다 시총 순 · 숫자는 대표 수출 흐름의 최근 3개월 전년비</small></h3></div>
        <div class="cs-stages" style="--n:${stages.length}">${stages.map(([stage, ss]) => `<div class="cs-stage"><h4>${stage} <small class="muted">${ss.length}</small></h4>${ss.map(chipHtml).join('')}</div>`).join('')}</div></div>`;
    }).join('');
  }

  // ---------- 종목 표 ----------
  const verdictHtml = p => (!p ? '<span class="muted">–</span>' : p.verdict ? `<i class="cs-v ${p.verdict.replace(' ', '')}">${p.verdict}</i> <small class="${U.cls(p.diff)}">${U.pct(p.diff, 0)}</small>`
    : `<small class="muted" title="지난 분기 되맞춤 오차가 커서 판정은 내지 않는다">추정 ${U.eok(p.est)} · 참고</small>`);

  function renderTable() {
    const q = st.q.trim().toLowerCase();
    const list = data.stocks.filter(s => inSector(s) && (!q || s.n.toLowerCase().includes(q) || s.c.includes(q)));
    $('table').innerHTML = `<div class="tbl-wrap card"><div class="col-head"><h3>종목 <span class="muted">${list.length}개 · 열 제목을 누르면 정렬 · 줄을 누르면 아래에 상세</span></h3></div>
      <table class="tbl cs-tbl"><thead><tr><th>종목</th><th>단계</th><th class="num">시총</th><th class="num">내년 POR</th><th>대표 흐름</th>
        <th class="num">${ymLabel(data.last_ym)}월 전년비</th><th class="num">3개월 전년비</th><th class="nosort">24개월</th>
        <th class="num" title="분기 수출 전년비와 분기 매출 전년비의 상관 (최근 12분기)">매출 상관 r</th>
        <th class="num" title="최근 4분기 수출(원화 환산) ÷ 매출">수출÷매출</th><th title="수출로 본 이번 분기 매출 추정 vs 컨센서스">프리뷰</th><th class="num">컨콜·탐방</th></tr></thead>
      <tbody>${list.map(s => {
        const f = mainFlow(s);
        return `<tr data-s="${s.c}" class="${st.s === s.c ? 'on' : ''}" ${Stock.hintAttr(s)}>
          <td class="name-cell">${Stock.link(s)}${s.reviewed ? '' : ' <small class="muted" title="흐름 매핑을 아직 검수하지 않았다">초안</small>'}</td>
          <td class="muted">${s.stage}</td><td class="num" data-v="${s.mc ?? ''}">${U.eok(s.mc)}</td><td class="num" data-v="${porNext(s) ?? ''}">${porNext(s) ? U.mult(porNext(s)) : '–'}</td>
          <td>${f ? `${U.esc(f.label)} <small class="muted">${BASIS[f.basis][0]}</small>` : '<span class="muted">–</span>'}</td>
          <td class="num" data-v="${f?.yoy ?? ''}">${pctB(f?.yoy)}</td><td class="num" data-v="${f?.yoy3 ?? ''}">${pctB(f?.yoy3)}</td>
          <td>${f ? spark(f.usd.slice(-24), 90, 22, U.cls(f.yoy3)) : ''}</td>
          <td class="num" data-v="${f?.r ?? ''}">${f?.r != null ? `<b class="${f.ok ? 'up' : ''}">${f.r.toFixed(2)}</b> <small class="muted">${f.nq}분기${f.ok ? ' ✓' : ''}</small>` : '<span class="muted">–</span>'}</td>
          <td class="num" data-v="${f?.cover ?? ''}">${f?.cover != null && f.kind === 'sigungu' ? `${(f.cover * 100).toFixed(0)}%` : '<span class="muted">–</span>'}</td>
          <td>${verdictHtml(s.preview)}</td>
          <td class="num" data-v="${(s.calls?.n || 0) + (s.visits?.n || 0)}">${s.calls?.n ? `컨콜 ${s.calls.n}` : ''}${s.calls?.n && s.visits?.n ? ' · ' : ''}${s.visits?.n ? `탐방 ${s.visits.n}` : ''}</td></tr>`;
      }).join('')}</tbody></table></div>`;
  }

  // ---------- 종목 상세 ----------
  function renderDetail() {
    const s = data.stocks.find(x => x.c === st.s);
    const box = $('detail');
    box.hidden = !s;
    if (!s) return;
    const f = s.flows.find(x => x.id === st.f) || mainFlow(s);
    const p = s.preview;
    const notes = calls?.calls?.[s.c] || [];
    const irs = data.ir.filter(x => x.c === s.c);
    box.innerHTML = `<div class="cs-d-head"><h3>${Stock.link(s)} <small class="muted">${s.c} · ${MARKETS[s.mk] || ''} · ${s.sector} ${s.stage} · 시총 ${U.eok(s.mc)}</small></h3>
        <button class="linkish" data-s="">닫기 ✕</button></div>
      ${s.memo ? `<p class="cs-memo">${U.esc(s.memo)}</p>` : ''}
      <div class="cs-two">
        <div>${U.porTable(s.mc, s) || '<p class="muted small">영업이익 컨센서스가 없어 POR 을 계산하지 못합니다.</p>'}
          ${p ? `<div class="cs-prev"><b>수출로 본 ${p.q} 매출 추정 ${U.eok(p.est)}</b>${p.cns ? ` · 컨센서스 ${U.eok(p.cns)} 대비 ${pctB(p.diff)} ${p.verdict ? `<i class="cs-v ${p.verdict.replace(' ', '')}">${p.verdict}</i>` : ''}` : ' · 분기 컨센서스 없음'}
            <small class="muted">전년 같은 분기 매출 × (수출 전년비로 본 매출 전년비). 지난 ${p.n}개 분기로 맞춤(R² ${p.r2.toFixed(2)})${p.mae != null ? `, 지난 분기 평균 오차 ${(p.mae * 100).toFixed(0)}%` : ''}.
              ${p.cns && !p.verdict ? `오차가 ${data.mae_ok * 100}% 를 넘어 BEAT·MISS 판정은 내지 않습니다. ` : ''}어림값이며 매매 권유가 아닙니다.</small></div>` : ''}
          ${s.past?.length ? `<p class="small cs-past"><span class="muted">같은 방법으로 지난 분기를 다시 맞춰 보면 (추정 ÷ 실제 − 1):</span> ${s.past.map(h => `${h.q.slice(2)} <b class="${U.cls(h.err)}">${U.pct(h.err, 0)}</b>`).join(' · ')}</p>` : ''}
        </div>
        <div><h4>분기 수출 vs 매출 <small class="muted">억원 · 대표 흐름 기준</small></h4><div id="q-chart"></div></div>
      </div>
      <h4>수출 흐름 <small class="muted">누르면 아래 차트가 바뀝니다</small></h4>
      <div class="cs-flows">${s.flows.map(x => `<button class="cs-flow${f && x.id === f.id ? ' on' : ''}" data-f="${x.id}">
        <b>${U.esc(x.label)}</b><span class="pill" title="${BASIS[x.basis][1]}">${BASIS[x.basis][0]}</span>
        <span>3개월 ${pctB(x.yoy3, 0)} · 매출 상관 ${x.r != null ? `<b>${x.r.toFixed(2)}</b>` : '<span class="muted">–</span>'}${x.cover != null && x.kind === 'sigungu' ? ` · 수출÷매출 ${(x.cover * 100).toFixed(0)}%` : ''}${x.ok ? ' · <b class="up">회사 수출로 확인 ✓</b>' : ''}</span>
      </button>`).join('') || '<p class="muted small">품목 사전과 맞는 수출 흐름이 없습니다.</p>'}</div>
      <div id="f-chart"></div>
      <div class="cs-cols3">
        <div><h4>기업설명회 공시 <small class="muted">DART, 최근 60일</small></h4>${irs.length ? irs.map(x => `<p class="small"><span class="muted">${U.md(x.d)}</span> <a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${x.no}" target="_blank" rel="noopener">${U.esc(x.t)} ↗</a></p>`).join('') : '<p class="muted small">없음</p>'}</div>
        <div class="cs-span2"><h4>컨콜 노트 <small class="muted">텔레그램 · ${notes.length}건${calls ? '' : ' (이 화면에서는 볼 수 없음)'}</small>${s.visits?.n ? ` <a class="small" href="visit.html?per=all&q=${encodeURIComponent(s.n)}">탐방 노트 ${s.visits.n}건 →</a>` : ''}</h4>
          ${notes.map(n => `<details class="cs-call"><summary><span class="muted">${U.md(n.d)}</span> <b>${U.esc(n.t)}</b> <small class="muted">${n.rooms.map(U.esc).join(' · ')}</small></summary>
            ${n.lines.length ? `<ul class="vs-lines">${n.lines.map(l => `<li>${U.num(l)}</li>`).join('')}</ul>` : ''}
            <pre class="vs-text">${U.esc(n.x)}</pre>${n.link ? `<a class="small muted" href="${U.esc(n.link)}" target="_blank" rel="noopener">텔레그램에서 열기 ↗</a>` : ''}</details>`).join('') || '<p class="muted small">없음</p>'}</div>
      </div>`;
    if (f) {
      const ms = data.months;
      const yoys = f.usd.map((_, i) => (i >= 12 && f.usd[i] != null && f.usd[i - 12] > 0 ? (f.usd[i] / f.usd[i - 12] - 1) * 100 : null));
      Plot.chart($('f-chart'), {
        n: ms.length, height: 240, uid: 'csf', has: i => f.usd[i] != null,
        panes: [{ h: 2.4, fmt: v => usd(v), series: [{ type: 'bar', values: f.usd, cls: i => (yoys[i] == null ? '' : yoys[i] >= 0 ? 'up' : 'dn') }] },
          { h: 1, zero: true, fmt: v => `${Math.round(v)}%`, label: '전년비', series: [{ type: 'line', values: yoys, color: 'var(--text)', width: 1.4 }] }],
        xTicks: Plot.monthTicks(ms.map(ymInt)),
        tip: i => `<div class="tt-h">${ymLabel(ms[i])} · ${U.esc(f.label)}</div><div class="tt-v">${usd(f.usd[i])}</div>${yoys[i] != null ? `<div>전년비 <b class="${U.cls(yoys[i])}">${yoys[i] > 0 ? '+' : ''}${yoys[i].toFixed(1)}%</b></div>` : ''}`,
      });
    }
    const qs = s.q.filter(x => x.rev != null || x.exp != null);
    if (qs.length) {
      Plot.chart($('q-chart'), {
        n: qs.length, height: 200, uid: 'csq',
        panes: [{ h: 1, fmt: v => U.eok(v), series: [{ type: 'bar', values: qs.map(x => x.rev) },
          { type: 'line', values: qs.map(x => x.exp), color: 'var(--accent)', width: 1.8 }] }],
        xTicks: qs.map((x, i) => [i, x.q.slice(2).replace('Q', '.')]).filter((_, i) => i % 2 === 0),
        tip: i => `<div class="tt-h">${qs[i].q}</div><div class="tt-g"><span>매출</span><b>${U.eok(qs[i].rev)}</b><span>수출</span><b>${U.eok(qs[i].exp)}</b></div>`,
      });
    } else $('q-chart').innerHTML = '<p class="muted small">분기 매출 자료 없음</p>';
  }

  // ---------- 급등 탐색 · 컨콜 ----------
  function renderSurge() {
    const rows = data.surge.filter(x => st.sector === 'all' || data.groups.find(g => g.id === x.g)?.sector === st.sector);
    $('surge').innerHTML = `<div class="tbl-wrap card"><div class="col-head"><h3>급등 탐색 <span class="muted">시군구 × 품목, 최근 3개월 수출이 전년보다 50% 넘게 늘고 200만 달러 이상인 곳 · 늘어난 금액 순</span></h3></div>
      <table class="tbl"><thead><tr><th>품목</th><th>시군구 (신고인 소재지)</th><th class="num">3개월 수출</th><th class="num">전년비</th><th class="num">늘어난 금액</th><th class="nosort">24개월</th><th>매핑된 종목</th></tr></thead>
      <tbody>${rows.map(x => `<tr><td>${U.esc(x.label)} <small class="muted">${x.hs6}</small></td><td>${U.esc(x.sgg)}</td><td class="num" data-v="${x.usd3}">${usd(x.usd3)}</td>
        <td class="num" data-v="${x.yoy3}">${pctB(x.yoy3, 0)}</td><td class="num" data-v="${x.inc}">${usd(x.inc)}</td><td>${spark(x.spark, 90, 22, 'up')}</td>
        <td>${x.stocks.length ? x.stocks.map(U.esc).join(', ') : '<span class="muted">미매핑</span>'}</td></tr>`).join('') || '<tr><td colspan="7" class="muted empty">해당 없음</td></tr>'}</tbody></table></div>`;
  }

  function renderCalls() {
    const ok = c => { const s = data.stocks.find(x => x.c === c); return s && inSector(s); };
    const irs = data.ir.filter(x => ok(x.c)).slice(0, 14);
    const all = calls ? Object.entries(calls.calls).filter(([c]) => ok(c)).flatMap(([c, ns]) => ns.map(n => ({ ...n, c, n: data.stocks.find(s => s.c === c).n })))
      .sort((a, b) => (a.d < b.d ? 1 : a.d > b.d ? -1 : 0)).slice(0, 16) : [];
    $('calls').innerHTML = `<div class="card cs-chain"><div class="cs-d-head"><h3>컨콜 · 기업설명회 <small class="muted">종목 줄을 누르면 종목별로 모아 봅니다</small></h3></div>
      <div class="cs-cols3">
        <div><h4>기업설명회 공시 <small class="muted">DART 최근 60일</small></h4>${irs.map(x => `<p class="small"><span class="muted">${U.md(x.d)}</span> <button class="linkish cs-pick" data-s="${x.c}">${U.esc(x.n)}</button>
          <a class="muted" href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${x.no}" target="_blank" rel="noopener">공시 ↗</a></p>`).join('') || '<p class="muted small">없음</p>'}</div>
        <div class="cs-span2"><h4>최근 컨콜 노트 <small class="muted">텔레그램에서 모은 글${calls ? '' : ' — 이 화면(공개 사이트)에는 싣지 않습니다'}</small></h4>
          ${all.map(n => `<p class="small"><span class="muted">${U.md(n.d)}</span> <button class="linkish cs-pick" data-s="${n.c}">${U.esc(n.n)}</button> ${U.esc(n.t)} <span class="muted">${U.esc(n.rooms[0] || '')}</span></p>`).join('') || '<p class="muted small">없음</p>'}</div>
      </div></div>`;
  }

  function render() {
    renderFilters();
    renderGroups();
    renderChain();
    renderTable();
    renderDetail();
    renderSurge();
    renderCalls();
    $('asof').textContent = `${U.timeLabel(data.built_at)} 정리`;
    $('foot').innerHTML = `<p><b>읽는 법</b> · 수출은 관세청 통관 기준(달러)입니다. 전국 통계는 품목(HS 10단위)·국가·중량까지, 시군구 통계는 품목(HS 6단위) 금액만 나옵니다.
        시군구는 수출 신고인의 소재지라 공장이 아니라 본사·물류센터·무역상 주소로 잡히기도 하고, 한 시군구에 여러 회사가 섞입니다. 해외 공장에서 만들어 파는 매출은 한국 수출에 잡히지 않습니다.</p>
      <p>흐름의 근거: <b>채널 근거</b> = 수출입 채널이 그 종목·지역·품목을 함께 다룬 기록, <b>본사 소재지</b> = DART 본사 주소(검수 전 초안), <b>전국 업황</b> = 회사가 아니라 품목 전체.
        매출 상관 r 은 분기 수출 전년비와 분기 매출 전년비의 상관입니다. r 이 ${data.r_ok} 이상이고 최근 4분기 수출이 매출의 ${data.cover_min * 100}~${data.cover_max * 100}% 인 지역 흐름만 '회사 수출로 확인(✓)'으로 보고 프리뷰를 냅니다
        (상관만 높고 매출의 1~2%인 흐름, 수출이 매출보다 훨씬 큰 흐름은 다른 회사 물량이거나 우연입니다). 프리뷰는 지난 분기 되맞춤 오차가 ${data.mae_ok * 100}% 이하일 때만 컨센서스 대비 ±${data.band * 100}% 로 BEAT·MISS 를 냅니다.</p>
      <p class="muted">출처: 관세청 수출입무역통계(공공데이터포털), DART, FnGuide 컨센서스(네이버 종목분석). 매달 15일경 전월 확정치가 올라옵니다. 품목 단위 10일 속보는 없습니다. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  }

  document.querySelector('main').addEventListener('click', e => {
    if (e.target.closest('a')) return;
    const g = e.target.closest('[data-g]');
    if (g) return pg.set({ g: st.g === g.dataset.g ? '' : g.dataset.g });
    const f = e.target.closest('[data-f]');
    if (f) { st.f = f.dataset.f; pg.write(); return renderDetail(); }
    const s = e.target.closest('[data-s]');
    if (s) {
      pg.set({ s: st.s === s.dataset.s ? '' : s.dataset.s, f: '' });
      if (st.s) $('detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  pg.bind($('filters'));
  U.initTheme($('theme'));

  (async () => {
    try {
      data = await U.json('data/consumer.json');
    } catch (e) {
      $('msg').textContent = '소비재 데이터가 아직 없습니다. python3 collect_trade.py && python3 build_consumer.py';
      return;
    }
    try { calls = await U.json('data/consumer_calls.json'); } catch (e) { calls = null; }
    $('msg').hidden = true;
    render();
  })();
})();
