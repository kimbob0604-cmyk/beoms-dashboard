// 반도체 탭: data/semi.json (build_semi.py) — 밸류체인 도식 위에 국내·해외 종목을 앉히고 분기 매출·영업이익, 수주, 빅테크 AI capex 를 본다
// - 도식: 단계(수요 → 설계 → 팹 → 전공정·소재·후공정 → 패키징·기판)마다 칸. 칸 색 = 최근 분기 매출 YoY 중앙값, 칸을 누르면 아래 표가 그 칸으로
// - 수요: 빅테크 capex 분기 합계(SEC 공시) · 공급: 마이크론·TSMC·인텔 capex
// - 표: 칸별 종목. 국내는 펀더 손익(억원), 해외는 회사 통화(백만). 국내 종목명 → 종목 패널, 해외 → 야후 파이낸스
// 계획: docs/semi-plan.md
(() => {
  const $ = id => document.getElementById(id);
  const DEFAULTS = { cell: '', ov: 'all', sort: 'mc', q: '', rack: '2' };
  const pg = U.page(DEFAULTS, (patch, typing) => { if ('rack' in patch) return renderAI(); if (!typing) { renderFilters(); renderChain(); } renderTable(); });
  const st = pg.state;
  let data = null;
  const esc = s => U.esc(s);
  const pc = (v, nd = 0) => (v == null ? '<span class="muted">–</span>' : `<b class="${U.cls(v)}">${v > 0 ? '+' : ''}${v.toFixed(nd)}%</b>`);
  const pp = v => (v == null ? '<span class="muted">–</span>' : `<b class="${U.cls(v)}">${v > 0 ? '+' : ''}${v.toFixed(1)}%p</b>`);
  const n0 = v => (v == null ? '–' : Math.abs(v) >= 100 ? Math.round(v).toLocaleString('ko-KR') : v.toFixed(1));
  const qlab = cq => (cq ? `${cq[5]}Q${cq.slice(2, 4)}` : '–');
  const usdB = v => (v == null ? '–' : v >= 1e12 ? `$${(v / 1e12).toFixed(2)}T` : `$${(v / 1e9).toFixed(v >= 1e10 ? 0 : 1)}B`);
  const CASE = { both: ['동반 서프', 'up'], op: ['영익 서프', 'up'], sales: ['매출 서프', 'up'], miss: ['미스', 'down'], inline: ['부합', 'muted'] };
  const cellOf = id => data.cells.find(c => c.id === id);

  // ---------- 도식 ----------
  // 단계마다 가로 띠(칸이 많으면 여러 줄), 띠 사이에 '무엇이 흐르는가'
  const FLOW = {
    sys: 'AI capex → 가속기·서버 주문 → 랙 부품(소캠·광·전원·MLB)',
    dc: '랙 전력 100kW → MW급 · 수랭 → 데이터센터 전력기기·냉각',
    design: '빅테크 → GPU·자체 ASIC 설계 주문',
    fab: '설계 → 웨이퍼 주문(파운드리) · HBM·DRAM·eSSD 주문(메모리)',
    fe: '팹 증설 capex → 장비 반입 때 수주, 설치·검수 뒤 매출 (6~12개월 뒤)',
    fep: '장비 출하·팹 가동 → 서브시스템·소모 부품·팹 인프라',
    mat: '팹 가동률·웨이퍼 투입량 → 같은 분기 소재 매출',
    be: 'HBM·첨단 패키징 증설 → 본더·리플로우·검사 장비',
    bec: '신제품 수·출하량 → 프로브카드·소켓 반복 매출',
    osat: '칩 출하·AI 서버 → 패키징 외주·기판·모듈 PCB·MLB',
  };
  function heat(v) {   // 매출 YoY → 칸 채움 (붉을수록 증가, 푸를수록 감소)
    if (v == null) return 'var(--chip)';
    const a = Math.min(Math.abs(v) / 80, 1) * 0.55 + 0.08;
    return v >= 0 ? `color-mix(in srgb, var(--up) ${Math.round(a * 100)}%, var(--card))` : `color-mix(in srgb, var(--down) ${Math.round(a * 100)}%, var(--card))`;
  }
  function renderChain() {
    const W = 1000, LW = 128, BH = 58, RG = 6, GAP = 28, MAXR = 5, top = 6;
    let y = top, svg = '';
    data.stages.forEach((sg, si) => {
      if (si > 0) {
        svg += `<line x1="${LW + 6}" y1="${y - GAP + 4}" x2="${LW + 6}" y2="${y - 4}" class="sm-arrow" marker-end="url(#sm-ah)"/>
          <text x="${LW + 16}" y="${y - GAP / 2 + 4}" class="sm-flow">${esc(FLOW[sg.id] || '')}</text>`;
      }
      const cs = data.cells.filter(c => c.stage === sg.id);
      const rows = Math.ceil(cs.length / MAXR), per = Math.ceil(cs.length / rows);
      const bandH = rows * BH + (rows - 1) * RG;
      svg += `<text x="4" y="${y + bandH / 2 - 2}" class="sm-stage">${esc(sg.name)}</text><text x="4" y="${y + bandH / 2 + 14}" class="sm-sdesc">${esc(sg.desc)}</text>`;
      cs.forEach((c, i) => {
        const r = Math.floor(i / per), k = i % per, nInRow = Math.min(per, cs.length - r * per), w = (W - LW) / nInRow;
        const x = LW + k * w, yy = y + r * (BH + RG), on = st.cell === c.id;
        svg += `<g class="sm-cell${on ? ' on' : ''}${st.cell && !on ? ' dim' : ''}" data-cell="${c.id}"><title>${esc(c.name)} — ${esc(c.driver)}</title>
          <rect x="${x + 3}" y="${yy}" width="${w - 6}" height="${BH}" rx="9" style="fill:${heat(c.yoy)}"/>
          <text x="${x + 12}" y="${yy + 19}" class="sm-name">${esc(c.sn || c.name)}</text>
          <text x="${x + 12}" y="${yy + 35}" class="sm-num">국내 ${c.nk}${c.n - c.nk ? ` · 해외 ${c.n - c.nk}` : ''} · 매출 ${c.yoy == null ? '–' : (c.yoy > 0 ? '+' : '') + c.yoy.toFixed(0) + '%'}</text>
          <text x="${x + 12}" y="${yy + 50}" class="sm-sub">OPM ${c.opm == null ? '–' : c.opm.toFixed(0) + '%'}${c.con90 ? ` · 수주 ${c.con90}` : ''}${c.beat + c.miss ? ` · 서프${c.beat}·미스${c.miss}` : ''}</text></g>`;
      });
      y += bandH + GAP;
    });
    const H = y - GAP + 6;
    const sel = st.cell && cellOf(st.cell);
    const nk = data.stocks.filter(s => !s.ov).length;
    $('chain').innerHTML = `<div class="col-head"><h3>반도체·AI 인프라 밸류체인 <span class="muted">${data.stages.length}단계 ${data.cells.length}칸 · 국내 ${nk} · 해외 ${data.stocks.length - nk} · ${qlab(data.last)} 기준</span></h3>
        <span class="muted small">칸 색 = 그 칸 종목의 최근 분기 매출 전년 대비 중앙값 · 칸을 누르면 아래 표가 그 칸만 · 수주 = 최근 90일 단일판매·공급계약</span></div>
      <div class="sm-wrap"><svg viewBox="0 0 ${W} ${H}" class="sm-svg" role="img" aria-label="반도체 밸류체인 도식">
        <defs><marker id="sm-ah" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="sm-ahead"/></marker></defs>${svg}</svg></div>
      ${sel ? `<p class="sm-driver"><b>${esc(sel.name)}</b> — ${esc(sel.driver)} <button class="linkish" data-clear>칸 선택 풀기</button></p>` : ''}`;
  }

  // ---------- AI 개괄: 랙 해부 · 가속기 비교 · 학습 vs 추론 · capex 가이던스 · 새 소식 ----------
  const srcLinks = list => (list || []).filter(x => x && x.url).slice(0, 4).map(x => `<a href="${esc(x.url)}" target="_blank" rel="noopener" title="${esc(x.t || '')}">${esc((x.t || '출처').slice(0, 24))}${x.d ? ` ${x.d.slice(2)}` : ''} ↗</a>`).join(' · ');
  const tkLink = t => {   // 공급사 → 국내면 종목 패널, 해외면 표 칸
    if (!t.ticker) return esc(t.n);
    if (/^\d{6}$/.test(t.ticker)) return `<a href="https://finance.naver.com/item/main.naver?code=${t.ticker}" data-code="${t.ticker}" class="sm-kr">${esc(t.n)}</a>`;
    return `<span title="${esc(t.ticker)}">${esc(t.n)}</span>`;
  };
  function rackHtml(r) {
    const g = r.gpu || {}, h = g.hbm || {}, c = r.cpu || {}, su = r.scaleup || {};
    const row = (k, v, note) => (v == null || v === '' ? '' : `<tr><th>${k}</th><td>${v}${note ? `<small class="muted sm-note">${esc(note)}</small>` : ''}</td></tr>`);
    if (!r.gpu) return `<p>${esc(r.notes || r.status || '')}</p><p class="small muted">${srcLinks(r.src)}</p>`;
    return `<table class="tbl sm-spec">
      ${row('상태 · 출하', `${esc(r.status || '–')}${r.ship ? ` · <b>${esc(r.ship)}</b>` : ''}`)}
      ${row('GPU', `${esc(g.name || '–')} × ${g.n ?? '–'}${g.node ? ` · ${esc(g.node)}` : ''}${g.pkg ? ` · ${esc(g.pkg)}` : ''}`)}
      ${row('HBM (GPU당)', h.gen ? `<b>${esc(h.gen)}</b> ${h.gb ?? '–'}GB${h.stacks ? ` · ${h.stacks}스택` : ''}${h.tbps ? ` · ${h.tbps}TB/s` : ''}` : null, h.note)}
      ${row('CPU · CPU 메모리', c.name ? `${esc(c.name)}${c.n ? ` × ${c.n}` : ''} · <b>${esc(c.mem || '–')}</b>${c.gb ? ` ${c.gb >= 1000 ? (c.gb / 1024).toFixed(1) + 'TB' : c.gb + 'GB'}/CPU` : ''}` : null, c.note)}
      ${row('스케일업', [su.nvlink, su.per_gpu_tbps && `GPU당 ${su.per_gpu_tbps}TB/s`, su.rack_tbps && `랙 ${su.rack_tbps}TB/s`, su.switch_chips && `스위치 칩 ${su.switch_chips}개`, su.domain && `도메인 ${su.domain}`].filter(Boolean).map(esc).join(' · '), su.note)}
      ${row('NIC · 스케일아웃', [r.nic, r.scaleout].filter(Boolean).map(esc).join('<br>'))}
      ${row('전력 · 냉각', `${r.power_kw ? `<b>${r.power_kw}kW</b>/랙 · ` : ''}${esc(r.cooling || '–')}${r.power_arch ? `<br>${esc(r.power_arch)}` : ''}`, r.power_note)}
      ${(r.conflicts || []).length ? `<tr><th>출처 상충</th><td class="small">${r.conflicts.map(x => esc(typeof x === 'string' ? x : JSON.stringify(x))).join('<br>')}</td></tr>` : ''}
      </table><p class="small muted">출처: ${srcLinks(r.src)}</p>`;
  }
  function renderAI() {
    const ai = data.ai || {};
    if (!ai.racks) { $('ai').innerHTML = ''; return; }
    const ri = Math.min(+st.rack || 0, ai.racks.length - 1), r = ai.racks[ri];
    const chips = ai.chips || [];
    const f = v => (v == null ? '<span class="muted">–</span>' : v);
    const newsNew = (ai.news || []).filter(n => n.new);
    $('ai').innerHTML = `<div class="col-head"><h3>AI 인프라 개괄 <span class="muted">규격표 ${esc(ai.as_of || '')} 기준 · 숫자마다 출처</span></h3>
        <span class="muted small">학습·추론이 어떤 칩·메모리·네트워크·전력을 요구하는지 → 아래 밸류체인 칸으로 이어집니다${newsNew.length ? ` · <b class="up">규격표에 없는 새 제품 소식 ${newsNew.length}건</b>` : ''}</span></div>
      <div class="sm-ai">
        <div class="sm-ai-rack"><h4>AI 랙 해부 <span class="muted small">엔비디아 세대별</span></h4>
          <div class="seg sm-racks">${ai.racks.map((x, i) => `<button data-rack="${i}" class="${i === ri ? 'on' : ''}">${esc(x.id.split(' (')[0].split(' / ')[0])}</button>`).join('')}</div>
          ${rackHtml(r)}</div>
        <div class="sm-ai-bom"><h4>랙 부품과 공급사 <span class="muted small">국내 상장사는 이름을 누르면 종목 설명</span></h4>
          <table class="tbl sm-bom">${(ai.bom || []).map(b => `<tr><th>${esc(b.part)}<small class="muted sm-note">${esc(b.where || '')}</small></th>
            <td>${(b.suppliers || []).map(t => `<span class="sm-sup${t.country === 'KR' ? ' kr' : ''}" title="${esc(t.note || '')}">${tkLink(t)}</span>`).join(' ')}</td></tr>`).join('')}</table></div>
      </div>
      <div class="sm-ai2">
        <div><h4>가속기 비교 <span class="muted small">엔비디아 vs 구글 TPU · AWS 트레이니엄 · AMD · MS · 메타 — FP4/FP8 은 PF(밀집 기준이 아닐 수 있음)</span></h4>
          <div class="tbl-wrap"><table class="tbl sm-chips"><thead><tr><th>칩</th><th>설계 파트너</th><th>HBM</th><th class="num">GB</th><th class="num">TB/s</th><th class="num">FP8</th><th class="num">FP4</th><th>스케일업</th><th>출시</th><th>용도</th></tr></thead>
          <tbody>${chips.map(c => `<tr title="${esc(c.note || '')}"><td><b>${esc(c.vendor)}</b> ${esc(c.name || c.id)}${c.src?.[0]?.url ? ` <a href="${esc(c.src[0].url)}" target="_blank" rel="noopener">↗</a>` : ''}${c.added ? ` <span class="tag sm-added" title="새 소식에서 반영">${esc(c.added.slice(5))} 추가</span>` : ''}</td><td>${f(c.partner && esc(c.partner))}</td>
            <td>${f(c.hbm?.gen && esc(c.hbm.gen))}</td><td class="num">${f(c.hbm?.gb)}</td><td class="num">${f(c.hbm?.tbps)}</td><td class="num">${f(c.fp8_pf)}</td><td class="num">${f(c.fp4_pf)}</td>
            <td class="small">${f(c.scaleup && esc([c.scaleup.n && `${c.scaleup.n}칩`, c.scaleup.link].filter(Boolean).join(' · ')))}</td><td class="small">${f(c.ship && esc(c.ship))}</td><td class="small">${f(c.use && esc(c.use))}</td></tr>`).join('')}</tbody></table></div>
          <p class="muted small">줄에 마우스를 올리면 출처 메모(추정·계산·상충). ${(ai.changelog || []).slice(-3).reverse().map(x => `${esc(x.d)} ${esc(x.t)}`).join(' · ')}</p></div>
      </div>
      <div class="sm-ai3">
        <div><h4>학습 vs 추론 — 무엇이 바뀌나</h4><ul class="sm-points">${(ai.train_vs_infer || []).map(x => `<li>${esc(x.point)} ${(x.impact || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}${x.src ? ` <a href="${esc(x.src)}" target="_blank" rel="noopener">↗</a>` : ''}</li>`).join('')}
          ${(ai.nv_notes || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
        <div><h4>빅테크 capex 가이던스</h4><table class="tbl sm-mini">${(ai.capex_guide || []).map(g => `<tr><td><b>${esc(g.co)}</b> ${g.year || ''}</td><td class="small">${esc(g.guide || '')} <span class="muted">${esc(g.said || '')}</span>${g.src ? ` <a href="${esc(g.src)}" target="_blank" rel="noopener">↗</a>` : ''}</td></tr>`).join('')}</table>
          <h4>최근 소식 <span class="muted small">공식 피드·전문지에서 가속기·메모리·패키징 낱말이 든 글 (매일)</span></h4>
          <ul class="sm-news">${(ai.news || []).slice(0, 14).map(n => `<li>${n.new ? `<b class="up" title="규격표에 없는 제품명 — 규격표 검토 필요">새 ${esc(n.new)}</b> ` : ''}<a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a> <span class="muted small">${esc(n.src)} · ${esc((n.date || '').slice(5))}</span></li>`).join('')}</ul></div>
      </div>
      ${(ai.caveat || []).filter(Boolean).length ? `<p class="muted small sm-cav">유의: ${(ai.caveat || []).filter(Boolean).map(esc).join(' ')}</p>` : ''}`;
  }

  // ---------- 수요·공급 capex ----------
  function bars(vals, labels, { h = 120, fmt = v => v, cls = '' } = {}) {
    const max = Math.max(...vals.filter(v => v != null), 1), bw = 100 / vals.length;
    return `<svg viewBox="0 0 100 ${h / 3}" preserveAspectRatio="none" class="sm-bars ${cls}">${vals.map((v, i) => v == null ? ''
      : `<rect x="${i * bw + bw * 0.15}" y="${(1 - v / max) * (h / 3 - 1)}" width="${bw * 0.7}" height="${v / max * (h / 3 - 1)}"><title>${labels[i]} ${fmt(v)}</title></rect>`).join('')}</svg>
      <div class="sm-blab">${labels.map((l, i) => `<span style="width:${bw}%">${i % 2 === labels.length % 2 ? l : ''}</span>`).join('')}</div>`;
  }
  function renderDemand() {
    const c = data.capex, qs = data.qs, L = qs.map(qlab), n = qs.length - 1;
    const last = c.tot.map((v, i) => [v, i]).filter(([v]) => v != null).pop();
    const i = last ? last[1] : n;
    const cos = Object.keys(c.cos).filter(t => t !== 'CRWV');
    const sup = data.supply.capex;
    $('demand').innerHTML = `<div class="sm-dgrid">
      <div class="card sm-dcard"><h4>빅테크 AI capex <span class="muted small">MS·알파벳·아마존·메타·오라클 분기 유형자산 취득 합계 (SEC 공시)</span></h4>
        <p class="sm-big">$${(c.tot[i] / 1000).toFixed(1)}B <span class="small muted">${L[i]}</span> ${pc(c.yoy[i])} <span class="muted small">전년 대비</span></p>
        ${bars(c.tot, L, { fmt: v => `$${(v / 1000).toFixed(1)}B` })}
        <table class="tbl sm-mini"><tr><th></th>${[i - 4, i - 1, i].map(k => `<th class="num">${L[k] || ''}</th>`).join('')}<th class="num">YoY</th></tr>
          ${cos.concat(['CRWV']).map(t => { const v = c.cos[t]; return `<tr><td>${esc(c.names[t] || t)}</td>${[i - 4, i - 1, i].map(k => `<td class="num">${v[k] == null ? '–' : (v[k] / 1000).toFixed(1)}</td>`).join('')}<td class="num">${v[i] && v[i - 4] ? pc((v[i] / v[i - 4] - 1) * 100) : '–'}</td></tr>`; }).join('')}
        </table><p class="muted small">십억 달러. 금융리스로 들인 서버(아마존·MS)는 빠져 실제 투자보다 작다. 코어위브는 합계에 넣지 않았다. 회계연도가 다른 회사는 분기 끝에서 45일 앞이 든 달력 분기로 맞췄다.</p></div>
      <div class="card sm-dcard"><h4>공급 쪽 capex <span class="muted small">메모리·파운드리 증설 투자 (회사 통화 십억)</span></h4>
        <table class="tbl sm-mini"><tr><th></th>${[i - 4, i - 1, i].map(k => `<th class="num">${L[k] || ''}</th>`).join('')}<th class="num">YoY</th></tr>
          ${Object.entries(sup).map(([t, v]) => { const krw = data.supply.cur[t] === 'KRW', f = x => (x == null ? '–' : krw ? (x / 1e6).toFixed(1) : (x / 1000).toFixed(1)); return `<tr><td>${esc(c.names[t] || t)} <small class="muted">${krw ? '조원' : (data.supply.cur[t] || '') + ' 십억'}</small></td>${[i - 4, i - 1, i].map(k => `<td class="num">${f(v[k])}</td>`).join('')}<td class="num">${v[i] && v[i - 4] ? pc((v[i] / v[i - 4] - 1) * 100) : '–'}</td></tr>`; }).join('')}
        </table>
        <p class="muted small">삼성·하이닉스 = DART 현금흐름표 유형자산 취득(연결, 분기는 누적끼리 뺀 값). 해외 = SEC·야후.</p></div></div>
      ${fabsHtml()}${ordersHtml()}${facHtml()}${lagHtml()}`;
  }

  // 증설 트래커: 팹마다 단계 막대(계획 → … → 풀가동), 투자액, 장비 반입 시점, 최신 소식, 연결한 DART 신규시설투자 공시
  function fabsHtml() {
    const F = data.fabs;
    if (!F || !F.fabs) return '';
    const ord = F.stage_order || [];
    const bar = x => { const k = ord.indexOf(x.stage); return `<div class="sm-stg">${ord.map((sname, i) => `<i class="${k < 0 ? '' : i < k ? 'done' : i === k ? 'cur' : ''}" title="${esc(sname)}"></i>`).join('')}</div>`; };
    const cos = [...new Set(F.fabs.map(x => x.co))];
    return `<div class="card sm-dcard sm-wide"><h4>증설 트래커 <span class="muted small">팹·패키징 라인별 단계 · ${esc(F.as_of || '')} 기준 · 단계: ${ord.join(' → ')} · 마우스를 올리면 단계별 날짜·출처 상충</span></h4>
      ${(F.cycle || []).length ? `<ul class="sm-points">${F.cycle.map(c => `<li>${esc(c)}</li>`).join('')}</ul>` : ''}
      <div class="tbl-wrap"><table class="tbl sm-mini sm-fabs"><thead><tr><th>팹</th><th>제품</th><th>단계</th><th>투자</th><th>장비 반입</th><th>최신</th></tr></thead><tbody>
      ${cos.map(co => `<tr class="sm-group"><td colspan="6">${esc(co)}${(F.capex || []).filter(c => c.co === co).map(c => ` <span class="muted small">· ${esc(String(c.year))} ${esc(c.guide)}</span>`).join('')}</td></tr>
        ${F.fabs.filter(x => x.co === co).map(x => `<tr title="${esc((x.stages || []).map(t => `${t.s} ${t.d || ''}`).join(' / ') + ((x.conflicts || []).length ? ' | 상충: ' + x.conflicts.join(' / ') : ''))}">
          <td><b>${esc(x.site)}</b>${(x.conflicts || []).length ? ' <span class="tag" title="출처 상충">상충</span>' : ''}</td><td class="small">${esc(x.product || '')}</td>
          <td>${bar(x)}<small>${esc(x.stage || '미확보')}</small></td>
          <td class="small">${esc(x.invest || '–')}${(x.dart || []).map(d => `<br><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${d.r}" target="_blank" rel="noopener" title="${esc(d.purpose || '')}${d.note ? ' · ' + esc(d.note) : ''}">공시 ${d.d.slice(2)} ${d.amt >= 10000 ? (d.amt / 10000).toFixed(1) + '조' : n0(d.amt) + '억'}${d.note ? '?' : ''}</a>`).join('')}</td>
          <td class="small">${esc(x.tool_in || '–')}</td>
          <td class="small">${x.latest ? `${esc(x.latest.t || '')} <span class="muted">${esc(x.latest.d || '')}</span>${x.latest.src ? ` <a href="${esc(x.latest.src)}" target="_blank" rel="noopener">↗</a>` : ''}` : '–'}</td></tr>`).join('')}`).join('')}
      </tbody></table></div><p class="muted small">${esc(F.note || '')} 장비 반입 시점이 다가오는 팹 → 전공정 장비 칸 수주, 램프 중인 팹 → 소재·부품 칸 매출로 이어집니다.</p></div>`;
  }
  // 고객별 분기 수주: 전공정 장비·부품·후공정·테스트 칸 종목의 단일판매·공급계약 합계 (억원)
  function ordersHtml() {
    const o = data.orders_q;
    if (!o) return '';
    const qs = o.qs, L = qs.map(qlab), show = Object.keys(o.cust).slice(0, 8);
    const tot = qs.map((_, i) => show.reduce((a, c) => a + (o.cust[c][i] || 0), 0));
    const max = Math.max(...tot, 1);
    const COL = ['var(--accent)', 'var(--up)', '#f59e0b', '#10b981', '#8b5cf6', '#64748b', '#ec4899', '#94a3b8'];
    const bars = qs.map((q, i) => { let y = 100; return `<g>${show.map((c, k) => { const v = o.cust[c][i] || 0, h = v / max * 96; y -= h; return v ? `<rect x="${i * (100 / qs.length) + 0.6}" y="${y}" width="${100 / qs.length - 1.2}" height="${h}" fill="${COL[k]}"><title>${L[i]} ${c} ${n0(v)}억</title></rect>` : ''; }).join('')}</g>`; }).join('');
    return `<div class="card sm-dcard sm-wide"><h4>고객별 분기 수주 <span class="muted small">장비·부품·후공정·테스트 칸 국내 종목의 단일판매·공급계약(5년, 억원) — 고객 설비투자의 대리 지표 · 공시 의무가 매출의 10%(대기업 5%) 이상이라 '보이는 수주'만</span></h4>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" class="sm-obars">${bars}</svg>
      <div class="sm-blab">${L.map((l, i) => `<span style="width:${100 / L.length}%">${i % 2 === L.length % 2 ? l : ''}</span>`).join('')}</div>
      <div class="sm-legend">${show.map((c, k) => `<span><i style="background:${COL[k]}"></i>${esc(c)} <b>${n0(o.cust[c].slice(-4).reduce((a, v) => a + (v || 0), 0))}</b><small class="muted">억/최근 4분기</small></span>`).join('')}</div></div>`;
  }
  // 신규시설투자 공시 (최근 5년) — 삼성·하이닉스 증설의 공식 신호, 장비·소재사 증설
  function facHtml() {
    const f = data.fac || [];
    if (!f.length) return '';
    const big = f.filter(x => ['005930', '000660', '000990'].includes(x.c));
    const rest = f.filter(x => !['005930', '000660', '000990'].includes(x.c)).slice(0, 12);
    const row = x => `<tr><td>${x.d.slice(2)}</td><td><a href="https://finance.naver.com/item/main.naver?code=${x.c}" data-code="${x.c}">${esc(x.n)}</a></td><td class="num">${x.amt == null ? '–' : x.amt >= 10000 ? (x.amt / 10000).toFixed(1) + '조' : n0(x.amt) + '억'}</td><td class="num">${x.pct == null ? '–' : x.pct + '%'}</td><td class="small">${esc((x.purpose || '').slice(0, 60))}</td><td class="small muted">${x.start ? x.start.slice(2) : ''}~${x.end ? x.end.slice(2) : ''}</td><td><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${x.r}" target="_blank" rel="noopener">↗</a></td></tr>`;
    return `<div class="card sm-dcard sm-wide"><h4>신규시설투자 공시 <span class="muted small">DART '신규시설투자등' — 금액·자기자본 대비·목적·기간</span></h4>
      <table class="tbl sm-mini sm-fac"><tr><th>날짜</th><th>회사</th><th class="num">금액</th><th class="num">자기자본 대비</th><th>목적</th><th>기간</th><th></th></tr>
        ${big.slice(0, 10).map(row).join('')}<tr class="sm-group"><td colspan="7">장비·소재·부품·기판사 (최근)</td></tr>${rest.map(row).join('')}</table></div>`;
  }
  // 칸별 시차 상관: 수요 지표(k 분기 앞)의 전년 대비 증가율과 그 칸 국내 매출 합계 증가율
  function lagHtml() {
    const cs = data.cells.filter(c => c.lag);
    if (!cs.length) return '';
    const D = ['빅테크 capex', '삼성+하이닉스 설비투자'];
    const cell = (r, best) => (r == null ? '<td class="num muted">–</td>' : `<td class="num${best ? ' sm-best' : ''}" style="background:${r > 0 ? `color-mix(in srgb, var(--up) ${Math.round(Math.abs(r) * 45)}%, var(--card))` : `color-mix(in srgb, var(--down) ${Math.round(Math.abs(r) * 45)}%, var(--card))`}">${r.toFixed(2)}</td>`);
    return `<div class="card sm-dcard sm-wide"><h4>어느 칸이 투자를 몇 분기 늦게 따라오나 <span class="muted small">상관계수 · 칸 매출 전년 대비 vs 지표 전년 대비(0~3분기 앞) · 비교 구간 전체에 매출이 있는 국내 종목만 합산 · 분기 수가 적어(7~11개) 참고용</span></h4>
      <div class="tbl-wrap"><table class="tbl sm-mini sm-lag"><thead><tr><th>칸</th><th class="num">종목</th>${D.map(d => `<th colspan="4" class="num">${d} — 0·1·2·3분기 앞</th>`).join('')}</tr></thead>
      <tbody>${cs.map(c => `<tr><td>${esc(c.sn || c.name)}</td><td class="num">${c.lag.n_stocks}</td>${D.map(d => (c.lag[d]?.r || []).map((r, k) => cell(r, k === c.lag[d].best)).join('')).join('')}</tr>`).join('')}</tbody></table></div></div>`;
  }

  // ---------- 종목 표 ----------
  function spark(vals) {
    const v = vals.slice(-8), max = Math.max(...v.filter(x => x != null).map(Math.abs), 1), bw = 100 / v.length;
    return `<svg viewBox="0 0 100 24" preserveAspectRatio="none" class="sm-spark">${v.map((x, i) => x == null ? '' : `<rect x="${i * bw + 1}" y="${x >= 0 ? 24 - x / max * 23 : 24}" width="${bw - 2}" height="${Math.abs(x) / max * 23}" class="${i === v.length - 1 ? 'last' : ''}${x < 0 ? ' neg' : ''}"/>`).join('')}</svg>`;
  }
  const mcKey = s => (s.ov ? (s.mc_usd || 0) * (data.usdkrw || 1400) / 1e8 : s.mc || 0);
  function renderFilters() {
    const nOv = data.stocks.filter(s => s.ov).length;
    $('filters').innerHTML = `<div class="frow">
      ${pg.seg('ov', [['all', `전체 ${data.stocks.length}`], ['kr', `국내 ${data.stocks.length - nOv}`], ['ov', `해외 ${nOv}`]])}
      ${pg.seg('sort', [['mc', '시총 순'], ['yoy', '매출 YoY'], ['opm', 'OPM'], ['dopm', 'OPM 변화']])}
      <select data-sel="cell" aria-label="칸"><option value="">모든 칸</option>${data.stages.map(sg => `<optgroup label="${esc(sg.name)}">${data.cells.filter(c => c.stage === sg.id).map(c => `<option value="${c.id}"${st.cell === c.id ? ' selected' : ''}>${esc(c.name)} (${c.n})</option>`).join('')}</optgroup>`).join('')}</select>
      <input type="search" data-q="q" placeholder="종목명·코드·티커" value="${esc(st.q)}" autocomplete="off">
      <span class="muted small">${U.timeLabel(data.built)} 갱신</span></div>`;
  }
  function row(s) {
    const unit = s.ov ? (s.cur || '') : '억';
    const name = s.ov ? `<a href="https://finance.yahoo.com/quote/${encodeURIComponent(s.tk)}" target="_blank" rel="noopener">${esc(s.n)}</a> <small class="muted">${esc(s.tk)}</small>`
      : `${Stock.link(s)} <small class="muted">${s.c}</small>`;
    const rv = s.lq ? s.q.rev[data.qs.indexOf(s.lq)] : null, op = s.lq ? s.q.op[data.qs.indexOf(s.lq)] : null;
    const k = (s.con || []).filter(x => !x.x)[0];
    return `<tr class="sm-row${open.has(s.c || s.tk) ? ' on' : ''}" data-k="${esc(s.c || s.tk)}" ${s.ov ? '' : Stock.hintAttr(s)}>
      <td class="name-cell"><b>${name}</b>${s.ov ? '<span class="tag">해외</span>' : ''}${(s.ix || []).map(x => `<span class="tag">${x}</span>`).join('')}<small class="muted sm-prod">${esc(s.p_ || '')}${s.conf != null && s.conf < 0.6 ? ' <span title="칸 배정 확신 낮음 — 검수 필요">?</span>' : ''}${s.chk ? ' <span title="티커·노출 재확인 필요">?</span>' : ''}</small>${s.ai ? `<small class="sm-ai-l">${esc(s.ai)}</small>` : ''}</td>
      <td class="num">${s.ov ? usdB(s.mc_usd) : s.mc != null ? U.eok(s.mc) : '–'}</td>
      <td class="num">${qlab(s.lq)}${s.lq && s.lq < data.last ? ' <small class="muted" title="회계연도가 달라 아직 이 분기 실적이 안 나옴">·직전</small>' : ''}</td>
      <td class="num">${n0(rv)} <small class="muted">${unit}</small></td><td class="num">${pc(s.yoy)}</td>
      <td class="num ${op < 0 ? 'down' : ''}">${n0(op)}</td><td class="num">${s.opm == null ? '–' : s.opm.toFixed(1) + '%'}</td><td class="num">${pp(s.dopm)}</td>
      <td>${spark(s.q.rev)}</td>
      <td>${s.eq ? `<span class="fd-chip ${CASE[s.eq.case]?.[1] || ''}" title="@darthacking 실적 글 기준 · 영익 ${s.eq.or == null ? '–' : (s.eq.or * 100).toFixed(0) + '%'} · 매출 ${s.eq.sr == null ? '–' : (s.eq.sr * 100).toFixed(0) + '%'}">${s.eq.q} ${CASE[s.eq.case]?.[0] || '–'}</span>` : ''}</td>
      <td class="small">${s.conn12 ? `<b>${s.conn12}건 ${n0(s.con12)}억</b><small class="muted">/1년</small><br>` : ''}${k ? `<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${k.r}" target="_blank" rel="noopener" title="${esc(k.name || '')} · 계약 끝 ${k.end || '–'}">${k.d.slice(2)} ${k.amt != null ? n0(k.amt) + '억' : ''}${k.pct != null ? ` (${k.pct}%)` : ''}</a> <span class="muted">${esc(k.cust && !['기타', '미상'].includes(k.cust) ? k.cust : (k.party || ''))}</span>` : ''}</td></tr>
      ${open.has(s.c || s.tk) ? detailHtml(s) : ''}`;
  }
  const open = new Set();      // 펼친 종목
  function detailHtml(s) {
    const cons = (s.con || []).filter(k => !k.x);
    const byY = {};
    cons.forEach(k => { const y = k.d.slice(0, 4); byY[y] = (byY[y] || 0) + (k.amt || 0); });
    const fac = (data.fac || []).filter(f => f.c === s.c);
    return `<tr class="sm-detail"><td colspan="11"><div class="sm-dgrid2">
      <div><h5>기술적 해자 <span class="muted small">사업보고서 원문 근거 · 마우스를 올리면 원문 구절</span></h5>
        ${(s.moat || []).length ? `<ul class="sm-moat">${s.moat.map(m => `<li title="원문: ${esc(m.q || '')}"><span class="tag">${esc(m.kind || '')}</span> ${esc(m.t)}${m.r ? ` <a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${m.r}" target="_blank" rel="noopener">↗</a>` : ''}</li>`).join('')}</ul>` : '<p class="muted small">원문에서 해자 근거 문장을 찾지 못했습니다.</p>'}
        ${s.why ? `<h5>칸 배정 근거</h5><p class="small">${esc(s.why)}${s.why_src ? ` <a href="${esc(s.why_src)}" target="_blank" rel="noopener">↗</a>` : ''}</p>` : ''}
        ${s.note ? `<p class="small muted">${esc(s.note)}</p>` : ''}
        ${fac.length ? `<h5>신규시설투자</h5><ul class="sm-moat">${fac.slice(0, 5).map(f => `<li>${f.d} ${f.amt >= 10000 ? (f.amt / 10000).toFixed(1) + '조' : n0(f.amt) + '억'} · ${esc((f.purpose || '').slice(0, 50))}</li>`).join('')}</ul>` : ''}</div>
      <div><h5>수주 이력 <span class="muted small">5년 ${cons.length}건 · 연도별 ${Object.entries(byY).sort().map(([y, v]) => `${y.slice(2)}년 ${n0(v)}억`).join(' · ') || '없음'}</span></h5>
        ${cons.length ? `<table class="tbl sm-mini"><tr><th>날짜</th><th class="num">금액(억)</th><th class="num">매출 대비</th><th>상대</th><th>계약</th><th>기간 끝</th></tr>${cons.slice(0, 15).map(k => `<tr><td><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${k.r}" target="_blank" rel="noopener">${k.d.slice(2)}</a></td><td class="num">${n0(k.amt)}</td><td class="num">${k.pct == null ? '–' : k.pct + '%'}</td><td class="small">${esc(k.party || '–')} <span class="tag">${esc(k.cust)}</span></td><td class="small">${esc(k.name || '')}</td><td class="small muted">${k.end || ''}</td></tr>`).join('')}</table>` : '<p class="muted small">공시된 수주가 없습니다(매출의 10% 미만이면 공시 의무 없음).</p>'}</div>
    </div></td></tr>`;
  }
  function renderTable() {
    const q = st.q.trim().toLowerCase();
    const ok = s => (st.ov === 'all' || (st.ov === 'ov') === !!s.ov) && (!st.cell || s.cell === st.cell || (s.also || []).includes(st.cell))
      && (!q || s.n.toLowerCase().includes(q) || (s.c || '').includes(q) || (s.tk || '').toLowerCase().includes(q));
    const key = st.sort;
    const sorter = (a, b) => (key === 'mc' ? mcKey(b) - mcKey(a) : (b[key] ?? -1e9) - (a[key] ?? -1e9));
    const cells = st.cell ? [cellOf(st.cell)] : data.cells;
    const body = cells.map(c => {
      const rows = data.stocks.filter(s => ok(s) && (s.cell === c.id || (st.cell && (s.also || []).includes(c.id)))).sort(sorter);
      if (!rows.length) return '';
      const sg = data.stages.find(x => x.id === c.stage);
      return `<tr class="sm-group"><td colspan="11"><b>${esc(c.name)}</b> <span class="muted small">${esc(sg.name)} · ${esc(c.driver)}</span>
        <span class="small sm-gstat">매출 YoY 중앙값 ${pc(c.yoy)} · OPM ${c.opm == null ? '–' : c.opm.toFixed(0) + '%'}</span></td></tr>${rows.map(row).join('')}`;
    }).join('');
    $('table').innerHTML = `<div class="col-head"><h3>칸별 종목 <span class="muted">${data.stocks.filter(ok).length}</span></h3>
        <span class="muted small">국내 = 펀더 손익(억원, 연결 우선) · 해외 = 회사 통화 백만 · 종목명 → 종목 설명 · 줄의 다른 곳 → 해자·수주 이력</span></div>
      <div class="tbl-wrap"><table class="tbl fd-list sm-list">
        <thead><tr><th>종목</th><th class="num">시총</th><th class="num">분기</th><th class="num">매출</th><th class="num">YoY</th><th class="num">영업이익</th><th class="num">OPM</th><th class="num" title="영업이익률의 전년 동기 대비 변화">OPM YoY</th><th>매출 8분기</th><th>실적 vs 예상</th><th>최근 수주</th></tr></thead>
        <tbody>${body || '<tr><td colspan="11" class="muted">해당 종목 없음</td></tr>'}</tbody></table></div>`;
  }

  $('ai').addEventListener('click', e => {
    const b = e.target.closest('[data-rack]');
    if (b) pg.set({ rack: b.dataset.rack });
  });
  $('table').addEventListener('click', e => {
    if (e.target.closest('a')) return;
    const tr = e.target.closest('tr.sm-row');
    if (!tr) return;
    const k = tr.dataset.k;
    open.has(k) ? open.delete(k) : open.add(k);
    renderTable();
  });
  $('chain').addEventListener('click', e => {
    if (e.target.closest('[data-clear]')) return pg.set({ cell: '' });
    const g = e.target.closest('[data-cell]');
    if (g) pg.set({ cell: st.cell === g.dataset.cell ? '' : g.dataset.cell });
  });
  pg.bind($('filters'));
  U.initTheme($('theme'));
  (async () => {
    try { data = await U.json('data/semi.json'); } catch (e) { $('msg').textContent = '반도체 데이터를 불러오지 못했습니다.'; return; }
    $('msg').hidden = true;
    renderFilters();
    renderAI();
    renderChain();
    renderDemand();
    renderTable();
    $('foot').innerHTML = `<p>국내: 금융감독원 DART 정기보고서 손익(펀더 탭과 같은 수집), 단일판매·공급계약 공시. 해외: 미국 SEC EDGAR 공시(XBRL), 그 밖은 야후 파이낸스 분기 재무. 칸 배정과 제품 설명은 초안(검수 전)입니다.</p>
      <p>실적 vs 예상은 @darthacking 실적 글의 예상치 기준입니다. 투자 판단의 참고용이며 정확성을 보장하지 않습니다.</p>`;
  })();
})();
