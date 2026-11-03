"""
네이버 수집분 → 화면용 JSON

- public/data/flow/{거래일}.json   수급 탭: 종목별 외국인·기관·개인 순매수 금액(1·5·20·60일), 연속 순매수, 지분율 변화
- public/data/high/{거래일}.json   신고가 탭: 그날 52주 신고가 종목 + 최근 20거래일 안에 신고가를 냈던 종목
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
HIGH_WINDOW = 20       # 최근 신고가 집계 거래일 수
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
    ratios = [r['frgn_ratio'] for r in rows]
    out['fr'] = ratios[0] if ratios else None
    out['frd'] = round(ratios[0] - ratios[20], 2) if len(ratios) > 20 and None not in (ratios[0], ratios[20]) else None
    return out


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

def growth_extract(d):
    """d 이하 가장 최근 이익 성장 JSON → {code: 영업이익 성장률·구간·POR·1개월 리비전}"""
    files = sorted(p for p in (DATA / 'growth').glob('20*.json') if p.stem <= d)
    if not files:
        return {}
    out = {}
    for s in json.loads(files[-1].read_text(encoding='utf-8'))['stocks']:
        op = s['k'].get('y0', {}).get('op')
        if op:
            out[s['c']] = {'g': op['g'], 'k': op['k'], 'por': op['mn'], 'r1': op['m1'], 'lb': op['lb']}
    return out


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


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
    return {'date': d, 'stocks': stocks}


# ------------------------------------------------------------
# 신고가
# ------------------------------------------------------------

def build_high(conn, d):
    info, _ = market_info(conn, d)
    gx = growth_extract(d)
    flows = flow_by_code(conn, d, limit=20)
    days = [r[0] for r in conn.execute(
        'SELECT DISTINCT date FROM high52_daily WHERE date <= ? ORDER BY date DESC LIMIT ?', (d, HIGH_WINDOW))]
    hits = defaultdict(list)   # code → [(date, close)] 최신순
    snap = {}                  # code → 가장 최근 신고가 행
    for r in conn.execute(f"SELECT * FROM high52_daily WHERE date IN ({','.join('?' * len(days))}) "
                          'ORDER BY date DESC', days):
        hits[r['code']].append((r['date'], r['close']))
        snap.setdefault(r['code'], dict(r))

    def row(code):
        h = hits[code]
        sn = snap[code]
        base = dict(info.get(code) or {'n': sn['name'], 'mk': sn['market'], 'mc': round(sn['mcap'] or 0),
                                       'p': None, 'ch': None, 'w': None, 'pd': None})
        if base['pd'] != d and sn['date'] == d:   # 그날 KRX·수급 가격이 없으면 신고가 목록의 가격
            base.update(p=sn['close'], ch=sn['change_pct'])
        base = public(base)
        run = 0
        for day in days:   # 오늘부터 거꾸로 연속 신고가 일수
            if day in {x[0] for x in h}:
                run += 1
            else:
                break
        f = summarize_flow(flows[code]) if flows.get(code) else {}
        return {'c': code, **base, 'n20': len(h), 'run': run, 'last': h[0][0], 'hp': h[0][1],
                'first': h[-1][0], 'f5': f.get('f5'), 'o5': f.get('o5'), 'gx': gx.get(code)}

    today = [row(c) for c, h in hits.items() if h[0][0] == d]
    recent = [row(c) for c, h in hits.items() if h[0][0] != d]
    at = conn.execute('SELECT MAX(fetched_at) FROM high52_daily WHERE date = ?', (d,)).fetchone()[0]
    return {'date': d, 'at': at, 'days': len(days), 'from': days[-1] if days else None, 'today': today, 'recent': recent}


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

    hd = conn.execute('SELECT MAX(date) FROM high52_daily').fetchone()[0]
    if hd:
        data = build_high(conn, hd)
        write_json(DATA / 'high' / f'{hd}.json', data)
        write_dates(DATA / 'high')
        print(f"high/{hd}.json: 오늘 {len(data['today'])}, 최근 {len(data['recent'])} ({data['days']}거래일 기록)")

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
