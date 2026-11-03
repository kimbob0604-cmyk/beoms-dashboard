"""
1단계: 연간 컨센서스 수집기

종목마다
  1) flag=2 연간 실적·추정 (1회)
  2) 추정(E) 연도마다 flag=4 컨센서스 추이 (최대 3회)
  3) 추정치가 있고 메타가 없거나 오래됐으면 시장/WICS (1회)
→ db/dashboard.db 에 as_of(오늘) 스냅샷으로 저장

CLI
  python3 collect_consensus.py --codes 251970,005930   # 지정 종목
  python3 collect_consensus.py --limit 50               # 시총 상위 50
  python3 collect_consensus.py                          # 전체 (이미 수집한 종목은 건너뜀)
  python3 collect_consensus.py --check                  # 오늘 수집 결과 점검만
  python3 collect_consensus.py --covered-only           # 추정치 있던 종목 + 신규만 (평일 자동 실행용)

종료 코드: 0 정상, 1 오류 많음, 2 커버리지 급감(형식 변경 의심), 3 서버 응답 없음(연속 실패로 중단)
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta

import requests

import db
from collectors import wisereport as wr
from universe import load_universe

log = logging.getLogger('collect_consensus')

META_MAX_AGE_DAYS = 7
RETRIES = 2
SEPARATE_MIN_MCAP = 500   # 억원. 이 이상만 별도 기준 대체 조회
MAX_NET_FAILS = 8         # 연속 네트워크 실패가 이만큼이면 서버가 막힌 것으로 보고 중단 (다음 실행이 이어받음)
EXIT_UNREACHABLE = 3


class Throttle:
    """요청 사이 최소 간격 보장"""

    def __init__(self, delay: float):
        self.delay = delay
        self._last = 0.0

    def wait(self):
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()


def _call(throttle, fn, *args):
    for attempt in range(RETRIES + 1):
        throttle.wait()
        try:
            return fn(*args)
        except (requests.RequestException, ValueError) as e:
            # ValueError = 응답 형식 변경 → 재시도해도 소용없음
            if isinstance(e, ValueError) and not isinstance(e, requests.JSONDecodeError):
                raise
            if attempt == RETRIES:
                raise
            time.sleep(2 * (attempt + 1))


def _meta_is_stale(conn, code: str) -> bool:
    row = conn.execute('SELECT updated_at FROM stock_meta WHERE code = ?', (code,)).fetchone()
    if not row or not row['updated_at']:
        return True
    return datetime.fromisoformat(row['updated_at']) < datetime.now() - timedelta(days=META_MAX_AGE_DAYS)


def collect_one(conn, session, throttle, code: str, as_of: str, try_separate: bool = True) -> dict:
    fin_gubun = 'MAIN'
    annual = _call(throttle, wr.fetch_annual, session, code, fin_gubun)
    estimates = [a for a in annual if a['is_estimate']]

    # 연결 추정이 없으면 별도 기준 컨센서스로 대체 (연결 우선, 없으면 별도)
    if not estimates and try_separate and annual and '연결' in (annual[-1]['basis'] or ''):
        separate = _call(throttle, wr.fetch_annual, session, code, 'IFRSS')
        if any(a['is_estimate'] for a in separate):
            fin_gubun, annual = 'IFRSS', separate
            estimates = [a for a in annual if a['is_estimate']]

    trends = []
    for a in estimates:
        for t in _call(throttle, wr.fetch_trend, session, code, a['fy'], a['fy_month'], fin_gubun):
            trends.append({**t, 'fy': a['fy'], 'fy_month': a['fy_month']})

    meta = None
    if estimates and _meta_is_stale(conn, code):
        meta = _call(throttle, wr.fetch_overview, session, code)

    with conn:
        conn.execute('DELETE FROM consensus_annual WHERE as_of = ? AND code = ?', (as_of, code))
        conn.execute('DELETE FROM consensus_trend WHERE as_of = ? AND code = ?', (as_of, code))
        conn.executemany(
            """INSERT INTO consensus_annual
               (as_of, code, fy, fy_month, is_estimate, basis, revenue, op, ni, eps, bps, roe)
               VALUES (:as_of, :code, :fy, :fy_month, :is_estimate, :basis,
                       :revenue, :op, :ni, :eps, :bps, :roe)""",
            [{**a, 'as_of': as_of, 'code': code} for a in annual])
        conn.executemany(
            """INSERT INTO consensus_trend
               (as_of, code, fy, fy_month, metric, cns_date, now, w1, m1, m3, y1)
               VALUES (:as_of, :code, :fy, :fy_month, :metric, :cns_date, :now, :w1, :m1, :m3, :y1)""",
            [{**t, 'as_of': as_of, 'code': code} for t in trends])
        if meta:
            conn.execute(
                """INSERT INTO stock_meta (code, name, market, market_sector, wics, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(code) DO UPDATE SET
                     name = excluded.name, market = excluded.market,
                     market_sector = excluded.market_sector, wics = excluded.wics,
                     updated_at = excluded.updated_at""",
                (code, meta['name'], meta['market'], meta['market_sector'], meta['wics'],
                 datetime.now().isoformat(timespec='seconds')))
    return {'n_annual': len(annual), 'n_estimate': len(estimates), 'n_trend': len(trends)}


def _log_result(conn, as_of, code, status, n_estimate=None, error=None):
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO collect_log (as_of, code, status, n_estimate, error, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (as_of, code, status, n_estimate, error, datetime.now().isoformat(timespec='seconds')))


def check(conn, as_of: str, top_codes) -> int:
    """수집 결과 점검. 형식 변경 의심이면 0이 아닌 값을 돌려준다."""
    stat = {r['status']: r['n'] for r in conn.execute(
        'SELECT status, COUNT(*) n FROM collect_log WHERE as_of = ? GROUP BY status', (as_of,))}
    with_est = conn.execute(
        "SELECT COUNT(*) FROM collect_log WHERE as_of = ? AND status = 'ok' AND n_estimate > 0",
        (as_of,)).fetchone()[0]
    print(f'[{as_of}] ok={stat.get("ok", 0)} no_data={stat.get("no_data", 0)} '
          f'error={stat.get("error", 0)} / 추정치 보유 {with_est}종목')

    # 시총 상위 100 중 수집된 종목의 추정치 보유율 — 평소 90% 이상이어야 정상
    top = list(top_codes)[:100]
    if top:
        q = ','.join('?' * len(top))
        done, est = conn.execute(
            f"""SELECT COUNT(*), SUM(n_estimate > 0) FROM collect_log
                WHERE as_of = ? AND status = 'ok' AND code IN ({q})""",
            (as_of, *top)).fetchone()
        if done >= 30:
            ratio = (est or 0) / done
            print(f'  시총 상위 {done}종목 추정치 보유율 {ratio:.0%}')
            if ratio < 0.7:
                print('  ⚠️ 보유율이 낮음 — 응답 형식 변경 가능성 확인 필요')
                return 2
    errors = conn.execute(
        "SELECT code, error FROM collect_log WHERE as_of = ? AND status = 'error' LIMIT 5",
        (as_of,)).fetchall()
    for e in errors:
        print(f'  error {e["code"]}: {e["error"]}')
    return 1 if stat.get('error', 0) > max(10, 0.05 * sum(stat.values())) else 0


def covered_codes(conn, as_of: str, codes):
    """
    직전 스냅샷에서 추정치가 있던 종목 + 한 번도 정상 수집된 적 없는 종목(신규 상장 등).
    커버리지가 새로 생긴 종목은 다음 전체 수집(월요일)에서 잡힌다. 직전 스냅샷이 없으면 전체.
    """
    prev = conn.execute('SELECT MAX(as_of) FROM consensus_annual WHERE as_of < ?', (as_of,)).fetchone()[0]
    if not prev:
        return codes
    covered = {r[0] for r in conn.execute(
        'SELECT DISTINCT code FROM consensus_annual WHERE as_of = ? AND is_estimate = 1', (prev,))}
    seen = {r[0] for r in conn.execute("SELECT DISTINCT code FROM collect_log WHERE status != 'error'")}
    return [c for c in codes if c in covered or c not in seen]


def main():
    ap = argparse.ArgumentParser(description='연간 컨센서스 수집 (네이버 종목분석/FnGuide)')
    ap.add_argument('--codes', help='쉼표 구분 종목코드')
    ap.add_argument('--limit', type=int, help='시총 상위 N종목만')
    ap.add_argument('--min-mcap', type=float, default=0, help='최소 시총(억원)')
    ap.add_argument('--delay', type=float, default=0.6, help='요청 간격(초)')
    ap.add_argument('--as-of', default=date.today().isoformat())
    ap.add_argument('--force', action='store_true', help='오늘 이미 수집한 종목도 다시')
    ap.add_argument('--check', action='store_true', help='수집 없이 점검만')
    ap.add_argument('--covered-only', action='store_true',
                    help='직전 스냅샷에서 추정치가 있던 종목 + 아직 제대로 받아 본 적 없는 종목만 (요청 수 약 1/4)')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    conn = db.connect()

    universe = load_universe(args.min_mcap)
    if args.codes:
        codes = [c.strip() for c in args.codes.split(',') if c.strip()]
    else:
        codes = [u['code'] for u in universe][:args.limit]

    if args.check:
        sys.exit(check(conn, args.as_of, [u['code'] for u in universe]))

    if args.covered_only:
        codes = covered_codes(conn, args.as_of, codes)

    if not args.force:
        done = {r['code'] for r in conn.execute(
            "SELECT code FROM collect_log WHERE as_of = ? AND status != 'error'", (args.as_of,))}
        codes = [c for c in codes if c not in done]

    mcap = {u['code']: u['market_cap'] for u in universe}
    session = requests.Session()
    throttle = Throttle(args.delay)
    started = time.monotonic()
    log.info('수집 시작: %d종목 (as_of=%s)', len(codes), args.as_of)

    net_fails = 0
    for i, code in enumerate(codes, 1):
        try:
            # 소형주는 별도 컨센서스도 거의 없음 → 대체 조회 생략해 요청 수 절약
            try_separate = mcap.get(code, SEPARATE_MIN_MCAP) >= SEPARATE_MIN_MCAP
            res = collect_one(conn, session, throttle, code, args.as_of, try_separate)
            status = 'ok' if res['n_annual'] else 'no_data'
            _log_result(conn, args.as_of, code, status, res['n_estimate'])
            net_fails = 0
        except Exception as e:  # 한 종목 실패가 전체를 멈추지 않게
            _log_result(conn, args.as_of, code, 'error', error=f'{type(e).__name__}: {e}'[:300])
            log.warning('%s 실패: %s', code, e)
            net_fails = net_fails + 1 if isinstance(e, requests.RequestException) else 0
            if net_fails >= MAX_NET_FAILS:
                log.error('연속 %d종목 네트워크 실패 → 서버 응답 없음으로 보고 중단 (%d/%d)', net_fails, i, len(codes))
                sys.exit(EXIT_UNREACHABLE)
        if i % 50 == 0 or i == len(codes):
            elapsed = time.monotonic() - started
            log.info('%d/%d (%.0f초, 남은 예상 %.0f분)', i, len(codes), elapsed,
                     elapsed / i * (len(codes) - i) / 60)

    sys.exit(check(conn, args.as_of, [u['code'] for u in universe]))


if __name__ == '__main__':
    main()
