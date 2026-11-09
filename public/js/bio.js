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

  function renderOverview() {
    const row = c => {
      const m = c.market, v = c.valuation, n = nextCat(c), cap = m.mcap_used || m.mcap;
      const sc = c.scenarios;
      return `<tr data-c="${c.ticker}" class="${c.ticker === st.c ? 'on' : ''}">
        <td><b>${esc(c.ticker)}</b><small>${esc(c.name)}</small></td>
        <td class="num">${px(m.price)}<small class="${U.cls(m.change_pct)}">${pc100(m.change_pct)}</small></td>
        <td class="num" title="${m.mcap_used ? '주당 가치와 같은 주식 수(희석 기준)로 계산' : 'yfinance 시총'}">${usd(cap)}</td>
        <td>${KIND[c.kind]}</td>
        <td class="num">${v ? px(v.per_share) : '–'}</td>
        <td class="num ${v ? U.cls(v.upside) : ''}">${v ? pc(v.upside) : '–'}</td>
        <td class="num">${sc ? `${px(sc.bear.per_share)} ~ ${px(sc.bull.per_share)}` : '–'}</td>
        <td>${n ? `${esc(n.text)}<small>${n.date} · ${dday(n.date)}</small>` : '<span class="muted">–</span>'}</td></tr>`;
    };
    $('overview').innerHTML = `<div class="col-head"><h3>${data.companies.length}종목 한눈에 <span class="muted">기준 시세 ${esc(data.companies[0].market.asof)}</span></h3>
        <span class="muted small">가치는 가정치로 계산한 참고값 · 무위험이자율 ${(data.rf * 100).toFixed(2)}%${data.rf_stale ? ' (대체값)' : ''}</span></div>
      <div class="tbl-wrap"><table class="tbl bio-ov"><thead><tr><th>종목</th><th class="num">주가</th><th class="num">시총</th><th>방법</th>
        <th class="num">기본 가치/주</th><th class="num">대비</th><th class="num">보수 ~ 낙관</th><th>다음 일정</th></tr></thead>
        <tbody>${data.companies.map(row).join('')}</tbody></table></div>`;
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
      ${v.assets.map(a => `<tr><td><b>${esc(a.name)}</b><small>${esc(a.indication)} · ${esc(a.stage)} · 피크매출 가정 ${usd(a.peak)}</small></td>
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
      h += `<div class="bio-grid"><div>${bridgeHtml(c)}</div><div class="bio-pad">
        <p><b>시나리오</b> (보수: PoS ×0.8·피크 ×0.6·성장 ×0.6, 낙관: PoS ×1.1·피크 ×1.4·성장 ×1.3)</p>
        <p>${Object.values(c.scenarios).map(s => `${esc(s.label)} <b>${px(s.per_share)}</b> <span class="${U.cls(s.upside)}">${pc(s.upside)}</span>`).join(' · ')}</p>
        ${c.implied_pos_scale != null ? `<p><b>시장 내재 PoS</b> 시총을 설명하려면 모든 단계 PoS를 가정치의 ${(c.implied_pos_scale * 100).toFixed(0)}% 수준으로 곱해야 합니다 (100%보다 작으면 시장이 가정치보다 비관적, 크면 낙관적).</p>`
          : c.valuation.assets.length ? '<p><b>시장 내재 PoS</b> PoS를 최대로 올려도 시총에 닿지 않습니다. 이 모델이 반영하지 못한 가치가 있다는 뜻입니다.</p>' : ''}
        ${c.not_modeled ? `<p class="muted"><b>반영하지 않은 것</b> ${esc(c.not_modeled)}</p>` : ''}</div></div>`;
      h += assetsHtml(c) + commHtml(c);
    }
    h += trialsHtml(c);
    h += `<div class="bio-grid"><div><div class="bio-sub">확인한 사실 (원문 확인 여부 표시)</div><ul class="bio-list">
        ${c.facts.length ? c.facts.map(f => `<li><span class="d">${esc(f.date)}</span><span class="bio-tag ${f.verified ? 'go' : 'stop'}">${f.verified ? '원문 확인' : '원문 미확인'}</span> ${esc(f.text)} ${f.url ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.src || '출처')}</a>` : `<span class="muted">${esc(f.src || '')}</span>`}</li>`).join('') : '<li class="muted">없음</li>'}</ul></div>
      <div><div class="bio-sub">최근 뉴스</div><ul class="bio-list">
        ${c.news.length ? c.news.map(n => `<li><span class="d">${esc(n.date)}</span><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>${n.src ? ` <span class="muted">${esc(n.src)}</span>` : ''}</li>`).join('') : '<li class="muted">불러오지 못함</li>'}</ul></div></div>`;
    $('detail').innerHTML = h;
  }

  function renderCal() {
    const ev = data.companies.flatMap(c => (c.catalysts || []).map(x => ({ ...x, t: c.ticker }))).sort((a, b) => a.date.localeCompare(b.date));
    $('cal').innerHTML = `<div class="col-head"><h3>일정 <span class="muted">다가오는 순</span></h3><span class="muted small">날짜가 분기·반기 단위인 항목은 마지막 날로 적었습니다</span></div>
      <ul class="bio-list">${ev.map(e => `<li><span class="d">${e.date}</span><b>${esc(e.t)}</b> ${esc(e.text)} <span class="bio-tag">${days(e.date) >= 0 ? dday(e.date) : '지남'}</span></li>`).join('')}</ul>`;
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
    renderOverview(); renderDetail(); renderCal(); renderMethod(); renderFoot();
  }

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
