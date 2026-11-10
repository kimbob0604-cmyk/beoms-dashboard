"""
바이오 탭: 새 종목 초안 만들기. 원문에서 근거 문장을 모아 .cache/drafts/<종목>.json 으로 저장한다.
초안의 사실은 모두 verified=false 이고, 원문을 읽고 대조한 뒤에만 bio_assets.json 에 옮긴다(자동으로 넣지 않음).

  미장: python3 bio_draft.py SMMT      (SEC 10-K·10-Q·8-K Ex.99 문장, XBRL 현금·주식 수, CT.gov 시험)
  국장: python3 bio_draft.py 000100    (DART 공시 제목·주요내용, 증권사 리포트 산정 근거 문장, DART 재무)
"""

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

import bio_events as be

ROOT = Path(__file__).resolve().parent
OUT = ROOT / '.cache' / 'drafts'

# 시장 크기·가격·일정·현금 근거가 되는 문장
KEYS = {
    'patients': re.compile(r'(approximately|estimated|an estimated|up to)[^.]{0,60}(patients|people|adults|individuals|Americans)', re.I),
    'price': re.compile(r'(WAC|wholesale acquisition cost|list price|net price|per year|annual cost)', re.I),
    'pdufa': re.compile(r'PDUFA|target action date', re.I),
    'readout': re.compile(r'top-?line|data readout|expect(s|ed)? to report', re.I),
    'cash': re.compile(r'cash, cash equivalents|cash and (cash equivalents|investments)', re.I),
    'guidance': re.compile(r'guidance|expects? (net )?(product )?revenue', re.I),
    'patent': re.compile(r'patents?[^.]{0,80}expir', re.I),
}


def cik_of(ticker: str):
    j = be.sec_get('https://www.sec.gov/files/company_tickers.json').json()
    for v in j.values():
        if v['ticker'].upper() == ticker.upper():
            return int(v['cik_str']), v['title']
    return None, None


def _doc_text(cik, acc, name):
    return be.html_to_text(be.sec_get(f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{name}').text)


def us_draft(ticker: str) -> dict:
    cik, title = cik_of(ticker)
    if not cik:
        raise SystemExit(f'{ticker}: SEC 종목 목록에 없음')
    sub = be.sec_get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json').json()['filings']['recent']
    docs = []
    want = {'10-K': 1, '10-Q': 1, '8-K': 6}
    since = (date.today() - timedelta(days=200)).isoformat()
    for k, form in enumerate(sub['form']):
        if want.get(form, 0) <= 0 or sub['filingDate'][k] < since and form == '8-K':
            continue
        acc = sub['accessionNumber'][k].replace('-', '')
        name = sub['primaryDocument'][k]
        if form == '8-K':
            idx = be.sec_get(f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json').json()
            ex = [x['name'] for x in idx['directory']['item'] if re.search(r'ex-?99', x['name'], re.I) and x['name'].endswith('.htm')]
            if not ex:
                continue
            name = ex[0]
        want[form] -= 1
        url = f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{name}'
        try:
            text = _doc_text(cik, acc, name)
        except Exception as e:   # 문서 하나 실패는 건너뛴다
            docs.append({'form': form, 'filed': sub['filingDate'][k], 'url': url, 'error': str(e)[:80]})
            continue
        hits = {}
        for s in be.sentences(text):
            if len(s) > 400:
                continue
            for key, rx in KEYS.items():
                if rx.search(s) and re.search(r'\d', s) and len(hits.setdefault(key, [])) < 6:
                    hits[key].append(s)
        docs.append({'form': form, 'filed': sub['filingDate'][k], 'url': url, 'sentences': hits})
    fin = None
    try:
        import bio_xbrl as bx
        fin = bx.summarize(bx.fetch(cik))
        fin = {'balance': fin.get('balance'), 'shares': fin.get('shares'), 'burn_quarter': fin.get('burn_quarter'),
               'last_quarters': (fin.get('quarters') or [])[-4:]}
    except Exception as e:
        fin = {'error': str(e)[:80]}
    return {'ticker': ticker, 'market': 'US', 'cik': cik, 'name': title, 'docs': docs, 'xbrl': fin, 'trials': trials(title)}


def trials(sponsor: str) -> list:
    spons = re.sub(r',?\s+(Inc|Corp|Corporation|Ltd|plc|Holdings|Therapeutics|Pharmaceuticals|Biosciences)\.?$', '', sponsor or '', flags=re.I).strip()
    try:
        r = requests.get('https://clinicaltrials.gov/api/v2/studies', timeout=30,
                         params={'query.spons': spons, 'pageSize': 40, 'filter.overallStatus': 'RECRUITING,ACTIVE_NOT_RECRUITING,NOT_YET_RECRUITING,ENROLLING_BY_INVITATION',
                                 'fields': 'NCTId,BriefTitle,OverallStatus,Phase,EnrollmentInfo,PrimaryCompletionDate,Condition,InterventionName'})
        r.raise_for_status()
    except Exception as e:
        return [{'error': str(e)[:80]}]
    out = []
    for s in r.json().get('studies', []):
        p = s['protocolSection']
        st, de = p['statusModule'], p.get('designModule', {})
        out.append({'nct': p['identificationModule']['nctId'], 'title': p['identificationModule']['briefTitle'], 'status': st['overallStatus'],
                    'phases': de.get('phases'), 'enroll': (de.get('enrollmentInfo') or {}).get('count'),
                    'pcd': (st.get('primaryCompletionDateStruct') or {}).get('date'), 'conditions': (p.get('conditionsModule') or {}).get('conditions', [])[:3]})
    return out


def kr_draft(code: str) -> dict:
    import bio_kr as bk
    import bio_reports as br
    mk = bk.market(code)
    fl = bk.filings(code, 365)
    rep = br.kr_reports(code)
    try:
        fin = bk.financials(code)
        fin = {'balance': fin.get('balance'), 'burn_quarter': fin.get('burn_quarter'), 'last_quarters': (fin.get('quarters') or [])[-4:]}
    except Exception as e:
        fin = {'error': str(e)[:80]}
    return {'ticker': code, 'market': 'KR', 'quote': mk, 'dart_fin': fin,
            'filings': [{'filed': f['filed'], 'title': f['title'], 'kind': f['kind'], 'url': f['url'], 'data': f.get('data')} for f in fl[:40]],
            'reports': {'summary': rep['summary'], 'items': [{k: x.get(k) for k in ('date', 'broker', 'goal', 'title', 'valuation', 'pdf')} for x in rep['items'][:8]]}}


def main(arg: str):
    OUT.mkdir(parents=True, exist_ok=True)
    d = kr_draft(arg) if arg.isdigit() else us_draft(arg.upper())
    d['made'] = date.today().isoformat()
    d['note'] = '초안: 모든 문장은 원문 대조 전 (verified=false). bio_assets.json 에 옮길 때 원문 링크와 함께 확인할 것.'
    p = OUT / f'{arg.upper()}.json'
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    n = sum(len(v) for x in d.get('docs', []) for v in (x.get('sentences') or {}).values()) if d['market'] == 'US' else len(d.get('filings', []))
    print(f'{p.relative_to(ROOT)}: 근거 {n}개, 시험 {len(d.get("trials", []))}건')
    return p


if __name__ == '__main__':
    for a in sys.argv[1:] or ['SMMT']:
        main(a)
