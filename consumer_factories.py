"""
소비재 탭: 종목별 국내 생산·물류 사업장의 시군구 → consumer_factories.json

DART 최근 사업보고서의 'II. 사업의 내용 > 원재료 및 생산설비'(생산설비의 현황·주요 사업장) 구역에서 주소를 뽑는다.
주소 옆 낱말로 공장(factory)·물류(logistics)·본사·사무소(office)를 가른다. 관세청 시군구 이름(db/trade.db)과
맞춰 '시도코드:시군구' 꼴로 남기고, 근거로 접수번호와 주소 한 줄을 붙인다(원문은 옮기지 않는다).

build_consumer.py 가 이 파일을 읽어 종목의 품목 묶음 × 공장 지역을 '공장 소재지' 흐름(basis factory)으로 더한다.
흐름이 회사 수출로 확인되는지(상관·비중)는 그쪽에서 데이터로 판정한다 — 여기서는 지역만 찾는다.

  python3 consumer_factories.py            # 아직 없는 종목만
  python3 consumer_factories.py --redo     # 전부 다시
"""

import io
import json
import os
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import requests

import config  # noqa: F401
from collect_history import corp_codes

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'consumer_factories.json'
ASSETS = ROOT / 'consumer_assets.json'
TRADE_DB = ROOT / 'db' / 'trade.db'
API = 'https://opendart.fss.or.kr/api'

SIDO = [('서울', '11'), ('부산', '26'), ('대구', '27'), ('인천', '28'), ('광주', '29'), ('대전', '30'), ('울산', '31'), ('세종', '36'),
        ('경기', '41'), ('충청북', '43'), ('충북', '43'), ('충청남', '44'), ('충남', '44'), ('전라남', '46'), ('전남', '46'),
        ('경상북', '47'), ('경북', '47'), ('경상남', '48'), ('경남', '48'), ('제주', '50'), ('강원', '51'), ('전라북', '52'), ('전북', '52')]
METRO = {'서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종'}
# 2026 개편으로 관세청 시군구 이름이 바뀐 곳 (옛 주소 → 지금 이름)
ALIAS = {('28', '중구'): '제물포구', ('28', '동구'): '제물포구', ('28', '서구'): '서해구', ('46', '광주'): None}
KIND_WORDS = [('factory', ('공장', '생산', '제조', 'Plant', '플랜트', '캠퍼스')), ('logistics', ('물류', '센터', '창고', 'DC')),
              ('office', ('본사', '본점', '사무소', '연구소', '지점', '영업소', '사옥'))]
_ADDR = re.compile(r'(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청북|충북|충청남|충남|전라북|전북|전라남|전남|경상북|경북|경상남|경남|제주)'
                   r'[가-힣]{0,5}\s+([가-힣]{1,5}(?:시|군|구))(?=[\s,·()])')
# 시도 없이 쓴 공장 이름: '세종공장', '원주 공장', '생산공장(원주, 익산, 밀양)'
_BARE = re.compile(r'([가-힣]{2,4})\s?제?\d?\s?(?:공장|사업장)')
_LIST = re.compile(r'(?:공장|사업장)\s*\(([^()]{2,60})\)|\(([^()]{2,60})\)\s*공장')


def section(text: str) -> str:
    """'원재료 및 생산설비' 본문 구역 (목차의 같은 제목은 건너뛴다) — 없으면 빈 문자열"""
    hits = [m.start() for m in re.finditer(r'원재료\s*및\s*생산설비', text)]
    for h in reversed(hits):
        body = text[h:h + 60000]
        end = re.search(r'\n?\s*\d\.\s*매출\s*및\s*수주', body[50:])
        body = body[:end.start() + 50] if end else body[:30000]
        if len(body) > 800:
            return body
    return ''


def addresses(text: str) -> list:
    """구역 안의 주소 → [(시도코드, 시군구 이름, 종류, 주변 글)]. 종류는 주소 앞 60자 안에서 가장 가까운 낱말"""
    out = []
    for m in _ADDR.finditer(text):
        sido = next(code for k, code in SIDO if m.group(1).startswith(k))
        name = m.group(2)
        if sido == '36':
            name = '세종특별자치시'
        before = text[max(0, m.start() - 60):m.start()]
        kind, best = 'other', -1
        for k, words in KIND_WORDS:
            for w in words:
                i = before.rfind(w)
                if i > best:
                    kind, best = k, i
        out.append((sido, name, kind, re.sub(r'\s+', ' ', text[max(0, m.start() - 30):m.end() + 25]).strip()))
    return out


def bare_sites(text: str, known: dict) -> list:
    """시도 없이 이름만 쓴 공장 → [(시도코드, 시군구 끝말, 주변 글)]. 이름이 전국에서 하나뿐인 시·군만 받는다(광주·고성 같은 겹치는 이름은 버린다)"""
    by = {}
    for (sido, name) in known:
        if name.endswith(('시', '군')) and len(name) >= 3:
            by.setdefault(name[:-1], []).append((sido, name))
    out = []
    toks = [(m.group(1), m.start()) for m in _BARE.finditer(text)]
    for m in _LIST.finditer(text):
        for t in re.split(r'[,·/ ]+', m.group(1) or m.group(2)):
            toks.append((t.strip(), m.start()))
    for t, at in toks:
        t = re.sub(r'(시|군)$', '', t)
        if t in METRO:                    # '광주공장'은 광주광역시일 수도 경기 광주시일 수도 있다 — 시도 없이는 정하지 않는다
            continue
        hit = by.get(t)
        if hit and len(hit) == 1:
            out.append((*hit[0], re.sub(r'\s+', ' ', text[max(0, at - 20):at + 40]).strip()))
    return out


def sgg_names(path: Path = TRADE_DB) -> dict:
    """{(시도코드, 끝 이름): 관세청 시군구 전체 이름}"""
    out = {}
    if not path.exists():
        return out
    for sido, full in sqlite3.connect(f'file:{path}?mode=ro', uri=True).execute('SELECT DISTINCT sido, sgg FROM sgg'):
        out[(sido, full.split()[-1])] = full
    return out


def resolve(sido: str, name: str, known: dict):
    """주소의 시군구 → 관세청 이름의 끝말(흐름 regions 에 쓰는 꼴). 모르면 None"""
    name = ALIAS.get((sido, name), name)
    if name is None:
        return None
    if (sido, name) in known:
        return name
    # 일반구가 붙은 주소(성남시 분당구 → 성남시)는 앞의 시로 이미 잡힌다. 군→시 승격 등은 이름만 같으면 받는다
    alt = [n for (s, n) in known if s == sido and n[:-1] == name[:-1]]
    return alt[0] if len(alt) == 1 else None


def latest_report(session, key: str, corp: str):
    r = session.get(f'{API}/list.json', params={'crtfc_key': key, 'corp_code': corp, 'bgn_de': '20240101', 'pblntf_ty': 'A',
                                                 'page_count': 40}, timeout=20).json()
    for x in r.get('list', []):
        if re.search(r'사업보고서', x['report_nm']):
            return x['rcept_no'], x['report_nm']
    return None, None


def report_text(session, key: str, rcept_no: str) -> str:
    z = zipfile.ZipFile(io.BytesIO(session.get(f'{API}/document.xml', params={'crtfc_key': key, 'rcept_no': rcept_no}, timeout=90).content))
    raw = max((z.read(n) for n in z.namelist()), key=len)
    for enc in ('utf-8', 'euc-kr', 'cp949'):
        try:
            xml = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        xml = raw.decode('utf-8', 'replace')
    txt = re.sub(r'<[^>]+>', ' ', xml)
    txt = re.sub(r'&nbsp;|&#160;|&amp;', ' ', txt)
    return re.sub(r'[ \t]+', ' ', txt)


def extract(text: str, known: dict) -> list:
    """보고서 원문 → [{region: '시도:이름', kind, note}] 같은 지역은 한 번(공장 > 물류 > 기타 > 사무소 순으로 남김)"""
    rank = {'factory': 0, 'logistics': 1, 'other': 2, 'office': 3}
    best = {}
    sec = section(text)
    found = addresses(sec) + [(sido, name, 'factory', note) for sido, name, note in bare_sites(sec, known)]
    for sido, name, kind, note in found:
        r = resolve(sido, name, known)
        if not r:
            continue
        key = f'{sido}:{r}'
        if key not in best or rank[kind] < rank[best[key]['kind']]:
            best[key] = {'region': key, 'kind': kind, 'note': note[:90]}
    return sorted(best.values(), key=lambda x: (rank[x['kind']], x['region']))


def main() -> int:
    redo = '--redo' in sys.argv
    key = os.environ.get('DART_API_KEY', '')
    if not key:
        print('DART_API_KEY 없음')
        return 4
    stocks = json.loads(ASSETS.read_text(encoding='utf-8'))['stocks']
    old = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() and not redo else {}
    known = sgg_names()
    s = requests.Session()
    cc = corp_codes(s, key)
    for st in stocks:
        code = st['code']
        if code in old or code not in cc:
            continue
        try:
            rno, rnm = latest_report(s, key, cc[code])
            if not rno:
                old[code] = {'name': st['name'], 'rcept_no': None, 'sites': [], 'err': '사업보고서 없음'}
                continue
            try:
                txt = report_text(s, key, rno)
            except zipfile.BadZipFile:            # 가끔 빈 응답 — 한 번 더
                time.sleep(2)
                txt = report_text(s, key, rno)
            sites = extract(txt, known)
            old[code] = {'name': st['name'], 'rcept_no': rno, 'report': rnm, 'sites': sites}
            print(f"{st['name']:9s} {rnm[:14]:14s} " + ' · '.join(f"{x['region'].split(':')[1]}({x['kind'][:3]})" for x in sites[:8]))
        except (requests.RequestException, zipfile.BadZipFile, ValueError) as e:
            old[code] = {'name': st['name'], 'rcept_no': None, 'sites': [], 'err': type(e).__name__}
            print(st['name'], '실패', type(e).__name__)
        time.sleep(0.3)
    OUT.write_text(json.dumps(old, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'consumer_factories.json: {len(old)}종목, 사업장 찾음 {sum(1 for v in old.values() if v["sites"])}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
