"""
KRX 일별 종가·시총 수집

KRX 일별 데이터는 다음 날 아침에 열린다. 그래서 장 마감(15:40) 뒤 저녁·다음 날 이른 아침 실행에서는
그날 종가를 네이버 증권 전 종목 시세로 먼저 채우고, KRX 가 열리면 그 날짜를 KRX 값으로 덮어쓴다.
네이버 값은 넥스트레이드 시간외(~20:00)까지 반영한 통합 가격이라 KRX 정규장 종가와 조금 다를 수 있다.

CLI
  python3 collect_prices.py                     # 가장 최근 거래일 (오늘부터 거슬러 올라가며 탐색)
  python3 collect_prices.py --date 2026-11-02   # 지정일
  python3 collect_prices.py --days 30           # 최근 30일 백필 (휴장일은 자동 건너뜀)
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime, time as dtime, timedelta

import requests

import config
import db
from collectors import krx, naver

log = logging.getLogger('collect_prices')

CLOSE_AFTER = dtime(15, 40)   # 이 시각 뒤면 그날 종가가 확정된 것으로 본다
PREOPEN = dtime(8, 0)         # 넥스트레이드 프리마켓 시작. 이 뒤로는 네이버 시세가 새 날짜로 바뀐다
NAVER_MIN_ROWS = 2000         # 이보다 적으면 목록이 덜 온 것으로 보고 쓰지 않음


OHLC_SQL = """INSERT INTO ohlc_daily (date, code, open, high, low, close, volume)
              VALUES (:date, :code, :open, :high, :low, :close, :volume)"""


def collect_date(conn, session, d: date, ohlc_only: bool = False) -> int:
    """ohlc_only: 일봉만 채운다 (차트용 과거 백필. price_daily 는 건드리지 않음)"""
    rows = []
    for market in krx.ENDPOINTS:
        rows += krx.fetch_daily(session, config.KRX_API_KEY, d.strftime('%Y%m%d'), market)
        time.sleep(0.3)
    if rows:
        with conn:
            if not ohlc_only:
                conn.execute('DELETE FROM price_daily WHERE date = ?', (d.isoformat(),))
                conn.executemany(
                    """INSERT INTO price_daily
                       (date, code, name, market, close, change_pct, mcap, shares, trd_val)
                       VALUES (:date, :code, :name, :market, :close, :change_pct, :mcap, :shares, :trd_val)""",
                    rows)
            conn.execute('DELETE FROM ohlc_daily WHERE date = ?', (d.isoformat(),))
            conn.executemany(OHLC_SQL, rows)
    return len(rows)


def expected_session(now: datetime):
    """
    지금 화면에 있어야 할 가장 최근 장 날짜. 15:40 뒤면 오늘, 08:00 전이면 직전 평일.
    그 사이(장중)는 None — 네이버 시세가 아직 그날 종가가 아니다. 휴장일은 네이버 응답 날짜로 거른다.
    """
    d = now.date()
    if PREOPEN <= now.time() < CLOSE_AFTER:
        return None
    if now.time() < PREOPEN:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def collect_naver(conn, session, d: date) -> int:
    """네이버 전 종목 시세 중 날짜가 d 인 보통·우선주만 d 의 가격으로 저장 (KRX 가 나중에 덮어씀)"""
    rows = []
    for market in krx.ENDPOINTS:
        page = 1
        while True:
            res = naver.fetch_market_list(session, market, page)
            rows += res['rows']
            if page * 100 >= res['total']:
                break
            page += 1
            time.sleep(0.2)
    rows = [r for r in rows if r['date'] == d.isoformat() and r['close']]
    if len(rows) < NAVER_MIN_ROWS:
        return 0
    for r in rows:
        r['shares'] = round(r['mcap'] * 1e8 / r['close']) if r['mcap'] else None
    with conn:
        conn.execute('DELETE FROM price_daily WHERE date = ?', (d.isoformat(),))
        conn.executemany(
            """INSERT INTO price_daily
               (date, code, name, market, close, change_pct, mcap, shares, trd_val)
               VALUES (:date, :code, :name, :market, :close, :change_pct, :mcap, :shares, :trd_val)""",
            rows)
        # 시가·고가·저가는 이 목록에 없어 종가만 (KRX 가 공개되면 덮어씀)
        conn.execute('DELETE FROM ohlc_daily WHERE date = ?', (d.isoformat(),))
        conn.executemany(OHLC_SQL, [{**r, 'open': None, 'high': None, 'low': None, 'volume': None} for r in rows])
    return len(rows)


def fill_from_naver(conn, session, latest: str):
    """KRX 최근 거래일(latest)보다 뒤인 장 날짜가 끝났으면 그날 종가를 네이버로 채운다"""
    d = expected_session(datetime.now())
    if not d or d.isoformat() <= (latest or ''):
        return
    try:
        n = collect_naver(conn, session, d)
    except (requests.RequestException, ValueError) as e:
        log.warning('네이버 시세 실패: %s', e)
        return
    if n:
        log.info('%s: %d종목 (네이버 통합 시세, KRX 공개 전 임시)', d, n)
    else:
        log.info('%s: 네이버 시세에 이날 종가 없음 (휴장일?)', d)


def main():
    ap = argparse.ArgumentParser(description='KRX 일별 종가·시총 수집')
    ap.add_argument('--date', help='YYYY-MM-DD')
    ap.add_argument('--days', type=int, help='오늘부터 N일 전까지 백필')
    ap.add_argument('--ohlc-days', type=int, help='차트용 일봉만 N일 전까지 백필 (이미 있는 날은 건너뜀)')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    if not config.KRX_API_KEY:
        sys.exit('KRX_API_KEY 없음 (.env 확인)')

    conn = db.connect()
    session = requests.Session()
    today = date.today()

    if args.date:
        n = collect_date(conn, session, date.fromisoformat(args.date))
        log.info('%s: %d종목', args.date, n)
        sys.exit(0 if n else 1)

    if args.ohlc_days:
        have = {r[0] for r in conn.execute('SELECT DISTINCT date FROM ohlc_daily WHERE open IS NOT NULL')}
        for i in range(args.ohlc_days, 0, -1):
            d = today - timedelta(days=i)
            if d.weekday() >= 5 or d.isoformat() in have:
                continue
            try:
                n = collect_date(conn, session, d, ohlc_only=True)
            except requests.RequestException as e:
                log.warning('%s: %s', d, e)
                continue
            log.info('%s: 일봉 %d종목', d, n)
        return

    if args.days:
        for i in range(args.days, -1, -1):
            d = today - timedelta(days=i)
            if d.weekday() >= 5:
                continue
            n = collect_date(conn, session, d)
            log.info('%s: %d종목', d, n)
        return

    # 기본: 최근 거래일 1개 (오늘 데이터는 보통 다음 날 열림) + 그 뒤 끝난 장은 네이버 종가로
    for i in range(0, 7):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        n = collect_date(conn, session, d)
        if n:
            log.info('%s: %d종목', d, n)
            fill_from_naver(conn, session, d.isoformat())
            return
    sys.exit('최근 7일 내 KRX 데이터 없음')


if __name__ == '__main__':
    main()
