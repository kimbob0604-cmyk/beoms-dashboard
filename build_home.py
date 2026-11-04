"""
홈 탭 JSON: public/data/home.json

다른 탭이 이미 만든 JSON(이익 성장·수급·신고가·리포트)과 DB(가격·지수)에서 오늘 볼 것만 골라 한 파일로 묶는다.
- idx      코스피·코스닥 종가·등락률, 그날 투자자별·프로그램 순매수(억원), 상승/하락 종목 수,
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

build_growth.py · build_naver.py 뒤에 돌린다.

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
    for code, name in (('KOSPI', '코스피'), ('KOSDAQ', '코스닥')):
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
        secs.append({'w': w, 'ch': round(s / m, 2), 'k': len(members), 'mc': round(m),
                     'top': [slim(x) for x in members[:3]]})
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


def build(conn) -> dict:
    d = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    info, pd = market_info(conn, d)
    live = apply_live(conn, info, pd)
    info = {c: public(i) for c, i in info.items()}
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
        'big': [slim(s) for s in big],
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
