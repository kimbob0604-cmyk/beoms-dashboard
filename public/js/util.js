// 탭 공통: 숫자 포맷, 테마, JSON 로딩
const U = (() => {
  const DOW = '일월화수목금토';
  const cache = {}, last = {}, got = {};

  // ── 실시간 시세 덧입히기 (2026-11-19) ──
  // data/quotes.json({_d: 시세 날짜, _t: 장중 시각, 코드: [가격, 등락률]})은 장중 1분마다 맥(live.py)이나 GitHub Actions(cloud_live.py)가
  // 새로 올린다. 탭 데이터의 종목 행({c, n, mk, w, mc, p, ch} — build_naver.market_info 모양)은 빌드한 때의 가격이라,
  // 읽을 때와 시세가 바뀔 때마다 p·ch 를 지금 시세로 바꾸고 시총(mc)은 가격 비율로 맞춘다. 바이오 국장 행({ticker, price, mcap})도.
  // 날짜별 파일(data/<폴더>/<날짜>.json)은 그날이 시세 날짜보다 앞이면(지난날 화면) 건드리지 않는다.
  let Q = null, qText = null, qP = null, qVer = 0;   // qVer: 시세가 바뀔 때마다 1씩 — 한 화면의 여러 확인 타이머가 모두 알아채게
  const orig = new WeakMap();
  const NO_OVERLAY = /(^|\/)(quotes|home|live_base|live_high|names)\.json|\/dates\.json|^data\/(stocks|chart|vchart|bt|st|events|earn|dart\/s)\//;
  const DATED = /^data\/[\w-]+\/(\d{4}-\d{2}-\d{2})\.json/;
  const overlayable = url => !NO_OVERLAY.test(url) && (!DATED.test(url) || !Q?.d || url.match(DATED)[1] >= Q.d);
  function setQuotes(text) {
    if (text === qText) return false;
    qText = text;
    qVer++;
    try {
      const j = JSON.parse(text);
      Q = { d: j._d, t: j._t, m: j };
    } catch (e) { Q = null; }
    return true;
  }
  function overlay(o) {
    if (!Q || !o || typeof o !== 'object') return;
    if (Array.isArray(o)) { for (const v of o) if (v && typeof v === 'object') overlay(v); return; }
    const code = typeof o.c === 'string' ? o.c : (typeof o.ticker === 'string' && /^\d{6}$/.test(o.ticker) ? o.ticker : null);
    const q = code && code[0] !== '_' ? Q.m[code] : null;
    if (Array.isArray(q) && q[0] != null) {
      if ('p' in o && 'ch' in o) {
        let b = orig.get(o);
        if (!b) { b = { p: o.p, mc: o.mc }; orig.set(o, b); }
        o.p = q[0];
        o.ch = q[1];
        if (b.mc != null && b.p) o.mc = Math.round(b.mc * q[0] / b.p);
      } else if (typeof o.price === 'number' && 'mcap' in o) {
        let b = orig.get(o);
        if (!b) { b = { price: o.price, mcap: o.mcap }; orig.set(o, b); }
        o.price = q[0];
        if (b.mcap != null && b.price) o.mcap = b.mcap * q[0] / b.price;
      }
    }
    for (const k in o) { const v = o[k]; if (v && typeof v === 'object') overlay(v); }
  }
  const applyQuotes = (url, data) => { if (overlayable(url)) overlay(data); return data; };

  const num = (v, nd = 0) => v.toLocaleString('ko-KR', { minimumFractionDigits: nd, maximumFractionDigits: nd });

  return {
    // 2026-11-02 → 11/2(월)
    dateLabel(d) {
      const t = new Date(d + 'T00:00:00');
      return `${t.getMonth() + 1}/${t.getDate()}(${DOW[t.getDay()]})`;
    },
    // 2026-11-03T11:07:56 → 11/3(화) 11:07
    timeLabel(ts) {
      if (!ts) return '–';
      const t = new Date(ts);
      return `${t.getMonth() + 1}/${t.getDate()}(${DOW[t.getDay()]}) ${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
    },
    // 억 단위 값 → 753억 / 1.5조
    eok(v, signed = false) {
      if (v == null) return '–';
      const sign = signed && v > 0 ? '+' : '';
      return Math.abs(v) >= 10000 ? `${sign}${num(v / 10000, 1)}조` : `${sign}${num(Math.round(v))}억`;
    },
    won(v, signed = false) {
      if (v == null) return '–';
      return `${signed && v > 0 ? '+' : ''}${num(Math.round(v))}원`;
    },
    // 소수 → +18.8%
    pct(v, nd = 1) {
      if (v == null) return '–';
      return `${v > 0 ? '+' : ''}${num(v * 100, nd)}%`;
    },
    mult(v) {
      return v == null ? '–' : `${num(v, 1)}배`;
    },
    price(v) {
      return v == null ? '–' : num(v);
    },
    cls(v) {
      return v > 0 ? 'up' : v < 0 ? 'down' : '';
    },
    // POR = 시총 ÷ 영업이익 표 (종목 패널·탐방 탭 공통). mc: 시총(억), pv: {fy0: 올해 결산연도, ops: [[연도, 영업이익(억), 추정이면 1]…]}
    // 내년 열을 강조한다. 영업이익이 0 이하면 배수 대신 '적자'.
    porTable(mc, pv, capLabel = '시총') {
      if (!pv?.ops?.length || !mc) return '';
      const cs = pv.ops.map(([fy, op, est]) => ({ fy, op, est, por: op > 0 ? mc / op : null, key: fy === pv.fy0 + 1 }));
      const k = c => (c.key ? ' class="key"' : '');
      const tag = c => (c.key ? '<small>내년</small>' : c.fy === pv.fy0 ? '<small>올해</small>' : '');
      return `<div class="por">
        <div class="por-eq"><b>POR</b> = ${capLabel} <b>${U.eok(mc)}</b> ÷ 영업이익</div>
        <table class="por-tbl">
          <thead><tr><th></th>${cs.map(c => `<th${k(c)}>${String(c.fy).slice(2)}${c.est ? 'E' : 'A'}${tag(c)}</th>`).join('')}</tr></thead>
          <tbody>
            <tr><th>영업이익</th>${cs.map(c => `<td${k(c)}><span class="${c.op < 0 ? 'down' : ''}">${U.eok(c.op)}</span></td>`).join('')}</tr>
            <tr class="por-x"><th>POR</th>${cs.map(c => `<td${k(c)}>${c.por != null ? `<b>${U.mult(c.por)}</b>` : '<span class="muted">적자</span>'}</td>`).join('')}</tr>
          </tbody>
        </table>
      </div>`;
    },
    // 글 속 숫자 강조: 원문을 이스케이프한 뒤 금액·비율·배수 같은 숫자를 <b class="n">로 감싼다.
    // 부호 있는 %(+12%, -3.5%)는 오름·내림 색까지. HTML 엔티티(&#39; 등) 속 숫자는 건드리지 않는다.
    num(s) {
      return U.esc(s).replace(/(?<![#\w&.])([+\-−]?\d[\d,]*(?:\.\d+)?)(?:(\s?(?:조|억|만|천|원|%p|%|배|주|건|명|년|분기|개월|일|bp))|(?![\w.]))/g, (m, n, u = '') => {
        const signed = /^[+\-−]/.test(n) && /%/.test(u);
        const cls = signed ? (n.startsWith('+') ? ' up' : ' down') : '';
        return `<b class="n${cls}">${n}${u}</b>`;
      });
    },
    esc(s) {
      return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    },
    // GitHub Pages 는 CDN 이 10분 캐시하고 브라우저의 'no-cache' 요청도 무시한다(2026-11-09 확인).
    // 주소에 1분 단위 숫자를 붙여 CDN 을 우회한다 → 새로고침하면 1분 안의 최신 데이터.
    bust(url, every = 60000) {
      return `${url}${url.includes('?') ? '&' : '?'}t=${Math.floor(Date.now() / every)}`;
    },
    async json(url) {
      if (!cache[url]) {
        cache[url] = Promise.all([fetch(U.bust(url), { cache: 'no-store' }), overlayable(url) ? U.quotes() : null]).then(async ([r]) => {
          if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
          const text = await r.text();
          last[url] = text;
          return (got[url] = applyQuotes(url, JSON.parse(text)));
        });
        cache[url].catch(() => delete cache[url]);
      }
      return cache[url];
    },
    // 지금 서버 것을 다시 받아, 내용이 바뀌었으면 새 데이터를(캐시도 바꿈), 그대로면 null 을 돌려준다
    async fresh(url) {
      const r = await fetch(U.bust(url, 1), { cache: 'no-store' });
      if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
      const text = await r.text();
      if (text === last[url]) return null;
      last[url] = text;
      const data = (got[url] = applyQuotes(url, JSON.parse(text)));
      cache[url] = Promise.resolve(data);
      return data;
    },
    // 받아 둔 파일을 잊는다 → 다음 U.json 이 서버에서 새로 받는다 (종목별·조합별 상세처럼 U.live 목록에 없는 파일)
    forget(prefix, keep = []) {
      for (const url of Object.keys(cache)) {
        if (url.startsWith(prefix) && !keep.includes(url)) { delete cache[url]; delete last[url]; delete got[url]; }
      }
    },
    // data/quotes.json 을 한 번 받아 둔다 (탭 데이터에 덧입힐 시세)
    quotes() {
      qP = qP || fetch(U.bust('data/quotes.json', 1), { cache: 'no-store' })
        .then(r => (r.ok ? r.text() : null)).then(t => { if (t) setQuotes(t); return Q; }).catch(() => null);
      return qP;
    },
    // 시세를 다시 받아 바뀌었으면 읽어 둔 탭 데이터 전부에 다시 덧입히고 true
    async refreshQuotes() {
      try {
        const r = await fetch(U.bust('data/quotes.json', 1), { cache: 'no-store' });
        if (!r.ok || !setQuotes(await r.text())) return false;
      } catch (e) { return false; }
      qP = Promise.resolve(Q);
      for (const [url, data] of Object.entries(got)) applyQuotes(url, data);
      return true;
    },
    // 열어 둔 화면 실시간: 1분마다(화면이 보일 때)와 탭으로 돌아올 때 시세와 urls 를 다시 받아,
    // 무엇이든 바뀌었으면 onChange 를 부른다(그 안에서 U.json 으로 다시 읽으면 새 데이터). 2026-11-19
    // urls 는 배열이나 배열을 돌려주는 함수(보고 있는 날짜에 따라 바뀔 때)
    live(urls, onChange, every = 60000) {
      let busy = false, seen = qVer;
      const tick = async () => {
        if (document.hidden || busy) return;
        busy = true;
        try {
          await U.refreshQuotes();
          let changed = seen !== qVer;
          seen = qVer;
          for (const url of (typeof urls === 'function' ? urls() : urls)) {
            try { if (await U.fresh(url)) changed = true; } catch (e) { /* 없는 파일·네트워크 — 다음 차례에 */ }
          }
          if (changed) await onChange();
        } catch (e) { /* 다음 차례에 */ } finally { busy = false; }
      };
      setInterval(tick, every);
      document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
    },
    // 2026-11-03 → 11.03 (리포트 날짜처럼 짧게)
    md(d) {
      return d ? `${d.slice(5, 7)}.${d.slice(8, 10)}` : '';
    },
    // 새 탭(컨센 리비전·신고가·수급)이 함께 쓰는 URL 상태 + 필터 버튼
    // 기본값과 같은 값은 URL에 남기지 않는다. date 는 첫 날짜(최신)면 생략.
    page(defaults, onChange) {
      const p = new URLSearchParams(location.search);
      const state = { ...defaults };
      for (const k in state) if (p.has(k)) state[k] = p.get(k);
      const api = {
        state,
        latest: '',
        set(patch) {
          Object.assign(state, patch);
          api.write();
          onChange(patch);
        },
        write() {
          const q = new URLSearchParams();
          for (const k in state) {
            if (state[k] === defaults[k] || (k === 'date' && state.date === api.latest)) continue;
            q.set(k, state[k]);
          }
          const qs = q.toString();
          history.replaceState(null, '', (qs ? `?${qs}` : location.pathname) + location.hash);
        },
        seg(key, opts) {
          return `<div class="seg" role="group">${opts.map(([val, label, title]) =>
            `<button data-k="${key}" data-v="${val}" class="${state[key] === val ? 'on' : ''}"${title ? ` title="${title}"` : ''}>${label}</button>`).join('')}</div>`;
        },
        chk(key, label, title = '') {
          return `<label class="chk${state[key] ? ' on' : ''}" title="${title}"><input type="checkbox" data-chk="${key}"${state[key] ? ' checked' : ''}> ${label}</label>`;
        },
        // 필터 영역의 버튼·체크박스·검색창을 state 에 연결
        bind(el) {
          el.addEventListener('click', e => {
            const b = e.target.closest('button[data-k]');
            if (b) api.set({ [b.dataset.k]: b.dataset.v });
          });
          el.addEventListener('change', e => {
            if (e.target.dataset.chk) api.set({ [e.target.dataset.chk]: e.target.checked ? '1' : '' });
            else if (e.target.dataset.sel) api.set({ [e.target.dataset.sel]: e.target.value });
          });
          let t;
          el.addEventListener('input', e => {
            if (!e.target.dataset.q) return;
            clearTimeout(t);
            t = setTimeout(() => {
              state[e.target.dataset.q] = e.target.value;
              api.write();
              onChange({ q: e.target.value }, true);   // true: 검색 중 — 필터 영역은 다시 그리지 않음
            }, 150);
          });
        },
      };
      return api;
    },
    // dates.json → 기준일 select 채우기. 고른 날짜를 돌려준다.
    // onRefresh(날짜): 같은 날 데이터·시세가 바뀌었을 때 다시 그리기 (없으면 onPick — 펼침 상태를 지우는 화면은 따로 준다)
    async dates(folder, pg, sel, onPick, onRefresh = onPick) {
      let ds = await U.json(`data/${folder}/dates.json`);
      if (!ds.length) throw new Error('빌드된 날짜 없음');
      pg.latest = ds[0];
      if (!ds.includes(pg.state.date)) pg.state.date = ds[0];
      const fill = () => {
        sel.innerHTML = ds.map(d => `<option value="${d}"${d === pg.state.date ? ' selected' : ''}>${U.dateLabel(d)} 기준</option>`).join('');
      };
      fill();
      sel.addEventListener('change', e => { pg.state.date = e.target.value; pg.write(); onPick(e.target.value); });
      // 1분마다: 최신 날짜를 보고 있으면 새 날짜가 올라왔을 때 그 날짜로 넘어가고(장중 신고가가 새 거래일로 생기는 등),
      // 같은 날 갱신(신고가·수급·공시 등)이나 시세가 바뀌면 다시 그린다
      U.watch(folder, ds[0], async (qChanged, newer) => {
        if (newer) {
          const onLatest = pg.state.date === ds[0];
          ds = newer;
          pg.latest = ds[0];
          if (onLatest) { pg.state.date = ds[0]; pg.write(); }
          fill();
          if (onLatest) onPick(ds[0]);
          return onLatest;
        }
        if (pg.state.date !== ds[0]) return;
        try {
          if (await U.fresh(`data/${folder}/${ds[0]}.json`) || qChanged) onRefresh(ds[0]);
        } catch (e) { /* 다음 확인 때 */ }
      });
      return pg.state.date;
    },
    // 열어 둔 화면: 1분마다(화면이 보일 때), 그리고 탭으로 돌아올 때 새 날짜·시세를 확인한다 (2026-11-19 3분 → 1분, 매일).
    // onSame(시세 바뀜, 새 날짜 목록|null) — 새 날짜를 스스로 처리했으면 true 를 돌려주고, 아니면 '새로 올라왔습니다' 알림을 띄운다
    watch(folder, latest, onSame) {
      let busy = false, seen = qVer;
      const check = async () => {
        if (document.hidden || busy) return;
        busy = true;
        try {
          const ds = await (await fetch(U.bust(`data/${folder}/dates.json`, 1), { cache: 'no-store' })).json();
          await U.refreshQuotes();
          const q = seen !== qVer;
          seen = qVer;
          if (ds[0] && ds[0] > latest) {
            latest = ds[0];
            if (!(onSame && await onSame(q, ds))) {
              U.toast(`${U.dateLabel(ds[0])} 데이터가 새로 올라왔습니다`, '보기', () => {
                const p = new URLSearchParams(location.search);
                p.delete('date');
                location.href = `${location.pathname}${p.toString() ? `?${p}` : ''}${location.hash}`;
              });
            }
          } else if (onSame) await onSame(q, null);
        } catch (e) { /* 다음 확인 때 */ } finally { busy = false; }
      };
      setInterval(check, 60000);
      document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
    },
    toast(msg, label, onClick) {
      let t = document.getElementById('toast');
      if (!t) {
        t = document.createElement('div');
        t.id = 'toast';
        t.className = 'toast';
        document.body.append(t);
      }
      t.innerHTML = `<span>${U.esc(msg)}</span>${label ? `<button>${U.esc(label)}</button>` : ''}<button class="x" aria-label="닫기">✕</button>`;
      t.hidden = false;
      t.querySelector('button:not(.x)')?.addEventListener('click', onClick);
      t.querySelector('.x').addEventListener('click', () => { t.hidden = true; });
    },
    // 한국 시간 (요일 0~6, 분)
    kst() {
      const k = new Date(Date.now() + (new Date().getTimezoneOffset() + 540) * 60000);
      return { dow: k.getDay(), min: k.getHours() * 60 + k.getMinutes() };
    },
    // 새 데이터가 올라올 수 있는 시간대: 매일 06:00~24:00 (맥 live.py 가 1분마다 도는 때 — 수급은 밤·주말에도, 텔레그램·뉴스도 매일).
    // 이때 열어 둔 화면을 1분마다 확인한다 (2026-11-19 평일 07:00~21:30 → 매일 06:00~24:00)
    busyHours() {
      const { min } = U.kst();
      return min >= 360;
    },
    // 'YYYY-MM-DDTHH:MM:SS'(한국 시각) → 지금으로부터 몇 분 전
    minsAgo(ts) {
      const { min } = U.kst();
      const k = new Date(Date.now() + (new Date().getTimezoneOffset() + 540) * 60000);
      const today = `${k.getFullYear()}-${String(k.getMonth() + 1).padStart(2, '0')}-${String(k.getDate()).padStart(2, '0')}`;
      if (!ts || ts.slice(0, 10) !== today) return Infinity;
      return min - (+ts.slice(11, 13) * 60 + +ts.slice(14, 16));
    },
    // 한국 시간 평일 08:50~15:40 (NXT 프리·애프터는 제외). 차트 이미지 자동 갱신에 쓴다
    marketHours() {
      const k = new Date(Date.now() + (new Date().getTimezoneOffset() + 540) * 60000);
      const m = k.getHours() * 60 + k.getMinutes();
      return k.getDay() > 0 && k.getDay() < 6 && m >= 530 && m <= 940;
    },
    initTheme(btn) {
      btn.addEventListener('click', () => {
        const root = document.documentElement;
        const dark = root.dataset.theme
          ? root.dataset.theme === 'dark'
          : matchMedia('(prefers-color-scheme: dark)').matches;
        root.dataset.theme = dark ? 'light' : 'dark';
        try { localStorage.setItem('theme', root.dataset.theme); } catch (e) {}
      });
    },
  };
})();

// ---------- 표 머리글을 누르면 그 열로 정렬 (모든 탭 공통) ----------
// 숫자 열은 처음 누르면 큰 순, 다시 누르면 작은 순. 글자 열은 가나다 순부터. 값 없는 칸(–)은 늘 맨 아래.
// 자체 정렬이 있는 표(th.sortable·th[data-sort], 이익 성장·퀀트)는 건드리지 않는다.
// 표를 다시 그려도(장중 갱신·필터 변경) 고른 정렬을 다시 적용한다.
(() => {
  const state = {};   // 표 키 → { col, dir }
  const keyOf = t => `${t.closest('[id]')?.id || ''}|${t.className}`;
  const own = t => !!t.querySelector('thead th.sortable, thead th[data-sort]') || t.dataset.nosort != null;

  function value(td) {
    if (!td) return null;
    if (td.dataset.v != null) return td.dataset.v === '' ? null : (isNaN(+td.dataset.v) ? td.dataset.v : +td.dataset.v);
    const main = td.querySelector('b, .qt-p') || td;   // 칸의 대표 숫자 (아래 작은 글씨는 빼고)
    const txt = main.textContent.trim();
    if (!txt || txt === '–' || txt === '-') return null;
    const m = txt.replace(/,/g, '').replace(/−/g, '-').match(/^[^\d+-]{0,6}([+-]?\d+(?:\.\d+)?)\s*(조|억|만|천)?/);
    if (m) {
      let v = parseFloat(m[1]);
      v *= { 조: 1e4, 억: 1, 만: 1e-4, 천: 1e-5 }[m[2]] ?? 1;
      return v;
    }
    return txt;
  }

  function apply(t, col, dir) {
    const body = t.tBodies[0];
    if (!body) return;
    // 구분 줄(칸 하나가 줄 전체를 차지)은 제자리에 두고 그 사이 묶음끼리 정렬
    const rows = [...body.rows], groups = [[]], seps = [];
    for (const r of rows) {
      if (r.cells.length === 1 && r.cells[0].colSpan > 1) { seps.push(r); groups.push([]); } else groups[groups.length - 1].push(r);
    }
    const cmp = (a, b) => {
      const x = value(a.cells[col]), y = value(b.cells[col]);
      if (x == null) return y == null ? 0 : 1;
      if (y == null) return -1;
      if (typeof x === 'number' && typeof y === 'number') return dir === 'desc' ? y - x : x - y;
      if (typeof x === 'number') return -1;
      if (typeof y === 'number') return 1;
      return dir === 'desc' ? String(y).localeCompare(String(x), 'ko') : String(x).localeCompare(String(y), 'ko');
    };
    const frag = document.createDocumentFragment();
    groups.forEach((g, i) => {
      g.sort(cmp).forEach(r => frag.append(r));
      if (seps[i]) frag.append(seps[i]);
    });
    body.append(frag);
    [...t.tHead.rows[0].cells].forEach((th, i) => {
      th.classList.toggle('sorted', i === col);
      th.dataset.dir = i === col ? dir : '';
    });
  }

  document.addEventListener('click', e => {
    const th = e.target.closest('table.tbl thead th');
    if (!th || e.target.closest('a, button, input')) return;
    const t = th.closest('table');
    if (own(t) || th.classList.contains('nosort')) return;
    const col = th.cellIndex;
    const sample = [...(t.tBodies[0]?.rows || [])].map(r => value(r.cells[col])).find(v => v != null);
    const first = typeof sample === 'number' ? 'desc' : 'asc';
    const cur = state[keyOf(t)];
    const dir = cur && cur.col === col ? (cur.dir === 'desc' ? 'asc' : 'desc') : first;
    state[keyOf(t)] = { col, dir };
    apply(t, col, dir);
  });

  // 다시 그려진 표에 고른 정렬을 다시 적용
  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    setTimeout(() => {   // requestAnimationFrame 은 탭이 뒤에 있으면 멈춰서 setTimeout
      queued = false;
      document.querySelectorAll('table.tbl').forEach(t => {
        const s = state[keyOf(t)];
        if (s && !own(t) && !t.tHead?.rows[0]?.cells[s.col]?.classList.contains('sorted')) apply(t, s.col, s.dir);
      });
    }, 0);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
