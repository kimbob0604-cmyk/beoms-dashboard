// 공시 탭: data/dart/{접수일}.json — DART 주요 공시를 종류별로, 잠정실적은 컨센서스 대비
(() => {
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };
  const GROUPS = {
    all: ['전체', null],
    earn: ['실적', ['earn', 'earn_m']],
    contract: ['수주·계약', ['contract', 'contract_x']],
    ret: ['주주환원', ['cancel', 'buyback', 'trust', 'dividend']],
    fund: ['자금조달', ['cb', 'bw', 'eb', 'rights', 'bonus']],
    gov: ['지배구조·투자', ['holder', 'invest']],
    biz: ['주요경영사항', ['biz']],
    ir: ['IR·일정', ['ir', 'preview']],
  };
  const DEFAULTS = { date: '', g: 'all', market: 'all', cap: 'all', q: '', sort: 'time', hit: '' };
  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => (typing ? renderBody() : render()));
  const st = pg.state;
  let data = null;

  const F = DartFmt;
  const chg = ch => (ch == null ? '' : `<span class="${U.cls(ch)}">${ch > 0 ? '+' : ''}${ch.toFixed(2)}%</span>`);

  function filtered() {
    const q = st.q.trim().toLowerCase();
    const cap = CAPS[st.cap];
    const kinds = GROUPS[st.g][1];
    const xs = data.items.filter(x => {
      if (kinds && !kinds.includes(x.k)) return false;
      if (st.market !== 'all' && x.mk !== st.market) return false;
      if (cap && (x.mc == null || x.mc < cap[0] || x.mc >= cap[1])) return false;
      if (st.hit && !(x.s?.tag || (x.k === 'contract' && x.d?.pct >= 10))) return false;
      if (q && !x.n.toLowerCase().includes(q) && !x.c.includes(q)) return false;
      return true;
    });
    return st.sort === 'mc' ? xs.sort((a, b) => (b.mc || 0) - (a.mc || 0)) : xs;
  }

  function renderFilters() {
    $('filters').innerHTML = `
      <div class="frow">
        ${pg.seg('g', Object.entries(GROUPS).map(([k, [l]]) => [k, l]))}
        <button class="btn-copy" id="copy" title="아래 목록을 종류별 글로 복사 (텔레그램·메모용)">글로 복사</button>
      </div>
      <div class="frow">
        ${pg.seg('market', [['all', '전체'], ['KOSPI', '코스피'], ['KOSDAQ', '코스닥']])}
        ${pg.seg('cap', [['all', '시총 전체'], ['L', '1조 이상'], ['M', '3천억~1조'], ['S', '3천억 미만']])}
        ${pg.seg('sort', [['time', '공시 순'], ['mc', '시총 순']])}
        <input type="search" data-q="q" placeholder="종목명·코드 검색" value="${U.esc(st.q)}" autocomplete="off">
        ${pg.chk('hit', '서프·쇼크·대형 수주만', '잠정실적 서프라이즈·쇼크, 매출액 대비 10% 이상 공급계약')}
      </div>`;
  }

  // ---------- 요약 ----------
  function renderSummary(xs) {
    const cnt = {};
    for (const x of data.items) cnt[x.k] = (cnt[x.k] || 0) + 1;
    const earn = data.items.filter(x => x.k === 'earn');
    const sp = earn.filter(x => x.s?.tag === '서프').length, sk = earn.filter(x => x.s?.tag === '쇼크').length;
    const sched = data.schedule.filter(e => e.earn);
    const byDay = {};
    for (const e of sched) (byDay[e.date] = byDay[e.date] || []).push(e);
    const chips = F.SECTIONS.filter(([, , kinds]) => kinds.some(k => cnt[k]))
      .map(([key, title, kinds]) => `<a class="chip" href="#sec-${key}">${title.split(' (')[0]} <b>${kinds.reduce((a, k) => a + (cnt[k] || 0), 0)}</b></a>`).join('');
    $('summary').innerHTML = `
      <div class="dt-sum-head">
        <div><h2>${F.md(data.date)} 주요 공시 <span class="muted small">${data.items.length}건 · 보이는 것 ${xs.length}건</span></h2>
          <p class="muted small">${U.timeLabel(data.built)} 갱신 · 장중에는 10분마다 새 공시를 받습니다</p></div>
        <div class="dt-kpis">
          <div><span>잠정실적</span><b>${earn.length}</b></div>
          <div><span>서프라이즈</span><b class="up">${sp}</b></div>
          <div><span>쇼크</span><b class="down">${sk}</b></div>
        </div>
      </div>
      <div class="dt-chips">${chips}</div>
      ${Object.keys(byDay).length ? `<div class="dt-sched">${Object.entries(byDay).slice(0, 3).map(([d, es]) => `
        <div><h3>${F.md(d)} 실적발표 예정 <span class="muted small">${es.length}종목</span></h3>
          <p>${es.map(e => `<span ${Stock.hintAttr(e)}>${Stock.link(e)}${e.ir?.time ? `<small class="muted"> ${e.ir.time}</small>` : ''}</span>`).join('')}</p></div>`).join('')}
        <p class="muted small">결산실적 공시 예고·실적 IR 공시로 확인된 회사만 (예고 없이 발표하는 회사는 빠집니다)</p></div>` : ''}`;
  }

  // ---------- 섹션 ----------
  function kv(text) {
    return text.split('\n').map((line, i) => (i ? `<p class="dt-more">${U.esc(line)}</p>`
      : `<p class="dt-kv">${line.split(' / ').map(p => {
        const m = p.match(/^([^:]{1,12}) : (.*)$/);
        return m ? `<span><em>${U.esc(m[1])}</em>${U.esc(m[2])}</span>` : `<span>${U.esc(p)}</span>`;
      }).join('')}</p>`)).join('');
  }

  function tagHtml(x) {
    return F.tags(x).map(t => `<span class="dt-tag ${t === '서프' ? 'up' : t === '쇼크' ? 'down' : ''}">${t}</span>`).join('');
  }

  function itemHtml(x) {
    return `<article class="dt-item" ${Stock.hintAttr(x)}>
      <header>
        <div class="dt-name">${Stock.link(x)}<small class="muted">${x.mc != null ? F.eok(x.mc) : ''}${x.w ? ` · ${U.esc(x.w)}` : ''}</small>${tagHtml(x)}</div>
        <div class="dt-right small">${chg(x.ch)}<a class="muted" href="${F.dartUrl(x.no)}" target="_blank" rel="noopener" title="DART 원문">원문 ↗</a></div>
      </header>
      ${x.d && Object.keys(x.d).length ? kv(F.body(x)) : `<p class="muted small">${U.esc(x.t)} (원문 양식을 읽지 못함)</p>`}
    </article>`;
  }

  // 잠정실적: 표로 (실적 · 추정치 대비 · 전년 대비)
  function earnCell(r, c, d, key) {
    if (!r || r.v == null) return '<td class="num muted">–</td>';
    const dd = d == null ? '' : `<small class="${U.cls(d)}">${c != null && Math.sign(r.v) !== Math.sign(c) ? (r.v > 0 ? '흑전' : '적전') : F.pct(d, Math.abs(d) < 0.01 ? 1 : 0)}</small>`;
    return `<td class="num"><b class="${r.v < 0 ? 'down' : ''}">${Math.round(r.v).toLocaleString('ko-KR')}</b>
      <small class="muted">${c != null ? `추정 ${Math.round(c).toLocaleString('ko-KR')}` : '추정 없음'}</small>${dd}
      ${r.yoy != null && key !== 'np' ? `<small class="muted">YoY ${r.yoy > 0 ? '+' : ''}${r.yoy.toFixed(0)}%</small>` : ''}</td>`;
  }

  function earnTable(xs) {
    return `<div class="tbl-wrap"><table class="tbl dt-earn">
      <thead><tr><th>회사</th><th class="num">매출</th><th class="num">영업이익</th><th class="num">순이익</th><th></th></tr></thead>
      <tbody>${xs.map(x => {
        const r = x.d.rows || {}, s = x.s?.mismatch ? null : x.s;
        const np = s?.np_basis === '지배' ? r.cnp : (r.np || r.cnp);
        return `<tr ${Stock.hintAttr(x)}>
          <td class="name-cell">${Stock.link(x)} ${tagHtml(x)}<small class="muted">${x.mc != null ? F.eok(x.mc) : ''} · ${x.d.period || ''} ${x.d.basis || ''}</small></td>
          ${earnCell(r.sales, s?.cns.sales, s?.d.sales, 'sales')}${earnCell(r.op, s?.cns.op, s?.d.op, 'op')}${earnCell(np, s?.cns.np, s?.d.np, 'np')}
          <td class="small"><a class="muted" href="${F.dartUrl(x.no)}" target="_blank" rel="noopener">원문 ↗</a></td></tr>`;
      }).join('')}</tbody></table></div>
      <p class="muted small dt-note">억원. 추정 = 네이버 종목분석 분기 컨센서스(FnGuide), 공시일까지 받은 마지막 값. 영업이익이 추정치보다 10% 이상 많으면 서프, 10% 이상 적으면(또는 적자전환) 쇼크.</p>`;
  }

  function renderSections(xs) {
    const sec = ([key, title, kinds]) => {
      const items = xs.filter(x => kinds.includes(x.k));
      if (!items.length) return '';
      const wide = key === 'earn';
      return `<section class="card dt-sec${wide ? ' wide' : ''}" id="sec-${key}">
        <div class="col-head"><h3>${title} <span class="muted">${items.length}건</span></h3></div>
        ${wide ? earnTable(items) : `<div class="dt-items">${items.map(itemHtml).join('')}</div>`}
      </section>`;
    };
    // 잠정실적 표를 맨 위 전체 폭으로, 나머지는 두 단으로 쌓는다
    const earn = sec(F.SECTIONS.find(s => s[0] === 'earn'));
    const rest = F.SECTIONS.filter(s => s[0] !== 'earn').map(sec).join('');
    $('sections').innerHTML = earn || rest ? `${earn}<div class="dt-cols">${rest}</div>` : '<p class="msg">조건에 맞는 공시가 없습니다.</p>';
  }

  function renderBody() {
    const xs = filtered();
    renderSummary(xs);
    renderSections(xs);
  }

  function renderFoot() {
    $('foot').innerHTML = `
      <p>공시: 금융감독원 DART Open API (유가증권·코스닥, 종류별 원문에서 항목을 읽음). 회사 옆 금액은 시가총액, 등락률은 그날 종가 기준.</p>
      <p>장전·장후 표시는 장중 수집이 처음 본 시각 기준이라 지난 날 공시에는 없을 수 있습니다. 원문 확인 후 판단하세요. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  }

  function render() {
    renderFilters();
    renderBody();
    renderFoot();
  }

  $('filters').addEventListener('click', async e => {
    if (!e.target.closest('#copy')) return;
    const xs = filtered().filter(x => x.d && Object.keys(x.d).length);
    const text = F.digest(data.date, xs, data.schedule);
    const b = e.target.closest('#copy');
    try {
      await navigator.clipboard.writeText(text);
      b.textContent = '복사됨 ✓';
    } catch (err) {
      b.textContent = '복사 실패';
    }
    setTimeout(() => { b.textContent = '글로 복사'; }, 1600);
  });

  async function load(d) {
    try {
      data = await U.json(`data/dart/${d}.json`);
    } catch (e) {
      $('msg').hidden = false;
      $('msg').textContent = `${d} 공시를 불러오지 못했습니다. (${e.message})`;
      return;
    }
    $('msg').hidden = true;
    render();
  }

  // 보고 있는 날짜에 새 공시가 들어오면(장중 10분마다) 조용히 다시 그린다
  async function refreshSame() {
    if (!data || !U.busyHours()) return;
    try {
      const d = await U.fresh(`data/dart/${data.date}.json`);   // 바뀌었을 때만 (캐시도 같이 바뀜)
      if (d && d.date === data.date) { data = d; renderBody(); }
    } catch (e) { /* 다음 때 */ }
  }
  setInterval(refreshSame, 120000);

  pg.bind($('filters'));
  U.initTheme($('theme'));
  (async () => {
    try {
      await U.dates('dart', pg, $('date'), load);
    } catch (e) {
      $('msg').textContent = '공시 목록을 불러오지 못했습니다.';
      return;
    }
    load(st.date);
  })();
})();
