"""
공시 탭 JSON: public/data/dart/{date}.json + dates.json, 종목별 최근 공시 public/data/dart/s/{code}.json

- items     그날 접수된 공시 (종류별 항목 + 회사 시총). 잠정실적은 분기 컨센서스와 비교한 서프라이즈·쇼크
- schedule  그날부터 7일 안의 실적 공시 예정(결산실적공시예고)·기업설명회(IR) 일정
- 장전/장후: 장중 실행이 처음 본 시각으로 정한다 (백필한 공시는 모름)

  python3 build_dart.py
"""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta

import db
from build_naver import DATA, market_info, write_json

OUT = DATA / 'dart'
KEEP_DAYS = 30           # 화면에 둘 날짜 수
STOCK_DAYS = 90          # 종목 패널에 보일 기간
SURPRISE = 0.10          # 영업이익이 추정치보다 ±10% 이상이면 서프라이즈·쇼크
MISMATCH = 0.5           # 별도 실적 매출이 추정치와 50% 넘게 다르면 연결 추정치로 보고 비교 안 함


def session_tag(day: str, seen: str):
    if not seen or seen[:10] != day:
        return None
    t = seen[11:16]
    return '장전' if t < '09:00' else '장후' if t >= '15:30' else '장중'


def cns_for(conn, code, period, day):
    """공시일까지 받은 추정치 중 마지막 (없으면 공시 뒤에 받은 것 — 네이버가 하루쯤 추정 열을 남겨 둔다)"""
    r = conn.execute('SELECT * FROM cns_quarter WHERE code = ? AND period = ? AND as_of <= ? ORDER BY as_of DESC LIMIT 1',
                     (code, period, day)).fetchone()
    if not r:
        r = conn.execute('SELECT * FROM cns_quarter WHERE code = ? AND period = ? ORDER BY as_of LIMIT 1',
                         (code, period)).fetchone()
    return dict(r) if r else None


def diff(v, c):
    if v is None or c is None or c == 0:
        return None
    return (v - c) / abs(c)


def surprise(data, cns):
    """{'cns': {...}, 'd': {'sales': .., 'op': .., 'np': ..}, 'tag': '서프'|'쇼크'|None}"""
    if not cns:
        return None
    rows = data.get('rows', {})
    # 순이익: 지배주주 기준으로 비교하되, 추정치에 지배 값이 없으면 당기순이익끼리
    np_key = 'cnp' if cns.get('cnp') is not None and rows.get('cnp') else 'np'
    pick = {'sales': ('sales', 'sales'), 'op': ('op', 'op'), 'np': (np_key, np_key)}
    out = {'cns': {}, 'd': {}, 'np_basis': '지배' if np_key == 'cnp' else '당기'}
    for k, (a, c) in pick.items():
        v = (rows.get(a) or {}).get('v')
        out['cns'][k] = cns.get(c)
        out['d'][k] = diff(v, cns.get(c))
    # 별도 실적을 연결 추정치와 비교하게 되면(지주사 등) 매출부터 크게 어긋난다 → 비교하지 않는다
    if data.get('basis') == '별도' and out['d']['sales'] is not None and abs(out['d']['sales']) > MISMATCH:
        return {'mismatch': True}
    v, c = (rows.get('op') or {}).get('v'), cns.get('op')
    tag = None
    if v is not None and c is not None:
        if c > 0 > v:
            tag = '쇼크'
        elif c < 0 < v:
            tag = '서프'
        elif out['d']['op'] is not None:
            tag = '서프' if out['d']['op'] >= SURPRISE else '쇼크' if out['d']['op'] <= -SURPRISE else None
    out['tag'] = tag
    return out


def load_day(conn, day):
    rows = [dict(r) for r in conn.execute('SELECT * FROM dart_filing WHERE date = ? ORDER BY rcept_no', (day,))]
    # 같은 날 같은 회사의 잠정실적은 연결 > 별도, 정정이면 나중 것
    earn = {}
    for r in rows:
        if r['kind'] != 'earn' or not r['data']:
            continue
        d = json.loads(r['data'])
        prev = earn.get(r['code'])
        if not prev or (d.get('basis') == '연결') >= (prev[1].get('basis') == '연결'):
            earn[r['code']] = (r['rcept_no'], d)
    keep_earn = {v[0] for v in earn.values()}
    return [r for r in rows if r['kind'] != 'earn' or r['rcept_no'] in keep_earn]


def item(conn, r, info):
    d = json.loads(r['data']) if r['data'] else {}
    i = info.get(r['code'], {})
    out = {'no': r['rcept_no'], 'k': r['kind'], 'c': r['code'], 'n': r['name'], 'mk': r['market'],
           'mc': i.get('mc'), 'p': i.get('p'), 'ch': i.get('ch'), 'w': i.get('w'),
           't': r['title'], 'fx': r['fixed'] or None, 'ss': session_tag(r['date'], r['fetched_at']), 'd': d}
    if r['kind'] == 'earn' and d.get('end'):
        out['s'] = surprise(d, cns_for(conn, r['code'], d['end'][:4] + d['end'][5:7], r['date']))
    return out


def schedule(conn, day, info, days=7):
    """day ~ day+days 사이 예정된 실적 공시(예고)·IR. 같은 회사 같은 날은 하나로"""
    end = (date.fromisoformat(day) + timedelta(days=days)).isoformat()
    out = {}
    for r in conn.execute("SELECT * FROM dart_filing WHERE kind IN ('preview', 'ir') AND data IS NOT NULL "
                          "AND date >= ? ORDER BY rcept_no", ((date.fromisoformat(day) - timedelta(days=45)).isoformat(),)):
        d = json.loads(r['data'])
        when = d.get('date')
        if not when or not (day <= when <= end):
            continue
        k = (r['code'], when)
        i = info.get(r['code'], {})
        e = out.setdefault(k, {'date': when, 'c': r['code'], 'n': r['name'], 'mk': r['market'], 'mc': i.get('mc'),
                               'w': i.get('w'), 'earn': False, 'ir': None})
        if r['kind'] == 'preview':
            e['earn'] = True
        else:
            e['ir'] = {'time': d.get('time'), 'how': d.get('how'), 'what': d.get('what'), 'who': d.get('who')}
            if d.get('what') and any(w in d['what'] for w in ('실적', '경영성과', '결산')):
                e['earn'] = True
    # 이미 잠정실적을 낸 회사의 다음 날 IR(컨퍼런스콜)은 '실적발표 예정'에서 뺀다
    for e in out.values():
        if e['earn'] and conn.execute(
                "SELECT 1 FROM dart_filing WHERE code = ? AND kind = 'earn' AND date < ? AND date >= ? LIMIT 1",
                (e['c'], e['date'], (date.fromisoformat(e['date']) - timedelta(days=10)).isoformat())).fetchone():
            e['earn'], e['done'] = False, True
    return sorted(out.values(), key=lambda e: (e['date'], -(e['mc'] or 0)))


def build(conn):
    days = [r[0] for r in conn.execute('SELECT DISTINCT date FROM dart_filing ORDER BY date DESC LIMIT ?', (KEEP_DAYS,))]
    OUT.mkdir(parents=True, exist_ok=True)
    built = datetime.now().isoformat(timespec='seconds')
    latest_info = None
    for day in days:
        info, _ = market_info(conn, day)
        latest_info = latest_info or info
        items = [item(conn, r, info) for r in load_day(conn, day)]
        write_json(OUT / f'{day}.json', {'date': day, 'built': built, 'items': items,
                                         'schedule': schedule(conn, day, info)})
    (OUT / 'dates.json').write_text(json.dumps(days))
    for p in OUT.glob('20*.json'):
        if p.stem not in days:
            p.unlink()

    # 종목별 최근 공시
    since = (date.today() - timedelta(days=STOCK_DAYS)).isoformat()
    per = defaultdict(list)
    info = latest_info or {}
    consolidated = {(r[0], r[1]) for r in conn.execute(
        "SELECT code, date FROM dart_filing WHERE kind = 'earn' AND date >= ? AND title LIKE '%연결%'", (since,))}
    for r in conn.execute('SELECT * FROM dart_filing WHERE date >= ? ORDER BY rcept_no DESC', (since,)):
        if r['kind'] == 'earn' and '연결' not in (r['title'] or '') and (r['code'], r['date']) in consolidated:
            continue   # 같은 날 연결 실적이 있으면 별도는 빼고
        x = item(conn, dict(r), info)
        x['date'] = r['date']
        for k in ('mc', 'p', 'ch', 'w', 'mk'):
            x.pop(k, None)
        per[r['code']].append(x)
    (OUT / 's').mkdir(exist_ok=True)
    for code, xs in per.items():
        write_json(OUT / 's' / f'{code}.json', xs[:40])
    for p in (OUT / 's').glob('*.json'):
        if p.stem not in per:
            p.unlink()
    return days


def main():
    days = build(db.connect())
    print(f"dart: {len(days)}일 ({days[-1] if days else '-'} ~ {days[0] if days else '-'})")


if __name__ == '__main__':
    main()
