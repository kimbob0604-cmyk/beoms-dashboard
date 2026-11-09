"""
이벤트 스터디: public/data/events.json — 공시 종류별 공시 뒤 초과수익률

- 이벤트: dart_event (DART 목록 제목으로 종류를 정함, 1년치). 정정·자회사 공시는 빼고, 같은 날 같은 회사 같은 종류는 하나로.
  원문을 읽은 최근 공시(dart_filing)로는 '잠정실적 서프·쇼크', '대형 수주(매출 대비 10% 이상)' 같은 세부 그룹도 만든다.
- 가격: 수정주가 수익률 (KRX 등락률을 이어 붙임, adjust.py) — 무상증자·유상증자 권리락 날 하락이 손실로 잡히지 않게.
- 공시 시각(KIND, dart_event.tm)으로 장전(<09:00)·장중·장후(15:30~)를 나누고, 장후 공시는 다음 거래일을 반응일(t=0)로 잡는다.
  시각을 모르면 공시일을 t=0 으로 둔다.
- 기준: 반응일 전 거래일 종가(t=-1). 반응일(d0) = t-1 → t0, 반응일 거래량 배수 = t0 거래량 ÷ 직전 20일 평균.
- 초과수익 = 종목 수익률 − 같은 시장 지수(코스피·코스닥) 수익률, 같은 구간.
- 구간: 사전(t-6→t-1), 반응일(t-1→t0), D+1(t-1→t+1), D+5, D+20. 평균은 한 건당 ±50%로 잘라 극단값 영향을 줄이고, 중앙값·적중률(0보다 큰 비율)·t값을 함께 낸다.
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
WINDOWS = {'pre': (-6, -1), 'd0': (-1, 0), 'd1': (-1, 1), 'd5': (-1, 5), 'd20': (-1, 20)}
EV_DIR = DATA / 'events'   # 종류별 기업 리스트 (화면에서 종류를 누를 때 받음)
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


def session_of(tm):
    if not tm:
        return None
    return '장전' if tm < '09:00' else '장중' if tm < '15:30' else '장후'


def eok_(v):
    if v is None:
        return '–'
    v = v / 1e8
    return f'{v / 1e4:,.1f}조' if abs(v) >= 1e4 else f'{v:,.0f}억'


def info_of(kind, d, s=None, mc=None):
    """원문에서 읽은 핵심 한 줄 (최근 공시만)"""
    if not d:
        return None
    try:
        if kind == 'contract':
            return f"{eok_(d.get('amt'))} · 매출대비 {d.get('pct')}%" + (f" · {d['party']}" if d.get('party') else '')
        if kind == 'earn':
            op = ((d.get('rows') or {}).get('op') or {})
            if op.get('v') is None:
                return None
            txt = f"영업이익 {op['v']:,.0f}억"
            if s and not s.get('mismatch') and (s.get('d') or {}).get('op') is not None:
                txt += f" (컨센 대비 {s['d']['op'] * 100:+.0f}%)"
            elif op.get('yoy') is not None:
                txt += f" (YoY {op['yoy']:+.0f}%)"
            return txt
        if kind in ('cancel', 'buyback', 'trust'):
            amt = d.get('amt')
            return eok_(amt) + (f" (시총 {amt / 1e8 / mc * 100:.1f}%)" if amt and mc else '')
        if kind in ('cb', 'bw', 'eb'):
            return eok_(d.get('amt')) + (f" · 전환가 {d['price']:,.0f}원" if d.get('price') else '') + (f" · {d['how']}" if d.get('how') else '')
        if kind == 'rights':
            return eok_(d.get('amt')) + (f" · {d['how']}" if d.get('how') else '')
        if kind == 'holder':
            return f"→ {d.get('after') or '–'} {d.get('after_pct') or ''}%"
        if kind == 'invest':
            return f"{d.get('target') or '–'} · {eok_(d.get('amt'))}"
        if kind == 'dividend':
            return f"주당 {d.get('dps') or 0:,.0f}원" + (f" · 시가배당률 {d['yld']}%" if d.get('yld') is not None else '')
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None


def volumes(conn, pos):
    out = defaultdict(lambda: [None] * len(pos))
    for code, d, v in conn.execute('SELECT code, date, volume FROM ohlc_daily WHERE volume IS NOT NULL'):
        if d in pos:
            out[code][pos[d]] = v
    return out


def vol_ratio(vs, i0):
    if not vs or i0 >= len(vs) or not vs[i0]:
        return None
    prev = [v for v in vs[max(0, i0 - 20):i0] if v]
    return round(vs[i0] / (sum(prev) / len(prev)), 1) if len(prev) >= 10 and sum(prev) else None


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
    EV_DIR.mkdir(parents=True, exist_ok=True)
    days, pos = calendar(conn)
    n = len(days)
    px = adjusted_series(conn, pos)   # 권리락·분할을 반영한 수정 가격
    mx = series(conn, 'index_ohlc', pos, n)
    mcap = {r[0]: r[1] for r in conn.execute(
        'SELECT code, mcap FROM price_daily WHERE date = (SELECT MAX(date) FROM price_daily)')}
    kind_to_group = {k: g for g, _, _, ks in KIND_GROUPS for k in ks}
    tags = detail_tags(conn)
    vol = volumes(conn, pos)
    filings = {r['rcept_no']: r for r in conn.execute('SELECT rcept_no, code, date, kind, data FROM dart_filing WHERE data IS NOT NULL')}

    events = defaultdict(list)
    seen = set()
    for r in conn.execute('SELECT * FROM dart_event ORDER BY date, rcept_no'):
        if '정정' in (r['title'] or '') or '자회사' in (r['title'] or '') or not is_common(r['code']):
            continue
        g = kind_to_group.get(r['kind'])
        if not g or (r['code'], r['date'], g) in seen or r['code'] not in px:
            continue
        seen.add((r['code'], r['date'], g))
        ss = session_of(r['tm'])
        i0 = bisect.bisect_left(days, r['date'])   # 공시일(휴일이면 다음 거래일)
        if ss == '장후' and i0 < n and days[i0] == r['date']:
            i0 += 1   # 장 마감 뒤 공시 → 다음 거래일이 반응일
        if i0 < 6 or i0 > n:
            continue
        p, m = px[r['code']], mx.get(r['market'])
        if not m:
            continue
        mc = round(mcap.get(r['code']) or 0) or None
        f = filings.get(r['rcept_no'])
        info, tag = None, None
        if f:
            fd = json.loads(f['data'] or '{}')
            sur = None
            if f['kind'] == 'earn' and fd.get('end'):
                sur = surprise(fd, cns_for(conn, f['code'], fd['end'][:4] + fd['end'][5:7], f['date']))
                tag = (sur or {}).get('tag')
            info = info_of(f['kind'], fd, sur, mc)
        raw0 = None
        if i0 < n and p[i0] and p[i0 - 1]:
            raw0 = p[i0] / p[i0 - 1] - 1
        ev = {'no': r['rcept_no'], 'd': r['date'], 'tm': r['tm'], 'ss': ss, 'c': r['code'], 'n': r['name'],
              'mk': r['market'], 'mc': mc, 't': r['title'], 'info': info, 'tag': tag,
              'rd': days[i0] if i0 < n else None, 'r0': raw0, 'vx': vol_ratio(vol.get(r['code']), i0),
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
        by_ss = {}
        for ss in ('장전', '장중', '장후'):   # 공시 시간대별 반응일 초과수익
            st_ = stats([e['d0'] for e in evs if e['ss'] == ss])
            if st_:
                by_ss[ss] = st_
        groups.append({
            'key': key, 'label': label, 'desc': desc, 'detail': key in {k for k, *_ in DETAIL_GROUPS},
            'n': len(evs), 'from': evs[0]['d'], 'to': evs[-1]['d'],
            **{w: stats([e[w] for e in evs]) for w in WINDOWS},
            'path': path, 'by_ss': by_ss,
            'timed': sum(1 for e in evs if e['tm']),
        })
        # 종류별 기업 리스트 (최신순). 경로는 % × 10 정수로 줄여 둔다
        rows = [{**{k: e[k] for k in ('no', 'd', 'tm', 'ss', 'c', 'n', 'mk', 'mc', 't', 'info', 'tag', 'rd', 'vx')},
                 'r0': pct(e['r0']), **{w: pct(e[w]) for w in WINDOWS},
                 'p': [None if v is None else round(v * 1000) for v in e['path']]} for e in reversed(evs)]
        write_json(EV_DIR / f'{key}.json', {'key': key, 'label': label, 'path_t': PATH, 'rows': rows})
    return {'built': datetime.now().isoformat(timespec='seconds'), 'from': days[0], 'to': days[-1],
            'path_t': PATH, 'min_n': MIN_N, 'clip': CLIP * 100, 'groups': groups}


def main():
    data = build(db.connect())
    write_json(DATA / 'events.json', data)
    print('events.json:', ', '.join(f"{g['label']} {g['n']}" for g in data['groups']))


if __name__ == '__main__':
    main()
