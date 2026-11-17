"""
반도체 밸류체인 탭 JSON (docs/semi-plan.md) → public/data/semi.json

- 칸·종목: semi_assets.json
- 국내 종목: 펀더(fund.db)의 손익 줄(매출·영업이익)을 분기로 — 비용 주석을 못 찾은 회사도 손익은 있다.
  시총·업종은 market_info, @darthacking 서프/미스, 최근 1년 단일판매·공급계약(dart_filing 의 파싱 값)
- 해외 종목: collect_semi.py 가 받은 db/semi.db (분기 매출·영업이익·capex, 회사 통화 백만)
- 칸 요약: 최근 분기 매출 YoY·OPM 중앙값, 서프/미스 수, 최근 90일 수주
- 수요: 하이퍼스케일러 capex 분기 합계 (달러)
"""
import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

import db
import fund
from build_fund import attach_earn, latest_earn, load
from build_naver import DATA, market_info, write_json
from collect_fund import connect as fund_connect
from collect_semi import ASSETS, DB as SEMI_DB, cal_q, connect as semi_connect

OUT = DATA / 'semi.json'
AI_FILE = Path(__file__).parent / 'semi_ai.json'
FABS_FILE = Path(__file__).parent / 'semi_fabs.json'
NQ = 12                       # 분기 몇 개를 보여 줄지
CLOUD = ('MSFT', 'GOOGL', 'AMZN', 'META', 'ORCL')       # 빅테크 capex 합계 (코어위브는 따로)


def quarters(last: str, n: int = NQ) -> list:
    """'2026Q3' 에서 거슬러 n 개 (오래된 것부터)"""
    y, q = int(last[:4]), int(last[5])
    out = []
    for _ in range(n):
        out.append(f'{y}Q{q}')
        y, q = (y, q - 1) if q > 1 else (y - 1, 4)
    return out[::-1]


def prev_year(cq: str) -> str:
    return f'{int(cq[:4]) - 1}{cq[4:]}'


def domestic(fconn, code: str) -> dict:
    """펀더 손익 → {metric: {cq: 억원}}, 기준(연결/별도)"""
    facts, *_ = load(fconn, code)
    # 연결 → 별도로 바뀐 회사(자회사 정리)가 있어 최근 분기까지 이어지는 기준을 쓴다 (같으면 연결)
    last = lambda b: max((pe[1] for pe in ((facts.get((b, 'is')) or {}).get('rev') or {})), default='')
    basis = 'C' if last('C') and last('C') >= last('S') else 'S'
    isf = facts.get((basis, 'is')) or {}
    out = {}
    for k in ('rev', 'op'):
        out[k] = {cal_q(e): v for e, v in fund.quarterize(isf.get(k, {})).items()}
    return out, '연결' if basis == 'C' else '별도'


CUST = [   # 계약상대 → 고객 묶음 (위에서부터 처음 맞는 것)
    ('SK하이닉스', r'SK ?하이닉스|에스케이하이닉스|SK ?hynix'),
    ('삼성전자', r'삼성전자|Samsung (Electronics|Austin)'),
    ('마이크론', r'Micron|마이크론'),
    ('TSMC', r'TSMC|Taiwan Semiconductor'),
    ('중국 메모리', r'CXMT|ChangXin|창신|YMTC|Yangtze|长鑫|长江'),
    ('인텔', r'\bIntel\b|인텔'),
    ('해외 반도체(비공개)', r'해외.*(반도체|메모리|Memory|NAND|DRAM|파운드리|Foundry|OSAT)'),
    ('국내 반도체(비공개)', r'국내.*(반도체|메모리|Probe|프로브)'),
    ('디스플레이', r'디스플레이|Display|BOE|CSOT'),
    ('배터리·에너지', r'SDI|에너지솔루션|SK ?온|배터리|Battery|Energy|BESS|태양광|풍력|Orsted'),
    ('전력·건설', r'전력|송전|Power|Electric|National Grid|건설|물산|엔지니어링|Engineering|E&C|조합|재개발|리모델링|개발'),
    ('비공개', r'글로벌 대형|영업비밀|비공개|미공개'),
]


def cust_of(party: str, region: str = '') -> str:
    if not party:
        return '미상'
    for k, pat in CUST:
        if re.search(pat, party, re.I):
            return k
    if re.search(r'영업비밀|비공개|미공개', party):
        return '비공개'
    return '기타'


def contracts(main, codes, since: str) -> dict:
    """{code: [{d, x(해지), amt(억), pct, party, cust(고객 묶음), name, end, r}]} — 단일판매·공급계약 5년치(semi.db orders) + 최근 날짜별 수집(dart_filing).
    정정 공시는 같은 계약(같은 회사·상대·시작일)의 앞 공시를 대신한다"""
    rows = {}
    q1 = ('SELECT date, code, kind, data, rcept_no, fixed FROM dart_filing WHERE kind IN ("contract", "contract_x") AND date >= ? '
          f'AND code IN ({",".join("?" * len(codes))})')
    src = list(main.execute(q1, (since, *codes)))
    try:
        so = sqlite3.connect(str(SEMI_DB))
        so.row_factory = sqlite3.Row
        src += list(so.execute('SELECT date, code, kind, data, rcept_no, fixed FROM orders WHERE kind IN ("contract", "contract_x") AND date >= ?', (since,)))
    except sqlite3.OperationalError:
        pass
    for r in src:
        try:
            x = json.loads(r['data'] or '{}')
        except ValueError:
            continue
        party = (x.get('party') or '').strip() or None
        rows[r['rcept_no']] = {'fx': bool(r['fixed']), 'c': r['code'], 'd': r['date'], 'x': r['kind'] == 'contract_x', 'amt': round(x['amt'] / 1e8, 1) if x.get('amt') else None,
                               'pct': x.get('pct'), 'party': party, 'cust': cust_of(party or '', x.get('region') or ''),
                               'name': (x.get('name') or '').strip() or None, 'start': x.get('start'), 'end': x.get('end'), 'r': r['rcept_no']}
    keep = dedupe_fixed([rows[k] for k in sorted(rows)], lambda v: (v['c'], v['party'], v['start'], v['x']))
    out = {}
    for v in sorted(keep, key=lambda v: v['d'], reverse=True):
        v.pop('fx', None)
        out.setdefault(v.pop('c'), []).append(v)
    return out


def dedupe_fixed(rows: list, key) -> list:
    """접수 순 rows 에서 정정 공시만 같은 key 의 앞 공시를 대신한다 (정정이 아닌 별개 공시는 key 가 같아도 둘 다 둔다)"""
    out, last = [], {}
    for v in rows:
        k = key(v)
        if v.get('fx') and k in last:
            prev = out[last[k]]
            out[last[k]] = {**v, **{f: prev[f] for f in ('amt', 'pct', 'party', 'cust', 'name', 'purpose', 'start', 'end') if f in prev and v.get(f) in (None, '', '미상')}}
        else:
            last[k] = len(out)
            out.append(v)
    return out


def facilities(codes, since: str) -> list:
    """신규시설투자등 공시 [{c, n, d, amt(억), pct(자기자본 대비), purpose, start, end, r}] — 금액 큰 순이 아니라 최근 순"""
    try:
        so = sqlite3.connect(str(SEMI_DB))
        so.row_factory = sqlite3.Row
        rs = list(so.execute('SELECT code, name, date, data, rcept_no, fixed FROM orders WHERE kind = "facility" AND date >= ? ORDER BY rcept_no', (since,)))
    except sqlite3.OperationalError:
        return []
    vs = []
    for r in rs:
        x = json.loads(r['data'] or '{}')
        vs.append({'fx': bool(r['fixed']), 'c': r['code'], 'n': r['name'], 'd': r['date'], 'amt': round(x['amt'] / 1e8) if x.get('amt') else None, 'pct': x.get('pct'),
                   'purpose': x.get('purpose'), 'start': x.get('start'), 'end': x.get('end'), 'r': r['rcept_no']})
    keep = dedupe_fixed(vs, lambda v: (v['c'], v['purpose'], v['start'], v['end']))
    for v in keep:
        v.pop('fx', None)
    return sorted((v for v in keep if v['c'] in codes), key=lambda v: v['d'], reverse=True)


def stats(series: dict, cq: str) -> dict:
    """최근 분기 cq 의 매출·영업이익·OPM·YoY"""
    rev, op = series.get('rev', {}), series.get('op', {})
    r, o, r4, o4 = rev.get(cq), op.get(cq), rev.get(prev_year(cq)), op.get(prev_year(cq))
    opm = o / r * 100 if r and o is not None else None
    opm4 = o4 / r4 * 100 if r4 and o4 is not None else None
    return {'yoy': (r / r4 - 1) * 100 if r and r4 and r4 > 0 else None,
            'opm': opm, 'dopm': opm - opm4 if opm is not None and opm4 is not None else None,
            'oyoy': (o / o4 - 1) * 100 if o is not None and o4 and o4 > 0 else None}


def yoy_series(ser: dict) -> dict:
    """{cq: 값} → {cq: 전년 대비 %}"""
    return {cq: (v / ser[prev_year(cq)] - 1) * 100 for cq, v in ser.items() if ser.get(prev_year(cq)) and ser[prev_year(cq)] > 0 and v is not None}


def shift(cq: str, k: int) -> str:
    """cq 에서 k 분기 앞"""
    y, q = int(cq[:4]), int(cq[5])
    n = y * 4 + q - 1 - k
    return f'{n // 4}Q{n % 4 + 1}'


def corr(a: list, b: list):
    n = len(a)
    if n < 6:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    return None if not va or not vb else sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb)


def lag_table(cell_rev: dict, drivers: dict, lags=(0, 1, 2, 3)) -> dict:
    """칸 매출 YoY 와 수요 지표 YoY(k 분기 앞)의 상관 {지표: {'r': [k별], 'n': [k별], 'best': k}}"""
    cy = yoy_series(cell_rev)
    out = {}
    for name, dser in drivers.items():
        dy = yoy_series(dser)
        rs, ns = [], []
        for k in lags:
            pts = [(cy[cq], dy[shift(cq, k)]) for cq in cy if shift(cq, k) in dy]
            r = corr([p[0] for p in pts], [p[1] for p in pts])
            rs.append(None if r is None else round(r, 2))
            ns.append(len(pts))
        ok = [(r, k) for r, k in zip(rs, lags) if r is not None]
        out[name] = {'r': rs, 'n': ns, 'best': max(ok)[1] if ok else None}
    return out


def r1(v):
    return None if v is None else round(v, 1)


def fabs_out(fac: list) -> dict:
    """증설 트래커(semi_fabs.json) + 연결한 DART 신규시설투자 공시의 금액·기간"""
    if not FABS_FILE.exists():
        return {}
    f = json.loads(FABS_FILE.read_text(encoding='utf-8'))
    by_r = {x['r']: x for x in fac}
    for x in f.get('fabs', []):
        x['dart'] = [{**d, **{k: by_r[d['r']].get(k) for k in ('d', 'amt', 'purpose', 'start', 'end')}} for d in x.get('dart', []) if d['r'] in by_r]
    return {k: f.get(k) for k in ('as_of', 'note', 'fabs', 'capex', 'cycle', 'stage_order')}


def build():
    a = json.loads(ASSETS.read_text(encoding='utf-8'))
    main = db.connect()
    day = main.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    info, _ = market_info(main, day)
    fconn = fund_connect()
    sconn = semi_connect()
    sconn.row_factory = sqlite3.Row
    fund_idx = {}
    fi = DATA / 'fund' / 'index.json'
    if fi.exists():
        fund_idx = {s['c']: s for s in json.loads(fi.read_text(encoding='utf-8'))['stocks']}
    codes = [s['code'] for s in a['stocks'] if s.get('code')]
    con = contracts(main, codes, (date.today() - timedelta(days=365 * 5 + 30)).isoformat())
    fac = facilities(set(codes), (date.today() - timedelta(days=365 * 5 + 30)).isoformat())

    # 해외: semi.db
    ov, meta = {}, {r['tk']: dict(r) for r in sconn.execute('SELECT * FROM ov_meta')}
    for r in sconn.execute('SELECT tk, cq, metric, value FROM ov_q'):
        ov.setdefault(r['tk'], {}).setdefault(r['metric'], {})[r['cq']] = r['value']

    stocks = []
    for s in a['stocks']:
        if s.get('code'):
            c = s['code']
            ser, basis = domestic(fconn, c)
            i = info.get(c, {})
            fx = fund_idx.get(c, {})
            x = {'c': c, 'n': i.get('n') or s['n'], 'mk': i.get('mk'), 'w': i.get('w'), 'mc': i.get('mc'), 'p': i.get('p'), 'ch': i.get('ch'),
                 'basis': basis, 'unit': '억원', 'eq': fx.get('eq') or latest_earn(attach_earn(c)), 'fund': c in fund_idx,
                 'ix': fx.get('ix') or [], 'con': con.get(c, [])[:40],
                 'con12': round(sum(k['amt'] or 0 for k in con.get(c, []) if not k['x'] and k['d'] >= (date.today() - timedelta(days=365)).isoformat()), 1),
                 'conn12': sum(1 for k in con.get(c, []) if not k['x'] and k['d'] >= (date.today() - timedelta(days=365)).isoformat())}
        else:
            tk = s['tk']
            ser = ov.get(tk, {})
            m = meta.get(tk, {})
            x = {'tk': tk, 'n': s['n'], 'ov': True, 'cur': m.get('cur'), 'unit': f"백만 {m.get('cur') or ''}".strip(),
                 'mc_usd': m.get('mcap_usd'), 'fx': m.get('fx_usd'), 'src': s.get('src')}
            if ser.get('capex'):
                x['capex'] = ser['capex']
        x.update({'cell': s['cell'], 'also': s.get('also', []), 'p_': s.get('p'), 'ai': s.get('ai'), 'moat': s.get('moat', []),
                  'conf': s.get('conf'), 'note': s.get('note'), 'chk': s.get('chk'), 'rv': s.get('reviewed')})
        x['q'] = {k: {cq: r1(v) for cq, v in ser.get(k, {}).items()} for k in ('rev', 'op')}
        stocks.append(x)

    # 최근 분기 = 국내 손익이 가장 많이 나온 분기 (해외는 회계연도가 달라 한 분기 늦을 수 있다)
    cnt = {}
    for x in stocks:
        if not x.get('ov'):
            for cq in x['q']['rev']:
                cnt[cq] = cnt.get(cq, 0) + 1
    last = max((cq for cq, n in cnt.items() if n >= len(codes) * 0.6), default=max(cnt))
    qs = quarters(last)
    raw = {(x.get('c') or x.get('tk')): dict(x['q']['rev']) for x in stocks}     # 시차 상관용 (자르기 전 전체 분기)
    for x in stocks:
        lq = max((cq for cq in x['q']['rev'] if cq <= last), default=None)    # 그 종목의 최신 분기 (해외는 한 분기 늦을 수 있음)
        x['lq'] = lq
        x.update({k: r1(v) for k, v in stats(x['q'], lq).items()} if lq else {})
        x['q'] = {k: [v.get(cq) for cq in qs] for k, v in x['q'].items()}
        if 'capex' in x:
            x['capex'] = [r1(x['capex'].get(cq)) for cq in qs]

    # 칸 요약 — 최근 분기(last) 기준. 해외 종목은 그 회사 최신 분기(lq)를 쓴다
    since90 = (date.today() - timedelta(days=90)).isoformat()
    cells = []
    for c in a['cells']:
        mem = [x for x in stocks if x['cell'] == c['id'] or c['id'] in (x.get('also') or [])]    # 보조 칸으로 걸친 종목도 그 칸에 센다
        yo = [x['yoy'] for x in mem if x.get('yoy') is not None]
        om = [x['opm'] for x in mem if x.get('opm') is not None]
        cs = [k for x in mem for k in x.get('con', []) if k['d'] >= since90 and not k['x']]
        eqs = [x['eq'] for x in mem if x.get('eq') and x['eq']['q'] == f'{last[5]}Q{last[2:4]}']
        cells.append({**c, 'n': len(mem), 'nk': sum(not x.get('ov') for x in mem),
                      'yoy': r1(median(yo)) if yo else None, 'opm': r1(median(om)) if om else None,
                      'dopm': r1(median([x['dopm'] for x in mem if x.get('dopm') is not None])) if any(x.get('dopm') is not None for x in mem) else None,
                      'con90': len(cs), 'con90amt': r1(sum(k['amt'] or 0 for k in cs)),
                      'beat': sum(e['case'] in ('both', 'op', 'sales') for e in eqs), 'miss': sum(e['case'] == 'miss' for e in eqs)})

    # 시차 상관: 수요 지표(빅테크 capex 합계, 삼성+하이닉스 설비투자) → 칸별 국내 매출 합계.
    # 종목 구성이 바뀌면 합이 튀므로, 비교 구간 전체에 매출이 있는 종목만 더한다 (삼성·하이닉스 자신은 뺀다)
    drv = {'빅테크 capex': {}, '삼성+하이닉스 설비투자': {}}
    for cq in {c for tk in CLOUD for c in ov.get(tk, {}).get('capex', {})}:
        if all(ov.get(tk, {}).get('capex', {}).get(cq) is not None for tk in CLOUD):
            drv['빅테크 capex'][cq] = sum(ov[tk]['capex'][cq] for tk in CLOUD)
    for cq in set(ov.get('005930', {}).get('capex', {})) & set(ov.get('000660', {}).get('capex', {})):
        drv['삼성+하이닉스 설비투자'][cq] = ov['005930']['capex'][cq] + ov['000660']['capex'][cq]
    span = [cq for cq in quarters(last, 16) if cq >= '2023Q1']
    for c in cells:
        mem = [x for x in stocks if not x.get('ov') and x['cell'] == c['id'] and x.get('c') not in ('005930', '000660')]
        full = [x for x in mem if all(raw[x['c']].get(cq) is not None for cq in span)]
        if len(full) < 2:
            continue
        rev = {cq: sum(raw[x['c']][cq] for x in full) for cq in span}
        c['lag'] = {'n_stocks': len(full), 'span': [span[0], span[-1]], **lag_table(rev, drv)}

    # 고객별 분기 수주 (억원) — 전공정 장비·부품·후공정·테스트 단계 종목의 단일판매·공급계약. 고객 capex 의 대리 지표
    EQ = {'fe', 'fep', 'be', 'bec'}
    stage_of = {c['id']: c['stage'] for c in a['cells']}
    cq_of = lambda d: f'{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}'
    oq = quarters(last, 20)
    by_c = {}
    for x in stocks:
        if x.get('ov') or stage_of.get(x['cell']) not in EQ:
            continue
        for k in x.get('con', []):
            if k['x'] or not k['amt'] or cq_of(k['d']) not in oq:
                continue
            by_c.setdefault(k['cust'], {}).setdefault(cq_of(k['d']), 0)
            by_c[k['cust']][cq_of(k['d'])] += k['amt']
    top = sorted(by_c, key=lambda c: -sum(by_c[c].values()))
    orders_q = {'qs': oq, 'cust': {c: [r1(by_c[c].get(q)) for q in oq] for c in top}}

    # 수요: 빅테크 capex (백만 달러) 분기 합계와 회사별
    capex = {tk: [r1(ov.get(tk, {}).get('capex', {}).get(cq)) for cq in qs] for tk in CLOUD + ('CRWV',)}
    tot = [r1(sum(capex[tk][i] or 0 for tk in CLOUD)) if all(capex[tk][i] is not None for tk in CLOUD) else None for i in range(len(qs))]
    yoy = [r1((tot[i] / tot[i - 4] - 1) * 100) if i >= 4 and tot[i] and tot[i - 4] else None for i in range(len(qs))]
    supply = {tk: [r1(ov.get(tk, {}).get('capex', {}).get(cq)) for cq in qs] for tk in ('005930', '000660', 'MU', 'TSM', 'INTC', 'SNDK')}

    # AI 개괄: 손으로 관리하는 규격표(semi_ai.json) + 피드에서 감지한 최근 소식 (규격표에 없는 제품명은 '검토 필요')
    ai = json.loads(AI_FILE.read_text(encoding='utf-8')) if AI_FILE.exists() else {}
    news = []
    try:
        from collect_ai_news import known_text, names_of, new_names
        known = known_text(ai)
        news = [dict(r) for r in sconn.execute('SELECT url, src, title, date, tags FROM ai_news WHERE date >= ? ORDER BY date DESC LIMIT 60',
                                               ((date.today() - timedelta(days=45)).isoformat(),))]
        for n in news:      # '새' 는 지금 규격표 기준으로 다시 — 규격표에 넣으면 표시가 사라진다
            n['new'] = ','.join(new_names(names_of(n['title']), known))
    except sqlite3.OperationalError:
        pass
    ai_out = {k: ai.get(k) for k in ('as_of', 'caveat', 'racks', 'bom', 'nv_notes', 'chips', 'train_vs_infer', 'capex_guide', 'changelog')}
    ai_out['news'] = news
    krw = (meta.get('_KRW') or {}).get('fx_usd')
    out = {'built': datetime.now().isoformat(timespec='seconds'), 'last': last, 'qs': qs, 'usdkrw': round(1 / krw, 1) if krw else None,
           'stages': a['stages'], 'cells': cells, 'stocks': stocks,
           'capex': {'cos': capex, 'tot': tot, 'yoy': yoy, 'names': {**{s['tk']: s['n'] for s in a['stocks'] if s.get('tk')}, '005930': '삼성전자', '000660': 'SK하이닉스'}},
           'ai': ai_out, 'orders_q': orders_q, 'fac': fac[:60], 'fabs': fabs_out(fac),
           'supply': {'capex': supply, 'cur': {tk: meta.get(tk, {}).get('cur') for tk in supply}}}
    write_json(OUT, out)
    return len(stocks)


def main():
    n = build()
    print(f'semi: {n}종목')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
