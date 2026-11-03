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
        cache[url] = fetch(url).then(r => {
          if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
          return r.json();
        });
        cache[url].catch(() => delete cache[url]);
      }
      return cache[url];
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
