// 조건 신호 백테스트 (20년): data/bt/summary.json (전 조합 성과) + data/bt/{조합}.json (주간 누적·보유 종목 수·연도별·지금 보유)
(() => {
  const DEFAULTS = { c: '', ex: 'h120', per: 'all', bm: 'u', sort: 'yt', minN: '20', sup: '' };
  const BM = { u: '대상 평균', k: '코스피', q: '코스닥' };
  const BMwa = { u: '대상 평균과', k: '코스피와', q: '코스닥과' };
  const $ = id => document.getElementById(id);
  const pg = U.page(DEFAULTS, () => render());
  const st = pg.state;
  let S = null;
  const detail = {};

  const pct = (v, nd = 1) => (v == null ? '–' : `${v > 0 ? '+' : ''}${(+v).toFixed(nd)}%`);
  const dot = d => d.replace(/-/g, '.');
  const order = () => S.conds.map(c => c.k);
  const keyOf = ks => order().filter(k => ks.includes(k)).join('+');
  const condOf = k => S.conds.find(c => c.k === k);
  const label = key => key.split('+').map(k => condOf(k)?.l || k).join(' + ');
  const combo = key => S.combos.find(c => c.k === key);
  const isFin = key => key.split('+').some(k => S.fin.includes(k));
  const exitOf = k => S.exits.find(e => e.k === k);
  const win = key => (isFin(key) ? 'r10' : st.per);          // 실적 조건은 2016년부터라 최근 10년으로만 본다
  const mult = v => { const x = 2 ** v; return x >= 10 ? `×${x.toFixed(0)}` : x >= 1 ? `×${x.toFixed(1).replace('.0', '')}` : `×${x.toFixed(2)}`; };

  // 창(20년 / 최근 10년)별로 같은 이름의 지표를 꺼낸다
  const M = (m, w) => (w === 'all'
    ? { ret: m.cagr, x: m.x, mdd: m.mdd, sh: m.sharpe, a: m.x1, b: m.x2 }
    : { ret: m.c2, x: m.x2, mdd: m.mdd2, sh: m.sh2, a: m.x3, b: m.x4 });
  // 연도별 BM 대비 초과: [세는 해, 평균 초과, 이긴 해, t값, 가장 나쁜 해, 앞 절반 평균, 뒤 절반 평균, 중간값]
  const Y = (m, w) => {
    const a = m.ex?.[w]?.[st.bm];
    return a && { n: a[0], m: a[1], w: a[2], t: a[3], lo: a[4], a: a[5], b: a[6], md: a[7] };
  };
  const halfLbl = w => (w === 'all' ? ['앞 10년', '뒤 10년'] : ['앞 5년', '뒤 5년']);
  const sortVal = (m, w) => {
    const v = M(m, w), y = Y(m, w);
    return { yt: y.t, ym: y.m, ymd: y.md, yw: y.w / y.n, ylo: y.lo, rb: Math.min(v.a, v.b), ret: v.ret, sh: v.sh }[st.sort];
  };
  const eligible = (c, w) => {
    const m = c.x[st.ex];
    const y = m && Y(m, w);
    return m && y && y.n >= (w === 'all' ? 12 : 8) && m.n >= +st.minN && m.tr >= 100 && (w === 'r10' || !isFin(c.k));
  };
  const ranked = w => S.combos.filter(c => eligible(c, w)).sort((a, b) => sortVal(b.x[st.ex], w) - sortVal(a.x[st.ex], w));

  function renderFilters() {
    const sel = st.c.split('+');
    $('filters').innerHTML = `
      <div class="frow bt-conds">${S.conds.map(c => `<button class="bt-cond${sel.includes(c.k) ? ' on' : ''}" data-cond="${c.k}" title="${U.esc(c.d)}">${U.esc(c.l)}${S.fin.includes(c.k) ? '<small>2016~</small>' : ''}</button>`).join('')}</div>
      <div class="frow"><span class="flabel">파는 규칙</span>${pg.seg('ex', S.exits.map(e => [e.k, e.l, e.d]))}
        <span class="flabel">기간</span>${pg.seg('per', [['all', `20년 (${S.start.slice(0, 4)}~)`], ['r10', `최근 10년 (${S.recent}~)`]])}
        <span class="flabel">연도별 비교 기준</span>${pg.seg('bm', Object.entries(BM).map(([k, l]) => [k, l, k === 'u' ? '그 해 대상 종목(시총 500억·거래대금 5억 이상)을 같은 비중으로 들고 간 수익률' : `그 해 ${l} 지수 등락률`]))}</div>
      <p class="muted small bt-help">조건은 최대 3개. 고른 조건을 <b>모두</b> 만족한 날 신호 → 다음 거래일 종가에 매수 → 파는 규칙대로 보유. 조건에 마우스를 올리면 정의가 나옵니다.</p>`;
  }

  const kpi = (lbl, v, cls = '', sub = '') => `<div><span>${lbl}</span><b class="${cls}">${v}</b>${sub ? `<small>${sub}</small>` : ''}</div>`;

  function yearGrid(d, w) {
    const b = S.bm_yr[st.bm];
    const idx = S.years.map((y, i) => i).filter(i => S.yfull[i] && (w === 'all' || S.years[i] >= S.recent));
    const ex = i => (d.yc[i] ? d.yr[i] - b[i] : null);
    const vals = idx.map(ex).filter(v => v != null);
    const mx = Math.max(10, ...vals.map(Math.abs));
    const W = 100 / idx.length;
    const bars = idx.map((i, k) => {
      const v = ex(i);
      if (v == null) return '';
      const h = Math.abs(v) / mx * 46;
      return `<rect x="${k * W + W * 0.15}%" width="${W * 0.7}%" y="${v >= 0 ? 50 - h : 50}%" height="${Math.max(h, 0.6)}%" class="${v >= 0 ? 'up' : 'dn'}"><title>${S.years[i]}년 초과 ${pct(v)}p</title></rect>`;
    }).join('');
    return `<svg class="bt-exbar" preserveAspectRatio="none"><line x1="0" x2="100%" y1="50%" y2="50%"/>${bars}</svg>
      <div class="bt-years" style="grid-template-columns:repeat(${idx.length},minmax(0,1fr))">${idx.map(i => {
        const v = ex(i);
        if (v == null) return `<div class="bt-year off" title="${S.years[i]}년: 조건을 계산할 데이터가 없거나 그 해 중간에 처음 사서 세지 않음"><span>${String(S.years[i]).slice(2)}</span><b>–</b><small>${BM[st.bm]} ${pct(b[i], 0)}</small></div>`;
        return `<div class="bt-year ${v > 0 ? 'win' : 'lose'}" title="${S.years[i]}년 · 조합 ${pct(d.yr[i])} · ${BM[st.bm]} ${pct(b[i])} · 초과 ${pct(v)}p">
          <span>${String(S.years[i]).slice(2)}</span><b class="${U.cls(v)}">${pct(v, 0)}p</b><small>${pct(d.yr[i], 0)} / ${pct(b[i], 0)}</small></div>`;
      }).join('')}</div>`;
  }

  async function renderMain() {
    const box = $('main');
    const c = combo(st.c);
    if (!c) {
      box.innerHTML = '<p class="msg">이 조합은 계산하지 않았거나 신호가 없습니다 (조건 1~3개, 대형주·소형주 / 흑자전환·영업이익 급증은 함께 고를 수 없음).</p>';
      return;
    }
    const m = c.x[st.ex];
    if (!m) {
      box.innerHTML = `<p class="msg">이 조합은 '${exitOf(st.ex).l}' 규칙에서 한 번도 매수되지 않았습니다.</p>`;
      return;
    }
    if (!detail[c.k]) {
      box.innerHTML = '<p class="msg">불러오는 중…</p>';
      try { detail[c.k] = await U.json(`data/bt/${c.k}.json`); } catch (e) {
        box.innerHTML = `<p class="msg">불러오지 못했습니다. (${e.message})</p>`;
        return;
      }
      if (st.c !== c.k) return;
    }
    const d = detail[c.k].x[st.ex], ev = c.ev || {}, w = win(c.k), v = M(m, w), b = S.bench_m;
    const from = w === 'all' ? 0 : S.weeks.findIndex(x => x >= S.half);
    const weeks = S.weeks.slice(from);
    const rebase = arr => arr.slice(from).map(x => (x - (from ? arr[from - 1] : 0)) / 1000 / Math.LN2);   // 밑 2 로그 → 눈금이 배수(×2, ×4)로
    const nav = rebase(d.nav), bu = rebase(S.bench.univ), bk = rebase(S.bench.kospi), bq = rebase(S.bench.kosdaq);
    const y = Y(m, w), H = halfLbl(w);
    const halves = w === 'all'
      ? [['전반 초과', `${dot(S.start).slice(0, 7)}~`], ['후반 초과', `${dot(S.half).slice(0, 7)}~`]]
      : [['앞 5년 초과', `${dot(S.half).slice(0, 7)}~`], ['뒤 5년 초과', `${dot(S.q3).slice(0, 7)}~`]];
    box.innerHTML = `<div class="sec-head"><div><h2>${U.esc(label(c.k))}</h2>
        <p class="muted small">${dot(weeks[0])} ~ ${dot(S.end)} · ${U.esc(exitOf(st.ex).d)} · 신호마다 같은 금액 매수 · 매수·매도 각 ${S.cost}% 비용${isFin(c.k) && st.per === 'all' ? ' · <b>실적 조건은 2016년부터라 최근 10년으로 표시</b>' : ''}</p></div></div>
      ${y ? `<h3 class="bt-h3">해마다 ${BMwa[st.bm]} 비교 <span class="muted small">그 해 수익률 − 그 해 ${BM[st.bm]} 수익률 · ${y.n}개 해</span></h3>
      <div class="dt-kpis bt-kpis bt-yk">
        ${kpi('해마다 평균 초과', `${pct(y.m)}p`, U.cls(y.m), `중간값 ${pct(y.md)}p`)}
        ${kpi('이긴 해', `${y.w}/${y.n}`, y.w / y.n >= 0.6 ? 'up' : '', `${Math.round(y.w / y.n * 100)}%`)}
        ${kpi('t값', y.t, y.t >= 2 ? 'up' : '', y.t >= 2 ? '우연일 가능성 낮음' : y.t >= 1 ? '약함' : '우연과 구별 안 됨')}
        ${kpi('가장 나쁜 해', `${pct(y.lo)}p`, U.cls(y.lo))}
        ${kpi(`${H[0]} 평균 초과`, `${pct(y.a)}p`, U.cls(y.a))}
        ${kpi(`${H[1]} 평균 초과`, `${pct(y.b)}p`, U.cls(y.b))}
      </div>
      ${yearGrid(d, w)}` : ''}
      <h3 class="bt-h3">기간 전체 <span class="muted small">복리 기준</span></h3>
      <div class="dt-kpis bt-kpis">
        ${kpi('연평균 수익', pct(v.ret), U.cls(v.ret), `대상 평균 ${pct(v.ret - v.x)} · 코스피 ${pct(w === 'all' ? S.idx_m.kospi.cagr : S.idx_m.kospi.c2)}`)}
        ${kpi('평균 대비 초과', `${pct(v.x)}p`, U.cls(v.x), '연평균')}
        ${kpi('최대 낙폭', pct(v.mdd), 'down', w === 'all' ? `평균 ${pct(b.mdd)}` : '')}
        ${kpi('샤프', v.sh, '', w === 'all' ? `평균 ${b.sharpe}` : '')}
        ${kpi(halves[0][0], `${pct(v.a)}p`, U.cls(v.a), halves[0][1])}
        ${kpi(halves[1][0], `${pct(v.b)}p`, U.cls(v.b), halves[1][1])}
        ${w === 'all' ? kpi('2010년~ 초과', `${pct(m.x10)}p`, U.cls(m.x10), '상장폐지 포함 구간') : ''}
        ${kpi('평균 보유', `${m.n}종목`, '', isFin(c.k) ? '' : `투자 기간 ${m.inv}%`)}
        ${kpi('거래', `${m.tr.toLocaleString()}건`, '', `평균 ${m.hd}거래일 보유`)}
        ${kpi('거래 승률', `${m.win}%`, '', `중간값 ${pct(m.med)}`)}
        ${kpi('거래당 평균', pct(m.avg), U.cls(m.avg), `2배 이상 ${m.big}%`)}
        ${isFin(c.k) ? '' : kpi('시총 비례로 사면', pct(m.capc), U.cls(m.capc), '20년 연평균')}
      </div>
      <div class="hm-legend bt-legend"><i style="--c:var(--accent)"></i>이 조합 <i style="--c:var(--muted)"></i>대상 전체 평균 <i style="--c:var(--inv-frgn)"></i>코스피 <i style="--c:var(--inv-ind)"></i>코스닥 <span class="muted">· 세로축은 배수(로그)</span></div>
      <div class="bt-plot"></div>
      ${ev.n ? `<h3 class="bt-h3">신호가 처음 나온 뒤 <span class="muted small">60거래일 만에 처음 조건을 만족한 ${ev.n.toLocaleString()}번 · 20년 전체 · 괄호는 같은 날 대상 평균 대비</span></h3>
      <div class="dt-kpis bt-kpis bt-ev">
        ${kpi('3개월 뒤', pct(ev.f60), U.cls(ev.f60), `(${pct(ev.x60)}p)`)}
        ${kpi('6개월 뒤', pct(ev.f120), U.cls(ev.f120), `(${pct(ev.x120)}p)`)}
        ${kpi('1년 뒤', pct(ev.f250), U.cls(ev.f250), `(${pct(ev.x250)}p)`)}
        ${kpi('1년 뒤 중간값', pct(ev.m250), U.cls(ev.m250))}
        ${kpi('1년 뒤 평균 이길 확률', ev.w250 == null ? '–' : `${ev.w250}%`)}
        ${kpi('1년 안에 2배', ev.big == null ? '–' : `${ev.big}%`)}
      </div>` : ''}
      ${d.nnow ? `<div class="bt-now"><h3 class="bt-h3">지금 이 규칙으로 들고 있는 종목 <span class="muted small">${d.nnow}개${d.nnow > d.now.length ? ` 중 최근 신호 ${d.now.length}개` : ''} · ${dot(S.end)} 종가 기준 · 신호일 / 매수 후 수익률</span></h3>
        <div class="bt-chips">${d.now.map(x => `<span class="chip" ${Stock.hintAttr(x)}>${Stock.link(x)}
          <small class="muted">${x.d.slice(2).replace(/-/g, '.')}</small>${x.r == null ? '<small class="muted">매수 예정</small>' : `<small class="${U.cls(x.r)}">${pct(x.r)}</small>`}</span>`).join('')}</div></div>`
        : '<p class="muted small bt-now">지금은 이 규칙으로 들고 있는 종목이 없습니다.</p>'}`;
    const n = weeks.length;
    const yt = [];
    weeks.forEach((x, i) => { if (i && x.slice(0, 4) !== weeks[i - 1].slice(0, 4)) yt.push([i, `'${x.slice(2, 4)}`]); });
    const step = Math.ceil(yt.length / (box.clientWidth < 620 ? 6 : 12));
    Plot.chart(box.querySelector('.bt-plot'), {
      n, height: 360, uid: 'bt',
      panes: [
        { h: 3, zero: true, fmt: mult, series: [
          { type: 'line', values: bu, color: 'var(--muted)', width: 1.3, nodot: true },
          { type: 'line', values: bk, color: 'var(--inv-frgn)', width: 1.1, nodot: true },
          { type: 'line', values: bq, color: 'var(--inv-ind)', width: 1.1, nodot: true },
          { type: 'line', values: nav, color: 'var(--accent)', width: 2.2, last: true }] },
        { h: 0.8, label: '보유 종목 수', fmt: x => Math.round(x), series: [{ type: 'bar', values: d.n.slice(from) }] },
      ],
      xTicks: yt.filter((_, i) => i % step === 0),
      tip: i => `<div class="tt-h">${Plot.dateStr(weeks[i])}</div>
        <div><i style="--c:var(--accent)"></i>이 조합<b>${mult(nav[i])}</b></div>
        <div><i style="--c:var(--muted)"></i>대상 전체<b>${mult(bu[i])}</b></div>
        <div><i style="--c:var(--inv-frgn)"></i>코스피<b>${mult(bk[i])}</b></div>
        <div><i style="--c:var(--inv-ind)"></i>코스닥<b>${mult(bq[i])}</b></div>
        <div class="muted">보유 ${d.n[from + i]}종목</div>`,
    });
  }

  function renderRank() {
    const w = st.per;
    const sel = st.c.split('+');
    let rows = ranked(w);
    const total = rows.length;
    if (st.sup) rows = rows.filter(c => sel.every(k => c.k.split('+').includes(k)));
    const shown = rows.slice(0, 300);
    const H = halfLbl(w);
    const SORTS = [['yt', 't값', '해마다 초과수익의 평균 ÷ 흔들림 — 꾸준히 이긴 조합이 위로'], ['ym', '평균 초과', '해마다 초과수익의 평균'],
      ['ymd', '중간값', '해마다 초과수익의 중간값 — 한두 해 대박에 덜 끌려간다'], ['yw', '이긴 해 비율'], ['ylo', '최악의 해'], ['ret', '연수익']];
    $('rank').innerHTML = `<div class="col-head bt-rhead"><div><h3>조건 조합 순위 <span class="muted">${rows.length.toLocaleString()}개${st.sup ? ` / ${total.toLocaleString()}개` : ''} · ${exitOf(st.ex).l} · ${w === 'all' ? '20년' : '최근 10년'}</span></h3>
        <p class="muted small">해마다 그 해 <b>${BM[st.bm]}</b> 수익률을 빼서(초과 %p) 몇 해나 이겼는지, 평균·중간값·t값으로 봅니다. 한두 해 대박으로 올라온 조합은 중간값·t값이 낮습니다. <b>${H[0]}</b>·<b>${H[1]}</b>이 모두 플러스여야 믿을 만합니다.
          평균 ${st.minN}종목 이상 보유 · 거래 100건 이상 · ${w === 'all' ? '12' : '8'}개 해 이상${w === 'all' ? ' · 실적 조건(2016~)은 "최근 10년"에서' : ''}. 줄을 누르면 위 차트로.</p></div>
        <div class="bt-rtools">${pg.seg('sort', SORTS)}${pg.seg('minN', [['5', '5종목↑'], ['20', '20종목↑'], ['50', '50종목↑'], ['100', '100종목↑']])}
          ${pg.chk('sup', '고른 조건이 들어간 조합만')}</div></div>
      <div class="tbl-wrap bt-rwrap"><table class="tbl bt-rank">
        <thead><tr><th>#</th><th>조건 조합</th><th class="num" title="해마다 초과수익 평균 ÷ 표준오차">t값</th><th class="num">평균 초과</th><th class="num">중간값</th><th class="num">이긴 해</th><th class="num">최악의 해</th>
          <th class="num">${H[0]}</th><th class="num">${H[1]}</th><th class="num">연수익</th><th class="num">최대 낙폭</th>
          <th class="num">평균 종목</th><th class="num">거래</th><th class="num" title="거래 중 2배 이상 난 비율">2배↑</th><th class="num">지금</th></tr></thead>
        <tbody>${shown.map((c, i) => {
          const m = c.x[st.ex], v = M(m, w), y = Y(m, w);
          return `<tr class="bt-row${c.k === st.c ? ' on' : ''}" data-combo="${c.k}"><td class="muted">${i + 1}</td>
            <td><b>${U.esc(label(c.k))}</b></td>
            <td class="num" data-v="${y.t}"><b class="${y.t >= 2 ? 'up' : ''}">${y.t}</b></td>
            <td class="num"><b class="${U.cls(y.m)}">${pct(y.m)}</b></td><td class="num"><span class="${U.cls(y.md)}">${pct(y.md)}</span></td>
            <td class="num" data-v="${y.w / y.n}">${y.w}/${y.n}</td><td class="num"><span class="${U.cls(y.lo)}">${pct(y.lo)}</span></td>
            <td class="num"><span class="${U.cls(y.a)}">${pct(y.a)}</span></td><td class="num"><span class="${U.cls(y.b)}">${pct(y.b)}</span></td>
            <td class="num"><span class="${U.cls(v.ret)}">${pct(v.ret)}</span></td><td class="num down">${pct(v.mdd)}</td>
            <td class="num">${m.n}</td><td class="num">${m.tr}</td><td class="num">${m.big}%</td><td class="num">${m.now}</td></tr>`;
        }).join('')}</tbody></table></div>
      ${rows.length > shown.length ? `<p class="muted small">위 ${shown.length}개만 표시 — 조건을 고르고 "고른 조건이 들어간 조합만"으로 좁히세요.</p>` : ''}`;
  }

  function renderFoot() {
    const b = S.bench_m;
    $('foot').innerHTML = `
      <p><b>읽는 법</b> · 대상: 보통주(스팩·리츠 제외) 중 그 시점 시총 ${S.min_mcap}억 이상 · 20일 평균 거래대금 ${S.min_tv}억 이상. 비교 기준 "대상 전체 평균"은 이 종목들을 매일 같은 비중으로 들고 간 것 — 20년 연 ${pct(b.cagr)}, 최대 낙폭 ${pct(b.mdd)}.
        조건은 그날 종가까지 알 수 있던 데이터로만 판단하고 다음 거래일 종가에 사고판다고 가정했습니다. 신호마다 같은 금액을 사서 팔 때까지 비중을 맞추지 않으므로 크게 오른 종목의 비중이 커집니다.</p>
      <p><b>데이터</b> · ${dot(S.clean)} 이후는 한국거래소 일별 전 종목(상장폐지 종목 포함, 그날 시가총액). 그 전은 네이버 수정주가라 2010년 전에 상장폐지된 종목이 빠져 있어 수익률이 실제보다 좋게 나옵니다 — "2010~ 초과"가 더 믿을 만합니다.
        수급은 외국인·기관 순매수(2005~), 실적은 DART 분기 영업이익(2016~, 정정 공시가 있으면 정정된 값·날짜 기준).</p>
      <p><b>주의</b> · 조합 ${S.combos.length.toLocaleString()}개 × 파는 규칙 3개를 한꺼번에 시험했으므로 t값 2를 넘는 조합도 일부는 우연입니다. 연도별 초과에서 앞·뒤 절반이 모두 플러스인 조합을 고르고, 실제 체결가·유동성·세금은 다를 수 있습니다. 과거 성과가 앞으로를 보장하지 않습니다. ${S.built} 계산.</p>`;
  }

  function render() {
    renderFilters();
    renderMain();
    renderRank();
    renderFoot();
  }

  $('filters').addEventListener('click', e => {
    const b = e.target.closest('[data-cond]');
    if (!b) return;
    const k = b.dataset.cond;
    let sel = st.c ? st.c.split('+') : [];
    sel = sel.includes(k) ? sel.filter(x => x !== k) : [...sel, k];
    for (const [a, z] of [['large', 'small'], ['e_turn', 'e_up']]) {
      if (k === a) sel = sel.filter(x => x !== z);
      if (k === z) sel = sel.filter(x => x !== a);
    }
    if (sel.length > 3) sel = sel.slice(-3);            // 4번째를 고르면 가장 먼저 고른 것을 뺀다
    if (!sel.length) return;
    pg.set({ c: keyOf(sel) });
  });
  $('rank').addEventListener('click', e => {
    const r = e.target.closest('[data-combo]');
    if (r) { pg.set({ c: r.dataset.combo }); window.scrollTo({ top: 0, behavior: 'smooth' }); }
  });

  pg.bind($('filters'));
  pg.bind($('rank'));
  U.initTheme($('theme'));
  (async () => {
    try {
      S = await U.json('data/bt/summary.json');
    } catch (e) {
      $('msg').textContent = `백테스트 데이터를 불러오지 못했습니다. (${e.message})`;
      return;
    }
    $('msg').hidden = true;
    $('asof').textContent = `${dot(S.end)}까지`;
    if (!combo(st.c)) {   // 주소에 조합이 없으면 지금 기준 1위
      const best = ranked(st.per)[0];
      if (best) st.c = best.k;
    }
    render();
  })();
})();
