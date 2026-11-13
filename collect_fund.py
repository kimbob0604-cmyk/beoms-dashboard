"""
펀더멘털 축적 수집 → db/fund.db (계획 docs/fundamental-plan.md)

대상(fund_watch.json 의 codes)마다 2023년 이후 정기보고서(분기·반기·사업)를 DART 에서 찾아, 아직 안 받은 보고서만
  · 원문(document.xml)의 '비용의 성격별 분류' 주석 표  → fund_fact topic 'nature' (연결 C / 별도 S)
  · XBRL(fnlttXbrl.xml)의 손익(매출·영업이익 …)         → topic 'is',  주석 XBRL 이 있으면 topic 'nature_x'(검증용)
을 받는다. 접수번호 순서로 넣어 같은 기간 값은 나중 보고서(정정·재작성)가 덮어쓴다.

  python3 collect_fund.py                 # 새 보고서만 (한 번에 --max 건까지)
  python3 collect_fund.py --code 078350   # 한 종목
  python3 collect_fund.py --add 078350    # 대상에 더하고 받기
  python3 collect_fund.py --reparse       # 캐시한 원문으로 주석 표만 다시 읽기 (파서·규칙을 고친 뒤)

종료 코드: 0 정상, 1 일부 실패, 3 DART 응답 없음, 4 키 없음
"""

import argparse
import io
import json
import logging
import os
import re
import sqlite3
import sys
import time
import zipfile
from calendar import monthrange
from datetime import datetime
from pathlib import Path

import requests

import config  # noqa: F401
import fund
import fund_xbrl

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'db' / 'fund.db'
WATCH = ROOT / 'fund_watch.json'
CORP = ROOT / '.cache' / 'dart_corp.json'
API = 'https://opendart.fss.or.kr/api'
SINCE = '20230101'
DELAY = 0.25
log = logging.getLogger('collect_fund')

SCHEMA = """
CREATE TABLE IF NOT EXISTS fund_report (
    rcept_no TEXT PRIMARY KEY, code TEXT NOT NULL, name TEXT, period_end TEXT, kind TEXT,   -- kind Q(분기·반기) / A(사업)
    fetched_at TEXT, note TEXT                                                              -- note: 못 읽은 것 등
);
CREATE INDEX IF NOT EXISTS fund_report_code ON fund_report (code);
CREATE TABLE IF NOT EXISTS fund_fact (
    code TEXT NOT NULL, basis TEXT NOT NULL,          -- C 연결 / S 별도 / X 구분 없음
    topic TEXT NOT NULL,                              -- nature(원문 주석) / nature_x(주석 XBRL) / is(손익 XBRL)
    item TEXT NOT NULL, label TEXT,                   -- item = 공통 키 (fund.key_of), label = 회사가 쓴 이름
    start TEXT NOT NULL, end TEXT NOT NULL, value REAL,   -- 억원
    rcept_no TEXT, ord INTEGER,
    PRIMARY KEY (code, basis, topic, item, start, end)
);
"""


def connect(path=DB):
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def watch() -> list:
    if not WATCH.exists():
        return []
    return list(dict.fromkeys(json.loads(WATCH.read_text(encoding='utf-8')).get('codes', [])))


def add_watch(codes: list):
    data = json.loads(WATCH.read_text(encoding='utf-8')) if WATCH.exists() else {'codes': []}
    data['codes'] = list(dict.fromkeys(data.get('codes', []) + codes))
    WATCH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def corp_codes(session, key) -> dict:
    if CORP.exists():
        return json.loads(CORP.read_text(encoding='utf-8'))
    from collect_history import corp_codes as fetch
    out = fetch(session, key)
    CORP.parent.mkdir(exist_ok=True)
    CORP.write_text(json.dumps(out), encoding='utf-8')
    return out


def parse_name(nm: str):
    """'분기보고서 (2026.09)' → ('Q', '2026-09-30'), '사업보고서 (2025.12)' → ('A', '2025-12-31')"""
    m = re.search(r'(분기|반기|사업)보고서\s*\((\d{4})\.(\d{2})\)', nm)
    if not m:
        return None, None
    y, mth = int(m.group(2)), int(m.group(3))
    return ('A' if m.group(1) == '사업' else 'Q'), f'{y}-{mth:02d}-{monthrange(y, mth)[1]:02d}'


def reports(session, key, corp: str) -> list:
    """[(rcept_no, 이름, kind, period_end)] 접수 순"""
    out, page = [], 1
    while True:
        r = session.get(f'{API}/list.json', params={'crtfc_key': key, 'corp_code': corp, 'bgn_de': SINCE, 'pblntf_ty': 'A',
                                                     'page_count': 100, 'page_no': page}, timeout=20).json()
        for x in r.get('list', []):
            kind, end = parse_name(x['report_nm'])
            if kind:
                out.append((x['rcept_no'], x['report_nm'], kind, end))
        if page >= int(r.get('total_page') or 1):
            break
        page += 1
        time.sleep(DELAY)
    return sorted(out)


def reprt_code(kind: str, end: str, fy_end: int) -> str:
    if kind == 'A':
        return '11011'
    n = (int(end[5:7]) - fy_end) % 12
    return {3: '11013', 6: '11012', 9: '11014'}.get(n, '11013')


DOCS = ROOT / '.cache' / 'fund_docs'      # 원문 캐시 (gzip) — 파서를 고치거나 다른 주석 토픽을 더할 때 다시 내려받지 않는다


def document(session, key, rcept_no: str) -> str:
    import gzip
    f = DOCS / f'{rcept_no}.xml.gz'
    if f.exists():
        return gzip.decompress(f.read_bytes()).decode('utf-8')
    z = zipfile.ZipFile(io.BytesIO(session.get(f'{API}/document.xml', params={'crtfc_key': key, 'rcept_no': rcept_no}, timeout=120).content))
    raw = max((z.read(n) for n in z.namelist()), key=len)
    for enc in ('utf-8', 'euc-kr', 'cp949'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode('utf-8', 'replace')
    DOCS.mkdir(parents=True, exist_ok=True)
    f.write_bytes(gzip.compress(text.encode('utf-8')))
    return text


XBRLS = ROOT / '.cache' / 'fund_xbrl'     # XBRL 압축 캐시 (손익·주석 XBRL·부문)


def xbrl_zip(session, key, rcept_no: str, code: str) -> bytes:
    f = XBRLS / f'{rcept_no}.zip'
    if f.exists():
        return f.read_bytes()
    z = session.get(f'{API}/fnlttXbrl.xml', params={'crtfc_key': key, 'rcept_no': rcept_no, 'reprt_code': code}, timeout=120).content
    time.sleep(DELAY)
    if z[:2] == b'PK':
        XBRLS.mkdir(parents=True, exist_ok=True)
        f.write_bytes(z)
    return z


def xbrl_rows(zbytes: bytes, rno: str) -> list:
    """XBRL → fund_fact 줄: 손익(is), 주석 XBRL 성격별 비용(nature_x), 부문·제품·지역별 매출/영업이익(seg:rev · prod:rev · geo:rev · seg:op …)"""
    x = fund_xbrl.parse(zbytes)
    rows, agg = [], {}
    for item, basis, st, en, v in x['facts']:
        if item in fund_xbrl.IS_ITEMS:
            rows.append((basis, 'is', fund_xbrl.IS_ITEMS[item][0], fund_xbrl.IS_ITEMS[item][1], st, en, v, rno, 0))
        else:               # 주석 XBRL (검증·보충용) — 같은 키는 더한다
            lab = x['labels'].get(item, item)
            k = 'total' if item == fund_xbrl.TOTAL else fund.key_of(lab)[0]
            a = agg.setdefault((basis, k, st, en), [lab, 0.0, x['nature'].index(item) if item in x['nature'] else 99])
            a[1] += v
    rows += [(b, 'nature_x', k, lab, st, en, v, rno, o) for (b, k, st, en), (lab, v, o) in agg.items()]
    # 부문: item = '분류¦이름' (같은 이름이 다른 분류 벌에 또 나와도 덮어쓰지 않게), label = 이름
    rows += [(b, f'{view}:{item}', f'{grp}¦{name}', name, st, en, v, rno, 0) for view, item, name, grp, b, st, en, v in x['segs']]
    return rows


def put(conn, code, rows):
    """rows: (basis, topic, item, label, start, end, value, rcept_no, ord)"""
    conn.executemany('INSERT OR REPLACE INTO fund_fact (code, basis, topic, item, label, start, end, value, rcept_no, ord) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [(code, *r) for r in rows])


def collect_report(conn, session, key, code, rno, name, kind, end, fy_end) -> str:
    """보고서 하나. 돌려주는 글 = 메모 ('' 이면 다 읽음)"""
    notes, rows = [], []
    try:
        xml = document(session, key, rno)
        tables = fund.note_tables(xml)
        for t in tables:
            for item, label, st, en, v, ord_ in fund.table_facts(t, end, kind, fy_end):
                rows.append((t['basis'], 'nature', item, label, st, en, v, rno, ord_))
        if not tables:
            notes.append('원문에서 성격별 비용 표를 못 찾음')
    except zipfile.BadZipFile:
        notes.append('원문 없음')
    time.sleep(DELAY)
    try:
        rows += xbrl_rows(xbrl_zip(session, key, rno, reprt_code(kind, end, fy_end)), rno)
    except (zipfile.BadZipFile, StopIteration, TypeError, KeyError):
        notes.append('XBRL 없음')
    time.sleep(DELAY)
    with conn:
        put(conn, code, rows)
        conn.execute('INSERT OR REPLACE INTO fund_report VALUES (?, ?, ?, ?, ?, ?, ?)',
                     (rno, code, name, end, kind, datetime.now().isoformat(timespec='seconds'), '; '.join(notes)))
    return '; '.join(notes)


def reparse(conn) -> int:
    """캐시한 원문으로 주석 표(topic nature)만 다시 읽는다 — 파서·규칙을 고친 뒤. 네트워크 없음"""
    import gzip
    fy = {}
    for code, end in conn.execute("SELECT code, period_end FROM fund_report WHERE kind = 'A'"):
        fy[code] = int(end[5:7])
    n = miss = 0
    with conn:
        conn.execute("DELETE FROM fund_fact WHERE topic = 'nature'")
        zs = {r[0]: XBRLS / f'{r[0]}.zip' for r in conn.execute('SELECT rcept_no FROM fund_report')}
        have_x = [rno for rno, f in zs.items() if f.exists()]
        if have_x:      # XBRL 캐시가 있는 보고서의 XBRL 유래 값도 다시 (손익·주석 XBRL·부문)
            q = ','.join('?' * len(have_x))
            conn.execute(f"DELETE FROM fund_fact WHERE topic != 'nature' AND rcept_no IN ({q})", have_x)
        for r in conn.execute('SELECT rcept_no, code, name, period_end, kind, note FROM fund_report ORDER BY rcept_no').fetchall():
            f = DOCS / f"{r['rcept_no']}.xml.gz"
            if not f.exists():
                continue
            tables = fund.note_tables(gzip.decompress(f.read_bytes()).decode('utf-8'))
            rows = [(t['basis'], 'nature', item, label, st, en, v, r['rcept_no'], o)
                    for t in tables for item, label, st, en, v, o in fund.table_facts(t, r['period_end'], r['kind'], fy.get(r['code'], 12))]
            if zs[r['rcept_no']].exists():
                try:
                    rows += xbrl_rows(zs[r['rcept_no']].read_bytes(), r['rcept_no'])
                except (zipfile.BadZipFile, StopIteration, TypeError, KeyError):
                    pass
            put(conn, r['code'], rows)
            note = [x for x in (r['note'] or '').split('; ') if x and '성격별' not in x]
            if not tables:
                note.insert(0, '원문에서 성격별 비용 표를 못 찾음')
                miss += 1
            conn.execute('UPDATE fund_report SET note = ? WHERE rcept_no = ?', ('; '.join(note), r['rcept_no']))
            n += 1
    log.info('다시 읽음: 보고서 %d건 (표 못 찾음 %d)', n, miss)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='분기 비용 구조·손익 축적 (DART 원문 주석 + XBRL)')
    ap.add_argument('--code', help='이 종목만')
    ap.add_argument('--add', nargs='+', help='대상에 더할 종목코드')
    ap.add_argument('--max', type=int, default=300, help='한 번에 받을 보고서 수')
    ap.add_argument('--reparse', action='store_true', help='캐시한 원문·XBRL 로 다시 읽기 (네트워크 없음)')
    ap.add_argument('--xbrl-cache', action='store_true', help='받은 보고서의 XBRL 압축을 캐시에 채우기')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    key = os.environ.get('DART_API_KEY', '')
    if args.xbrl_cache and key:      # 이미 받은 보고서의 XBRL 압축을 캐시에 채운다 (부문 등 새 토픽을 읽으려고) → 그다음 --reparse
        conn, s, n = connect(), requests.Session(), 0
        fy = {c: int(e[5:7]) for c, e in conn.execute("SELECT code, period_end FROM fund_report WHERE kind = 'A'")}
        for r in conn.execute('SELECT rcept_no, code, kind, period_end FROM fund_report ORDER BY rcept_no DESC').fetchall():
            if not (XBRLS / f"{r['rcept_no']}.zip").exists():
                try:
                    xbrl_zip(s, key, r['rcept_no'], reprt_code(r['kind'], r['period_end'], fy.get(r['code'], 12)))
                    n += 1
                except requests.RequestException as e:
                    log.warning('%s XBRL 실패: %s', r['rcept_no'], type(e).__name__)
        log.info('XBRL 캐시: %d건 받음', n)
        return 0
    if args.reparse:
        return reparse(connect())
    if not key:
        log.info('DART_API_KEY 없음 — 건너뜀')
        return 4
    if args.add:
        add_watch(args.add)
    codes = [args.code] if args.code else (args.add or watch())
    conn = connect()
    s = requests.Session()
    cc = corp_codes(s, key)
    have = {r[0] for r in conn.execute('SELECT rcept_no FROM fund_report')}
    done = errors = fails = 0
    try:
        for code in codes:
            if code not in cc:
                continue
            reps = reports(s, key, cc[code])
            time.sleep(DELAY)
            fy_end = next((int(e[5:7]) for _, _, k, e in reps if k == 'A'), 12)
            todo = [r for r in reps if r[0] not in have]
            for rno, name, kind, end in todo:
                if done >= args.max:
                    break
                try:
                    note = collect_report(conn, s, key, code, rno, name, kind, end, fy_end)
                    done += 1
                    fails = 0
                    if note:
                        log.info('%s %s: %s', code, name, note)
                except requests.RequestException as e:
                    errors += 1
                    fails += 1
                    log.warning('%s %s 실패: %s', code, name, type(e).__name__)
                    if fails >= 5:
                        raise
            if done >= args.max:
                log.info('한 번에 받을 수(%d)에 닿음 — 나머지는 다음 실행에서', args.max)
                break
    except requests.RequestException as e:
        log.error('DART 응답 없음, 중단: %s', e)
        return 3
    log.info('펀더 수집: 보고서 %d건, 오류 %d (대상 %d종목)', done, errors, len(codes))
    return 1 if errors > 5 else 0


if __name__ == '__main__':
    sys.exit(main())
