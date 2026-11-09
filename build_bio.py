"""
바이오 탭: public/data/bio.json — 관심 바이오 종목의 시세·임상 일정·공시 뉴스와 rNPV/옵션 가치

- 입력: bio_assets.json (직접 관리하는 가정치·사실·일정). 가정치는 이 파일에서만 고친다.
- 시세·재무: yfinance (가격, 시총, 현금, 부채, 주식 수, 영업현금흐름, 최근 뉴스), 무위험이자율은 미국 10년물(^TNX)
- 임상 시험: ClinicalTrials.gov API v2 (스폰서별, 진행 중인 시험의 1차 완료 예정일)
- 계산: bio_valuation.py (방법론은 Notion 'Bio기업 Valuation 방법론')
- 가져오기에 실패한 부분은 직전 bio.json 값을 그대로 두고 stale 로 표시한다.

  python3 build_bio.py
"""

import json
import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import date, datetime
from pathlib import Path

import requests

import bio_events as be
import bio_xbrl as bx
import bio_valuation as bv

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'bio_assets.json'
OUT = ROOT / 'public' / 'data' / 'bio.json'
CT_URL = 'https://clinicaltrials.gov/api/v2/studies'
ACTIVE = 'RECRUITING|ACTIVE_NOT_RECRUITING|NOT_YET_RECRUITING|ENROLLING_BY_INVITATION'
MAX_BURN_YEARS = 5


def load_previous() -> dict:
    try:
        return {c['ticker']: c for c in json.loads(OUT.read_text(encoding='utf-8'))['companies']}
    except (OSError, ValueError, KeyError):
        return {}


def fetch_rf(fallback: float):
    try:
        import yfinance as yf
        px = yf.Ticker('^TNX').history(period='5d')['Close'].dropna()
        return float(px.iloc[-1]) / 100, False
    except Exception as e:   # 네트워크·형식 변경
        print(f'  무위험이자율 실패: {e} → {fallback:.1%} 사용', file=sys.stderr)
        return fallback, True


def fetch_market(ticker: str):
    """달러 값은 백만 달러로 돌려준다."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    i = t.info
    m = lambda v: None if v is None else v / 1e6
    price = i.get('currentPrice') or i.get('regularMarketPrice')
    prev = i.get('previousClose')
    news = []
    try:
        for n in (t.news or [])[:6]:
            c = n.get('content') or n
            title = c.get('title')
            url = (c.get('canonicalUrl') or c.get('clickThroughUrl') or {}).get('url') or c.get('link')
            pub = c.get('pubDate') or c.get('displayTime') or (datetime.fromtimestamp(n['providerPublishTime']).isoformat() if n.get('providerPublishTime') else None)
            src = (c.get('provider') or {}).get('displayName') or n.get('publisher')
            if title and url and not str(src or '').lower().startswith(('http', 'www.')):
                news.append({'title': title, 'url': url, 'date': (pub or '')[:10], 'src': src})
    except Exception as e:
        print(f'  {ticker} 뉴스 실패: {e}', file=sys.stderr)
    if price is None:
        raise ValueError('가격 없음')
    return {
        'price': price, 'change_pct': (price / prev - 1) * 100 if prev else None,
        'mcap': m(i.get('marketCap')), 'cash': m(i.get('totalCash')), 'debt': m(i.get('totalDebt')),
        'shares': m(i.get('sharesOutstanding')), 'op_cf': m(i.get('operatingCashflow')),
        'revenue_ttm': m(i.get('totalRevenue')), 'beta': i.get('beta'), 'currency': i.get('currency', 'USD'),
        'asof': date.today().isoformat(),
    }, news


def fetch_news_rss(name: str, ticker: str):
    """yfinance 뉴스가 비면 구글 뉴스 RSS 로 대신한다."""
    r = requests.get('https://news.google.com/rss/search', params={'q': f'"{name}" {ticker} stock', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'},
                     timeout=20, headers={'User-Agent': 'Mozilla/5.0 (compatible; BeomDashboard)'})
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iterfind('./channel/item'):
        try:
            d = parsedate_to_datetime(it.findtext('pubDate')).date().isoformat()
        except (TypeError, ValueError):
            d = ''
        src = it.find('source')
        name_ = src.text if src is not None else None
        if str(name_ or '').lower().startswith(('http', 'www.')):   # 출처가 도메인 이름뿐인 스팸성 페이지 제외
            continue
        out.append({'title': it.findtext('title'), 'url': it.findtext('link'), 'date': d, 'src': name_})
    out.sort(key=lambda x: x['date'], reverse=True)
    return out[:6]


def fetch_trials(spons: str):
    params = {'query.spons': spons, 'filter.overallStatus': ACTIVE, 'pageSize': 100,
              'fields': 'NCTId,BriefTitle,OverallStatus,Phase,PrimaryCompletionDate,Condition,InterventionName'}
    r = requests.get(CT_URL, params=params, timeout=30)
    r.raise_for_status()
    out = []
    for s in r.json().get('studies', []):
        p = s['protocolSection']
        phases = p.get('designModule', {}).get('phases', [])
        if not any(x in ('PHASE2', 'PHASE3', 'PHASE2|PHASE3') for x in phases):
            continue
        out.append({
            'id': p['identificationModule']['nctId'], 'title': p['identificationModule'].get('briefTitle', ''),
            'status': p['statusModule'].get('overallStatus'),
            'phase': '/'.join(x.replace('PHASE', 'P') for x in phases),
            'done': (p['statusModule'].get('primaryCompletionDateStruct') or {}).get('date'),
            'cond': (p.get('conditionsModule', {}).get('conditions') or [''])[0],
            'drug': (p.get('armsInterventionsModule', {}).get('interventions') or [{}])[0].get('name', ''),
        })
    out.sort(key=lambda x: (x['done'] or '9999', x['id']))
    return out


def scale_stages(stages, k, force=None):
    """force 가 있으면 모든 단계의 PoS 를 그 값으로(성공 1.0, 실패 0.0). 아니면 k 배(최대 0.99)."""
    return [{'t': s['t'], 'pos': force if force is not None else min(0.99, s['pos'] * k), 'x': s['x'], 'name': s.get('name', '')}
            for s in stages]


def value_asset(a, g, rf, scen):
    peak = a['peak_musd'] * scen['peak_mult']
    v0 = bv.launch_value(peak, a['margin'], g['tax'], g['wacc'], a['launch_in'], a['ramp_years'], a['exclusivity_years'])
    stages = scale_stages(a['stages'], scen['pos_mult'], scen.get('pos_force'))
    tree, steps = bv.rnpv_tree(v0, rf, stages)
    rov = bv.option_value(v0, g['sigma'], rf, stages)
    forced = bv.rnpv_forced(v0, rf, stages)
    for s, src in zip(steps, stages):
        s['name'] = src['name']
        s['breakeven'] = bv.breakeven_pos(s['cont'], s['pv_x'])
    return {'v0': v0, 'rnpv': tree, 'rov': rov, 'forced': forced, 'steps': steps,
            'value': rov if a.get('method') == 'rov' else tree}


def value_company(co, mk, g, rf, scen):
    assets, total_assets = [], 0.0
    for a in co.get('assets', []):
        v = value_asset(a, g, rf, scen)
        assets.append({'id': a['id'], 'name': a['name'], 'indication': a['indication'], 'stage': a['stage'],
                       'method': a.get('method', 'rnpv'), 'peak': a['peak_musd'] * scen['peak_mult'], 'basis': a.get('basis', ''),
                       'assumptions': a.get('assumptions', ''), **v})
        total_assets += v['value']
    comm, comm_pv = None, 0.0
    c = co.get('commercial')
    if c:
        growth = [x * scen['growth_mult'] for x in c['growth']]
        comm_pv, rows = bv.dcf_commercial(c['run_rate_musd'] * scen.get('rev_mult', 1.0), growth, c['margin_now'], c['margin_target'], c['margin_years'],
                                          g['tax'], g['wacc'], c['loe_year_index'], c['erosion'], years=c.get('years', 15))
        comm = {'name': c['name'], 'run_rate': c['run_rate_musd'] * scen.get('rev_mult', 1.0), 'run_rate_note': c.get('run_rate_note', ''),
                'pv': comm_pv, 'rows': rows, 'assumptions': c.get('assumptions', '')}
    ov = co.get('overrides', {})
    cash = ov.get('cash_musd', mk['cash'] or 0.0)
    debt = ov.get('debt_musd', mk['debt'] or 0.0)
    other = ov.get('other_liab_musd', 0.0)
    burn = 0.0
    if co['kind'] == 'pipeline' and co.get('assets'):
        years = min(MAX_BURN_YEARS, min(a['launch_in'] for a in co['assets']))   # 첫 출시 이후엔 매출이 비용을 댄다(회사: 현금은 GD 출시 가능 시점까지)
        annual = ov.get('annual_burn_musd')
        if annual is None and mk.get('op_cf') is not None:
            annual = max(0.0, -mk['op_cf'])
        burn = (annual or 0.0) * years
    equity = total_assets + comm_pv + cash - debt - other - burn
    per_share = equity / mk['shares'] if mk.get('shares') else None
    return {'assets': assets, 'commercial': comm, 'equity': equity, 'per_share': per_share,
            'upside': (per_share / mk['price'] - 1) if per_share is not None and mk['price'] else None,
            'bridge': {'assets': total_assets, 'commercial': comm_pv, 'cash': cash, 'debt': debt, 'other': other, 'burn': burn}}


BASE = {'pos_mult': 1.0, 'peak_mult': 1.0, 'growth_mult': 1.0}


def payoffs(co, mk, g, rf, scenarios, base_ps):
    """업사이드 사다리: 실패 / 기본(확률가중) / 성공 / 낙관 성공, 시장 내재 성공확률, 시장이 요구하는 규모 배수."""
    price = mk['price']
    if not mk.get('shares'):
        return None
    ok = {**BASE, 'pos_force': 1.0}
    success = value_company(co, mk, g, rf, ok)
    bull = scenarios['bull']
    bull_ok = value_company(co, mk, g, rf, {**bull, 'pos_force': 1.0})
    b = success['bridge']
    # 실패: 임상 자산 가치 0. 임상 회사는 첫 발표 때까지만 현금을 쓰고 멈춘다고 본다.
    fail_burn = 0.0
    if co['kind'] == 'pipeline' and co.get('assets'):
        ov = co.get('overrides', {})
        annual = ov.get('annual_burn_musd')
        if annual is None and mk.get('op_cf') is not None:
            annual = max(0.0, -mk['op_cf'])
        first_t = min(s['t'] for a in co['assets'] for s in a['stages'])
        fail_burn = (annual or 0.0) * first_t
    fail_eq = b['commercial'] + b['cash'] - b['debt'] - b['other'] - fail_burn
    fail_ps = fail_eq / mk['shares']
    p_imp = None
    if success['per_share'] is not None and success['per_share'] > fail_ps:
        p_imp = (price - fail_ps) / (success['per_share'] - fail_ps)

    def at(k):
        return value_company(co, mk, g, rf, {'pos_mult': 1.0, 'peak_mult': k, 'growth_mult': 1.0, 'rev_mult': k})['per_share']
    scale = None
    lo, hi = 0.2, 12.0
    if at(lo) <= price <= at(hi):
        for _ in range(50):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if at(mid) < price else (lo, mid)
        scale = (lo + hi) / 2
    modeled = sum(a['peak_musd'] for a in co.get('assets', [])) + (co['commercial']['run_rate_musd'] if co.get('commercial') else 0.0)
    return {'modeled_revenue': modeled, 'required_revenue': modeled * scale if scale is not None else None,
            'fail': fail_ps, 'base': base_ps, 'success': success['per_share'], 'bull_success': bull_ok['per_share'],
            'implied_p': p_imp, 'implied_scale': scale}


def earnings_preview(co, mk, g, rf, cfg, consensus):
    """실적 분해: 2분기 실제(원문) → 3분기 추정(알려진 잠정 매출 + 비용 가정), 컨센서스와 비교,
    그리고 '분기 매출이 얼마면 현재가가 정당화되나'를 기본·낙관 성장 경로로 찾는다."""
    ep = co.get('earnings_preview')
    if not ep or not co.get('commercial'):
        return None
    q2, kn, a = ep['q2_actual'], ep['q3_known'], ep['q3_assumptions']
    sales = kn['product_sales']
    cogs = sales * q2['cogs_product'] / q2['product_sales']
    rnd = q2['rnd'] * (1 + a['rnd_growth'])
    sga = q2['sga'] * (1 + a['sga_growth'])
    pretax = sales + a['service_rev'] - cogs - q2['cogs_service'] - rnd - sga + q2['other_net']
    tax_rate = q2['tax'] / (q2['net_income'] + q2['tax'])
    net = pretax * (1 - tax_rate)
    est = {'product_sales': sales, 'service_rev': a['service_rev'], 'cogs_product': cogs, 'cogs_service': q2['cogs_service'],
           'rnd': rnd, 'sga': sga, 'other_net': q2['other_net'], 'pretax': pretax, 'tax_rate': tax_rate, 'net_income': net,
           'eps_diluted': net / q2['shares_diluted'], 'op_income': sales + a['service_rev'] - cogs - q2['cogs_service'] - rnd - sga}
    run = co['commercial']['run_rate_musd']

    def ps(q, growth_mult):
        return value_company(co, mk, g, rf, {'pos_mult': 1.0, 'peak_mult': 1.0, 'growth_mult': growth_mult,
                                             'rev_mult': q * 4 / run})['per_share']

    def solve(growth_mult):
        lo, hi = 50.0, 2000.0
        if ps(hi, growth_mult) < mk['price']:
            return None
        for _ in range(50):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if ps(mid, growth_mult) < mk['price'] else (lo, mid)
        return (lo + hi) / 2
    bull = cfg['scenarios']['bull']['growth_mult']
    grid = [{'q': q, 'base': ps(q, 1.0), 'bull': ps(q, bull)} for q in range(180, 381, 20)]
    return {'quarter': ep['quarter'], 'report_date': ep['report_date'], 'q2': q2, 'known': kn, 'assumptions': a, 'est': est,
            'consensus': consensus, 'breakeven_base': solve(1.0), 'breakeven_bull': solve(bull), 'bull_growth_mult': bull,
            'grid': grid, 'price': mk['price']}


def fetch_prices(ticker: str):
    """주가 차트용: 최근 1년 일봉, 5년 주봉 종가 (yfinance)."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    d = t.history(period='1y')['Close'].dropna()
    w = t.history(period='5y', interval='1wk')['Close'].dropna()
    fmt = lambda s: [[i.strftime('%Y-%m-%d'), round(float(v), 4)] for i, v in s.items()]
    return {'d': fmt(d), 'w': fmt(w)}


def checks(row, fin):
    """가치 계산에 쓴 값(수동 입력·yfinance)과 SEC XBRL 원문 수치를 나란히. 1% 넘게 다르면 표시."""
    if not fin or not row.get('valuation'):
        return []
    b = row['valuation']['bridge']
    notes = row.get('override_notes') or {}
    out = []

    def add(item, used, sec, sec_date, note):
        if sec is None:
            out.append({'item': item, 'used': used, 'sec': None, 'sec_date': sec_date, 'diff': None, 'note': note or 'SEC XBRL에 해당 항목 없음'})
            return
        diff = (used / sec - 1) if sec else None
        out.append({'item': item, 'used': used, 'sec': sec, 'sec_date': sec_date, 'diff': diff, 'note': note})
    bal = fin['balance']
    add('현금·단기투자', b['cash'], bal['cash_total'], bal['end'], notes.get('cash_note', ''))
    add('차입금', b['debt'], bal['debt'], bal['end'], notes.get('debt_note', ''))
    if fin.get('shares'):
        add('주식 수(백만)', row['market']['shares'], fin['shares']['value'], fin['shares']['date'], notes.get('shares_note', ''))
    return out


def card(co, row, today_iso):
    """대시보드 카드: 다음 일정(확정 우선, 자동은 표시), 실적 발표 당일 여부, 현금 버티는 기간, 업사이드."""
    auto = row.get('auto') or {}
    cands = [{'date': x['date'], 'text': x['text'], 'auto': False} for x in co.get('catalysts', []) if x['date'] >= today_iso]
    e = auto.get('earnings')
    if e and e['date'] >= today_iso:
        cands.append({'date': e['date'], 'text': '실적 발표', 'auto': True})
    for x in auto.get('events', []):
        cands.append({'date': x['date'], 'text': f"{x['date_text']} 일정 (공시 자동 추출)", 'auto': True})
    cands.sort(key=lambda x: (x['date'], x['auto']))
    nxt = cands[0] if cands else None
    v = row.get('valuation')
    runway = None
    fin = row.get('fin') or {}
    if fin.get('runway_months'):
        runway = {'months': fin['runway_months'], 'basis': f"SEC 원문: 현금·단기투자 {fin['balance']['cash_total']:.1f}M ({fin['balance']['end']}) ÷ 최근 2분기 평균 영업현금 유출 {fin['burn_quarter']:.1f}M/분기"}
    elif v and co['kind'] == 'pipeline':
        ov = co.get('overrides', {})
        annual = ov.get('annual_burn_musd')
        if annual is None and row['market'].get('op_cf') is not None:
            annual = max(0.0, -row['market']['op_cf'])
        if annual:
            runway = {'months': v['bridge']['cash'] / (annual / 12), 'basis': ov.get('burn_note', '최근 12개월 영업현금흐름 (yfinance)')}
    p = row.get('payoffs') or {}
    pipe = bool(v and v['assets'])
    top = p.get('bull_success') if pipe else (row.get('scenarios') or {}).get('bull', {}).get('per_share')
    price = row['market']['price']
    return {'next': nxt, 'earnings_today': bool(e and e['date'] == today_iso),
            'runway': runway, 'commercial': co['kind'] != 'pipeline',
            'cf_positive': bool(fin.get('quarters')) and fin.get('burn_quarter') is None,
            'base_up': v['upside'] if v else None, 'top_up': (top / price - 1) if top and price else None,
            'top_label': '낙관 성공' if pipe else '낙관'}


def implied_pos_scale(co, mk, g, rf):
    """시총이 요구하는 PoS 배수 (임상 자산만). 상업 부분·현금·부채는 그대로 두고 남는 자산 가치를 맞춘다."""
    mcap = mk.get('mcap_used') or mk.get('mcap')
    if not co.get('assets') or not mcap:
        return None
    base = value_company(co, mk, g, rf, {'pos_mult': 1.0, 'peak_mult': 1.0, 'growth_mult': 1.0})
    b = base['bridge']
    target = mcap - (b['commercial'] + b['cash'] - b['debt'] - b['other'] - b['burn'])
    if target <= 0:
        return 0.0

    def val(k):
        return value_company(co, mk, g, rf, {'pos_mult': k, 'peak_mult': 1.0, 'growth_mult': 1.0})['bridge']['assets']
    hi = 4.0   # PoS 배수 상한 (각 PoS 는 0.99 로 잘림)
    if val(hi) < target:
        return None
    lo = 0.0
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if val(mid) < target else (lo, mid)
    return (lo + hi) / 2


def build():
    cfg = json.loads(ASSETS.read_text(encoding='utf-8'))
    g = cfg['global']
    prev = load_previous()
    rf, rf_stale = fetch_rf(g['rf_fallback'])
    print(f'무위험이자율 {rf:.2%}{" (대체값)" if rf_stale else ""}')
    companies, problems = [], []
    cache = be.load_cache()
    for co in cfg['companies']:
        t = co['ticker']
        old = prev.get(t, {})
        print(f'{t} 수집')
        stale = []
        try:
            mk, news = fetch_market(t)
        except Exception as e:
            print(f'  시세 실패: {e}', file=sys.stderr)
            mk, news = old.get('market'), old.get('news', [])
            stale.append('market')
            if mk is None:
                problems.append(f'{t} 시세')
                continue
        if not news:
            try:
                news = fetch_news_rss(co['name'], t)
            except Exception as e:
                print(f'  뉴스 RSS 실패: {e}', file=sys.stderr)
                news = old.get('news', [])
        # 자동 수집: 실적 발표일·컨센서스(yfinance), 최근 SEC 공시 목록, 공시 원문 속 일정 후보, 임상 시험 변경
        auto = {'archive_ok': be.ARCHIVE_OK, 'earnings': None, 'filings': [], 'events': [], 'trial_changes': []}
        try:
            auto['earnings'] = be.earnings_event(t)
        except Exception as e:
            print(f'  실적일 실패: {e}', file=sys.stderr)
        if co.get('cik'):
            try:
                auto['filings'] = be.recent_filings(co['cik'], days=60)
                auto['events'] = be.company_filing_events(co['cik'], cache, filings=be.recent_filings(co['cik']))
            except Exception as e:
                print(f'  SEC 공시 실패: {e}', file=sys.stderr)
                auto['filings'] = (old.get('auto') or {}).get('filings', [])
                auto['events'] = (old.get('auto') or {}).get('events', [])
                stale.append('sec')
        seen = {(e['date'], e['kind'], (e.get('sentence') or '')[:60]) for e in (old.get('auto') or {}).get('events', [])}
        first = not old.get('auto')
        for e in auto['events']:
            e['new'] = not first and (e['date'], e['kind'], (e.get('sentence') or '')[:60]) not in seen
        old_acc = {f['acc'] for f in (old.get('auto') or {}).get('filings', [])}
        for f in auto['filings']:
            f['new'] = not first and f['acc'] not in old_acc
        if co.get('overrides', {}).get('shares_m'):      # 원문(공시)의 주식 수가 yfinance 보다 우선
            sh = co['overrides']['shares_m']
            mk = {**mk, 'shares': sh, 'mcap_used': mk['price'] * sh}   # 시총도 같은 주식 수로 다시 계산 (내재 PoS 역산용)
        trials = old.get('trials', [])
        if co.get('ct'):
            try:
                trials = fetch_trials(co['ct']['spons'])
            except Exception as e:
                print(f'  임상 시험 실패: {e}', file=sys.stderr)
                stale.append('trials')
        auto['trial_changes'] = be.trial_changes(old.get('trials', []), trials)
        fin = old.get('fin')
        if co.get('cik'):
            try:
                fin = bx.summarize(bx.fetch(co['cik']))
                fin['filings_url'] = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={co['cik']}&type=10-Q"
            except Exception as e:
                print(f'  XBRL 실패: {e}', file=sys.stderr)
                stale.append('xbrl')
        try:
            prices = fetch_prices(t)
        except Exception as e:
            print(f'  주가 이력 실패: {e}', file=sys.stderr)
            prices = old.get('prices')
        row = {'ticker': t, 'name': co['name'], 'kind': co['kind'], 'summary': co['summary'], 'not_modeled': co.get('not_modeled', ''), 'market': mk, 'news': news,
               'trials': trials, 'auto': auto, 'fin': fin, 'prices': prices, 'facts': co.get('facts', []), 'catalysts': co.get('catalysts', []),
               'assumption_notes': {a['id']: a.get('assumptions', '') for a in co.get('assets', [])}, 'stale': stale}
        if co['kind'] != 'excluded':
            row['valuation'] = value_company(co, mk, g, rf, cfg['scenarios']['base'])
            row['scenarios'] = {}
            for key, sc in cfg['scenarios'].items():
                v = value_company(co, mk, g, rf, sc)
                row['scenarios'][key] = {'label': sc['label'], 'per_share': v['per_share'], 'upside': v['upside'], 'equity': v['equity']}
            row['implied_pos_scale'] = implied_pos_scale(co, mk, g, rf)
            row['payoffs'] = payoffs(co, mk, g, rf, cfg['scenarios'], row['valuation']['per_share'])
            row['earnings_preview'] = earnings_preview(co, mk, g, rf, cfg, auto['earnings'])
            row['card'] = card(co, row, date.today().isoformat())
            row['checks'] = checks(row, fin)
            if co.get('overrides'):
                row['override_notes'] = {k: v for k, v in co['overrides'].items() if k.endswith('_note')}
        companies.append(row)
    try:
        screen = be.market_screen(cache)
    except Exception as e:
        print(f'  시장 스크리닝 실패: {e}', file=sys.stderr)
        screen = None
    be.save_cache(cache)
    out = {'generated_at': datetime.now().isoformat(timespec='seconds'), 'market_screen': screen, 'archive_ok': be.ARCHIVE_OK, 'as_of': cfg['as_of'], 'rf': rf, 'rf_stale': rf_stale,
           'params': g, 'scenarios': {k: v['label'] for k, v in cfg['scenarios'].items()}, 'note': cfg['note'], 'companies': companies}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'저장: {OUT.relative_to(ROOT)} ({len(companies)}개 종목)')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(build())
