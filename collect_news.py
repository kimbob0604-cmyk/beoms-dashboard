"""
섹터 데일리 뉴스 — 관심 종목(소비재·미용 의료·의료기기)과 섹터 키워드의 기사 제목·링크 (교보·다올 '데일리 뉴스' 모양) → public/data/news.json

네이버 뉴스 검색 API(공식 — NAVER API HUB 키 NAVER_HUB_KEY_ID/KEY, 없으면 예전 NAVER_CLIENT_ID/SECRET)를 종목 이름·키워드마다 최신순 30건씩 부른다. 제목·링크·언론사 주소·시각만 싣는다(본문 없음).
종목·키워드 기사 모두 제목에 그 이름·낱말이 있어야 넣는다(짧은 이름은 앞 글자가 한글·영숫자가 아닐 때만 — '디오' 가 '라디오' 에 걸리지 않게).
최근 7일만 남기고 같은 링크·같은 제목은 하나로. 하루 몇 번 돌려도 된다(호출 수 ≈ 종목 수 + 키워드 수).

  python3 collect_news.py
"""

import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

import config  # noqa: F401
from earn_alert import watch_codes

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'public' / 'data' / 'news.json'
URL = 'https://openapi.naver.com/v1/search/news.json'              # 예전 개발자센터 (2027-06-30 까지)
HUB_URL = 'https://naverapihub.apigw.ntruss.com/search/v1/news'     # 네이버 클라우드 NAVER API HUB (응답 모양은 같다)


def endpoint() -> tuple:
    """(주소, 헤더). .env 에 NAVER_HUB_KEY_ID/NAVER_HUB_KEY 가 있으면 API HUB, 없으면 예전 개발자센터 키"""
    if os.environ.get('NAVER_HUB_KEY_ID') and os.environ.get('NAVER_HUB_KEY'):
        return HUB_URL, {'X-NCP-APIGW-API-KEY-ID': os.environ['NAVER_HUB_KEY_ID'], 'X-NCP-APIGW-API-KEY': os.environ['NAVER_HUB_KEY']}
    return URL, {'X-Naver-Client-Id': os.environ.get('NAVER_CLIENT_ID', ''), 'X-Naver-Client-Secret': os.environ.get('NAVER_CLIENT_SECRET', '')}
KEYWORDS = {'화장품': ['화장품 수출', 'K뷰티', '화장품 ODM', '올리브영'],
            '식음료': ['라면 수출', 'K푸드 수출', '음식료 원가'],
            '미용 의료·의료기기': ['미용의료기기', '톡신 수출', '스킨부스터', '임플란트 수출', '의료관광']}
DAYS = 7
PAUSE = 0.12


def clean(s: str) -> str:
    return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


def name_hit(title: str, name: str) -> bool:
    for m in re.finditer(re.escape(name), title):
        prev = title[m.start() - 1] if m.start() else ' '
        if len(name) > 2 or not re.match(r'[가-힣A-Za-z0-9]', prev):
            return True
    return False


def kw_hit(title: str, kw: str) -> bool:
    """키워드의 낱말이 제목에 모두 있나 ('K-뷰티'·'K 뷰티' 도 'K뷰티' 로 본다)"""
    t = re.sub(r'[\s\-·]', '', title).lower()
    return all(w.lower() in t for w in kw.split())


def search(s, q: str, n: int = 30) -> list:
    r = s.get(s.news_url, params={'query': q, 'display': n, 'sort': 'date'}, timeout=20)
    r.raise_for_status()
    out = []
    for it in r.json().get('items', []):
        try:
            d = parsedate_to_datetime(it['pubDate']).astimezone().replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        link = it.get('originallink') or it.get('link')
        out.append({'t': clean(it['title']), 'link': link, 'nv': it.get('link') if 'naver.com' in (it.get('link') or '') else None,
                    'src': urlparse(link).netloc.replace('www.', ''), 'd': d.isoformat(timespec='minutes')})
    return out


def sectors() -> dict:
    a = json.loads((ROOT / 'consumer_assets.json').read_text(encoding='utf-8'))
    return {s['code']: s['sector'] for s in a['stocks']}


def collect(log=print) -> int:
    if not (os.environ.get('NAVER_HUB_KEY_ID') or os.environ.get('NAVER_CLIENT_ID')):
        log('뉴스: 키 없음(NAVER_HUB_KEY_ID 또는 NAVER_CLIENT_ID) — 건너뜀')
        return 4
    s = requests.Session()
    s.news_url, h = endpoint()
    s.headers.update(h)
    old = json.loads(OUT.read_text(encoding='utf-8')).get('items', []) if OUT.exists() else []
    since = (datetime.now() - timedelta(days=DAYS)).isoformat(timespec='minutes')
    items = {x['link']: x for x in old if x['d'] >= since}
    sec = sectors()
    fail = 0
    jobs = [('c', c, n, sec.get(c, '미용 의료·의료기기')) for c, n in watch_codes().items() if n] + \
           [('k', None, k, sc) for sc, ks in KEYWORDS.items() for k in ks]
    for kind, code, q, sc in jobs:
        try:
            got = search(s, f'"{q}"' if kind == 'c' else q)
        except (requests.RequestException, ValueError) as e:
            fail += 1
            log(f'  실패 {q}: {str(e)[:100]}')
            continue
        finally:
            time.sleep(PAUSE)
        for it in got:
            if it['d'] < since or (kind == 'c' and not name_hit(it['t'], q)) or (kind == 'k' and not kw_hit(it['t'], q)):
                continue
            cur = items.setdefault(it['link'], {**it, 'cs': [], 'ks': [], 'sec': []})
            cur.setdefault('cs', []), cur.setdefault('ks', []), cur.setdefault('sec', [])
            if kind == 'c' and code not in cur['cs']:
                cur['cs'].append(code)
            if kind == 'k' and q not in cur['ks']:
                cur['ks'].append(q)
            if sc not in cur['sec']:
                cur['sec'].append(sc)
    # 같은 제목(통신사 기사 재게재)은 가장 이른 것 하나만
    seen, out = set(), []
    for it in sorted(items.values(), key=lambda x: x['d']):
        key = re.sub(r'\W', '', it['t'])[:40]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    out.sort(key=lambda x: x['d'], reverse=True)
    names = {c: n for c, n in watch_codes().items()}
    OUT.write_text(json.dumps({'built_at': datetime.now().isoformat(timespec='seconds'), 'days': DAYS, 'names': names, 'items': out},
                              ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    log(f'뉴스: 검색 {len(jobs)}번(실패 {fail}), 최근 {DAYS}일 기사 {len(out)}건')
    return 1 if fail > len(jobs) // 4 else 0


if __name__ == '__main__':
    sys.exit(collect())
