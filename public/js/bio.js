// 바이오 탭: data/bio.json — 종목별 시세·가치(rNPV·옵션·DCF)·임상 일정·뉴스
(() => {
  const $ = id => document.getElementById(id);
  const esc = U.esc;
  const pg = U.page({ c: '' }, () => render());
  const st = pg.state;
  let data = null;

  const usd = v => v == null ? '–' : `${v < 0 ? '-' : ''}$${Math.abs(v) >= 1000 ? (Math.abs(v) / 1000).toFixed(2) + 'B' : Math.abs(v).toFixed(0) + 'M'}`;
  const px = v => v == null ? '–' : `$${v.toFixed(2)}`;
  const pc = (v, nd = 0) => v == null ? '–' : `${v > 0 ? '+' : ''}${(v * 100).toFixed(nd)}%`;
  const pc100 = (v, nd = 2) => v == null ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(nd)}%`;
  const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
  const days = ds => Math.round((new Date(ds + 'T00:00:00') - today()) / 86400000);
  const dday = ds => { const n = days(ds); return n === 0 ? 'D-day' : n > 0 ? `D-${n}` : `D+${-n}`; };
  const KIND = { pipeline: '임상 자산 가치', 'commercial+pipeline': '상업 DCF + 임상', excluded: '비바이오' };

  function nextCat(c) {
    return (c.catalysts || []).filter(x => days(x.date) >= 0).sort((a, b) => a.date.localeCompare(b.date))[0];
  }

  const KIND_KO = { regulatory: '허가·규제', readout: '임상 결과', milestone: '개발 단계', earnings: '실적' };
  const todayIso = () => { const d = today(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  const newTag = x => x && x.new ? ' <span class="bio-tag go">새로</span>' : '';

  function previewHtml(c) {
    const p = c.earnings_preview;
    if (!p) return '';
    const e = p.est, q2 = p.q2, cs = p.consensus || {};
    const row = (l, a, b, note = '') => `<tr><td>${l}${note ? `<small>${note}</small>` : ''}</td><td class="num">${a}</td><td class="num">${b}</td></tr>`;
    const m = v => usd(v);
    const eps = v => v == null ? '–' : `$${v.toFixed(2)}`;
    const be = (v, l) => v == null ? `${l}: 범위 밖` : `${l} <b>${usd(v)}</b> (연환산 ${usd(v * 4)})`;
    const q2op = q2.product_sales + q2.service_rev - q2.cogs_product - q2.cogs_service - q2.rnd - q2.sga;
    return `<div class="bio-sub">${esc(p.quarter)} 실적 분해 · 발표 ${p.report_date} ${days(p.report_date) >= 0 ? dday(p.report_date) : '(발표됨, 원문 대조 필요)'}</div>
      <div class="bio-grid"><div class="tbl-wrap"><table class="tbl"><thead><tr><th>항목 (백만 달러)</th><th class="num">2분기 실제</th><th class="num">3분기 추정</th></tr></thead><tbody>
        ${row('YUTREPIA 순매출', m(q2.product_sales), `<b>${m(e.product_sales)}</b>`, '3분기는 회사 잠정치 (원문 확인)')}
        ${row('서비스 매출', m(q2.service_rev), m(e.service_rev), 'Sandoz 판촉 계약 10월 종료 가정')}
        ${row('제품 원가', m(-q2.cogs_product), m(-e.cogs_product), '2분기 원가율 유지 가정')}
        ${row('R&D', m(-q2.rnd), m(-e.rnd), 'L606 pivotal 진행으로 +10% 가정')}
        ${row('판관비', m(-q2.sga), m(-e.sga), '+8% 가정')}
        ${row('영업이익', m(q2op), `<b>${m(e.op_income)}</b>`)}
        ${row('순이익', m(q2.net_income), m(e.net_income), `유효세율 ${(e.tax_rate * 100).toFixed(1)}% (2분기와 같게)`)}
        ${row('희석 EPS', eps(q2.eps_diluted), `<b>${eps(e.eps_diluted)}</b>`, `희석 주식 ${q2.shares_diluted.toFixed(1)}M`)}
      </tbody></table><p class="bio-pad muted small">2분기 실제: <a href="${esc(q2.url)}" target="_blank" rel="noopener">${esc(q2.src)}</a> · 3분기 잠정: <a href="${esc(p.known.url)}" target="_blank" rel="noopener">${esc(p.known.src)}</a></p></div><div class="bio-pad">
        <p><b>컨센서스</b> (yfinance, 원문 아님) 매출 ${m(cs.rev_avg)} (범위 ${m(cs.rev_low)}~${m(cs.rev_high)}), EPS ${eps(cs.eps_avg)} (범위 ${eps(cs.eps_low)}~${eps(cs.eps_high)}).
          회사 잠정 매출 ${m(p.known.product_sales)}는 컨센서스 평균 대비 ${cs.rev_avg ? pc(p.known.product_sales / cs.rev_avg - 1) : '–'}.</p>
        <p class="muted">주의: UTHR 합의(10월 체결)가 3분기 손익에 비용으로 잡히면 GAAP EPS가 위 추정과 크게 달라집니다. 발표 원문의 합의 회계 처리를 먼저 보세요.</p>
        <p><b>분기 순매출이 얼마면 현재가 ${px(p.price)}가 정당화되나</b><br>
          ${be(p.breakeven_base, '기본 성장 경로')}<br>${be(p.breakeven_bull, `낙관 성장 경로 (성장률 ×${p.bull_growth_mult})`)}<br>
          <span class="muted">3분기 잠정 ${m(p.known.product_sales)}는 기본 경로 기준점의 ${p.breakeven_base ? ((p.known.product_sales / p.breakeven_base) * 100).toFixed(0) + '%' : '–'}, 낙관 경로 기준점의 ${p.breakeven_bull ? ((p.known.product_sales / p.breakeven_bull) * 100).toFixed(0) + '%' : '–'}입니다. 다음 분기 매출이 낙관 기준점에 다가가면 낙관 시나리오로 옮길 근거가 됩니다.</span></p>
      </div></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>분기 순매출</th>${p.grid.map(r => `<th class="num">${usd(r.q)}</th>`).join('')}</tr></thead><tbody>
        <tr><td>주당 가치 (기본 성장)</td>${p.grid.map(r => `<td class="num ${r.base >= p.price ? 'up' : ''}">${px(r.base)}</td>`).join('')}</tr>
        <tr><td>주당 가치 (낙관 성장)</td>${p.grid.map(r => `<td class="num ${r.bull >= p.price ? 'up' : ''}">${px(r.bull)}</td>`).join('')}</tr>
      </tbody></table></div><p class="bio-pad muted small">색이 바뀐 칸부터 현재가 이상. 분기 매출 × 4를 시작 매출로 놓고, 마진·성장률·주식 수·합의금 같은 나머지 가정은 그대로 둔 계산입니다.</p>`;
  }

  function autoHtml(c) {
    const a = c.auto;
    if (!a) return '';
    const t = todayIso();
    const ev = a.events || [];
    const earn = a.earnings && a.earnings.date >= t ? a.earnings : null;
    const fl = a.filings || [];
    const tc = a.trial_changes || [];
    return `<div class="bio-sub">자동 수집 <span class="muted small">검토 필요 · 가치 계산에는 넣지 않음</span></div>
      ${a.archive_ok ? '' : '<div class="bio-warn">공시 원문에서 날짜를 뽑는 기능이 꺼져 있습니다. SEC는 원문 접근에 이름·이메일이 담긴 User-Agent를 요구해서, .env에 SEC_USER_AGENT를 넣어야 켜집니다. 지금은 공시 목록, 실적 발표일, 임상 시험 변경만 자동입니다.</div>'}
      <ul class="bio-list">
        ${earn ? `<li><span class="d">${earn.date}</span><span class="bio-tag">실적</span> 다음 실적 발표 ${dday(earn.date)} · 컨센서스 매출 ${usd(earn.rev_avg)}, EPS ${earn.eps_avg != null ? '$' + earn.eps_avg.toFixed(2) : '–'} <span class="muted">${esc(earn.src)}</span></li>` : ''}
        ${ev.map(e => `<li><span class="d">${e.date}</span><span class="bio-tag">${KIND_KO[e.kind] || e.kind}</span>${newTag(e)} <b>${esc(e.date_text)}</b> · ${esc(e.sentence)} <a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.src)}</a></li>`).join('')}
        ${tc.map(x => `<li><span class="bio-tag">임상</span> <a href="https://clinicaltrials.gov/study/${x.id}" target="_blank" rel="noopener">${x.id}</a> ${esc(x.change)} ${x.before || ''} → ${x.after || ''} <span class="muted">${esc(x.title.slice(0, 60))}</span></li>`).join('')}
        ${!earn && !ev.length && !tc.length ? '<li class="muted">새로 찾은 일정 없음</li>' : ''}
      </ul>
      <div class="bio-sub">최근 60일 SEC 공시</div><ul class="bio-list">
        ${fl.length ? fl.map(f => `<li><span class="d">${f.filed}</span><b>${f.form}</b>${newTag(f)} ${esc(f.labels.join(' · '))} <a href="${esc(f.url)}" target="_blank" rel="noopener">원문</a></li>`).join('') : '<li class="muted">없음</li>'}</ul>`;
  }

  function renderScreen() {
    const s = data.market_screen;
    if (!s) { $('screen').innerHTML = ''; return; }
    $('screen').innerHTML = `<div class="col-head"><h3>시장 스크리닝 <span class="muted">최근 14일 8-K·6-K 중 PDUFA·탑라인 언급</span></h3>
        <span class="muted small">EDGAR 전문 검색 · ${data.archive_ok ? '원문에서 뽑은 날짜' : '날짜는 원문을 열어야 확인 (SEC_USER_AGENT 필요)'}</span></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>회사</th><th>공시일</th><th>종류</th><th>찾은 날짜</th><th>문장</th></tr></thead><tbody>
      ${s.slice(0, 40).map(e => `<tr><td><b>${esc(e.ticker || '')}</b><small>${esc(e.company)}</small></td><td>${esc(e.filed || '')}</td><td>${KIND_KO[e.kind] || e.kind}</td>
        <td>${e.date ? `${e.date}<small>${esc(e.date_text)}</small>` : '<span class="muted">–</span>'}</td>
        <td style="white-space:normal">${e.sentence ? esc(e.sentence.slice(0, 160)) + ' ' : ''}<a href="${esc(e.url)}" target="_blank" rel="noopener">원문</a></td></tr>`).join('')}
      </tbody></table></div>`;
  }

  function renderCards() {
    const chip = (v, l) => v == null ? '' : `<span class="bc-chip ${U.cls(v)}">${l} ${pc(v)}</span>`;
    $('cards').innerHTML = data.companies.map(c => {
      const m = c.market, k = c.card || {}, n = k.next;
      const rw = [k.commercial ? '상업화 중' : '', k.cf_positive ? '영업현금 흑자' : k.runway ? `현금 약 ${Math.round(k.runway.months)}개월` : ''].filter(Boolean).join(' · ');
      return `<button class="bc${c.ticker === st.c ? ' on' : ''}" data-c="${c.ticker}" type="button">
        <div class="bc-top"><b>${esc(c.ticker)}</b>${k.earnings_today ? '<span class="bc-badge">실적 오늘</span>' : ''}</div>
        <div class="bc-px">${px(m.price)} <small class="${U.cls(m.change_pct)}">${pc100(m.change_pct)}</small></div>
        <div class="bc-next">${n ? `<span class="bc-d">${dday(n.date)}</span> ${esc(n.text)}${n.auto ? ' <i>자동</i>' : ''}` : '<span class="muted">예정 일정 없음</span>'}</div>
        <div class="bc-meta" title="${k.runway ? esc('현금 ÷ 월 소진 추정. 근거: ' + k.runway.basis) : ''}">${esc(rw)}${k.runway ? ' (추정)' : ''}</div>
        <div class="bc-chips">${chip(k.base_up, '기본')}${chip(k.top_up, k.top_label || '낙관')}</div>
      </button>`;
    }).join('');
  }

  const RANGES = [['1M', 'd', 21], ['6M', 'd', 126], ['1Y', 'd', 260], ['5Y', 'w', 270]];
  let range = '1Y';

  function priceSvg(c) {
    const p = c.prices;
    if (!p) return '<p class="muted small">주가 이력을 불러오지 못했습니다.</p>';
    const [, key, n] = RANGES.find(r => r[0] === range);
    const pts = p[key].slice(-n);
    if (pts.length < 2) return '';
    const W = 560, H = 180, padL = 44, padR = 8, padT = 10, padB = 22;
    const vs = pts.map(x => x[1]);
    let lo = Math.min(...vs), hi = Math.max(...vs);
    const span = hi - lo || 1; lo -= span * 0.05; hi += span * 0.05;
    const X = i => padL + (i / (pts.length - 1)) * (W - padL - padR);
    const Y = v => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);
    const line = pts.map((x, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(x[1]).toFixed(1)}`).join('');
    const area = `${line}L${X(pts.length - 1).toFixed(1)},${H - padB}L${padL},${H - padB}Z`;
    const ticks = [0, 0.5, 1].map(f => lo + (hi - lo) * f);
    const chg = vs[vs.length - 1] / vs[0] - 1;
    const color = chg >= 0 ? 'var(--up)' : 'var(--down)';
    const xl = [0, Math.floor((pts.length - 1) / 2), pts.length - 1];
    return `<div class="bio-px-head"><span><b>${px(vs[vs.length - 1])}</b> <span class="${U.cls(chg)}">${pc(chg, 1)}</span> <span class="muted small">${pts[0][0]} ~ ${pts[pts.length - 1][0]}</span></span>
        <span class="seg" role="group">${RANGES.map(r => `<button type="button" data-range="${r[0]}" class="${r[0] === range ? 'on' : ''}">${r[0]}</button>`).join('')}</span></div>
      <svg class="bio-px" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(c.ticker)} 주가 ${range}">
        ${ticks.map(t => `<line x1="${padL}" x2="${W - padR}" y1="${Y(t)}" y2="${Y(t)}" class="g"/><text x="${padL - 6}" y="${Y(t) + 4}" text-anchor="end">${t.toFixed(t < 10 ? 2 : 0)}</text>`).join('')}
        <path d="${area}" fill="${color}" opacity="0.10"/><path d="${line}" fill="none" stroke="${color}" stroke-width="1.8"/>
        <circle cx="${X(pts.length - 1)}" cy="${Y(vs[vs.length - 1])}" r="3" fill="${color}"/>
        ${xl.map(i => `<text x="${X(i)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === pts.length - 1 ? 'end' : 'middle'}">${pts[i][0].slice(2)}</text>`).join('')}
      </svg><p class="muted small">yfinance 종가 (원문 아님)</p>`;
  }

  function finHtml(c) {
    const f = c.fin;
    if (!f) return '';
    const b = f.balance, qs = f.quarters || [];
    const ck = c.checks || [];
    const has = k => qs.some(q => q[k] != null);
    const rows = [['revenue', '매출'], ['rnd', 'R&D'], ['sga', '판관비'], ['op_income', '영업이익'], ['net_income', '순이익'], ['opcf', '영업현금흐름']].filter(([k]) => has(k));
    const maxRev = Math.max(1, ...qs.map(q => Math.abs(q.revenue || 0)));
    const cell = v => v == null ? '<td class="num muted">–</td>' : `<td class="num ${v < 0 ? 'down' : ''}">${usd(v)}</td>`;
    return `<div class="bio-sub">재무 <span class="muted small">SEC XBRL 공시 원문 수치 · 마지막 제출 ${esc(f.last_filed || '')} · <a href="${esc(f.filings_url)}" target="_blank" rel="noopener">EDGAR 공시 목록</a></span></div>
      <div class="bio-grid"><div class="bio-pad" id="pxbox">${priceSvg(c)}</div>
      <div><table class="tbl"><tbody>
        <tr><td>현금·단기투자 <small>${esc(b.end || '')} 기준${b.sti != null ? ` (현금 ${usd(b.cash)} + 단기투자 ${usd(b.sti)})` : ''}</small></td><td class="num"><b>${usd(b.cash_total)}</b></td></tr>
        <tr><td>차입금 <small>장기차입 유동+비유동 항목만 (리스·매출연동 차입은 회사마다 달라 빠질 수 있음)</small></td><td class="num">${b.debt != null ? usd(b.debt) : '<span class="muted">항목 없음</span>'}</td></tr>
        <tr><td>발행주식 <small>${f.shares ? `표지 기준 ${esc(f.shares.date)} (${esc(f.shares.form)})` : ''}</small></td><td class="num">${f.shares ? f.shares.value.toFixed(1) + 'M' : '–'}</td></tr>
        <tr><td>분기 영업현금 유출 <small>최근 2분기 평균</small></td><td class="num">${f.burn_quarter != null ? usd(-f.burn_quarter) : '<span class="up">유입(흑자)</span>'}</td></tr>
        <tr><td>현금 버티는 기간 <small>현금·단기투자 ÷ 분기 유출 × 3</small></td><td class="num"><b>${f.runway_months != null ? Math.round(f.runway_months) + '개월' : '–'}</b></td></tr>
      </tbody></table>
      ${ck.length ? `<div class="bio-sub">가치 계산 값 대 SEC 원문 <span class="muted small">1% 넘게 다르면 표시</span></div><table class="tbl"><thead><tr><th>항목</th><th class="num">가치 계산</th><th class="num">SEC</th><th class="num">차이</th></tr></thead><tbody>
        ${ck.map(x => `<tr><td>${esc(x.item)}<small>${esc(x.note || '')}</small></td><td class="num">${x.item.includes('주식') ? (x.used != null ? x.used.toFixed(1) + 'M' : '–') : usd(x.used)}</td>
          <td class="num">${x.sec == null ? '<span class="muted">없음</span>' : (x.item.includes('주식') ? x.sec.toFixed(1) + 'M' : usd(x.sec))}<small>${esc(x.sec_date || '')}</small></td>
          <td class="num">${x.diff == null ? '–' : Math.abs(x.diff) > 0.01 ? `<span class="bio-tag stop">${pc(x.diff, 1)}</span>` : '<span class="bio-tag">일치</span>'}</td></tr>`).join('')}
      </tbody></table>` : ''}</div></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>분기 (백만 달러)</th>${qs.map(q => `<th class="num">${esc(q.label)}</th>`).join('')}</tr></thead><tbody>
        ${has('revenue') ? `<tr><td></td>${qs.map(q => `<td class="num"><span class="bio-bar" style="height:${Math.round(Math.abs(q.revenue || 0) / maxRev * 34)}px"></span></td>`).join('')}</tr>` : ''}
        ${rows.map(([k, l]) => `<tr><td>${l}</td>${qs.map(q => cell(q[k])).join('')}</tr>`).join('')}
      </tbody></table></div>
      <p class="bio-pad muted small">분기 값이 공시에 없으면 같은 회계연도 누적 값의 차이로 계산 (예: 6개월 누적 − 3개월). 회계연도가 달라도 달력 분기로 표시. 사용한 XBRL 항목: ${esc(Object.entries(f.concepts).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join(', '))}</p>`;
  }

  function renderOverview() {
    const row = c => {
      const m = c.market, v = c.valuation, p = c.payoffs, n = nextCat(c), cap = m.mcap_used || m.mcap;
      const pipe = v && v.assets.length > 0;
      const up = x => x == null ? '–' : `<span class="${U.cls(x / m.price - 1)}">${pc(x / m.price - 1)}</span>`;
      const top = p ? (pipe ? p.bull_success : c.scenarios.bull.per_share) : null;
      return `<tr data-c="${c.ticker}" class="${c.ticker === st.c ? 'on' : ''}">
        <td><b>${esc(c.ticker)}</b><small>${esc(c.name)}</small></td>
        <td class="num">${px(m.price)}<small class="${U.cls(m.change_pct)}">${pc100(m.change_pct)}</small></td>
        <td class="num" title="${m.mcap_used ? '주당 가치와 같은 주식 수(희석 기준)로 계산' : 'yfinance 시총'}">${usd(cap)}</td>
        <td class="num">${pipe ? px(p.fail) : '–'}</td>
        <td class="num"><b>${v ? px(v.per_share) : '–'}</b><small>${v ? up(v.per_share) : ''}</small></td>
        <td class="num">${pipe ? px(p.success) : '–'}<small>${pipe ? up(p.success) : ''}</small></td>
        <td class="num">${top != null ? px(top) : '–'}<small>${top != null ? up(top) : ''}</small></td>
        <td class="num">${p && p.required_revenue != null ? usd(p.required_revenue) : '–'}<small>가정 ${p ? usd(p.modeled_revenue) : '–'}</small></td>
        <td>${n ? `${esc(n.text)}<small>${n.date} · ${dday(n.date)}</small>` : '<span class="muted">–</span>'}</td></tr>`;
    };
    $('overview').innerHTML = `<div class="col-head"><h3>${data.companies.length}종목 한눈에 <span class="muted">기준 시세 ${esc(data.companies[0].market.asof)}</span></h3>
        <span class="muted small">주당 가치는 가정치로 계산한 참고값 · 무위험이자율 ${(data.rf * 100).toFixed(2)}%${data.rf_stale ? ' (대체값)' : ''}</span></div>
      <div class="tbl-wrap"><table class="tbl bio-ov"><thead><tr><th>종목</th><th class="num">주가</th><th class="num">시총</th>
        <th class="num" title="임상 자산 가치 0, 첫 발표 때까지만 현금을 쓰고 멈춘다고 봄">실패 시</th>
        <th class="num" title="단계별 PoS를 반영한 확률가중 값 (rNPV)">기본 (확률가중)</th>
        <th class="num" title="모든 단계가 성공하는 경우, 피크매출은 가정치 그대로">성공 시</th>
        <th class="num" title="성공 + 피크매출·성장 ×1.4~1.3">낙관 성공</th>
        <th class="num" title="현재 주가를 설명하려면 필요한 매출 규모(피크매출 합 + 연환산 매출), 작은 글씨는 이 모델이 가정한 값">필요 매출</th><th>다음 일정</th></tr></thead>
        <tbody>${data.companies.map(row).join('')}</tbody></table></div>
      <p class="bio-pad muted small">작은 글씨는 현재 주가 대비 %. 임상 자산이 없는 종목(LQDA)은 성공·실패가 없어 낙관 시나리오만 보여줍니다. 필요 매출이 가정 매출보다 크면 시장이 내 가정보다 큰 시장을 가격에 넣고 있다는 뜻입니다.</p>`;
  }

  function ladderHtml(c) {
    const p = c.payoffs, v = c.valuation, price = c.market.price;
    if (!p) return '';
    const pipe = v.assets.length > 0;
    const pts = pipe
      ? [['실패', p.fail], ['기본', p.base], ['성공', p.success], ['낙관 성공', p.bull_success]]
      : [['보수', c.scenarios.bear.per_share], ['기본', c.scenarios.base.per_share], ['낙관', c.scenarios.bull.per_share]];
    const max = Math.max(price, ...pts.map(x => x[1])) * 1.1;
    const pos = x => `${Math.max(1, Math.min(99, x / max * 100)).toFixed(1)}%`;
    const marks = pts.map(([l, x], i) => `<div class="lad-m ${i % 2 ? 'lo' : 'hi'}" style="left:${pos(x)}"><span>${l}<b>${px(x)}</b><i class="${U.cls(x / price - 1)}">${pc(x / price - 1)}</i></span></div>`).join('');
    const verdict = p.implied_scale != null
      ? `현재가 ${px(price)}를 설명하려면 매출 규모(피크매출 합·연환산 매출)가 <b>${usd(p.required_revenue)}</b>여야 합니다. 이 모델의 가정은 ${usd(p.modeled_revenue)}입니다.`
      : '현재가가 모델이 닿는 범위 밖입니다.';
    const prob = pipe && p.implied_p != null
      ? (p.implied_p <= 1 ? ` 가정한 성공 가치 기준으로 시장은 성공 확률을 <b>${(p.implied_p * 100).toFixed(0)}%</b>로 보고 있습니다.`
        : ' 현재가가 가정한 성공 가치보다 높아, 가정한 시장 규모로는 성공해도 현재가가 정당화되지 않습니다.') : '';
    return `<div class="bio-sub">업사이드 사다리 <span class="muted small">현재가 대비 %는 각 점 옆에 표시</span></div>
      <div class="bio-pad"><div class="ladder" role="img" aria-label="실패, 기본, 성공, 낙관 성공 가치와 현재가 비교">
        <div class="lad-line"></div>${marks}
        <div class="lad-px" style="left:${pos(price)}"><span>현재가 ${px(price)}</span></div></div>
        <p>${verdict}${prob}</p></div>`;
  }

  function bridgeHtml(c) {
    const v = c.valuation, b = v.bridge;
    const line = (l, val, note = '') => `<tr><td>${l}${note ? `<small>${note}</small>` : ''}</td><td class="num ${val < 0 ? 'down' : ''}">${usd(val)}</td></tr>`;
    const on = c.override_notes || {};
    return `<table class="tbl"><tbody>
      ${b.assets ? line('임상 자산 가치 (rNPV/옵션)', b.assets) : ''}
      ${v.commercial ? line('상업 제품 DCF (영구가치 제외)', b.commercial) : ''}
      ${line('현금', b.cash, esc(on.cash_note || 'yfinance 값 (원문 미확인)'))}
      ${line('부채', -b.debt, esc(on.debt_note || 'yfinance 값 (원문 미확인)'))}
      ${b.other ? line('기타 부채', -b.other, esc(on.other_liab_note || '')) : ''}
      ${b.burn ? line('출시까지 현금 소진(추정)', -b.burn, esc(on.burn_note || '최근 12개월 영업현금흐름 × 출시까지 햇수(yfinance, 원문 미확인)') + ' × 출시까지 햇수') : ''}
      <tr><td><b>주주가치</b></td><td class="num"><b>${usd(v.equity)}</b></td></tr>
      <tr><td>주당 (주식 수 ${(c.market.shares).toFixed(1)}M)<small>${esc(on.shares_note || 'yfinance 값 (원문 미확인)')}</small></td><td class="num"><b>${px(v.per_share)}</b> <span class="${U.cls(v.upside)}">${pc(v.upside)}</span></td></tr></tbody></table>`;
  }

  function assetsHtml(c) {
    const v = c.valuation;
    if (!v.assets.length) return '';
    return `<div class="bio-sub">임상 자산 (방법: PoS는 노드에, V는 WACC로 한 번, 트리 안 할인은 Rf)</div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>자산</th><th class="num">출시 가치 V0</th><th class="num">rNPV</th><th class="num">옵션(ROV)</th><th class="num">진행 강제</th></tr></thead><tbody>
      ${v.assets.map(a => `<tr><td><b>${esc(a.name)}</b><small>${esc(a.indication)} · ${esc(a.stage)} · 피크매출 가정 ${usd(a.peak)}</small>${a.basis ? `<small>산출: ${esc(a.basis)}</small>` : ''}</td>
        <td class="num">${usd(a.v0)}</td><td class="num"><b>${usd(a.rnpv)}</b></td><td class="num">${usd(a.rov)}</td><td class="num">${usd(a.forced)}</td></tr>
        ${a.steps.map(s => `<tr><td colspan="5" class="muted small" style="padding-left:34px">${esc(s.name)} · PoS ${(s.pos * 100).toFixed(0)}% · 다음 단계 비용 ${usd(s.x)} ·
          <span class="bio-tag ${s.go ? 'go' : 'stop'}">${s.go ? '진행' : '포기'}</span>
          ${s.x > 0 && s.margin != null ? ` 계속가치가 비용의 ${s.margin.toFixed(1)}배 (1배 미만이면 포기)` : ''}</td></tr>`).join('')}
        ${a.assumptions ? `<tr><td colspan="5" class="muted small" style="padding-left:34px">가정: ${esc(a.assumptions)}</td></tr>` : ''}`).join('')}
      </tbody></table></div>`;
  }

  function commHtml(c) {
    const m = c.valuation.commercial;
    if (!m) return '';
    return `<div class="bio-sub">상업 제품 DCF · ${esc(m.name)}</div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>연차</th>${m.rows.map(r => `<th class="num">${r.y}년</th>`).join('')}</tr></thead><tbody>
        <tr><td>매출</td>${m.rows.map(r => `<td class="num">${usd(r.rev)}</td>`).join('')}</tr>
        <tr><td>영업이익률</td>${m.rows.map(r => `<td class="num">${(r.margin * 100).toFixed(0)}%</td>`).join('')}</tr>
        <tr><td>세후 FCF</td>${m.rows.map(r => `<td class="num">${usd(r.fcf)}</td>`).join('')}</tr></tbody></table></div>
      <p class="bio-pad muted small">시작 매출 ${usd(m.run_rate)} = ${esc(m.run_rate_note)}. ${esc(m.assumptions)}</p>`;
  }

  function trialsHtml(c) {
    if (!c.trials.length) return '';
    return `<div class="bio-sub">진행 중인 2·3상 시험 (ClinicalTrials.gov, 1차 완료 예정일 순)</div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>시험</th><th>적응증</th><th>약물</th><th>단계</th><th>상태</th><th>1차 완료 예정</th></tr></thead><tbody>
      ${c.trials.slice(0, 12).map(t => `<tr><td><a href="https://clinicaltrials.gov/study/${t.id}" target="_blank" rel="noopener">${t.id}</a><small>${esc(t.title.slice(0, 70))}</small></td>
        <td>${esc(t.cond)}</td><td>${esc(t.drug)}</td><td>${t.phase}</td><td>${esc(t.status.replace(/_/g, ' ').toLowerCase())}</td><td>${t.done || '–'}</td></tr>`).join('')}
      </tbody></table></div>`;
  }

  function renderDetail() {
    const c = data.companies.find(x => x.ticker === st.c) || data.companies[0];
    st.c = c.ticker;
    const m = c.market;
    let h = `<div class="col-head"><h3>${esc(c.ticker)} · ${esc(c.name)} <span class="muted">${px(m.price)} · 시총 ${usd(m.mcap_used || m.mcap)}${m.mcap_used ? ' (주식 수 ' + m.shares.toFixed(1) + 'M 기준)' : ''}</span></h3>
      <span class="muted small">${c.stale.length ? '일부 값은 직전 수집 결과 (' + c.stale.join(', ') + ')' : '방금 갱신된 값'}</span></div>
      <div class="bio-pad"><p>${esc(c.summary)}</p></div>`;
    if (c.kind === 'excluded') {
      h += `<div class="bio-warn">바이오 기업이 아니라 임상 방법론(rNPV·옵션)을 적용하지 않습니다. 시세와 뉴스만 표시합니다. 상품(우라늄·희토류) 가격에 따라 가치가 달라지는 광업 기업이라 별도 모델(NAV)이 맞습니다.</div>`;
    } else {
      h += ladderHtml(c);
      h += finHtml(c);
      h += previewHtml(c);
      h += `<div class="bio-grid"><div>${bridgeHtml(c)}</div><div class="bio-pad">
        <p><b>시나리오</b> (보수: PoS ×0.8·피크 ×0.6·성장 ×0.6, 낙관: PoS ×1.1·피크 ×1.4·성장 ×1.3)</p>
        <p>${Object.values(c.scenarios).map(s => `${esc(s.label)} <b>${px(s.per_share)}</b> <span class="${U.cls(s.upside)}">${pc(s.upside)}</span>`).join(' · ')}</p>
        ${c.implied_pos_scale != null ? `<p><b>시장 내재 PoS</b> 시총을 설명하려면 모든 단계 PoS를 가정치의 ${(c.implied_pos_scale * 100).toFixed(0)}% 수준으로 곱해야 합니다 (100%보다 작으면 시장이 가정치보다 비관적, 크면 낙관적).</p>`
          : c.valuation.assets.length ? '<p><b>시장 내재 PoS</b> PoS를 최대로 올려도 시총에 닿지 않습니다. 이 모델이 반영하지 못한 가치가 있다는 뜻입니다.</p>' : ''}
        ${c.not_modeled ? `<p class="muted"><b>반영하지 않은 것</b> ${esc(c.not_modeled)}</p>` : ''}</div></div>`;
      h += assetsHtml(c) + commHtml(c);
    }
    h += trialsHtml(c);
    h += autoHtml(c);
    h += `<div class="bio-grid"><div><div class="bio-sub">확인한 사실 (원문 확인 여부 표시)</div><ul class="bio-list">
        ${c.facts.length ? c.facts.map(f => `<li><span class="d">${esc(f.date)}</span><span class="bio-tag ${f.verified ? 'go' : 'stop'}">${f.verified ? '원문 확인' : '원문 미확인'}</span> ${esc(f.text)} ${f.url ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.src || '출처')}</a>` : `<span class="muted">${esc(f.src || '')}</span>`}</li>`).join('') : '<li class="muted">없음</li>'}</ul></div>
      <div><div class="bio-sub">최근 뉴스</div><ul class="bio-list">
        ${c.news.length ? c.news.map(n => `<li><span class="d">${esc(n.date)}</span><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>${n.src ? ` <span class="muted">${esc(n.src)}</span>` : ''}</li>`).join('') : '<li class="muted">불러오지 못함</li>'}</ul></div></div>`;
    $('detail').innerHTML = h;
  }

  function renderCal() {
    const t0 = todayIso();
    const ev = data.companies.flatMap(c => [
      ...(c.catalysts || []).map(x => ({ ...x, t: c.ticker })),
      ...(c.auto && c.auto.earnings && c.auto.earnings.date >= t0 && !(c.catalysts || []).some(x => x.date === c.auto.earnings.date)
        ? [{ date: c.auto.earnings.date, text: '실적 발표 (자동: yfinance)', t: c.ticker, auto: true }] : []),
      ...((c.auto && c.auto.events) || []).map(x => ({ date: x.date, text: `${KIND_KO[x.kind] || x.kind}: ${x.date_text} (자동: ${x.src})`, t: c.ticker, auto: true, new: x.new })),
    ]).sort((a, b) => a.date.localeCompare(b.date));
    $('cal').innerHTML = `<div class="col-head"><h3>일정 <span class="muted">다가오는 순</span></h3><span class="muted small">날짜가 분기·반기 단위인 항목은 마지막 날로 적었습니다</span></div>
      <ul class="bio-list">${ev.map(e => `<li><span class="d">${e.date}</span><b>${esc(e.t)}</b> ${esc(e.text)} <span class="bio-tag">${days(e.date) >= 0 ? dday(e.date) : '지남'}</span>${e.auto ? ' <span class="bio-tag">자동·검토 필요</span>' : ''}${newTag(e)}</li>`).join('')}</ul>`;
  }

  function renderMethod() {
    $('method').innerHTML = `<div class="col-head"><h3>이 탭의 방법 <span class="muted">Notion 'Bio기업 Valuation 방법론' 기준</span></h3></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>상황</th><th>방법</th><th>이유</th></tr></thead><tbody>
        <tr><td>전임상 ~ 1상</td><td>실물옵션 (이항모형)</td><td>rNPV가 보통 음수(OTM), 포기옵션이 가치의 큰 부분</td></tr>
        <tr><td>2상</td><td>rNPV + 포기 임계값</td><td>성공률 편차가 가장 큼</td></tr>
        <tr><td>3상 / 허가 심사</td><td>rNPV (트리형)</td><td>누적 성공률이 높아 옵션과 차이가 작음</td></tr>
        <tr><td>상업화 제품</td><td>DCF, 확률가중 없음</td><td>침식률로 모델링, 영구가치(TV) 쓰지 않음</td></tr></tbody></table></div>
      <div class="bio-pad"><p>위험은 세 곳에 나눠 넣습니다. ① 시장위험: 출시 후 가치 V0를 오늘 가치로 만들 때 WACC(${(data.params.wacc * 100).toFixed(0)}%)로 한 번. ② 임상위험: 노드의 PoS(실제확률). ③ 트리 안 할인: 무위험이자율. 발표 노드 가치 = PoS × max(계속가치 − 다음 단계 비용, 0). 옵션 변동성 σ는 피크매출 추정치의 변동성으로 ${(data.params.sigma * 100).toFixed(0)}%를 씁니다.</p>
        <p class="muted">'진행 강제'는 단계마다 포기하지 않고 비용을 반드시 내는 단순 rNPV입니다. rNPV와 옵션 가치가 같게 나오면 깊은 ITM이라 변동성에 둔감하다는 뜻입니다.</p></div>`;
  }

  function renderFoot() {
    $('foot').innerHTML = `<p>${esc(data.note)}</p>
      <p>시세·재무: yfinance(지연·오류 가능). 임상 시험: ClinicalTrials.gov. 뉴스: 야후·구글 뉴스 RSS. 달러 단위, 시총·재무 수치는 최근 분기 기준이라 실적 발표 직후에는 한 분기 늦을 수 있습니다.</p>
      <p>피크매출·PoS·출시비용·마진은 모두 가정치이며 투자 권유가 아닙니다. 가치가 시총과 크게 다르면 먼저 '반영하지 않은 것'과 가정치를 의심하세요. 갱신: ${U.timeLabel(data.generated_at)}</p>`;
  }

  function render() {
    renderCards(); renderOverview(); renderDetail(); renderCal(); renderScreen(); renderMethod(); renderFoot();
  }

  $('detail').addEventListener('click', e => {
    const b = e.target.closest('[data-range]');
    if (!b) return;
    range = b.dataset.range;
    const c = data.companies.find(x => x.ticker === st.c);
    $('pxbox').innerHTML = priceSvg(c);
  });
  $('cards').addEventListener('click', e => {
    const r = e.target.closest('[data-c]');
    if (r) pg.set({ c: r.dataset.c });
  });
  $('overview').addEventListener('click', e => {
    const r = e.target.closest('[data-c]');
    if (r) pg.set({ c: r.dataset.c });
  });

  U.initTheme($('theme'));
  (async () => {
    try {
      data = await U.json('data/bio.json');
    } catch (e) {
      $('msg').textContent = `바이오 데이터를 불러오지 못했습니다. (${e.message})`;
      return;
    }
    $('msg').hidden = true;
    $('asof').textContent = `${U.timeLabel(data.generated_at)} 갱신`;
    render();
  })();
})();
