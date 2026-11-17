// 소비재 탭: data/consumer.json (build_consumer.py) — 화장품·식음료·미용 의료(의료기기) 상장사를 관세청 수출 통계로 본다
// - 요점: 강한·약한 품목, 국가별 큰 변화, 수출은 느는데 시총은 빠진 종목(또는 반대), 프리뷰 판정을 규칙으로 뽑은 한 줄들
// - 품목 × 국가 표: 최근 3개월 전년비를 색으로 (칸 아래 작은 글씨는 그 나라 비중)
// - 업황 카드: 품목 묶음별 전국 월 수출·전년 대비. 누르면 월 차트·국가별·세부 품목·수출 상위 시군구
// - 밸류체인 보드: 분야의 단계(원료 → 용기 → ODM → 브랜드 → 유통 …)마다 종목. 시총·내년 POR·대표 흐름의 3개월 전년비
// - 종목 표와 상세: 수출 흐름(지역×품목 / 전국 묶음), 분기 수출과 분기 매출, 수출로 본 분기 매출 추정(프리뷰), POR 표
// - 급등 탐색: 시군구×품목 수출이 크게 뛴 곳 / 컨콜: DART 기업설명회 공시 + 텔레그램 컨콜 노트(data/consumer_calls.json —
//   공개 사이트에는 1:1 대화를 빼고 공개 채널 글은 제목·링크만 실은 사본이 올라간다)
// 금액은 달러(통관 기준), 분기 비교는 월평균 환율로 바꾼 억원. 주가가 아니라 시총·POR 로 본다.
(() => {
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  const BASIS = { channel: ['채널 근거', '수출입 채널이 이 종목·지역·품목을 짝지어 다뤘다'], hq: ['본사 소재지', 'DART 본사 주소의 시군구 — 공장이 아닐 수 있다'], national: ['전국 업황', '여러 회사가 섞인 전국 품목 묶음'],
    factory: ['공장 소재지', 'DART 사업보고서의 생산·물류 사업장이 있는 시군구 — 같은 지역의 다른 회사 물량이 섞일 수 있다'],
    scan: ['자동 탐색 후보', '이 종목의 분기 매출과 같이 움직인 수출 지역을 자동으로 찾은 것 — 같은 업황이라 우연히 맞았을 수 있다'] };
  const HEAT = [['US', '미국'], ['CN', '중국'], ['JP', '일본'], ['HK', '홍콩'], ['VN', '베트남'], ['TW', '대만'], ['RU', '러시아'], ['AE', 'UAE'], ['EU', 'EU 6국']];
  const SHOWS = [['all', '전체'], ['ok', '수출 연동 ✓', '회사 수출로 확인된 지역 흐름이 있는 종목'], ['flow', '지역 흐름 있는 종목', '대표 흐름이 회사 지역 흐름인 종목'], ['prev', '프리뷰 있는 종목'], ['gap', '수출↑ 시총↓', '회사 지역 흐름(매출의 10% 이상)의 3개월 전년비가 +15% 이상인데 시총은 3개월 -10% 이하'], ['notes', '컨콜·탐방 있는 종목']];
  const DEFAULTS = { sector: 'all', g: '', s: '', f: '', q: '', show: 'all', wv: 'm', tg: '', tr: '104', im: 'eu' };
  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => (typing ? renderTable() : render()));
  const st = pg.state;
  let data = null, calls = null, trends = null, alt = null;

  // ---------- 포맷 ----------
  const usd = v => (v == null ? '–' : Math.abs(v) >= 1e8 ? `${(v / 1e8).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억$` : `${Math.round(v / 1e4).toLocaleString('ko-KR')}만$`);
  const pctB = (v, nd = 1) => (v == null ? '<span class="muted">–</span>' : `<b class="${U.cls(v)}">${U.pct(v, nd)}</b>`);
  const ymInt = m => +(m.replace('-', '') + '01');
  const ymLabel = m => `${m.slice(2, 4)}.${m.slice(5, 7)}`;
  const inSector = x => st.sector === 'all' || x.sector === st.sector;
  const opNext = s => s.ops?.find(x => x[0] === s.fy0 + 1)?.[1];
  const porNext = s => (s.mc && opNext(s) > 0 ? s.mc / opNext(s) : null);
  const mainFlow = s => s.flows.find(f => f.id === s.main) || null;
  const own = s => { const f = mainFlow(s); return f && f.kind === 'sigungu'; };          // 대표 흐름이 회사 지역 흐름인가
  const FIT = { ok: ['수출 연동 ✓'], loose: ['따로 논다'], short: ['판정 보류'], small: ['수출 작음'], mixed: ['지역 혼합'], none: ['업황만'] };
  const fitTag = s => (s.fit ? `<span class="cs-fit ${s.fit.k}" title="${U.esc(s.fit.why)}">${FIT[s.fit.k][0]}</span>` : '');
  // 수출↑ 시총↓: 회사 지역 흐름(매출의 10% 이상을 설명하는 것만 — 아주 작은 흐름의 +900% 같은 숫자는 뺀다)이 늘었는데 시총은 빠진 종목
  const solid = s => { const f = mainFlow(s); return own(s) && f.cover != null && f.cover >= data.cover_min && f.yoy3 != null && s.ret3 != null; };
  const gap = s => solid(s) && mainFlow(s).yoy3 >= 0.15 && s.ret3 <= -0.10;
  const median = v => { const a = v.filter(x => x != null).sort((x, y) => x - y); return a.length ? a[Math.floor(a.length / 2)] : null; };
  const pick = (c, label) => `<button class="linkish cs-pick" data-s="${c}">${U.esc(label)}</button>`;

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

  // ---------- 요점 ----------
  function renderBrief() {
    const gs = data.groups.filter(g => inSector(g) && !g.mixed && g.usd12 >= 5e7 && g.yoy3 != null).sort((a, b) => b.yoy3 - a.yoy3);
    const ss = data.stocks.filter(inSector);
    const g1 = x => `<button class="linkish cs-pick" data-g="${x.id}">${U.esc(x.label)}</button> ${pctB(x.yoy3, 0)}`;
    const moves = data.groups.filter(g => inSector(g) && !g.mixed).flatMap(g => Object.entries(g.heat || {})
      .filter(([c, v]) => v[0] != null && v[1] >= 0.08 && c !== 'EU').map(([c, v]) => ({ g, c, y: v[0], w: v[1] })))
      .sort((a, b) => Math.abs(b.y) * b.w * b.g.usd12 - Math.abs(a.y) * a.w * a.g.usd12).slice(0, 5);
    const cname = c => (HEAT.find(h => h[0] === c) || [c, c])[1];
    const up = ss.filter(gap).sort((a, b) => a.ret3 - b.ret3).slice(0, 5);
    const dn = ss.filter(s => solid(s) && mainFlow(s).yoy3 <= -0.10 && s.ret3 >= 0.10).slice(0, 4);
    // 분야 전체: 혼합 묶음을 뺀 수출 합의 3개월 전년비와 종목 시총 3개월 변화의 중앙값
    const secs = Object.keys(data.chains).filter(sec => st.sector === 'all' || st.sector === sec).map(sec => {
      const g = data.groups.filter(x => x.sector === sec && !x.mixed);
      const n = data.months.length;
      const sum = (a, b) => g.reduce((t, x) => t + x.usd.slice(a, b).reduce((u, v) => u + (v || 0), 0), 0);
      const y = sum(n - 15, n - 12) > 0 ? sum(n - 3, n) / sum(n - 15, n - 12) - 1 : null;
      return `${sec} <span class="muted">수출</span> ${pctB(y, 0)} <span class="muted">· 종목 시총 중앙값</span> ${pctB(median(data.stocks.filter(s => s.sector === sec).map(s => s.ret3)), 0)}`;
    });
    const pv = ss.filter(s => s.preview);
    const sv = s => `${pick(s.c, s.n)} <span class="muted">${own(s) ? '수출' : '업황'}</span> ${pctB(mainFlow(s).yoy3, 0)} <span class="muted">· 시총</span> ${pctB(s.ret3, 0)}`;
    const rows = [
      ['분야', secs.join(' · ')],
      gs.length ? ['강한 품목', gs.slice(0, 4).map(g1).join(' · ')] : null,
      gs.length > 4 ? ['약한 품목', gs.slice(-3).reverse().map(g1).join(' · ')] : null,
      moves.length ? ['국가', moves.map(m => `${U.esc(m.g.label)} → ${cname(m.c)} ${pctB(m.y, 0)}`).join(' · ')] : null,
      up.length ? ['수출↑ 시총↓', `${up.map(sv).join(' · ')} <span class="muted small">(회사 지역 흐름이 매출의 ${data.cover_min * 100}% 이상인 종목만 · 시총은 3개월 변화)</span>`] : null,
      dn.length ? ['수출↓ 시총↑', dn.map(sv).join(' · ')] : null,
      pv.length ? ['프리뷰', pv.map(s => `${pick(s.c, s.n)} ${s.preview.q.slice(2)} 추정 ${U.eok(s.preview.est)}${s.preview.cns ? ` <span class="muted">(컨센 대비</span> ${pctB(s.preview.diff, 0)}<span class="muted">)</span>` : ''} ${s.preview.verdict ? `<i class="cs-v ${s.preview.verdict.replace(' ', '')}">${s.preview.verdict}</i>` : ''}`).join(' · ')] : null,
    ].filter(Boolean);
    $('brief').innerHTML = `<div class="card cs-brief"><h3>${ymLabel(data.last_ym)}월 요점 <small class="muted">숫자는 최근 3개월 전년비 · 규칙으로 뽑은 것이라 해석은 붙이지 않습니다</small></h3>
      <dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl></div>`;
  }

  // ---------- 월간 확정치 (관심 품목 × 회사 지역) ----------
  // export_watch.py 가 만든 표. 같은 내용이 확정치가 들어온 날 텔레그램으로 간다
  function bars(v, w = 104, h = 24) {
    const xs = v.map(x => (x == null ? 0 : x)), hi = Math.max(...xs, 1), bw = w / xs.length;
    return `<svg class="cs-bars" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${xs.map((x, i) =>
      `<rect x="${(i * bw + 0.5).toFixed(1)}" y="${(h - x / hi * h).toFixed(1)}" width="${(bw - 1).toFixed(1)}" height="${(x / hi * h).toFixed(1)}"${i === xs.length - 1 ? ' class="last"' : ''}/>`).join('')}</svg>`;
  }
  function renderWatch() {
    const w = data.watch;
    if (!w || !w.cats?.length) { $('watch').innerHTML = ''; return; }
    if (st.sector !== 'all' && st.sector !== '미용 의료·의료기기' && st.sector !== '화장품') { $('watch').innerHTML = ''; return; }
    const musd = v => (v == null ? '–' : `${(v / 1e6).toLocaleString('ko-KR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })}`);
    const who = it => {
      const s = it.c && data.stocks.find(x => x.c === it.c);
      const name = it.c ? (s ? pick(it.c, it.n) : `${Stock.link({ c: it.c, n: it.n })}`) : `${U.esc(it.n)} <small class="muted">비상장</small>`;
      const por = s ? porNext(s) : null;
      return `${name}${it.mc ? ` <small class="muted">시총 ${U.eok(it.mc)}${por ? ` · POR ${por.toFixed(1)}배` : ''}</small>` : ''}`;
    };
    const q0 = w.cats[0].items[0].q;                       // 분기 열 (모든 줄이 같은 달까지라 첫 줄 기준)
    const qcols = q0.slice(0, 5);
    const head = st.wv === 'q'
      ? `<th>품목</th><th>회사</th><th>지역</th>${qcols.map(q => `<th class="num">${q.qtd ? `${q.q} QTD<br><small class="muted">${q.nm}개월</small>` : q.q}</th>`).join('')}<th class="nosort">8분기</th>`
      : `<th>품목</th><th>회사</th><th>지역</th><th class="num">${ymLabel(w.last_ym)}월<br><small class="muted">백만$</small></th><th class="num">YoY</th><th class="num">MoM</th><th class="nosort">13개월</th>`;
    const row = (c, it, first) => {
      const lead = `<td>${first ? `<b>${U.esc(c.name)}</b> <small class="muted">HS ${c.hs6.join('·')}</small>` : ''}</td><td>${who(it)}</td><td>${U.esc(it.label)}</td>`;
      if (st.wv === 'q') {
        const cells = qcols.map((_, i) => { const q = it.q[i]; return q ? `<td class="num" data-v="${q.v}">${musd(q.v)}<br><small>${pctB(q.yoy, 0)}${q.qoq != null ? ` <span class="muted">QoQ</span> ${pctB(q.qoq, 0)}` : ''}</small></td>` : '<td class="num muted">–</td>'; }).join('');
        return `<tr>${lead}${cells}<td>${bars(it.q.filter(q => !q.qtd).slice(0, 8).reverse().map(q => q.v))}</td></tr>`;
      }
      return `<tr>${lead}<td class="num" data-v="${it.usd ?? ''}"><b>${musd(it.usd)}</b></td><td class="num" data-v="${it.yoy ?? ''}">${pctB(it.yoy)}</td><td class="num" data-v="${it.mom ?? ''}">${pctB(it.mom)}</td><td>${bars(it.m)}</td></tr>`;
    };
    $('watch').innerHTML = `<details class="card cs-chain" id="watch-card" open><summary class="cs-d-head"><h3>월간 수출 확정치 <small class="muted">${ymLabel(w.last_ym)}월 · 관심 품목 × 회사 공장·신고 지역(시군구 × HS6) · 확정치가 들어온 날 텔레그램으로도 보냅니다</small></h3></summary>
      <div class="col-head">${pg.seg('wv', [['m', '월별'], ['q', '분기별', 'QTD 는 들어온 달까지, 전년비는 작년 같은 달들과 비교']])}</div>
      <div class="tbl-wrap"><table class="tbl cs-watch" data-nosort><thead><tr>${head}</tr></thead>
      <tbody>${w.cats.map(c => c.items.map((it, i) => row(c, it, i === 0)).join('')).join('')}</tbody></table></div>
      <p class="muted small">시군구는 수출 신고인 소재지라 같은 지역의 다른 회사 물량이 섞일 수 있습니다(예: 강남구 미용기기·체성분 분석기). 품목·지역 짝은 <code>export_watch.json</code>.</p></details>`;
  }

  // ---------- EU 수입: 한국 vs 중국 (eu_trade.py, Eurostat 원산지 기준) ----------
  function euChart(e, n = 36) {
    const ms = e.months.slice(-n), kr = e.kr.slice(-n), cn = e.cn.slice(-n);
    const W = 640, H = 170, P = 30, hi = Math.max(...kr, ...cn, 1);
    const X = i => P + i / (ms.length - 1) * (W - P - 8), Y = v => H - 18 - v / hi * (H - 30);
    const line = (v, cls) => `<polyline class="${cls}" points="${v.map((x, i) => (x == null ? '' : `${X(i).toFixed(1)},${Y(x).toFixed(1)}`)).filter(Boolean).join(' ')}"/>`;
    const ticks = ms.map((m, i) => (m.endsWith('-01') ? `<text x="${X(i).toFixed(1)}" y="${H - 4}" text-anchor="middle">${m.slice(0, 4)}</text><line class="eu-grid" x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="8" y2="${H - 18}"/>` : '')).join('');
    const ylab = [0.5, 1].map(f => `<text x="2" y="${(Y(hi * f) + 4).toFixed(1)}">${e.cur || '€'}${Math.round(hi * f / 1e6)}M</text>`).join('');
    return `<svg class="eu-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${ticks}${ylab}${line(cn, 'cn')}${line(kr, 'kr')}</svg>`;
  }
  function renderEU() {
    const us = st.im === 'us' && data.us, e = us ? data.us : data.eu;
    if (!e || (st.sector !== 'all' && st.sector !== '화장품')) { $('eu').innerHTML = ''; return; }
    const ext = e.ext_label || '역외 전체', mk = us ? '미국' : 'EU';
    const n = e.months.length, s3 = (v, end = n) => { const xs = v.slice(end - 3, end); return xs.length === 3 && xs.every(x => x != null) ? xs.reduce((a, b) => a + b, 0) : null; };
    const r = (a, b) => (a == null || !b ? null : a / b - 1);
    const eur = v => (v == null ? '–' : `${e.cur || '€'}${(v / 1e6).toLocaleString('ko-KR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })}M`);
    const pp = v => (v == null ? '–' : `${(v * 100).toFixed(1)}%`);
    const kr3 = s3(e.kr), cn3 = s3(e.cn), ext3 = s3(e.ext), krp = s3(e.kr, n - 12), cnp = s3(e.cn, n - 12), extp = s3(e.ext, n - 12);
    const up = (v, kg) => { const a = s3(v), b = s3(kg); return a && b ? a / b : null; };
    const kp = up(e.kr, e.kr_kg), cp = up(e.cn, e.cn_kg);
    const b3p = krp;                                      // 기여도 분모: 작년 같은 3개월 한국 바스켓
    const hsRows = e.hs.map(h => ({ ...h, k3: s3(h.kr), kp: s3(h.kr, n - 12), c3: s3(h.cn), cpv: s3(h.cn, n - 12) }))
      .map(h => ({ ...h, contrib: h.k3 != null && h.kp != null && b3p ? (h.k3 - h.kp) / b3p : null }))
      .sort((a, b) => (b.k3 || 0) - (a.k3 || 0));
    const tox3 = s3(e.tox.kr), toxp = s3(e.tox.kr, n - 12);
    const lm = ymLabel(e.last_ym);
    $('eu').innerHTML = `<details class="card cs-chain" open><summary class="cs-d-head"><h3>${mk} 화장품 수입 — 한국 vs 중국 <small class="muted">${e.src || 'Eurostat Comext'} · 원산지 기준 · ${lm}월까지 · 바스켓 ${e.hs.length}개 HS6 · 숫자는 최근 3개월</small></h3></summary>
      ${data.us ? `<div class="col-head">${pg.seg('im', [['eu', 'EU'], ['us', '미국']])}</div>` : ''}
      <div class="eu-top">
        <dl class="eu-kpi">
          <dt><i class="eu-dot kr"></i>한국산</dt><dd><b>${eur(kr3)}</b> ${pctB(r(kr3, krp))} <span class="muted">· ${ext} 수입 중</span> ${pp(kr3 / ext3)} <span class="muted">(작년 ${pp(krp / extp)})</span> <span class="muted">· 단가</span> ${e.cur || '€'}${kp ? kp.toFixed(1) : '–'}/kg</dd>
          <dt><i class="eu-dot cn"></i>중국산</dt><dd><b>${eur(cn3)}</b> ${pctB(r(cn3, cnp))} <span class="muted">· ${ext} 수입 중</span> ${pp(cn3 / ext3)} <span class="muted">(작년 ${pp(cnp / extp)})</span> <span class="muted">· 단가</span> ${e.cur || '€'}${cp ? cp.toFixed(1) : '–'}/kg</dd>
          <dt>${ext}</dt><dd>${eur(ext3)} ${pctB(r(ext3, extp))}${(e.oth || []).map(([lb, v]) => ` <span class="muted">· ${lb}</span> ${eur(s3(v))} ${pctB(r(s3(v), s3(v, n - 12)))}`).join('')}</dd>
          <dt>톡신(300249)</dt><dd>한국산 ${eur(tox3)} ${pctB(r(tox3, toxp))} <span class="muted">· ${ext} 톡신 중</span> ${pp(tox3 && s3(e.tox.ext) ? tox3 / s3(e.tox.ext) : null)}</dd>
        </dl>
        ${euChart(e)}
      </div>
      <div class="eu-tables${e.rep.length ? '' : ' one'}">
        ${e.rep.length ? `<div class="tbl-wrap"><table class="tbl" data-nosort><thead><tr><th>보고국</th><th class="num">한국산</th><th class="num">전년비</th><th class="num">점유율</th><th class="num">중국산</th><th class="num">전년비</th><th class="num">점유율</th></tr></thead>
          <tbody>${e.rep.map(x => `<tr><td>${x.name}</td><td class="num">${eur(x.kr3)}</td><td class="num">${pctB(x.kr_yoy3, 0)}</td><td class="num">${pp(x.kr_sh3)}</td><td class="num">${eur(x.cn3)}</td><td class="num">${pctB(x.cn_yoy3, 0)}</td><td class="num">${pp(x.cn_sh3)}</td></tr>`).join('')}</tbody></table></div>` : ''}
        <div class="tbl-wrap"><table class="tbl" data-nosort><thead><tr><th>HS (${us ? '미국' : 'EU 27'})</th><th class="num">한국산</th><th class="num">전년비</th><th class="num" title="(올해 − 작년) ÷ 작년 한국 바스켓 — 다 더하면 바스켓 전년비">기여도</th><th class="num">중국산</th><th class="num">전년비</th></tr></thead>
          <tbody>${hsRows.map(h => `<tr><td>${U.esc(h.label)} <small class="muted">${h.hs}</small></td><td class="num">${eur(h.k3)}</td><td class="num">${pctB(r(h.k3, h.kp), 0)}</td><td class="num">${h.contrib == null ? '–' : `<b class="${U.cls(h.contrib)}">${h.contrib > 0 ? '+' : ''}${(h.contrib * 100).toFixed(1)}%p</b>`}</td><td class="num">${eur(h.c3)}</td><td class="num">${pctB(r(h.c3, h.cpv), 0)}</td></tr>`).join('')}</tbody></table></div>
      </div>
      <p class="muted small">원산지 기준이라 한국산 제품이지 한국 회사가 아닙니다(한국 회사의 해외 생산분은 안 잡히고, 제3국 경유 물량은 원산지로 집계). ${us ? '미국 값은 미국이 UN Comtrade 에 보고한 수입액(달러, 키 없는 공개 미리보기)입니다' : 'EU 는 CIF 성격(유로)이라 한국 관세청 수출(FOB, 달러)과 금액 수준을 바로 비교하지 않습니다'}. 보통 두 달 늦게 올라옵니다.</p></details>`;
  }

  // ---------- 방한 외래관광객 (tourism.py, 출입국관광통계) ----------
  function renderTour() {
    const t = data.tour;
    if (!t || (st.sector !== 'all' && st.sector !== '화장품' && st.sector !== '미용 의료·의료기기')) { $('tour').innerHTML = ''; return; }
    const ms = t.months, n = ms.length, last = ms[n - 1], mm = last.slice(5);
    const at = (v, ym) => { const i = ms.indexOf(ym); return i < 0 ? null : v[i]; };
    const r = (a, b) => (a == null || !b ? null : a / b - 1);
    const ytd = (v, y) => { const xs = ms.map((m, i) => [m, v[i]]).filter(([m]) => m.startsWith(y) && m.slice(5) <= mm); return xs.length && xs.every(x => x[1] != null) ? xs.reduce((a, x) => a + x[1], 0) : null; };
    const y0 = last.slice(0, 4), y1 = String(+y0 - 1);
    const man = v => (v == null ? '–' : `${(v / 1e4).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}만`);
    const cur = t.total[n - 1], py = at(t.total, `${y1}-${mm}`), p19 = at(t.total, `2019-${mm}`);
    const W = 680, H = 160, N = Math.min(36, n), vs = t.total.slice(-N), hi = Math.max(...vs.filter(x => x != null), 1), bw = (W - 30) / N;
    const bars = vs.map((v, i) => { const m = ms[n - N + i], b19 = at(t.total, `2019-${m.slice(5)}`);
      return `<rect class="${i === N - 1 ? 'last' : ''}" x="${(26 + i * bw).toFixed(1)}" y="${(H - 18 - (v || 0) / hi * (H - 28)).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${((v || 0) / hi * (H - 28)).toFixed(1)}"><title>${m} ${man(v)} (2019년 같은 달 ${man(b19)})</title></rect>`
        + (b19 ? `<line class="tour19" x1="${(26 + i * bw).toFixed(1)}" x2="${(26 + i * bw + bw - 2).toFixed(1)}" y1="${(H - 18 - b19 / hi * (H - 28)).toFixed(1)}" y2="${(H - 18 - b19 / hi * (H - 28)).toFixed(1)}"/>` : '')
        + (m.endsWith('-01') ? `<text x="${(26 + i * bw).toFixed(1)}" y="${H - 4}">${m.slice(0, 4)}</text>` : ''); }).join('');
    const rows = t.nats.map(x => { const c = x.v[n - 1], p = at(x.v, `${y1}-${mm}`), b = at(x.v, `2019-${mm}`);
      return `<tr><td>${U.esc(x.n)}</td><td class="num">${man(c)}</td><td class="num">${pctB(r(c, p), 0)}</td><td class="num">${pctB(r(c, b), 0)}</td><td class="num">${cur ? `${(c / cur * 100).toFixed(1)}%` : '–'}</td><td class="num">${man(ytd(x.v, y0))}</td><td class="num">${pctB(r(ytd(x.v, y0), ytd(x.v, y1)), 0)}</td><td>${spark(x.v.slice(-24), 90, 20)}</td></tr>`; }).join('');
    $('tour').innerHTML = `<details class="card cs-chain" open><summary class="cs-d-head"><h3>방한 외래관광객 <small class="muted">한국문화관광연구원 출입국관광통계 · ${ymLabel(last)}월까지 · 화장품 면세·로드숍, 피부과·성형외과 의료관광의 수요</small></h3></summary>
      <dl class="eu-kpi tour-kpi"><dt>${+mm}월</dt><dd><b>${man(cur)}</b>명 <span class="muted">전년비</span> ${pctB(r(cur, py), 1)} <span class="muted">· 2019년 대비</span> ${pctB(r(cur, p19), 1)}</dd>
        <dt>${y0}년 누계</dt><dd>${man(ytd(t.total, y0))}명 <span class="muted">(1~${+mm}월) 전년비</span> ${pctB(r(ytd(t.total, y0), ytd(t.total, y1)), 1)} <span class="muted">· 2019년 대비</span> ${pctB(r(ytd(t.total, y0), ytd(t.total, '2019')), 1)}</dd></dl>
      <svg class="eu-chart cs-bars tour-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"><text x="0" y="12">${man(hi)}</text>${bars}</svg>
      <div class="tbl-wrap"><table class="tbl" data-nosort><thead><tr><th>국적</th><th class="num">${+mm}월</th><th class="num">전년비</th><th class="num">2019년 대비</th><th class="num">비중</th><th class="num">누계</th><th class="num">누계 전년비</th><th class="nosort">24개월</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="muted small">막대 = 월 입국자, 가로 선 = 2019년 같은 달. ${t.total_src === 'sum' ? '전체는 국적 줄의 합(대륙 소계 제외)입니다. ' : ''}매 수집마다 최근 13개월을 다시 받아 정정을 반영합니다.</p></details>`;
  }

  // ---------- 외국인 의료 소비 (medical.py ← 한국관광 데이터랩, 외국인 카드 결제) ----------
  function renderMed() {
    const m = data.med;
    if (!m || (st.sector !== 'all' && st.sector !== '화장품' && st.sector !== '미용 의료·의료기기')) { $('med').innerHTML = ''; return; }
    const ms = m.months, n = ms.length, last = ms[n - 1], mm = last.slice(5), y0 = last.slice(0, 4), y1 = String(+y0 - 1);
    const sum = (v, a, b) => { const xs = v.slice(a, b); return xs.length && xs.every(x => x != null) ? xs.reduce((p, q) => p + q, 0) : null; };
    const ytd = (v, y) => { const xs = ms.map((x, i) => [x, v[i]]).filter(([x]) => x.startsWith(y) && x.slice(5) <= mm); return xs.length && xs.every(x => x[1] != null) ? xs.reduce((p, x) => p + x[1], 0) : null; };
    const r = (a, b) => (a == null || !b ? null : a / b - 1);
    const eok = v => (v == null ? '–' : U.eok(v / 100));                       // 백만원 → 억원
    const tot = ms.map((_, i) => m.cats.reduce((p, c) => (p == null || c.v[i] == null ? null : p + c.v[i]), 0));
    const cat = k => (m.cats.find(c => c.cat === k) || { v: ms.map(() => null) }).v;
    const kpi = ['피부과', '성형외과', '약국'].map(k => { const v = cat(k); return `${k} ${eok(v[n - 1])} ${pctB(r(v[n - 1], v[n - 13]), 0)} <span class="muted">(비중 ${tot[n - 1] ? (v[n - 1] / tot[n - 1] * 100).toFixed(0) : '–'}%)</span>`; }).join(' · ');
    const N = 36, ser = m.cats.slice(0, 5).map(c => ({ kw: c.cat, v: c.v.slice(-N) }));
    const rows = m.nats.slice(0, 14).map(x => {
      const a3 = sum(x.amt, n - 3, n), p3 = sum(x.amt, n - 15, n - 12), d3 = sum(x['피부과'], n - 3, n);
      const c3 = sum(x.cnt, n - 3, n);
      const y3 = k => r(sum(x[k], n - 3, n), sum(x[k], n - 15, n - 12));
      return `<tr><td>${U.esc(x.n)}</td><td class="num">${eok(x.amt[n - 1])}</td><td class="num">${pctB(r(x.amt[n - 1], x.amt[n - 13]), 0)}</td><td class="num">${eok(a3)}</td><td class="num">${pctB(r(a3, p3), 0)}</td>
        <td class="num">${a3 ? `${(d3 / a3 * 100).toFixed(0)}%` : '–'}</td><td class="num">${pctB(y3('피부과'), 0)}</td><td class="num">${pctB(y3('성형외과'), 0)}</td><td class="num">${pctB(y3('약국'), 0)}</td>
        <td class="num">${a3 && c3 ? `${Math.round(a3 * 1e6 / c3 / 1e4).toLocaleString('ko-KR')}만` : '–'}</td><td class="num">${pctB(r(ytd(x.amt, y0), ytd(x.amt, y1)), 0)}</td><td>${spark(x.amt.slice(-24), 90, 20)}</td></tr>`;
    }).join('');
    $('med').innerHTML = `<details class="card cs-chain" open><summary class="cs-d-head"><h3>외국인 의료 소비 <small class="muted">한국관광 데이터랩 의료관광 현황 · 외국인 카드 결제 · ${ymLabel(last)}월까지 · 피부 미용 의료기기(클래시스·원텍 …)·스킨부스터(파마리서치)·톡신·약국 화장품 수요</small></h3></summary>
      <dl class="eu-kpi tour-kpi"><dt>${+mm}월 전체</dt><dd><b>${eok(tot[n - 1])}</b> ${pctB(r(tot[n - 1], tot[n - 13]), 1)} <span class="muted">· ${y0}년 누계</span> ${eok(ytd(tot, y0))} ${pctB(r(ytd(tot, y0), ytd(tot, y1)), 1)}</dd>
        <dt>진료과목</dt><dd>${kpi}</dd></dl>
      ${lineChart(ms.slice(-N), ser, 680, 200, v => U.eok(v / 100))}
      <p class="muted small" style="margin:2px 0 6px">${ser.map((x, k) => `<i class="eu-dot" style="background:${PAL[k % PAL.length]}"></i>${U.esc(x.kw)}`).join(' &nbsp; ')} <span class="muted">(월 소비액)</span></p>
      <div class="tbl-wrap"><table class="tbl" data-nosort><thead><tr><th>국적</th><th class="num">${+mm}월</th><th class="num">전년비</th><th class="num">3개월</th><th class="num">전년비</th><th class="num">피부과 비중</th><th class="num">피부과</th><th class="num">성형외과</th><th class="num">약국</th><th class="num" title="최근 3개월 소비액 ÷ 건수">건당</th><th class="num">누계 전년비</th><th class="nosort">24개월</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="muted small">진료과목별 전년비는 최근 3개월 기준. 카드 결제(국내 카드사 집계 외국인 카드) 표본 기반이라 현금·해외 결제앱은 빠집니다. 데이터랩 공개 화면의 조회 주소를 그대로 부릅니다.</p></details>`;
  }

  // ---------- 구글 검색 관심도 (collect_trends.py → data/trends.json) ----------
  const PAL = ['#3182f6', '#f04452', '#1fa774', '#e8a33d', '#8b5cf6', '#14b8c4', '#ec4899', '#64748b', '#a3a020'];
  function lineChart(labels, series, W = 680, H = 200, fmt = v => Math.round(v)) {
    const all = series.flatMap(x => x.v).filter(v => v != null), hi = Math.max(...all, 1);
    const P = 26, X = i => P + i / Math.max(labels.length - 1, 1) * (W - P - 8), Y = v => H - 18 - v / hi * (H - 28);
    const yr = labels.map((d, i) => (i && d.slice(0, 4) !== labels[i - 1].slice(0, 4) ? `<line class="eu-grid" x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="6" y2="${H - 18}"/><text x="${X(i).toFixed(1)}" y="${H - 4}" text-anchor="middle">${d.slice(0, 4)}</text>` : '')).join('');
    const ln = (x, k) => `<polyline style="stroke:${PAL[k % PAL.length]}" points="${x.v.map((v, i) => (v == null ? '' : `${X(i).toFixed(1)},${Y(v).toFixed(1)}`)).filter(Boolean).join(' ')}"><title>${U.esc(x.kw)}</title></polyline>`;
    return `<svg class="eu-chart tr-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${yr}<text x="2" y="12">${fmt(hi)}</text>${series.map(ln).join('')}</svg>`;
  }
  function renderTrends() {
    if (!trends?.groups?.length || (st.sector !== 'all' && st.sector !== '화장품' && st.sector !== '미용 의료·의료기기')) { $('trends').innerHTML = ''; return; }
    const g = trends.groups.find(x => x.id === st.tg) || trends.groups[0];
    const n = +st.tr, labels = g.labels.slice(-n), ser = g.series.map(x => ({ ...x, v: x.v.slice(-n) }));
    const avg = (v, a, b) => { const xs = v.slice(a, b).filter(x => x != null); return xs.length ? xs.reduce((p, q) => p + q, 0) / xs.length : null; };
    const L = g.labels.length;
    const rows = g.series.map((x, k) => {
      const now = avg(x.v, L - 4, L), prev = avg(x.v, L - 8, L - 4), ly = avg(x.v, L - 56, L - 52), peak = Math.max(...x.v.slice(-52));
      const r = (a, b) => (a == null || !b ? null : a / b - 1);
      const s = x.c && data.stocks.find(y => y.c === x.c);
      return `<tr><td><i class="eu-dot" style="background:${PAL[k % PAL.length]}"></i>${U.esc(x.kw)}</td><td>${x.c ? (s ? pick(x.c, x.n || s.n) : Stock.link({ c: x.c, n: x.n || x.c })) : '<span class="muted">–</span>'}</td>
        <td class="num">${now == null ? '–' : now.toFixed(1)}</td><td class="num">${pctB(r(now, prev), 0)}</td><td class="num">${pctB(r(now, ly), 0)}</td><td class="num">${peak ? `${Math.round(now / peak * 100)}%` : '–'}</td></tr>`;
    }).join('');
    $('trends').innerHTML = `<details class="card cs-chain" open><summary class="cs-d-head"><h3>구글 검색 관심도 <small class="muted">구글 트렌드 주간 · 묶음 안에서만 비교(최고 = 100) · 판매량 아님 · ${U.esc(g.labels[L - 1])} 주까지${g.stale ? ' · <b class="down">이번 수집 실패 — 직전 값</b>' : ''}</small></h3></summary>
      <div class="col-head">${pg.seg('tg', trends.groups.map(x => [x.id, x.label]))} ${pg.seg('tr', [['104', '2년'], ['262', '5년']])}</div>
      ${g.note ? `<p class="muted small" style="margin:4px 0">${U.esc(g.note)}</p>` : ''}
      ${lineChart(labels, ser)}
      <div class="tbl-wrap"><table class="tbl" data-nosort><thead><tr><th>검색어</th><th>종목</th><th class="num">최근 4주</th><th class="num">직전 4주 대비</th><th class="num">1년 전 대비</th><th class="num">1년 최고 대비</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
  }

  // ---------- Amazon · TikTok · Reddit (newsbot 집계, data/altdata.json — 이 컴퓨터에서만) ----------
  function renderAlt() {
    if (!alt?.companies || (st.sector !== 'all' && st.sector !== '화장품' && st.sector !== '미용 의료·의료기기')) { $('alt').innerHTML = ''; return; }
    const avg = (v, a, b) => { const xs = v.slice(a, b).filter(x => x != null); return xs.length ? xs.reduce((p, q) => p + q, 0) / xs.length : null; };
    const pp = v => (v == null ? '' : ` <small class="${U.cls(v)}">${v > 0 ? '+' : ''}${v.toFixed(1)}%p</small>`);
    const rows = Object.entries(alt.companies).map(([c, x]) => {
      const s = data.stocks.find(y => y.c === c);
      const name = s ? pick(c, x.name) : Stock.link({ c, n: x.name });
      const cap = s ? ` <small class="muted">시총 ${U.eok(s.mc)}${porNext(s) ? ` · POR ${porNext(s).toFixed(1)}배` : ''}</small>` : '';
      const brands = (x.brands || []).slice(0, 4).map(b => b.kr || b.kw).join(', ') + ((x.brands || []).length > 4 ? ` 외 ${x.brands.length - 4}` : '');
      let amz = '<span class="muted">–</span>';
      if (x.amazon) {
        const a = x.amazon, n = a.labels.length;
        amz = (a.order || Object.keys(a.by_country)).map(k => { const v = a.by_country[k]; const now = avg(v, n - 7, n), was = avg(v, n - 35, n - 28);
          return `<span class="alt-ms"><b>${k}</b> ${now == null ? '–' : now.toFixed(1) + '%'}${now != null && was != null ? pp(now - was) : ''}</span>`; }).join(' ')
          + `<div>${spark((a.by_country[a.order?.[0]] || []).slice(-60), 110, 22)}</div>`;
      }
      let tt = '<span class="muted">–</span>';
      if (x.tiktok?.index) {
        const t = x.tiktok;
        tt = x.tiktok.thin ? `<span class="muted small">${U.esc(t.detail || '표본 적음')}</span>`
          : `<b>${t.index[t.index.length - 1]?.toFixed(0)}</b> <small class="muted">(${t.base_from.slice(5)}~${t.base_to.slice(5)} = 100)</small> <span class="muted small">WoW</span> ${pctB(t.wow != null ? t.wow / 100 : null, 0)}<div>${spark(t.index.slice(-60), 110, 22, t.wow >= 0 ? 'up' : 'down')}</div>`;
      }
      let rd = '<span class="muted">–</span>';
      if (x.reddit) {
        const r = x.reddit, se = r.sentiment;
        rd = `${r.thin ? '<span class="muted small">표본 적음 · </span>' : ''}7일 <b>${r.d7}</b>건 <small class="muted">(직전 ${r.d7_prev})</small> · 90일 ${r.n90}${se ? ` <div class="small">감성 ${se.net > 0 ? '+' : ''}${se.net} <span class="muted">(긍 ${se.pos}·중 ${se.neu}·부 ${se.neg}${se.topic ? ` · ${U.esc(se.topic)}` : ''})</span></div>` : ''}
          ${(r.posts || []).slice(0, 2).map(p => `<div class="small alt-post"><a href="${U.esc(p.url)}" target="_blank" rel="noopener">${U.esc(p.title.slice(0, 48))}</a> <span class="muted">${p.d.slice(5)}${p.intent ? ` · ${U.esc(p.intent)}` : ''}</span></div>`).join('')}`;
      }
      return `<tr><td>${name}${cap}<div class="muted small">${U.esc(brands)}</div></td><td>${amz}</td><td>${tt}</td><td>${rd}</td></tr>`;
    }).join('');
    $('alt').innerHTML = `<details class="card cs-chain" open><summary class="cs-d-head"><h3>Amazon · TikTok · Reddit <small class="muted">newsbot 커버리지 대시보드 집계를 그대로 표시 · 원자료 ${U.esc(alt.data_through || '')}까지 · 이 컴퓨터에서만(공개 배포 제외)</small></h3></summary>
      <div class="tbl-wrap"><table class="tbl alt-tbl" data-nosort><thead><tr><th>회사 · 브랜드</th><th>Amazon 점유율 <small class="muted">순위 가중 SKU · 최근 7일 평균, 4주 전 대비</small></th><th>TikTok Shop GMV 지수</th><th>Reddit 언급</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="muted small">출처: <a href="${U.esc(alt.page)}" target="_blank" rel="noopener">newsbot 커버리지</a> (${U.esc(alt.source?.amazon || '')} · ${U.esc((alt.source?.tiktok || '').split('·')[0])}). 받은 때 ${U.timeLabel(alt.fetched_at)}. 절대 GMV 는 공개되지 않아 지수만 있습니다.</p></details>`;
  }

  // ---------- 품목 × 국가 ----------
  function renderHeat() {
    const gs = data.groups.filter(inSector);
    const cell = v => {
      if (!v || v[0] == null) return '<td class="muted">–</td>';
      const a = Math.min(Math.abs(v[0]), 1) * 0.55 + 0.05;
      return `<td style="background:color-mix(in srgb, var(--${v[0] >= 0 ? 'up' : 'down'}) ${(a * 100).toFixed(0)}%, transparent)" title="비중 ${(v[1] * 100).toFixed(1)}%"><b>${U.pct(v[0], 0)}</b><small>${v[1] >= 0.005 ? `${(v[1] * 100).toFixed(0)}%` : ''}</small></td>`;
    };
    $('heat').innerHTML = `<details class="card cs-chain" open><summary class="cs-d-head"><h3>품목 × 국가 <small class="muted">최근 3개월 수출의 전년비 · 작은 숫자는 그 나라가 품목 수출에서 차지하는 비중(12개월)</small></h3></summary>
      <div class="tbl-wrap"><table class="cs-heat" data-nosort><thead><tr><th>품목</th><th>전체</th>${HEAT.map(h => `<th>${h[1]}</th>`).join('')}</tr></thead>
      <tbody>${gs.map(g => `<tr><th><button class="linkish cs-pick" data-g="${g.id}">${U.esc(g.label)}</button></th>${cell([g.yoy3, 1])}${HEAT.map(h => cell(g.heat?.[h[0]])).join('')}</tr>`).join('')}</tbody></table></div></details>`;
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
      <b>${U.esc(s.n)} ${fitTag(s)}</b>
      <span class="muted">${U.eok(s.mc)}${porNext(s) ? ` · POR ${U.mult(porNext(s))}` : ''}</span>
      <span>${!f ? '<span class="muted">맞는 품목 없음</span>'
        : f.kind === 'sigungu' && f.cover != null && f.cover < data.cover_min ? `<span class="muted" title="이 지역 흐름은 매출의 ${(f.cover * 100).toFixed(0)}%뿐이라 전년비가 크게 튄다">수출(매출의 ${(f.cover * 100).toFixed(0)}%) ${U.pct(f.yoy3, 0)}</span>`
        : `${f.kind === 'national' ? '업황' : '수출'} ${pctB(f.yoy3, 0)}`}${s.ret3 != null ? ` <span class="muted">· 시총</span> ${pctB(s.ret3, 0)}` : ''}
        ${s.preview?.verdict ? `<i class="cs-v ${s.preview.verdict.replace(' ', '')}">${s.preview.verdict}</i>` : ''}</span>
    </button>`;
  }

  function renderChain() {
    const sectors = Object.keys(data.chains).filter(sec => st.sector === 'all' || st.sector === sec);
    $('chain').innerHTML = sectors.map(sec => {
      const stages = data.chains[sec].map(stage => [stage, data.stocks.filter(s => s.sector === sec && s.stage === stage).sort((a, b) => (b.mc || 0) - (a.mc || 0))]).filter(x => x[1].length);
      return `<div class="card cs-chain"><div class="cs-d-head"><h3>${sec} 밸류체인 <small class="muted">단계마다 시총 순 · 수출(지역 흐름)·업황(전국 묶음)은 최근 3개월 전년비, 시총은 3개월 변화</small></h3></div>
        <div class="cs-stages" style="--n:${stages.length}">${stages.map(([stage, ss]) => `<div class="cs-stage"><h4>${stage} <small class="muted">${ss.length}</small></h4>${ss.map(chipHtml).join('')}</div>`).join('')}</div></div>`;
    }).join('');
  }

  // ---------- 종목 표 ----------
  const verdictHtml = p => (!p ? '<span class="muted">–</span>' : p.verdict ? `<i class="cs-v ${p.verdict.replace(' ', '')}">${p.verdict}</i> <small class="${U.cls(p.diff)}">${U.pct(p.diff, 0)}</small>`
    : `<small class="muted" title="지난 분기 되맞춤 오차가 커서 판정은 내지 않는다">추정 ${U.eok(p.est)} · 참고</small>`);

  function renderTable() {
    const q = st.q.trim().toLowerCase();
    const shows = { all: () => true, ok: s => s.fit?.k === 'ok', flow: own, prev: s => !!s.preview, gap, notes: s => (s.calls?.n || 0) + (s.visits?.n || 0) > 0 };
    const list = data.stocks.filter(s => inSector(s) && shows[st.show](s) && (!q || s.n.toLowerCase().includes(q) || s.c.includes(q)));
    $('table').innerHTML = `<div class="tbl-wrap card"><div class="col-head"><h3>종목 <span class="muted">${list.length}개 · 열 제목을 누르면 정렬 · 줄을 누르면 위에 상세</span></h3>${pg.seg('show', SHOWS)}</div>
      <table class="tbl cs-tbl"><thead><tr><th>종목</th><th>단계</th><th class="num">시총</th><th class="num" title="수정주가 기준 3개월 변화">시총 3개월</th><th class="num">내년 POR</th><th>대표 흐름</th>
        <th class="num">${ymLabel(data.last_ym)}월 전년비</th><th class="num">3개월 전년비</th><th class="nosort">24개월</th>
        <th class="num" title="분기 수출 전년비와 분기 매출 전년비의 상관 (최근 12분기)">매출 상관 r</th>
        <th class="num" title="최근 4분기 수출(원화 환산) ÷ 매출">수출÷매출</th><th title="수출로 본 이번 분기 매출 추정 vs 컨센서스">프리뷰</th><th class="num">컨콜·탐방</th></tr></thead>
      <tbody>${list.map(s => {
        const f = mainFlow(s);
        return `<tr data-s="${s.c}" class="${st.s === s.c ? 'on' : ''}" ${Stock.hintAttr(s)}>
          <td class="name-cell">${Stock.link(s)} ${fitTag(s)}</td>
          <td class="muted">${s.stage}</td><td class="num" data-v="${s.mc ?? ''}">${U.eok(s.mc)}</td><td class="num" data-v="${s.ret3 ?? ''}">${pctB(s.ret3, 0)}</td><td class="num" data-v="${porNext(s) ?? ''}">${porNext(s) ? U.mult(porNext(s)) : '–'}</td>
          <td>${f ? `${U.esc(f.label)} <small class="muted">${BASIS[f.basis][0]}</small>` : '<span class="muted">–</span>'}</td>
          <td class="num" data-v="${f?.yoy ?? ''}">${pctB(f?.yoy)}</td><td class="num" data-v="${f?.yoy3 ?? ''}">${pctB(f?.yoy3)}</td>
          <td>${f ? spark(f.usd.slice(-24), 90, 22, U.cls(f.yoy3)) : ''}</td>
          <td class="num" data-v="${f?.r ?? ''}">${f?.r != null ? `<b class="${f.ok ? 'up' : ''}">${f.r.toFixed(2)}</b> <small class="muted">${f.nq}분기${f.ok ? ' ✓' : ''}</small>` : '<span class="muted">–</span>'}</td>
          <td class="num" data-v="${f?.cover ?? ''}">${f?.cover != null && f.kind === 'sigungu' ? `${(f.cover * 100).toFixed(0)}%` : '<span class="muted">–</span>'}</td>
          <td>${verdictHtml(s.preview)}</td>
          <td class="num" data-v="${(s.calls?.n || 0) + (s.visits?.n || 0)}">${s.calls?.n ? `컨콜 ${s.calls.n}` : ''}${s.calls?.n && s.visits?.n ? ' · ' : ''}${s.visits?.n ? `탐방 ${s.visits.n}` : ''}</td></tr>`;
      }).join('')}</tbody></table></div>`;
  }

  // ---------- 예측 계산식 (프록시·가정을 바꾸면 다시 계산) ----------
  // ① 수출 전년비 → ② 매출 전년비 = a + b×① → ③ 매출 = 전년 같은 분기 매출 × (1+②) → ④ 영업이익 = ③ × 영업이익률 → ⑤ 연환산 POR
  // 프록시 = 매출을 대신 보여 준다고 보는 수출 흐름(들의 합). 프록시·맞춤 기간을 바꾸면 a·b·상관·되맞춤 오차부터 다시 계산한다.
  // 계산은 consumer.py 의 estimate·hindcast·yoy_corr·partial_quarter 와 같은 식이다 (기본 프록시로는 서버가 낸 프리뷰와 같은 값이 나온다).
  // 고친 값(프록시, 맞춤 기간, ①, 영업이익률)은 종목별로 이 브라우저에 남는다.
  const CKEY = 'csCalc';
  const cfgAll = () => { try { return JSON.parse(localStorage.getItem(CKEY)) || {}; } catch (e) { return {}; } };
  const cfgOf = s => ({ flows: [s.main], look: 12, x: null, opm: null, ...(cfgAll()[s.c] || {}) });
  function cfgSave(s, cfg) {
    const all = cfgAll();
    const same = cfg.flows.length === 1 && cfg.flows[0] === s.main && cfg.look === 12 && cfg.x == null && cfg.opm == null;
    if (same) delete all[s.c]; else all[s.c] = cfg;
    try { localStorage.setItem(CKEY, JSON.stringify(all)); } catch (e) { /* 저장 안 되는 브라우저 */ }
  }
  const pp = (v, nd = 1) => `${v > 0 ? '+' : ''}${(v * 100).toFixed(nd)}%`;
  const qOf = m => `${m.slice(0, 4)}Q${Math.floor((+m.slice(5, 7) - 1) / 3) + 1}`;
  const prevQ = q => `${+q.slice(0, 4) - 1}${q.slice(4)}`;

  // 고른 흐름들의 합 → 분기 수출(억원). full = 석 달이 다 찬 분기, part = 진행 중인 마지막 분기의 어림
  function proxyQuarters(s, ids) {
    const fl = s.flows.filter(f => ids.includes(f.id));
    const ms = data.months;
    const krw = ms.map((_, i) => (fl.length && fl.every(f => f.usd[i] != null) ? fl.reduce((t, f) => t + f.usd[i], 0) * data.fx[i] / 1e8 : null));
    const acc = {};
    ms.forEach((m, i) => { if (krw[i] != null) { const q = qOf(m), o = acc[q] || (acc[q] = [0, 0]); o[0] += krw[i]; o[1] += 1; } });
    const full = {};
    for (const q in acc) if (acc[q][1] === 3) full[q] = acc[q][0];
    let part = null;
    const lastI = krw.map((v, i) => (v != null ? i : -1)).filter(i => i >= 0).pop();
    if (lastI != null) {
      const q = qOf(ms[lastI]);
      if (acc[q][1] < 3) {
        const by = Object.fromEntries(ms.map((m, i) => [m, krw[i]]));
        const py = m => by[`${+m.slice(0, 4) - 1}${m.slice(4)}`];
        const mo = (+q[5] - 1) * 3, y = q.slice(0, 4);
        const fullPy = [1, 2, 3].map(k => py(`${y}-${String(mo + k).padStart(2, '0')}`));
        const samePy = ms.filter((m, i) => qOf(m) === q && krw[i] != null).map(py);
        const sum = a => a.reduce((t, v) => t + v, 0);
        if (fullPy.every(v => v != null) && samePy.every(v => v != null) && sum(samePy) > 0) part = { q, est: acc[q][0] * sum(fullPy) / sum(samePy), k: acc[q][1] };
      }
    }
    return { full, part };
  }

  function fit(pts) {      // y = a + b·x 최소제곱 → [a, b, R²]
    const n = pts.length;
    if (n < data.min_q) return null;
    const mx = pts.reduce((t, p) => t + p[0], 0) / n, my = pts.reduce((t, p) => t + p[1], 0) / n;
    const sx = pts.reduce((t, p) => t + (p[0] - mx) ** 2, 0), sy = pts.reduce((t, p) => t + (p[1] - my) ** 2, 0);
    if (sx <= 0) return null;
    const b = pts.reduce((t, p) => t + (p[0] - mx) * (p[1] - my), 0) / sx, a = my - b * mx;
    const r2 = sy > 0 ? 1 - pts.reduce((t, p) => t + (p[1] - (a + b * p[0])) ** 2, 0) / sy : 0;
    return [a, b, r2, sy > 0 ? pts.reduce((t, p) => t + (p[0] - mx) * (p[1] - my), 0) / Math.sqrt(sx * sy) : null];
  }
  const yoyPts = (eq, rq, before, look) => Object.keys(eq).filter(q => q in rq).sort()
    .filter(q => (!before || q < before) && eq[prevQ(q)] > 0 && rq[prevQ(q)] > 0)
    .map(q => [eq[q] / eq[prevQ(q)] - 1, rq[q] / rq[prevQ(q)] - 1]).slice(-look);
  function estimate(eq, rq, q, look) {
    const p = prevQ(q);
    if (!(eq[q] > 0) || !(eq[p] > 0) || !(rq[p] > 0)) return null;
    const pts = yoyPts(eq, rq, q, look), f = fit(pts);
    if (!f) return null;
    const x = eq[q] / eq[p] - 1, g = f[0] + f[1] * x;
    return rq[p] * (1 + g) > 0 ? { q, a: f[0], b: f[1], r2: f[2], n: pts.length, x, g, base: rq[p], exp: eq[q], exp_py: eq[p], est: rq[p] * (1 + g) } : null;
  }

  // 지금 설정으로 계산한 것 전부: 상관·비중·되맞춤 오차와 분기별 추정(다 찬 분기, 진행 중 분기)
  function proxyCalc(s, cfg) {
    const { full, part } = proxyQuarters(s, cfg.flows);
    const rq = s.rq || {};
    const pts = yoyPts(full, rq, null, cfg.look), f = fit(pts);
    const common = Object.keys(full).filter(q => q in rq).sort().slice(-4);
    const revSum = common.reduce((t, q) => t + rq[q], 0);
    const cover = common.length === 4 && revSum > 0 ? common.reduce((t, q) => t + full[q], 0) / revSum : null;
    const past = Object.keys(full).filter(q => q in rq).sort().slice(-4).map(q => { const e = estimate(full, rq, q, cfg.look); return e ? { q, err: e.est / rq[q] - 1 } : null; }).filter(Boolean);
    const mae = past.length >= 3 ? past.reduce((t, h) => t + Math.abs(h.err), 0) / past.length : null;
    const todo = Object.keys(full).filter(q => !(q in rq)).sort();
    const targets = [];
    if (todo.length) { const e = estimate(full, rq, todo[todo.length - 1], cfg.look); if (e) targets.push(e); }
    if (part && !(part.q in rq)) { const e = estimate({ ...full, [part.q]: part.est }, rq, part.q, cfg.look); if (e) targets.push({ ...e, months: part.k }); }
    const r = f ? f[3] : null;
    return { full, r, n: pts.length, cover, past, mae, targets,
      ok: r != null && r >= data.r_ok && pts.length >= data.min_nq && cover != null && cover >= data.cover_min && cover <= data.cover_max };
  }

  function calcRows(s, e, cfg, i) {
    const py = prevQ(e.q).slice(2), cns = s.cnsq?.[e.q] || [null, null];
    const x = i === 0 && cfg.x != null ? cfg.x : e.x, opm = cfg.opm != null ? cfg.opm : s.opm;
    const args = { base: e.base, a: e.a, b: e.b, x0: e.x, opm0: s.opm, mc: s.mc, cns: cns[0], cnsOp: cns[1] };
    return `<div class="cs-calc-q" data-calc="${U.esc(JSON.stringify(args))}" data-i="${i}">
      <h5>${e.q}${e.months ? ` <i class="muted">진행 중 · ${e.months}개월 수출로 어림</i>` : ''}</h5>
      <ol>
        <li><span>① 수출 전년비</span><span>${e.q.slice(2)} 수출 ${U.eok(e.exp)} ÷ ${py} 수출 ${U.eok(e.exp_py)} − 1 =</span>
          <span><input type="number" step="1" data-in="x" value="${(x * 100).toFixed(1)}" aria-label="수출 전년비 가정"${i ? ' disabled' : ''}>%</span></li>
        <li><span>② 매출 전년비</span><span>${pp(e.a)} + ${e.b.toFixed(2)} × ① <i class="muted">(지난 ${e.n}분기 수출 전년비 → 매출 전년비 직선, R² ${e.r2.toFixed(2)})</i> =</span><b data-out="g"></b></li>
        <li><span>③ 매출 추정</span><span>${py} 매출 ${U.eok(e.base)} × (1 + ②) =</span><b data-out="rev"></b><small data-out="revc"></small></li>
        ${opm != null ? `<li><span>④ 영업이익 추정</span><span>③ × 영업이익률 <input type="number" step="0.5" data-in="opm" value="${(opm * 100).toFixed(1)}" aria-label="영업이익률 가정">% <i class="muted">(기본값 ${(s.opm * 100).toFixed(1)}% = 최근 4분기 합산)</i> =</span><b data-out="op"></b><small data-out="opc"></small></li>
        <li><span>⑤ 연환산 POR</span><span>시총 ${U.eok(s.mc)} ÷ (④ × 4) <i class="muted">(이 분기 이익이 1년 이어진다고 볼 때 — 계절성은 무시)</i> =</span><b data-out="por"></b></li>` : ''}
      </ol>
      ${Math.abs(e.a) >= 0.2 ? `<p class="cs-warn">절편이 ${pp(e.a, 0)} 로 큽니다 — 수출이 그대로여도 매출이 이만큼 변한다고 본다는 뜻이라, 추정의 대부분이 수출이 아니라 지난 성장 추세에서 나옵니다.</p>` : ''}
      ${e.b < 0.2 ? `<p class="cs-warn">기울기가 ${e.b.toFixed(2)} 로 작습니다 — 수출이 변해도 추정 매출이 거의 움직이지 않습니다.</p>` : ''}
    </div>`;
  }

  function calcRender(s) {
    const box = $('calc');
    if (!box) return;
    if (!s.flows.length) { box.innerHTML = ''; return; }
    const cfg = cfgOf(s);
    cfg.flows = cfg.flows.filter(id => s.flows.some(f => f.id === id));
    if (!cfg.flows.length) cfg.flows = [s.main];
    const c = proxyCalc(s, cfg);
    const mine = !!cfgAll()[s.c];
    box.innerHTML = `<div class="cs-calc">
      <h4>예측 계산식 <small class="muted">프록시(매출을 대신 보는 수출 흐름)·맞춤 기간·가정을 바꾸면 다시 계산됩니다</small>
        <span class="pill cs-mine"${mine ? '' : ' hidden'}>내 설정</span><button class="linkish" data-reset>처음 값으로</button></h4>
      <div class="cs-proxy"><span class="muted">프록시</span>${s.flows.map(f => `<button class="cs-px${cfg.flows.includes(f.id) ? ' on' : ''}" data-px="${U.esc(f.id)}" title="${BASIS[f.basis][1]}">${U.esc(f.label)} <small>${BASIS[f.basis][0]}</small></button>`).join('')}</div>
      <div class="cs-proxy"><span class="muted">맞춤 기간</span><span class="seg" role="group">${[8, 12, 16].map(k => `<button data-look="${k}" class="${cfg.look === k ? 'on' : ''}">${k}분기</button>`).join('')}</span>
        <span>매출 상관 ${c.r != null ? `<b>${c.r.toFixed(2)}</b> <span class="muted">(${c.n}분기)</span>` : `<span class="muted">– (${c.n}분기 — ${data.min_q}분기 이상 필요)</span>`}
          · 수출÷매출 ${c.cover != null ? `<b>${(c.cover * 100).toFixed(0)}%</b>` : '<span class="muted">–</span>'}
          · 지난 분기 평균 오차 ${c.mae != null ? `<b>${(c.mae * 100).toFixed(0)}%</b>` : '<span class="muted">–</span>'}
          ${c.ok ? '<b class="up">회사 수출 기준 통과 ✓</b>' : ''}</span></div>
      ${c.ok ? '' : `<p class="cs-warn">이 프록시는 '회사 수출' 기준(상관 ${data.r_ok} 이상 · ${data.min_nq}분기 이상 · 수출÷매출 ${data.cover_min * 100}~${data.cover_max * 100}%)을 통과하지 못했습니다. 아래 숫자는 참고용입니다.</p>`}
      ${c.past.length ? `<p class="small cs-past"><span class="muted">이 설정으로 지난 분기를 다시 맞춰 보면 (추정 ÷ 실제 − 1):</span> ${c.past.map(h => `${h.q.slice(2)} <b class="${U.cls(h.err)}">${U.pct(h.err, 0)}</b>`).join(' · ')}</p>` : ''}
      ${c.targets.length ? c.targets.map((e, i) => calcRows(s, e, cfg, i)).join('')
        : '<p class="muted small">이 프록시로는 추정할 수 없습니다 — 실적이 안 나온 분기의 수출이 없거나, 전년비를 맞출 분기가 모자랍니다.</p>'}
    </div>`;
    box.querySelectorAll('.cs-calc-q').forEach(calcUpdate);
    drawQuarters(s, c.full);
  }

  function calcUpdate(box) {
    const c = JSON.parse(box.dataset.calc);
    const val = (k, d) => { const el = box.querySelector(`[data-in="${k}"]`); const v = el ? parseFloat(el.value) : NaN; return Number.isFinite(v) ? v / 100 : d; };
    const x = val('x', c.x0), opm = val('opm', c.opm0);
    const g = c.a + c.b * x, rev = c.base * (1 + g), op = opm != null ? rev * opm : null;
    const set = (k, html) => { const el = box.querySelector(`[data-out="${k}"]`); if (el) el.innerHTML = html; };
    const vs = (v, cns) => (cns ? ` 컨센서스 ${U.eok(cns)} 대비 <b class="${U.cls(v / cns - 1)}">${U.pct(v / cns - 1)}</b>` : ' 분기 컨센서스 없음');
    set('g', `<span class="${U.cls(g)}">${pp(g)}</span>`);
    set('rev', U.eok(rev));
    set('revc', vs(rev, c.cns));
    if (op != null) {
      set('op', U.eok(op));
      set('opc', vs(op, c.cnsOp));
      set('por', op > 0 && c.mc ? U.mult(c.mc / (op * 4)) : '적자');
    }
  }

  // 분기 수출(지금 프록시) vs 분기 매출
  function drawQuarters(s, full) {
    const el = $('q-chart');
    if (!el) return;
    const qs = [...new Set([...Object.keys(s.rq || {}), ...Object.keys(full)])].sort().slice(-14);
    if (!qs.length) { el.innerHTML = '<p class="muted small">분기 매출 자료 없음</p>'; return; }
    const rev = qs.map(q => s.rq?.[q] ?? null), exp = qs.map(q => full[q] ?? null);
    Plot.chart(el, {
      n: qs.length, height: 200, uid: 'csq',
      panes: [{ h: 1, fmt: v => U.eok(v), series: [{ type: 'bar', values: rev }, { type: 'line', values: exp, color: 'var(--accent)', width: 1.8 }] }],
      xTicks: qs.map((q, i) => [i, q.slice(2).replace('Q', '.')]).filter((_, i) => i % 2 === 0),
      tip: i => `<div class="tt-h">${qs[i]}</div><div class="tt-g"><span>매출</span><b>${U.eok(rev[i])}</b><span>수출(프록시)</span><b>${U.eok(exp[i])}</b></div>`,
    });
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
    box.innerHTML = `<div class="cs-d-head"><h3>${Stock.link(s)} <small class="muted">${s.c} · ${MARKETS[s.mk] || ''} · ${s.sector} ${s.stage} · 시총 ${U.eok(s.mc)}${s.ret1 != null ? ` (1개월 ${U.pct(s.ret1, 0)} · 3개월 ${U.pct(s.ret3, 0)})` : ''}</small></h3>
        <button class="linkish" data-s="">닫기 ✕</button></div>
      ${s.fit ? `<p class="cs-memo">${fitTag(s)} ${U.esc(s.fit.why)}${s.fit.k === 'ok' ? '' : s.fit.k === 'none' ? '' : ' — 수출 숫자는 이 회사 매출을 설명하지 못하니 업황 참고로만 보세요.'}</p>` : ''}
      ${s.memo ? `<p class="cs-memo">${U.esc(s.memo)}</p>` : ''}
      <div class="cs-two">
        <div>${U.porTable(s.mc, s) || '<p class="muted small">영업이익 컨센서스가 없어 POR 을 계산하지 못합니다.</p>'}
          ${p ? `<div class="cs-prev"><b>수출로 본 ${p.q} 매출 추정 ${U.eok(p.est)}</b>${p.cns ? ` · 컨센서스 ${U.eok(p.cns)} 대비 ${pctB(p.diff)} ${p.verdict ? `<i class="cs-v ${p.verdict.replace(' ', '')}">${p.verdict}</i>` : ''}` : ' · 분기 컨센서스 없음'}
            <small class="muted">전년 같은 분기 매출 × (수출 전년비로 본 매출 전년비). 지난 ${p.n}개 분기로 맞춤(R² ${p.r2.toFixed(2)})${p.mae != null ? `, 지난 분기 평균 오차 ${(p.mae * 100).toFixed(0)}%` : ''}.
              ${p.cns && !p.verdict ? `오차가 ${data.mae_ok * 100}% 를 넘어 BEAT·MISS 판정은 내지 않습니다. ` : ''}어림값이며 매매 권유가 아닙니다.</small></div>` : ''}
          ${s.next ? `<div class="cs-prev"><b>진행 중인 ${s.next.q} — ${s.next.months}개월 수출로 어림한 매출 ${U.eok(s.next.est)}</b>${s.next.cns ? ` · 컨센서스 ${U.eok(s.next.cns)} 대비 ${pctB(s.next.diff)}` : ''}
            <small class="muted">들어온 달의 수출에 전년 같은 분기의 달별 비중을 적용해 분기 수출을 어림했습니다. 달이 다 차기 전이라 판정은 내지 않습니다.</small></div>` : ''}
          ${s.past?.length ? `<p class="small cs-past"><span class="muted">같은 방법으로 지난 분기를 다시 맞춰 보면 (추정 ÷ 실제 − 1):</span> ${s.past.map(h => `${h.q.slice(2)} <b class="${U.cls(h.err)}">${U.pct(h.err, 0)}</b>`).join(' · ')}</p>` : ''}
        </div>
        <div><h4>분기 수출 vs 매출 <small class="muted">억원 · 막대 = 매출, 선 = 지금 고른 프록시의 수출</small></h4><div id="q-chart"></div></div>
      </div>
      <div id="calc"></div>
      <h4>수출 흐름 <small class="muted">누르면 아래 차트가 바뀝니다</small></h4>
      <div class="cs-flows">${s.flows.map(x => `<button class="cs-flow${f && x.id === f.id ? ' on' : ''}" data-f="${x.id}">
        <b>${U.esc(x.label)}</b><span class="pill" title="${BASIS[x.basis][1]}">${BASIS[x.basis][0]}</span>
        <span>3개월 ${pctB(x.yoy3, 0)} · 매출 상관 ${x.r != null ? `<b>${x.r.toFixed(2)}</b>` : '<span class="muted">–</span>'}${x.cover != null && x.kind === 'sigungu' ? ` · 수출÷매출 ${(x.cover * 100).toFixed(0)}%` : ''}${x.ok ? ' · <b class="up">회사 수출로 확인 ✓</b>' : ''}</span>
      </button>`).join('') || '<p class="muted small">품목 사전과 맞는 수출 흐름이 없습니다.</p>'}</div>
      <div id="f-chart"></div>
      <div class="cs-cols3">
        <div><h4>기업설명회 공시 <small class="muted">DART, 최근 60일</small></h4>${irs.length ? irs.map(x => `<p class="small"><span class="muted">${U.md(x.d)}</span> <a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${x.no}" target="_blank" rel="noopener">${U.esc(x.t)} ↗</a></p>`).join('') : '<p class="muted small">없음</p>'}</div>
        <div class="cs-span2"><h4>컨콜 노트 <small class="muted">텔레그램 · ${notes.length}건${calls ? '' : ' (이 화면에서는 볼 수 없음)'}</small>${s.visits?.n ? ` <a class="small" href="visit.html?per=all&q=${encodeURIComponent(s.n)}">탐방 노트 ${s.visits.n}건 →</a>` : ''}</h4>
          ${notes.map(n => n.lim
            ? `<p class="cs-call small"><span class="muted">${U.md(n.d)}</span> <b>${U.esc(n.t)}</b> <small class="muted">${n.rooms.map(U.esc).join(' · ')}</small>${n.link ? ` · <a href="${U.esc(n.link)}" target="_blank" rel="noopener">원문은 채널에서 ↗</a>` : ''}</p>`
            : `<details class="cs-call"><summary><span class="muted">${U.md(n.d)}</span> <b>${U.esc(n.t)}</b> <small class="muted">${n.rooms.map(U.esc).join(' · ')}</small></summary>
            ${n.lines.length ? `<ul class="vs-lines">${n.lines.map(l => `<li>${U.num(l)}</li>`).join('')}</ul>` : ''}
            <pre class="vs-text">${U.esc(n.x)}</pre>${n.link ? `<a class="small muted" href="${U.esc(n.link)}" target="_blank" rel="noopener">텔레그램에서 열기 ↗</a>` : ''}</details>`).join('') || '<p class="muted small">없음</p>'}</div>
      </div>`;
    calcRender(s);
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
        <div class="cs-span2"><h4>최근 컨콜 노트 <small class="muted">텔레그램에서 모은 글${calls?.public ? ' · 공개 채널 글은 제목·링크만' : ''}</small></h4>
          ${all.map(n => `<p class="small"><span class="muted">${U.md(n.d)}</span> <button class="linkish cs-pick" data-s="${n.c}">${U.esc(n.n)}</button> ${U.esc(n.t)} <span class="muted">${U.esc(n.rooms[0] || '')}</span></p>`).join('') || '<p class="muted small">없음</p>'}</div>
      </div></div>`;
  }

  function render() {
    renderFilters();
    renderBrief();
    renderWatch();
    renderHeat();
    renderEU();
    renderTour();
    renderMed();
    renderTrends();
    renderAlt();
    renderGroups();
    renderChain();
    renderTable();
    renderDetail();
    renderSurge();
    renderCalls();
    $('asof').textContent = `${U.timeLabel(data.built_at)} 정리`;
    $('foot').innerHTML = `<p><b>읽는 법</b> · 수출은 관세청 통관 기준(달러)입니다. 전국 통계는 품목(HS 10단위)·국가·중량까지, 시군구 통계는 품목(HS 6단위) 금액만 나옵니다.
        시군구는 수출 신고인의 소재지라 공장이 아니라 본사·물류센터·무역상 주소로 잡히기도 하고, 한 시군구에 여러 회사가 섞입니다. 해외 공장에서 만들어 파는 매출은 한국 수출에 잡히지 않습니다.</p>
      <p>흐름의 근거: <b>공장 소재지</b> = DART 사업보고서 '생산설비 현황'의 생산·물류 사업장, <b>채널 근거</b> = 수출입 채널이 그 종목·지역·품목을 함께 다룬 기록,
        <b>본사 소재지</b> = DART 본사 주소, <b>전국 업황</b> = 회사가 아니라 품목 전체, <b>자동 탐색 후보</b> = 매출과 같이 움직인 지역을 기계적으로 찾은 것(판정에 쓰지 않음).</p>
      <p>종목 옆 표시: <b>수출 연동 ✓</b> 회사 수출로 확인 · <b>따로 논다</b> 매출의 상당 부분인 지역 수출이 있지만 매출과 같이 움직이지 않음 · <b>수출 작음</b> 지역 수출이 매출의 10% 미만(해외 생산·내수·다른 사업)
        · <b>지역 혼합</b> 지역 수출이 매출보다 커 다른 회사 물량이 대부분 · <b>판정 보류</b> 비교할 분기가 모자람 · <b>업황만</b> 회사 지역 흐름 없음.
        종목 매핑은 공시·채널 기록으로 기계적으로 만든 것이라 틀린 곳이 있을 수 있습니다.</p>
      <p>
        매출 상관 r 은 분기 수출 전년비와 분기 매출 전년비의 상관입니다. r 이 ${data.r_ok} 이상이고 최근 4분기 수출이 매출의 ${data.cover_min * 100}~${data.cover_max * 100}% 인 지역 흐름만 '회사 수출로 확인(✓)'으로 보고 프리뷰를 냅니다
        (상관만 높고 매출의 1~2%인 흐름, 수출이 매출보다 훨씬 큰 흐름은 다른 회사 물량이거나 우연입니다).
        예측 계산식: ① 수출 전년비 → ② 매출 전년비 = a + b × ① (지난 12분기로 맞춘 직선) → ③ 매출 = 전년 같은 분기 매출 × (1 + ②) → ④ 영업이익 = ③ × 최근 4분기 영업이익률 → ⑤ 연환산 POR = 시총 ÷ (④ × 4). 프리뷰는 지난 분기 되맞춤 오차가 ${data.mae_ok * 100}% 이하일 때만 컨센서스 대비 ±${data.band * 100}% 로 BEAT·MISS 를 냅니다.</p>
      <p class="muted">출처: 관세청 수출입무역통계(공공데이터포털), DART, FnGuide 컨센서스(네이버 종목분석). 매달 15일경 전월 확정치가 올라옵니다. 품목 단위 10일 속보는 없습니다. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  }

  document.querySelector('main').addEventListener('click', e => {
    if (e.target.closest('a')) return;
    const k = e.target.closest('button[data-k]');
    if (k) return pg.set({ [k.dataset.k]: k.dataset.v });          // 종목 표의 보기 필터 (필터 줄 밖에 있다)
    const g = e.target.closest('[data-g]');
    if (g) {
      pg.set({ g: st.g === g.dataset.g ? '' : g.dataset.g });
      if (st.g && g.classList.contains('cs-pick')) $('group-detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    const f = e.target.closest('[data-f]');
    if (f) { st.f = f.dataset.f; pg.write(); return renderDetail(); }
    const s = e.target.closest('[data-s]');
    if (s) {
      pg.set({ s: st.s === s.dataset.s ? '' : s.dataset.s, f: '' });
      if (st.s) $('detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  const selStock = () => data.stocks.find(x => x.c === st.s);
  $('detail').addEventListener('input', e => {
    const q = e.target.closest('.cs-calc-q');
    if (!q || !e.target.dataset.in) return;
    calcUpdate(q);
    const s = selStock(), cfg = cfgOf(s), c = JSON.parse(q.dataset.calc), v = parseFloat(e.target.value);
    const k = e.target.dataset.in, base = k === 'x' ? c.x0 : c.opm0;
    cfg[k] = Number.isFinite(v) && Math.abs(v / 100 - base) > 5e-4 ? v / 100 : null;      // 기본값과 같으면 저장하지 않는다
    cfgSave(s, cfg);
    const tag = $('calc').querySelector('.cs-mine');
    if (tag) tag.hidden = !cfgAll()[s.c];
  });
  $('detail').addEventListener('click', e => {
    const s = selStock();
    if (!s || !e.target.closest('.cs-calc')) return;
    const cfg = cfgOf(s);
    const px = e.target.closest('[data-px]'), look = e.target.closest('[data-look]');
    if (e.target.closest('[data-reset]')) { cfgSave(s, { flows: [s.main], look: 12, x: null, opm: null }); return calcRender(s); }
    if (px) {
      const id = px.dataset.px;
      cfg.flows = cfg.flows.includes(id) ? cfg.flows.filter(x => x !== id) : [...cfg.flows, id];
      if (!cfg.flows.length) cfg.flows = [id];
      cfg.x = null;                                   // 프록시가 바뀌면 ① 은 새 프록시의 값으로
    } else if (look) cfg.look = +look.dataset.look;
    else return;
    e.stopPropagation();
    cfgSave(s, cfg);
    calcRender(s);
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
    try { trends = await U.json('data/trends.json'); } catch (e) { trends = null; }
    try { alt = await U.json('data/altdata.json'); } catch (e) { alt = null; }     // 공개 사이트에는 없다 → 카드 숨김
    $('msg').hidden = true;
    render();
  })();
})();
