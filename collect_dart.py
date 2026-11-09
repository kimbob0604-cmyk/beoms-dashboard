"""
DART 공시 수집 → dart_filing, 분기 컨센서스 스냅샷 → cns_quarter

  python3 collect_dart.py              # 오늘·어제 공시 (처음 보는 공시만 원문을 받는다)
  python3 collect_dart.py --days 14    # 최근 14일 백필
  python3 collect_dart.py cns          # 컨센서스 있는 종목의 분기 추정치 스냅샷 (하루 한 번이면 충분)
  python3 collect_dart.py events --days 370   # 이벤트 스터디용 공시 목록만 백필 (원문 없이, 날마다 목록 몇 쪽)
  python3 collect_dart.py times --days 370    # KIND 공시 시각 백필 (종류별 검색) → dart_event.tm
  python3 collect_dart.py times [--latest]    # 오늘 KIND 공시 시각 (장중엔 --latest: 최신 100건만)

잠정실적이 들어오면 그 종목의 분기 추정치를 바로 한 번 더 받아 둔다(네이버가 발표 뒤에도 하루쯤 추정 열을 남겨 둔다).
종료 코드: 0 정상, 1 오류가 많음, 3 DART 응답 없음
"""

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests

import config  # noqa: F401  (.env 로딩)
import db
from collectors import dart, kind

log = logging.getLogger('collect_dart')
DELAY = 0.15
MAX_FAILS = 8
MARKET = {'Y': 'KOSPI', 'K': 'KOSDAQ'}
EXIT_UNREACHABLE = 3


# 시각을 붙일 공시 종류의 KIND 검색어 (제목 일부, 띄어쓰기는 무시됨)
KIND_TERMS = ['영업(잠정)실적', '단일판매', '주식소각', '자기주식취득', '사채권발행결정', '유상증자결정', '무상증자결정',
              '최대주주변경', '타법인주식', '배당결정', '투자판단', '기업설명회', '결산실적공시']


def save_kind(conn, rows):
    with conn:
        conn.executemany('INSERT OR REPLACE INTO kind_disc (acpt, dt, code, name, title) VALUES (?, ?, ?, ?, ?)',
                         [(r['acpt'], r['dt'], r['code'], r['name'], r['title']) for r in rows])


def match_times(conn, since: str) -> int:
    """같은 종목·날짜·종류의 DART 이벤트와 KIND 공시를 접수 순서대로 짝지어 dart_event.tm 에 시각을 넣는다"""
    kind_rows = defaultdict(list)
    for r in conn.execute('SELECT * FROM kind_disc WHERE dt >= ? ORDER BY dt, acpt', (since,)):
        k = dart.kind_of(r['title'])
        if k:
            kind_rows[(r['code'], r['dt'][:10], k)].append(r['dt'][11:16])
    ev = defaultdict(list)
    for r in conn.execute('SELECT rcept_no, code, date, kind FROM dart_event WHERE date >= ? ORDER BY rcept_no', (since[:10],)):
        ev[(r['code'], r['date'], r['kind'])].append(r['rcept_no'])
    upd = []
    for key, nos in ev.items():
        times = kind_rows.get(key)
        if not times:
            continue
        for i, no in enumerate(nos):   # KIND 쪽이 모자라면 마지막 시각을 쓴다 (정정 공시 등)
            upd.append((times[min(i, len(times) - 1)], no))
    with conn:
        conn.executemany('UPDATE dart_event SET tm = ? WHERE rcept_no = ?', upd)
    return len(upd)


def collect_times(conn, session, days: int = 0, latest_only: bool = False) -> int:
    """KIND 공시 시각. days>0: 그 기간을 종류별 검색으로 (백필), 아니면 오늘 전체 목록
    (latest_only 면 최신 100건 한 쪽만 — 장중 10분 갱신용)"""
    today = date.today()
    since = (today - timedelta(days=days)).isoformat()
    n = 0
    try:
        if days:
            for term in KIND_TERMS:
                page = 1
                while True:
                    res = kind.search(session, term, since, today.isoformat(), page)
                    save_kind(conn, res['rows'])
                    n += len(res['rows'])
                    if not res['rows'] or page * 100 >= res['total']:
                        break
                    page += 1
                    time.sleep(0.4)
                time.sleep(0.4)
        else:
            page = 1
            while True:
                res = kind.search(session, '', today.isoformat(), today.isoformat(), page)
                save_kind(conn, res['rows'])
                n += len(res['rows'])
                if latest_only or not res['rows'] or page * 100 >= res['total']:
                    break
                page += 1
                time.sleep(0.4)
    except requests.RequestException as e:
        log.warning('KIND 시각 실패: %s', e)
        return 1
    m = match_times(conn, since if days else today.isoformat())
    log.info('KIND 공시 시각 %d건 받음 · 이벤트 %d건에 시각', n, m)
    return 0


def key() -> str:
    import os
    k = os.environ.get('DART_API_KEY', '')
    if not k:
        sys.exit('DART_API_KEY 없음 (.env 확인)')
    return k


def safe(e) -> str:
    """오류 메시지 속 요청 주소에 들어간 API 키를 가린다 (로그에 평문으로 남지 않게)"""
    import os
    import re
    msg = str(e)
    k = os.environ.get('DART_API_KEY')
    if k:
        msg = msg.replace(k, '***')
    return re.sub(r'crtfc_key=[0-9a-fA-F]+', 'crtfc_key=***', msg)


def now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def save_cns(conn, code, cns: dict, as_of: str):
    with conn:
        conn.executemany(
            'INSERT OR REPLACE INTO cns_quarter (as_of, code, period, sales, op, np, cnp) VALUES (?, ?, ?, ?, ?, ?, ?)',
            [(as_of, code, p, v.get('sales'), v.get('op'), v.get('np'), v.get('cnp')) for p, v in cns.items()])


def save_events(conn, rows, d: date):
    """목록에서 종류가 정해지는 공시를 dart_event 에 (이벤트 스터디용, 원문 없이)"""
    ev = [(r['rcept_no'], d.isoformat(), r['stock_code'], r['corp_name'], MARKET[r['corp_cls']], kind,
           ' '.join(r['report_nm'].split()))
          for r in rows if (kind := dart.kind_of(r['report_nm']))]
    with conn:
        conn.executemany('INSERT OR REPLACE INTO dart_event VALUES (?, ?, ?, ?, ?, ?, ?)', ev)
    return len(ev)


def collect_events(conn, session, k: str, days: int) -> int:
    """과거 N일 공시 목록만 받아 dart_event 를 채운다 (이미 있는 날은 건너뜀)"""
    have = {r[0] for r in conn.execute('SELECT DISTINCT date FROM dart_event')}
    n = 0
    for i in range(days, 0, -1):
        d = date.today() - timedelta(days=i)
        if d.weekday() >= 5 or d.isoformat() in have:
            continue
        n += save_events(conn, dart.fetch_list(session, k, d.strftime('%Y%m%d')), d)
        time.sleep(DELAY)
        if i % 30 == 0:
            log.info('%s까지 이벤트 %d건', d, n)
    log.info('이벤트 목록 %d건 저장', n)
    return 0


def collect_day(conn, session, k: str, d: date) -> int:
    rows = dart.fetch_list(session, k, d.strftime('%Y%m%d'))
    save_events(conn, rows, d)
    have = {r[0] for r in conn.execute('SELECT rcept_no FROM dart_filing WHERE date = ? AND data IS NOT NULL',
                                       (d.isoformat(),))}
    errors, fails, new = 0, 0, 0
    for r in rows:
        kind = dart.kind_of(r['report_nm'])
        if not kind or r['rcept_no'] in have:
            continue
        data = None
        try:
            data = dart.parse(kind, dart.fetch_cells(session, k, r['rcept_no']))
            fails = 0
        except requests.RequestException as e:
            errors += 1
            fails += 1
            log.warning('%s %s 원문 실패: %s', r['corp_name'], r['report_nm'].strip(), safe(e))
            if fails >= MAX_FAILS:
                raise
        except Exception as e:   # 양식이 달라 못 읽은 공시는 제목만 남긴다
            errors += 1
            log.warning('%s %s 파싱 실패: %s', r['corp_name'], r['report_nm'].strip(), safe(e))
            data = {}
        if kind == 'earn':
            data['basis'] = '연결' if '연결' in r['report_nm'] else '별도'
            try:
                save_cns(conn, r['stock_code'], dart.fetch_quarter_cns(session, r['stock_code']), date.today().isoformat())
            except Exception as e:
                log.warning('%s 분기 컨센서스 실패: %s', r['corp_name'], safe(e))
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO dart_filing (rcept_no, date, code, name, market, kind, title, fixed, data, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r['rcept_no'], d.isoformat(), r['stock_code'], r['corp_name'], MARKET[r['corp_cls']], kind,
                 ' '.join(r['report_nm'].split()), int('정정' in r['report_nm']),
                 json.dumps(data, ensure_ascii=False) if data is not None else None, now()))
        new += 1
        time.sleep(DELAY)
    log.info('%s: 목록 %d건 · 새로 읽은 공시 %d건', d, len(rows), new)
    return errors


def covered_codes(conn) -> list:
    """최근 컨센서스 스냅샷에 추정치가 있는 종목"""
    as_of = conn.execute("SELECT MAX(as_of) FROM consensus_annual").fetchone()[0]
    return [r[0] for r in conn.execute('SELECT DISTINCT code FROM consensus_annual WHERE as_of = ? AND is_estimate = 1',
                                       (as_of,))] if as_of else []


def collect_cns(conn, session) -> int:
    today = date.today().isoformat()
    done = {r[0] for r in conn.execute('SELECT DISTINCT code FROM cns_quarter WHERE as_of = ?', (today,))}
    codes = [c for c in covered_codes(conn) if c not in done]
    errors, fails = 0, 0
    for c in codes:
        try:
            save_cns(conn, c, dart.fetch_quarter_cns(session, c), today)
            fails = 0
        except Exception as e:
            errors += 1
            fails += 1
            if fails >= MAX_FAILS:
                raise requests.RequestException(f'연속 {fails}회 실패: {e}')
        time.sleep(0.1)
    log.info('분기 컨센서스 %d종목 (이미 받은 %d종목 건너뜀)', len(codes), len(done))
    return errors


def main():
    ap = argparse.ArgumentParser(description='DART 공시 수집')
    ap.add_argument('what', nargs='?', default='filings', choices=['filings', 'cns', 'events', 'times'])
    ap.add_argument('--latest', action='store_true', help='times: 오늘 최신 100건만 (장중 갱신용)')
    ap.add_argument('--days', type=int, default=1, help='오늘부터 N일 전까지')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    conn = db.connect()
    session = requests.Session()
    errors = 0
    try:
        if args.what == 'cns':
            errors += collect_cns(conn, session)
        elif args.what == 'events':
            errors += collect_events(conn, session, key(), args.days)
        elif args.what == 'times':
            errors += collect_times(conn, session, args.days if args.days > 1 else 0, latest_only=args.latest)
        else:
            k = key()
            for i in range(args.days, -1, -1):
                d = date.today() - timedelta(days=i)
                if d.weekday() < 5:
                    errors += collect_day(conn, session, k, d)
    except requests.RequestException as e:
        log.error('응답 없음, 중단: %s', safe(e))
        sys.exit(EXIT_UNREACHABLE)
    sys.exit(1 if errors > 20 else 0)


if __name__ == '__main__':
    main()
