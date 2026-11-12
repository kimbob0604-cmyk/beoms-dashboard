"""
실적 발표 덱 JSON: public/data/earn/{발표일}.json (그날 카드) · stats.json (과거 반응 평균) · dates.json

- 이벤트 = 예상치가 있는 그 분기 실적의 첫 발표 (잠정실적, 또는 잠정 없이 낸 정기보고서). 정정·재게시는 뺀다
- 판정: earn.tag / earn.case_of (매출 ±5%, 영업이익 ±10%·흑적자 전환)
- 반응: 분봉(최근 1년, earn.minute_reaction) · 일봉(2021~, earn.daily_reaction — 같은 시장 지수 차감)

  python3 build_earn.py
"""

import json
import sqlite3
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta

import earn
from build_naver import DATA, write_json
from collect_earn import DB, HIST, MAIN, connect, trading_days

OUT = DATA / 'earn'
CARD_DAYS = 370            # 카드(분봉 차트)를 둘 기간
PATH_LO, PATH_HI, PATH_STEP = -30, 120, 5
REP = [('잠정', '잠정'), ('분기보고서', '분기'), ('반기보고서', '반기'), ('사업보고서', '사업')]


def rep_short(r):
    return next((v for k, v in REP if k in (r or '')), '기타')


def pick_events(rows):
    """글 → 이벤트. 같은 종목·같은 분기(분기를 모르면 5일 안)는 첫 발표 하나 (몇 분 안에 연결·별도가 같이 나오면 연결)"""
    rows = sorted(rows, key=lambda p: p['ts'])
    prelim_at = defaultdict(list)
    for p in rows:
        if '잠정' in (p['report'] or ''):
            prelim_at[p['code']].append(p['ts'])
    out, seen = [], {}
    for p in rows:
        if not p['code'] or (p['se'] is None and p['oe'] is None):
            continue
        fr = earn.first_release(p)
        if fr is False:
            continue
        if fr is None:   # 예전 형식 정기보고서: 앞 75일 안에 잠정실적이 있었으면 재게시
            lo = (datetime.fromisoformat(p['ts']) - timedelta(days=75)).isoformat(' ')
            if any(lo <= t < p['ts'] for t in prelim_at[p['code']]):
                continue
        key = (p['code'], p['period'] or p['ts'][:7])
        prev = seen.get(key)
        if prev is not None:
            e = out[prev]
            close = (datetime.fromisoformat(p['ts']) - datetime.fromisoformat(e['ts'])).total_seconds() < 600
            if close and '연결' in (p['report'] or '') and '연결' not in (e['report'] or ''):
                out[prev] = {**p, 'ts': e['ts']}
            continue
        seen[key] = len(out)
        out.append(dict(p))
    return out


def load_daily(codes, since):
    """{code: (adj{date: 수정종가}, open{date}, close{date}, market)} — history.db + 최근 며칠은 dashboard.db"""
    from newhigh import chain
    h = sqlite3.connect(f'file:{HIST}?mode=ro', uri=True)
    m = sqlite3.connect(f'file:{MAIN}?mode=ro', uri=True)
    hmax = h.execute('SELECT MAX(date) FROM hp').fetchone()[0] or ''
    market = dict(h.execute('SELECT code, market FROM hname'))
    out = {}
    q = ','.join('?' * len(codes))
    rows = defaultdict(list)
    for r in h.execute(f'SELECT code, date, open, close, chg FROM hp WHERE date >= ? AND code IN ({q}) ORDER BY code, date', (since, *codes)):
        rows[r[0]].append(r[1:])
    for r in m.execute(f'SELECT code, date, open, close, chg FROM ohlc_daily WHERE date > ? AND code IN ({q}) ORDER BY code, date', (hmax, *codes)):
        rows[r[0]].append(r[1:])
    for code, rs in rows.items():
        rs = [r for r in rs if r[2]]
        adj = chain([(r[2], r[3]) for r in rs])
        out[code] = ({r[0]: a for r, a in zip(rs, adj)}, {r[0]: r[1] for r in rs}, {r[0]: r[2] for r in rs}, market.get(code))
    idx = defaultdict(dict)
    for c, d, v in h.execute('SELECT code, date, close FROM hidx WHERE date >= ?', (since,)):
        idx[c][d] = v
    for d, c, v in m.execute('SELECT date, code, close FROM index_daily WHERE date > ?', (hmax,)):
        idx[c][d] = v
    return out, idx


def r4(v):
    return None if v is None else round(v, 4)


def card(e, mins, days):
    """화면 카드. 분봉이 있으면 미니 차트(5분)와 분봉 반응"""
    d0 = e['ts'][:10]
    b0 = mins.get((e['code'], d0)) or []
    b1 = mins.get((e['code'], e['rd'])) if e['ss'] == '장후' and e['rd'] else []
    prev_close = None
    if e['ss'] == '장전' and e['rd']:
        i = bisect_left(days, e['rd'])
        pb = mins.get((e['code'], days[i - 1])) if i else None
        reg = earn.regular(pb or [])
        prev_close = reg[-1][1] if reg else e['dr_prev']
    if e['ss'] == '장전' and e['rd'] != d0:      # 휴장일 발표: 반응일 분봉이 차트·반응
        b0 = mins.get((e['code'], e['rd'])) or []
    mr = earn.minute_reaction(e['ts'], e['ss'], b0, b1 or [], prev_close) if b0 else {}
    chart = None
    if b0:
        pts = [[0, hm, c] for hm, c in earn.sample(earn.active(b0))] + [[1, hm, c] for hm, c in earn.sample(earn.active(b1 or []))]
        hm = e['ts'][11:13] + e['ts'][14:16]
        at = 0 if e['ss'] == '장전' and e['rd'] != d0 else next((i for i, p in enumerate(pts) if p[0] == 0 and p[1] >= hm), len(pts) - 1)
        chart = {'p': pts, 'at': at, 'base': mr.get('base')}
    return {'c': e['code'], 'n': e['name'], 'mk': e['mk'], 'mc': e['mcap'], 'ts': e['ts'], 'ss': e['ss'], 'rd': e['rd'],
            'rep': rep_short(e['report']), 'per': e['period'], 'rcp': e['rcp'],
            's': e['s'], 'se': e['se'], 'sr': r4(e['sr']), 'st': e['st'], 'o': e['o'], 'oe': e['oe'], 'or': r4(e['or']), 'ot': e['ot'],
            'np': e['n'], 'npe': e['ne'], 'case': e['case'],
            'mr': {k: r4(v) for k, v in mr.items() if k != 'base'} or None, 'dr': {k: r4(v) for k, v in e['dr'].items()} or None,
            'ch': chart, 'path': earn.path(e['ts'], b0, PATH_LO, PATH_HI, PATH_STEP) if e['ss'] == '장중' and b0 else None}


def stats(evs):
    """묶음 × 시간대 → 지표별 요약. 'all' 시간대 = 전부"""
    keys_d = ['gap', 'd0', 'd1', 'd5', 'd20', 'x0', 'x1', 'x5', 'x20']
    keys_m = ['m5', 'm30', 'm60', 'nxt', 'open', 'close']
    out = {}
    for case, _ in earn.CASES:
        out[case] = {}
        for ss in ('all', '장전', '장중', '장후'):
            xs = [e for e in evs if e['case'] == case and (ss == 'all' or e['ss'] == ss)]
            if not xs:
                continue
            row = {'n': len(xs)}
            for k in keys_d:
                row[k] = earn.summarize([e['dr'].get(k) for e in xs])
            mx = [e for e in xs if e.get('mr')]
            row['nm'] = len(mx)
            for k in keys_m:
                row['m_' + k] = earn.summarize([e['mr'].get(k) for e in mx])
            out[case][ss] = row
    return out


def avg_paths(cards):
    """장중 발표의 발표 전후 평균 경로 (묶음별, %)"""
    T = list(range(PATH_LO, PATH_HI + 1, PATH_STEP))
    out = {}
    for case, _ in earn.CASES:
        ps = [c['path'] for c in cards if c['case'] == case and c.get('path')]
        if not ps:
            continue
        avg = []
        for i in range(len(T)):
            v = [max(-30, min(30, p[i])) for p in ps if p[i] is not None]
            avg.append(round(sum(v) / len(v), 2) if len(v) >= 3 else None)
        out[case] = {'n': len(ps), 'v': avg}
    return {'t': T, 'cases': out}


def build():
    conn = connect()
    days = trading_days()
    posts = [dict(r) for r in conn.execute('SELECT * FROM earn_post ORDER BY ts')]
    evs = pick_events(posts)
    codes = sorted({e['code'] for e in evs})
    since = (date.fromisoformat(evs[0]['ts'][:10]) - timedelta(days=10)).isoformat() if evs else '2021-01-01'
    daily, idx = load_daily(codes, since) if codes else ({}, {})
    hdays = [d for d in days if d <= max((max(v[0]) for v in daily.values() if v[0]), default='')] or days
    for e in evs:
        e['st'], e['ot'] = earn.tag(e['s'], e['se'], earn.SALES_T), earn.tag(e['o'], e['oe'], earn.OP_T)
        e['sr'], e['or'] = earn.ratio(e['s'], e['se']), earn.ratio(e['o'], e['oe'])
        e['case'] = earn.case_of(e['st'], e['ot'])
        e['rd'], e['ss'] = earn.reaction_day(e['ts'], days)
        adj, op, cl, mk = daily.get(e['code'], ({}, {}, {}, None))
        e['mk'] = mk
        ix = idx.get(mk or 'KOSPI', {})
        e['dr'] = earn.daily_reaction(adj, op, cl, ix, hdays, e['rd']) if e['rd'] else {}
        i = bisect_left(hdays, e['rd'] or '')
        e['dr_prev'] = cl.get(hdays[i - 1]) if 0 < i <= len(hdays) else None
    evs = [e for e in evs if e['case']]

    cut = (date.today() - timedelta(days=CARD_DAYS)).isoformat()
    recent = [e for e in evs if e['ts'][:10] >= cut]
    keys = {(e['code'], d) for e in recent for d in {e['ts'][:10], e['rd']} if d}
    mins = {}
    for r in conn.execute('SELECT code, date, bars FROM minute_day WHERE date >= ?', (cut,)):
        if (r[0], r[1]) in keys:
            mins[(r[0], r[1])] = json.loads(r[2])
    # 휴장일 장전 발표의 전 거래일 종가용 분봉도
    cards = [card(e, mins, days) for e in recent]
    for e, c in zip(recent, cards):
        e['mr'] = c['mr'] or {}
    for e in evs:
        e.setdefault('mr', {})

    OUT.mkdir(parents=True, exist_ok=True)
    by_day = defaultdict(list)
    for c in cards:
        by_day[c['ts'][:10]].append(c)
    built = datetime.now().isoformat(timespec='seconds')
    for d, cs in by_day.items():
        cs.sort(key=lambda c: -(c['mc'] or 0))
        write_json(OUT / f'{d}.json', {'date': d, 'built': built, 'cards': [{k: v for k, v in c.items() if k != 'path'} for c in cs]})
    dates = sorted(by_day, reverse=True)
    (OUT / 'dates.json').write_text(json.dumps(dates))
    for p in OUT.glob('20*.json'):
        if p.stem not in by_day:
            p.unlink()
    st = {'from': evs[0]['ts'][:10] if evs else None, 'to': evs[-1]['ts'][:10] if evs else None, 'n': len(evs),
          'm_from': cut, 'th': {'sales': earn.SALES_T, 'op': earn.OP_T}, 'cases': earn.CASES,
          'table': stats(evs), 'paths': avg_paths(cards)}
    write_json(OUT / 'stats.json', st)
    return len(evs), len(cards), sum(1 for c in cards if c['ch']), len(dates)


def main():
    n, nc, nch, nd = build()
    print(f'earn: 이벤트 {n} (최근 1년 카드 {nc}, 분봉 {nch}) · 날짜 {nd}')


if __name__ == '__main__':
    main()
