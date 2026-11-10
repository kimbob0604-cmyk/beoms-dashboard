"""
네이버 수집분 → 화면용 JSON

- public/data/flow/{거래일}.json   수급 탭: 종목별 외국인·기관·개인 순매수 금액(1·5·20·60일), 연속 순매수, 지분율 변화
- public/data/high/{거래일}.json   신고가 탭: build_newhigh.py 가 가격 이력으로 계산 (역사적·52주·120일·60일, 종가 기준)
- public/data/reports/recent.json  컨센 리비전 탭: 최근 30일 리포트의 목표가와 같은 증권사 직전 목표가
- public/data/stocks/{code}.json   종목 상세: 리포트 목록·키워드 정리·목표가 요약·최근 수급

금액은 순매수 수량 × 그날 정규장 종가로 어림한 값이다(억원). 네이버 화면의 금액과 조금 다를 수 있다.
신고가·수급 행에는 이익 성장 JSON(같은 날 이하 가장 최근)의 영업이익 성장률·POR·리비전을 붙인다.

  python3 build_naver.py
"""

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import db
import keywords as K
from build_growth import company_mcaps
from universe import is_common

DATA = Path(__file__).parent / 'public' / 'data'
REPORT_DAYS = 90       # 종목 상세에 보일 리포트 기간
RECENT_DAYS = 30       # 컨센 리비전 탭의 목표가 변경 목록 기간
FLOW_DAYS = (1, 5, 20, 60)

OPINION = {
    'buy': '매수', '매수': '매수', 'strongbuy': '매수', 'outperform': '매수', 'tradingbuy': '매수', 'overweight': '매수',
    '중립': '중립', 'hold': '중립', 'neutral': '중립', 'marketperform': '중립', 'marketweight': '중립',
    '매도': '매도', 'sell': '매도', 'underperform': '매도', 'reduce': '매도', 'underweight': '매도',
}


def opinion(s):
    return OPINION.get((s or '').replace(' ', '').lower())


def eok(vol, price):
    return None if vol is None or not price else round(vol * price / 1e8, 1)


# ------------------------------------------------------------
# 순수 계산 (tests/test_build_naver.py)
# ------------------------------------------------------------

def streak(vals):
    """최신순 순매수 값 → 연속 순매수(+n)·순매도(−n) 일수"""
    n, sign = 0, 0
    for v in vals:
        s = (v or 0) > 0 and 1 or (v or 0) < 0 and -1 or 0
        if s == 0 or (sign and s != sign):
            break
        sign, n = s, n + 1
    return n * sign


def summarize_flow(rows):
    """rows: 한 종목의 flow_daily 최신순 → 기간별 금액 합, 연속 일수, 지분율 변화"""
    out = {}
    amt = {k: [eok(r[k], r['close']) for r in rows] for k in ('frgn', 'org', 'ind')}
    for key, short in (('frgn', 'f'), ('org', 'o'), ('ind', 'i')):
        for d in FLOW_DAYS:
            vals = [v for v in amt[key][:d] if v is not None]
            out[f'{short}{d}'] = round(sum(vals), 1) if len(rows) >= d else None
        out[f'{short}s'] = streak([r[key] for r in rows])
    # 직전 3거래일(오늘 제외) 외국인 순매수 합 — 수급 반전(순매도 → 순매수 전환) 판정용
    out['fp3'] = round(sum(v or 0 for v in amt['frgn'][1:4]), 1) if len(rows) >= 4 else None
    ratios = [r['frgn_ratio'] for r in rows]
    out['fr'] = ratios[0] if ratios else None
    out['frd'] = round(ratios[0] - ratios[20], 2) if len(ratios) > 20 and None not in (ratios[0], ratios[20]) else None
    return out


SIG_MIN = 50        # 억: 쌍끌이·수급 반전에서 당일 순매수(순매도) 하한. 연속은 이 값의 절반
SIG_STREAK = 3      # 외국인 연속 순매수·순매도 최소 일수
SIG_TOP = 6         # 시그널마다 올릴 종목 수


def flow_signals(stocks, min_eok=SIG_MIN, streak_min=SIG_STREAK, top=SIG_TOP):
    """수급 시그널 {종류: [종목코드…]} — 예전 stock-dashboard 의 '수급 시그널' 텔레그램 알림과 같은 규칙.
    dual_buy/dual_sell  쌍끌이: 외국인·기관이 둘 다 min_eok 이상 순매수(순매도). 합이 큰 순
    streak_buy/sell     외국인이 streak_min 일 이상 연속 순매수(순매도)이고 당일 금액이 min_eok 의 절반 이상. 긴 순, 같으면 금액순
    reversal            수급 반전: 직전 3거래일 외국인 합이 순매도였는데 당일 min_eok 이상 순매수. 금액순"""
    rows = [s for s in stocks if s.get('f1') is not None and s.get('o1') is not None]
    half = min_eok / 2
    pick = lambda xs, key: [s['c'] for s in sorted(xs, key=key)[:top]]
    return {
        'dual_buy': pick([s for s in rows if s['f1'] >= min_eok and s['o1'] >= min_eok], lambda s: -(s['f1'] + s['o1'])),
        'dual_sell': pick([s for s in rows if s['f1'] <= -min_eok and s['o1'] <= -min_eok], lambda s: s['f1'] + s['o1']),
        'streak_buy': pick([s for s in rows if s['fs'] >= streak_min and s['f1'] >= half], lambda s: (-s['fs'], -s['f1'])),
        'streak_sell': pick([s for s in rows if s['fs'] <= -streak_min and s['f1'] <= -half], lambda s: (s['fs'], s['f1'])),
        'reversal': pick([s for s in rows if s.get('fp3') is not None and s['fp3'] < 0 and s['f1'] >= min_eok], lambda s: -s['f1']),
    }


def prev_goals(reports):
    """reports: 날짜·id 오름차순 → {id: 같은 증권사·같은 종목의 직전 목표가}"""
    last, out = {}, {}
    for r in reports:
        key = (r['code'], r['broker'])
        out[r['id']] = last.get(key)
        if r['goal']:
            last[key] = r['goal']
    return out


# ------------------------------------------------------------
# 공통
# ------------------------------------------------------------

_growth_cache = {}


def growth_stocks(d):
    """d 이하 가장 최근 이익 성장 JSON 의 종목 목록 (한 번 읽어 둔다)"""
    files = sorted(p for p in (DATA / 'growth').glob('20*.json') if p.stem <= d)
    if not files:
        return []
    if files[-1] not in _growth_cache:
        _growth_cache[files[-1]] = json.loads(files[-1].read_text(encoding='utf-8'))['stocks']
    return _growth_cache[files[-1]]


def growth_extract(d):
    """d 이하 가장 최근 이익 성장 JSON → {code: 영업이익 성장률·구간·POR·1개월 리비전}"""
    out = {}
    for s in growth_stocks(d):
        op = s['k'].get('y0', {}).get('op')
        if op:
            out[s['c']] = {'g': op['g'], 'k': op['k'], 'por': op['mn'], 'r1': op['m1'], 'lb': op['lb']}
    return out


def por_series(s):
    """이익 성장 JSON 의 한 종목 → {'fy0': 올해 결산연도, 'ops': [[연도, 영업이익(억), 추정이면 1]…]} (전년 실적 ~ 내후년 추정).
    화면이 지금 시총 ÷ 연도별 영업이익으로 POR 을 계산한다 (장중 시총이 바뀌어도 맞도록 배수는 싣지 않는다)."""
    ops = [x for x in s['s'].get('op', []) if x[0] >= s['fy0'] - 1 and x[1] is not None]
    return {'fy0': s['fy0'], 'ops': ops} if ops else None


def por_base(d):
    """{code: por_series} — 종목 패널과 탐방 탭의 'POR = 시총 ÷ 영업이익' 표에 쓴다"""
    return {s['c']: v for s in growth_stocks(d) if (v := por_series(s))}


def market_info(conn, d):
    """
    d 시점 종목 정보 {code: name, mk, mc(회사 시총), p, ch, w}.
    KRX 가격은 다음 날 아침에 열려서 d 의 KRX 가격이 아직 없을 수 있다. 그때는 네이버 수급 응답의
    정규장 종가(d 와 그 전 거래일)로 주가·등락률을 채우고 시총도 그 비율로 맞춘다.
    """
    pd = conn.execute('SELECT MAX(date) FROM price_daily WHERE date <= ?', (d,)).fetchone()[0]
    prices = {r['code']: dict(r) for r in conn.execute('SELECT * FROM price_daily WHERE date = ?', (pd,))}
    mcaps = company_mcaps(prices)
    wics = {r['code']: r['wics'] for r in conn.execute('SELECT code, wics FROM stock_meta')}
    info = {c: {'n': p['name'], 'mk': p['market'], 'mc': round(mcaps.get(c, p['mcap'])),
                'p': p['close'], 'ch': p['change_pct'], 'w': wics.get(c), 'pd': pd}
            for c, p in prices.items() if is_common(c)}
    if pd and pd < d:
        last = defaultdict(list)
        for r in conn.execute('SELECT code, date, close FROM flow_daily WHERE date <= ? AND date >= ? '
                              'ORDER BY code, date DESC', (d, pd)):
            last[r['code']].append(r)
        for c, rows in last.items():
            if c not in info or rows[0]['date'] != d or not rows[0]['close'] or len(rows) < 2 or not rows[1]['close']:
                continue
            i = info[c]
            if i['p']:
                i['mc'] = round(i['mc'] * rows[0]['close'] / i['p'])
            i['p'] = rows[0]['close']
            i['ch'] = round((rows[0]['close'] / rows[1]['close'] - 1) * 100, 2)
            i['pd'] = d
    return info, pd


def public(i):
    """화면 JSON 에는 가격 기준일(pd)을 빼고 넣는다"""
    return {k: v for k, v in i.items() if k != 'pd'}


def write_json(path: Path, data):
    """내용이 그대로면(빌드 시각 'built' 만 다르면) 파일을 건드리지 않는다 → 바뀐 게 없으면 배포도 안 한다"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and isinstance(data, dict) and 'built' in data:
        try:
            old = json.loads(path.read_text(encoding='utf-8'))
            if {**old, 'built': None} == {**data, 'built': None}:
                return False
        except ValueError:
            pass
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return False
    path.write_text(text, encoding='utf-8')
    return True


def write_dates(folder: Path):
    dates = sorted((p.stem for p in folder.glob('20*.json')), reverse=True)
    write_json(folder / 'dates.json', dates)


# ------------------------------------------------------------
# 수급
# ------------------------------------------------------------

def flow_by_code(conn, d, limit=max(FLOW_DAYS)):
    rows = defaultdict(list)
    for r in conn.execute('SELECT * FROM flow_daily WHERE date <= ? ORDER BY code, date DESC', (d,)):
        if len(rows[r['code']]) < limit:
            rows[r['code']].append(dict(r))
    return rows


def build_flow(conn, d):
    info, _ = market_info(conn, d)
    gx = growth_extract(d)
    stocks = []
    for code, rows in flow_by_code(conn, d).items():
        if rows[0]['date'] != d or code not in info:   # 그날 수급이 없는 종목(거래정지 등)은 뺀다
            continue
        stocks.append({'c': code, **public(info[code]), **summarize_flow(rows), 'gx': gx.get(code)})
    return {'date': d, 'stocks': stocks, 'sig': flow_signals(stocks), 'sig_min': SIG_MIN, 'sig_streak': SIG_STREAK}


# ------------------------------------------------------------
# 리포트 · 종목 상세
# ------------------------------------------------------------

def report_text(r):
    return '\n'.join([r['title'] or ''] + json.loads(r['heads'] or '[]') + [r['body'] or ''])


def build_reports(conn, d):
    since = (date.fromisoformat(d) - timedelta(days=REPORT_DAYS)).isoformat()
    rows = [dict(r) for r in conn.execute(
        'SELECT * FROM research WHERE date >= ? AND date <= ? ORDER BY date, id', (since, d))]
    pg = prev_goals(rows)
    texts = {r['id']: report_text(r) for r in rows}
    vocab = K.build_vocab(texts.values())
    df = K.doc_freq(K.doc_terms(t, vocab) for t in texts.values())
    n_docs = len(rows)

    by_code = defaultdict(list)
    for r in reversed(rows):   # 최신순
        by_code[r['code']].append(r)

    info, _ = market_info(conn, d)
    gx = growth_extract(d)
    pv = por_base(d)
    flows = flow_by_code(conn, d, limit=20)
    month_ago = (date.fromisoformat(d) - timedelta(days=RECENT_DAYS)).isoformat()

    def slim(r):
        return {'id': r['id'], 'd': r['date'], 'b': r['broker'], 't': r['title'], 'op': opinion(r['opinion']),
                'g': r['goal'], 'pg': pg[r['id']], 'p': r['price']}

    recent = [{**slim(r), 'c': r['code'], 'n': r['name'], 'mk': (info.get(r['code']) or {}).get('mk'),
               'mc': (info.get(r['code']) or {}).get('mc'), 'w': (info.get(r['code']) or {}).get('w'),
               'cp': (info.get(r['code']) or {}).get('p')}
              for r in reversed(rows) if r['date'] >= month_ago]

    stock_files = {}
    for code in set(by_code) | set(flows):
        reps = by_code.get(code, [])
        name = (info.get(code) or {}).get('n') or (reps[0]['name'] if reps else '')
        docs = [{'id': r['id'], 'date': r['date'], 'broker': r['broker'], 'text': texts[r['id']]} for r in reps]
        latest_goal = {}
        for r in reps:   # 증권사별 최신 목표가 (최근 90일)
            if r['goal'] and r['broker'] not in latest_goal:
                latest_goal[r['broker']] = r['goal']
        goals = list(latest_goal.values())
        kws = K.stock_keywords(docs, df, n_docs, vocab, name=name)
        stock_files[code] = {
            'c': code, 'n': name, **{k: v for k, v in public(info.get(code) or {}).items() if k != 'n'},
            'gx': gx.get(code),
            'pv': pv.get(code),
            'tgt': {'avg': round(sum(goals) / len(goals)), 'hi': max(goals), 'lo': min(goals), 'n': len(goals),
                    'up': sum(1 for r in reps if r['goal'] and pg[r['id']] and r['goal'] > pg[r['id']]),
                    'dn': sum(1 for r in reps if r['goal'] and pg[r['id']] and r['goal'] < pg[r['id']])}
                   if goals else None,
            'kws': kws,
            'reports': [{**slim(r), 'h': json.loads(r['heads'] or '[]'),
                         'kw': K.report_keywords(texts[r['id']], df, n_docs, vocab, name=name,
                                                 prefer=[k['kw'] for k in kws]), 'pdf': r['pdf']}
                        for r in reps],
            'flow': [[f['date'], eok(f['frgn'], f['close']), eok(f['org'], f['close']), eok(f['ind'], f['close']),
                      f['close'], f['frgn_ratio']] for f in flows.get(code, [])],
        }
    return {'date': d, 'since': month_ago, 'reports': recent}, stock_files


def main():
    conn = db.connect()
    d = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]

    fd = conn.execute('SELECT MAX(date) FROM flow_daily').fetchone()[0]
    if fd:
        data = build_flow(conn, fd)
        write_json(DATA / 'flow' / f'{fd}.json', data)
        write_dates(DATA / 'flow')
        print(f"flow/{fd}.json: {len(data['stocks'])}종목")

    # 신고가: 가격 이력으로 직접 계산 (build_newhigh.py — 역사적·52주·120일·60일, 종가 기준)
    import build_newhigh
    data = build_newhigh.write_all(conn)
    hd = data['date']
    print(f"high/{hd}.json{' (잠정)' if data['prov'] else ''}: 대상 {data['universe']}종목, 신고가 {len(data['today'])}, 최근 {len(data['recent'])}")

    rd = max(filter(None, [d, fd, hd]))
    recent, stocks = build_reports(conn, rd)
    write_json(DATA / 'reports' / 'recent.json', recent)
    out = DATA / 'stocks'
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob('*.json'):   # 대상에서 빠진 종목 파일은 지운다
        if old.stem not in stocks:
            old.unlink()
    for code, data in stocks.items():
        write_json(out / f'{code}.json', data)
    print(f"reports/recent.json: {len(recent['reports'])}건, stocks/: {len(stocks)}종목")


if __name__ == '__main__':
    main()
