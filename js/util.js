// 탭 공통: 숫자 포맷, 테마, JSON 로딩
const U = (() => {
  const DOW = '일월화수목금토';
  const cache = {}, last = {};

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
        cache[url] = fetch(U.bust(url), { cache: 'no-store' }).then(async r => {
          if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
          const text = await r.text();
          last[url] = text;
          return JSON.parse(text);
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
      const data = JSON.parse(text);
      cache[url] = Promise.resolve(data);
      return data;
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
    async dates(folder, pg, sel, onPick) {
      const ds = await U.json(`data/${folder}/dates.json`);
      if (!ds.length) throw new Error('빌드된 날짜 없음');
      pg.latest = ds[0];
      if (!ds.includes(pg.state.date)) pg.state.date = ds[0];
      sel.innerHTML = ds.map(d => `<option value="${d}"${d === pg.state.date ? ' selected' : ''}>${U.dateLabel(d)} 기준</option>`).join('');
      sel.addEventListener('change', e => { pg.state.date = e.target.value; pg.write(); onPick(e.target.value); });
      // 보고 있는 날짜가 최신이면 같은 날 장중 갱신(신고가·수급·공시 등)도 받아 다시 그린다
      U.watch(folder, ds[0], async () => {
        if (pg.state.date !== ds[0]) return;
        try {
          if (await U.fresh(`data/${folder}/${ds[0]}.json`)) onPick(ds[0]);
        } catch (e) { /* 다음 확인 때 */ }
      });
      return pg.state.date;
    },
    // 열어 둔 화면: 5분마다, 그리고 탭으로 돌아올 때 더 새 날짜가 올라왔는지 보고 알려 준다
    watch(folder, latest, onSame) {
      const check = async () => {
        if (document.hidden) return;
        try {
          const ds = await (await fetch(U.bust(`data/${folder}/dates.json`, 1), { cache: 'no-store' })).json();
          if (ds[0] && ds[0] > latest) {
            U.toast(`${U.dateLabel(ds[0])} 데이터가 새로 올라왔습니다`, '보기', () => {
              const q = new URLSearchParams(location.search);
              q.delete('date');
              location.href = `${location.pathname}${q.toString() ? `?${q}` : ''}${location.hash}`;
            });
          } else if (onSame) onSame();
        } catch (e) { /* 다음 확인 때 */ }
      };
      setInterval(() => { if (U.busyHours()) check(); }, 180000);
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
    // 맥이 새 데이터를 올리는 시간대 (평일 07:00~21:30, 저녁 20:40 실행 포함): 이때만 열어 둔 화면을 자주 확인한다
    busyHours() {
      const { dow, min } = U.kst();
      return dow > 0 && dow < 6 && min >= 420 && min <= 1290;
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
