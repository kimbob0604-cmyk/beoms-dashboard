"""
바이오 탭: 자산별 시장(TAM → SAM → SOM)과 시나리오 트리거.

시장: 유병 환자(TAM) × 표적 비율(SAM) × 침투율(SOM) × 순가격 = 피크매출. bear·base·bull 은 이 세 값과 가격만 다르다.
      base 의 피크매출은 bio_assets.json 의 peak_musd 와 같아야 한다(테스트로 확인).
트리거: 시나리오를 가르는 사건과 그 진행을 보여주는 프록시. 각각 수집기가 있다.
  ctgov   : ClinicalTrials.gov 시험 상태·1차 완료 예정일 (매일 자동)
  sec     : 최근 8-K·보도자료·10-Q 문장에서 단어가 모두 나오면 '새 원문, 판정 필요' (결과를 자동으로 판정하지 않음)
  revenue : 출시 뒤 분기 제품 매출을 시나리오별 1년차 분기 매출과 비교 (자동)
  manual  : 원문을 읽고 설정에 적은 판정 (evidence: status·scenario·url)
"""

import copy
from datetime import date

import requests

CASES = ('bear', 'base', 'bull')
LIVE = {'RECRUITING', 'NOT_YET_RECRUITING', 'ENROLLING_BY_INVITATION'}
STOPPED = {'TERMINATED', 'WITHDRAWN', 'SUSPENDED'}
_ct_cache = {}


def peak_of(m: dict, case: str) -> float:
    """백만 달러."""
    c = m['cases'][case]
    if m.get('kind') == 'dollar':
        return m['tam_usd'] * c['sam'] * c['pen']
    return m['tam_patients'] * c['sam'] * c['pen'] * c['price_k'] * 1000 / 1e6 * m.get('global_mult', 1.0)


def ct_study(nct: str):
    if nct in _ct_cache:
        return _ct_cache[nct]
    r = requests.get(f'https://clinicaltrials.gov/api/v2/studies/{nct}', timeout=30,
                     params={'fields': 'NCTId,OverallStatus,EnrollmentInfo,PrimaryCompletionDate,LastUpdatePostDate,Phase'})
    r.raise_for_status()
    p = r.json()['protocolSection']
    st, de = p['statusModule'], p.get('designModule', {})
    out = {'status': st['overallStatus'], 'pcd': (st.get('primaryCompletionDateStruct') or {}).get('date'),
           'enroll': (de.get('enrollmentInfo') or {}).get('count'), 'enroll_type': (de.get('enrollmentInfo') or {}).get('type'),
           'updated': (st.get('lastUpdatePostDateStruct') or {}).get('date'), 'phases': de.get('phases') or []}
    _ct_cache[nct] = out
    return out


def _months(a: str, b: str) -> int:
    """b − a 개월 (YYYY-MM[-DD])."""
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return (yb - ya) * 12 + (mb - ma)


def judge_ct(s: dict, due):
    """(status, scenario). 모집 중이면 진행 중이고 시나리오는 일정으로 잠정 판단."""
    if s['status'] in STOPPED:
        return 'done', 'bear'
    lean = 'base'
    if due and s.get('pcd'):
        d = _months(due, s['pcd'])
        lean = 'bear' if d > 3 else 'bull' if d < -2 else 'base'
    return ('live' if s['status'] in LIVE else 'done'), lean


STATUS_KO = {'RECRUITING': '모집 중', 'NOT_YET_RECRUITING': '모집 전', 'ENROLLING_BY_INVITATION': '초청 모집 중', 'ACTIVE_NOT_RECRUITING': '모집 완료·진행 중',
             'COMPLETED': '완료', 'TERMINATED': '중단', 'WITHDRAWN': '철회', 'SUSPENDED': '일시 중지'}


def sec_hits(row: dict, terms, since):
    auto = row.get('auto') or {}
    texts = []
    for x in auto.get('ir', []):
        for h in [x.get('title') or ''] + list(x.get('highlights') or []):
            texts.append((x.get('filed'), h, x.get('url')))
    for e in auto.get('events', []):
        texts.append((e.get('filed'), e.get('sentence') or '', e.get('url')))
    for f in auto.get('filings', []):
        for lb in f.get('labels') or []:
            texts.append((f.get('filed'), lb, f.get('url')))
    out, seen = [], set()
    for d, t, u in texts:
        if since and (d or '') < since:
            continue
        low = t.lower()
        if all(any(alt.lower() in low for alt in w.split('|')) for w in terms) and t not in seen:   # 'a|b' 는 둘 중 하나
            seen.add(t)
            out.append({'date': d, 'text': t[:300], 'url': u})
    return out[:3]


def collect(trig: dict, row: dict, asset: dict, m: dict, today: str):
    col = trig['collector']
    t = {k: v for k, v in trig.items() if k != 'collector'}
    t['source'] = col['type']
    if col['type'] == 'ctgov':
        try:
            s = ct_study(col['nct'])
        except Exception as e:
            t.update(status='error', note=f'CT.gov 실패: {str(e)[:60]}')
            return t
        st, sc = judge_ct(s, col.get('due'))
        prog = f"{col['nct']} {STATUS_KO.get(s['status'], s['status'])} · {'목표' if s['enroll_type'] == 'ESTIMATED' else '실제'} {s['enroll'] or '–'}명 · 1차 완료 {s['pcd'] or '–'}"
        if col.get('due') and s.get('pcd') and s['pcd'][:7] != col['due']:
            prog += f" (기준 {col['due']})"
        t.update(status=st, scenario=sc, tentative=st == 'live', progress=prog, date=s.get('updated'), data=s)
    elif col['type'] in ('sec', 'dart'):
        hits = sec_hits(row, col['terms'], col.get('since'))
        if trig.get('evidence'):
            t.update(_evidence(trig['evidence']))
        elif hits:
            t.update(status='hit', progress=f"새 원문 {len(hits)}건. 읽고 판정해야 합니다.", hits=hits, date=hits[0]['date'])
        else:
            t.update(status='wait', progress=f"{col.get('since') or ''} 이후 해당 문장 없음 (단어: {' + '.join(w.replace('|', ' 또는 ') for w in col['terms'])})")
    elif col['type'] == 'merck_qlex':
        try:
            q = merck_qlex(col['cik'])
        except Exception as e:
            q = None
            t.update(status='error', progress=f'MSD 공시 읽기 실패: {str(e)[:60]}')
        if q:
            t.update(status='live', scenario=None, date=q['filed'], evidence_url=q['url'],
                     progress=f"{q['filed']} 8-K: Qlex ${q['qlex']:,.0f}M ÷ 키트루다 패밀리 ${q['family']:,.0f}M = 전환율 {q['share'] * 100:.1f}% (2027년 말에 판정)")
    elif col['type'] == 'qgrowth':
        qs = [q for q in ((row.get('fin') or {}).get('quarters') or []) if q.get('revenue')]
        base_q = (1 + col['base_annual']) ** 0.25 - 1
        if len(qs) < 2:
            t.update(status='wait', progress='분기 매출 2개 이상 필요')
        else:
            a, b = qs[-2], qs[-1]
            gr = b['revenue'] / a['revenue'] - 1
            sc = 'bear' if gr < 0 else 'bull' if gr > base_q * 1.5 else 'base'
            t.update(status='done', scenario=sc, date=b['end'],
                     progress=f"{b['label']} 매출 ${b['revenue']:.1f}M, 전분기 ${a['revenue']:.1f}M 대비 {gr * 100:+.1f}% (기본 경로 분기 {base_q * 100:+.1f}%)")
    elif col['type'] == 'revenue':
        launch = col.get('launch')
        qs = [q for q in ((row.get('fin') or {}).get('quarters') or []) if launch and q['end'] > launch and q.get('revenue')]
        exp = {k: peak_of(m, k) / max(1, asset.get('ramp_years', 5)) / 4 for k in CASES}
        t['expected_q1'] = exp
        if not launch or launch > today:
            t.update(status='wait', progress='출시 전')
        elif not qs:
            t.update(status='live', progress='출시 후 첫 분기 실적 대기', tentative=True, scenario=None)
        else:
            q = qs[-1]
            sc = min(CASES, key=lambda k: abs(exp[k] - q['revenue']))
            t.update(status='done', scenario=sc, progress=f"{q['label']} 매출 ${q['revenue']:.1f}M (1년차 분기 경로: bear ${exp['bear']:.0f}M · base ${exp['base']:.0f}M · bull ${exp['bull']:.0f}M)",
                     date=q['end'])
    else:
        if trig.get('evidence'):
            t.update(_evidence(trig['evidence']))
        else:
            t.update(status='wait', progress='판정 전')
    return t


_mrk = {}


def merck_qlex(cik):
    """MSD 최신 실적 8-K(Ex.99)에서 키트루다 패밀리·Qlex 분기 매출(백만 달러)."""
    import re, html as H
    import bio_events as be
    if cik in _mrk:
        return _mrk[cik]
    sub = be.sec_get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json').json()['filings']['recent']
    for k, form in enumerate(sub['form']):
        if form != '8-K' or '2.02' not in (sub.get('items') or [''] * len(sub['form']))[k]:
            continue
        acc = sub['accessionNumber'][k].replace('-', '')
        idx = be.sec_get(f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json').json()
        ex = [x['name'] for x in idx['directory']['item'] if re.search(r'ex-?99', x['name'], re.I) and x['name'].endswith('.htm')]
        if not ex:
            continue
        url = f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{ex[0]}'
        t = re.sub(r'\s+', ' ', H.unescape(re.sub(r'<[^>]+>', ' ', be.sec_get(url).text)))
        fam = re.search(r'KEYTRUDA/KEYTRUDA QLEX\s*\d?\s*Sales Were \$([\d.]+) (Billion|Million)', t)
        ql = re.search(r'Sales of KEYTRUDA QLEX were \$([\d,.]+) (billion|million)', t, re.I)
        if not (fam and ql):
            continue
        f = float(fam.group(1)) * (1000 if fam.group(2) == 'Billion' else 1)
        qv = float(ql.group(1).replace(',', '')) * (1000 if ql.group(2).lower() == 'billion' else 1)
        _mrk[cik] = {'filed': sub['filingDate'][k], 'url': url, 'family': f, 'qlex': qv, 'share': qv / f}
        return _mrk[cik]
    _mrk[cik] = None
    return None


def _evidence(ev):
    return {'status': ev.get('status', 'done'), 'scenario': ev.get('scenario'), 'progress': ev.get('note', ''), 'date': ev.get('date'),
            'evidence_url': ev.get('url')}


def tracking(trigs):
    """판정된(잠정 포함) 트리거로 지금 어느 시나리오를 지나는지. bear 가 하나라도 있으면 bear."""
    sc = [t['scenario'] for t in trigs if t.get('scenario') and t['status'] in ('done', 'live')]
    if not sc:
        return 'base', 0
    if 'bear' in sc:
        return 'bear', len(sc)
    return ('bull' if sc.count('bull') > sc.count('base') else 'base'), len(sc)


REG = {}   # 자산 id → 계산된 시장 (로열티 자산이 파트너 시장을 끌어다 씀). 설정 순서대로 미장 → 국장이라 파트너가 먼저 계산된다.


def _market_cases(m, value_case, price):
    cases = {}
    for k in CASES:
        c = m['cases'][k]
        pk = m['tam_patients'] * c['sam'] * c['pen'] * c['price_k'] * 1000 / 1e6 * m.get('global_mult', 1.0)
        ps = value_case(k, pk)
        sam_n = m['tam_patients'] * c['sam']
        cases[k] = {**c, 'peak': pk, 'per_share': ps, 'upside': ps / price - 1 if ps is not None and price else None,
                    'tam_usd': m['tam_patients'] * c['price_k'] * 1000 / 1e6, 'sam_n': sam_n, 'sam_usd': sam_n * c['price_k'] * 1000 / 1e6,
                    'som_n': sam_n * c['pen']}
    return cases


def _head(m):
    return {k: m.get(k) for k in ('region', 'tam_usd', 'tam_patients', 'tam_src', 'tam_verified', 'tam_url', 'sam_label', 'sam_src', 'som_label', 'price_src')}


def asset_markets(co, row, mk, g, rf, value_company, scen_base):
    today = date.today().isoformat()
    out = []
    price = mk['price']

    def asset_value(aid):
        def f(k, pk):
            c2 = copy.deepcopy(co)
            next(x for x in c2['assets'] if x['id'] == aid)['peak_musd'] = pk
            return value_company(c2, mk, g, rf, scen_base)['per_share']
        return f

    for a in co.get('assets', []):
        m = a.get('market')
        if not m:
            continue
        if m.get('kind') == 'triggers':
            trigs = [collect(t, row, a, m, today) for t in m.get('triggers', [])]
            track, n = tracking(trigs)
            out.append({'id': a['id'], 'kind': 'triggers', 'name': a['name'], 'indication': a['indication'], 'region': m['region'], 'note': m.get('note', ''),
                        'triggers': trigs, 'tracking': track, 'judged': n})
            continue
        if m.get('kind') == 'dollar':   # 회사가 시장을 금액으로만 밝힌 경우: 시장 금액 × 표적 비율 × 점유
            f = asset_value(a['id'])
            cases = {}
            for k in CASES:
                c = m['cases'][k]
                pk = m['tam_usd'] * c['sam'] * c['pen']
                ps = f(k, pk)
                cases[k] = {**c, 'tam_usd': m['tam_usd'], 'sam_usd': m['tam_usd'] * c['sam'], 'peak': pk, 'per_share': ps,
                            'upside': ps / price - 1 if ps is not None and price else None}
            trigs = [collect(t, row, a, m, today) for t in m.get('triggers', [])]
            track, n = tracking(trigs)
            out.append({'id': a['id'], 'kind': 'dollar', 'name': a['name'], 'indication': a['indication'], **_head(m),
                        'cases': cases, 'triggers': trigs, 'tracking': track, 'judged': n})
            continue
        if m.get('kind') == 'product_royalty':
            out.append(product_royalty(co, row, mk, g, rf, value_company, scen_base, a, m, today))
            continue
        if m.get('kind') == 'royalty':
            links = [REG[x] for x in m['links'] if x in REG]
            if len(links) != len(m['links']):
                continue
            f = asset_value(a['id'])
            cases = {}
            for k in CASES:
                agg = {x: sum(l['cases'][k][x] for l in links) for x in ('tam_usd', 'sam_n', 'sam_usd', 'som_n', 'peak')}
                roy = agg['peak'] * m['rate']
                ps = f(k, roy)
                cases[k] = {**agg, 'royalty': roy, 'rate': m['rate'], 'per_share': ps, 'upside': ps / price - 1 if ps is not None and price else None,
                            'why': ' / '.join(f"{l['indication']}: {l['cases'][k]['why']}" for l in links)}
            trigs = [{**t, 'name': f"[{l['indication']}] {t['name']}"} for l in links for t in l['triggers']]
            track, n = tracking(trigs)
            out.append({'id': a['id'], 'kind': 'royalty', 'name': a['name'], 'indication': ' + '.join(l['indication'] for l in links), 'region': m['region'],
                        'tam_patients': sum(l['tam_patients'] for l in links), 'tam_src': f"파트너 {m['partner']} 시장 합산",
                        'tam_verified': all(l['tam_verified'] for l in links), 'sam_label': '파트너 표적 환자 합산', 'sam_src': '적응증별 표적 비율',
                        'som_label': f"파트너 피크매출 × 로열티 {m['rate'] * 100:.0f}%", 'price_src': m['rate_src'], 'rate': m['rate'],
                        'cases': cases, 'triggers': trigs, 'tracking': track, 'judged': n})
            continue
        cases = _market_cases(m, asset_value(a['id']), price)
        trigs = [collect(t, row, a, m, today) for t in m.get('triggers', [])]
        track, n = tracking(trigs)
        r = {'id': a['id'], 'kind': 'pipeline', 'name': a['name'], 'indication': a['indication'], **_head(m),
             'cases': cases, 'triggers': trigs, 'tracking': track, 'judged': n}
        REG[a['id']] = r
        out.append(r)

    cm = (co.get('commercial') or {}).get('market')
    if cm:
        out.insert(0, commercial_market(co, row, mk, g, rf, value_company, scen_base, cm, today))
    return out


def _dcf_peak(co, g, gm):
    import bio_valuation as bv
    c = co['commercial']
    _, rows = bv.dcf_commercial(c['run_rate_musd'], [x * gm for x in c['growth']], c['margin_now'], c['margin_target'], c['margin_years'],
                                g['tax'], g['wacc'], c['loe_year_index'], c['erosion'], years=c.get('years', 15))
    return max(r['rev'] for r in rows)


def solve_growth(co, g, total_peak):
    """상업 DCF 최고 매출이 total_peak 가 되는 성장률 배수(이분법). 시작 매출보다 낮은 피크는 성장 0 근처로 잘린다."""
    lo, hi = -1.0, 20.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _dcf_peak(co, g, mid) < total_peak else (lo, mid)
    return (lo + hi) / 2


def commercial_market(co, row, mk, g, rf, value_company, scen_base, cm, today):
    m = copy.deepcopy(cm)
    share = m.get('product_share', 1.0)
    base_total = _dcf_peak(co, g, 1.0)
    bc = m['cases']['base']
    if bc['pen'] == 'model':
        bc['pen'] = base_total * share * 1e6 / (m['tam_patients'] * bc['sam'] * bc['price_k'] * 1000)

    def value_case(k, pk):
        gm = 1.0 if k == 'base' else solve_growth(co, g, pk / share)
        return value_company(co, mk, g, rf, {**scen_base, 'growth_mult': gm})['per_share']

    cases = _market_cases(m, value_case, mk['price'])
    for k in CASES:
        cases[k]['total_peak'] = cases[k]['peak'] / share
    cur = m.get('current') or {}
    sam_n = m['tam_patients'] * bc['sam']
    current = {**cur, 'pen': cur['patients'] / sam_n if cur.get('patients') else None,
               'revenue': co['commercial']['run_rate_musd'] * share}
    trigs = [collect(t, row, {'ramp_years': 5}, m, today) for t in m.get('triggers', [])]
    track, n = tracking(trigs)
    return {'id': 'commercial', 'kind': 'commercial', 'name': m['product'], 'indication': f"{m['product']} (상업)", **_head(m),
            'cases': cases, 'current': current, 'share': share, 'share_note': m.get('share_note', ''),
            'triggers': trigs, 'tracking': track, 'judged': n}


def product_royalty(co, row, mk, g, rf, value_company, scen_base, a, m, today):
    """파트너 제품 매출 × 전환율 × 로열티율. display_only 자산이면 기본 가치에 더한 값을 시나리오별로 보여준다."""
    price = mk['price']
    cases = {}
    for k in CASES:
        c = m['cases'][k]
        sales = m['base_sales_musd'] * c['share']
        roy = sales * m['rate']
        c2 = copy.deepcopy(co)
        x = next(y for y in c2['assets'] if y['id'] == a['id'])
        x['peak_musd'] = roy
        x.pop('display_only', None)
        ps = value_company(c2, mk, g, rf, scen_base)['per_share']
        cases[k] = {**c, 'tam_usd': m['base_sales_musd'], 'sam_usd': m['base_sales_musd'], 'peak': sales, 'royalty': roy, 'rate': m['rate'],
                    'per_share': ps, 'upside': ps / price - 1 if ps is not None and price else None}
    trigs = [collect(t, row, a, m, today) for t in m.get('triggers', [])]
    track, n = tracking(trigs)
    return {'id': a['id'], 'kind': 'product_royalty', 'name': a['name'], 'indication': a['indication'], 'region': m['region'], 'product': m['product'],
            'tam_src': m['base_src'], 'tam_url': m.get('base_url'), 'tam_verified': True, 'sam_label': 'SC 전환 대상 매출', 'sam_src': '키트루다 패밀리 전체',
            'som_label': f"Qlex 매출 × 로열티 {m['rate'] * 100:.0f}%", 'price_src': m['rate_src'], 'rate': m['rate'],
            'current_share': m.get('current_share'), 'current_src': m.get('current_src'), 'display_only': bool(a.get('display_only')),
            'cases': cases, 'triggers': trigs, 'tracking': track, 'judged': n}
