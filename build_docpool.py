"""
@DOC_POOL 글 → 화면용 JSON (리포트 탭의 '@DOC_POOL 자료' 보기)

- public/data/docpool/{올라온 날}.json + dates.json
    stocks  종목 리포트를 종목별로: 시총·주가(build_naver.market_info) + 글마다 시각·증권사·제목·의견·목표가·글 번호
            nv = 같은 리포트가 네이버 리서치 수집분(research)에도 있으면 그 researchId (증권사 + 종목 + 작성일 ±3일 + 제목)
    others  종목을 가려내지 못한 글(산업·전략·시황·해외 종목·IR 자료): 주제 머리글 + 제목
    sum     건수, brokers = 증권사별 건수

공개 범위: 제목·증권사·의견·목표가·시각·글 번호 같은 목록 정보만 싣는다. 채널이 붙인 요약 본문과 PDF 는 싣지 않는다
(원문은 제목 링크로 텔레그램에서 본다). 2026-11-17 사용자 승인으로 공개 사이트에도 올린다 (publish.py DATED).

  python3 build_docpool.py          # build_naver.py 뒤 (시총·네이버 리포트와 견준다)
  python3 build_docpool.py stats    # 월별 건수 · 증권사/종목을 가려낸 비율 · 네이버와 겹치는 건수
"""

import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import collect_docpool as C
import db
import docpool as D
from build_naver import DATA, market_info, public, write_json

OUT = DATA / 'docpool'
KEEP_DAYS = 120          # 화면에 둘 날 수 (올라온 날 기준)


# 리포트가 아직 옛 이름·줄임말로 부르는 종목 (거래소 이름이 바뀐 곳). stats -v 의 '목표주가 있는데 종목 모름'에 보이면 여기에 더한다
ALIASES = {'엔씨소프트': '036570', 'LIG넥스원': '079550', 'LIG D&A': '079550', '코윈테크': '282880'}


def name_maps(conn):
    """(종목 정보, {견줄 꼴 종목명: 코드}, 코드 모음) — 보통주만. 지금 거래소 이름 + ALIASES"""
    d = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    info, _ = market_info(conn, d) if d else ({}, None)
    names = {D.norm(n): c for n, c in ALIASES.items() if c in info}
    names.update({D.norm(i['n']): c for c, i in info.items()})
    return info, names, set(info)


def load_posts(pconn, names, codes) -> list:
    """docpool.db 의 글 → 파싱·중복 묶기까지 한 목록 (id 오름차순)"""
    rows = [dict(r) for r in pconn.execute('SELECT id, ts, file, text FROM post ORDER BY id')]
    return D.dedupe([D.parse_post(r, names, codes) for r in rows])


def naver_by_code(conn, since) -> dict:
    out = defaultdict(list)
    for r in conn.execute('SELECT id, code, date, broker, title FROM research WHERE date >= ?', (since,)):
        out[r['code']].append(dict(r))
    return out


def day_json(d, posts, info, nv) -> dict:
    """하루치 글(posts: 그날 올라온 것) → 화면 JSON"""
    stocks, others, brokers = {}, [], Counter()
    for p in sorted(posts, key=lambda p: -p['id']):      # 최신순
        item = {'id': p['id'], 't': p['ts'][11:16], 'b': p['broker'], 'ti': p['title']}
        if p['rdate'] != d:
            item['rd'] = p['rdate']
        if p['op']:
            item['op'] = p['op']
        brokers[p['broker']] += 1
        if p['code'] and p['code'] in info:
            if p['goal']:
                item['g'] = p['goal']
            m = D.match_naver(p, nv.get(p['code'], []))
            if m:
                item['nv'] = m
            stocks.setdefault(p['code'], {'c': p['code'], **public(info[p['code']]), 'r': []})['r'].append(item)
        else:
            item['tp'] = p['topic']
            others.append(item)
    n_stock = sum(len(s['r']) for s in stocks.values())
    n_nv = sum(1 for s in stocks.values() for r in s['r'] if r.get('nv'))
    return {
        'date': d, 'built': datetime.now().isoformat(timespec='seconds'),
        'sum': {'n': n_stock + len(others), 'stock': n_stock, 'stocks': len(stocks), 'other': len(others),
                'brokers': len([b for b in brokers if b]), 'nv': n_nv, 'only': n_stock - n_nv},
        'brokers': [[b, n] for b, n in brokers.most_common() if b],
        'stocks': sorted(stocks.values(), key=lambda s: (-len(s['r']), -(s.get('mc') or 0))),
        'others': others,
    }


def build(conn, pconn) -> dict:
    info, names, codes = name_maps(conn)
    posts = load_posts(pconn, names, codes)
    if not posts:
        return {}
    since = (date.fromisoformat(min(p['rdate'] for p in posts)) - timedelta(days=7)).isoformat()
    nv = naver_by_code(conn, since)
    days = defaultdict(list)
    for p in posts:
        days[p['date']].append(p)
    keep = sorted(days, reverse=True)[:KEEP_DAYS]
    return {d: day_json(d, days[d], info, nv) for d in keep}


def stats(conn, pconn) -> int:
    info, names, codes = name_maps(conn)
    rows = [dict(r) for r in pconn.execute('SELECT id, ts, file, text FROM post ORDER BY id')]
    parsed = [D.parse_post(r, names, codes) for r in rows]
    posts = D.dedupe(parsed)
    if not posts:
        print('받은 글이 없습니다.')
        return 0
    heads = {r['id']: D.header(r['text'] or '') for r in rows}
    goal = [p for p in posts if heads[p['id']].get('목표주가')]      # 목표주가 줄이 있는 글 = 종목 리포트 꼴
    nv = naver_by_code(conn, min(p['rdate'] for p in posts))
    matched = {p['id']: D.match_naver(p, nv.get(p['code'], [])) for p in posts if p['code']}
    hit = {v for v in matched.values() if v}
    pct = lambda a, b: f'{a / b * 100:.1f}%' if b else '–'
    print(f'글 {len(rows)}건 → 같은 리포트 두 번 올린 것 {len(parsed) - len(posts)}건 묶어 {len(posts)}건 '
          f"({posts[0]['ts'][:10]} ~ {posts[-1]['ts'][:16]})")
    mon = Counter(p['date'][:7] for p in posts)
    print('월별:', ' · '.join(f'{m} {n}건' for m, n in sorted(mon.items())))
    n_b, n_t, n_c = sum(1 for p in posts if p['broker']), sum(1 for p in posts if p['title']), sum(1 for p in posts if p['code'])
    print(f'제목 {pct(n_t, len(posts))} · 증권사 {pct(n_b, len(posts))} ({n_b}건) · 국내 종목 {pct(n_c, len(posts))} ({n_c}건)')
    print(f"목표주가 줄이 있는 글 {len(goal)}건 가운데 종목을 가려낸 것 {pct(sum(1 for p in goal if p['code']), len(goal))}, "
          f"증권사 {pct(sum(1 for p in goal if p['broker']), len(goal))}")
    print(f'네이버 수집분과 같은 리포트: 종목 글 {n_c}건 가운데 {sum(1 for v in matched.values() if v)}건 '
          f'(네이버 리포트 {len(hit)}건에 해당 · 같은 기간 네이버 {sum(len(v) for v in nv.values())}건)')
    print('증권사:', ', '.join(f'{b} {n}' for b, n in Counter(p['broker'] or '(모름)' for p in posts).most_common(45)))
    if '-v' in sys.argv:
        print('\n[증권사 모름] 작성자 줄 상위:')
        for a, n in Counter((p['author'] or f"(작성자 없음) {p['file'][-30:]}") for p in posts if not p['broker']).most_common(40):
            print(f'  {n:4d}  {a[:70]}')
        print('\n[목표주가 있는데 종목 모름] 머리글 상위:')
        for a, n in Counter(p['topic'] or p['title'][:30] for p in goal if not p['code']).most_common(40):
            print(f'  {n:4d}  {a[:70]}')
    return 0


def main() -> int:
    conn, pconn = db.connect(), C.connect()
    if len(sys.argv) > 1 and sys.argv[1] == 'stats':
        return stats(conn, pconn)
    days = build(conn, pconn)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob('20*.json'):          # 보관 기간을 넘긴 날은 지운다
        if old.stem not in days:
            old.unlink()
    for d, data in days.items():
        write_json(OUT / f'{d}.json', data)
    write_json(OUT / 'dates.json', sorted(days, reverse=True))
    n = sum(x['sum']['n'] for x in days.values())
    print(f"docpool/: {len(days)}일, 글 {n}건 (종목 리포트 {sum(x['sum']['stock'] for x in days.values())}건, "
          f"네이버에도 있는 것 {sum(x['sum']['nv'] for x in days.values())}건)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
