// 수급 탭 '지수 정기변경 패시브 수급' 칸: data/rebal.json (build_rebal.py ← KBJ PDF·ETF 순자산, FnGuide 유동비율, history.db)
// 예상 유입 = 추종 자금 × 편입 후 지수 비중, 패시브 효과 = 예상 유입 ÷ 20일 평균 거래대금 (신한투자증권 방식, docs/passive-inflow-plan.md)
// - 추종 자금은 화면에서 고른다: 1배 ETF(액티브 제외, 신한식) + TR·지수형 액티브·레버리지 현물(가정 %)·직접 넣는 금액(연기금·인덱스펀드)
// - '지금 시세 반영': data/quotes.json 으로 신규·편출 종목과 기존 구성종목 가격을 다시 매겨 비중을 고친다 (기존 종목 움직임 = 지수 움직임)
// - 행을 누르면 계산식이 숫자로 펼쳐진다
const Rebal = (() => {
  const open = new Set();
  let Q = null;

  const pct = (v, nd = 3) => (v == null ? '–' : `${(v * 100).toFixed(nd)}%`);
  const jo = v => (v == null ? "–" : `${(v / 10000).toFixed(v >= 1000000 ? 0 : 1)}조`);
  const man = v => (v == null ? '–' : `${Math.round(v / 10000).toLocaleString('ko-KR')}만 주`);
  const won = v => (v == null ? '–' : `${Math.round(v).toLocaleString('ko-KR')}원`);
  const dday = d => Math.ceil((new Date(d + 'T15:30:00+09:00') - Date.now()) / 864e5);

  // 추종 자금(억) — 고른 항목만 더한다
  function aum(I, st) {
    const a = I.aum, parts = [['1배 ETF', a.etf1]];
    if (st.rt && a.tr) parts.push(['TR ETF', a.tr]);
    if (st.ra && a.act) parts.push(['지수형 액티브', a.act]);
    const lp = Math.max(0, Math.min(200, +st.rlp || 0)) / 100;
    if (st.rl && a.lev && lp) parts.push([`레버리지 현물 ${Math.round(lp * 100)}%`, a.lev * lp]);
    const x = Math.max(0, +st.rx || 0) * 10000;
    if (x) parts.push(['직접 넣은 금액', x]);
    return { parts, total: parts.reduce((s, p) => s + p[1], 0) };
  }

  // 지금 시세로 다시 매긴 비중. 기존 구성종목 가격 움직임의 비중 가중 평균 = 지수 움직임 m
  function reprice(I, basis, on) {
    const id = { m: 1, f: {}, live: false };
    if (!on || !Q || !Q.d || Q.d < basis) return id;
    let sw = 0, sm = 0;
    for (const [c, w, pb] of I.cons) { const q = Q.m[c]; if (Array.isArray(q) && q[0] && pb) { sw += w; sm += w * q[0] / pb; } }
    if (!sw) return id;
    const m = sm / sw, f = {};
    for (const x of [...I.new, ...I.out]) { const q = Q.m[x.c]; f[x.c] = Array.isArray(q) && q[0] && x.pb ? q[0] / x.pb : 1; }
    return { m, f, live: true, t: Q.t, d: Q.d };
  }

  function rows(I, st, R) {
    const A = aum(I, st).total;
    const rN = I.new.map(x => (x.w == null ? null : x.w * I.denom * (R.f[x.c] ?? 1) / R.m));     // 지금 지수 대비 상대 크기
    const wO = I.out.map(o => (o.w == null ? null : o.w * (R.f[o.c] ?? 1) / R.m));
    const dn = 1 + rN.reduce((s, v) => s + (v || 0), 0) - wO.reduce((s, v) => s + (v || 0), 0);
    const nw = I.new.map((x, i) => { const w = rN[i] == null ? null : rN[i] / dn, amt = w == null ? null : A * w;
      return { ...x, wn: w, k: w && x.w ? w / x.w : 1, amt, pe: amt != null && x.tv20 ? amt / x.tv20 : null }; });
    const ot = I.out.map((o, i) => { const amt = wO[i] == null ? null : A * wO[i];
      return { ...o, wn: wO[i], amt, pe: amt != null && o.tv20 ? amt / o.tv20 : null }; });
    return { A, dn, nw, ot };
  }

  const bar = (v, dir) => { if (v == null) return ''; const w = Math.min(v / 8, 1) * 100;
    return `<span class="rb-bar"><i class="${dir}" style="width:${w.toFixed(1)}%"></i></span>`; };

  // 고른 방법의 유동비율과 이름
  const ffOf = x => (x.src === 'PDF' ? x.ff_pdf : x.src === 'DART' ? x.dart && x.dart.ff : x.ff_fn);
  const srcName = src => ({ PDF: 'PDF 역산', DART: 'DART', FnGuide: 'FnGuide' })[src] || src;
  const ym = d => `${d.slice(2, 4)}.${d.slice(5, 7)}`;
  const md = d => `${+d.slice(5, 7)}/${+d.slice(8, 10)}`;

  // DART 근거: 정기보고서 최대주주 등 + 자사주, DART 유동비율, 기준 구간 지분 공시 (build_rebal.py dart_view)
  function dartBlock(x, A, win) {
    const v = x.dart;
    if (!v) return '';
    const ser = v.s.map(([d, h, t]) => `${ym(d)} ${pct(h + t, 1)}`).join(' · ');
    const qe = v.s.some(r => r[0] === v.tsy_d);       // 자사주가 정기보고서 값인지, 그 뒤 결과보고서 값인지
    const tsy = v.tsy_d && v.tsy_d !== v.ff_d ? `, 자사주는 ${qe ? ym(v.tsy_d) : `${md(v.tsy_d)} 결과보고서`}` : '';
    const gap = x.ff_fn != null && x.ff_pdf != null ? x.ff_fn - x.ff_pdf : null;
    const auto = x.by === 'manual' && gap != null && Math.abs(gap) > 0.09
      ? `<div class="muted">자동 규칙: ${v.auto ? `${v.auto}${v.auto === x.src ? ' (사람이 고른 것과 같음)' : ' (사람이 고른 것과 다름)'}` : `못 정함 — 지분 변화 ${v.d == null ? '–' : `${(v.d * 100).toFixed(1)}%p`}가 두 유동비율 차이를 설명하지 못함`}</div>` : '';
    const wD = v.flag && x.w_dart != null ? x.w_dart * x.k : null;
    const alt = wD != null && x.by !== 'manual' && x.src !== 'DART'
      ? `<div class="up">DART 유동비율 ${pct(v.ff, 1)}이면 비중 ${pct(wD)}, 유입 ${U.eok(A * wD)} — FnGuide와 ${Math.abs((v.ff - x.ff_fn) * 100).toFixed(1)}%p 차이, 아래 공시로 어느 쪽이 맞는지 확인</div>` : '';
    const ev = [...v.ev].reverse(), shown = ev.slice(0, 8);
    const evs = shown.map(([d, t, f, no, late]) => `<span class="${late ? 'muted' : ''}">${md(d)} <a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${U.esc(no)}" target="_blank" rel="noopener">${U.esc(t)}</a>${f ? ` <span class="muted">${U.esc(f)}</span>` : ''}${late ? ' (심사기준일 뒤)' : ''}</span>`).join(' · ');
    return `<div><b>DART 지분</b> 최대주주 등 + 자사주 ${ser} → DART 유동비율 ${pct(v.ff, 1)} <span class="muted">(1 − 최대주주 등 − 자사주, ${ym(v.ff_d)}${tsy}${v.d != null ? ` · ${ym(v.d_from)}→${ym(v.ff_d)} ${v.d >= 0 ? '+' : ''}${(v.d * 100).toFixed(1)}%p` : ''})</span></div>
      ${alt}${auto}
      ${evs ? `<div class="small">지분 공시 ${md(win[0])} 뒤 ${ev.length}건: ${evs}${ev.length > shown.length ? ` <span class="muted">외 ${ev.length - shown.length}건</span>` : ''}</div>` : `<div class="muted small">${md(win[0])} 뒤 지분 공시 없음 (기관 약식 대량보유 제외)</div>`}`;
  }

  function formula(x, I, D, A, R, win) {
    const ff = ffOf(x);
    const Tafter = I.T * D.dn * R.m;
    const ffcap = x.wn * Tafter;
    const alts = [['FnGuide', x.ff_fn, x.w_fn], ['PDF 역산', x.ff_pdf, x.w_pdf]].filter(a => a[0] !== srcName(x.src) && a[1] != null && a[2] != null);
    const live = R.live ? `<div>지금 시세 ${won(x.pb * (R.f[x.c] ?? 1))} (기준 ${won(x.pb)}, ${U.pct((R.f[x.c] ?? 1) - 1)}), 지수 ${U.pct(R.m - 1)} → 비중 ×${x.k.toFixed(3)}</div>` : '';
    const pdfs = (x.pdfs || []).map(([n, w, q, cap]) => `${U.esc(n)} ${pct(w)}${cap ? '(상한 지수, 안 씀)' : ''} <span class="muted">${q}주</span>`).join(' · ');
    return `<div class="rb-f">
      <div><b>유입</b> = 추종 자금 ${jo(A)} × 비중 ${pct(x.wn)} = <b class="up">${U.eok(x.amt)}</b></div>
      <div><b>비중</b> = 유동시총 ${U.eok(ffcap)} ÷ 편입 후 지수 유동시총 ${jo(Tafter)} <span class="muted">(지금 ${jo(I.T * R.m)} × 편입·편출 뒤 ${D.dn.toFixed(4)})</span></div>
      <div><b>유동시총</b> = 발행주식 ${man(x.sh)} × ${won(x.pb * (R.f[x.c] ?? 1))} × 유동비율 ${pct(ff, 1)} <span class="muted">(${srcName(x.src)})</span></div>
      ${alts.map(a => `<div class="muted">${a[0]} 유동비율 ${pct(a[1], 1)}이면 비중 ${pct(a[2] * x.k)}, 유입 ${U.eok(A * a[2] * x.k)}</div>`).join('')}
      ${pdfs ? `<div class="muted">PDF 역산 근거: ${pdfs}</div>` : ''}
      ${x.why ? `<div>고른 이유: ${U.esc(x.why)}</div>` : x.check ? '<div class="up">두 유동비율이 크게 다름 — DART 자동 규칙으로도 못 정해 확인 필요</div>' : ''}
      ${dartBlock(x, A, win)}
      <div><b>패시브 효과</b> = ${U.eok(x.amt)} ÷ 20일 평균 거래대금 ${U.eok(x.tv20)} = <b>${x.pe == null ? '–' : `${Math.round(x.pe * 100).toLocaleString('ko-KR')}%`}</b></div>
      ${live}
      ${x.wa != null ? `<div><b>실제 비중</b> ${pct(x.wa)} (${I.actual_asof} PDF) — 추정 ${pct(x.w)} 대비 ${U.pct(x.w / x.wa - 1)}</div>` : ''}
    </div>`;
  }

  function controls(data, st, pg) {
    const I = data.idx[st.ri] || data.idx.KQ150, a = I.aum;
    const quoted = Q && Q.d >= data.basis;
    const seg = Object.entries(data.idx).map(([k, v]) => [k, `${v.name} ${v.new.length}`]);
    return `<div class="frow fm-ctl">${pg.seg('ri', seg)}${pg.seg('rv', [['in', '편입'], ['out', '편출']])}${pg.seg('rs', [['pe', '패시브 효과 순', '예상 유입 ÷ 20일 평균 거래대금'], ['amt', '금액 순']])}
        ${quoted ? pg.chk('rq', `지금 시세 반영 <span class="muted">${U.timeLabel(Q.t)}</span>`, '신규·편출 종목과 기존 구성종목을 지금 시세로 다시 매김 (기존 종목 움직임 = 지수 움직임)') : ''}</div>
      <div class="frow fm-ctl rb-aum"><span class="muted small">추종 자금</span><span class="ef-st">1배 ETF ${jo(a.etf1)}</span>
        ${a.tr ? pg.chk('rt', `TR ETF ${jo(a.tr)}`, '코스피 200 TR 추종 ETF (신한식에 포함)') : ''}
        ${a.act ? pg.chk('ra', `지수형 액티브 ${jo(a.act)}`, '같은 기초지수의 액티브 ETF — 지수와 다르게 담을 수 있어 신한식에서는 뺀다') : ''}
        ${a.lev ? `${pg.chk('rl', `레버리지 ${jo(a.lev)} 중 현물`, '2배 ETF 는 선물·스왑으로 대부분 담는다. 현물로 담는 몫을 순자산 대비 %로 가정')}<input type="number" class="rb-num" data-q="rlp" value="${U.esc(st.rlp)}" min="0" max="200" step="5" aria-label="레버리지 현물 비율 %">%` : ''}
        <label class="muted small">+ 연기금·인덱스펀드 <input type="number" class="rb-num" data-q="rx" value="${U.esc(st.rx)}" min="0" step="0.5" placeholder="0" aria-label="추가 추종 자금(조원)">조</label></div>
      <div id="rebal-body"></div>`;
  }

  function body(data, st) {
    const I = data.idx[st.ri] || data.idx.KQ150;
    const R = reprice(I, data.basis, !!st.rq);
    const D = rows(I, st, R), au = aum(I, st);
    const inSum = D.nw.reduce((s, x) => s + (x.amt || 0), 0), outSum = D.ot.reduce((s, x) => s + (x.amt || 0), 0);
    const key = st.rs === 'amt' ? x => -(x.amt ?? -1) : x => -(x.pe ?? -1);
    const hasA = D.nw.some(x => x.wa != null);
    const head = `<div class="rb-sum small">추종 자금 <b>${jo(au.total)}</b> = ${au.parts.map(p => `${p[0]} ${jo(p[1])}`).join(' + ')} <span class="muted">(${I.aum.date})</span><br>
      편입 ${D.nw.length}종목 <b class="up">${U.eok(inSum)}</b> 매수 · 편출 ${D.ot.length}종목 <b class="down">${U.eok(outSum)}</b> 매도 ·
      남는 종목은 비중이 ${((1 - 1 / D.dn) * 100).toFixed(1)}% 줄어 약 <b class="down">${U.eok(inSum - outSum)}</b> 매도
      ${R.live ? `<span class="muted"> · ${U.timeLabel(R.t)} 시세 반영(지수 ${U.pct(R.m - 1)})</span>` : `<span class="muted"> · ${U.dateLabel(data.basis)} 종가 기준</span>`}</div>`;
    let tbl;
    if (st.rv === 'out') {
      const L = [...D.ot].sort((a, b) => key(a) - key(b));
      tbl = `<table class="tbl" data-nosort><thead><tr><th>종목</th><th class="num">시총</th><th class="num">지금 비중</th><th class="num">예상 유출</th><th class="num">20일 평균 거래대금</th><th class="num" title="예상 유출 ÷ 20일 평균 거래대금">패시브 효과</th><th></th></tr></thead>
        <tbody>${L.map(o => `<tr><td>${Stock.link({ c: o.c, n: o.n })}</td><td class="num">${U.eok(o.mc)}</td><td class="num">${pct(o.wn)}</td><td class="num"><b class="down">${U.eok(o.amt)}</b></td>
          <td class="num">${U.eok(o.tv20)}</td><td class="num"><b class="down">${o.pe == null ? '–' : `${Math.round(o.pe * 100).toLocaleString('ko-KR')}%`}</b></td><td>${bar(o.pe, 'down')}</td></tr>`).join('')}</tbody></table>`;
    } else {
      const L = [...D.nw].sort((a, b) => key(a) - key(b));
      tbl = `<table class="tbl rb-tbl" data-nosort><thead><tr><th>종목</th><th class="num">시총</th><th class="num" title="편입 후 지수 유동시총 대비">편입 후 비중</th><th class="num">예상 유입</th><th class="num">20일 평균 거래대금</th>
          <th class="num" title="예상 유입 ÷ 20일 평균 거래대금">패시브 효과</th><th></th><th class="num" title="고른 유동비율 (FnGuide 또는 PDF 역산)">유동비율</th><th>근거</th>${hasA ? '<th class="num">실제 비중</th>' : ''}</tr></thead>
        <tbody>${L.map(x => { const on = open.has(x.c), ws = [x.w, x.w_fn, x.w_pdf].filter(v => v != null), lo = Math.min(...ws), hi = Math.max(...ws);
          const ff = ffOf(x);
          // 두 방법(FnGuide·PDF 역산) 범위: 2% 넘게 다르고, 소수 셋째 자리로 찍어도 다를 때만 (작은 비중은 반올림하면 같아진다)
          const [rl, rh] = [lo, hi].map(v => (v * x.k * 100).toFixed(3)), rng = hi / lo > 1.02 && rl !== rh;
          return `<tr class="ef-row${on ? ' on' : ''}" data-ro="${x.c}"><td><span class="ef-tw">${on ? '▾' : '▸'}</span> ${Stock.link({ c: x.c, n: x.n })}</td><td class="num">${U.eok(x.mc)}</td>
            <td class="num">${pct(x.wn)}${rng ? `<div class="muted small">${rl}~${rh}</div>` : ''}</td>
            <td class="num"><b class="up">${U.eok(x.amt)}</b></td><td class="num">${U.eok(x.tv20)}</td>
            <td class="num"><b class="up">${x.pe == null ? '–' : `${Math.round(x.pe * 100).toLocaleString('ko-KR')}%`}</b></td><td>${bar(x.pe, 'up')}</td>
            <td class="num">${pct(ff, 1)}</td><td class="small"><span class="ef-st" title="${U.esc(x.why || (x.src === 'PDF' ? '같은 유동비율을 쓰는 KRX 지수 ETF 구성 비중에서 역산' : 'FnGuide 유동비율 × 기존 구성종목으로 보정'))}">${srcName(x.src)}</span>${x.why && x.src !== 'DART' ? ` <span class="muted" title="${U.esc(x.why)}">${x.by === 'auto' ? 'DART 자동' : 'DART'}</span>` : ''}${x.check ? ' <span class="ef-st up" title="PDF 역산과 FnGuide 유동비율이 9%p 넘게 다르고 DART 자동 규칙으로도 못 정함 — 행을 눌러 공시 확인">확인 필요</span>' : ''}${x.dart && x.dart.flag && x.by !== 'manual' ? ` <span class="ef-st up" title="DART 유동비율 ${pct(x.dart.ff, 1)} (1 − 최대주주 등 − 자사주) — FnGuide ${pct(x.ff_fn, 1)}와 ${Math.round(data.dart.gap * 100)}%p 넘게 다름. 행을 눌러 공시 확인">DART 다름</span>` : ''}</td>
            ${hasA ? `<td class="num">${x.wa == null ? '–' : `${pct(x.wa)}<div class="muted small">${U.pct(x.w / x.wa - 1)}</div>`}</td>` : ''}</tr>
            ${on ? `<tr class="ef-det"><td colspan="${hasA ? 10 : 9}">${formula(x, I, D, D.A, R, data.dart && data.dart.win)}</td></tr>` : ''}`; }).join('')}</tbody></table>`;
    }
    const C = data.check;
    const chk = C && C.rows.length ? `<details class="rb-chk"><summary class="small">신한 숫자와 대조 · ${C.basis} 종가 · ${C.rows.length}개 · 오차 중앙 ${C.med_abs}%</summary>
      <table class="tbl" data-nosort><thead><tr><th>종목</th><th>항목</th><th class="num">신한</th><th class="num">이 화면</th><th class="num">차이</th><th>방법</th></tr></thead>
      <tbody>${C.rows.map(r => { const K = { w: ['비중', '%'], inflow: ['예상 유입', '억'], pe: ['패시브 효과', '%'] }[r.kind];
        return `<tr><td>${U.esc(r.n)}</td><td>${K[0]}</td><td class="num">${r.shinhan}${K[1]}</td><td class="num">${r.ours}${K[1]}</td><td class="num">${r.err > 0 ? '+' : ''}${r.err}%</td><td class="small">${r.src}</td></tr>`; }).join('')}</tbody></table>
      <p class="muted small">${U.esc(C.source)}. 같은 기준일 종가와 같은 추종 자금(1배 ETF·TR, 액티브 제외)으로 맞춘 값.</p></details>` : '';
    const cal = I.calib;
    const note = `<p class="muted small fm-note">예상 유입 = 추종 자금 × 편입 후 지수 비중. 비중은 두 가지로 구합니다.
      PDF 역산은 같은 유동비율을 쓰는 KRX 지수 ETF(KRX300·KRX 헬스케어·KRX 섹터 등)의 구성 비중에서 거꾸로 구합니다.
      FnGuide 보정은 FnGuide 유동비율로 만든 유동시총을 지수 유동시총 ${jo(I.T)}로 나눕니다. 지수 유동시총은 기존 ${cal.n}종목으로 맞췄고, 종목별 오차 중앙값은 ${(cal.med_abs * 100).toFixed(1)}%입니다.
      12월 정기변경 때 KRX가 유동비율을 다시 매기므로 기본은 최신 지분을 담은 FnGuide 값을 씁니다. 두 유동비율이 ${Math.round(data.gap_pp * 100)}%p 넘게 다르면 사람이 DART로 확인한 쪽, 없으면 DART 자동 규칙을 따릅니다.
      ${data.dart ? `자동 규칙은 ${U.dateLabel(data.dart.win[0])}~${U.dateLabel(data.dart.win[1])}(6월·12월 심사기준일 추정) 사이 최대주주 등 + 자사주 지분이 차이 방향으로 ${Math.round(data.dart.move * 100)}%p 넘게 바뀌었으면 FnGuide, ${Math.round(data.dart.flat * 100)}%p 안쪽이면 PDF 역산입니다.
      FnGuide가 DART 유동비율(1 − 최대주주 등 − 자사주)과 ${Math.round(data.dart.gap * 100)}%p 넘게 다르면 'DART 다름'으로 표시만 합니다.` : ''}
      실제 매매 금액은 ${U.dateLabel(data.event.rebalance)} 종가로 정해집니다. ETF만 넣었으므로 인덱스펀드·연기금 몫은 빠진 하한입니다.
      KODEX ${I.name} PDF ${I.pdf_asof}자(${U.dateLabel(data.basis)} 종가) 기준이고, 행을 누르면 계산식이 펼쳐집니다.
      명단: ${data.event.sources.map(s => `<a href="${U.esc(s.url)}" target="_blank" rel="noopener">${U.esc(s.name)}</a>`).join(' · ')}</p>`;
    return head + `<div class="tbl-wrap">${tbl}</div>` + chk + note;
  }

  return {
    // box: #rebal, title: #rebal-title. typing 이면 입력칸이 있는 위쪽은 그대로 두고 아래만 다시 그린다
    render(box, title, data, st, pg, typing) {
      if (!data) { title.innerHTML = ''; box.hidden = true; return; }
      box.hidden = false;
      const d = dday(data.event.rebalance);
      title.innerHTML = `<h2>지수 정기변경 패시브 수급</h2><span class="muted small">${U.esc(data.event.title)} · ${U.dateLabel(data.event.announced)} 발표 ·
        ${U.dateLabel(data.event.rebalance)} 리밸런싱(종가)${d >= 0 ? ` D-${d}` : ''} · ${U.dateLabel(data.event.effective)} 적용 · 신한투자증권 방식</span>`;
      if (!typing || !box.querySelector('#rebal-body')) box.innerHTML = controls(data, st, pg);
      box.querySelector('#rebal-body').innerHTML = body(data, st);
    },
    // 시세를 받아 두고 다시 그리기
    async quotes(redraw) { Q = await U.quotes(); if (Q) redraw(); },
    toggle(c) { open.has(c) ? open.delete(c) : open.add(c); },
  };
})();
