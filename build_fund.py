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


def pick_report(rcepts, en, own):
    """기간 끝 en 의 값을 담은 보고서들 중 쓸 것: 그 기간의 보고서(own[rcept] == en) 가운데 가장 나중 것(기재정정이 원본을 대신한다).
    그 기간의 보고서가 없으면(수집 시작 전 기간 — 전기 열로만 있다) 가장 이른 기간의 보고서 중 가장 나중 것"""
    mine = [r for r in rcepts if own.get(r) == en]
    if mine:
        return max(mine)
    first = min(own.get(r) or '9999' for r in rcepts)
    return max(r for r in rcepts if (own.get(r) or '9999') == first)


def load(conn, code):
    """facts[(basis, topic)][item][(시작, 끝)] = 값, labels, 그리고 성격별 비용은 보고서별로:
    tables[(basis, topic)][(시작, 끝)][rcept_no][item] = (값, 이름, 순서).
    같은 기간이 여러 보고서에 나오면 **그 기간의 보고서**(정정이 있으면 정정본) 값을 쓴다. 나중 보고서의 전기 열은 재작성(중단사업 재분류 등)된 값이라,
    연간은 다음 해 사업보고서 기준·9개월 누적은 다음 해 3분기 보고서 기준처럼 시점이 섞이면 4분기(연간 − 9개월)가 어긋난다"""
    own = {r['rcept_no']: r['period_end'] for r in conn.execute('SELECT rcept_no, period_end FROM fund_report WHERE code = ?', (code,))}
    by = defaultdict(dict)                 # (basis, topic, item, 시작, 끝) → {rcept: 값}
    tables = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    labels = {}
    for r in conn.execute('SELECT basis, topic, item, label, start, end, value, ord, rcept_no FROM fund_fact WHERE code = ? ORDER BY rcept_no DESC', (code,)):
        by[(r['basis'], r['topic'], r['item'], r['start'], r['end'])][r['rcept_no']] = r['value']
        if r['topic'] != 'is':
            labels.setdefault((r['basis'], r['topic'], r['item']), (r['label'], r['ord']))      # 이름표는 가장 최근 것
        if r['topic'] in ('nature', 'nature_x'):
            tables[(r['basis'], r['topic'])][(r['start'], r['end'])][r['rcept_no']][r['item']] = (r['value'], r['label'], r['ord'])
    facts = defaultdict(lambda: defaultdict(dict))
    for (basis, topic, item, st, en), vals in by.items():
        facts[(basis, topic)][item][(st, en)] = vals[pick_report(list(vals), en, own)]
    return facts, labels, tables, own, by


def nature_periods(tables, basis, own=None):
    """기간마다 표 하나: 그 기간을 처음 보고한 보고서의 원문 표, 원문이 없으면 주석 XBRL.
    보고서마다 줄 이름이 달라서, 한 기간에 여러 보고서의 줄을 섞으면 같은 비용이 두 줄이 된다 (감가상각비 등 / 감가상각비 및 무형자산 상각).
    → (periods {(시작, 끝): {키: 값}}, meta {키: (이름, 순서)}, src {(시작, 끝): 'html'|'xbrl'}, bad {(시작, 끝): 사유})"""
    periods, meta, src, bad = {}, {}, {}, {}

    def recon(d):
        tot = d.get('total')
        return tot is None or abs(sum(v for k, v in d.items() if k != 'total') - tot) <= max(0.5, abs(tot) * 0.005)
    for topic, tag in (('nature_x', 'xbrl'), ('nature', 'html')):        # 원문이 뒤에 와서 XBRL 을 덮는다
        for pe, by_rcept in tables.get((basis, topic), {}).items():
            # 그 기간의 보고서(정정이 있으면 정정본). 그 표가 줄의 합 ≠ 합계이면 맞는 것 중에서 같은 규칙으로
            good = [r for r in by_rcept if recon({k: v for k, (v, _, _) in by_rcept[r].items()})]
            rno = pick_report(good or list(by_rcept), pe[1], own or {})
            d = {k: v for k, (v, _, _) in by_rcept[rno].items()}
            # 원문 표가 줄의 합 ≠ 합계인데(회사 원문의 줄이 밀려 있는 경우 등) 주석 XBRL 은 맞으면 XBRL 을 둔다
            if tag == 'html' and pe in periods and not recon(d) and recon(periods[pe]) and len(periods[pe]) > 3:
                continue
            periods[pe] = d
            src[pe] = tag
            for k, (_, lab, o) in by_rcept[max(by_rcept)].items():     # 줄 이름·순서는 최근 보고서 것
                meta.setdefault(k, (lab, o))
            for k, (_, lab, o) in by_rcept[rno].items():
                meta.setdefault(k, (lab, o))
    for pe in [pe for pe, d in periods.items() if src[pe] == 'xbrl' and set(d) <= {'total'}]:
        del periods[pe], src[pe]        # 주석 XBRL 에 합계만 있고 줄이 없다 (일부 항목만 표시하는 회사) — 쓰지 않는다
    for pe, d in periods.items():       # 표 하나 안에서 줄의 합 = 합계인가 (안 맞으면 그 표에서 줄을 덜 읽었거나 소계를 줄로 셌다)
        tot = d.get('total')
        s = sum(v for k, v in d.items() if k != 'total')
        if tot is not None and abs(s - tot) > max(0.5, abs(tot) * 0.005):
            bad[pe] = f'표의 줄 합 {s:.1f} ≠ 합계 {tot:.1f}'
    return periods, meta, src, bad


def company(conn, code):
    facts, labels, tables, own, by = load(conn, code)
    basis = 'C' if tables.get(('C', 'nature')) or tables.get(('C', 'nature_x')) else 'S'
    periods, meta, src, bad = nature_periods(tables, basis, own)
    if not periods:
        return None
    keys = sorted({k for d in periods.values() for k in d if k != 'total'}, key=lambda k: (meta[k][1], k))
    group_of = {k: fund.key_of(meta[k][0])[1] for k in keys}
    # 묶음: 기간마다 묶음 합을 내고(그 표에 없는 묶음은 0) 분기로 — 표마다 줄 나눔이 달라도 합이 맞는다
    gper = {pe: {g: sum(v for k, v in d.items() if k != 'total' and group_of[k] == g) for g in set(group_of.values())} for pe, d in periods.items()}
    gq = fund.quarter_series(gper, sorted(set(group_of.values())), fill=True)
    totq = {e: v for e, v in fund.quarterize({pe: d['total'] for pe, d in periods.items() if 'total' in d}).items() if e >= FROM}
    lineq = fund.quarter_series(periods, keys, fill=False)             # 원본 줄: 없는 것은 비워 둔다
    lines = {k: {'l': fund.clean_label(meta[k][0]), 'g': group_of[k], 'v': {e: v for e, v in lineq[k].items() if e >= FROM}} for k in keys}
    lines = {k: ln for k, ln in lines.items() if ln['v']}
    isf = facts.get((basis, 'is')) or facts.get(('X', 'is')) or {}
    inc = {k: {e: v for e, v in fund.quarterize(isf.get(k, {})).items() if e >= FROM} for k in ('rev', 'op', 'np', 'cogs', 'sga')}
    have = {e for g in gq.values() for e in g} | set(totq)
    ends = sorted(e for e in inc['rev'] if e in have and e >= FROM)
    if not ends:
        return None
    groups, chk, inf = {}, {}, {}
    for e in ends:
        g = {name: q[e] for name, q in gq.items() if e in q}
        tot = totq.get(e)
        s = sum(g.values())
        if tot is not None:                 # 합계가 있으면 '기타' = 합계 − 나머지 (표가 맞으면 원래 기타와 같다)
            g['기타'] = tot - sum(v for name, v in g.items() if name != '기타')
        groups[e] = g
        rev, op = inc['rev'].get(e), inc['op'].get(e)
        cs = inc['cogs'].get(e) + inc['sga'].get(e) if e in inc['cogs'] and e in inc['sga'] else None
        if cs is None and rev is not None and op is not None:
            cs = rev - op                    # 손익계산서에 매출원가·판관비 구분이 없는 회사: 매출 − 영업이익
        msg = []
        used = [pe for pe in periods if pe[1] == e or (pe[1] == fund.months_back(e, 3) and fund._months(*pe) > 0)]
        tb = [bad[pe] for pe in periods if pe[1] == e and pe in bad]
        if tot is not None and abs(s - tot) > max(0.5, abs(tot) * 0.005):
            msg.append(f'줄의 합 {s:.1f} ≠ 합계 {tot:.1f}' + (f' ({tb[0]})' if tb else ''))
        if tot is not None and rev is not None and op is not None and abs(rev - tot - op) > max(1.0, abs(rev) * 0.01):
            ok_table = abs(s - tot) <= max(0.5, abs(tot) * 0.005) and not tb
            if cs is not None and abs(tot - cs) <= max(1.0, abs(cs) * 0.005):
                # 주석 합계 = 손익계산서 매출원가 + 판관비. 영업이익이 그것과 다르면 회사가 영업이익에 다른 항목(기타영업손익 등)을 넣은 것
                inf[e] = f'영업이익 {op:.1f} = 매출 − 매출원가·판관비 {rev - tot:.1f} + 그 밖의 영업손익 {op - (rev - tot):.1f} (회사 손익계산서 구성)'
            elif cs is not None and ok_table and abs(tot - cs) <= abs(cs) * 0.15:
                # 표는 줄의 합 = 합계로 맞게 읽혔는데 합계가 매출원가+판관비와 다르다: 회사가 주석에 넣는 비용의 범위가 다르다 (기타비용·연구개발비 등)
                inf[e] = f'주석 합계 {tot:.1f} 가 손익계산서 매출원가+판관비 {cs:.1f} 보다 {tot - cs:+.1f} — 회사가 주석에 넣는 비용 범위가 다름 (표는 줄의 합 = 합계)'
            else:
                msg.append(f'매출 − 비용합계 {rev - tot:.1f} ≠ 영업이익 {op:.1f}' + (f' · 주석 합계가 매출원가+판관비 {cs:.1f} 와 {tot - cs:+.1f} 다름' if cs is not None else ''))
        if tot is None:
            msg.append('이 분기의 합계를 만들 수 없음 (앞 분기 누적이 없음)')
        if msg:
            chk[e] = ' · '.join(msg)
    gnames = [g for g in fund.GROUP_ORDER if any(abs(groups[e].get(g, 0.0)) > 0.05 for e in ends)]
    order = [k for k in keys if k in lines]
    reps = {r['period_end']: r['rcept_no'] for r in conn.execute(
        'SELECT period_end, rcept_no FROM fund_report WHERE code = ? ORDER BY rcept_no', (code,))}
    r1 = lambda v: None if v is None else round(v, 1)
    return {
        'c': code, 'basis': '연결' if basis == 'C' else '별도', 'q': ends, 'ql': [fund.qlabel(e) for e in ends],
        'rev': [r1(inc['rev'].get(e)) for e in ends], 'op': [r1(inc['op'].get(e)) for e in ends], 'np': [r1(inc['np'].get(e)) for e in ends],
        'tot': [r1(totq.get(e)) for e in ends],
        'lines': [{'k': k, 'l': lines[k]['l'], 'g': lines[k]['g'], 'v': [r1(lines[k]['v'].get(e)) for e in ends]} for k in order],
        'groups': [{'g': g, 'fix': g in fund.FIXED, 'v': [r1(groups[e].get(g)) for e in ends]} for g in gnames],
        'xb': sorted(e for e in ends if any(pe[1] == e and src[pe] == 'xbrl' for pe in periods)),      # 주석 XBRL 로 채운 분기
        'chk': chk, 'inf': inf, 'rep': {e: reps[e] for e in ends if e in reps},
        'seg': segments(by, own, basis, inc),
        '_groups': groups, '_inc': inc,
    }


def segments(by, own, basis, inc):
    """부문·제품·지역 보기 [{k, name, q, ql, m: [{n, rev, op}], adj, tot, chk, inf}] — 주석 XBRL 이 있는 기간만 (없으면 빈 목록).
    by = {(basis, topic, item, 시작, 끝): {rcept: 값}}, item = '분류¦이름'.
    - 한 기간은 한 보고서의 줄만 (그 기간의 보고서, pick_report). 보고서마다 부문 구성·이름표가 달라 섞으면 같은 매출을 두 번 센다
    - 같은 기간이 두 보고서에 있을 때 값이 같은 줄끼리 이름을 잇는다 (fund.rename_map)
    - 분류가 여러 벌이면 전체 매출과 가장 잘 맞는 한 벌만
    - 전체 매출은 그 줄들을 가져온 보고서의 것으로 맞춘다 (전기 열로만 있는 기간은 재작성된 매출과 비교해야 맞다)"""
    out = []
    r1 = lambda v: None if v is None else round(v, 1)

    def tables_of(topic):
        t = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))        # 분류 → (시작, 끝) → rcept → {이름: 값}
        for (b, tp, item, st, en), vals in by.items():
            if b == basis and tp == topic and '¦' in item:
                g, n = item.split('¦', 1)
                for r, v in vals.items():
                    t[g][(st, en)][r][fund.seg_name(n)] = v
        return t

    def series(tb, ren=None):
        """한 분류의 {(시작, 끝): {rcept: {이름: 값}}} → ({이름: {(시작, 끝): 값}}, {(시작, 끝): rcept})"""
        ren = fund.rename_map(tb) if ren is None else ren
        vals, src = defaultdict(dict), {}
        # 회계연도마다 한 시점의 값으로: 그해 기간들이 전부 그 기간 보고서에 있으면 그것, 하나라도 없으면(주석 XBRL 을 그해 중간·이듬해에 시작한 회사)
        # 그해 기간은 전부 이듬해 보고서의 전기 열로 — 섞으면 4분기(연간 − 앞 분기)가 부문 개편 전후 값의 차가 된다
        years = defaultdict(list)
        for pe in tb:
            years[pe[1][:4]].append(pe)
        comp = set()
        for y, pes in years.items():
            if not all(any(own.get(r) == pe[1] for r in tb[pe]) for pe in pes):
                comp.update(pes)
        for pe, byr in tb.items():
            later = [r for r in byr if (own.get(r) or '') > pe[1]]
            if pe in comp and later:
                first = min(own[r] for r in later)
                r = max(x for x in later if own[x] == first)
            else:
                r = pick_report(list(byr), pe[1], own)
            src[pe] = r
            for n, v in byr[r].items():
                vals[ren.get(n, n)][pe] = v
        vals = fund.merge_similar(vals, {n: max(en for _, en in vs) for n, vs in vals.items()})     # Harman/Haman
        for n in vals:                      # 내부거래 제거 전(조정이 따로 있는 기간)과 제거 후 값은 서로 뺄 수 없다 → 그해 연간 값을 뺀다 (4분기는 비워 둔다)
            for pe in [pe for pe in vals[n] if pe in gross_only]:
                del vals[n][pe]
        return vals, src, ren

    gross_only = set()
    for view in ('seg', 'prod', 'geo'):
        rt, ot = tables_of(f'{view}:rev'), tables_of(f'{view}:op')
        gross_only = set()
        adjv, _, _ = series(rt.pop('', {}))
        adjo, _, _ = series(ot.pop('', {}))
        if view == 'seg':                   # 연간에만 조정이 있고 같은 해 분기·누적 기간에는 조정이 0/없음 → 연간은 제거 전, 분기는 제거 후 값
            a = adjv.get('조정', {})
            for pe, v in a.items():
                if fund._months(*pe) == 12 and abs(v) >= 0.05:
                    same = [w for q, w in a.items() if q[1][:4] == pe[1][:4] and q != pe]
                    if same and all(abs(w) < 0.05 for w in same):
                        gross_only.add(pe)
        # 조정: 누적 값이 0 으로만 들어간 기간은 표시하지 않은 것으로 본다 (1분기·연간에만 조정을 적고 반기·3분기는 0 인 회사)
        nz = lambda d: {pe: v for pe, v in d.items() if abs(v) >= 0.05} if any(abs(v) >= 0.05 for v in d.values()) else d
        adj, adjop = fund.quarterize(nz(adjv.get('조정', {}))), fund.quarterize(nz(adjo.get('조정', {})))
        best = None
        for g, tb in rt.items():
            vals, src, ren = series(tb)
            rev = {n: {e: v for e, v in fund.quarterize(vs).items() if e >= FROM} for n, vs in vals.items()}
            rev = {n: q for n, q in rev.items() if q}
            names = fund.pick_members(rev)
            # 그 줄들을 가져온 보고서의 매출 (없으면 그 기간 보고서의 매출)
            revv = {}
            for pe, r in src.items():
                v = (by.get((basis, 'is', 'rev', *pe)) or by.get(('X', 'is', 'rev', *pe)) or {}).get(r)
                if v is not None:
                    revv[pe] = v
            vint = {e: v for e, v in fund.quarterize(revv).items() if e >= FROM}
            use_adj0 = adj if view == 'seg' else {}
            tot = dict(inc['rev'])
            for e, v in vint.items():            # 그 기간 보고서의 매출과 안 맞고 줄을 가져온 보고서의 매출과는 맞을 때만 그쪽 매출로
                ssum = sum(rev[n].get(e) or 0.0 for n in names) + (use_adj0.get(e) or 0.0)
                own_ok = e in tot and abs(ssum - tot[e]) <= max(1.0, abs(tot[e]) * 0.02)
                if not own_ok and (e not in tot or abs(ssum - v) <= max(1.0, abs(v) * 0.02)):
                    tot[e] = v
            ends = sorted({e for n in names for e in rev[n]} & set(tot))
            if len(names) < 2 or not ends:
                continue
            use_adj = adj if view == 'seg' else {}

            def check(ns):
                chk, inf = {}, {}
                for e in ends:
                    w, i = fund.seg_verdict({n: rev[n].get(e) for n in ns}, use_adj.get(e), tot.get(e), has_adj_elsewhere=bool(use_adj))
                    if w:
                        chk[e] = w
                    elif i and view != 'prod':          # 제품 보기는 주요 제품만 적는 회사가 많아 모자란 것은 말하지 않는다
                        inf[e] = i
                return chk, inf
            chk, inf = check(names)
            if len(chk) * 2 >= len(ends):       # 절반 넘게 넘치면: 한 표에 분류가 두 벌일 수 있다 → 전체 매출과 맞는 줄 묶음만
                sub = fund.best_subset(rev, names, use_adj, tot, ends)
                if sub:
                    names = sub
                    ends = sorted({e for n in names for e in rev[n]} & set(tot))
                    chk, inf = check(names)
            score = (len(ends) - len(chk) - len(inf), -len(chk), len(names))      # 맞는 분기가 많은 벌
            if best is None or score > best[0]:
                best = (score, g, rev, names, ends, chk, inf, tot, ren)
        if not best:
            continue
        _, g, rev, names, ends, chk, inf, tot, ren = best
        opv, _, _ = series(ot.get(g, {}), ren)
        op = {n: fund.quarterize(vs) for n, vs in opv.items()}
        names.sort(key=lambda n: -(rev[n].get(ends[-1]) or 0))
        out.append({'k': view, 'name': fund.VIEW_NAME[view], 'q': ends, 'ql': [fund.qlabel(e) for e in ends],
                    'm': [{'n': n, 'rev': [r1(rev[n].get(e)) for e in ends],
                           'op': [r1(op[n].get(e)) for e in ends] if n in op and any(e in op[n] for e in ends) else None} for n in names],
                    'adj': [r1(adj.get(e)) for e in ends] if view == 'seg' and any(e in adj for e in ends) else None,
                    'adjop': [r1(adjop.get(e)) for e in ends] if view == 'seg' and any(e in adjop for e in ends) else None,
                    'tot': [r1(tot.get(e)) for e in ends], 'chk': chk, 'inf': inf, 'sets': len(rt)})
    return out


def attach_seg_reports(main, code, d):
    """부문 이름이 든 리포트 문장 {분기 끝: [{d, b, t, pdf, s: [[이름, 문장]…]}]} (부문 보기 → 없으면 제품 보기의 이름으로)"""
    views = {v['k']: v for v in d.get('seg') or []}
    v = views.get('seg') or views.get('prod')
    if not v:
        return {}
    names = [m['n'] for m in v['m']] + ([m['n'] for m in views['prod']['m']] if 'prod' in views and v['k'] != 'prod' else [])
    ends = d['q'] + [fund.months_back(d['q'][-1], -3)]
    ev = defaultdict(list)
    for r in main.execute('SELECT date, broker, title, heads, body, pdf FROM research WHERE code = ? ORDER BY date DESC', (code,)):
        q = fund.quarter_of_report(r['date'], ends)
        if not q or len(ev[q]) >= 5:
            continue
        s = fund.mentions('\n'.join(json.loads(r['heads'] or '[]') + [r['body'] or '']), names)
        if s:
            ev[q].append({'d': r['date'], 'b': r['broker'], 't': r['title'], 'pdf': r['pdf'], 's': [[n, t] for n, t in s]})
    return dict(ev)


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
    from collect_fund import WATCH
    w = json.loads(WATCH.read_text(encoding='utf-8')) if WATCH.exists() else {}
    idx_of = w.get('index', {})                    # 코스피200·코스닥150 구성 (화면 필터)
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
                  'ev': attach_reports(main, code, d), 'cns': attach_cns(main, code, d), 'earn': attach_earn(code, d),
                  'sev': attach_seg_reports(main, code, d)})
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
                      'top': [[g, round(v, 1)] for g, v in br[:2] if abs(v) >= 0.3],
                      'chk': len(d['chk']) + sum(len(v['chk']) for v in d['seg']),
                      'ev': sum(len(v) for v in d['ev'].values()), 'cns': bool(d['cns']['next']),
                      'seg': [v['name'] for v in d['seg']], 'ix': idx_of.get(code, [])})
    for p in OUT.glob('*.json'):
        if p.stem != 'index' and p.stem not in {x['c'] for x in index}:
            p.unlink()
    pending = [c for c in w.get('codes', []) if c not in {x['c'] for x in index} and c not in {x['c'] for x in skipped}]
    write_json(OUT / 'index.json', {'built': built, 'stocks': index, 'skipped': skipped, 'pending': len(pending),
                                     'ix_as_of': w.get('index_as_of')})
    return len(index)


def main():
    print(f'fund: {build()}종목')


if __name__ == '__main__':
    main()
