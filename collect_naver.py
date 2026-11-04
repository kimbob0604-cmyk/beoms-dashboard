"""
네이버 증권 수집: 리서치 리포트 · 투자자별 순매수(수급) · 52주 신고가 · 지수

CLI
  python3 collect_naver.py research              # 최근 14일 목록에서 새 리포트만 본문까지 받기
  python3 collect_naver.py research --days 90    # 백필 (약 4,500건, 20분 안팎)
  python3 collect_naver.py flow                  # 대상 종목 최근 순매수 (처음 받는 종목은 60거래일)
  python3 collect_naver.py high                  # 그날 52주 신고가 목록
  python3 collect_naver.py index                 # 코스피·코스닥 지수 60거래일 + 그날 투자자별 순매수
  python3 collect_naver.py all                   # 넷 다

종료 코드: 0 정상, 1 오류가 많음, 3 서버 응답 없음(연속 실패로 중단)

수급 대상: 시총 1,000억 이상 보통주 + 컨센서스 추정치가 있는 종목 + 최근 90일 리포트가 나온 종목.
"""

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta

import requests

import db
from collectors import naver
from universe import is_common

log = logging.getLogger('collect_naver')

DELAY = 0.2            # 요청 사이 간격(초)
MAX_NET_FAILS = 8      # 연속 네트워크 실패가 이만큼이면 중단
EXIT_UNREACHABLE = 3
FLOW_MIN_MCAP = 1000   # 억원
FLOW_BACKFILL = 60     # 처음 받는 종목의 거래일 수
FLOW_DAILY = 10        # 이미 받은 종목은 최근 10거래일 (며칠 못 돌려도 메워짐)


class Unreachable(Exception):
    pass


class Guard:
    """연속 네트워크 실패를 세다가 MAX_NET_FAILS 에 닿으면 Unreachable."""

    def __init__(self):
        self.fails = 0
        self.errors = 0

    def ok(self):
        self.fails = 0

    def fail(self, what: str, e: Exception):
        self.errors += 1
        log.warning('%s 실패: %s', what, e)
        if isinstance(e, requests.RequestException):
            self.fails += 1
            if self.fails >= MAX_NET_FAILS:
                raise Unreachable(f'연속 {self.fails}회 네트워크 실패')


def now() -> str:
    return datetime.now().isoformat(timespec='seconds')


# ------------------------------------------------------------
# 리포트
# ------------------------------------------------------------

def collect_research(conn, session, days: int) -> int:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    known = {r[0] for r in conn.execute('SELECT id FROM research')}
    guard, new, page = Guard(), [], 1
    while True:
        try:
            items = naver.fetch_research_list(session, page)
            guard.ok()
        except Exception as e:
            guard.fail(f'목록 {page}쪽', e)
            if not isinstance(e, requests.RequestException):
                break   # 형식 변경 등: 같은 쪽을 다시 받아도 소용없음
            time.sleep(1)
            continue
        if not items:
            break
        new += [it for it in items if it['date'] >= cutoff and it['id'] not in known]
        if items[-1]['date'] < cutoff:
            break
        page += 1
        time.sleep(DELAY)
    log.info('리포트 목록 %d쪽, 새 리포트 %d건', page, len(new))

    saved = 0
    for i, it in enumerate(new, 1):
        try:
            d = naver.fetch_research_detail(session, it['id'])
            guard.ok()
        except Exception as e:
            guard.fail(f"리포트 {it['id']}", e)
            continue
        finally:
            time.sleep(DELAY)
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO research
                   (id, code, name, broker, date, title, opinion, goal, price, heads, body, pdf, fetched_at)
                   VALUES (:id, :code, :name, :broker, :date, :title, :opinion, :goal, :price,
                           :heads, :body, :pdf, :fetched_at)""",
                {**d, 'heads': json.dumps(d['heads'], ensure_ascii=False), 'fetched_at': now()})
        saved += 1
        if i % 200 == 0:
            log.info('  %d/%d', i, len(new))
    log.info('리포트 저장 %d건 (오류 %d)', saved, guard.errors)
    return guard.errors


# ------------------------------------------------------------
# 수급
# ------------------------------------------------------------

def flow_targets(conn):
    d = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    codes = {r['code'] for r in conn.execute(
        'SELECT code FROM price_daily WHERE date = ? AND mcap >= ?', (d, FLOW_MIN_MCAP))}
    codes |= {r[0] for r in conn.execute(
        """SELECT DISTINCT code FROM consensus_annual
           WHERE as_of = (SELECT MAX(as_of) FROM consensus_annual) AND is_estimate = 1""")}
    since = (date.today() - timedelta(days=90)).isoformat()
    codes |= {r[0] for r in conn.execute('SELECT DISTINCT code FROM research WHERE date >= ?', (since,))}
    listed = {r[0] for r in conn.execute('SELECT code FROM price_daily WHERE date = ?', (d,))}
    return sorted(c for c in codes if c and is_common(c) and c in listed)


def collect_flow(conn, session) -> int:
    codes = flow_targets(conn)
    have = {r[0] for r in conn.execute('SELECT DISTINCT code FROM flow_daily')}
    log.info('수급 대상 %d종목 (처음 받는 종목 %d)', len(codes), len(set(codes) - have))
    guard = Guard()
    for i, code in enumerate(codes, 1):
        try:
            rows = naver.fetch_flow(session, code, FLOW_DAILY if code in have else FLOW_BACKFILL)
            guard.ok()
        except Exception as e:
            guard.fail(f'수급 {code}', e)
            continue
        finally:
            time.sleep(DELAY)
        with conn:
            conn.executemany(
                """INSERT OR REPLACE INTO flow_daily (date, code, frgn, org, ind, close, frgn_ratio)
                   VALUES (:date, :code, :frgn, :org, :ind, :close, :frgn_ratio)""", rows)
        if i % 300 == 0:
            log.info('  %d/%d', i, len(codes))
    last = conn.execute('SELECT MAX(date) FROM flow_daily').fetchone()[0]
    log.info('수급 완료: 최근 거래일 %s (오류 %d)', last, guard.errors)
    return guard.errors


# ------------------------------------------------------------
# 신고가
# ------------------------------------------------------------

def collect_high(conn, session) -> int:
    guard, rows = Guard(), []
    for market in ('KOSPI', 'KOSDAQ'):
        page = 1
        while True:
            try:
                res = naver.fetch_high52(session, market, page)
                guard.ok()
            except Exception as e:
                guard.fail(f'신고가 {market} {page}쪽', e)
                return guard.errors
            rows += res['rows']
            time.sleep(DELAY)
            if page * 100 >= res['total']:
                break
            page += 1
    rows = [r for r in rows if is_common(r['code'])]
    dates = sorted({r['date'] for r in rows})
    with conn:
        for d in dates:  # 같은 날 다시 받으면 통째로 바꾼다 (장중에 받은 목록을 마감 목록으로)
            conn.execute('DELETE FROM high52_daily WHERE date = ?', (d,))
        conn.executemany(
            """INSERT OR REPLACE INTO high52_daily
               (date, code, name, market, close, change_pct, mcap, trd_val, fetched_at)
               VALUES (:date, :code, :name, :market, :close, :change_pct, :mcap, :trd_val, :fetched_at)""",
            [{**r, 'fetched_at': now()} for r in rows])
    log.info('신고가 %s: %d종목', ','.join(dates) or '-', len(rows))
    return guard.errors


# ------------------------------------------------------------
# 지수
# ------------------------------------------------------------

def collect_index(conn, session) -> int:
    guard, rows = Guard(), []
    for code in ('KOSPI', 'KOSDAQ'):
        try:
            rows += naver.fetch_index(session, code)
            guard.ok()
        except Exception as e:
            guard.fail(f'지수 {code}', e)
        time.sleep(DELAY)
    # 종가는 늘 덮어쓰고, 순매수 등은 값이 있을 때만 (지난 날 행의 순매수를 지우지 않게)
    with conn:
        conn.executemany(
            """INSERT INTO index_daily (date, code, close, change_pct, frgn, org, ind, prog, up, down, flat, fetched_at)
               VALUES (:date, :code, :close, :change_pct, :frgn, :org, :ind, :prog, :up, :down, :flat, :fetched_at)
               ON CONFLICT (date, code) DO UPDATE SET
                 close = excluded.close, change_pct = excluded.change_pct,
                 frgn = COALESCE(excluded.frgn, frgn), org = COALESCE(excluded.org, org),
                 ind = COALESCE(excluded.ind, ind), prog = COALESCE(excluded.prog, prog),
                 up = COALESCE(excluded.up, up), down = COALESCE(excluded.down, down),
                 flat = COALESCE(excluded.flat, flat),
                 fetched_at = CASE WHEN excluded.frgn IS NULL THEN fetched_at ELSE excluded.fetched_at END""",
            [{**r, 'fetched_at': now()} for r in rows])
    last = max((r['date'] for r in rows), default='-')
    log.info('지수 %s까지 %d행', last, len(rows))
    return guard.errors


def main():
    ap = argparse.ArgumentParser(description='네이버 증권 수집 (리포트·수급·신고가·지수)')
    ap.add_argument('what', choices=['research', 'flow', 'high', 'index', 'all'])
    ap.add_argument('--days', type=int, default=14, help='리포트 목록을 거슬러 볼 일수')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')

    conn = db.connect()
    session = requests.Session()
    errors = 0
    try:
        if args.what in ('research', 'all'):
            errors += collect_research(conn, session, args.days)
        if args.what in ('high', 'all'):
            errors += collect_high(conn, session)
        if args.what in ('index', 'all'):
            errors += collect_index(conn, session)
        if args.what in ('flow', 'all'):
            errors += collect_flow(conn, session)
    except Unreachable as e:
        log.error('네이버 서버 응답 없음, 중단: %s', e)
        sys.exit(EXIT_UNREACHABLE)
    sys.exit(1 if errors > 20 else 0)


if __name__ == '__main__':
    main()
