"""
방한 외래관광객 (한국문화관광연구원 출입국관광통계서비스, 공공데이터포털) → db/trade.db 의 tour 표

getEdrcntTourismStatsList 에 YM(필수)·ED_CD=E(방한 외래)만 주면(NAT_CD 생략) 그 달 국적별 줄이 모두 온다.
키는 관세청과 같은 공공데이터포털 키(config.DATAGO_KEY). 2026-11-16 사용자가 이 서비스 활용 신청을 승인받았다
(승인 직후엔 'SERVICE KEY IS NOT REGISTERED' 가 한두 시간 나온다 — 그때는 4 로 조용히 건너뛴다).

처음엔 2015-01 부터, 그 뒤로는 하루 한 번 최근 13개월만 다시 받아 소급 정정을 반영한다.

  python3 collect_tourism.py            # 오늘 아직 안 받았으면
  python3 collect_tourism.py --force
  python3 collect_tourism.py --status
"""

import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime

import requests

import config
from collect_trade import connect

URL = 'http://openapi.tour.go.kr/openapi/service/EdrcntTourismStatsService/getEdrcntTourismStatsList'
START = '2015-01'
SCHEMA = """
CREATE TABLE IF NOT EXISTS tour (ym TEXT, nat_cd TEXT, nat TEXT, num REAL, PRIMARY KEY (ym, nat_cd));
"""


class TourError(RuntimeError):
    pass


class NotRegistered(TourError):
    pass


def parse(text: str) -> list:
    """XML → [{ym, nat_cd, nat, num}]. 결과 코드가 00 이 아니면 TourError"""
    root = ET.fromstring(text)
    code = (root.findtext('.//resultCode') or '').strip()
    msg = (root.findtext('.//resultMsg') or root.findtext('.//returnAuthMsg') or '').strip()
    if code == '30' or 'NOT REGISTERED' in msg or 'SERVICE_KEY_IS_NOT_REGISTERED' in text:
        raise NotRegistered(msg or 'SERVICE KEY IS NOT REGISTERED')
    if code not in ('00', '0000', ''):
        raise TourError(f'{code} {msg}')
    out = []
    for it in root.iter('item'):
        g = lambda k: (it.findtext(k) or '').strip()          # noqa: E731
        ym, num = re.sub(r'\D', '', g('ym')), g('num')
        if len(ym) != 6 or not num:
            continue
        out.append({'ym': f'{ym[:4]}-{ym[4:]}', 'nat_cd': g('natCd'), 'nat': g('natKorNm'), 'num': float(num.replace(',', ''))})
    return out


def fetch_month(session, key: str, ym: str) -> list:
    r = session.get(URL, params={'serviceKey': key, 'YM': ym.replace('-', ''), 'ED_CD': 'E', 'numOfRows': '999', 'pageNo': '1'},
                    timeout=30)
    if r.status_code != 200:
        raise TourError(f'HTTP {r.status_code}')
    return parse(r.text)


def months(a: str, b: str) -> list:
    out, (y, m) = [], (int(a[:4]), int(a[5:]))
    while f'{y}-{m:02d}' <= b:
        out.append(f'{y}-{m:02d}')
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out


def collect(conn, force: bool = False, today: date = None, log=print) -> int:
    today = today or date.today()
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT v FROM meta WHERE k = 'tour_refreshed_at'").fetchone()
    if row and row[0][:10] == today.isoformat() and not force:
        log('방한 관광객: 오늘 이미 받음')
        return 0
    if not config.DATAGO_KEY:
        log('DATAGO_KEY 없음 — 건너뜀')
        return 4
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    end = f'{y}-{m:02d}'
    have = {r[0] for r in conn.execute('SELECT DISTINCT ym FROM tour')}
    recent = months(f'{y - 1}-{m:02d}', end)
    todo = [ym for ym in months(START, end) if ym not in have or ym in recent]
    s = requests.Session()
    n = fail = 0
    for ym in sorted(todo, reverse=True):
        try:
            rows = fetch_month(s, config.DATAGO_KEY, ym)
        except NotRegistered as e:
            log(f'방한 관광객: 키가 이 서비스에 아직 등록되지 않음({e}) — 승인 뒤 한두 시간 걸린다. 건너뜀')
            return 4
        except (TourError, requests.RequestException, ET.ParseError) as e:
            fail += 1
            log(f'  실패 {ym}: {str(e)[:120]}')
            if fail >= 5:
                break
            continue
        if rows:
            conn.execute('DELETE FROM tour WHERE ym = ?', (ym,))
            conn.executemany('INSERT OR REPLACE INTO tour VALUES (:ym, :nat_cd, :nat, :num)', rows)
            n += len(rows)
        time.sleep(0.2)
    if not fail:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('tour_refreshed_at', ?)", (datetime.now().isoformat(timespec='seconds'),))
    conn.commit()
    log(f'방한 관광객: {len(todo)}개월 요청, {n:,}줄, 실패 {fail} · 마지막 달 {conn.execute("SELECT MAX(ym) FROM tour").fetchone()[0]}')
    return 1 if fail else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args()
    conn = connect()
    conn.executescript(SCHEMA)
    if a.status:
        r = conn.execute('SELECT COUNT(*), MIN(ym), MAX(ym), COUNT(DISTINCT nat_cd) FROM tour').fetchone()
        print(f'tour {r[0]:,}줄  {r[1]} ~ {r[2]}  국적 {r[3]}')
        return 0
    return collect(conn, a.force)


if __name__ == '__main__':
    sys.exit(main())
