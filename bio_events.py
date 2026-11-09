"""
바이오 일정 자동 수집: 회사 원문(SEC 공시)에서 PDUFA·탑라인·승인 결정 같은 날짜를 찾고,
실적 발표일·컨센서스는 yfinance 에서, 임상 완료 예정일 변경은 ClinicalTrials.gov 스냅샷 비교로 찾는다.

- 자동으로 찾은 일정은 '검토 필요'로만 표시하고 가치 계산(bio_assets.json 의 stages)에는 넣지 않는다.
  사람이 원문을 보고 bio_assets.json 의 catalysts 에 옮겨야 확정 일정이 된다.
- 회사 문장 그대로(sentence)와 원문 링크(url)를 함께 남겨, 화면에서 바로 대조할 수 있게 한다.
- SEC: data.sec.gov/submissions (회사별 최근 공시), efts.sec.gov 전문 검색(시장 전체 스크리닝).
  초당 10회 제한을 지키려고 요청 사이에 쉬고, 이미 읽은 공시는 .cache/bio_sec.json 에 결과를 남겨 다시 받지 않는다.

  python3 bio_events.py LQDA      # 한 종목 점검
"""

import html
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

import config  # noqa: F401  (.env 를 환경변수로 읽는다)
import os

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / '.cache' / 'bio_sec.json'
# SEC 공정 접근 정책: 공시 원문(www.sec.gov/Archives)은 User-Agent 에 이름·이메일이 있어야 열린다.
# .env 에 SEC_USER_AGENT="이름 이메일" 을 넣으면 원문 추출까지, 없으면 공시 목록(data.sec.gov)만 쓴다.
SEC_UA = os.environ.get('SEC_USER_AGENT', '').strip()
ARCHIVE_OK = bool(SEC_UA)
SEC_H = {'User-Agent': SEC_UA or 'BeomDashboard bio-research script', 'Accept-Encoding': 'gzip, deflate'}
ITEM_LABELS = {'1.01': '중요 계약', '1.02': '계약 종료', '2.02': '실적', '2.03': '채무 발생', '3.02': '주식 발행',
               '5.02': '임원 변경', '5.07': '주총 결과', '7.01': '보도자료(Reg FD)', '8.01': '기타 중요 사항', '9.01': '첨부'}
FORMS = ('8-K', '6-K', '10-Q', '10-K')
LOOKBACK_DAYS = 120
MAX_DOCS_PER_COMPANY = 12

MONTHS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
                                       'september', 'october', 'november', 'december'], 1)}
_MON = '(january|february|march|april|may|june|july|august|september|october|november|december)'
_ORD = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, '1': 1, '2': 2, '3': 3, '4': 4}

# 날짜 표현 → (ISO 날짜, 정밀도). 기간 표현은 그 기간의 마지막 날로 둔다.
DATE_RULES = [
    (re.compile(rf'\b{_MON}\s+(\d{{1,2}}),\s*(20\d\d)', re.I),
     lambda m: (date(int(m[3]), MONTHS[m[1].lower()], int(m[2])), 'day')),
    (re.compile(r'\b(first|second|third|fourth)\s+quarter\s+of\s+(?:calendar\s+(?:year\s+)?)?(20\d\d)', re.I),
     lambda m: (_q_end(int(m[2]), _ORD[m[1].lower()]), 'quarter')),
    (re.compile(r'\b(?:Q([1-4])\s*(20\d\d)|([1-4])Q\s*(20\d\d|\d\d))\b', re.I),
     lambda m: (_q_end(_yr(m[2] or m[4]), int(m[1] or m[3])), 'quarter')),
    (re.compile(r'\b(first|second)\s+half\s+of\s+(?:calendar\s+(?:year\s+)?)?(20\d\d)', re.I),
     lambda m: (date(int(m[2]), 6 if m[1].lower() == 'first' else 12, 30 if m[1].lower() == 'first' else 31), 'half')),
    (re.compile(r'\b([12])H\s*(20\d\d|\d\d)\b', re.I),
     lambda m: (date(_yr(m[2]), 6 if m[1] == '1' else 12, 30 if m[1] == '1' else 31), 'half')),
    (re.compile(r'\b(?:by\s+)?(?:year[- ]end|end\s+of)\s+(20\d\d)', re.I),
     lambda m: (date(int(m[1]), 12, 31), 'year')),
    (re.compile(r'\bin\s+calendar\s+(?:year\s+)?(20\d\d)', re.I),
     lambda m: (date(int(m[1]), 12, 31), 'year')),
]

# 키워드 → 일정 종류. 위에서부터 먼저 맞는 것.
KINDS = [
    ('regulatory', re.compile(r'PDUFA|target action date|approval decision|CHMP|marketing authori[sz]ation|MAAs?\b|'
                              r'regulatory decision|advisory committee', re.I)),
    ('readout', re.compile(r'top[- ]?line|data readout|results? (?:are |is )?(?:expected|anticipated)|'
                           r'report (?:topline )?data|read[- ]?out', re.I)),
    ('milestone', re.compile(r'enrollment (?:completion|complete)|initiat(?:e|ion) (?:of )?(?:a |the )?(?:pivotal|phase)|'
                             r'(?:NDA|BLA|sNDA|sBLA) (?:submission|filing)|submit (?:an? )?(?:NDA|BLA)', re.I)),
]


def _yr(s: str) -> int:
    y = int(s)
    return y + 2000 if y < 100 else y


def _q_end(y: int, q: int) -> date:
    return {1: date(y, 3, 31), 2: date(y, 6, 30), 3: date(y, 9, 30), 4: date(y, 12, 31)}[q]


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_cache(c: dict):
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(c, ensure_ascii=False), encoding='utf-8')


def sec_get(url: str, **kw):
    time.sleep(0.15)   # SEC 초당 10회 제한
    r = requests.get(url, headers=SEC_H, timeout=30, **kw)
    r.raise_for_status()
    return r


def html_to_text(s: str) -> str:
    """HTML → 텍스트. 문단(블록) 경계는 줄바꿈으로 남겨, 문장이 다른 문단과 섞이지 않게 한다."""
    s = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', s)
    s = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h\d|td|table)>', '\n', s)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s).replace('\xa0', ' ')
    s = re.sub(r'[ \t\r\f\v]+', ' ', s)
    return re.sub(r'\s*\n\s*', '\n', s).strip()


# 소문자·숫자 뒤나 두 글자 이상 약어(RA., GD.) 뒤의 마침표에서 나눈다. U.S., U.K. 같은 한 글자 약어에서는 끊지 않는다.
_SPLIT = re.compile(r'(?:(?<=[a-z0-9)%][.!?])|(?<=[A-Z]{2}[.!?]))\s+(?=[A-Z•·\-–(])')


def sentences(text: str):
    for para in text.split('\n'):
        for s in _SPLIT.split(para):
            s = s.strip(' .•·-–')
            if 30 <= len(s) <= 600:
                yield s


HILITE = re.compile(r'\$\s?\d|\d+(?:\.\d+)?\s?%|PDUFA|top[- ]?line|approv|guidance|cash (?:and|position|runway)|'
                    r'primary endpoint|met |did not|discontinu|initiat|enroll', re.I)


def press_release(text: str, max_lines: int = 6) -> dict:
    """보도자료 텍스트 → 제목(첫 'Announces/Reports/Provides…' 문장)과 숫자·일정이 든 핵심 문장 몇 개."""
    title = None
    for line in text.split('\n')[:60]:
        line = line.strip()
        if 20 <= len(line) <= 220 and re.search(r'\b(Announces?|Reports?|Provides?|Presents?|Receives?|Completes?|Enters?)\b', line):
            title = line
            break
    out, seen = [], set()
    for s in sentences(text):
        if len(s) > 320 or not HILITE.search(s) or re.search(r'forward-looking|Securities Litigation|undue reliance|risk factors', s, re.I):
            continue
        k = s[:60]
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= max_lines:
            break
    return {'title': title, 'highlights': out}


def extract_events(text: str, today: date | None = None) -> list:
    """원문 텍스트에서 '키워드 + 미래 날짜'가 함께 있는 문장을 일정 후보로 뽑는다."""
    today = today or date.today()
    out, seen = [], set()
    for s in sentences(text):
        kind = next((k for k, rx in KINDS if rx.search(s)), None)
        if not kind:
            continue
        for rx, conv in DATE_RULES:
            for m in rx.finditer(s):
                try:
                    d, prec = conv(m)
                except (ValueError, KeyError):
                    continue
                if d < today or d > date.today() + timedelta(days=365 * 4):   # 상한은 실제 오늘 기준 (캐시용 호출은 today 를 과거로 줌)
                    continue
                key = (d.isoformat(), kind, s[:80])
                if key in seen:
                    continue
                seen.add(key)
                out.append({'date': d.isoformat(), 'precision': prec, 'date_text': m.group(0), 'kind': kind, 'sentence': s})
    return out


def recent_filings(cik: int, today: date | None = None, days: int = LOOKBACK_DAYS) -> list:
    """회사 최근 공시 목록 (data.sec.gov, User-Agent 이메일 없이도 열림)."""
    today = today or date.today()
    sub = sec_get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json').json()['filings']['recent']
    since = (today - timedelta(days=days)).isoformat()
    out = []
    for i, form in enumerate(sub['form']):
        if form not in FORMS or sub['filingDate'][i] < since:
            continue
        acc = sub['accessionNumber'][i]
        items = [x for x in (sub.get('items') or [''] * len(sub['form']))[i].split(',') if x]
        out.append({'acc': acc, 'filed': sub['filingDate'][i], 'form': form, 'primary': sub['primaryDocument'][i], 'items': items,
                    'labels': [ITEM_LABELS.get(x, x) for x in items if x != '9.01'],
                    'url': f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace("-", "")}/{sub["primaryDocument"][i]}'})
    return out


def company_filing_events(cik: int, cache: dict, today: date | None = None, filings: list | None = None) -> list:
    """회사 최근 공시(8-K 별첨 보도자료, 10-Q 등)에서 일정 후보를 찾는다. 최근 공시가 같은 날짜를 다시 말하면 최신 것만 남긴다.
    원문을 열 수 없으면(SEC_USER_AGENT 미설정) 빈 목록."""
    today = today or date.today()
    if not ARCHIVE_OK:
        return []
    filings = filings if filings is not None else recent_filings(cik, today)
    docs = [(f['acc'], f['filed'], f['form'], f['primary']) for f in filings]
    events = []
    for acc, filed, form, primary in docs[:MAX_DOCS_PER_COMPANY]:
        key = f'v6:{cik}:{acc}'   # v6: 보도자료 제목·핵심 문장 추가
        if key not in cache:
            base = f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace("-", "")}'
            urls = [f'{base}/{primary}']
            if form in ('8-K', '6-K'):   # 보도자료는 보통 별첨 99.x
                try:
                    idx = sec_get(f'{base}/index.json').json()['directory']['item']
                    urls += [f'{base}/{x["name"]}' for x in idx if re.search(r'ex(?:hibit)?[-_]?99', x['name'], re.I) and x['name'].endswith('.htm')]
                except (requests.RequestException, ValueError, KeyError):
                    pass
            found, failed, pr = [], 0, None
            for u in urls:
                try:
                    txt = html_to_text(sec_get(u).text)
                except requests.RequestException as ex:
                    failed += 1
                    print(f'  SEC 원문 실패 {u}: {ex}', file=sys.stderr)
                    continue
                for e in extract_events(txt, today=date(2000, 1, 1)):   # 캐시에는 과거 것까지 두고, 쓸 때 거른다
                    found.append({**e, 'url': u})
                if re.search(r'ex(?:hibit)?[-_]?99', u, re.I) and pr is None:   # 첫 보도자료 별첨
                    pr = {**press_release(txt), 'url': u}
            if failed:   # 하나라도 못 읽었으면 캐시에 남기지 않고 다음 실행에서 다시 읽는다
                events += [{**e, 'filed': filed, 'form': form, 'src': f'SEC {form} ({filed})'} for e in found if e['date'] >= today.isoformat()]
                continue
            cache[key] = {'filed': filed, 'form': form, 'events': found, 'pr': pr}
        for e in cache[key]['events']:
            if e['date'] >= today.isoformat():
                events.append({**e, 'filed': cache[key]['filed'], 'form': cache[key]['form'], 'src': f'SEC {cache[key]["form"]} ({cache[key]["filed"]})'})
    # 가장 최근 정기보고서(10-Q·10-K)보다 오래된 공시의 일정은 버린다: 정기보고서가 현재 안내를 다시 적으므로,
    # 그 전 8-K 의 일정(예: 8월 '4분기 탑라인' → 11월 '1분기')은 이미 바뀌었을 수 있다.
    periodic = [f[1] for f in docs if f[2] in ('10-Q', '10-K')]
    if periodic:
        events = [e for e in events if e['filed'] >= max(periodic)]
    # 같은 날짜·종류는 가장 최근 공시 하나만
    events.sort(key=lambda e: e['filed'], reverse=True)
    uniq, seen = [], set()
    for e in events:
        k = (e['date'], e['kind'])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)
    uniq.sort(key=lambda e: e['date'])
    return uniq


def company_ir(cik: int, cache: dict, filings: list) -> list:
    """최근 8-K 보도자료: 제목과 핵심 문장 (company_filing_events 가 캐시에 남긴 것)."""
    out = []
    for f in filings:
        c = cache.get(f'v6:{cik}:{f["acc"]}')
        if c and c.get('pr') and (c['pr'].get('title') or c['pr'].get('highlights')):
            out.append({'filed': f['filed'], 'form': f['form'], 'labels': f['labels'], **c['pr']})
    return out


def earnings_event(ticker: str):
    """다음 실적 발표일과 컨센서스 (yfinance, 회사 원문 아님)."""
    import yfinance as yf
    cal = yf.Ticker(ticker).calendar or {}
    ds = cal.get('Earnings Date') or []
    if not ds:
        return None
    d = ds[0]
    m = lambda v: None if v is None else v / 1e6
    return {'date': d.isoformat(), 'precision': 'day', 'kind': 'earnings', 'src': 'yfinance (예정일·컨센서스, 원문 아님)',
            'eps_avg': cal.get('Earnings Average'), 'eps_low': cal.get('Earnings Low'), 'eps_high': cal.get('Earnings High'),
            'rev_avg': m(cal.get('Revenue Average')), 'rev_low': m(cal.get('Revenue Low')), 'rev_high': m(cal.get('Revenue High'))}


def trial_changes(old: list, new: list) -> list:
    """ClinicalTrials.gov 1차 완료 예정일이 바뀌었거나 새로 생긴 시험."""
    prev = {t['id']: t for t in old or []}
    out = []
    for t in new:
        p = prev.get(t['id'])
        if p is None and prev:
            out.append({'id': t['id'], 'change': '새 시험', 'before': None, 'after': t.get('done'), 'title': t['title']})
        elif p and p.get('done') != t.get('done'):
            out.append({'id': t['id'], 'change': '완료 예정일 변경', 'before': p.get('done'), 'after': t.get('done'), 'title': t['title']})
        elif p and p.get('status') != t.get('status'):
            out.append({'id': t['id'], 'change': f'상태 변경 {p.get("status")} → {t.get("status")}', 'before': p.get('done'),
                        'after': t.get('done'), 'title': t['title']})
    return out


SCREEN_QUERIES = [
    ('regulatory', '"PDUFA"'),
    ('readout', '"topline data" AND ("expected" OR "anticipated")'),
]


def market_screen(cache: dict, days: int = 30, limit: int = 100, today: date | None = None) -> list:
    # 원문을 못 열면(SEC_USER_AGENT 미설정) 회사·공시일·링크만 돌려준다 (날짜는 원문을 열어야 뽑을 수 있음)
    """시장 전체: 최근 30일 8-K·6-K 에서 PDUFA·탑라인 일정을 말한 회사를 찾는다 (EDGAR 전문 검색, 검색어마다 최대 100건)."""
    today = today or date.today()
    start = (today - timedelta(days=days)).isoformat()
    hits = []
    for kind, q in SCREEN_QUERIES:
        try:
            r = sec_get('https://efts.sec.gov/LATEST/search-index',
                        params={'q': q, 'forms': '8-K,6-K', 'dateRange': 'custom', 'startdt': start, 'enddt': today.isoformat()})
        except requests.RequestException as e:
            print(f'  전문 검색 실패 ({q}): {e}', file=sys.stderr)
            continue
        for h in r.json().get('hits', {}).get('hits', [])[:limit]:
            src = h['_source']
            adsh, fname = h['_id'].split(':', 1)
            cik = int(src['ciks'][0])
            name = (src.get('display_names') or [''])[0]
            hits.append({'kind': kind, 'adsh': adsh, 'file': fname, 'cik': cik, 'name': name, 'filed': src.get('file_date')})
    out, seen = [], set()
    for h in hits:
        key = f'v6:{h["cik"]}:{h["adsh"]}:{h["file"]}'
        if key in seen:
            continue
        seen.add(key)
        url = f'https://www.sec.gov/Archives/edgar/data/{h["cik"]}/{h["adsh"].replace("-", "")}/{h["file"]}'
        m = re.search(r'\(([A-Z.\-]{1,6})\)', h['name'])
        company = re.sub(r'\s*\(.*$', '', h['name']).strip()
        if not ARCHIVE_OK:
            out.append({'kind': h['kind'], 'company': company, 'ticker': m.group(1) if m else None, 'filed': h['filed'],
                        'url': url, 'date': None, 'date_text': None, 'sentence': None})
            continue
        if key not in cache:
            try:
                ev = extract_events(html_to_text(sec_get(url).text), today=date(2000, 1, 1))
            except requests.RequestException as ex:
                print(f'  SEC 원문 실패 {url}: {ex}', file=sys.stderr)
                continue
            cache[key] = {'filed': h['filed'], 'events': ev}
        for e in cache[key]['events']:
            if e['date'] >= today.isoformat() and e['kind'] in ('regulatory', 'readout'):
                out.append({**e, 'company': company, 'ticker': m.group(1) if m else None, 'filed': h['filed'], 'url': url})
    out.sort(key=lambda e: (e['date'] or '9999', e['company']))
    uniq, seen = [], set()
    for e in out:
        k = (e['company'], e['date'] or e['filed'], e['kind'])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


if __name__ == '__main__':
    c = load_cache()
    print('원문 추출', '가능' if ARCHIVE_OK else '불가 (.env 에 SEC_USER_AGENT 필요)')
    for arg in sys.argv[1:] or ['LQDA:1819576']:
        t, cik = arg.split(':')
        print(t, json.dumps(earnings_event(t), ensure_ascii=False, default=str))
        fl = recent_filings(int(cik))
        for f in fl[:5]:
            print(f"  공시 {f['filed']} {f['form']} {','.join(f['labels'])}")
        for e in company_filing_events(int(cik), c, filings=fl):
            print(f"  {e['date']} {e['kind']:10} {e['date_text']!r} ← {e['src']}: {e['sentence'][:150]}")
    save_cache(c)
