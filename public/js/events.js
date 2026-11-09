// 이벤트 스터디 탭: data/events.json — 공시 종류별 공시 뒤 초과수익(시장 대비)
(() => {
  const WIN = [['pre', '사전', '공시 전 5거래일 (t-6→t-1) — 미리 오르면 정보가 새어 나갔을 수 있음'],
    ['d0', '반응일', '반응일 하루 (t-1→t0). 장후 공시는 다음 거래일이 반응일'],
    ['d1', 'D+1', '공시 전날 종가 → 다음 거래일 종가'], ['d5', 'D+5', '공시 전날 종가 → 5거래일 뒤'], ['d20', 'D+20', '공시 전날 종가 → 20거래일 뒤']];
  const DEFAULTS = { g: 'earn_sp', ss: 'all', per: 'all', lmk: 'all', lq: '', ls: 'd', lo: 'desc' };
  const LIST_PAGE = 100;
  const lists = {};          // 종류별 기업 리스트 (data/events/{key}.json, 처음 누를 때 받음)
  let shown = LIST_PAGE;
  const $ = id => document.getElementById(id);
  // 검색창 입력 중에는 리스트 표만 다시 그린다 (검색창이 다시 그려지면 입력이 끊김)
  const pg = U.page(DEFAULTS, (patch, typing) => (typing ? renderListBody() : render()));
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
          ${detail.length ? `<tr class="ev-sep"><td colspan="${2 + WIN.length}">원문을 읽은 최근 공시로 나눈 세부 그룹 (잠정실적은 분기 컨센서스 대비)</td></tr>${detail.map(row).join('')}` : ''}
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

  // ---------- 종류를 누르면: 그 공시를 낸 기업 리스트 ----------
  const SS = [['all', '전체'], ['장전', '장전'], ['장중', '장중'], ['장후', '장후'], ['none', '시각 미상']];
  const PERS = [['all', '1년'], ['3m', '3개월'], ['1m', '1개월']];
  const LCOLS = [['d', '공시일'], ['d0', '반응일'], ['d1', 'D+1'], ['d5', 'D+5'], ['d20', 'D+20'], ['vx', '거래량'], ['pre', '사전']];

  function spark(ps, T) {
    const xs = ps.map((v, i) => [i, v]).filter(([, v]) => v != null);
    if (xs.length < 2) return '';
    const W = 96, H = 28, vals = xs.map(([, v]) => v / 10);
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals), span = hi - lo || 1;
    const X = i => (i / (T.length - 1)) * W, Y = v => H - 2 - ((v - lo) / span) * (H - 4);
    const pts = xs.map(([i, v]) => `${X(i).toFixed(1)},${Y(v / 10).toFixed(1)}`).join(' ');
    const last = vals[vals.length - 1], t0 = T.indexOf(0);
    return `<svg class="ev-spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
      <line x1="0" x2="${W}" y1="${Y(0)}" y2="${Y(0)}" class="z"/><line x1="${X(t0)}" x2="${X(t0)}" y1="0" y2="${H}" class="t0"/>
      <polyline points="${pts}" class="${last >= 0 ? 'up' : 'dn'}"/></svg>`;
  }

  function listRows(L) {
    const q = st.lq.trim().toLowerCase();
    const since = st.per === 'all' ? '' : (() => {
      const d = new Date(`${data.to}T00:00:00`);
      d.setMonth(d.getMonth() - (st.per === '3m' ? 3 : 1));
      return d.toISOString().slice(0, 10);
    })();
    const rows = L.rows.filter(e => (st.ss === 'all' || (st.ss === 'none' ? !e.ss : e.ss === st.ss))
      && (!since || e.d >= since) && (st.lmk === 'all' || e.mk === st.lmk)
      && (!q || e.n.toLowerCase().includes(q) || e.c.includes(q)));
    const sign = st.lo === 'asc' ? -1 : 1;
    const key = st.ls === 'd' ? e => `${e.d} ${e.tm || ''}` : e => e[st.ls];
    return rows.sort((a, b) => {
      const x = key(a), y = key(b);
      if (x == null) return y == null ? 0 : 1;
      if (y == null) return -1;
      return sign * (typeof x === 'string' ? (y > x ? 1 : y < x ? -1 : 0) : y - x);
    });
  }

  async function renderRecent() {
    const g = data.groups.find(x => x.key === st.g);
    const box = $('recent');
    if (!lists[g.key]) {
      box.innerHTML = `<div class="col-head"><h3>${U.esc(g.label)} 기업 리스트</h3></div><p class="msg">불러오는 중…</p>`;
      try { lists[g.key] = await U.json(`data/events/${g.key}.json`); } catch (e) {
        box.innerHTML = `<p class="msg">리스트를 불러오지 못했습니다. (${e.message})</p>`;
        return;
      }
      if (st.g !== g.key) return;
    }
    const L = lists[g.key];
    const ssStat = Object.entries(g.by_ss || {}).map(([k, v]) =>
      `<span class="chip">${k} ${v.n}건 · 반응일 평균 <b class="${U.cls(v.mean)}">${pct(v.mean)}</b></span>`).join('');
    const th = (k, l) => `<th class="num" data-sort="${k}">${l}${st.ls === k ? (st.lo === 'asc' ? ' ▲' : ' ▼') : ''}</th>`;
    box.innerHTML = `<div class="col-head ev-lhead"><div><h3>${U.esc(g.label)} 기업 리스트 <span class="muted"><span id="lcount"></span>건 / 전체 ${L.rows.length.toLocaleString('ko-KR')}건</span></h3>
        <p class="muted small">공시 시각(KIND)을 확인한 공시 ${g.timed.toLocaleString('ko-KR')}건 · 장후 공시는 다음 거래일이 반응일 · 초과수익은 같은 시장 지수 대비 · 머리글을 누르면 정렬</p></div></div>
      <div class="ev-lfilter">${pg.seg('ss', SS)}${pg.seg('per', PERS)}${pg.seg('lmk', [['all', '전체'], ['KOSPI', '코스피'], ['KOSDAQ', '코스닥']])}
        <input type="search" data-q="lq" placeholder="종목명·코드" value="${U.esc(st.lq)}" autocomplete="off"></div>
      ${ssStat ? `<div class="dt-chips ev-ss">${ssStat}</div>` : ''}
      <div id="lbody"></div>`;
    renderListBody();
  }

  function renderListBody() {
    const L = lists[st.g], el = $('lbody');
    if (!L || !el) return;
    const rows = listRows(L);
    $('lcount').textContent = rows.length.toLocaleString('ko-KR');
    const th = (k, l) => `<th class="num" data-sort="${k}">${l}${st.ls === k ? (st.lo === 'asc' ? ' ▲' : ' ▼') : ''}</th>`;
    el.innerHTML = `<div class="tbl-wrap"><table class="tbl ev-list">
        <thead><tr><th data-sort="d">공시일·시각${st.ls === 'd' ? (st.lo === 'asc' ? ' ▲' : ' ▼') : ''}</th><th>종목</th><th>공시 · 핵심 내용</th>
          ${LCOLS.slice(1).map(([k, l]) => th(k, l)).join('')}<th>t-5 ~ t+20</th></tr></thead>
        <tbody>${rows.slice(0, shown).map(e => `<tr ${Stock.hintAttr({ n: e.n, mk: e.mk, mc: e.mc })}>
          <td class="ev-when"><b>${U.md(e.d)}</b>${e.tm ? ` <span>${e.tm}</span>` : ''}
            ${e.ss ? `<small class="dt-tag${e.ss === '장후' ? ' down' : e.ss === '장전' ? ' up' : ''}">${e.ss}</small>` : '<small class="muted">시각 미상</small>'}
            ${e.rd && e.rd !== e.d ? `<small class="muted">반응 ${U.md(e.rd)}</small>` : ''}</td>
          <td class="name-cell">${Stock.link(e)}<small class="muted">${e.mc ? U.eok(e.mc) : ''}</small></td>
          <td class="ev-t"><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${e.no}" target="_blank" rel="noopener">${U.esc(e.t)}</a>
            ${e.tag ? `<span class="dt-tag ${e.tag === '서프' ? 'up' : 'down'}">${e.tag}</span>` : ''}
            ${e.info ? `<small class="ev-info">${U.num(e.info)}</small>` : ''}</td>
          <td class="num"><b class="${U.cls(e.d0)}">${pct(e.d0, 1)}</b>${e.r0 != null ? `<small class="muted">주가 ${pct(e.r0, 1)}</small>` : ''}</td>
          ${['d1', 'd5', 'd20'].map(k => `<td class="num"><b class="${U.cls(e[k])}">${pct(e[k], 1)}</b></td>`).join('')}
          <td class="num">${e.vx != null ? `<b class="${e.vx >= 3 ? 'ev-hot' : ''}">${e.vx}배</b>` : '<span class="muted">–</span>'}</td>
          <td class="num"><span class="${U.cls(e.pre)}">${pct(e.pre, 1)}</span></td>
          <td>${spark(e.p, L.path_t)}</td></tr>`).join('')}</tbody></table></div>
      ${rows.length > shown ? `<button class="more" id="lmore">${Math.min(LIST_PAGE, rows.length - shown)}건 더 보기 (${shown}/${rows.length})</button>` : ''}`;
  }

  function renderFoot() {
    $('foot').innerHTML = `
      <p>공시: DART 목록(정정·자회사 공시 제외, 같은 날 같은 회사 같은 종류는 한 건). 가격: KRX 일봉을 등락률로 이어 붙인 수정주가(권리락·무상증자·분할 반영). 시장: 코스피·코스닥 지수.</p>
      <p>평균은 한 건당 ±${data.clip}%로 잘라 계산하고 중앙값·오른 비율·t값을 함께 봅니다. 공시 시각(KIND)으로 장전·장중·장후를 나누고 장후 공시는 다음 거래일을 반응일로 봅니다(시각을 모르면 공시일). 반응일 전날 종가에서 잽니다. 거래비용·슬리피지는 빼지 않았습니다.</p>
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
    if (r) { shown = LIST_PAGE; pg.set({ g: r.dataset.g }); }
  });
  // 기업 리스트: 필터(pg.bind), 머리글 정렬(같은 머리글 다시 누르면 반대), 더 보기
  pg.bind($('recent'));
  $('recent').addEventListener('click', e => {
    const h = e.target.closest('th[data-sort]');
    if (h) {
      st.lo = st.ls === h.dataset.sort && st.lo === 'desc' ? 'asc' : 'desc';
      st.ls = h.dataset.sort;
      pg.write(); shown = LIST_PAGE; return renderListBody();
    }
    if (e.target.closest('#lmore')) { shown += LIST_PAGE; renderListBody(); }
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
