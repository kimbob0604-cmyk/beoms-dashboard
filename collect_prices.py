"""
KRX 일별 종가·시총 수집

CLI
  python3 collect_prices.py                     # 가장 최근 거래일 (오늘부터 거슬러 올라가며 탐색)
  python3 collect_prices.py --date 2026-11-02   # 지정일
  python3 collect_prices.py --days 30           # 최근 30일 백필 (휴장일은 자동 건너뜀)
"""

import argparse
import logging
import sys
import time
from datetime import date, timedelta

import requests

import config
import db
from collectors import krx

log = logging.getLogger('collect_prices')


def collect_date(conn, session, d: date) -> int:
    rows = []
    for market in krx.ENDPOINTS:
        rows += krx.fetch_daily(session, config.KRX_API_KEY, d.strftime('%Y%m%d'), market)
        time.sleep(0.3)
    if rows:
        with conn:
            conn.execute('DELETE FROM price_daily WHERE date = ?', (d.isoformat(),))
            conn.executemany(
                """INSERT INTO price_daily
                   (date, code, name, market, close, change_pct, mcap, shares, trd_val)
                   VALUES (:date, :code, :name, :market, :close, :change_pct, :mcap, :shares, :trd_val)""",
                rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description='KRX 일별 종가·시총 수집')
    ap.add_argument('--date', help='YYYY-MM-DD')
    ap.add_argument('--days', type=int, help='오늘부터 N일 전까지 백필')
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

    if args.days:
        for i in range(args.days, -1, -1):
            d = today - timedelta(days=i)
            if d.weekday() >= 5:
                continue
            n = collect_date(conn, session, d)
            log.info('%s: %d종목', d, n)
        return

    # 기본: 최근 거래일 1개 (오늘 데이터는 보통 다음 날 열림)
    for i in range(0, 7):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        n = collect_date(conn, session, d)
        if n:
            log.info('%s: %d종목', d, n)
            return
    sys.exit('최근 7일 내 KRX 데이터 없음')


if __name__ == '__main__':
    main()
