// 펀더 탭: data/fund/index.json — 분기 비용 구조를 쌓아 둔 종목. 줄을 누르면 위에 표·브리지·리포트 문장이 열린다 (fund.js)
(() => {
  const $ = id => document.getElementById(id);
  const DEFAULTS = { q: '', sort: 'dq', c: '' };
  const pg = U.page(DEFAULTS, (patch, typing) => { if ('c' in patch) openDetail(); renderTable(); if (!typing) renderFilters(); });
  const st = pg.state;
  let data = null;
  const pp = v => (v == null ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%p`);

  function renderFilters() {
    $('filters').innerHTML = `<div class="frow">
      ${pg.seg('sort', [['dq', 'OPM 변화(직전 분기)'], ['dy', 'OPM 변화(전년 동기)'], ['mc', '시총 순'], ['opm', 'OPM 순']])}
      <input type="search" data-q="q" placeholder="종목명·코드 검색" value="${U.esc(st.q)}" autocomplete="off">
      <span class="muted small">${data.stocks.length}종목 · ${U.timeLabel(data.built)} 갱신</span></div>`;
  }

  function renderTable() {
    const q = st.q.trim().toLowerCase();
    const key = st.sort;
    const rows = data.stocks.filter(s => !q || s.n.toLowerCase().includes(q) || s.c.includes(q))
      .sort((a, b) => (key === 'mc' || key === 'opm' ? (b[key] ?? -1e9) - (a[key] ?? -1e9) : Math.abs(b[key] ?? 0) - Math.abs(a[key] ?? 0)));
    $('table').innerHTML = `<div class="col-head"><h3>쌓아 둔 종목 <span class="muted">${rows.length}</span></h3>
        <span class="muted small">줄을 누르면 분기 표가 열립니다 · 요인 = 직전 분기 대비 매출 대비 비중이 가장 크게 움직인 비용 (＋면 그만큼 OPM 을 깎음)</span></div>
      <div class="tbl-wrap"><table class="tbl fd-list">
        <thead><tr><th>종목</th><th class="num">시총</th><th class="num">최근 분기</th><th class="num">매출</th><th class="num">OP</th><th class="num">OPM</th>
          <th class="num">직전 분기 대비</th><th class="num">전년 동기 대비</th><th>큰 요인</th><th class="num">리포트 문장</th></tr></thead>
        <tbody>${rows.map(s => `<tr data-c="${s.c}" class="${st.c === s.c ? 'on' : ''}" ${Stock.hintAttr(s)}>
          <td class="name-cell"><b>${U.esc(s.n)}</b>${s.w ? `<small class="muted">${U.esc(s.w)}</small>` : ''}${s.chk ? '<i class="fd-warn" title="검증이 어긋난 분기가 있습니다">!</i>' : ''}</td>
          <td class="num">${s.mc != null ? U.eok(s.mc) : '–'}</td><td class="num">${s.ql} <small class="muted">${s.nq}분기</small></td>
          <td class="num">${s.rev == null ? '–' : Math.round(s.rev).toLocaleString('ko-KR')}</td>
          <td class="num ${s.op < 0 ? 'down' : ''}">${s.op == null ? '–' : Math.round(s.op).toLocaleString('ko-KR')}</td>
          <td class="num">${s.opm == null ? '–' : s.opm.toFixed(1) + '%'}</td>
          <td class="num"><b class="${U.cls(s.dq)}">${pp(s.dq)}</b></td><td class="num"><b class="${U.cls(s.dy)}">${pp(s.dy)}</b></td>
          <td>${(s.top || []).map(([g, v]) => `<span class="fd-chip">${g} <b class="${v > 0 ? 'down' : 'up'}">${pp(v)}</b></span>`).join('')}</td>
          <td class="num muted">${s.ev || ''}${s.cns ? ' · 컨센' : ''}</td></tr>`).join('') || '<tr><td colspan="10" class="muted">해당 종목 없음</td></tr>'}
        </tbody></table></div>
      ${data.skipped?.length ? `<p class="muted small" style="padding:8px 12px">성격별 비용 주석을 찾지 못한 종목 ${data.skipped.length}개 (대개 기능별로만 공시): ${data.skipped.map(x => U.esc(x.n)).join(' · ')}</p>` : ''}`;
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
    $('foot').innerHTML = `<p>출처: 금융감독원 DART 정기보고서 원문 주석(비용의 성격별 분류)과 XBRL(손익). 분기 값은 3개월 값, 없으면 누적끼리 뺀 값입니다. 연결이 있으면 연결, 없으면 별도.</p>
      <p>리포트 문장은 네이버 증권 리서치 요약에서 요인 낱말이 든 문장을 뽑은 것이고, 컨센서스는 네이버 종목분석(FnGuide) 분기 추정치입니다. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  })();
})();
