"""
홈 탭 JSON: public/data/home.json

다른 탭이 이미 만든 JSON(이익 성장·수급·신고가·리포트)과 DB(가격·지수)에서 오늘 볼 것만 골라 한 파일로 묶는다.
- idx      코스피·코스닥·코스피200 선물(최근월물) 종가·등락률, 그날 투자자별·프로그램 순매수(억원), 상승/하락 종목 수,
           당일 1분봉(min)·장중 순매수 스냅샷(snap)·1년 일봉(ohlc, 열 단위 배열)
- live     장중이면 전 종목 시세를 받은 시각 (그때 big·movers·sectors·breadth 는 장중 시세 기준)
- sectors  WICS 업종별 시총 가중 등락률 (5종목 이상 업종 전부, 업종 시총 상위 3종목 포함)
- big      회사 시총 상위 BIG 종목 등락 (홈 지도)
- movers   시총 3,000억 이상 중 상승률·하락률 상위
- rev      내년 영업이익 추정치 1주 상향·하향 상위 (이익 성장 JSON)
- tgt      최근 1주 목표가 상향·하향 (같은 증권사 직전 목표가 대비)
- flow     외국인+기관 1일 순매수·순매도 상위 (수급 JSON)
- high     그날 52주 신고가 (시총 순)
- reports  최신 리포트
- mab      시장 폭: 20·60·120일 이동평균 위에 있는 종목 비율(%) 최근 120거래일 (코스피·코스닥)
- spike    거래대금 급증: 20일 평균 대비 3배 이상 (시총 500억·평균 5억 이상). 장중이면 그때까지의 거래대금
- sectors·big 의 w1·m1·m3: 1주·1개월·3개월 수익률(%) (업종은 시총 가중)
- quotes.json 전 종목 [가격, 등락률] + _d 시세 날짜·_t 장중 시각 (관심종목 카드·종목 패널 장중 시세용)
- dart     최근 공시일의 눈에 띄는 공시 (잠정실적 서프·쇼크, 큰 수주, 최대주주 변경, 큰 자사주 소각·취득, 자금조달)

build_growth.py · build_naver.py · build_dart.py 뒤에 돌린다.

  python3 build_home.py
"""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta

import db
from build_naver import DATA, market_info, public, write_json

TOP = 5
BIG = 60
SECTOR_MIN = 5          # 업종 등락에 넣을 최소 종목 수
MOVER_MIN_MCAP = 3000   # 억원
FLAT = 0.001            # 리비전 ±0.1% 미만은 변화 없음
TGT_DAYS = 7            # 목표가 변경을 모을 기간(일, 컨센 리비전 탭 기본값과 같게)


def latest_json(folder: str):
    dates = sorted((p.stem for p in (DATA / folder).glob('20*.json')), reverse=True)
    return json.loads((DATA / folder / f'{dates[0]}.json').read_text(encoding='utf-8')) if dates else None


def slim(s, **extra):
    """종목 행 공통 필드 (패널 열기용 힌트 포함)"""
    return {'c': s['c'], 'n': s['n'], 'mk': s.get('mk'), 'mc': s.get('mc'), 'p': s.get('p'), 'ch': s.get('ch'),
            'w': s.get('w'), **extra}


def build_index(conn):
    out = []
    for code, name in (('KOSPI', '코스피'), ('KOSDAQ', '코스닥'), ('FUT', '코스피200 선물')):
        rows = [dict(r) for r in conn.execute(
            'SELECT * FROM index_daily WHERE code = ? ORDER BY date DESC LIMIT 60', (code,))]
        if not rows:
            continue
        last = rows[0]
        flow = next((r for r in rows if r['frgn'] is not None), None)
        out.append({
            'c': code, 'n': name, 'd': last['date'], 'v': last['close'], 'ch': last['change_pct'],
            'fd': flow and flow['date'], 'at': flow and flow['fetched_at'],
            'f': flow and flow['frgn'], 'o': flow and flow['org'], 'i': flow and flow['ind'], 'pg': flow and flow['prog'],
            'up': flow and flow['up'], 'dn': flow and flow['down'], 'fl': flow and flow['flat'],
            'prev': rows[1]['close'] if len(rows) > 1 else None,
            'min': [[r['t'], r['price']] for r in conn.execute(
                'SELECT t, price FROM index_minute WHERE code = ? AND date = ? ORDER BY t', (code, last['date']))],
            'snap': [[r['t'], r['frgn'], r['org'], r['ind'], r['prog']] for r in conn.execute(
                'SELECT * FROM index_snap WHERE code = ? AND date = ? ORDER BY t', (code, last['date']))],
            'ohlc': ohlc_cols(conn, code),
        })
    return out


def ohlc_cols(conn, code):
    rows = list(conn.execute('SELECT * FROM index_ohlc WHERE code = ? ORDER BY date DESC LIMIT 260', (code,)))[::-1]
    return {'d': [int(r['date'].replace('-', '')) for r in rows], 'o': [r['open'] for r in rows],
            'h': [r['high'] for r in rows], 'l': [r['low'] for r in rows], 'c': [r['close'] for r in rows],
            'v': [r['volume'] for r in rows]}


def apply_live(conn, info, pd):
    """장중: price_daily 보다 새 날짜의 장중 시세가 있으면 가격·등락률·시총을 그 값으로. 받은 시각을 돌려준다."""
    q = {r['code']: r for r in conn.execute('SELECT * FROM quote_live WHERE date > ?', (pd or '',))}
    if not q:
        return None
    for c, i in info.items():
        r = q.get(c)
        if r and r['close']:
            if i['p'] and i['mc']:
                i['mc'] = round(i['mc'] * r['close'] / i['p'])
            i['p'], i['ch'] = r['close'], r['change_pct']
    return max(r['at'] for r in q.values())


def build_sectors(info):
    acc = defaultdict(lambda: [0.0, 0.0, []])   # 시총×등락, 시총, 종목
    for c, i in info.items():
        if i['w'] and i['ch'] is not None and i['mc']:
            a = acc[i['w']]
            a[0] += i['mc'] * i['ch']
            a[1] += i['mc']
            a[2].append({'c': c, **i})
    secs = []
    for w, (s, m, members) in acc.items():
        if len(members) < SECTOR_MIN:
            continue
        members.sort(key=lambda x: -x['mc'])
        per = {}
        for key in PERIODS:   # 기간 수익률도 시총 가중 (값 있는 종목만)
            xs = [(x['mc'], x[key]) for x in members if x.get(key) is not None]
            if xs:
                per[key] = round(sum(a * b for a, b in xs) / sum(a for a, _ in xs), 2)
        secs.append({'w': w, 'ch': round(s / m, 2), 'k': len(members), 'mc': round(m), **per,
                     'top': [slim(x, **{k: x.get(k) for k in PERIODS}) for x in members[:3]]})
    secs.sort(key=lambda x: -x['ch'])
    return {'all': secs, 'n': len(secs)}


def build_rev(growth):
    rows = []
    for s in growth['stocks']:
        op = (s.get('k') or {}).get('y0', {}).get('op')
        if op and op.get('w1') is not None and op.get('n') is not None:
            rows.append(slim(s, r=op['w1'], now=op['n']))
    up = sorted((r for r in rows if r['r'] >= FLAT), key=lambda r: -r['r'])
    dn = sorted((r for r in rows if r['r'] <= -FLAT), key=lambda r: r['r'])
    return {'fy': growth['fy0'] + 1, 'cns': growth['cns_date'], 'nup': len(up), 'ndn': len(dn),
            'up': up[:TOP], 'dn': dn[:TOP]}


def build_tgt(recent):
    """최근 TGT_DAYS 일(마지막 리포트일 포함) 목표가 변경. 같은 증권사 직전 목표가가 있는 리포트만 비교된다."""
    reps = recent['reports']
    if not reps:
        return None
    d = max(r['d'] for r in reps)
    since = (date.fromisoformat(d) - timedelta(days=TGT_DAYS - 1)).isoformat()
    win = [r for r in reps if r['d'] >= since]
    row = lambda r: {**slim(r), 'id': r['id'], 'd': r['d'], 'b': r['b'], 'g': r['g'], 'pg': r['pg'],
                     'r': r['g'] / r['pg'] - 1, 'p': r.get('cp') or r.get('p')}
    cmp = [r for r in win if r.get('g') and r.get('pg')]
    up = sorted((row(r) for r in cmp if r['g'] > r['pg']), key=lambda x: -x['r'])
    dn = sorted((row(r) for r in cmp if r['g'] < r['pg']), key=lambda x: x['r'])
    return {'d': d, 'since': since, 'n': len(win), 'nup': len(up), 'ndn': len(dn), 'up': up[:TOP], 'dn': dn[:TOP]}


def build_flow(flow):
    rows = [s for s in flow['stocks'] if s.get('f1') is not None and s.get('o1') is not None]
    fo = lambda s: s['f1'] + s['o1']
    buy = sorted((s for s in rows if fo(s) > 0), key=lambda s: -fo(s))
    sell = sorted((s for s in rows if fo(s) < 0), key=fo)
    pick = lambda s: slim(s, f=s['f1'], o=s['o1'])
    return {'d': flow['date'], 'buy': [pick(s) for s in buy[:TOP]], 'sell': [pick(s) for s in sell[:TOP]]}


def build_high(high):
    today = sorted(high['today'], key=lambda s: -(s.get('mc') or 0))
    return {'d': high['date'], 'at': high.get('at'), 'n': len(today),
            'list': [slim(s, run=s.get('run')) for s in today[:8]]}


def dart_rank(x):
    """홈에 올릴 공시면 우선순위(작을수록 먼저), 아니면 None"""
    d, k = x.get('d') or {}, x['k']
    if x.get('fx'):   # 정정 공시는 빼고
        return None
    amt = lambda: (d.get('amt') or 0) / 1e8   # 억
    if k == 'earn' and (x.get('s') or {}).get('tag'):
        return 0
    if k == 'holder':
        return 1
    if k == 'contract' and ((d.get('pct') or 0) >= 10 or amt() >= 500):
        return 2
    if k in ('cancel', 'buyback', 'trust') and amt() >= 100:
        return 3
    if k in ('cb', 'bw', 'eb', 'rights') and amt() >= 100:
        return 4
    if k == 'biz':
        return 5
    return None


def build_dart():
    dates_path = DATA / 'dart' / 'dates.json'
    if not dates_path.exists():
        return None
    dates = json.loads(dates_path.read_text())
    if not dates:
        return None
    day = json.loads((DATA / 'dart' / f'{dates[0]}.json').read_text(encoding='utf-8'))
    picks = [(dart_rank(x), x) for x in day['items']]
    picks = sorted((p for p in picks if p[0] is not None), key=lambda p: (p[0], -(p[1].get('mc') or 0)))
    earn = [x for x in day['items'] if x['k'] == 'earn']
    return {'d': day['date'], 'n': len(day['items']), 'earn': len(earn),
            'sp': sum((x.get('s') or {}).get('tag') == '서프' for x in earn),
            'sk': sum((x.get('s') or {}).get('tag') == '쇼크' for x in earn),
            'items': ([x for r, x in picks if r == 0][:4] + [x for r, x in picks if r != 0])[:8],   # 실적은 4개까지
            'next': [e for e in day['schedule'] if e['earn'] and e['date'] > day['date']][:30]}


PERIODS = {'w1': 5, 'm1': 21, 'm3': 63}   # 거래일
MA_WINDOWS = (20, 60, 120)
MAB_DAYS = 120
SPIKE_X, SPIKE_MCAP, SPIKE_AVG = 3.0, 500, 5   # 배, 억원, 억원


def period_returns(conn, info, price_date):
    """{code: {'w1': %, 'm1': %, 'm3': %}} — 현재가(장중이면 장중 시세) 대 N거래일 전 종가"""
    dates = [r[0] for r in conn.execute('SELECT DISTINCT date FROM ohlc_daily ORDER BY date DESC LIMIT 70')]
    shift = 1 if dates and price_date > dates[0] else 0   # 오늘 일봉이 아직 없으면 하루 덜 거슬러 간다
    out = defaultdict(dict)
    for key, k in PERIODS.items():
        if len(dates) <= k - shift:
            continue
        base = dict(conn.execute('SELECT code, close FROM ohlc_daily WHERE date = ?', (dates[k - shift],)).fetchall())
        for c, i in info.items():
            b = base.get(c)
            if b and i.get('p'):
                out[c][key] = round((i['p'] / b - 1) * 100, 2)
    return out


def ma_breadth(conn, markets):
    """날짜별로 N일 이동평균 위에 있는 종목 비율 (그날 종가와 이동평균이 다 있는 종목 중)"""
    dates = [r[0] for r in conn.execute('SELECT DISTINCT date FROM ohlc_daily ORDER BY date')]
    if len(dates) < max(MA_WINDOWS):
        return None
    pos = {d: i for i, d in enumerate(dates)}
    n = len(dates)
    closes = defaultdict(lambda: [None] * n)
    for code, d, c in conn.execute('SELECT code, date, close FROM ohlc_daily'):
        if code in markets:
            closes[code][pos[d]] = c
    start = n - MAB_DAYS
    above = {m: {w: [0] * MAB_DAYS for w in MA_WINDOWS} for m in ('KOSPI', 'KOSDAQ')}
    total = {m: {w: [0] * MAB_DAYS for w in MA_WINDOWS} for m in ('KOSPI', 'KOSDAQ')}
    for code, xs in closes.items():
        m = markets[code]
        if m not in above:
            continue
        ps, pc = [0.0], [0]   # 누적합, 값 있는 날 수
        for x in xs:
            ps.append(ps[-1] + (x or 0))
            pc.append(pc[-1] + (x is not None))
        for t in range(max(start, 0), n):
            if xs[t] is None:
                continue
            for w in MA_WINDOWS:
                if t + 1 < w or pc[t + 1] - pc[t + 1 - w] < w:
                    continue
                ma = (ps[t + 1] - ps[t + 1 - w]) / w
                total[m][w][t - start] += 1
                above[m][w][t - start] += xs[t] > ma
    pct = lambda a, b: round(a / b * 100, 1) if b else None
    return {'d': [int(d.replace('-', '')) for d in dates[start:]],
            **{m: {str(w): [pct(a, b) for a, b in zip(above[m][w], total[m][w])] for w in MA_WINDOWS} for m in above}}


def trd_spike(conn, info, live):
    """거래대금이 20일 평균의 SPIKE_X 배 이상인 종목"""
    dates = [r[0] for r in conn.execute('SELECT DISTINCT date FROM price_daily ORDER BY date DESC LIMIT 21')]
    if len(dates) < 16:
        return None
    if live:   # 장중: 오늘 거래대금은 장중 시세, 평균은 최근 20거래일
        cur = dict(conn.execute('SELECT code, trd_val FROM quote_live').fetchall())
        prev, day = dates[:20], None
    else:
        cur = dict(conn.execute('SELECT code, trd_val FROM price_daily WHERE date = ?', (dates[0],)).fetchall())
        prev, day = dates[1:21], dates[0]
    sums, cnt = defaultdict(float), defaultdict(int)
    q = f"SELECT code, trd_val FROM price_daily WHERE date IN ({','.join('?' * len(prev))})"
    for code, v in conn.execute(q, prev):
        if v:
            sums[code] += v
            cnt[code] += 1
    rows = []
    for c, i in info.items():
        if c not in cur or not cur[c] or cnt[c] < 15 or (i.get('mc') or 0) < SPIKE_MCAP:
            continue
        avg = sums[c] / cnt[c]
        if avg >= SPIKE_AVG and cur[c] >= avg * SPIKE_X:
            rows.append(slim({'c': c, **i}, x=round(cur[c] / avg, 1), tv=round(cur[c]), av=round(avg)))
    rows.sort(key=lambda r: -r['x'])
    return {'d': day, 'live': bool(live), 'n': len(rows), 'list': rows[:10]}


def build(conn) -> dict:
    d = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    info, pd = market_info(conn, d)
    live = apply_live(conn, info, pd)
    price_date = conn.execute('SELECT MAX(date) FROM quote_live').fetchone()[0] if live else pd
    rets = period_returns(conn, info, price_date or pd)
    info = {c: {**public(i), **rets.get(c, {})} for c, i in info.items()}
    # _d: 시세 날짜, _t: 장중이면 받은 시각 (종목 패널이 하루 한 번 빌드한 종가보다 새 시세인지 가린다)
    write_json(DATA / 'quotes.json', {'_d': price_date or pd, '_t': live,
                                      **{c: [i['p'], i['ch']] for c, i in info.items() if i.get('p') is not None}})
    commons = [{'c': c, **i} for c, i in info.items() if i['mc'] and i['ch'] is not None]
    big = sorted(commons, key=lambda s: -s['mc'])[:BIG]
    movers = [s for s in commons if s['mc'] >= MOVER_MIN_MCAP]
    out = {
        'date': d, 'built': datetime.now().isoformat(timespec='seconds'), 'live': live,
        'idx': build_index(conn),
        'breadth': {m: {'up': sum(s['ch'] > 0 for s in commons if s['mk'] == m),
                        'dn': sum(s['ch'] < 0 for s in commons if s['mk'] == m),
                        'fl': sum(s['ch'] == 0 for s in commons if s['mk'] == m)} for m in ('KOSPI', 'KOSDAQ')},
        'sectors': build_sectors(info),
        'mab': ma_breadth(conn, {c: i['mk'] for c, i in info.items()}),
        'spike': trd_spike(conn, info, live),
        'big': [slim(s, **{k: s.get(k) for k in PERIODS}) for s in big],
        'movers': {'up': [slim(s) for s in sorted(movers, key=lambda s: -s['ch'])[:8]],
                   'dn': [slim(s) for s in sorted(movers, key=lambda s: s['ch'])[:8]]},
    }
    growth, flow, high = latest_json('growth'), latest_json('flow'), latest_json('high')
    recent_path = DATA / 'reports' / 'recent.json'
    recent = json.loads(recent_path.read_text(encoding='utf-8')) if recent_path.exists() else None
    out['rev'] = growth and build_rev(growth)
    out['tgt'] = recent and build_tgt(recent)
    out['flow'] = flow and build_flow(flow)
    out['high'] = high and build_high(high)
    out['dart'] = build_dart()
    out['reports'] = recent and [{**slim(r), 'id': r['id'], 'd': r['d'], 'b': r['b'], 't': r['t'], 'op': r.get('op'),
                                  'g': r.get('g'), 'pg': r.get('pg')} for r in recent['reports'][:10]]
    return out


def main():
    conn = db.connect()
    data = build(conn)
    write_json(DATA / 'home.json', data)
    print(f"home.json: {data['date']} · 지수 {len(data['idx'])} · 업종 {data['sectors']['n']} · "
          f"신고가 {data['high']['n'] if data['high'] else 0}")


if __name__ == '__main__':
    main()
