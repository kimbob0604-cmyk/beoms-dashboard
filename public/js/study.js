// Beom's Study: 리포트·책을 그림·표 단위 카드로 분해해 쌓는 공부 화면
// 데이터: data/study/index.json(트리·문서·색인) + data/study/docs/{doc}.json(카드)  ← build_study.py
// 주소(쿼리): ?n=노드경로[&c=문서:주제:카드]  ?e=색인키  ?d=문서id  ?q=검색어  (없으면 첫 화면)
// 해시(#종목코드)는 종목 상세 패널(stock.js)이 쓰므로 비워 둔다.
(() => {
  const $ = id => document.getElementById(id);
  const esc = U.esc;
  // 숫자 강조: 단위가 붙은 숫자만 (PD-(L)1 의 1, CTLA-4 의 4 같은 이름 속 숫자는 그대로)
  const UNIT = '(?:%p|%|억 달러|십억 달러|백만 달러|억|조|달러|개월|년|배|명|쪽|개)';
  const NUM_RE = new RegExp(`(?<![\\w\\-–()./&#])([+\\-−]?\\d[\\d,]*(?:\\.\\d+)?)(\\s?${UNIT})`, 'g');
  const num = s => esc(s).replace(NUM_RE, (m, n, u) => `<b class="n">${n}${u}</b>`);
  let IX = null;
  const CALC = {};   // 계산 카드 정의 (카드 id → 카드)

  // 계산 카드: 입력값으로 결과를 다시 계산하고, 식에 실제 숫자를 넣어 보여 준다
  const calcNum = (x, d) => Number.isFinite(x) ? x.toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d }) : '—';
  function calcRun(box) {
    const c = CALC[box.id.slice(2)];
    if (!c) return;
    const v = {};
    box.querySelectorAll('input[data-k]').forEach(i => { v[i.dataset.k] = parseFloat(i.value); });
    c.out.forEach((o, i) => {
      const ks = Object.keys(v);
      let r;
      try { r = Function(...ks, `return (${o.f});`)(...ks.map(k => v[k])); } catch (err) { r = NaN; }
      const show = (o.show || '').replace(/\{(\w+)\}/g, (m, k) => k in v ? calcNum(v[k], Number.isInteger(v[k]) ? 0 : (Math.abs(v[k]) < 10 ? 2 : 1)) : m);
      if (o.k) v[o.k] = r;
      box.querySelector(`.cc-f[data-i="${i}"]`).textContent = show;
      box.querySelector(`.cc-v[data-i="${i}"]`).textContent = `${calcNum(r, o.d ?? 1)}${o.unit ? ' ' + o.unit : ''}`;
    });
  }
  document.addEventListener('input', e => { const b = e.target.closest && e.target.closest('.sd-calc'); if (b) calcRun(b); });
  const DOCS = {};
  const KIND_LABEL = { c: '개념', d: '약물', co: '기업', tr: '임상', ind: '적응증', n: '국가' };

  // 공개 사이트에서는 데이터·그림이 암호로 잠겨 있다(data/study/lock.json, study_crypt.py).
  // 암호를 한 번 넣으면 열쇠를 이 기기(localStorage)에 기억하고, 파일은 <경로>.enc 를 받아 브라우저 안에서 푼다.
  const ENC = { on: false, key: null, urls: {} };
  const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  async function unseal(path) {
    const r = await fetch(`${path}.enc`);
    if (!r.ok) throw new Error(`${path} ${r.status}`);
    const b = new Uint8Array(await r.arrayBuffer());
    return crypto.subtle.decrypt({ name: 'AES-GCM', iv: b.slice(0, 12) }, ENC.key, b.slice(12));
  }
  const sjson = async path => ENC.on ? JSON.parse(new TextDecoder().decode(await unseal(path))) : U.json(path);
  async function keyOk(key, lock) {
    try { const c = b64(lock.check); await crypto.subtle.decrypt({ name: 'AES-GCM', iv: c.slice(0, 12) }, key, c.slice(12)); return true; } catch (e) { return false; }
  }
  async function unlock() {
    let lock;
    try { const r = await fetch('data/study/lock.json', { cache: 'no-cache' }); if (!r.ok) return; lock = await r.json(); } catch (e) { return; }
    ENC.on = true;
    const saved = localStorage.getItem('study_key');
    if (saved) {
      const k = await crypto.subtle.importKey('raw', b64(saved), 'AES-GCM', false, ['decrypt']);
      if (await keyOk(k, lock)) { ENC.key = k; return; }
      localStorage.removeItem('study_key');
    }
    $('body').innerHTML = `<section class="card col sd-lock"><h3>암호를 넣어 주세요</h3>
      <p class="muted small">Study는 책·리포트 원문 그림이 들어 있어 암호로 잠가 두었습니다. 한 번 풀면 이 기기에서는 다시 묻지 않습니다.</p>
      <form id="sd-unlock"><input type="password" id="sd-pw" autocomplete="current-password" placeholder="암호"><button type="submit">열기</button><span id="sd-pwmsg" class="small"></span></form></section>`;
    $('sd-pw').focus();
    await new Promise(done => {
      $('sd-unlock').addEventListener('submit', async e => {
        e.preventDefault();
        $('sd-pwmsg').textContent = '확인 중…';
        const base = await crypto.subtle.importKey('raw', new TextEncoder().encode($('sd-pw').value), 'PBKDF2', false, ['deriveKey']);
        const k = await crypto.subtle.deriveKey({ name: 'PBKDF2', hash: 'SHA-256', salt: b64(lock.salt), iterations: lock.iter }, base,
          { name: 'AES-GCM', length: 256 }, true, ['decrypt']);
        if (!(await keyOk(k, lock))) { $('sd-pwmsg').textContent = '암호가 맞지 않습니다'; return; }
        const raw = new Uint8Array(await crypto.subtle.exportKey('raw', k));
        localStorage.setItem('study_key', btoa(String.fromCharCode(...raw)));
        ENC.key = k;
        done();
      });
    });
  }
  // 잠긴 그림: 화면에 들어오는 <img src="data/study/…"> 를 가까워질 때 풀어 blob 주소로 바꾼다
  const IMG_IO = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { IMG_IO.unobserve(e.target); showImg(e.target); }
  }), { rootMargin: '800px 0px' }) : null;
  async function showImg(img) {
    const p = img.dataset.enc;
    try {
      ENC.urls[p] = ENC.urls[p] || unseal(p).then(buf => URL.createObjectURL(new Blob([buf], { type: p.endsWith('.png') ? 'image/png' : 'image/jpeg' })));
      img.src = await ENC.urls[p];
    } catch (e) { img.alt = `그림을 풀지 못했습니다 (${img.alt})`; }
  }
  function lockImg(img) {
    const src = img.getAttribute('src');
    if (!src || !src.startsWith('data/study/')) return;
    img.dataset.enc = src;
    img.removeAttribute('src');
    if (IMG_IO) IMG_IO.observe(img); else showImg(img);
  }
  function watchImages() {
    new MutationObserver(ms => ms.forEach(m => {
      if (m.type === 'attributes') return lockImg(m.target);
      m.addedNodes.forEach(n => { if (n.nodeType !== 1) return; if (n.tagName === 'IMG') lockImg(n); n.querySelectorAll?.('img').forEach(lockImg); });
    })).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['src'] });
  }

  const getDoc = async id => DOCS[id] || (DOCS[id] = await sjson(`data/study/docs/${id}.json`));
  const route = () => Object.fromEntries(new URLSearchParams(location.search));
  const nodeHref = (path, card) => `?n=${encodeURIComponent(path)}${card ? `&c=${card}` : ''}`;

  // 트리 노드 찾기
  const nodeMap = {};
  const index = (ns, trail = []) => ns.forEach(n => { nodeMap[n.path] = { ...n, trail: [...trail, n] }; index(n.children, [...trail, n]); });

  // ---------- 왼쪽 트리 ----------
  function drawTree(cur = '') {
    const li = n => {
      const open = cur === n.path || cur.startsWith(n.path + '/');
      const empty = !n.count;
      const kids = n.children.length ? `<ul${open || n.path.split('/').length < 2 ? '' : ' hidden'}>${n.children.map(li).join('')}</ul>` : '';
      return `<li class="${open ? 'open' : ''}${cur === n.path ? ' on' : ''}${empty ? ' sd-empty' : ''}">
        <a href="${nodeHref(n.path)}">${esc(n.name)}${n.count ? `<small>${n.count}</small>` : ''}</a>${kids}</li>`;
    };
    $('tree').innerHTML = `<ul class="sd-tree">${IX.tree.map(li).join('')}</ul>`;
  }

  // ---------- 조각 ----------
  const chip = (k, add) => {
    const e = IX.entities[k];
    if (!e) return '';
    return `<a class="sd-chip k-${e.kind}${add ? ' add' : ''}" href="?e=${encodeURIComponent(k)}" title="${esc(KIND_LABEL[e.kind])}${e.en ? ' · ' + esc(e.en) : ''}">${esc(e.name)}</a>`;
  };
  // 반도체 탭 칸으로 가는 링크 (semi.html?cell=칸)
  const semiLinks = cells => cells?.length ? `<p class="sd-links sd-semi">반도체 탭: ${cells.map(x => `<a href="semi.html?cell=${encodeURIComponent(x.id)}">${esc(x.name)}</a>`).join(' · ')}</p>` : '';
  const chips = (c) => {
    const a = (c.tags || []).map(k => chip(k)).join('');
    const b = (c.addTags || []).map(k => chip(k, true)).join('');
    return (a || b ? `<div class="sd-chips">${a}${b}</div>` : '') + semiLinks(c.semi_cells);
  };
  const srcLine = d => d.source.kind === 'multi' ? `리포트 ${d.source.n}건 종합 (${esc(d.source.houses || '')}) · ${esc(d.source.date || '')}` : d.source.kind === 'book' ? `${esc(d.source.author)} 지음 · 책` : `${esc(d.source.broker)} ${esc(d.source.author || '')} · ${esc(d.source.date || '')}`;
  const figLabel = f => `${f.part ? '[' + esc(f.part) + '] ' : ''}${f.no === '' ? '' : /^[^\d]/.test(f.no) ? `&lt;${esc(f.no)}&gt; ` : `&lt;${f.kind === 'fig' ? '그림' : '표'}${/-/.test(f.no) ? ' ' : ''}${f.no}&gt; `}${esc(f.title)}`;

  function tableHtml(rows) {
    if (!rows || !rows.length) return '';
    // 첫 줄을 머리로, 빈 머리칸은 앞 칸 이름을 잇는다
    const [head, ...body] = rows;
    return `<div class="sd-tblwrap"><table class="sd-tbl"><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
      <tbody>${body.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }

  // 원문 밖 내용 표시: 책이면 '책 외', 리포트면 '리포트 외'
  const outside = doc => doc?.source?.kind === 'book' ? '책 외' : '리포트 외';

  function cardHtml(doc, ti, ci, c) {
    const id = `${doc.id}:${ti}:${ci}`;
    const add = c.add ? `<p class="sd-add"><span>${outside(doc)}</span>${num(c.add)}</p>` : '';
    const page = c.p != null ? `<span class="sd-p">${c.src ? esc(c.src) + ' ' : (c.fig && c.fig.part ? esc(c.fig.part) + ' ' : '')}p.${c.p}</span>` : (c.src ? `<span class="sd-p">${esc(c.src)}</span>` : '');
    if (c.t === 'sec') {
      return `<div class="sd-card sd-sec" id="c-${id}"><h3>${esc(c.h)} ${page}</h3>
        <ul>${c.body.map(b => `<li>${num(b)}</li>`).join('')}</ul>${add}${chips(c)}</div>`;
    }
    if (c.t === 'calc') {   // 가정을 바꾸면 다시 계산되는 계산 카드
      CALC[id] = c;
      return `<div class="sd-card sd-calc" id="c-${id}"><h3>${esc(c.h)} <span class="sd-badge">계산 · 가정 조절</span></h3>
        ${c.body ? `<p class="sd-diatxt">${num(c.body)}</p>` : ''}
        <div class="cc-in">${c.inputs.map(x => `<label><span>${esc(x.label)}</span><input type="number" data-k="${esc(x.k)}" value="${x.v}" step="${x.step || 'any'}"><small>${esc(x.unit || '')}</small>${x.note ? `<em>${esc(x.note)}</em>` : ''}</label>`).join('')}</div>
        <table class="cc-out"><tbody>${c.out.map((o, i) => `<tr class="${o.hi ? 'hi' : ''}"><th>${esc(o.label)}</th><td class="cc-f" data-i="${i}"></td><td class="cc-v" data-i="${i}"></td></tr>`).join('')}</tbody></table>
        ${add}${chips(c)}</div>`;
    }
    if (c.t === 'dia') {   // 직접 그린 설명 그림 (study/diagrams/*.svg)
      return `<div class="sd-card sd-dia" id="c-${id}"><h3>${esc(c.h)} <span class="sd-badge">설명 그림 · 직접 그림</span></h3>
        <div class="dg">${c.svg || ''}</div>
        ${c.body ? `<p class="sd-diatxt">${num(c.body)}</p>` : ''}${add}${chips(c)}</div>`;
    }
    if (c.t === 'chart') {   // 원본 그림 없이 재구성만 있는 카드 (여러 그림을 모은 계산 등)
      return `<div class="sd-card sd-fig sd-kchart" id="c-${id}">
        <div class="sd-vis">${SChart.html(c.chart)}</div>
        <div class="sd-txt"><h3>${esc(c.h)} <span class="sd-badge">재구성</span></h3>
          ${c.body ? `<p>${num(c.body)}</p>` : ''}${add}${chips(c)}</div></div>`;
    }
    if (c.t === 'seq') return seqHtml(doc, id, c, add);
    if (c.tech && c.fig?.hd) return techHtml(doc, id, c, add, page);
    if (c.t === 'ext' && c.m) return techHtml(doc, id, c, add, page);
    const f = c.fig;
    const rows = f.rows ? `<details class="sd-data"><summary>원문 표 데이터 (원문에서 읽은 값, 셀 병합은 풀림)</summary>${tableHtml(f.rows)}</details>` : '';
    const img = `<div class="sd-img"><img src="${esc(f.img)}" alt="${esc(f.title)}" loading="lazy" width="${f.w}" height="${f.h}" data-cap="${esc(f.title)}"></div>`;
    // 재구성 차트가 있으면 기본으로 보여 주고, 원본은 탭으로
    const vis = c.chart ? `<div class="sd-vis">
        <div class="sd-tabs" role="tablist"><button type="button" class="on" data-v="chart">재구성</button><button type="button" data-v="orig">원본 ${f.kind === 'fig' ? '그림' : '표'}</button></div>
        <div class="sd-pane" data-p="chart">${SChart.html(c.chart)}</div>
        <div class="sd-pane" data-p="orig" hidden>${img}</div></div>` : img;
    return `<div class="sd-card sd-fig sd-k${f.kind}${c.chart ? ' has-chart' : ''}" id="c-${id}">
      ${vis}
      <div class="sd-txt">
        <h3>${figLabel(f)} ${page}</h3>
        ${f.source ? `<p class="sd-src">${esc(f.source)}</p>` : ''}
        ${c.what ? `<p><b class="sd-lab">무엇</b>${num(c.what)}</p>` : ''}
        ${c.how ? `<p><b class="sd-lab">읽는 법</b>${num(c.how)}</p>` : ''}
        ${c.nums?.length ? `<div class="sd-nums"><b class="sd-lab">핵심 숫자</b><ul>${c.nums.map(n => `<li>${num(n)}</li>`).join('')}</ul></div>` : ''}
        ${c.so ? `<p class="sd-so"><b class="sd-lab">그래서</b>${num(c.so)}</p>` : ''}
        ${add}${chips(c)}
      </div>
      ${rows}
    </div>`;
  }

  // 실제 기전 그림 해설: 정리본 이미지 위 번호 + 번호별 설명 + 작동 순서 + 심화(리포트 외 보충)
  // 공개 이미지 출처 줄: 저작자 · 라이선스 · 원문 링크 (HTML 이 섞인 메타데이터는 글자만)
  const plain = s => String(s || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  const credit = m => `출처: <a href="${esc(m.page)}" target="_blank" rel="noopener">${esc(m.source)}</a>${m.author ? ' · ' + esc(plain(m.author)) : ''} · ${m.license_url ? `<a href="${esc(m.license_url)}" target="_blank" rel="noopener">${esc(m.license)}</a>` : esc(m.license)}${m.mods ? ' · ' + esc(m.mods) : ''}`;

  function techHtml(doc, id, c, add, page) {
    const ext = c.t === 'ext';
    const f = ext ? { hd: c.m.img, hd_w: c.m.w, hd_h: c.m.h, title: c.h } : c.fig, x = c.tech;
    const dots = x.spots.map(s => `<button type="button" class="tx-dot" style="left:${s.x}%;top:${s.y}%" data-n="${s.n}" aria-label="${s.n}. ${esc(s.ko)}">${s.n}</button>`).join('');
    // 번호 위치(%)는 이미지 기준 → 이미지만 감싼 상자에 올린다. 세로로 긴 그림은 높이 560px 안으로
    const maxw = Math.round(560 * f.hd_w / f.hd_h);
    const img = `<div class="tx-img"><div class="tx-in" style="max-width:min(100%, ${maxw}px)"><img src="${esc(f.hd)}" alt="${esc(f.title)}" width="${f.hd_w}" height="${f.hd_h}" data-cap="${esc(f.title)}" loading="lazy">${dots}</div></div>`;
    const orig = f.raw   // 책 사진: 정리 전 사진을 보여 줘야 비교가 된다
      ? `<div class="sd-img"><img src="${esc(f.raw)}" alt="${esc(f.title)}" loading="lazy" width="${f.raw_w}" height="${f.raw_h}" data-cap="${esc(f.title)}"></div>`
      : `<div class="sd-img"><img src="${esc(f.img)}" alt="${esc(f.title)}" loading="lazy" width="${f.w}" height="${f.h}" data-cap="${esc(f.title)}"></div>`;
    const tabs = [['tech', ext ? '해설 사진' : '해설 그림'], ...(c.chart ? [['chart', '재구성']] : []), ...(ext ? [] : [['orig', doc?.source?.kind === 'book' ? '원본 (책 지면)' : '원본 (리포트 지면)']])];
    const panes = { tech: img, chart: c.chart ? SChart.html(c.chart) : '', orig };
    const vis = `<div class="sd-vis"><div class="sd-tabs"${tabs.length < 2 ? ' hidden' : ''}>${tabs.map(([k, l], i) => `<button type="button" class="${i ? '' : 'on'}" data-v="${k}">${l}</button>`).join('')}</div>
      ${tabs.map(([k], i) => `<div class="sd-pane" data-p="${k}"${i ? ' hidden' : ''}>${panes[k]}</div>`).join('')}</div>`;
    const list = `<ol class="tx-spots">${x.spots.map(s => `<li data-n="${s.n}"><span class="tx-n">${s.n}</span><div><b>${esc(s.ko)}</b> <small class="muted">${esc(s.en)}</small><p>${num(s.text)}</p></div></li>`).join('')}</ol>`;
    const steps = x.steps?.length ? `<div class="tx-steps"><h4>작동 순서</h4><ol>${x.steps.map(s => `<li><b>${esc(s.h)}</b><p>${num(s.body)}</p></li>`).join('')}</ol></div>` : '';
    const deep = x.deep?.length ? `<div class="tx-deep"><h4>더 깊이 <span class="sd-addtag">보충 설명 · ${outside(doc)}</span></h4>${x.deep.map(s => `<details open><summary>${esc(s.h)}</summary><p>${num(s.body)}</p></details>`).join('')}</div>` : '';
    return `<div class="sd-card sd-tech" id="c-${id}">
      <h3>${ext ? esc(c.h) : figLabel(f)} ${page} <span class="sd-badge">${ext ? `공개 이미지 · ${outside(doc)}` : '기술 해설'}</span></h3>
      <p class="tx-title">${esc(x.title)}</p>
      ${ext ? `<p class="sd-src">${credit(c.m)}</p>`
        : f.scan ? '<p class="sd-src">해설 그림은 책 사진에서 잘라 종이색을 흰색으로 맞추고 선명하게 한 것</p>' : f.source ? `<p class="sd-src">${esc(f.source)} · 해설 그림은 원본 이미지를 꺼내 여백을 자르고 2배로 키운 것</p>` : ''}
      <div class="tx-top">${vis}${list}</div>
      ${steps}${deep}
      ${c.body ? `<p class="sd-diatxt">${num(c.body)}</p>` : ''}
      <div class="tx-notes">
        ${c.what ? `<p><b class="sd-lab">무엇</b>${num(c.what)}</p>` : ''}
        ${c.how ? `<p><b class="sd-lab">읽는 법</b>${num(c.how)}</p>` : ''}
        ${c.nums?.length ? `<div class="sd-nums"><b class="sd-lab">핵심 숫자</b><ul>${c.nums.map(n => `<li>${num(n)}</li>`).join('')}</ul></div>` : ''}
        ${c.so ? `<p class="sd-so"><b class="sd-lab">그래서</b>${num(c.so)}</p>` : ''}
        ${add}${chips(c)}
      </div>
    </div>`;
  }

  // 단계 넘기기: 그림 여러 장을 ◀ ▶ 로 넘기며 단계마다 바뀐 점을 읽는다 (예: 도핑, 포토 8단계, 공정 17컷)
  function seqHtml(doc, id, c, add) {
    const n = c.steps.length;
    const panes = c.steps.map((st, i) => {
      const f = st.fig, src = f.hd || f.img, w = f.hd ? f.hd_w : f.w, h = f.hd ? f.hd_h : f.h;
      const maxw = Math.round(440 * w / h);
      const dots = (st.spots || []).map(sp => `<span class="tx-dot sq-dot" style="left:${sp.x}%;top:${sp.y}%" title="${esc(sp.ko || '')}">${sp.n}</span>`).join('');
      const spots = st.spots?.length ? `<ol class="sq-spots">${st.spots.map(sp => `<li><span class="tx-n">${sp.n}</span><b>${esc(sp.ko)}</b> ${num(sp.text || '')}</li>`).join('')}</ol>` : '';
      return `<div class="sq-pane" data-i="${i}"${i ? ' hidden' : ''}>
        <div class="tx-img"><div class="tx-in" style="max-width:min(100%, ${maxw}px)"><img src="${esc(src)}" alt="${esc(f.title)}" width="${w}" height="${h}" data-cap="${esc(f.title)}"${i ? '' : ' loading="lazy"'}>${dots}</div></div>
        <div class="sq-txt"><p class="sq-h"><span class="sq-no">${i + 1}</span>${esc(st.h)}</p>${st.body ? `<p>${num(st.body)}</p>` : ''}${spots}
          <p class="sd-src">${figLabel(f)} · p.${f.page}</p></div></div>`;
    }).join('');
    const pips = c.steps.map((st, i) => `<button type="button" class="sq-pip${i ? '' : ' on'}" data-i="${i}" title="${esc(st.h)}">${i + 1}</button>`).join('');
    return `<div class="sd-card sd-seq" id="c-${id}" data-i="0" data-n="${n}">
      <h3>${esc(c.h)} <span class="sd-badge">단계 넘기기 · ${n}단계</span></h3>
      ${c.body ? `<p class="sd-diatxt">${num(c.body)}</p>` : ''}
      <div class="sq-nav"><button type="button" class="sq-prev" aria-label="이전 단계" disabled>◀</button><div class="sq-pips">${pips}</div><button type="button" class="sq-next" aria-label="다음 단계">▶</button></div>
      ${panes}
      ${c.so ? `<p class="sd-so"><b class="sd-lab">그래서</b>${num(c.so)}</p>` : ''}
      ${add}${chips(c)}
    </div>`;
  }

  function topicHtml(doc, ti) {
    const t = doc.topics[ti];
    const s = t.summary || {};
    // 이 주제에 나온 개념 → 용어 상자
    const concepts = [...new Set(t.cards.flatMap(c => c.tags || []).filter(k => k.startsWith('c:')))];
    const terms = concepts.length ? `<details class="sd-terms"><summary>이 주제의 용어 ${concepts.length}개</summary><dl>${concepts.map(k => {
      const e = IX.entities[k];
      return `<dt><a href="?e=${encodeURIComponent(k)}">${esc(e.name)}</a>${e.en ? ` <small class="muted">${esc(e.en)}</small>` : ''}</dt><dd>${num(e.desc)}</dd>`;
    }).join('')}</dl></details>` : '';
    const nf = t.cards.filter(c => c.t !== 'sec').length;
    return `<article class="sd-topic" id="t-${doc.id}-${ti}">
      <header class="sd-thead">
        <h2>${esc(t.title)}</h2>
        <p class="muted small"><a href="?d=${encodeURIComponent(doc.id)}">${esc(doc.title)}</a> · ${srcLine(doc)}${t.pages ? ` · p.${t.pages[0]}~${t.pages[1]}` : ''} · 카드 ${t.cards.length}개(그림·표 ${nf})</p>
      </header>
      ${s.points ? `<div class="sd-sum card"><h3>요약</h3><ul>${s.points.map(p => `<li>${num(p)}</li>`).join('')}</ul>
        ${s.why ? `<p><b class="sd-lab">왜 중요한가</b>${num(s.why)}</p>` : ''}
        ${s.invest ? `<p><b class="sd-lab">투자 관점</b>${num(s.invest)}</p>` : ''}</div>` : ''}
      ${terms}
      <div class="sd-cards">${t.cards.map((c, ci) => cardHtml(doc, ti, ci, c)).join('')}</div>
    </article>`;
  }

  // ---------- 화면들 ----------
  function crumbs(path) {
    const n = nodeMap[path];
    return `<nav class="sd-crumb"><a href="?">Study</a>${n.trail.map(x => ` › <a href="${nodeHref(x.path)}">${esc(x.name)}</a>`).join('')}</nav>`;
  }

  async function showHome() {
    const docs = Object.values(IX.docs);
    const sectors = IX.tree.map(s => `<a class="sd-sector card" href="${nodeHref(s.path)}">
        <h3>${esc(s.name)}</h3><p class="big">${s.count}<small> 주제</small></p>
        <p class="muted small">${s.count ? s.children.map(c => esc(c.name)).join(' · ') : esc(s.desc || '자료가 들어오면 채웁니다')}</p></a>`).join('');
    const kinds = Object.entries(KIND_LABEL).map(([k, l]) => {
      const n = Object.values(IX.entities).filter(e => e.kind === k).length;
      return `<span class="sd-chip k-${k}">${l} ${n}</span>`;
    }).join('');
    $('body').innerHTML = `<div class="page-head"><h1>Beom's Study</h1><p>리포트·책을 그림·표 한 장씩 카드로 풀어 쌓습니다. 왼쪽은 주제 기준 분류이고, 칩(개념·약물·기업·임상·적응증)을 누르면 모든 문서에서 그 항목이 나온 카드가 모입니다.</p></div>
      <div class="sd-sectors">${sectors}</div>
      <section class="card col sd-docs"><h3>문서</h3>${docs.map(d => `<a class="sd-doc" href="?d=${encodeURIComponent(d.id)}">
        <b>${esc(d.title)}</b><span class="muted small">${srcLine(d)} · ${d.source.pages}쪽</span>
        <span class="sd-prog"><i style="width:${(100 * d.nfig_done / Math.max(d.nfig_total, 1)).toFixed(1)}%"></i></span>
        <span class="small">그림·표 ${d.nfig_done}/${d.nfig_total} 카드화 · 카드 ${d.ncards}개${d.source.kind === 'multi' ? '' : ` · 작성 p.${d.done[0]}~${d.done[1]}`}</span></a>`).join('')}</section>
      <section class="card col"><h3>색인</h3><div class="sd-chips">${kinds}</div>
        <p class="muted small">색인 목록은 왼쪽 검색창에 아무 글자나 넣으면 나옵니다.</p></section>`;
  }

  async function showNode(path, card) {
    const n = nodeMap[path];
    if (!n) return showHome();
    let html = crumbs(path) + `<div class="page-head"><h1>${esc(n.name)}</h1>${n.desc ? `<p>${esc(n.desc)}</p>` : ''}</div>`;
    if (n.children.length) {
      html += `<div class="sd-kids">${n.children.map(k => `<a class="sd-kid card${k.count ? '' : ' sd-empty'}" href="${nodeHref(k.path)}">
        <b>${esc(k.name)}</b><small class="muted">${k.count ? `주제 ${k.count}` : '아직 없음'}</small></a>`).join('')}</div>`;
    }
    if (n.topics.length) {
      const docs = await Promise.all([...new Set(n.topics.map(t => t.doc))].map(getDoc));
      const by = Object.fromEntries(docs.map(d => [d.id, d]));
      html += `<p class="muted small sd-from">이 주제를 다룬 문서: ${[...new Set(n.topics.map(t => t.doc))].map(id => `<a href="?d=${encodeURIComponent(id)}">${esc(by[id].title)}</a> (${srcLine(by[id])})`).join(', ')}</p>`;
      html += n.topics.map(t => topicHtml(by[t.doc], t.ti)).join('');
    } else if (!n.children.length || !n.count) {
      html += `<p class="msg">아직 이 주제의 자료가 없습니다.</p>`;
    }
    $('body').innerHTML = html;
    if (card) {
      const el = document.getElementById(`c-${card}`);
      if (el) { el.classList.add('hit'); el.scrollIntoView({ block: 'center' }); return; }
    }
    window.scrollTo(0, 0);
  }

  function companyLinks(e) {
    const out = [];
    if (e.code) out.push(Stock.link({ c: e.code, n: `${e.name} 종목 상세` }));
    if (e.bio) out.push(`<a href="bio.html?m=${e.bio.m}&c=${encodeURIComponent(e.bio.c)}">바이오 탭 자산 카드</a>`);
    if (e.ticker) out.push(`<span class="muted">${esc(e.ticker)}</span>`);
    (e.semi_cells || []).forEach(x => out.push(`<a href="semi.html?cell=${encodeURIComponent(x.id)}">반도체 탭 · ${esc(x.name)}</a>`));
    if (e.listed === false) out.push('<span class="muted">비상장</span>');
    return out.length ? `<p class="sd-links">${out.join(' · ')}</p>` : '';
  }

  async function showEntity(key) {
    const e = IX.entities[key];
    if (!e) return showHome();
    // 이 항목을 만든 회사, 이 회사가 만든 약
    const made = e.kind === 'co' ? Object.entries(IX.entities).filter(([, x]) => (x.co || []).includes(key)).map(([k]) => k) : [];
    const rel = [...(e.co || []), ...(e.tags || []), ...made];
    // 함께 나온 항목: 같은 카드에 붙은 칩을 센다
    const cnt = {};
    for (const r of e.refs) {
      const c = (await getDoc(r.doc)).topics[r.ti].cards[r.ci];
      for (const k of [...(c.tags || []), ...(c.addTags || [])]) if (k !== key) cnt[k] = (cnt[k] || 0) + 1;
    }
    const co = Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 18);
    // 출처 카드: 문서·주제별로 묶기
    const groups = {};
    e.refs.forEach(r => { (groups[`${r.doc}|${r.ti}`] = groups[`${r.doc}|${r.ti}`] || []).push(r); });
    const refs = Object.values(groups).map(rs => `<div class="sd-refg"><h4><a href="${nodeHref(rs[0].node)}">${esc(rs[0].topic)}</a> <small class="muted">${esc(IX.docs[rs[0].doc].title)}</small></h4>
      <ul>${rs.map(r => `<li><a href="${nodeHref(r.node, `${r.doc}:${r.ti}:${r.ci}`)}">${esc(r.h || '본문')}</a>${r.p != null ? ` <span class="sd-p">p.${r.p}</span>` : ''}${r.add ? ' <span class="sd-addtag">원문 외</span>' : ''}</li>`).join('')}</ul></div>`).join('');
    $('body').innerHTML = `<nav class="sd-crumb"><a href="?">Study</a> › 색인 › ${esc(KIND_LABEL[e.kind])}</nav>
      <div class="page-head"><h1><span class="sd-chip k-${e.kind}">${esc(KIND_LABEL[e.kind])}</span> ${esc(e.name)}</h1>
        ${e.en ? `<p>${esc(e.en)}${e.mod ? ' · ' + esc(e.mod) : ''}</p>` : ''}</div>
      <section class="card col sd-ent">
        <p class="sd-desc">${num(e.desc || '')}</p>
        ${e.add ? '<p class="sd-add"><span>원문 외</span>이 항목은 원문(리포트·책)에 나오지 않고 연결을 위해 덧붙였습니다.</p>' : ''}
        ${companyLinks(e)}
        ${rel.length ? `<div class="sd-chips"><b class="sd-lab">연결</b>${rel.map(k => chip(k)).join('')}</div>` : ''}
        ${co.length ? `<div class="sd-chips"><b class="sd-lab">함께 나온</b>${co.map(([k, n]) => chip(k).replace('</a>', `<small>${n}</small></a>`)).join('')}</div>` : ''}
      </section>
      <section class="card col"><h3>나온 카드 ${e.refs.length}개</h3>${refs || '<p class="muted">아직 카드가 없습니다.</p>'}</section>`;
    window.scrollTo(0, 0);
  }

  async function showDoc(id) {
    const m = IX.docs[id];
    if (!m) return showHome();
    const o = m.overview || {};
    $('body').innerHTML = `<nav class="sd-crumb"><a href="?">Study</a> › 문서</nav>
      <div class="page-head"><h1>${esc(m.title)}</h1><p>${srcLine(m)}${m.source.series ? ' · ' + esc(m.source.series) : ''} · ${m.source.pages}쪽</p></div>
      <section class="card col sd-sum">
        <h3>한눈에</h3><ul>${(o.points || []).map(p => `<li>${num(p)}</li>`).join('')}</ul>
        ${o.how_to_read ? `<p><b class="sd-lab">읽는 법</b>${num(o.how_to_read)}</p>` : ''}
        <p class="small muted">진행: 그림·표 ${m.nfig_done}/${m.nfig_total} 카드화 · ${m.source.kind === 'multi' ? `리포트 ${m.source.n}건` : m.done[1] >= m.done[0] ? `작성 범위 p.${m.done[0]}~${m.done[1]}` : '아직 작성 전'}</p>
      </section>
      <section class="card col"><h3>목차 (작성된 주제)</h3><ol class="sd-toc">${m.topics.map(t => `<li><a href="${nodeHref(t.node)}">${esc(t.title)}</a>
        <small class="muted">${t.pages ? `p.${t.pages[0]}~${t.pages[1]} · ` : ''}${esc(nodeMap[t.node].trail.map(x => x.name).join(' › '))}</small></li>`).join('')}</ol></section>`;
    window.scrollTo(0, 0);
  }

  async function showSearch(q) {
    const s = q.trim().toLowerCase();
    if (!s) return showHome();
    const ents = Object.entries(IX.entities).filter(([k, e]) => [e.name, e.en, e.desc, k].some(v => (v || '').toLowerCase().includes(s)));
    const docs = await Promise.all(Object.keys(IX.docs).map(getDoc));
    const hits = [];
    docs.forEach(d => d.topics.forEach((t, ti) => t.cards.forEach((c, ci) => {
      const txt = [c.h, c.what, c.how, c.so, c.add, ...(Array.isArray(c.body) ? c.body : [c.body]), ...(c.nums || []), c.fig?.title, c.chart?.note].filter(Boolean).join(' ');
      const at = txt.toLowerCase().indexOf(s);
      if (at >= 0) hits.push({ d, t, ti, ci, c, snip: txt.slice(Math.max(0, at - 40), at + 80) });
    })));
    const mark = t => esc(t).replace(new RegExp(s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), m => `<mark>${m}</mark>`);
    $('body').innerHTML = `<div class="page-head"><h1>검색: ${esc(q)}</h1><p>색인 ${ents.length}개 · 카드 ${hits.length}개</p></div>
      ${ents.length ? `<section class="card col"><h3>색인</h3><div class="sd-chips">${ents.map(([k]) => chip(k)).join('')}</div></section>` : ''}
      <section class="card col"><h3>카드</h3>${hits.slice(0, 200).map(h => `<p class="sd-hit"><a href="${nodeHref(h.t.node, `${h.d.id}:${h.ti}:${h.ci}`)}">${esc(h.c.h || h.c.fig?.title || '')}</a>
        <small class="muted">${esc(h.t.title)}</small><br><span class="small">…${mark(h.snip)}…</span></p>`).join('') || '<p class="muted">없음</p>'}</section>`;
    window.scrollTo(0, 0);
  }

  async function go() {
    const r = route();
    drawTree(r.n || '');
    try {
      if (r.n) await showNode(r.n, r.c);
      else if (r.e) await showEntity(r.e);
      else if (r.d) await showDoc(r.d);
      else if (r.q) await showSearch(r.q);
      else await showHome();
    } catch (err) {
      $('body').innerHTML = `<p class="msg">불러오지 못했습니다. (${esc(err.message)})</p>`;
    }
    document.querySelectorAll('.sd-calc').forEach(calcRun);
  }

  // 재구성 / 원본 탭
  document.addEventListener('click', e => {
    const b = e.target.closest('.sd-tabs button');
    if (!b) return;
    const box = b.closest('.sd-vis');
    box.querySelectorAll('.sd-tabs button').forEach(x => x.classList.toggle('on', x === b));
    box.querySelectorAll('.sd-pane').forEach(x => { x.hidden = x.dataset.p !== b.dataset.v; });
  });

  // 단계 넘기기: ◀ ▶ · 단계 번호 · 좌우 화살표 키(카드에 마우스가 있을 때)
  const seqGo = (card, i) => {
    const n = +card.dataset.n;
    i = Math.max(0, Math.min(n - 1, i));
    card.dataset.i = i;
    card.querySelectorAll('.sq-pane').forEach(p => { p.hidden = +p.dataset.i !== i; });
    card.querySelectorAll('.sq-pip').forEach(p => p.classList.toggle('on', +p.dataset.i === i));
    card.querySelector('.sq-prev').disabled = i === 0;
    card.querySelector('.sq-next').disabled = i === n - 1;
  };
  document.addEventListener('click', e => {
    const b = e.target.closest('.sq-prev, .sq-next, .sq-pip');
    if (!b) return;
    const card = b.closest('.sd-seq');
    seqGo(card, b.classList.contains('sq-pip') ? +b.dataset.i : +card.dataset.i + (b.classList.contains('sq-next') ? 1 : -1));
  });
  let seqHover = null;
  document.addEventListener('mouseover', e => { seqHover = e.target.closest && e.target.closest('.sd-seq'); });
  document.addEventListener('keydown', e => {
    if (!seqHover || !document.contains(seqHover) || !['ArrowLeft', 'ArrowRight'].includes(e.key) || e.target.closest('input, textarea')) return;
    e.preventDefault();
    seqGo(seqHover, +seqHover.dataset.i + (e.key === 'ArrowRight' ? 1 : -1));
  });

  // 해설 그림: 번호 ↔ 설명 서로 강조 (마우스를 올리거나 누르면)
  const txMark = (el, on) => {
    const card = el.closest('.sd-tech');
    if (!card) return;
    const n = el.dataset.n;
    card.querySelectorAll('.tx-dot, .tx-spots li').forEach(x => x.classList.toggle('hl', on && x.dataset.n === n));
  };
  document.addEventListener('mouseover', e => { const el = e.target.closest('.tx-dot, .tx-spots li'); if (el) txMark(el, true); });
  document.addEventListener('mouseout', e => { const el = e.target.closest('.tx-dot, .tx-spots li'); if (el) txMark(el, false); });
  document.addEventListener('click', e => {
    const dot = e.target.closest('.tx-dot');
    if (!dot) return;
    const li = dot.closest('.sd-tech').querySelector(`.tx-spots li[data-n="${dot.dataset.n}"]`);
    if (li) { li.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); txMark(dot, true); }
  });

  // 그림 크게 보기
  document.addEventListener('click', e => {
    const img = e.target.closest('.sd-img img, .tx-img img');
    if (img) {
      const lb = $('lb');
      lb.querySelector('img').src = img.src;
      lb.querySelector('p').textContent = img.dataset.cap;
      lb.hidden = false;
      return;
    }
    if (e.target.closest('#lb')) $('lb').hidden = true;
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') $('lb').hidden = true; });

  let qt;
  $('q').addEventListener('input', e => {
    clearTimeout(qt);
    qt = setTimeout(() => {
      const v = e.target.value.trim();
      history.replaceState(null, '', v ? `?q=${encodeURIComponent(v)}` : location.pathname);
      go();
    }, 250);
  });
  // 화면 안 링크(?로 시작)는 새로 불러오지 않고 주소만 바꿔 다시 그린다
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href^="?"]');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    history.pushState(null, '', a.getAttribute('href') === '?' ? location.pathname : a.getAttribute('href'));
    go();
  });
  window.addEventListener('popstate', () => { if (!/^#[0-9A-Z]{6}$/.test(location.hash)) go(); });

  U.initTheme($('theme'));
  (async () => {
    try {
      await unlock();
      if (ENC.on) watchImages();
      IX = await sjson('data/study/index.json');
    } catch (e) {
      $('msg').textContent = `공부 데이터를 불러오지 못했습니다. python3 build_study.py 를 먼저 실행하세요. (${e.message})`;
      return;
    }
    index(IX.tree);
    $('asof').textContent = `${U.timeLabel(IX.generated_at)} 빌드`;
    const q = route().q;
    if (q) $('q').value = q;
    go();
  })();
})();
