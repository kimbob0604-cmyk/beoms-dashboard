"""
수급 기관 세부: 한국투자증권 Open API 종목별 투자자 매매동향 → flow_detail (db/dashboard.db)

대상은 수급 탭과 같다 (collect_naver.flow_targets: 시총 1,000억 이상 보통주 + 컨센서스·리포트 종목).
한 종목 한 번 호출에 30거래일. 처음 받는 종목은 한 번 더 불러 60거래일을 채운다(수급 탭 60일 합).
이미 그 거래일 행이 있는 종목은 건너뛰므로 다시 돌려도 호출이 늘지 않는다.

  python3 collect_kis_flow.py            # 수급 탭의 마지막 거래일을 아직 안 받은 종목만 (다 받았으면 종료 코드 10)
  python3 collect_kis_flow.py --refill   # 전 종목 60거래일 다시

종료 코드: 0 정상, 1 오류 많음, 3 서버 응답 없음, 4 키 없음, 10 새 거래일 없음
"""

import argparse
import logging
import sys
import time
from datetime import date, timedelta

import requests

import config  # noqa: F401  (.env → KIS_APP_KEY)
import db
from collect_naver import flow_targets
from collectors import kis

log = logging.getLogger('collect_kis_flow')
PROBE = '005930'
GAP = 0.11          # 초당 한도 20회 — 같은 키를 쓰는 다른 프로그램 몫을 남겨 9회 남짓
BACKFILL = 60
NO_NEW, UNREACHABLE, NO_KEY = 10, 3, 4
COLS = ['date', 'code', *kis.FIELDS]


def save(conn, rows):
    with conn:
        conn.executemany(f"INSERT OR REPLACE INTO flow_detail ({', '.join(COLS)}) VALUES ({', '.join(':' + c for c in COLS)})", rows)


def ymd(d: str) -> str:
    return d.replace('-', '')


def collect(conn, session, tok, refill=False) -> int:
    """기준일은 수급 탭(네이버)에 이미 올라온 마지막 거래일. KIS 는 15:40 전에는 오늘 날짜 조회를 거절하고(OPSQ2001),
    장중 값이 섞이지 않게 하려는 것도 있다"""
    last = conn.execute('SELECT MAX(date) FROM flow_daily').fetchone()[0]
    if not last:
        raise kis.KisError('flow_daily 가 비어 있음 — collect_naver.py flow 먼저')
    have = conn.execute('SELECT 1 FROM flow_detail WHERE date = ? AND code = ?', (last, PROBE)).fetchone()
    if have and not refill:
        log.info('새 거래일 없음 (%s 까지 받음)', last)
        return -1
    probe = kis.investor_daily(session, tok, PROBE, ymd(last))
    if not probe or probe[0]['date'] != last:
        log.info('KIS 에 %s 수급이 아직 없음', last)
        return -1
    codes = flow_targets(conn)
    done = {r[0] for r in conn.execute('SELECT code FROM flow_detail WHERE date = ?', (last,))}
    count = dict(conn.execute('SELECT code, COUNT(*) FROM flow_detail GROUP BY code').fetchall())
    todo = [c for c in codes if refill or c not in done]
    log.info('기관 세부 %s: 대상 %d종목, 받을 종목 %d', last, len(codes), len(todo))
    errors = fails = 0
    for i, code in enumerate(todo, 1):
        try:
            rows = kis.investor_daily(session, tok, code, ymd(last))
            if rows and (refill or count.get(code, 0) + len(rows) < BACKFILL):   # 처음이면 그 앞 30거래일도
                time.sleep(GAP)
                prev = (date.fromisoformat(rows[-1]['date']) - timedelta(days=1)).strftime('%Y%m%d')
                rows += kis.investor_daily(session, tok, code, prev)
            save(conn, rows)
            fails = 0
        except requests.RequestException as e:
            errors += 1
            fails += 1
            log.warning('%s 네트워크 실패: %s', code, e)
            if fails >= 5:
                raise
        except kis.KisError as e:
            errors += 1
            log.warning('%s', e)
        time.sleep(GAP)
        if i % 300 == 0:
            log.info('  %d/%d', i, len(todo))
    log.info('기관 세부 완료: %s, 오류 %d', last, errors)
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description='KIS 종목별 투자자 매매동향(기관 세부) 수집')
    ap.add_argument('--refill', action='store_true', help='전 종목 60거래일 다시')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    if not all(kis.keys()):
        log.info('KIS 키 없음 — 건너뜀')
        return NO_KEY
    conn = db.connect()
    session = requests.Session()
    try:
        tok = kis.token(session)
        errors = collect(conn, session, tok, args.refill)
    except requests.RequestException as e:
        log.error('KIS 응답 없음, 중단: %s', e)
        return UNREACHABLE
    except kis.KisError as e:
        log.error('KIS 오류: %s', e)
        return UNREACHABLE
    if errors < 0:
        return NO_NEW
    return 1 if errors > 20 else 0


if __name__ == '__main__':
    sys.exit(main())
