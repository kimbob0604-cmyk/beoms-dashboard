"""
리포트 탭 JSON: public/data/digest/{작성일}.json + dates.json — 그날 나온 증권사 종목 리포트 정리

- stocks   종목별 묶음: 리포트마다 증권사·의견(직전 대비 변경)·목표가(같은 증권사 직전 대비)·상승여력·소제목·요약·키워드
           init  = 이 증권사가 이 종목을 처음 다룸(데이터 범위 안에서) · lone = 최근 90일 이 종목 첫 리포트(소외주)
- kws      그날 리포트들이 많이 쓴 말 (최근 90일 리포트 대비 그날 유난히 많이 나온 말 순)
- sum      건수·종목·증권사 수, 목표가 상향·하향·유지, 의견 상향·하향, 업종 분포

  python3 build_digest.py      # build_naver.py 뒤
"""

import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import db
import keywords as K
from build_naver import DATA, market_info, opinion, public, report_text, write_json

OUT = DATA / 'digest'
KEEP_DAYS = 30            # 화면에 둘 작성일 수
CORPUS_DAYS = 90          # 키워드 기준이 되는 기간
LONE_DAYS = 90
OP_RANK = {'매도': 0, '중립': 1, '매수': 2}


def summary_of(body, width=200):
    """본문 요약의 앞 두 문장 (width 자 안쪽)"""
    out = ''
    # 마침표 뒤 공백에서 나눈다 (keywords.sentences 는 짧은 문장을 빼므로 요약에는 안 맞음)
    for s in re.split(r'(?<=[.!?])\s+', (body or '').strip()):
        s = s.strip()
        if not s:
            continue
        if out and len(out) + len(s) > width:
            break
        out = f'{out} {s}'.strip()
        if len(out) >= width * 0.6:
            break
    return out[:width + 40]


def history(conn):
    """작성일·id 순 전체 리포트 + 같은 증권사 직전 목표가·의견, 첫 리포트 여부"""
    rows = [dict(r) for r in conn.execute('SELECT * FROM research ORDER BY date, id')]
    first_day = rows[0]['date'] if rows else None
    last, last_any = {}, {}
    for r in rows:
        key = (r['code'], r['broker'])
        prev = last.get(key)
        r['pg'] = prev and prev['goal']
        r['pop'] = prev and opinion(prev['opinion'])
        # 데이터가 1년 넘게 쌓인 뒤에만 '첫 커버'로 본다 (증권사가 몇 달 쉬었다 쓰는 일이 흔해서)
        r['init'] = prev is None and first_day is not None and \
            (date.fromisoformat(r['date']) - date.fromisoformat(first_day)).days >= 365
        p_any = last_any.get(r['code'])
        r['lone'] = p_any is not None and (date.fromisoformat(r['date']) - date.fromisoformat(p_any)).days > LONE_DAYS
        if r['goal']:
            last[key] = {'goal': r['goal'], 'opinion': r['opinion']}
        elif prev is None or r['opinion']:
            last[key] = {'goal': prev and prev['goal'], 'opinion': r['opinion'] or (prev and prev['opinion'])}
        last_any[r['code']] = r['date']
    return rows


def day_keywords(docs, df, n_docs, vocab, names, top=15):
    """그날 여러 리포트가 쓴 말: 문서 수 × idf. 종목명·너무 흔한 말은 뺀다"""
    cnt, where = Counter(), defaultdict(set)
    for d in docs:
        for t in set(K.doc_terms(d['text'], vocab)):
            if not K.keep(t) or any(K._in_name(t, n) for n in names):
                continue
            cnt[t] += 1
            where[t].add(d['n'])
    scored = []
    for t, c in cnt.items():
        if c < 2 or len(where[t]) < 2:   # 한 종목 리포트들만 쓴 말은 그 종목 이야기
            continue
        idf = math.log((n_docs + 1) / (df.get(t, 0) + 1)) + 1
        scored.append((t, c * idf, c, sorted(where[t])[:6]))
    scored.sort(key=lambda x: (-x[1], x[0]))
    out, used = [], []
    for t, _, c, ns in scored:
        if any(t in u or u in t for u in used):   # 'HBM'·'HBM4' 같은 겹침은 하나만
            continue
        used.append(t)
        out.append({'kw': t, 'n': c, 'stocks': ns})
        if len(out) >= top:
            break
    return out


def build(conn):
    rows = history(conn)
    if not rows:
        return []
    days = sorted({r['date'] for r in rows}, reverse=True)[:KEEP_DAYS]
    OUT.mkdir(parents=True, exist_ok=True)
    built = datetime.now().isoformat(timespec='seconds')
    latest = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    info, _ = market_info(conn, latest)
    info = {c: public(i) for c, i in info.items()}
    # 키워드 기준(어휘·문서 빈도)은 한 번만: 가장 오래된 표시일 90일 전부터 (날마다 다시 만들면 30배 느림)
    since = (date.fromisoformat(days[-1]) - timedelta(days=CORPUS_DAYS)).isoformat()
    corpus = [r for r in rows if r['date'] >= since]
    texts = {r['id']: report_text(r) for r in corpus}
    vocab = K.build_vocab(texts.values())
    df = K.doc_freq(K.doc_terms(t, vocab) for t in texts.values())
    for day in days:
        todays = [r for r in corpus if r['date'] == day]
        by_code = defaultdict(list)
        for r in todays:
            by_code[r['code']].append(r)
        stocks = []
        for code, reps in by_code.items():
            i = info.get(code, {})
            name = i.get('n') or reps[0]['name']
            items = []
            for r in reps:
                op = opinion(r['opinion'])
                items.append({
                    'id': r['id'], 'b': r['broker'], 't': r['title'], 'op': op, 'pop': r['pop'] if r['pop'] != op else None,
                    'g': r['goal'], 'pg': r['pg'] if r['pg'] != r['goal'] else None, 'same': bool(r['pg'] and r['pg'] == r['goal']),
                    'p': r['price'], 'h': json.loads(r['heads'] or '[]')[:3], 's': summary_of(r['body']),
                    'kw': K.report_keywords(texts[r['id']], df, len(corpus), vocab, name=name),
                    'init': r['init'], 'pdf': r['pdf'],
                })
            stocks.append({'c': code, 'n': name, 'mk': i.get('mk'), 'w': i.get('w'), 'mc': i.get('mc'),
                           'p': i.get('p'), 'ch': i.get('ch'), 'lone': any(r['lone'] for r in reps), 'r': items})
        chg = lambda it: abs(it['g'] / it['pg'] - 1) if it['g'] and it['pg'] else 0
        stocks.sort(key=lambda s: (-len(s['r']), -max(chg(x) for x in s['r']), -(s['mc'] or 0)))
        allr = [x for s in stocks for x in s['r']]
        sec = Counter(s['w'] for s in stocks if s['w'])
        summ = {
            'n': len(allr), 'stocks': len(stocks), 'brokers': len({x['b'] for x in allr}),
            'up': sum(1 for x in allr if x['g'] and x['pg'] and x['g'] > x['pg']),
            'dn': sum(1 for x in allr if x['g'] and x['pg'] and x['g'] < x['pg']),
            'keep': sum(1 for x in allr if x['same']),
            'opu': sum(1 for x in allr if x['pop'] and x['op'] and OP_RANK.get(x['op'], 1) > OP_RANK.get(x['pop'], 1)),
            'opd': sum(1 for x in allr if x['pop'] and x['op'] and OP_RANK.get(x['op'], 1) < OP_RANK.get(x['pop'], 1)),
            'init': sum(1 for x in allr if x['init']), 'lone': sum(1 for s in stocks if s['lone']),
            'sec': sec.most_common(12),
        }
        docs = [{'n': info.get(r['code'], {}).get('n') or r['name'], 'text': texts[r['id']]} for r in todays]
        names = {d['n'] for d in docs}
        write_json(OUT / f'{day}.json', {'date': day, 'built': built, 'sum': summ,
                                         'kws': day_keywords(docs, df, len(corpus), vocab, names), 'stocks': stocks})
    (OUT / 'dates.json').write_text(json.dumps(days))
    for p in OUT.glob('20*.json'):
        if p.stem not in days:
            p.unlink()
    return days


def main():
    days = build(db.connect())
    print(f"digest: {len(days)}일 ({days[-1] if days else '-'} ~ {days[0] if days else '-'})")


if __name__ == '__main__':
    main()
