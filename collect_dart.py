"""
DART 공시 수집 → dart_filing, 분기 컨센서스 스냅샷 → cns_quarter

  python3 collect_dart.py              # 오늘·어제 공시 (처음 보는 공시만 원문을 받는다)
  python3 collect_dart.py --days 14    # 최근 14일 백필
  python3 collect_dart.py cns          # 컨센서스 있는 종목의 분기 추정치 스냅샷 (하루 한 번이면 충분)

잠정실적이 들어오면 그 종목의 분기 추정치를 바로 한 번 더 받아 둔다(네이버가 발표 뒤에도 하루쯤 추정 열을 남겨 둔다).
종료 코드: 0 정상, 1 오류가 많음, 3 DART 응답 없음
"""

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta

import requests

import config  # noqa: F401  (.env 로딩)
import db
from collectors import dart

log = logging.getLogger('collect_dart')
DELAY = 0.15
MAX_FAILS = 8
MARKET = {'Y': 'KOSPI', 'K': 'KOSDAQ'}
EXIT_UNREACHABLE = 3


def key() -> str:
    import os
    k = os.environ.get('DART_API_KEY', '')
    if not k:
        sys.exit('DART_API_KEY 없음 (.env 확인)')
    return k


def now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def save_cns(conn, code, cns: dict, as_of: str):
    with conn:
        conn.executemany(
            'INSERT OR REPLACE INTO cns_quarter (as_of, code, period, sales, op, np, cnp) VALUES (?, ?, ?, ?, ?, ?, ?)',
            [(as_of, code, p, v.get('sales'), v.get('op'), v.get('np'), v.get('cnp')) for p, v in cns.items()])


def collect_day(conn, session, k: str, d: date) -> int:
    rows = dart.fetch_list(session, k, d.strftime('%Y%m%d'))
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
            log.warning('%s %s 원문 실패: %s', r['corp_name'], r['report_nm'].strip(), e)
            if fails >= MAX_FAILS:
                raise
        except Exception as e:   # 양식이 달라 못 읽은 공시는 제목만 남긴다
            errors += 1
            log.warning('%s %s 파싱 실패: %s', r['corp_name'], r['report_nm'].strip(), e)
            data = {}
        if kind == 'earn':
            data['basis'] = '연결' if '연결' in r['report_nm'] else '별도'
            try:
                save_cns(conn, r['stock_code'], dart.fetch_quarter_cns(session, r['stock_code']), date.today().isoformat())
            except Exception as e:
                log.warning('%s 분기 컨센서스 실패: %s', r['corp_name'], e)
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
    ap.add_argument('what', nargs='?', default='filings', choices=['filings', 'cns'])
    ap.add_argument('--days', type=int, default=1, help='오늘부터 N일 전까지')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    conn = db.connect()
    session = requests.Session()
    errors = 0
    try:
        if args.what == 'cns':
            errors += collect_cns(conn, session)
        else:
            k = key()
            for i in range(args.days, -1, -1):
                d = date.today() - timedelta(days=i)
                if d.weekday() < 5:
                    errors += collect_day(conn, session, k, d)
    except requests.RequestException as e:
        log.error('응답 없음, 중단: %s', e)
        sys.exit(EXIT_UNREACHABLE)
    sys.exit(1 if errors > 20 else 0)


if __name__ == '__main__':
    main()
