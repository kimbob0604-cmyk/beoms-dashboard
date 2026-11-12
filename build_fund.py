"""
펀더 JSON: public/data/fund/{code}.json (종목별 분기 비용 구조) · fund/index.json (목록)

- 분기 값: 원문 주석(nature)과 주석 XBRL(nature_x)을 합쳐(원문 우선) fund.quarterize — 3개월 값 우선, 없으면 누적 차감
- 연결이 있으면 연결, 없으면 별도. 둘을 섞지 않는다
- 검증: 줄의 합 = 합계, 매출 − 합계 = 영업이익. 어긋난 분기는 chk 에 남긴다 (숨기지 않는다)
- 리포트와 잇기: 분기마다 그 분기를 다룬 증권사 리포트의 요인 문장(ev), 다음 분기 컨센서스와 비용 구조 모델(cns), 실적 발표 덱의 서프/미스(earn)

  python3 build_fund.py
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime

import db
import fund
from build_naver import DATA, market_info, write_json
from collect_fund import DB, connect

OUT = DATA / 'fund'
FROM = '2023-01-01'
EARN_DB = DB.parent / 'earn.db'


def load(conn, code):
    facts = defaultdict(lambda: defaultdict(dict))      # (basis, topic) → item → {(start, end): value}
    labels = {}
    for r in conn.execute('SELECT basis, topic, item, label, start, end, value, ord FROM fund_fact WHERE code = ? ORDER BY rcept_no', (code,)):
        facts[(r['basis'], r['topic'])][r['item']][(r['start'], r['end'])] = r['value']
        if r['topic'] != 'is':
            labels[(r['basis'], r['topic'], r['item'])] = (r['label'], r['ord'])
    return facts, labels


def company(conn, code):
    facts, labels = load(conn, code)
    basis = 'C' if facts.get(('C', 'nature')) or facts.get(('C', 'nature_x')) else 'S'
    if not (facts.get((basis, 'nature')) or facts.get((basis, 'nature_x'))):
        return None
    html, xb = facts.get((basis, 'nature'), {}), facts.get((basis, 'nature_x'), {})
    # 한 기간에는 한 출처만: 원문 값이 있는 (시작, 끝)에는 주석 XBRL 값을 섞지 않는다 (줄 이름이 달라 같은 비용이 두 줄이 된다)
    hp = {pe for v in html.values() for pe in v}
    xb = {item: {pe: v for pe, v in vs.items() if pe not in hp} for item, vs in xb.items()}
    xb = {item: vs for item, vs in xb.items() if vs}
    lines = {}
    for item in set(html) | set(xb):
        vals = {**xb.get(item, {}), **html.get(item, {})}
        q = {e: v for e, v in fund.quarterize(vals).items() if e >= FROM}
        if not q:
            continue
        lab, ord_ = labels.get((basis, 'nature', item)) or labels.get((basis, 'nature_x', item))
        lines[item] = {'l': fund.clean_label(lab), 'g': fund.key_of(lab)[1] if item != 'total' else '비용합계', 'o': ord_, 'v': q,
                       'x': sorted(e for e in q if not any(en == e for _, en in html.get(item, {})))}   # XBRL 로만 채운 분기
    isf = facts.get((basis, 'is')) or facts.get(('X', 'is')) or {}
    inc = {k: {e: v for e, v in fund.quarterize(isf.get(k, {})).items() if e >= FROM} for k in ('rev', 'op', 'np', 'cogs', 'sga')}
    ends = sorted(e for e in inc['rev'] if any(e in ln['v'] for ln in lines.values()))
    if not ends:
        return None
    # 줄은 표에 나온 순서(최근 보고서 기준), 합계는 따로
    order = sorted((k for k in lines if k != 'total'), key=lambda k: (lines[k]['o'], k))
    chk = {}
    for e in ends:
        tot = (lines.get('total') or {'v': {}})['v'].get(e)
        s = sum(lines[k]['v'].get(e, 0.0) for k in order)
        rev, op = inc['rev'].get(e), inc['op'].get(e)
        msg = []
        if tot is not None and abs(s - tot) > max(0.5, abs(tot) * 0.005):
            msg.append(f'줄의 합 {s:.1f} ≠ 합계 {tot:.1f}')
        if tot is not None and rev is not None and op is not None and abs(rev - tot - op) > max(1.0, abs(rev) * 0.01):
            msg.append(f'매출 − 비용합계 {rev - tot:.1f} ≠ 영업이익 {op:.1f}')
        if msg:
            chk[e] = ' · '.join(msg)
    groups = {e: fund.grouped(lines, e) for e in ends}
    gnames = [g for g in fund.GROUP_ORDER if any(abs(groups[e].get(g, 0.0)) > 0.05 for e in ends)]
    reps = {r['period_end']: r['rcept_no'] for r in conn.execute(
        'SELECT period_end, rcept_no FROM fund_report WHERE code = ? ORDER BY rcept_no', (code,))}
    r1 = lambda v: None if v is None else round(v, 1)
    return {
        'c': code, 'basis': '연결' if basis == 'C' else '별도', 'q': ends, 'ql': [fund.qlabel(e) for e in ends],
        'rev': [r1(inc['rev'].get(e)) for e in ends], 'op': [r1(inc['op'].get(e)) for e in ends], 'np': [r1(inc['np'].get(e)) for e in ends],
        'tot': [r1((lines.get('total') or {'v': {}})['v'].get(e)) for e in ends],
        'lines': [{'k': k, 'l': lines[k]['l'], 'g': lines[k]['g'], 'v': [r1(lines[k]['v'].get(e)) for e in ends]} for k in order],
        'groups': [{'g': g, 'fix': g in fund.FIXED, 'v': [r1(groups[e].get(g)) for e in ends]} for g in gnames],
        'xb': sorted({e for ln in lines.values() for e in ln['x']} & set(ends)),      # 주석 XBRL 로 채운 분기
        'chk': chk, 'rep': {e: reps[e] for e in ends if e in reps},
        '_groups': groups, '_inc': inc,
    }


def attach_reports(main, code, d):
    """그 분기를 다룬 증권사 리포트의 요인 문장 {분기 끝: [{d, b, t, id, pdf, s: [[요인들, 문장]…]}]}"""
    ev = defaultdict(list)
    # 다음 분기 프리뷰도 붙도록 끝에 다음 분기 끝을 하나 더 둔다
    ends = d['q'] + [fund.months_back(d['q'][-1], -3)]
    for r in main.execute('SELECT id, date, broker, title, heads, body, pdf FROM research WHERE code = ? ORDER BY date DESC', (code,)):
        q = fund.quarter_of_report(r['date'], ends)
        if not q:
            continue
        text = '\n'.join([r['title'] or ''] + json.loads(r['heads'] or '[]') + [r['body'] or ''])
        s = fund.evidence(text)
        if s and len(ev[q]) < 6:
            ev[q].append({'d': r['date'], 'b': r['broker'], 't': r['title'], 'id': r['id'], 'pdf': r['pdf'], 's': [[g, t] for g, t in s]})
    return dict(ev)


def attach_cns(main, code, d):
    """아직 실적이 안 나온 분기의 컨센서스와, 비용 구조를 그대로 둔 모델 [{p, pl, sales, op, m: fund.model}]"""
    last = d['q'][-1]
    as_of = main.execute('SELECT MAX(as_of) FROM cns_quarter WHERE code = ?', (code,)).fetchone()[0]
    hist = [(d['_inc']['rev'].get(e), d['_groups'][e]) for e in d['q']]
    out = []
    for r in main.execute('SELECT period, sales, op FROM cns_quarter WHERE code = ? AND as_of = ? ORDER BY period', (code, as_of or '')):
        y, m = int(r['period'][:4]), int(r['period'][4:6])
        end = fund.months_back(f'{y + (m == 12)}-{m % 12 + 1:02d}-28', 1)
        if end <= last or not r['sales']:
            continue
        out.append({'p': end, 'pl': fund.qlabel(end), 'sales': r['sales'], 'op': r['op'], 'm': fund.model(hist, r['sales'])})
    base = fund.model(hist, d['_inc']['rev'].get(last) or 0)      # 컨센서스가 없어도 직전 분기 매출로 기본값
    return {'as_of': as_of, 'next': out[:2], 'base': base}


def attach_earn(code, d):
    """실적 발표 덱의 서프/미스 {분기 끝: {ts, sr, or, case}}"""
    if not EARN_DB.exists():
        return {}
    import earn
    conn = sqlite3.connect(f'file:{EARN_DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    out = {}
    for p in conn.execute("SELECT * FROM earn_post WHERE code = ? AND period IS NOT NULL AND (se IS NOT NULL OR oe IS NOT NULL) ORDER BY ts", (code,)):
        p = dict(p)
        if earn.first_release(p) is False:
            continue
        y, qn = int(p['period'][:4]), int(p['period'][5])
        end = fund.months_back(f'{y + (qn == 4)}-{(qn * 3) % 12 + 1:02d}-28', 1)
        if end in d['q'] and end not in out:
            st, ot = earn.tag(p['s'], p['se'], earn.SALES_T), earn.tag(p['o'], p['oe'], earn.OP_T)
            out[end] = {'ts': p['ts'], 'sr': earn.ratio(p['s'], p['se']), 'or': earn.ratio(p['o'], p['oe']), 'case': earn.case_of(st, ot)}
    return out


def build():
    conn = connect()
    main = db.connect()
    day = main.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    info, _ = market_info(main, day)
    OUT.mkdir(parents=True, exist_ok=True)
    index, built = [], datetime.now().isoformat(timespec='seconds')
    codes = [r[0] for r in conn.execute('SELECT DISTINCT code FROM fund_report ORDER BY code')]
    skipped = []
    for code in codes:
        d = company(conn, code)
        if not d:      # 보고서는 받았는데 표가 없다 — 대개 성격별 분류를 공시하지 않는 회사(기능별 공시만)
            n = conn.execute('SELECT COUNT(*) FROM fund_report WHERE code = ?', (code,)).fetchone()[0]
            skipped.append({'c': code, 'n': info.get(code, {}).get('n') or code, 'r': n})
            continue
        i = info.get(code, {})
        d.update({'n': i.get('n') or code, 'mk': i.get('mk'), 'mc': i.get('mc'), 'built': built,
                  'ev': attach_reports(main, code, d), 'cns': attach_cns(main, code, d), 'earn': attach_earn(code, d)})
        groups, inc = d.pop('_groups'), d.pop('_inc')
        write_json(OUT / f'{code}.json', d)
        e = d['q'][-1]
        opm = lambda x: (inc['op'][x] / inc['rev'][x] * 100) if inc['op'].get(x) is not None and inc['rev'].get(x) else None
        p1, p4 = fund.months_back(e, 3), fund.months_back(e, 12)
        br = fund.bridge(groups.get(p1, {}), inc['rev'].get(p1), groups[e], inc['rev'].get(e)) if p1 in groups else []
        index.append({'c': code, 'n': d['n'], 'mk': d['mk'], 'mc': d['mc'], 'w': i.get('w'), 'ql': d['ql'][-1], 'nq': len(d['q']),
                      'rev': d['rev'][-1], 'op': d['op'][-1], 'opm': opm(e) and round(opm(e), 1),
                      'dq': None if opm(e) is None or opm(p1) is None else round(opm(e) - opm(p1), 1),
                      'dy': None if opm(e) is None or opm(p4) is None else round(opm(e) - opm(p4), 1),
                      'top': [[g, round(v, 1)] for g, v in br[:2] if abs(v) >= 0.3], 'chk': bool(d['chk']),
                      'ev': sum(len(v) for v in d['ev'].values()), 'cns': bool(d['cns']['next'])})
    for p in OUT.glob('*.json'):
        if p.stem != 'index' and p.stem not in {x['c'] for x in index}:
            p.unlink()
    write_json(OUT / 'index.json', {'built': built, 'stocks': index, 'skipped': skipped})
    return len(index)


def main():
    print(f'fund: {build()}종목')


if __name__ == '__main__':
    main()
