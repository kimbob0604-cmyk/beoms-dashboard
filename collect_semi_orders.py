"""
반도체 탭: 국내 밸류체인 종목의 수주·투자 공시 5년치 (docs/semi-plan.md §4.3·§5.2) → db/semi.db

- 단일판매ㆍ공급계약체결 / 해지  → kind contract / contract_x (계약명·금액·최근 매출·매출 대비 %·계약상대·지역·기간)
- 신규시설투자등                 → kind facility (투자 구분·금액·자기자본 대비 %·목적·기간) — 삼성·하이닉스 증설의 공식 신호
회사별로 DART 목록(거래소 공시, 5년)을 받아 원문을 읽는다. 공시 탭이 쓰는 dart_filing 표는 건드리지 않는다(날짜별 수집과 섞이지 않게).
한 번 읽은 접수번호는 다시 읽지 않는다. 매일 실행하면 최근 공시만 더한다.

python3 collect_semi_orders.py               # semi_assets.json 의 국내 종목 전부
python3 collect_semi_orders.py --code 042700 # 한 종목
python3 collect_semi_orders.py --shard 0/4   # 나눠서 나란히
"""
import argparse
import fcntl
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

import config  # noqa: F401
from collectors import dart
from collect_fund import corp_codes

ROOT = Path(__file__).parent
DB = ROOT / 'db' / 'semi.db'
ASSETS = ROOT / 'semi_assets.json'
API = dart.API
DELAY = 0.12
YEARS = 5
log = logging.getLogger('semi_orders')

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    rcept_no TEXT PRIMARY KEY, code TEXT, name TEXT, date TEXT, kind TEXT, title TEXT, fixed INTEGER, data TEXT, at TEXT
);
CREATE INDEX IF NOT EXISTS orders_code ON orders (code, date);
CREATE TABLE IF NOT EXISTS orders_done (code TEXT PRIMARY KEY, upto TEXT, at TEXT);   -- 목록을 어디까지 받았나
"""


def kind_of(report_nm: str):
    n = re.sub(r'\s+', '', report_nm)
    if any(s in n for s in ('첨부정정', '첨부추가', '자회사의주요경영사항')):
        return None
    if '단일판매ㆍ공급계약해지' in n or '단일판매·공급계약해지' in n:
        return 'contract_x'
    if '단일판매ㆍ공급계약체결' in n or '단일판매·공급계약체결' in n:
        return 'contract'
    if '신규시설투자' in n:
        return 'facility'
    return None


def parse_facility(c):
    """신규시설투자등: 투자 구분·금액·자기자본 대비·목적·기간"""
    return {
        'name': dart.after(c, '1.투자구분') or dart.after(c, '투자구분'),
        'amt': dart.num(dart.after(c, '투자금액(원)')),
        'equity': dart.num(dart.after(c, '자기자본(원)')),
        'pct': dart.num(dart.after(c, '자기자본대비(%)')),
        'purpose': dart.after(c, '3.투자목적') or dart.after(c, '투자목적'),
        'start': dart.ymd(dart.after(c, '시작일')), 'end': dart.ymd(dart.after(c, '종료일')),
    }


def parse(kind, cells):
    if kind == 'facility':
        return parse_facility(dart.body_of(cells))
    return dart.parse(kind, cells)


def listing(session, key, corp, bgn: str):
    """그 회사의 거래소 공시 목록 (bgn 이후) — 수주·투자 공시만"""
    out, page = [], 1
    end = date.today().strftime('%Y%m%d')
    while True:
        r = session.get(f'{API}/list.json', params={'crtfc_key': key, 'corp_code': corp, 'bgn_de': bgn, 'end_de': end,
                                                    'pblntf_ty': 'I', 'page_no': page, 'page_count': 100}, timeout=30)
        r.raise_for_status()
        j = r.json()
        if j.get('status') == '013':
            return out
        if j.get('status') != '000':
            raise ValueError(f"DART {j.get('status')}")
        out += [x for x in j['list'] if kind_of(x['report_nm'])]
        if page >= int(j.get('total_page') or 1):
            return out
        page += 1
        time.sleep(DELAY)


def refix(key) -> int:
    conn = sqlite3.connect(str(DB), timeout=60)
    s = requests.Session()
    rows = conn.execute("SELECT rcept_no, kind FROM orders WHERE (json_extract(data, '$.amt') IS NULL OR json_extract(data, '$.party') IS NULL) "
                        "AND kind IN ('contract', 'contract_x', 'facility')").fetchall()
    n = 0
    for rno, kind in rows:
        try:
            data = parse(kind, dart.fetch_cells(s, key, rno))
        except Exception as e:
            log.warning('%s 다시 읽기 실패: %s', rno, type(e).__name__)
            continue
        if data.get('amt') or data.get('party'):
            with conn:
                conn.execute('UPDATE orders SET data = ? WHERE rcept_no = ?', (json.dumps(data, ensure_ascii=False), rno))
            n += 1
        time.sleep(DELAY)
    log.info('다시 읽음: %d건 중 %d건 채움', len(rows), n)
    return 0


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    ap = argparse.ArgumentParser()
    ap.add_argument('--code')
    ap.add_argument('--shard', help='i/n')
    ap.add_argument('--refix', action='store_true', help='정정 공시 중 금액·상대가 빈 것을 다시 읽는다 (파서 고친 뒤)')
    args = ap.parse_args()
    key = os.environ.get('DART_API_KEY', '')
    if not key:
        log.info('DART_API_KEY 없음 — 건너뜀')
        return 4
    if args.refix:
        return refix(key)
    codes = [args.code] if args.code else [s['code'] for s in json.loads(ASSETS.read_text(encoding='utf-8'))['stocks'] if s.get('code')]
    shard = None
    if args.shard:
        i, n = map(int, args.shard.split('/'))
        shard = (i, n)
        codes = [c for k, c in enumerate(codes) if k % n == i]
    lock = open(ROOT / 'logs' / (f'semi_orders.{shard[0]}.lock' if shard else 'semi_orders.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info('다른 수집이 도는 중 — 건너뜀')
        return 0
    conn = sqlite3.connect(str(DB), timeout=60)
    conn.executescript(SCHEMA)
    s = requests.Session()
    cc = corp_codes(s, key)
    have = {r[0] for r in conn.execute('SELECT rcept_no FROM orders')}
    done = {r[0]: r[1] for r in conn.execute('SELECT code, upto FROM orders_done')}
    first = (date.today() - timedelta(days=365 * YEARS)).strftime('%Y%m%d')
    new = errors = fails = 0
    for code in codes:
        if code not in cc:
            continue
        bgn = (datetime.strptime(done[code], '%Y-%m-%d') - timedelta(days=7)).strftime('%Y%m%d') if code in done else first
        try:
            rows = listing(s, key, cc[code], bgn)
        except (requests.RequestException, ValueError) as e:
            errors += 1
            log.warning('%s 목록 실패: %s', code, type(e).__name__)      # 예외 글에는 키가 든 주소가 있다 — 이름만
            continue
        for r in rows:
            if r['rcept_no'] in have:
                continue
            kind = kind_of(r['report_nm'])
            data = None
            try:
                data = parse(kind, dart.fetch_cells(s, key, r['rcept_no']))
                fails = 0
            except requests.RequestException as e:
                errors += 1
                fails += 1
                log.warning('%s %s 원문 실패: %s', r['corp_name'], r['report_nm'].strip(), type(e).__name__)
                if fails >= 8:
                    log.error('DART 응답 없음 — 중단')
                    return 3
                continue
            except Exception as e:      # 양식이 달라 못 읽은 공시는 제목만
                log.warning('%s %s 파싱 실패: %s', r['corp_name'], r['report_nm'].strip(), type(e).__name__)
                data = {}
            d = f"{r['rcept_dt'][:4]}-{r['rcept_dt'][4:6]}-{r['rcept_dt'][6:]}"
            with conn:
                conn.execute('INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                             (r['rcept_no'], code, r['corp_name'], d, kind, ' '.join(r['report_nm'].split()),
                              int('정정' in r['report_nm']), json.dumps(data, ensure_ascii=False), datetime.now().isoformat(timespec='seconds')))
            new += 1
            time.sleep(DELAY)
        with conn:
            conn.execute('INSERT OR REPLACE INTO orders_done VALUES (?, ?, ?)', (code, date.today().isoformat(), datetime.now().isoformat(timespec='seconds')))
        time.sleep(DELAY)
    log.info('수주·투자 공시: 새로 %d건, 오류 %d (대상 %d종목)', new, errors, len(codes))
    return 1 if errors > 10 else 0


if __name__ == '__main__':
    sys.exit(main())
