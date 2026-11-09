"""
이벤트 스터디: public/data/events.json — 공시 종류별 공시 뒤 초과수익률

- 이벤트: dart_event (DART 목록 제목으로 종류를 정함, 1년치). 정정·자회사 공시는 빼고, 같은 날 같은 회사 같은 종류는 하나로.
  원문을 읽은 최근 공시(dart_filing)로는 '잠정실적 서프·쇼크', '대형 수주(매출 대비 10% 이상)' 같은 세부 그룹도 만든다.
- 가격: 수정주가 수익률 (KRX 등락률을 이어 붙임, adjust.py) — 무상증자·유상증자 권리락 날 하락이 손실로 잡히지 않게.
- 기준: 공시일 바로 전 거래일 종가(t=-1). 장중·장후 공시 모두 반응이 들어가도록.
- 초과수익 = 종목 수익률 − 같은 시장 지수(코스피·코스닥) 수익률, 같은 구간.
- 구간: 사전(t-6→t-1), D+1(t-1→t+1), D+5, D+20. 평균은 한 건당 ±50%로 잘라 극단값 영향을 줄이고, 중앙값·적중률(0보다 큰 비율)·t값을 함께 낸다.
- path: t=-5~+20 평균 누적 초과수익 (t=-1 = 0)

  python3 build_events.py
"""

import bisect
import json
import math
from collections import defaultdict
from datetime import datetime

import db
from build_dart import cns_for, surprise
from adjust import adjusted_series
from build_naver import DATA, write_json
from universe import is_common

PATH = list(range(-5, 21))
WINDOWS = {'pre': (-6, -1), 'd1': (-1, 1), 'd5': (-1, 5), 'd20': (-1, 20)}
CLIP = 0.5
RECENT = 30
MIN_N = 10     # 이보다 적으면 화면에 '표본 적음'

# 그룹: 키, 이름, 설명, dart_event 종류
KIND_GROUPS = [
    ('earn', '잠정실적 (전체)', '영업(잠정)실적 공정공시 전부', ['earn']),
    ('contract', '공급계약 체결', '단일판매·공급계약 체결', ['contract']),
    ('contract_x', '공급계약 해지', '단일판매·공급계약 해지', ['contract_x']),
    ('cancel', '자사주 소각', '주식소각결정', ['cancel']),
    ('buyback', '자사주 취득', '자기주식 취득결정·취득 신탁계약', ['buyback', 'trust']),
    ('mezz', 'CB·BW·EB 발행', '전환사채·신주인수권부사채·교환사채 발행결정', ['cb', 'bw', 'eb']),
    ('rights', '유상증자', '유상증자결정', ['rights']),
    ('bonus', '무상증자', '무상증자결정', ['bonus']),
    ('holder', '최대주주 변경', '최대주주변경', ['holder']),
    ('invest', '타법인 주식 취득', '타법인주식및출자증권취득결정', ['invest']),
    ('dividend', '현금·현물배당', '현금ㆍ현물배당결정', ['dividend']),
    ('biz', '주요경영사항', '투자판단 관련 주요경영사항 (품목허가·임상 등)', ['biz']),
]
# 원문을 읽은 공시로만 만드는 세부 그룹: 키, 이름, 설명, 판정 함수(item dict → bool)
DETAIL_GROUPS = [
    ('earn_sp', '잠정실적 서프라이즈', '영업이익이 분기 컨센서스보다 10% 이상 많음 (또는 흑자전환)'),
    ('earn_sk', '잠정실적 쇼크', '영업이익이 분기 컨센서스보다 10% 이상 적음 (또는 적자전환)'),
    ('contract_big', '대형 수주', '공급계약 매출액 대비 10% 이상'),
]


def calendar(conn):
    days = [r[0] for r in conn.execute('SELECT DISTINCT date FROM ohlc_daily ORDER BY date')]
    return days, {d: i for i, d in enumerate(days)}


def series(conn, table, pos, n):
    out = defaultdict(lambda: [None] * n)
    for code, d, c in conn.execute(f'SELECT code, date, close FROM {table} WHERE close IS NOT NULL'):
        if d in pos:
            out[code][pos[d]] = c
    return out


def car(px, mx, i0, a, b):
    """t=a 종가 → t=b 종가 초과수익 (i0 = 이벤트 당일 위치). 값이 하나라도 없으면 None"""
    ia, ib = i0 + a, i0 + b
    if ia < 0 or ib >= len(px):
        return None
    p0, p1, m0, m1 = px[ia], px[ib], mx[ia], mx[ib]
    if not (p0 and p1 and m0 and m1):
        return None
    return (p1 / p0 - 1) - (m1 / m0 - 1)


def stats(xs):
    xs = [max(-CLIP, min(CLIP, x)) for x in xs if x is not None]
    n = len(xs)
    if not n:
        return None
    mean = sum(xs) / n
    srt = sorted(xs)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0
    return {'n': n, 'mean': round(mean * 100, 2), 'med': round(med * 100, 2),
            'hit': round(sum(x > 0 for x in xs) / n * 100, 1),
            't': round(mean / (sd / math.sqrt(n)), 2) if sd else None}


def detail_tags(conn):
    """rcept_no → 세부 그룹 키 (원문을 읽은 공시)"""
    tags = {}
    for r in conn.execute("SELECT rcept_no, code, date, kind, data FROM dart_filing "
                          "WHERE kind IN ('earn', 'contract') AND data IS NOT NULL"):
        d = json.loads(r['data'] or '{}')
        if r['kind'] == 'contract' and (d.get('pct') or 0) >= 10:
            tags[r['rcept_no']] = 'contract_big'
        elif r['kind'] == 'earn' and d.get('end') and ((d.get('rows') or {}).get('op') or {}).get('v') is not None:
            s = surprise(d, cns_for(conn, r['code'], d['end'][:4] + d['end'][5:7], r['date']))
            tag = (s or {}).get('tag')
            if tag:
                tags[r['rcept_no']] = 'earn_sp' if tag == '서프' else 'earn_sk'
    return tags


def build(conn):
    days, pos = calendar(conn)
    n = len(days)
    px = adjusted_series(conn, pos)   # 권리락·분할을 반영한 수정 가격
    mx = series(conn, 'index_ohlc', pos, n)
    mcap = {r[0]: r[1] for r in conn.execute(
        'SELECT code, mcap FROM price_daily WHERE date = (SELECT MAX(date) FROM price_daily)')}
    kind_to_group = {k: g for g, _, _, ks in KIND_GROUPS for k in ks}
    tags = detail_tags(conn)

    events = defaultdict(list)
    seen = set()
    for r in conn.execute('SELECT * FROM dart_event ORDER BY date, rcept_no'):
        if '정정' in (r['title'] or '') or '자회사' in (r['title'] or '') or not is_common(r['code']):
            continue
        g = kind_to_group.get(r['kind'])
        if not g or (r['code'], r['date'], g) in seen or r['code'] not in px:
            continue
        seen.add((r['code'], r['date'], g))
        i0 = bisect.bisect_left(days, r['date'])   # 공시일(휴일이면 다음 거래일)
        if i0 < 6 or i0 >= n:
            continue
        p, m = px[r['code']], mx.get(r['market'])
        if not m:
            continue
        ev = {'no': r['rcept_no'], 'd': r['date'], 'c': r['code'], 'n': r['name'], 'mk': r['market'],
              'mc': round(mcap.get(r['code']) or 0) or None, 't': r['title'],
              **{w: car(p, m, i0, a, b) for w, (a, b) in WINDOWS.items()},
              'path': [car(p, m, i0, -1, t) if t != -1 else 0.0 for t in PATH]}
        events[g].append(ev)
        if r['rcept_no'] in tags:
            events[tags[r['rcept_no']]].append(ev)

    groups = []
    for key, label, desc, *_ in KIND_GROUPS + [(k, l, d) for k, l, d in DETAIL_GROUPS]:
        evs = events.get(key, [])
        if not evs:
            continue
        path = []
        for j in range(len(PATH)):
            vals = [max(-CLIP, min(CLIP, e['path'][j])) for e in evs if e['path'][j] is not None]
            path.append(round(sum(vals) / len(vals) * 100, 2) if vals else None)
        pct = lambda v: None if v is None else round(v * 100, 2)
        groups.append({
            'key': key, 'label': label, 'desc': desc, 'detail': key in {k for k, *_ in DETAIL_GROUPS},
            'n': len(evs), 'from': evs[0]['d'], 'to': evs[-1]['d'],
            **{w: stats([e[w] for e in evs]) for w in WINDOWS},
            'path': path,
            'recent': [{**{k: e[k] for k in ('no', 'd', 'c', 'n', 'mk', 'mc', 't')},
                        **{w: pct(e[w]) for w in WINDOWS}} for e in evs[-RECENT:][::-1]],
        })
    return {'built': datetime.now().isoformat(timespec='seconds'), 'from': days[0], 'to': days[-1],
            'path_t': PATH, 'min_n': MIN_N, 'clip': CLIP * 100, 'groups': groups}


def main():
    data = build(db.connect())
    write_json(DATA / 'events.json', data)
    print('events.json:', ', '.join(f"{g['label']} {g['n']}" for g in data['groups']))


if __name__ == '__main__':
    main()
