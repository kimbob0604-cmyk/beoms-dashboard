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
    rcept_no TEXT NOT NULL, ord INTEGER,
    PRIMARY KEY (code, basis, topic, item, start, end, rcept_no)      -- 보고서별로 다 둔다: 같은 기간이 나중 보고서에 재작성돼 다시 나온다
);
"""


def connect(path=DB):
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    pk = [r[1] for r in conn.execute("PRAGMA table_info(fund_fact)") if r[5]] if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'fund_fact'").fetchone() else None
    if pk is not None and 'rcept_no' not in pk:      # 옛 구조(기간마다 마지막 보고서 값만) → 새로 만든다. 값은 --reparse 가 캐시에서 다시 채운다
        conn.execute('DROP TABLE fund_fact')
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
    rows, agg, sagg, iagg = [], {}, {}, {}
    for item, basis, st, en, v in x['facts']:
        if item in x.get('isx', []):        # 성격별 손익계산서의 영업비용 줄 (통신·플랫폼·게임)
            lab = x['labels'].get(item, item)
            if re.search(r'매출|영업수익|수익$', lab.replace(' ', '')) and '비용' not in lab:
                continue                    # 매출 세부 줄은 비용이 아니다
            k = 'total' if item in fund_xbrl.IS_OPEX_TOTAL or fund.key_of(lab)[0] == 'total' or lab.replace(' ', '') in ('영업비용', '영업비용합계') else fund.key_of(lab)[0]
            a = iagg.setdefault((basis, k, st, en), [lab, 0.0, x['isx'].index(item)])
            a[1] += v
            continue
        if item in x['sga'] or (item == fund_xbrl.SGA_TOTAL and x['sga']):   # 판관비 내역 (성격별 분류가 없는 회사)
            lab = x['labels'].get(item, item)
            k = 'total' if item == fund_xbrl.SGA_TOTAL else fund.key_of(lab)[0]
            a = sagg.setdefault((basis, k, st, en), [lab, 0.0, x['sga'].index(item) if item in x['sga'] else 99])
            a[1] += v
        if item in fund_xbrl.IS_ITEMS:
            k, lab = fund_xbrl.IS_ITEMS[item]
            gl = (x['labels'].get(item) or '').replace(' ', '')
            if k == 'gp' and '수익' in gl and '총' not in gl:
                k, lab = 'rev', '매출액'     # 매출(영업수익)을 매출총이익 항목으로 태그한 회사 (칩스앤미디어: 원가가 없어 둘이 같다)
            rows.append((basis, 'is', k, lab, st, en, v, rno, 0))
        elif item not in x['sga']:      # 주석 XBRL (검증·보충용) — 같은 키는 더한다
            lab = x['labels'].get(item, item)
            k = 'total' if item == fund_xbrl.TOTAL else fund.key_of(lab)[0]
            a = agg.setdefault((basis, k, st, en), [lab, 0.0, x['nature'].index(item) if item in x['nature'] else 99])
            a[1] += v
    # 합계 후보가 여럿이면(성격별 비용 합계 · '영업비용' 줄) 줄의 합과 가장 가까운 것 하나만 합계로 (크래프톤: 합계 항목이 두 배로 공시됨)
    for (b, st, en) in {(b, st, en) for (b, k, st, en) in agg}:
        cands = [k for k in ('total', 'x:영업') if (b, k, st, en) in agg]
        if len(cands) < 2:
            continue
        lines = sum(v for (b2, k, s2, e2), (_, v, _) in agg.items() if (b2, s2, e2) == (b, st, en) and k not in cands)
        keep = min(cands, key=lambda k: abs(agg[(b, k, st, en)][1] - lines))
        if keep != 'total':
            agg[(b, 'total', st, en)] = agg[(b, keep, st, en)]
        del agg[(b, 'x:영업', st, en)]
    rows += [(b, 'nature_x', k, lab, st, en, v, rno, o) for (b, k, st, en), (lab, v, o) in agg.items()]
    rows += [(b, 'sga_x', k, lab, st, en, v, rno, o) for (b, k, st, en), (lab, v, o) in sagg.items()]
    rows += [(b, 'isnat_x', k, lab, st, en, v, rno, o) for (b, k, st, en), (lab, v, o) in iagg.items()]
    # 부문: item = '분류¦이름' (같은 이름이 다른 분류 벌에 또 나와도 덮어쓰지 않게), label = 이름
    rows += [(b, f'{view}:{item}', f'{grp}¦{name}', name, st, en, v, rno, 0) for view, item, name, grp, b, st, en, v in x['segs']]
    return rows


FIN_NM = {'매출액': 'rev', '수익(매출액)': 'rev', '영업수익': 'rev', '매출': 'rev', '매출원가': 'cogs', '영업원가': 'cogs',
          '매출총이익': 'gp', '판매비와관리비': 'sga', '영업이익': 'op', '영업이익(손실)': 'op', '당기순이익': 'np', '당기순이익(손실)': 'np'}


FIN_NOTE = 'XBRL 대신 재무제표 API'      # XBRL 이 열리면 다시 받는다 (main 의 todo)


def fin_rows(session, key, corp: str, end: str, kind: str, fy_end: int, rno: str) -> list:
    """XBRL 압축이 아직 안 열렸을 때(DART 014) 전체 재무제표 API(fnlttSinglAcntAll)로 손익 줄만 — 열 맞춤 기준값·OPM 용.
    분기는 thstrm = 3개월, thstrm_add = 누적. 사업보고서는 thstrm = 1년"""
    from datetime import date
    y, m = int(end[:4]), int(end[5:7])
    q_st = date(y if m > 2 else y - 1, (m - 3) % 12 + 1, 1).isoformat()
    fy_m = fy_end % 12 + 1                             # 회계연도 첫 달
    c_st = date(y if fy_m <= m else y - 1, fy_m, 1).isoformat()
    bsns = str(y if m > fy_end or fy_end == 12 else y - 1) if kind != 'A' else str(y)
    rows = []
    for fs, basis in (('CFS', 'C'), ('OFS', 'S')):
        j = session.get(f'{API}/fnlttSinglAcntAll.json', params={'crtfc_key': key, 'corp_code': corp, 'bsns_year': bsns,
                        'reprt_code': reprt_code(kind, end, fy_end), 'fs_div': fs}, timeout=60).json()
        time.sleep(DELAY)
        seen = set()
        for a in j.get('list') or []:
            if a.get('sj_div') not in ('IS', 'CIS') or a.get('rcept_no') not in (None, rno):
                continue
            k = fund_xbrl.IS_ITEMS.get(a.get('account_id'), (None,))[0] or FIN_NM.get((a.get('account_nm') or '').replace(' ', ''))
            if not k or k in seen:
                continue
            seen.add(k)
            lab = {v[0]: v[1] for v in fund_xbrl.IS_ITEMS.values()}.get(k, a.get('account_nm'))
            for col, st in (('thstrm_amount', c_st if kind == 'A' else q_st), ('thstrm_add_amount', c_st)):
                v = str(a.get(col) or '').replace(',', '').strip()
                if kind == 'A' and col == 'thstrm_add_amount':
                    continue
                try:
                    rows.append((basis, 'is', k, lab, st, end, float(v) / 1e8, rno, 0))
                except ValueError:
                    pass
    return rows


def oracle_of(xrows: list, kind: str = 'nature') -> dict:
    """XBRL 손익 줄 → {basis: {(시작, 끝): [매출원가+판관비, 매출−영업이익]}} — 주석 표의 어느 열이 어느 기간인지 맞춰 보는 기준값"""
    by = {}
    for basis, topic, item, _, st, en, v, *_ in xrows:
        if topic == 'is':
            by.setdefault(basis, {}).setdefault((st, en), {})[item] = v
    out = {}
    for b, pe in by.items():
        for k, d in pe.items():
            refs = []
            if kind == 'sga':       # 판관비 내역 표의 기준값 = 손익계산서 판관비
                if d.get('sga') is not None:
                    out.setdefault(b, {})[k] = [d['sga']]
                continue
            if d.get('cogs') is not None and d.get('sga') is not None:
                refs.append(d['cogs'] + d['sga'])
            if d.get('rev') is not None and d.get('op') is not None:
                refs.append(d['rev'] - d['op'])
            if refs:
                out.setdefault(b, {})[k] = refs
    return out


def note_rows(xml: str, end: str, kind: str, fy_end: int, oracle: dict, rno: str, sga_oracle: dict = None):
    """원문 → (fund_fact 줄, 표를 찾았나). 연결·별도마다 그 basis 의 기준값으로 열을 맞춘다 (없으면 구분 없는 'X' 기준값)"""
    rows = []
    found = False
    for topic, words, orc_all in (('nature', fund.NATURE_WORDS, oracle), ('sga', fund.SGA_WORDS, sga_oracle or {})):
        tables = fund.note_tables(xml, words)
        claimed = set()
        for t in tables:
            orc = orc_all.get(t['basis']) or orc_all.get('X')
            fs = fund.table_facts(t, end, kind, fy_end, orc, t.get('first', True))
            mine = {(st, en) for _, _, st, en, _, _ in fs}
            for item, label, st, en, v, ord_ in fs:
                if (t['basis'], st, en) not in claimed:    # 한 기간은 그 보고서에서 먼저 나온 표 하나만 — 뒤의 다른 표가 같은 기간을 또 채우면 합이 두 배가 된다
                    rows.append((t['basis'], topic, item, label, st, en, v, rno, ord_))
            claimed |= {(t['basis'], st, en) for st, en in mine}
        if topic == 'nature' and any(r[1] == 'nature' for r in rows):
            return rows, True           # 성격별 분류가 있으면 판관비 내역은 읽지 않는다
        found = found or bool(tables)
    return rows, found


def put(conn, code, rows):
    """rows: (basis, topic, item, label, start, end, value, rcept_no, ord)"""
    conn.executemany('INSERT OR REPLACE INTO fund_fact (code, basis, topic, item, label, start, end, value, rcept_no, ord) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [(code, *r) for r in rows])


def collect_report(conn, session, key, code, rno, name, kind, end, fy_end, corp: str = None) -> str:
    """보고서 하나. 돌려주는 글 = 메모 ('' 이면 다 읽음). XBRL 손익을 먼저 읽어 주석 표의 기준값으로 쓴다"""
    notes, rows, xr = [], [], []
    try:
        xr = xbrl_rows(xbrl_zip(session, key, rno, reprt_code(kind, end, fy_end)), rno)
    except (zipfile.BadZipFile, StopIteration, TypeError, KeyError):
        xr = fin_rows(session, key, corp, end, kind, fy_end, rno) if corp else []
        notes.append(FIN_NOTE if xr else 'XBRL 없음')
    nx = {b: len({r[2] for r in xr if r[0] == b and r[1] == 'nature_x' and r[5] == end and r[2] != 'total'}) for b in ('C', 'S')}
    has_c = any(r[0] == 'C' and r[1] == 'is' for r in xr)
    if (nx['C'] >= 3 if has_c else nx['S'] >= 3):        # 그 기간 주석 XBRL 에 (연결이 있으면 연결) 비용 줄이 3개 이상일 때만 원문 생략
        rows = xr                   # 주석 XBRL 에 이번 기간의 성격별 비용이 있다 — 큰 원문(수 MB)은 받지 않는다
        with conn:
            put(conn, code, rows)
            conn.execute('INSERT OR REPLACE INTO fund_report VALUES (?, ?, ?, ?, ?, ?, ?)',
                         (rno, code, name, end, kind, datetime.now().isoformat(timespec='seconds'), '원문 생략 (주석 XBRL)'))
        return ''
    try:
        nr, found = note_rows(document(session, key, rno), end, kind, fy_end, oracle_of(xr), rno, oracle_of(xr, 'sga'))
        rows += nr
        if not found:
            notes.insert(0, '원문에서 성격별 비용 표를 못 찾음')
    except zipfile.BadZipFile:
        notes.insert(0, '원문 없음')
    time.sleep(DELAY)
    if ('원문 없음' in notes or 'XBRL 없음' in notes) and (datetime.now() - datetime.strptime(rno[:8], '%Y%m%d')).days < 10:
        return 'retry'          # 막 접수된 보고서는 DART 가 원문 파일을 며칠 늦게 연다(상태 014) — 기록하지 않고 다음 실행에서 다시
    rows += xr
    with conn:
        put(conn, code, rows)
        conn.execute('INSERT OR REPLACE INTO fund_report VALUES (?, ?, ?, ?, ?, ?, ?)',
                     (rno, code, name, end, kind, datetime.now().isoformat(timespec='seconds'), '; '.join(notes)))
    return '; '.join(notes)


def reparse(conn, codes=None) -> int:
    """캐시한 원문으로 주석 표(topic nature)만 다시 읽는다 — 파서·규칙을 고친 뒤. 네트워크 없음"""
    import gzip
    fy = {}
    for code, end in conn.execute("SELECT code, period_end FROM fund_report WHERE kind = 'A'"):
        fy[code] = int(end[5:7])
    n = miss = 0
    with conn:
        cq = f" AND code IN ({','.join('?' * len(codes))})" if codes else ''
        conn.execute(f"DELETE FROM fund_fact WHERE topic IN ('nature', 'sga'){cq}", list(codes or []))      # 원문 유래 값은 전부 다시
        zs = {r[0]: XBRLS / f'{r[0]}.zip' for r in conn.execute('SELECT rcept_no FROM fund_report' + (
            f" WHERE code IN ({','.join('?' * len(codes))})" if codes else ''), list(codes or []))}
        have_x = [rno for rno, f in zs.items() if f.exists()]
        if have_x:      # XBRL 캐시가 있는 보고서의 XBRL 유래 값도 다시 (손익·주석 XBRL·부문)
            q = ','.join('?' * len(have_x))
            conn.execute(f"DELETE FROM fund_fact WHERE topic != 'nature' AND rcept_no IN ({q})", have_x)
        for r in conn.execute('SELECT rcept_no, code, name, period_end, kind, note FROM fund_report ORDER BY rcept_no').fetchall():
            if codes and r['code'] not in codes:
                continue
            f = DOCS / f"{r['rcept_no']}.xml.gz"
            if not f.exists() and not zs[r['rcept_no']].exists():
                continue
            xr = []
            if zs[r['rcept_no']].exists():
                try:
                    xr = xbrl_rows(zs[r['rcept_no']].read_bytes(), r['rcept_no'])
                except (zipfile.BadZipFile, StopIteration, TypeError, KeyError):
                    pass
            if f.exists():      # 원문을 받지 않은 보고서(주석 XBRL 로 대신)는 XBRL 만 다시
                rows, tables = note_rows(gzip.decompress(f.read_bytes()).decode('utf-8'), r['period_end'], r['kind'], fy.get(r['code'], 12),
                                         oracle_of(xr), r['rcept_no'], oracle_of(xr, 'sga'))
            else:
                rows, tables = [], True
            rows += xr
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
    ap.add_argument('--shard', help='i/n — 대상의 i 번째 조각만 (여러 개를 나란히 돌려 빨리 받는다)')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    import fcntl
    (ROOT / 'logs').mkdir(exist_ok=True)
    shard = tuple(int(x) for x in args.shard.split('/')) if args.shard else None
    lock = open(ROOT / 'logs' / (f'collect_fund.{shard[0]}.lock' if shard else 'collect_fund.lock'), 'w')
    try:                    # 정기 실행과 손으로 돌린 수집이 겹치면 같은 보고서를 두 번 받는다
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info('다른 펀더 수집이 도는 중 — 건너뜀')
        return 0
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
        return reparse(connect(), [args.code] if args.code else (args.add or None))
    if not key:
        log.info('DART_API_KEY 없음 — 건너뜀')
        return 4
    if args.add:
        add_watch(args.add)
    codes = [args.code] if args.code else (args.add or watch())
    if shard:
        codes = [c for k, c in enumerate(codes) if k % shard[1] == shard[0]]
    conn = connect()
    s = requests.Session()
    cc = corp_codes(s, key)
    have = {r[0] for r in conn.execute('SELECT rcept_no FROM fund_report')}
    redo = {r[0] for r in conn.execute('SELECT rcept_no FROM fund_report WHERE note LIKE ?', (f'%{FIN_NOTE}%',))
            if (datetime.now() - datetime.strptime(r[0][:8], '%Y%m%d')).days < 45}   # 재무제표 API로 메운 보고서 — XBRL 이 열릴 때까지 다시
    done = errors = fails = 0
    try:
        for code in codes:
            if code not in cc:
                continue
            reps = reports(s, key, cc[code])
            time.sleep(DELAY)
            fy_end = next((int(e[5:7]) for _, _, k, e in reps if k == 'A'), 12)
            todo = [r for r in reps if r[0] not in have or (r[0] in redo and not (XBRLS / f'{r[0]}.zip').exists())]
            for rno, name, kind, end in todo:
                if done >= args.max:
                    break
                try:
                    note = collect_report(conn, s, key, code, rno, name, kind, end, fy_end, cc[code])
                    done += 1
                    fails = 0
                    if note == 'retry':
                        log.info('%s %s: 원문이 아직 안 열림 — 다음 실행에서 다시', code, name)
                    elif note:
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
        log.error('DART 응답 없음, 중단: %s', type(e).__name__)      # 예외 글에는 키가 든 URL 이 있다 — 이름만
        return 3
    log.info('펀더 수집: 보고서 %d건, 오류 %d (대상 %d종목)', done, errors, len(codes))
    return 1 if errors > 5 else 0


if __name__ == '__main__':
    sys.exit(main())
