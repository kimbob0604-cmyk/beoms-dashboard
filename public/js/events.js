// 이벤트 스터디 탭: data/events.json — 공시 종류별 공시 뒤 초과수익(시장 대비)
(() => {
  const WIN = [['pre', '사전', '공시 전 5거래일 (t-6→t-1) — 미리 오르면 정보가 새어 나갔을 수 있음'],
    ['d1', 'D+1', '공시 전날 종가 → 다음 거래일 종가'], ['d5', 'D+5', '공시 전날 종가 → 5거래일 뒤'], ['d20', 'D+20', '공시 전날 종가 → 20거래일 뒤']];
  const DEFAULTS = { g: 'earn_sp' };
  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, () => render());
  const st = pg.state;
  let data = null;

  const pct = (v, nd = 2) => (v == null ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(nd)}%`);
  const sig = s => s && s.t != null && Math.abs(s.t) >= 2 && s.n >= data.min_n;

  function cellHtml(s) {
    if (!s) return '<td class="num muted">–</td>';
    return `<td class="num ev-c${sig(s) ? ' sig' : ''}" title="평균 ${pct(s.mean)} · 중앙값 ${pct(s.med)} · 오른 비율 ${s.hit}% · t ${s.t ?? '–'} · ${s.n}건">
      <b class="${U.cls(s.mean)}">${pct(s.mean)}</b><small class="muted">중앙 ${pct(s.med, 1)} · ${s.hit}%↑</small></td>`;
  }

  function renderGroups() {
    const row = g => `<tr class="ev-row${g.key === st.g ? ' on' : ''}${g.n < data.min_n ? ' few' : ''}" data-g="${g.key}">
      <td><b>${U.esc(g.label)}</b><small class="muted">${U.esc(g.desc)}</small></td>
      <td class="num">${g.n.toLocaleString('ko-KR')}${g.n < data.min_n ? '<small class="muted">표본 적음</small>' : ''}</td>
      ${WIN.map(([k]) => cellHtml(g[k])).join('')}</tr>`;
    const base = data.groups.filter(g => !g.detail), detail = data.groups.filter(g => g.detail);
    $('groups').innerHTML = `<div class="col-head"><h3>공시 종류별 초과수익 <span class="muted">${data.from.replace(/-/g, '.')} ~ ${data.to.replace(/-/g, '.')}</span></h3>
        <span class="muted small">굵은 칸 = t값 2 이상 (우연이라 보기 어려움) · 칸에 마우스를 올리면 자세히</span></div>
      <div class="tbl-wrap"><table class="tbl ev-tbl">
        <thead><tr><th>공시 종류</th><th class="num">건수</th>${WIN.map(([, l, d]) => `<th class="num" title="${d}">${l}</th>`).join('')}</tr></thead>
        <tbody>${base.map(row).join('')}
          ${detail.length ? `<tr class="ev-sep"><td colspan="6">원문을 읽은 최근 공시로 나눈 세부 그룹 (잠정실적은 분기 컨센서스 대비)</td></tr>${detail.map(row).join('')}` : ''}
        </tbody></table></div>`;
  }

  function renderChart() {
    const g = data.groups.find(x => x.key === st.g) || data.groups[0];
    st.g = g.key;
    const T = data.path_t;
    $('chart').innerHTML = `<div class="sec-head"><div><h2>${U.esc(g.label)} <span class="muted small">${g.n}건 평균 누적 초과수익</span></h2>
        <p class="muted small">공시 전날(t=-1) 종가 = 0. 가로축은 공시일(t=0)부터의 거래일. 같은 시장 지수 대비.</p></div></div>
      <div class="ev-plot"></div>`;
    Plot.chart($('chart').querySelector('.ev-plot'), {
      n: T.length, height: 260, uid: 'ev',
      panes: [{ zero: true, fmt: v => pct(v, 1), series: [{ type: 'line', values: g.path, color: 'var(--accent)', width: 2, area: false, last: true }] }],
      xTicks: T.map((t, i) => [i, t === 0 ? '공시일' : `${t > 0 ? '+' : ''}${t}`]).filter(([, l], i) => T[i] % 5 === 0 || T[i] === -1),
      tip: i => `<div class="tt-h">t = ${T[i] > 0 ? '+' : ''}${T[i]}${T[i] === 0 ? ' (공시일)' : ''}</div><div class="tt-v">${pct(g.path[i])}</div>`,
    });
  }

  function renderRecent() {
    const g = data.groups.find(x => x.key === st.g);
    $('recent').innerHTML = `<div class="col-head"><h3>최근 사례 <span class="muted">${U.esc(g.label)} · 최근 ${g.recent.length}건</span></h3>
        <span class="muted small">아직 지나지 않은 구간은 –</span></div>
      <div class="tbl-wrap"><table class="tbl ev-rec">
        <thead><tr><th>공시일</th><th>종목</th><th>공시</th>${WIN.map(([, l]) => `<th class="num">${l}</th>`).join('')}</tr></thead>
        <tbody>${g.recent.map(e => `<tr ${Stock.hintAttr({ n: e.n, mk: e.mk, mc: e.mc })}>
          <td class="muted">${U.md(e.d)}</td>
          <td class="name-cell">${Stock.link(e)}<small class="muted">${e.mc ? U.eok(e.mc) : ''}</small></td>
          <td class="ev-t"><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${e.no}" target="_blank" rel="noopener">${U.esc(e.t)}</a></td>
          ${WIN.map(([k]) => `<td class="num ${U.cls(e[k])}">${pct(e[k], 1)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }

  function renderFoot() {
    $('foot').innerHTML = `
      <p>공시: DART 목록(정정·자회사 공시 제외, 같은 날 같은 회사 같은 종류는 한 건). 가격: KRX 일봉을 등락률로 이어 붙인 수정주가(권리락·무상증자·분할 반영). 시장: 코스피·코스닥 지수.</p>
      <p>평균은 한 건당 ±${data.clip}%로 잘라 계산하고 중앙값·오른 비율·t값을 함께 봅니다. 장중·장후 공시 모두 반응이 들어가도록 공시 전날 종가에서 잽니다. 거래비용·슬리피지는 빼지 않았습니다.</p>
      <p>현재 상장 종목만 있어(생존 편향) 상장폐지로 이어진 나쁜 사례가 빠집니다. 표본이 ${data.min_n}건보다 적은 그룹은 참고만 하세요. 과거 평균이 앞으로도 그렇다는 보장은 없습니다.</p>`;
  }

  function render() {
    renderGroups();
    renderChart();
    renderRecent();
    renderFoot();
  }

  $('groups').addEventListener('click', e => {
    const r = e.target.closest('[data-g]');
    if (r) pg.set({ g: r.dataset.g });
  });

  U.initTheme($('theme'));
  (async () => {
    try {
      data = await U.json('data/events.json');
    } catch (e) {
      $('msg').textContent = `이벤트 데이터를 불러오지 못했습니다. (${e.message})`;
      return;
    }
    $('msg').hidden = true;
    $('asof').textContent = `${U.dateLabel(data.to)}까지`;
    render();
  })();
})();
