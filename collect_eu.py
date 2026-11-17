"""
EU 화장품 수입(원산지 기준): Eurostat Comext(DS-045409) SDMX → db/trade.db 의 eu 표

- 보고국: EU27 합과 큰 6국(독일·프랑스·이탈리아·스페인·네덜란드·폴란드)
- 상대국(원산지): 한국·중국·일본·미국, 그리고 역외 전체(EXT_EU27_2020 — 점유율의 분모)
- 품목: K뷰티 바스켓 9개 HS6 + 보툴리눔 톡신(300249, 따로 본다)
- 값: 수입액(유로, CIF 성격)·물량(100kg → kg)

키가 필요 없다. 보통 다음다음 달 중순에 한 달 치가 올라온다(9월 → 11월 중순). 하루 한 번만 부르고,
처음엔 2021년부터, 그 뒤로는 최근 14개월만 다시 받아 정정을 반영한다.
'원산지 기준'이라 한국산 제품이지 한국 회사가 아니다(한국 회사의 해외 생산분은 안 잡히고, 제3국 경유는 원산지로 잡힌다).

  python3 collect_eu.py            # 오늘 아직 안 받았으면 받는다
  python3 collect_eu.py --force    # 지금 다시
  python3 collect_eu.py --status
"""

import argparse
import csv
import io
import sys
from datetime import date, datetime

import requests

from collect_trade import connect

URL = 'https://ec.europa.eu/eurostat/api/comext/dissemination/sdmx/2.1/data/DS-045409/{key}'
REPORTERS = ['EU27_2020', 'DE', 'FR', 'IT', 'ES', 'NL', 'PL']
PARTNERS = ['KR', 'CN', 'JP', 'US', 'EXT_EU27_2020']
BASKET = [('330499', '기초·메이크업'), ('330410', '립'), ('330420', '아이'), ('330430', '매니큐어'), ('330491', '파우더'),
          ('330510', '샴푸'), ('330590', '기타 헤어'), ('330790', '마스크팩·기타'), ('340130', '클렌징')]
EXTRA = [('300249', '보툴리눔 톡신')]
START = '2021-01'

SCHEMA = """
CREATE TABLE IF NOT EXISTS eu (ym TEXT, reporter TEXT, partner TEXT, hs TEXT, eur REAL, kg REAL,
                               PRIMARY KEY (ym, reporter, partner, hs));
"""


def parse(text: str) -> dict:
    """SDMX-CSV → {(ym, reporter, partner, hs): [eur, kg]}"""
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        try:
            v = float(r['OBS_VALUE'])
        except (TypeError, ValueError):
            continue                                      # 비밀 보호 등으로 빈 값
        k = (r['TIME_PERIOD'], r['reporter'], r['partner'], r['product'])
        cell = out.setdefault(k, [None, None])
        if r['indicators'] == 'VALUE_IN_EUROS':
            cell[0] = v
        elif r['indicators'] == 'QUANTITY_IN_100KG':
            cell[1] = v * 100
    return out


def fetch(session, hs: str, start: str) -> dict:
    key = f"M.{'+'.join(REPORTERS)}.{'+'.join(PARTNERS)}.{hs}.1.VALUE_IN_EUROS+QUANTITY_IN_100KG"
    r = session.get(URL.format(key=key), params={'startPeriod': start, 'format': 'SDMX-CSV'}, timeout=120)
    if r.status_code == 404:                              # 그 기간에 값이 하나도 없다
        return {}
    r.raise_for_status()
    return parse(r.text)


def ym_back(today: date, months: int) -> str:
    y, m = today.year, today.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    return f'{y}-{m:02d}'


def collect(conn, force: bool = False, today: date = None, log=print) -> int:
    today = today or date.today()
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT v FROM meta WHERE k = 'eu_refreshed_at'").fetchone()
    if row and row[0][:10] == today.isoformat() and not force:
        log('EU 수입: 오늘 이미 받음')
        return 0
    empty = not conn.execute('SELECT 1 FROM eu LIMIT 1').fetchone()
    start = START if empty else ym_back(today, 14)
    s = requests.Session()
    n = fail = 0
    for hs, _ in BASKET + EXTRA:
        try:
            rows = fetch(s, hs, start)
        except requests.RequestException as e:
            fail += 1
            log(f'  실패 {hs}: {str(e)[:120]}')
            continue
        conn.executemany('INSERT OR REPLACE INTO eu VALUES (?,?,?,?,?,?)', [(*k, *v) for k, v in rows.items()])
        n += len(rows)
    if not fail:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('eu_refreshed_at', ?)", (datetime.now().isoformat(timespec='seconds'),))
    conn.commit()
    last = conn.execute('SELECT MAX(ym) FROM eu').fetchone()[0]
    log(f'EU 수입: {start}부터 {n:,}줄, 실패 {fail} · 마지막 달 {last}')
    return 1 if fail else 0


def status(conn):
    conn.executescript(SCHEMA)
    r = conn.execute('SELECT COUNT(*), MIN(ym), MAX(ym), COUNT(DISTINCT hs) FROM eu').fetchone()
    print(f'eu {r[0]:,}줄  {r[1]} ~ {r[2]}  품목 {r[3]}  ·  받은 때',
          (conn.execute("SELECT v FROM meta WHERE k='eu_refreshed_at'").fetchone() or ['–'])[0])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args()
    conn = connect()
    if a.status:
        status(conn)
        return 0
    return collect(conn, a.force)


if __name__ == '__main__':
    sys.exit(main())
