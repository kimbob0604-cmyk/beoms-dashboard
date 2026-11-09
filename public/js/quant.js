// 퀀트 탭: data/factors.json — 팩터 원값을 받아 화면에서 백분위·가중 합산 점수를 계산한다
// 백분위는 지금 걸러진 종목들 안에서 매긴다 (예: 코스닥만 고르면 코스닥 안 순위)
(() => {
  // 키, 이름, 방향(+1 높을수록 좋음), 설명, 단위
  const FACT = [
    ['rev1', '리비전 1M', 1, '내년 영업이익 추정치 1개월 변화', '%'],
    ['rev3', '리비전 3M', 1, '내년 영업이익 추정치 3개월 변화', '%'],
    ['grow', '이익성장', 1, '내년 영업이익 증가율 (흑자전환은 맨 위)', '%'],
    ['ey', '이익수익률', 1, '내년 영업이익 ÷ 시총 (POR 의 역수)', '%'],
    ['mom', '모멘텀', 1, '12-1개월 수익률 (최근 1개월 제외)', '%'],
    ['flow', '수급', 1, '외국인+기관 20일 순매수 ÷ 시총', '%'],
    ['vol', '저변동', -1, '60일 변동성(연율) — 낮을수록 높은 점수', '%'],
    ['shr', '주주환원', 1, '90일 자사주 취득·소각 공시 금액 ÷ 시총', '%'],
  ];
  const KEYS = FACT.map(f => f[0]);
  // 가중치 프리셋 (FACT 순서). 기본은 한국 시장에서 근거가 있는 리비전 + 수급
  const PRESETS = {
    base: ['리비전+수급', [2, 1, 0, 0, 0, 2, 0, 0]],
    growth: ['성장', [1, 1, 2, 0, 0, 0, 0, 0]],
    mom: ['모멘텀', [0, 0, 0, 0, 2, 1, 1, 0]],
    value: ['밸류·환원', [0, 0, 0, 2, 0, 0, 1, 1]],
    equal: ['균등', [1, 1, 1, 1, 1, 1, 1, 1]],
  };
  const CNS = new Set(['rev1', 'rev3', 'grow', 'ey']);
  const CAPS = { L: [10000, Infinity], M: [3000, 10000], S: [0, 3000] };
  const PAGE = 50;
  const DEFAULTS = { p: 'base', w: PRESETS.base[1].join(''), market: 'all', cap: 'all', sec: '', cns: '1', q: '', sort: 'score', ord: 'desc' };

  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, (patch, typing) => (typing ? renderBody() : render()));
  const st = pg.state;
  let data = null, rows = [], shown = PAGE;

  const weights = () => [...st.w].map(Number);
  const val = (r, k) => r[7 + KEYS.indexOf(k)];
  const fmt = (v, k) => (v == null ? '–' : k === 'grow' && v >= 999 ? '흑전' : `${v > 0 && k !== 'vol' ? '+' : ''}${v.toLocaleString('ko-KR', { maximumFractionDigits: Math.abs(v) < 10 ? 2 : 1 })}%`);

  // 값 → 0~100 백분위 (같은 값은 평균 순위). 값 없는 종목은 null
  function percentiles(list, k, dir) {
    const xs = list.map((r, i) => [val(r, k), i]).filter(x => x[0] != null).sort((a, b) => dir * (a[0] - b[0]));
    const out = new Array(list.length).fill(null);
    const n = xs.length;
    for (let i = 0; i < n;) {
      let j = i;
      while (j + 1 < n && xs[j + 1][0] === xs[i][0]) j++;
      const p = n > 1 ? ((i + j) / 2) / (n - 1) * 100 : 50;
      for (let t = i; t <= j; t++) out[xs[t][1]] = p;
      i = j + 1;
    }
    return out;
  }

  function compute() {
    const q = st.q.trim().toLowerCase();
    const cap = CAPS[st.cap];
    const w = weights();
    const needCns = st.cns && w.some((x, i) => x && CNS.has(KEYS[i]));
    const list = data.rows.filter(r => {
      if (st.market !== 'all' && r[2] !== st.market) return false;
      if (cap && (r[4] < cap[0] || r[4] >= cap[1])) return false;
      if (st.sec && r[3] !== st.sec) return false;
      if (needCns && val(r, 'rev1') == null && val(r, 'ey') == null) return false;
      return true;
    });
    const pct = FACT.map(([k, , dir]) => percentiles(list, k, dir));
    const tw = w.reduce((a, b) => a + b, 0) || 1;
    rows = list.map((r, i) => {
      const ps = pct.map(p => p[i]);
      // 값 없는 팩터는 중립(50)으로 — 빠진 개수는 따로 보여 준다
      const score = w.reduce((a, x, j) => a + x * (ps[j] ?? 50), 0) / tw;
      const miss = w.reduce((a, x, j) => a + (x && ps[j] == null ? 1 : 0), 0);
      return { r, ps, score, miss };
    }).filter(x => !q || x.r[1].toLowerCase().includes(q) || x.r[0].includes(q));
    const key = st.sort === 'score' ? x => x.score : x => x.ps[KEYS.indexOf(st.sort)];
    const sign = st.ord === 'asc' ? -1 : 1;   // 같은 머리글을 다시 누르면 작은 순
    rows.sort((a, b) => {
      const x = key(a), y = key(b);
      if (x == null) return y == null ? 0 : 1;   // 값 없는 종목은 늘 아래
      if (y == null) return -1;
      return sign * (y - x);
    });
  }

  // ---------- 그리기 ----------
  function renderFilters() {
    const secs = [...new Set(data.rows.map(r => r[3]).filter(Boolean))].sort();
    $('filters').innerHTML = `
      <div class="frow">
        ${pg.seg('p', [...Object.entries(PRESETS).map(([k, [l]]) => [k, l]), ['custom', '직접']])}
        <button class="btn-copy" id="csv" title="지금 순위를 CSV 로 내려받기 (엑셀에서 열림)">CSV 받기</button>
      </div>
      <div class="frow">
        ${pg.seg('market', [['all', '전체'], ['KOSPI', '코스피'], ['KOSDAQ', '코스닥']])}
        ${pg.seg('cap', [['all', '시총 전체'], ['L', '1조 이상'], ['M', '3천억~1조'], ['S', '3천억 미만']])}
        <select data-sel="sec" aria-label="업종"><option value="">업종 전체</option>${secs.map(s => `<option${s === st.sec ? ' selected' : ''}>${U.esc(s)}</option>`).join('')}</select>
        <input type="search" data-q="q" placeholder="종목명·코드 검색" value="${U.esc(st.q)}" autocomplete="off">
        ${pg.chk('cns', '컨센서스 있는 종목만', '리비전·이익성장·이익수익률을 쓰면 추정치가 없는 종목은 뺍니다')}
      </div>`;
  }

  function renderWeights() {
    const w = weights();
    $('weights').innerHTML = `<div class="qt-wgrid">${FACT.map(([k, l, , desc], i) => `
      <label class="qt-w${w[i] ? ' on' : ''}" title="${desc}">
        <span class="qt-wl"><b>${l}</b><small class="muted">${desc}</small></span>
        <span class="qt-wv"><input type="range" min="0" max="3" step="1" value="${w[i]}" data-w="${i}"><em>${w[i] ? `×${w[i]}` : '안 씀'}</em></span>
      </label>`).join('')}</div>`;
  }

  function renderSummary() {
    const top = rows.slice(0, 30);
    const w = weights();
    const secs = {};
    for (const x of top) if (x.r[3]) secs[x.r[3]] = (secs[x.r[3]] || 0) + 1;
    const avg = j => { const v = top.map(x => x.ps[j]).filter(p => p != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
    $('summary').innerHTML = `
      <div class="qt-sum">
        <div><h2>상위 30종목 <span class="muted small">대상 ${rows.length.toLocaleString('ko-KR')}종목 중</span></h2>
          <p class="muted small">팩터별 상위 30종목 평균 백분위 (50 = 대상 전체 평균)</p>
          <div class="qt-bars">${FACT.map(([k, l], j) => {
            const a = avg(j);
            return `<div class="${w[j] ? '' : 'off'}"><span>${l}</span><i><b style="width:${a ?? 0}%"></b><s></s></i><em>${a == null ? '–' : Math.round(a)}</em></div>`;
          }).join('')}</div></div>
        <div><h3>업종 분포</h3><div class="dt-chips">${Object.entries(secs).sort((a, b) => b[1] - a[1]).slice(0, 10)
          .map(([s, n]) => `<span class="chip">${U.esc(s)} <b>${n}</b></span>`).join('') || '<span class="muted small">–</span>'}</div></div>
      </div>`;
  }

  function cell(x, j) {
    const [k] = FACT[j];
    const p = x.ps[j], v = val(x.r, k);
    const off = !weights()[j];
    return `<td class="num qt-c${off ? ' off' : ''}" title="${FACT[j][1]} ${fmt(v, k)} · 백분위 ${p == null ? '없음' : Math.round(p)}">
      <span class="qt-p" style="--p:${p ?? 0}">${p == null ? '–' : Math.round(p)}</span><small>${fmt(v, k)}</small></td>`;
  }

  function renderTable() {
    const list = rows.slice(0, shown);
    const th = (k, l) => `<th class="num sortable${st.sort === k ? ' on' : ''}" data-sort="${k}">${l}${st.sort === k ? (st.ord === 'asc' ? ' ▲' : ' ▼') : ''}</th>`;
    $('table').innerHTML = `<div class="col-head"><h3>순위 <span class="muted">${rows.length.toLocaleString('ko-KR')}종목 · ${st.sort === 'score' ? '점수' : FACT[KEYS.indexOf(st.sort)][1]} 순</span></h3>
        <span class="muted small">칸 숫자 = 백분위(0~100), 아래 = 원값 · 머리글을 누르면 그 팩터 순</span></div>
      <div class="tbl-wrap"><table class="tbl qt-tbl">
        <thead><tr><th>#</th><th>종목</th><th class="num">시총</th>${th('score', '점수')}${FACT.map(([k, l]) => th(k, l)).join('')}</tr></thead>
        <tbody>${list.map((x, i) => {
          const r = x.r;
          const s = { c: r[0], n: r[1], mk: r[2], w: r[3], mc: r[4], p: r[5], ch: r[6] };
          return `<tr ${Stock.hintAttr(s)}><td class="muted">${i + 1}</td>
            <td class="name-cell">${Stock.link(s)}<small class="muted">${U.esc(r[3] || '')}${x.miss ? ` · 값 없는 팩터 ${x.miss}개(중립)` : ''}</small></td>
            <td class="num">${U.eok(r[4])}</td>
            <td class="num"><b class="qt-score">${x.score.toFixed(1)}</b></td>${FACT.map((_, j) => cell(x, j)).join('')}</tr>`;
        }).join('')}</tbody></table></div>
      ${rows.length > shown ? `<button class="more" id="more">${Math.min(PAGE, rows.length - shown)}종목 더 보기</button>` : ''}`;
  }

  function renderBody() {
    compute();
    renderSummary();
    renderTable();
  }

  function renderFoot() {
    $('foot').innerHTML = `
      <p>점수 = 고른 팩터 백분위의 가중 평균. 백분위는 지금 걸러진 종목 안에서 매기고, 값이 없는 팩터는 중립(50)으로 둡니다. 시총 300억 이상 보통주.</p>
      <p>추정치: FnGuide 컨센서스(네이버 종목분석, 기준 ${data.cns ? U.dateLabel(data.cns) : '–'}). 수급: 네이버 투자자별 매매동향(${data.flow ? U.dateLabel(data.flow) : '–'}, 수량 × 종가 어림). 가격: KRX 일봉. 주주환원: DART 공시(자회사 공시 제외, 장내매수 후 소각은 취득 쪽만).</p>
      <p>현재 상장 종목만 있어(생존 편향) 과거 성과 검증용이 아닙니다. 한국 시장 연구에서 추정치 상향 전략은 동일가중일 때 효과가 컸고 회전율이 높았습니다. 투자 판단의 참고용입니다.</p>`;
  }

  function render() {
    renderFilters();
    renderWeights();
    renderBody();
    renderFoot();
  }

  // 프리셋을 고르면 가중치도 바꾸고, 슬라이더를 움직이면 '직접'으로
  const set0 = pg.set;
  pg.set = patch => {
    if (patch.p && PRESETS[patch.p]) patch.w = PRESETS[patch.p][1].join('');
    shown = PAGE;
    set0(patch);
  };

  $('weights').addEventListener('input', e => {
    const i = e.target.dataset.w;
    if (i == null) return;
    const w = weights();
    w[+i] = +e.target.value;
    st.w = w.join('');
    st.p = Object.entries(PRESETS).find(([, [, pw]]) => pw.join('') === st.w)?.[0] || 'custom';
    pg.write();
    e.target.closest('.qt-w').classList.toggle('on', !!w[+i]);
    e.target.nextElementSibling.textContent = w[+i] ? `×${w[+i]}` : '안 씀';
    document.querySelectorAll('#filters [data-k="p"]').forEach(b => b.classList.toggle('on', b.dataset.v === st.p));
    renderBody();
  });

  $('table').addEventListener('click', e => {
    const h = e.target.closest('[data-sort]');
    if (h) {
      st.ord = st.sort === h.dataset.sort && st.ord === 'desc' ? 'asc' : 'desc';
      st.sort = h.dataset.sort;
      pg.write(); shown = PAGE; return renderBody();
    }
    if (e.target.closest('#more')) { shown += PAGE; renderTable(); }
  });

  $('filters').addEventListener('click', e => {
    if (!e.target.closest('#csv')) return;
    const head = ['순위', '코드', '종목', '시장', '업종', '시총(억)', '주가', '등락률', '점수', ...FACT.flatMap(([, l]) => [`${l}`, `${l} 백분위`])];
    const esc = v => (v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v);
    const lines = rows.map((x, i) => [i + 1, x.r[0], x.r[1], x.r[2], x.r[3], x.r[4], x.r[5], x.r[6], x.score.toFixed(2),
      ...FACT.flatMap(([k], j) => [val(x.r, k), x.ps[j] == null ? '' : x.ps[j].toFixed(1)])].map(esc).join(','));
    const blob = new Blob(['﻿' + [head.join(','), ...lines].join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `퀀트_${data.date}_${st.p}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  });

  pg.bind($('filters'));
  U.initTheme($('theme'));
  (async () => {
    try {
      data = await U.json('data/factors.json');
    } catch (e) {
      $('msg').textContent = `팩터 데이터를 불러오지 못했습니다. (${e.message})`;
      return;
    }
    $('msg').hidden = true;
    $('asof').textContent = `${U.dateLabel(data.date)} 기준`;
    if (!/^[0-3]{8}$/.test(st.w)) st.w = PRESETS.base[1].join('');
    render();
  })();
})();
