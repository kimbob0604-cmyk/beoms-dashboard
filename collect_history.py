"""
장기 백테스트용 과거 데이터 수집 → db/history.db

화면용 DB(dashboard.db)와 파일을 나눠서, 몇 시간짜리 백필이 10분마다 도는 실시간 수집과 잠금이 겹치지 않게 한다.

  python3 collect_history.py krx      # KRX 일별 전 종목 (2010-01-04 ~, 상장폐지 종목 포함, 그 시점 시총)
  python3 collect_history.py naver    # 2010년 이전 수정주가 일봉 (네이버, 종목당 1회)
  python3 collect_history.py flow     # 외국인·기관 순매수, 외국인 지분율 (네이버, 2005 ~, 상장폐지 종목 포함)
  python3 collect_history.py fin      # 분기 매출·영업이익 (DART, 2015 사업보고서 ~)
  python3 collect_history.py index    # 코스피·코스닥 지수 (2005 ~)
  python3 collect_history.py sync     # 최근 날짜를 화면용 DB에서 복사 (매일)

KRX Open API 는 2010-01-04 이전 날짜를 주지 않는다. 그 전은 네이버 수정주가를 쓰는데,
종목 목록을 KRX 2010년 이후 상장 이력에서 가져오므로 2010년 전에 상장폐지된 종목은 빠진다.
"""

import argparse
import logging
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import requests

import config
from collectors import krx, naver

log = logging.getLogger('history')
ROOT = Path(__file__).resolve().parent
HIST = ROOT / 'db' / 'history.db'
KRX_FIRST = date(2010, 1, 4)
PRE_START = '20050101'          # 2006-11 부터 보려면 52주 지표용으로 1년 넘게 앞이 필요
SISE = 'https://api.finance.naver.com/siseJson.naver'
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

SCHEMA = """
CREATE TABLE IF NOT EXISTS hp (
    date TEXT NOT NULL, code TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    chg REAL,      -- 기준가 대비 등락률 % (권리락·분할 반영)
    mcap REAL,     -- 그날 시가총액, 억원
    tv REAL,       -- 거래대금, 억원
    PRIMARY KEY (date, code)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS hday (date TEXT PRIMARY KEY, n INTEGER);          -- 조회한 날 (휴장이면 0)
CREATE TABLE IF NOT EXISTS hname (code TEXT PRIMARY KEY, name TEXT, market TEXT, first TEXT, last TEXT);
CREATE TABLE IF NOT EXISTS nv (                                               -- 네이버 수정주가 (2010년 이전)
    code TEXT NOT NULL, date TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL, volume REAL, fr REAL,
    PRIMARY KEY (code, date)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fl (                                               -- 수급: 순매수 수량, 그날 종가(수정 전), 외국인 지분율
    code TEXT NOT NULL, date TEXT NOT NULL, frgn REAL, org REAL, close REAL, fr REAL,
    PRIMARY KEY (code, date)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS hidx (code TEXT NOT NULL, date TEXT NOT NULL, close REAL, PRIMARY KEY (code, date)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fin (                                              -- DART 주요 계정 (분기·반기·사업보고서)
    code TEXT NOT NULL, year INTEGER NOT NULL, reprt TEXT NOT NULL, fs TEXT NOT NULL, acc TEXT NOT NULL,
    cur REAL, cur_add REAL, prev REAL, prev_add REAL, rcept TEXT,
    PRIMARY KEY (code, year, reprt, fs, acc)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS hdone (kind TEXT NOT NULL, code TEXT NOT NULL, n INTEGER, at TEXT, PRIMARY KEY (kind, code));
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(HIST, timeout=60)
    conn.executescript(SCHEMA)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


HP_SQL = """INSERT OR REPLACE INTO hp (date, code, open, high, low, close, volume, chg, mcap, tv)
            VALUES (:date, :code, :open, :high, :low, :close, :volume, :change_pct, :mcap, :trd_val)"""
NAME_SQL = """INSERT INTO hname (code, name, market, first, last) VALUES (:code, :name, :market, :date, :date)
              ON CONFLICT(code) DO UPDATE SET
                name = CASE WHEN excluded.last >= hname.last THEN excluded.name ELSE hname.name END,
                market = CASE WHEN excluded.last >= hname.last THEN excluded.market ELSE hname.market END,
                first = MIN(hname.first, excluded.first), last = MAX(hname.last, excluded.last)"""


def save_day(conn, d: str, rows):
    with conn:
        if rows:
            conn.executemany(HP_SQL, rows)
            conn.executemany(NAME_SQL, rows)
        conn.execute('INSERT OR REPLACE INTO hday (date, n) VALUES (?, ?)', (d, len(rows)))


def collect_krx(conn, limit: int = 0, asc: bool = False):
    """최근 → 과거 순서 (asc 면 2010-01-04 부터 위로 — 두 개를 같이 돌리면 가운데서 만난다). 이미 조회한 날은 건너뛴다."""
    if not config.KRX_API_KEY:
        sys.exit('KRX_API_KEY 없음 (.env 확인)')
    session = requests.Session()
    step = timedelta(days=1 if asc else -1)
    d, fails, calls = (KRX_FIRST if asc else date.today() - timedelta(days=1)), 0, 0
    while KRX_FIRST <= d < date.today():
        iso = d.isoformat()
        if d.weekday() < 5 and not conn.execute('SELECT 1 FROM hday WHERE date = ?', (iso,)).fetchone():
            try:
                rows = krx.fetch_daily(session, config.KRX_API_KEY, d.strftime('%Y%m%d'), 'KOSPI')
                calls += 1
                if rows:        # 휴장일이면 코스닥은 묻지 않는다 (호출 한도 아끼기)
                    rows += krx.fetch_daily(session, config.KRX_API_KEY, d.strftime('%Y%m%d'), 'KOSDAQ')
                    calls += 1
                if rows or (date.today() - d).days > 3:     # 최근 며칠은 아직 안 열린 것일 수 있어 휴장으로 적지 않는다
                    save_day(conn, iso, rows)
                fails = 0
                if calls % 100 < 2:
                    log.info('%s: %d종목 (호출 %d)', iso, len(rows), calls)
            except (requests.RequestException, ValueError) as e:
                fails += 1
                log.warning('%s: %s', iso, type(e).__name__)
                if fails >= 5:
                    sys.exit(f'연속 5번 실패 — 중단 ({iso}, 호출 {calls}). 호출 한도일 수 있음. 다시 실행하면 이어서 받는다.')
                time.sleep(3)
                continue          # 같은 날 다시
            if limit and calls >= limit:
                break
            time.sleep(0.1)
        d += step
    log.info('KRX 끝: 호출 %d', calls)


SISE_ROW = re.compile(r'\["(\d{8})",\s*([^\]]*)\]')


def parse_sise(text: str):
    out = []
    for d, rest in SISE_ROW.findall(text):
        v = [x.strip() for x in rest.split(',')]
        num = lambda s: float(s) if s not in ('', 'null', 'None') else None
        try:
            o, h, l, c, vol = (num(x) for x in v[:5])
        except ValueError:
            continue
        fr = None
        if len(v) > 5:
            try:
                fr = num(v[5])
            except ValueError:
                fr = None
        if c:
            out.append((f'{d[:4]}-{d[4:6]}-{d[6:]}', o, h, l, c, vol, fr))
    return out


def fetch_sise(session, code: str, start: str, end: str):
    r = session.get(SISE, params={'symbol': code, 'requestType': 1, 'startTime': start, 'endTime': end,
                                  'timeframe': 'day'}, timeout=30)
    r.raise_for_status()
    return parse_sise(r.text)


def threaded(codes, work, save, workers: int, label: str):
    """work(session, code) → rows 를 여러 스레드로, save(code, rows) 는 이 스레드에서 (sqlite 연결 하나)"""
    def job(code):
        s = requests.Session()
        s.headers.update(UA)
        for attempt in range(3):
            try:
                return code, work(s, code), None
            except (requests.RequestException, ValueError, KeyError) as e:
                err = e
                time.sleep(1 + attempt * 2)
        return code, None, err

    n = bad = 0
    with ThreadPoolExecutor(workers) as ex:
        for code, rows, err in ex.map(job, codes):
            n += 1
            if err is not None:
                bad += 1
            else:
                save(code, rows)
            if not n % 100:
                log.info('%s %d/%d (실패 %d)', label, n, len(codes), bad)
    log.info('%s 끝: %d종목, 실패 %d', label, n, bad)


def collect_naver(conn, workers: int = 3):
    """2010-01-04 에 이미 상장돼 있던 종목의 그 전 일봉 (수정주가)"""
    first = conn.execute('SELECT MIN(date) FROM hday WHERE n > 0').fetchone()[0]
    if not first or first > '2010-01-10':
        sys.exit(f'KRX 수집이 2010-01-04 까지 끝난 뒤 실행 (지금 {first})')
    done = {r[0] for r in conn.execute("SELECT code FROM hdone WHERE kind = 'nv'")}
    codes = [r[0] for r in conn.execute('SELECT code FROM hname WHERE first <= ? ORDER BY code', ('2010-01-10',))
             if r[0] not in done]

    def save(code, rows):
        with conn:
            conn.executemany('INSERT OR REPLACE INTO nv VALUES (?,?,?,?,?,?,?,?)', [(code, *r) for r in rows])
            conn.execute("INSERT OR REPLACE INTO hdone VALUES ('nv', ?, ?, date('now'))", (code, len(rows)))

    threaded(codes, lambda s, c: fetch_sise(s, c, PRE_START, '20100115'), save, workers, '수정주가')


def collect_flow(conn, workers: int = 4, main_codes: bool = False, recent: int = 0):
    """종목마다 200거래일씩 과거로 넘겨 2005년까지. main_codes: KRX 수집 전이라도 화면용 DB의 현재 종목부터.
    recent: 지금 상장 종목의 최근 N거래일만 다시 (주간 갱신)"""
    done = {r[0] for r in conn.execute("SELECT code FROM hdone WHERE kind = 'fl'")}
    if main_codes:
        import db
        src = db.connect()
        codes = [r[0] for r in src.execute(
            'SELECT code FROM price_daily WHERE date = (SELECT MAX(date) FROM price_daily) ORDER BY mcap DESC')]
        src.close()
    elif recent:
        last = conn.execute('SELECT MAX(date) FROM hday WHERE n > 0').fetchone()[0]
        codes = [r[0] for r in conn.execute('SELECT code FROM hname WHERE last = ? ORDER BY code', (last,))]
        done = set()
    else:
        codes = [r[0] for r in conn.execute('SELECT code FROM hname ORDER BY last DESC, code')]
    codes = [c for c in codes if c not in done and c[-1] == '0']     # 보통주만 (우선주는 수급 조건에 쓰지 않음)

    def save(code, rows):
        with conn:
            conn.executemany('INSERT OR REPLACE INTO fl VALUES (?,?,?,?,?,?)',
                             [(code, r['date'], r['frgn'], r['org'], r['close'], r['frgn_ratio']) for r in rows])
            if not recent:
                conn.execute("INSERT OR REPLACE INTO hdone VALUES ('fl', ?, ?, date('now'))", (code, len(rows)))

    if recent:
        work = lambda s, c: naver.fetch_flow(s, c, size=min(recent, 200), timeout=20, pages=1)
    else:
        work = lambda s, c: naver.fetch_flow(s, c, size=200, timeout=20, pages=40)
    threaded(codes, work, save, workers, '수급')


DART = 'https://opendart.fss.or.kr/api'
FIN_ACC = {'매출액': 'sales', '영업이익': 'op', '당기순이익(손실)': 'ni', '당기순이익': 'ni'}
REPRTS = ('11013', '11012', '11014', '11011')        # 1분기, 반기, 3분기, 사업보고서


def corp_codes(session, key):
    """종목코드 → DART 고유번호 (상장폐지 종목도 일부 포함)"""
    import io
    import zipfile
    r = session.get(f'{DART}/corpCode.xml', params={'crtfc_key': key}, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    xml = z.read(z.namelist()[0]).decode('utf-8')
    out = {}
    for block in xml.split('<list>')[1:]:
        cc = re.search(r'<corp_code>(\d+)</corp_code>', block)
        st = re.search(r'<stock_code>\s*(\w+)\s*</stock_code>', block)
        if cc and st:
            out[st.group(1)] = cc.group(1)
    return out


def collect_fin(conn, first_year: int = 2015):
    """분기별 매출·영업이익·순이익 (fnlttMultiAcnt: 회사 100개씩). 2015 사업보고서부터 제공된다."""
    import os
    key = os.environ.get('DART_API_KEY')
    if not key:
        sys.exit('DART_API_KEY 없음 (.env 확인)')
    s = requests.Session()
    cm = corp_codes(s, key)
    codes = [r[0] for r in conn.execute('SELECT code FROM hname ORDER BY code') if r[0][-1] == '0' and r[0] in cm]
    log.info('재무: 종목 %d개', len(codes))
    done = {r[0] for r in conn.execute("SELECT code FROM hdone WHERE kind = 'fin'")}
    num = lambda v: float(v.replace(',', '')) if v and v.strip() not in ('', '-') else None
    this = date.today().year
    for year in range(first_year, this + 1):
        for rp in REPRTS:
            tag = f'{year}-{rp}'
            if tag in done and year < this - 1:        # 최근 2년은 다시 받는다 (새 보고서·정정)
                continue
            n = 0
            for i in range(0, len(codes), 100):
                batch = codes[i:i + 100]
                for attempt in range(3):
                    try:
                        r = s.get(f'{DART}/fnlttMultiAcnt.json', params={
                            'crtfc_key': key, 'corp_code': ','.join(cm[c] for c in batch),
                            'bsns_year': str(year), 'reprt_code': rp}, timeout=40)
                        r.raise_for_status()
                        j = r.json()
                        break
                    except (requests.RequestException, ValueError) as e:
                        j = None
                        log.warning('%s %d: %s', tag, i, type(e).__name__)
                        time.sleep(3)
                if not j or j.get('status') not in ('000', '013'):
                    if j and j.get('status') == '020':
                        sys.exit('DART 호출 한도 초과 — 내일 다시 실행하면 이어서 받는다')
                    continue
                rows = []
                for x in j.get('list') or []:
                    acc = FIN_ACC.get(x.get('account_nm'))
                    if not acc or not x.get('stock_code'):
                        continue
                    try:
                        rows.append((x['stock_code'], year, rp, x.get('fs_div') or '', acc, num(x.get('thstrm_amount')),
                                     num(x.get('thstrm_add_amount')), num(x.get('frmtrm_amount')),
                                     num(x.get('frmtrm_add_amount')), x.get('rcept_no')))
                    except ValueError:
                        continue
                with conn:
                    conn.executemany('INSERT OR REPLACE INTO fin VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
                n += len(rows)
                time.sleep(0.15)
            with conn:
                conn.execute("INSERT OR REPLACE INTO hdone VALUES ('fin', ?, ?, date('now'))", (tag, n))
            log.info('재무 %s: %d행', tag, n)


def collect_index(conn):
    """코스피·코스닥 지수 일봉 (2005 ~)"""
    s = requests.Session()
    s.headers.update(UA)
    for code in ('KOSPI', 'KOSDAQ'):
        rows = fetch_sise(s, code, PRE_START, date.today().strftime('%Y%m%d'))
        with conn:
            conn.executemany('INSERT OR REPLACE INTO hidx VALUES (?,?,?)', [(code, r[0], r[4]) for r in rows])
        log.info('%s 지수 %d일 (%s ~ %s)', code, len(rows), rows[0][0], rows[-1][0])


def sync(conn):
    """화면용 DB에 있는 최근 날짜를 복사 (KRX 를 다시 부르지 않는다). 오늘 날짜는 장 마감 직후 잠정치일 수 있어 어제까지만."""
    import db
    src = db.connect()
    # 마지막으로 '확정된' 날: 시가가 채워진 날. KRX 공개 전 임시 종가(시가 없음)로 복사된 날은 다시 복사해 확정값으로 덮는다
    # (2026-11-09 가 임시 종가로 들어가 2,243종목의 종가가 KRX 확정값과 달랐다 — 2026-11-10 발견)
    last = '2010-01-01'
    for (d,) in conn.execute('SELECT date FROM hday WHERE n > 0 ORDER BY date DESC LIMIT 10'):
        if conn.execute('SELECT 1 FROM hp WHERE date = ? AND open IS NOT NULL LIMIT 1', (d,)).fetchone():
            last = d
            break
    days = [r[0] for r in src.execute(
        'SELECT DISTINCT p.date FROM price_daily p WHERE p.date > ? AND p.date < ? AND EXISTS '
        '(SELECT 1 FROM ohlc_daily o WHERE o.date = p.date AND o.chg IS NOT NULL AND o.open IS NOT NULL) ORDER BY 1',
        (last, date.today().isoformat()))]
    for d in days:
        rows = [dict(zip(('date', 'code', 'name', 'market', 'close', 'change_pct', 'mcap', 'trd_val',
                          'open', 'high', 'low', 'volume'), r)) for r in src.execute(
            """SELECT p.date, p.code, p.name, p.market, p.close, COALESCE(o.chg, p.change_pct), p.mcap, p.trd_val,
                      o.open, o.high, o.low, o.volume
               FROM price_daily p LEFT JOIN ohlc_daily o ON o.date = p.date AND o.code = p.code
               WHERE p.date = ?""", (d,))]
        save_day(conn, d, rows)
        log.info('%s: 복사 %d종목', d, len(rows))
    src.close()


def main():
    ap = argparse.ArgumentParser(description='장기 백테스트용 과거 데이터')
    ap.add_argument('what', choices=['krx', 'naver', 'flow', 'index', 'fin', 'sync'])
    ap.add_argument('--limit', type=int, default=0, help='krx: 이번 실행의 최대 호출 수')
    ap.add_argument('--workers', type=int, default=0)
    ap.add_argument('--recent', type=int, default=0, help='flow: 지금 상장 종목의 최근 N거래일만')
    ap.add_argument('--asc', action='store_true', help='krx: 2010-01-04 부터 위로')
    ap.add_argument('--main-codes', action='store_true', help='flow: 화면용 DB의 현재 종목부터')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    conn = connect()
    if args.what == 'krx':
        collect_krx(conn, args.limit, args.asc)
    elif args.what == 'naver':
        collect_naver(conn, args.workers or 3)
    elif args.what == 'flow':
        collect_flow(conn, args.workers or 4, args.main_codes, args.recent)
    elif args.what == 'fin':
        collect_fin(conn)
    elif args.what == 'index':
        collect_index(conn)
    else:
        sync(conn)
        collect_index(conn)


if __name__ == '__main__':
    main()
