"""
KRX 일별 종가·시총 수집

KRX 일별 데이터는 다음 날 아침(08시 무렵)에 열린다. 그래서 장 마감(15:40) 뒤 저녁·다음 날 이른 아침 실행에서는
그날 종가를 네이버 증권 전 종목 시세로 먼저 채우고, KRX 가 열리면 그 날짜를 KRX 값으로 덮어쓴다.
네이버 목록 종가는 KRX 시간외 단일가·넥스트레이드 애프터마켓(~20:00)까지 따라간 통합 가격이라 정규장 종가와 다르다.
그래서 종목별 수급(flow_daily)에 정규장 종가가 있는 종목은 그 값으로 바꿔 넣고, 나머지는 KRX 가 덮어쓸 때까지 통합 가격이다.

KRX 확정값인지는 일봉(ohlc_daily)에 시가가 있는지로 본다 (네이버 임시 종가에는 시가가 없다).
기본 실행은 최근 HEAL_DAYS 일 안에서 확정값이 아닌 평일을 매번 KRX 로 다시 받는다 — 전에는 가장 최근 날 하나만 받아서,
그날이 '가장 최근'인 동안 실행이 모두 실패하면 임시 종가가 그대로 남았다 (2026-11-20·11-26, 디앤디파마텍 11-26 37,200 vs KRX 36,450).

CLI
  python3 collect_prices.py                     # 가장 최근 거래일 + 최근 HEAL_DAYS 일 중 KRX 확정값이 아닌 날
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
NAVER_TRIES = 3               # 목록에 같은 종목이 겹쳐 오면 다시 받아 합치는 횟수 (처음 포함)
HEAL_DAYS = 14                # 이 기간 안의 평일 중 KRX 확정값이 아닌 날은 기본 실행마다 KRX 로 다시 받는다


OHLC_SQL = """INSERT INTO ohlc_daily (date, code, open, high, low, close, volume, chg)
              VALUES (:date, :code, :open, :high, :low, :close, :volume, :change_pct)"""


def collect_date(conn, session, d: date, ohlc_only: bool = False) -> int:
    """ohlc_only: 일봉만 채운다 (차트용 과거 백필. price_daily 는 건드리지 않음).
    한 시장이라도 비면(휴장·미공개) 아무것도 쓰지 않는다 — 한 시장만 쓰면 다른 시장의 임시 종가가 지워지고
    그날이 확정된 것으로 보인다. 첫 시장이 비면 다음 시장은 묻지 않는다 (KRX 호출 한도 아끼기)."""
    rows = []
    for market in krx.ENDPOINTS:
        got = krx.fetch_daily(session, config.KRX_API_KEY, d.strftime('%Y%m%d'), market)
        if not got:
            if rows:
                log.warning('%s: KRX %s 만 비어 있음 — 쓰지 않음', d, market)
            return 0
        rows += got
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


def unique_by_code(rows) -> tuple:
    """(종목마다 마지막 행만 남긴 목록, 겹친 행 수). 네이버 목록은 시총순이라 시간외 거래 중에 쪽을 넘기는 사이
    순위가 바뀌면 같은 종목이 두 쪽에 들어온다 (2026-11-19 18:56 UNIQUE 오류로 가격 단계가 죽음).
    겹친 종목이 있으면 거꾸로 밀려서 빠진 종목도 있을 수 있다."""
    by = {r['code']: r for r in rows}
    return list(by.values()), len(rows) - len(by)


def naver_list(session) -> list:
    """네이버 전 종목 시세를 쪽마다 받아 이은 목록 (겹친 종목이 있을 수 있다)"""
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
    return rows


def regular_close(conn, rows, d: date) -> int:
    """
    네이버 목록 행(rows)의 통합 가격을, 종목별 수급(flow_daily)에 그날 정규장 종가가 있는 종목은 그 값으로 바꾼다 (바꾼 수).
    flow_daily.close 는 네이버 수급 응답의 krx.regularMarketClosingPrice 다. live.py 가 20:20 무렵부터 받고
    대상은 시총 1,000억 이상 보통주 + 리포트 종목(약 1,400개)이라 20:40 실행이면 시총 큰 종목은 거의 다 바뀐다.
    등락률은 네이버 기준가(종가 - 전일 대비)로, 시총은 상장주식수 × 정규장 종가로 다시 계산한다.
    """
    reg = {c: v for c, v in conn.execute(
        'SELECT code, close FROM flow_daily WHERE date = ? AND close > 0', (d.isoformat(),))}
    n = 0
    for r in rows:
        c = reg.get(r['code'])
        if not c:
            continue
        if c != r['close']:
            if r.get('base'):
                r['change_pct'] = round((c / r['base'] - 1) * 100, 2)
            if r.get('shares'):
                r['mcap'] = r['shares'] * c / 1e8
            r['close'] = c
        n += 1
    return n


def collect_naver(conn, session, d: date) -> int:
    """네이버 전 종목 시세 중 날짜가 d 인 보통·우선주만 d 의 가격으로 저장 (KRX 가 나중에 덮어씀)"""
    by = {}
    for _ in range(NAVER_TRIES):
        rows, dup = unique_by_code(naver_list(session))
        by.update({r['code']: r for r in rows})      # 앞에서 받은 것에 덮어 합친다 (밀려서 빠진 종목을 메운다)
        if not dup:
            break
        log.info('네이버 시세 목록에 같은 종목 %d건 겹침 — 한 번 더 받아 합침', dup)
    rows = [r for r in by.values() if r['date'] == d.isoformat() and r['close']]
    if len(rows) < NAVER_MIN_ROWS:
        return 0
    for r in rows:
        r['shares'] = round(r['mcap'] * 1e8 / r['close']) if r['mcap'] else None   # 네이버 시총 = 통합 가격 × 상장주식수
    n_reg = regular_close(conn, rows, d)
    log.info('%s: 네이버 목록 %d종목 중 %d종목은 종목별 수급의 정규장 종가로 바꿈', d, len(rows), n_reg)
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
        log.info('%s: %d종목 (네이버 시세, KRX 공개 전 임시)', d, n)
    else:
        log.info('%s: 네이버 시세에 이날 종가 없음 (휴장일?)', d)


def confirmed_dates(conn, since: str) -> set:
    """since 이후 KRX 확정값이 들어간 날 (일봉에 시가가 있는 날. 네이버 임시 종가는 시가가 없다)"""
    return {r[0] for r in conn.execute(
        'SELECT DISTINCT date FROM ohlc_daily WHERE date >= ? AND open IS NOT NULL', (since,))}


def heal(conn, session, latest: date) -> list:
    """
    latest 앞 HEAL_DAYS 일 중 KRX 확정값이 없는 평일(네이버 임시 종가로 남은 날·아예 빈 날)을 KRX 로 다시 받는다 (채운 날 목록).
    기본 실행은 KRX 가 연 가장 최근 날만 받는다. 그날이 '가장 최근'인 동안 실행이 모두 실패하면
    (07:10 은 KRX 공개 전, 12:10 은 네트워크 오류, 또는 daily.py 가 오래 돌아 다음 실행들이 건너뜀) 임시 종가가 영영 남았다.
    휴장일은 KRX 가 빈 목록을 돌려줘 아무것도 쓰지 않는다 (실행마다 1회 호출).
    """
    done = confirmed_dates(conn, (latest - timedelta(days=HEAL_DAYS)).isoformat())
    fixed = []
    for i in range(1, HEAL_DAYS + 1):
        d = latest - timedelta(days=i)
        if d.weekday() >= 5 or d.isoformat() in done:
            continue
        try:
            n = collect_date(conn, session, d)
        except requests.RequestException as e:
            log.warning('%s: KRX 다시 받기 실패 — %s', d, e)
            continue
        if n:
            log.info('%s: %d종목 (KRX 확정값이 없던 날 — 다시 채움)', d, n)
            fixed.append(d)
    return fixed


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
        have = {r[0] for r in conn.execute('SELECT DISTINCT date FROM ohlc_daily WHERE open IS NOT NULL AND chg IS NOT NULL')}
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

    # 기본: KRX 가 연 최근 거래일 (오늘 데이터는 보통 다음 날 열림) + 그 앞에 확정값이 없는 날 + 그 뒤 끝난 장은 네이버 종가로
    for i in range(0, 7):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        n = collect_date(conn, session, d)
        if n:
            log.info('%s: %d종목', d, n)
            heal(conn, session, d)
            fill_from_naver(conn, session, d.isoformat())
            return
    sys.exit('최근 7일 내 KRX 데이터 없음')


if __name__ == '__main__':
    main()
