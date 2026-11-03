// 탭 공통: 숫자 포맷, 테마, JSON 로딩
const U = (() => {
  const DOW = '일월화수목금토';
  const cache = {};

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
    esc(s) {
      return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    },
    async json(url) {
      if (!cache[url]) {
        // no-cache: 매번 서버에 바뀌었는지 확인(바뀌지 않았으면 304로 가볍게). 새로고침하면 바로 최신 데이터.
        cache[url] = fetch(url, { cache: 'no-cache' }).then(r => {
          if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
          return r.json();
        });
        cache[url].catch(() => delete cache[url]);
      }
      return cache[url];
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
      return pg.state.date;
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
