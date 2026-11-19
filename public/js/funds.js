// 펀더 탭: data/fund/index.json — 분기 비용 구조를 쌓아 둔 종목. 줄을 누르면 위에 표·브리지·리포트 문장이 열린다 (fund.js)
(() => {
  const $ = id => document.getElementById(id);
  const DEFAULTS = { q: '', sort: 'dq', c: '', ix: 'all', ec: 'all', w: '', view: 'list' };
  // @darthacking 실적 글 기준 판정 (실적 발표 덱과 같은 기준: 매출 ±5%, 영업이익 ±10%·흑적자 전환)
  const CASE = { both: ['동반 서프', 'up'], op: ['영업이익 서프', 'up'], sales: ['매출 서프', 'up'], miss: ['영업이익 미스', 'down'], inline: ['부합', 'muted'] };
  const pg = U.page(DEFAULTS, (patch, typing) => { if ('c' in patch) openDetail(); renderTable(); if (!typing) renderFilters(); });
  const st = pg.state;
  let data = null;
  const pp = v => (v == null ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%p`);

  const NOW = '업종 없음';
  const sec = s => s.w || NOW;
  function renderFilters() {
    const cnt = {};
    data.stocks.forEach(s => { cnt[sec(s)] = (cnt[sec(s)] || 0) + 1; });
    const opts = Object.entries(cnt).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ko'))
      .map(([w, n]) => `<option value="${U.esc(w)}"${st.w === w ? ' selected' : ''}>${U.esc(w)} (${n})</option>`).join('');
    $('filters').innerHTML = `<div class="frow">
      ${pg.seg('view', [['list', '종목'], ['sector', '업종별 요약']])}
      <select data-sel="w" aria-label="업종"><option value="">업종 전체 (${Object.keys(cnt).length}개)</option>${opts}</select>
    </div><div class="frow">
      ${pg.seg('ix', [['all', '전체'], ['코스피200', '코스피200'], ['코스닥150', '코스닥150'], ['etc', '그 밖']])}
      ${pg.seg('ec', [['all', '실적 전체'], ['beat', '서프'], ['miss', '미스'], ['inline', '부합'], ['none', '예상치 없음']])}
      ${pg.seg('sort', [['dq', 'OPM 변화(직전 분기)'], ['dy', 'OPM 변화(전년 동기)'], ['mc', '시총 순'], ['opm', 'OPM 순']])}
      <input type="search" data-q="q" placeholder="종목명·코드 검색" value="${U.esc(st.q)}" autocomplete="off">
      <span class="muted small">${data.stocks.length}종목${data.pending ? ` · 아직 받는 중 ${data.pending}종목` : ''} · ${U.timeLabel(data.built)} 갱신</span></div>`;
  }

  // 업종별 요약: 업종마다 종목 수, 최근 분기 OPM·변화 중앙값, @darthacking 판정 수, 시총 큰 종목. 줄을 누르면 그 업종 종목 목록으로
  const med = a => { const v = a.filter(x => x != null).sort((x, y) => x - y); return v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null; };
  function renderSectors(list, cur) {
    const by = {};
    list.forEach(s => (by[sec(s)] = by[sec(s)] || []).push(s));
    const beat = s => cur(s) && ['both', 'op', 'sales'].includes(s.eq.case), miss = s => cur(s) && s.eq.case === 'miss';
    const rows = Object.entries(by).map(([w, a]) => ({ w, a, mc: a.reduce((t, s) => t + (s.mc || 0), 0), opm: med(a.map(s => s.opm)), dq: med(a.map(s => s.dq)), dy: med(a.map(s => s.dy)),
      b: a.filter(beat).length, m: a.filter(miss).length, i: a.filter(s => cur(s) && s.eq.case === 'inline').length }))
      .sort((x, y) => (st.sort === 'mc' ? y.mc - x.mc : st.sort === 'opm' ? (y.opm ?? -1e9) - (x.opm ?? -1e9) : Math.abs(y[st.sort] ?? 0) - Math.abs(x[st.sort] ?? 0)));
    $('table').innerHTML = `<div class="col-head"><h3>업종별 요약 <span class="muted">${rows.length}개 업종 · ${list.length}종목</span></h3>
        <span class="muted small">네이버 증권 업종 기준 · 값은 업종 안 종목의 중앙값 · 줄을 누르면 그 업종 종목만 봅니다</span></div>
      <div class="tbl-wrap"><table class="tbl fd-list fd-sec-list">
        <thead><tr><th>업종</th><th class="num">종목</th><th class="num">시총 합</th><th class="num">OPM</th><th class="num">직전 분기 대비</th><th class="num">전년 동기 대비</th><th title="@darthacking 실적 글 기준 최근 분기 판정 수">서프 · 미스 · 부합</th><th>시총 큰 종목</th></tr></thead>
        <tbody>${rows.map(r => `<tr data-w="${U.esc(r.w)}"><td class="name-cell"><b>${U.esc(r.w)}</b></td><td class="num">${r.a.length}</td><td class="num">${U.eok(r.mc)}</td>
          <td class="num">${r.opm == null ? '–' : r.opm.toFixed(1) + '%'}</td><td class="num"><b class="${U.cls(r.dq)}">${pp(r.dq)}</b></td><td class="num"><b class="${U.cls(r.dy)}">${pp(r.dy)}</b></td>
          <td>${r.b ? `<span class="fd-chip up">서프 ${r.b}</span>` : ''}${r.m ? `<span class="fd-chip down">미스 ${r.m}</span>` : ''}${r.i ? `<span class="fd-chip">부합 ${r.i}</span>` : ''}${!r.b && !r.m && !r.i ? '<small class="muted">예상치 없음</small>' : ''}</td>
          <td class="small">${r.a.slice().sort((x, y) => (y.mc || 0) - (x.mc || 0)).slice(0, 4).map(s => `<span ${Stock.hintAttr(s)}>${Stock.link(s)}</span>`).join(' · ')}</td></tr>`).join('') || '<tr><td colspan="8" class="muted">해당 종목 없음</td></tr>'}
        </tbody></table></div>`;
  }

  function renderTable() {
    const q = st.q.trim().toLowerCase();
    const key = st.sort;
    const inIx = s => st.ix === 'all' || (st.ix === 'etc' ? !(s.ix || []).length : (s.ix || []).includes(st.ix));
    const latest = data.stocks.reduce((m, s) => (s.eq && s.eq.q.slice(2) + s.eq.q[0] > m ? s.eq.q.slice(2) + s.eq.q[0] : m), '');
    const cur = s => s.eq && s.eq.q.slice(2) + s.eq.q[0] === latest;       // 가장 최근 분기의 판정만 필터에 쓴다
    const inEc = s => st.ec === 'all' || (st.ec === 'none' ? !cur(s) : cur(s) && (st.ec === 'beat' ? ['both', 'op', 'sales'].includes(s.eq.case) : s.eq.case === st.ec));
    const inW = s => !st.w || sec(s) === st.w;
    if (st.view === 'sector') return renderSectors(data.stocks.filter(s => inIx(s) && inEc(s) && (!q || s.n.toLowerCase().includes(q) || s.c.includes(q))), cur);
    const rows = data.stocks.filter(s => inIx(s) && inEc(s) && inW(s) && (!q || s.n.toLowerCase().includes(q) || s.c.includes(q)))
      .sort((a, b) => (key === 'mc' || key === 'opm' ? (b[key] ?? -1e9) - (a[key] ?? -1e9) : Math.abs(b[key] ?? 0) - Math.abs(a[key] ?? 0)));
    $('table').innerHTML = `<div class="col-head"><h3>${st.w ? `${U.esc(st.w)} <button class="icon-btn fd-wclear" title="업종 필터 풀기">✕</button>` : '쌓아 둔 종목'} <span class="muted">${rows.length}</span></h3>
        <span class="muted small">종목명을 누르면 종목 설명, 줄의 다른 곳을 누르면 분기 표가 열립니다 · 요인 = 직전 분기 대비 매출 대비 비중이 가장 크게 움직인 비용 (＋면 그만큼 OPM 을 깎음)</span></div>
      <div class="tbl-wrap"><table class="tbl fd-list">
        <thead><tr><th>종목</th><th class="num">시총</th><th class="num">최근 분기</th><th class="num">매출</th><th class="num">OP</th><th class="num">OPM</th>
          <th class="num">직전 분기 대비</th><th class="num">전년 동기 대비</th><th title="@darthacking 실적 글의 예상치 대비 (영업이익 · 매출)">실적 vs 예상</th><th>큰 요인</th><th class="num" title="리포트 문장 수 · 다음 분기 컨센서스 · 부문(제품·지역)별 매출이 있는지">리포트 · 컨센 · 부문</th></tr></thead>
        <tbody>${rows.map(s => `<tr data-c="${s.c}" class="${st.c === s.c ? 'on' : ''}" ${Stock.hintAttr(s)}>
          <td class="name-cell"><b>${Stock.link(s)}</b>${(s.ix || []).map(x => `<span class="tag">${x}</span>`).join('')}${s.w ? `<small class="muted fd-w" data-w="${U.esc(s.w)}" title="이 업종만 보기">${U.esc(s.w)}</small>` : ''}${s.chk ? `<i class="fd-warn" title="검증이 어긋난 분기 ${s.chk}개 — 종목을 열면 사유가 보입니다">!</i>` : ''}</td>
          <td class="num">${s.mc != null ? U.eok(s.mc) : '–'}</td><td class="num">${s.ql} <small class="muted">${s.nq}분기</small></td>
          <td class="num">${s.rev == null ? '–' : Math.round(s.rev).toLocaleString('ko-KR')}</td>
          <td class="num ${s.op < 0 ? 'down' : ''}">${s.op == null ? '–' : Math.round(s.op).toLocaleString('ko-KR')}</td>
          <td class="num">${s.opm == null ? '–' : s.opm.toFixed(1) + '%'}</td>
          <td class="num"><b class="${U.cls(s.dq)}">${pp(s.dq)}</b></td><td class="num"><b class="${U.cls(s.dy)}">${pp(s.dy)}</b></td>
          <td>${s.eq ? `<span class="fd-chip ${CASE[s.eq.case]?.[1] || ''}">${s.eq.q} ${CASE[s.eq.case]?.[0] || '–'}</span><small class="muted"> 영익 ${s.eq.or == null ? '–' : (s.eq.or > 0 ? '+' : '') + (s.eq.or * 100).toFixed(0) + '%'} · 매출 ${s.eq.sr == null ? '–' : (s.eq.sr > 0 ? '+' : '') + (s.eq.sr * 100).toFixed(0) + '%'}</small>` : '<small class="muted">예상치 없음</small>'}</td>
          <td>${(s.top || []).map(([g, v]) => `<span class="fd-chip">${g} <b class="${v > 0 ? 'down' : 'up'}">${pp(v)}</b></span>`).join('')}</td>
          <td class="num muted">${s.ev || ''}${s.cns ? ' · 컨센' : ''}${s.seg?.length ? ` · ${s.seg[0]}` : ''}</td></tr>`).join('') || '<tr><td colspan="11" class="muted">해당 종목 없음</td></tr>'}
        </tbody></table></div>
      ${data.skipped?.length ? `<p class="muted small" style="padding:8px 12px">비용 주석을 찾지 못한 종목 ${data.skipped.length}개 —
        금융사(이 주석이 없음): ${data.skipped.filter(x => x.fin).map(x => U.esc(x.n)).join(' · ') || '없음'}<br>
        그 밖: ${data.skipped.filter(x => !x.fin).map(x => U.esc(x.n)).join(' · ') || '없음'}</p>` : ''}`;
  }

  async function openDetail() {
    const box = $('detail');
    if (!st.c) { box.hidden = true; return; }
    const d = await Fund.load(st.c);
    if (!d) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = `<div class="fd-dhead"><h2>${Stock.link({ c: d.c, n: d.n })} <span class="muted small">${d.mc != null ? U.eok(d.mc) : ''} · ${d.q.length}분기</span></h2>
      <button class="icon-btn" id="fd-close" title="닫기">✕</button></div><div id="fd-body"></div>`;
    Fund.render($('fd-body'), d);
    box.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  $('table').addEventListener('click', e => {
    if (e.target.closest('a[data-code]')) return;
    if (e.target.closest('.fd-wclear')) return pg.set({ w: '' });
    const w = e.target.closest('[data-w]');
    if (w) return pg.set({ w: w.dataset.w, view: 'list' });
    const tr = e.target.closest('tr[data-c]');
    if (tr) pg.set({ c: tr.dataset.c });
  });
  $('detail').addEventListener('click', e => { if (e.target.closest('#fd-close')) pg.set({ c: '' }); });

  pg.bind($('filters'));
  U.initTheme($('theme'));
  (async () => {
    try { data = await U.json('data/fund/index.json'); } catch (e) { $('msg').textContent = '펀더 데이터를 불러오지 못했습니다.'; return; }
    $('msg').hidden = true;
    renderFilters();
    renderTable();
    openDetail();
    // 1분마다(화면이 보일 때) 데이터·시세가 바뀌었으면 다시 그린다 (U.live, 2026-11-19)
    U.live(['data/fund/index.json'], async () => {
      data = await U.json('data/fund/index.json');
      U.forget('data/fund/', ['data/fund/index.json']);   // 종목별 상세도 다음에 열 때 새로
      renderFilters();
      renderTable();
    });
    $('foot').innerHTML = `<p>출처: 금융감독원 DART 정기보고서 원문 주석(비용의 성격별 분류)과 XBRL(손익). 분기 값은 3개월 값, 없으면 누적끼리 뺀 값입니다. 연결이 있으면 연결, 없으면 별도.</p>
      <p>코스피200·코스닥150 구성: ${U.esc(data.ix_as_of || '')}. 지수 정기변경(6월·12월) 뒤에는 목록을 다시 맞춰야 합니다.</p>
      <p>리포트 문장은 네이버 증권 리서치 요약에서 요인 낱말이 든 문장을 뽑은 것이고, 컨센서스는 네이버 종목분석(FnGuide) 분기 추정치입니다. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  })();
})();
