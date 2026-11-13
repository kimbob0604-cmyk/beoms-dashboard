// 탐방 노트 탭: data/visits.json (build_visits.py) — 내 텔레그램 방에서 '탐방'이 들어간 글을 종목별로 모은 것
// - 종목 카드: 시총(주가 아님), POR = 시총 ÷ 영업이익 표(전년 실적~내후년 추정), 탐방 당시 시총 → 지금 시총
// - 글: 직접 쓴 요약(visit_notes.json)이 있으면 요약, 그 아래 숫자가 든 핵심 줄, 원문은 접어 둔다
// - 차트: data/vchart/{code}.json (collect_visits_chart.py — 네이버 일봉 500거래일). 축은 시총(주가 × 지금 주식 수),
//   탐방 노트가 올라온 날에 세로 점선과 점. 점을 누르면 그 노트로 간다. 카드가 화면에 들어올 때 받아 그린다
// 글 원문이 들어가므로 공개 배포에서는 빠진다(publish_hold.txt). 데이터가 없으면 준비 방법을 보여 준다.
(() => {
  const MARKETS = { KOSPI: '코스피', KOSDAQ: '코스닥' };
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };
  const PERS = [['30', '1개월'], ['90', '3개월'], ['365', '1년'], ['all', '전체']];
  const SORTS = {
    recent: ['최근 탐방 순', c => c.shown[0].d, true],
    n: ['노트 많은 순', c => c.shown.length, true],
    por: ['내년 POR 낮은 순', c => porNext(c), false],
    chg: ['탐방 뒤 시총 변화 순', c => since(c, c.shown[0]), true],
    mc: ['시총 순', c => c.mc, true],
  };
  const DEFAULTS = { per: '90', sort: 'recent', kind: 'note', market: 'all', cap: 'all', room: '', q: '', rng: '1y' };
  const RNG = { '6m': 126, '1y': 252, '2y': 500 };   // 차트 기간 (거래일)
  const FOLD = 2;          // 종목마다 처음 펼쳐 둘 글 수

  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => (typing ? renderList() : render()));
  const st = pg.state;
  let data = null;
  const open = new Set();  // '노트 더 보기'를 누른 종목

  // ---------- 계산 ----------
  const opNext = c => c.ops?.find(x => x[0] === c.fy0 + 1)?.[1];
  const porNext = c => (c.mc && opNext(c) > 0 ? c.mc / opNext(c) : null);
  const since = (c, n) => (c.mc && n?.mc0 ? c.mc / n.mc0 - 1 : null);

  function cutoff() {
    if (st.per === 'all') return '';
    const t = new Date(Date.now() - +st.per * 864e5);
    return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
  }

  function noteOk(n, from, q, name = '') {
    if (from && n.d < from) return false;
    if (st.kind === 'note' && n.k !== 'note') return false;
    if (st.room && !n.rooms.includes(st.room)) return false;
    if (q && !name.includes(q) && !n.t.toLowerCase().includes(q) && !(n.x || '').toLowerCase().includes(q)) return false;
    return true;
  }

  function filtered() {
    const from = cutoff(), q = st.q.trim().toLowerCase(), cap = CAPS[st.cap];
    const [, key, desc] = SORTS[st.sort];
    const cos = data.cos.filter(c => {
      if (st.market !== 'all' && c.mk !== st.market) return false;
      if (cap && (c.mc == null || c.mc < cap[0] || c.mc >= cap[1])) return false;
      return true;
    }).map(c => ({ ...c, shown: c.notes.filter(n => noteOk(n, from, q, `${c.n} ${c.c}`.toLowerCase())) }))
      .filter(c => c.shown.length)
      .sort((a, b) => {
        const x = key(a), y = key(b);
        if (x == null) return y == null ? 0 : 1;
        if (y == null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * (desc ? -1 : 1);
      });
    const etc = st.market === 'all' && st.cap === 'all' ? data.etc.filter(n => noteOk(n, from, q)) : [];
    return { cos, etc };
  }

  // ---------- 그리기 ----------
  function renderFilters() {
    const rooms = data.rooms.map(([r, n]) => `<option value="${U.esc(r)}"${st.room === r ? ' selected' : ''}>${U.esc(r)} (${n})</option>`).join('');
    $('filters').innerHTML = `
      <div class="frow">
        ${pg.seg('per', PERS)}
        ${pg.seg('kind', [['note', '탐방 노트만', '제목(처음 세 줄)에 탐방이 있는 글'], ['all', '언급 글 포함', '본문에서 탐방을 한 줄 언급한 글(신고가 알림·뉴스·리포트 목록)까지']])}
        ${pg.seg('sort', Object.entries(SORTS).map(([k, [l]]) => [k, l]))}
      </div>
      <div class="frow">
        ${pg.seg('market', [['all', '전체'], ['KOSPI', '코스피'], ['KOSDAQ', '코스닥']])}
        ${pg.seg('cap', [['all', '시총 전체'], ['L', '1조 이상'], ['M', '3천억~1조'], ['S', '3천억 미만']])}
        <select data-sel="room" aria-label="방"><option value="">모든 방</option>${rooms}</select>
        <input type="search" data-q="q" placeholder="종목·본문 검색" value="${U.esc(st.q)}" autocomplete="off">
        ${pg.seg('rng', [['6m', '차트 6개월'], ['1y', '1년'], ['2y', '2년']])}
      </div>`;
  }

  const chg = v => (v == null ? '' : `<b class="${U.cls(v)}">${U.pct(v)}</b>`);

  function noteHtml(n, c) {
    const s = c ? since(c, n) : null;
    return `<li class="vs-note" id="${noteDomId(n)}">
      <div class="vs-note-head"><b>${U.dateLabel(n.d)}</b><span>${n.tm}</span>
        <span>${n.dm ? '<span class="pill">1:1</span> ' : ''}${n.rooms.map(U.esc).join(' · ')}</span>${n.k === 'mention' ? '<span class="pill">언급</span>' : ''}${n.fwd && !n.rooms.includes(n.fwd) ? `<span>출처 ${U.esc(n.fwd)}</span>` : ''}
        ${n.mc0 ? `<span>당시 시총 <b>${U.eok(n.mc0)}</b>${s != null ? ` → 지금 ${chg(s)}` : ''}</span>` : ''}
        ${n.link ? `<a href="${U.esc(n.link)}" target="_blank" rel="noopener">텔레그램에서 열기 ↗</a>` : ''}</div>
      <p class="vs-title">${U.esc(n.t)}</p>
      ${n.sum ? `<p class="vs-sum">${U.num(n.sum)}</p>` : ''}
      ${n.lines.length ? `<ul class="vs-lines">${n.lines.map(l => `<li>${U.num(l)}</li>`).join('')}</ul>` : ''}
      ${n.also?.length ? `<p class="vs-also">함께 나온 종목: ${n.also.map(a => Stock.link(a)).join(', ')}</p>` : ''}
      ${n.x ? `<details><summary>원문 보기 (${n.x.length.toLocaleString('ko-KR')}자)</summary><pre class="vs-text">${U.esc(n.x)}</pre></details>`
        : n.lim ? `<p class="vs-also">공개 채널 글이라 제목만 싣습니다${n.link ? ` · <a href="${U.esc(n.link)}" target="_blank" rel="noopener">원문은 채널에서 ↗</a>` : ''}</p>` : ''}
    </li>`;
  }

  function coHtml(c) {
    const last = c.shown[0], s = since(c, last);
    const por = U.porTable(c.mc, c);
    const all = open.has(c.c) || c.shown.length <= FOLD;
    return `<article class="card vs-co" ${Stock.hintAttr(c)}>
      <div class="vs-head">
        <div class="vs-name">
          <h3>${Stock.link(c)}<small class="muted">${c.c}</small></h3>
          <p>${[MARKETS[c.mk], c.w, `탐방 노트 ${c.shown.length}건`, `최근 ${U.dateLabel(last.d)}`].filter(Boolean).map(U.esc).join(' · ')}</p>
        </div>
        ${s != null ? `<div class="vs-since"><small>최근 탐방(${U.md(last.d)}) 뒤 시총</small>${chg(s)}<small>${U.eok(last.mc0)} → ${U.eok(c.mc)}</small></div>` : ''}
        <div class="vs-cap"><small>시총</small><b>${U.eok(c.mc)}</b>${c.ch != null ? `<small class="${U.cls(c.ch)}">${c.ch > 0 ? '+' : ''}${c.ch.toFixed(2)}%</small>` : ''}</div>
      </div>
      <div class="vs-body">
        <div>${por || '<p class="vs-nopor">영업이익 컨센서스가 없어 POR 을 계산하지 못합니다.</p>'}</div>
        <div class="vs-chart" data-chart="${c.c}"><div class="vs-plot"><p class="muted small">차트 불러오는 중…</p></div><p class="vs-chart-note small muted"></p></div>
      </div>
      <ul class="vs-notes">${(all ? c.shown : c.shown.slice(0, FOLD)).map(n => noteHtml(n, c)).join('')}</ul>
      ${all ? '' : `<button class="vs-more" data-more="${c.c}">노트 ${c.shown.length - FOLD}건 더 보기</button>`}
    </article>`;
  }

  // ---------- 차트 ----------
  const noteDomId = n => `vn-${n.id.replace(/[^0-9a-zA-Z]/g, '_')}`;
  const ymd = d => +d.replace(/-/g, '');
  let lastCos = [];       // 지금 화면에 그린 종목 (차트가 카드의 노트 목록을 찾을 때)
  const seen = new IntersectionObserver(es => {
    for (const e of es) {
      if (!e.isIntersecting) continue;
      seen.unobserve(e.target);
      drawChart(e.target);
    }
  }, { rootMargin: '300px' });

  async function drawChart(box) {
    const c = lastCos.find(x => x.c === box.dataset.chart);
    const el = box.querySelector('.vs-plot');
    if (!c) return;
    let x;
    try { x = await U.json(`data/vchart/${c.c}.json`); } catch (e) { el.innerHTML = '<p class="muted small">차트 데이터 없음</p>'; return; }
    if (!box.isConnected) return;
    const from = Math.max(0, x.d.length - RNG[st.rng]);
    const d = x.d.slice(from), close = x.c.slice(from), vol = x.v.slice(from);
    const k = c.mc && c.p ? c.mc / c.p : null;                       // 주가 1원당 시총(억)
    const val = v => (v == null ? null : k ? v * k : v);
    const fmt = v => (k ? U.eok(v) : Math.round(v).toLocaleString('ko-KR'));
    // 노트 날짜 → 그날(휴일이면 다음 거래일) 칸. 차트 범위 밖의 노트는 뺀다
    const byI = new Map();
    for (const n of c.shown) {
      const t = ymd(n.d);
      if (t < d[0]) continue;
      let i = d.findIndex(v => v >= t);
      if (i < 0) i = d.length - 1;
      if (!byI.has(i)) byI.set(i, []);
      byI.get(i).push(n);
    }
    const marks = [...byI].map(([i, ns]) => ({ i, v: val(close[i]), n: ns.length, notes: ns }));
    Plot.chart(el, {
      n: d.length, height: 210, uid: `vc${c.c}`,
      panes: [
        { h: 3.2, fmt, series: [{ type: 'line', values: close.map(val), color: 'var(--text)', width: 1.4 }] },
        { h: 1, fmt: v => (v >= 1e4 ? `${Math.round(v / 1e4).toLocaleString('ko-KR')}만` : `${Math.round(v)}`),
          series: [{ type: 'bar', values: vol, cls: i => (i && close[i] < close[i - 1] ? 'dn' : 'up') }] },
      ],
      xTicks: Plot.monthTicks(d),
      marks,
      tip: i => {
        const ns = byI.get(i);
        return `<div class="tt-h">${Plot.dateStr(d[i])}</div>
          <div class="tt-v">${k ? `시총 ${fmt(val(close[i]))}` : fmt(close[i])}</div>
          ${k ? `<div class="muted">주가 ${Math.round(close[i]).toLocaleString('ko-KR')}</div>` : ''}
          ${ns ? `<div class="vs-tt-notes"><b>탐방 노트 ${ns.length}건</b>${ns.slice(0, 3).map(n => `<div>${U.esc(n.t.slice(0, 34))}</div>`).join('')}</div>` : ''}`;
      },
      onMark: m => {
        if (!open.has(c.c) && c.shown.indexOf(m.notes[0]) >= FOLD) { open.add(c.c); renderList(); }
        const li = document.getElementById(noteDomId(m.notes[0]));
        if (!li) return;
        li.scrollIntoView({ behavior: 'smooth', block: 'center' });
        li.classList.add('flash');
        setTimeout(() => li.classList.remove('flash'), 1600);
      },
    });
    const first = c.shown[c.shown.length - 1], last = c.shown[0];
    const part = (lbl, n) => (since(c, n) == null ? '' : `${lbl}(${U.md(n.d)}) 뒤 시총 ${chg(since(c, n))}`);
    box.querySelector('.vs-chart-note').innerHTML = [
      c.shown.length > 1 ? part('첫 탐방', first) : '', part(c.shown.length > 1 ? '최근 탐방' : '탐방', last),
      '점선 = 탐방 노트가 올라온 날 · 축은 시총(주가 × 지금 주식 수)',
      `<a href="https://finance.naver.com/item/fchart.naver?code=${c.c}" target="_blank" rel="noopener">네이버 증권 차트 ↗</a>`,
    ].filter(Boolean).join(' · ');
  }

  function renderList() {
    const { cos, etc } = filtered();
    lastCos = cos;
    const nNotes = cos.reduce((a, c) => a + c.shown.length, 0) + etc.length;
    $('meta').innerHTML = `<span><b>${cos.length}</b>종목 · 탐방 노트 <b>${nNotes}</b>건</span>
      <span>${data.rooms.length}개 방 · ${data.since ? `${data.since.slice(2, 4)}년 ${U.dateLabel(data.since)}부터` : ''}</span>
      <span>수집 ${data.collected_at ? U.timeLabel(data.collected_at) : '–'} · 시총 ${U.dateLabel(data.date)} 기준</span>`;
    $('list').innerHTML = cos.map(coHtml).join('')
      + (etc.length ? `<article class="card vs-co"><div class="vs-head"><div class="vs-name"><h3>종목을 정하지 못한 글</h3>
          <p>제목에 종목이 여럿이거나(일정 공지·묶음 글) 상장 종목 이름을 찾지 못한 글 ${etc.length}건</p></div></div>
          <ul class="vs-notes">${(open.has('etc') ? etc : etc.slice(0, FOLD)).map(n => noteHtml(n)).join('')}</ul>
          ${open.has('etc') || etc.length <= FOLD ? '' : `<button class="vs-more" data-more="etc">${etc.length - FOLD}건 더 보기</button>`}</article>` : '')
      + (!cos.length && !etc.length ? '<p class="msg">조건에 맞는 탐방 노트가 없습니다. 기간을 넓혀 보세요.</p>' : '');
    seen.disconnect();
    document.querySelectorAll('.vs-chart').forEach(b => seen.observe(b));
  }

  function render() {
    renderFilters();
    renderList();
    $('asof').textContent = data.built_at ? `${U.timeLabel(data.built_at)} 정리` : '';
    $('foot').innerHTML = `<p><b>읽는 법</b> · POR = 시총 ÷ 영업이익(FnGuide 컨센서스, 내년 열 강조). 시총은 우선주를 더한 회사 시총입니다.
      '당시 시총'은 글이 올라온 날(휴일이면 그 전 거래일)의 시총이라, 그 뒤 증자가 있었다면 변화율에 함께 들어갑니다.
      핵심 줄은 숫자와 실적·수주·증설 같은 말이 함께 있는 줄을 기계적으로 고른 것이고, 요약은 글을 읽고 따로 쓴 것입니다.</p>
      <p class="muted">${data.public
        ? '글은 각 방 작성자의 것입니다. 공개 채널의 글은 제목과 링크만 싣고, 원문은 작성자의 허락을 받은 방의 글만 싣습니다. 1:1 대화는 싣지 않습니다.'
        : '글 원문은 각 방 작성자의 것입니다. 이 컴퓨터에서는 받은 글을 모두 보여 주고, 공개 사이트에는 줄인 사본(공개 채널은 제목·링크만, 1:1 대화 제외)을 올립니다.'}</p>`;
  }

  function setup() {
    $('msg').hidden = true;
    $('filters').hidden = true;
    $('list').innerHTML = `<article class="card vs-setup">
      <h3>아직 받은 탐방 글이 없습니다</h3>
      <p>비공개 방은 본인 텔레그램 계정으로 로그인해야 읽을 수 있습니다. 한 번만 준비하면 그 뒤로는 매일 자동으로 받습니다.</p>
      <ol>
        <li><a href="https://my.telegram.org" target="_blank" rel="noopener">my.telegram.org</a> → API development tools 에서 <code>api_id</code>, <code>api_hash</code> 발급</li>
        <li>프로젝트 <code>.env</code> 에 <code>TG_API_ID=…</code>, <code>TG_API_HASH=…</code> 두 줄 추가</li>
        <li>터미널에서 <code>python3 collect_visits.py login</code> (전화번호 → 앱으로 온 코드 → 2단계 비밀번호)</li>
        <li><code>python3 collect_visits.py && python3 build_visits.py</code> 뒤 새로고침</li>
      </ol>
      <p class="muted small">API 없이 하려면 텔레그램 데스크톱의 '채팅 기록 내보내기'(JSON)로 받은 파일을 <code>python3 collect_visits.py import result.json</code> 으로 넣어도 됩니다.</p>
    </article>`;
  }

  pg.bind($('filters'));
  U.initTheme($('theme'));
  $('list').addEventListener('click', e => {
    const b = e.target.closest('[data-more]');
    if (b) { open.add(b.dataset.more); renderList(); }
  });

  (async () => {
    try {
      data = await U.json('data/visits.json');
    } catch (e) {
      return setup();
    }
    if (!data.cos.length && !data.etc.length) return setup();
    $('msg').hidden = true;
    render();
  })();
})();
