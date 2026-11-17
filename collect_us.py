"""
미국 화장품·톡신 수입(원산지 기준): UN Comtrade 공개 미리보기 API(키 없음) → db/trade.db 의 us 표

US Census API 는 키를 요구해서, 같은 미국 수입 통계를 미국이 UN 에 보고한 값으로 받는다.
comtradeapi.un.org/public/v1/preview 는 키 없이 한 번에 한 달(최대 500줄)만 준다 — 달마다 한 번 부른다.

- 보고국 미국(842), 상대국(원산지): 세계(0)·한국(410)·중국(156)·일본(392)·프랑스(251)
- 품목: EU 와 같은 K뷰티 바스켓 9개 HS6 + 보툴리눔 톡신(300249 — 주보·레티보 같은 한국산 톡신 수입)
- 값: 달러(primaryValue), 순중량 kg. 보통 두 달 늦게 올라온다.

처음엔 2021-01 부터, 그 뒤로는 하루 한 번 최근 6개월만 다시 받는다. 너무 빨리 부르면 막혀서 3초씩 쉰다.

  python3 collect_us.py [--force|--status]
"""

import argparse
import sys
import time
from datetime import date, datetime

import requests

from collect_eu import BASKET, EXTRA
from collect_trade import connect

URL = 'https://comtradeapi.un.org/public/v1/preview/C/M/HS'
PARTNERS = {0: 'WLD', 410: 'KR', 156: 'CN', 392: 'JP', 251: 'FR'}
START = '2021-01'
PAUSE = 3.0
SCHEMA = """
CREATE TABLE IF NOT EXISTS us (ym TEXT, partner TEXT, hs TEXT, usd REAL, kg REAL, PRIMARY KEY (ym, partner, hs));
"""


class ComtradeError(RuntimeError):
    pass


def parse(d: dict) -> list:
    """응답 JSON → [(ym, partner, hs, usd, kg)]. 운송수단·세관 세부 줄은 빼고 합계 줄만"""
    if d.get('error'):
        raise ComtradeError(d['error'])
    out = []
    for r in d.get('data') or []:
        if r.get('partner2Code', 0) != 0 or r.get('motCode', 0) != 0 or r.get('customsCode', 'C00') != 'C00':
            continue
        p = PARTNERS.get(r.get('partnerCode'))
        if p is None or r.get('flowCode') != 'M':
            continue
        per = str(r['period'])
        out.append((f'{per[:4]}-{per[4:6]}', p, str(r['cmdCode']), r.get('primaryValue'), r.get('netWgt')))
    return out


def fetch(session, ym: str) -> list:
    params = {'reporterCode': '842', 'partnerCode': ','.join(map(str, PARTNERS)), 'flowCode': 'M',
              'cmdCode': ','.join(h for h, _ in BASKET + EXTRA), 'period': ym.replace('-', '')}
    for attempt in range(4):
        try:
            r = session.get(URL, params=params, timeout=90)
        except requests.RequestException:              # 미리보기 서버가 자주 늦다 — 쉬었다 다시
            if attempt == 3:
                raise
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 429 or (r.status_code == 200 and not r.text.strip()):
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise ComtradeError(f'HTTP {r.status_code}: {r.text[:120]}')
        return parse(r.json())
    raise ComtradeError('HTTP 429 (요청이 많다고 막힘)')


def months(a: str, b: str) -> list:
    out, (y, m) = [], (int(a[:4]), int(a[5:]))
    while f'{y}-{m:02d}' <= b:
        out.append(f'{y}-{m:02d}')
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out


def collect(conn, force: bool = False, today: date = None, log=print) -> int:
    today = today or date.today()
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT v FROM meta WHERE k = 'us_refreshed_at'").fetchone()
    if row and row[0][:10] == today.isoformat() and not force:
        log('미국 수입: 오늘 이미 받음')
        return 0
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    end = f'{y}-{m:02d}'
    have = {r[0] for r in conn.execute("SELECT DISTINCT ym FROM us WHERE partner = 'WLD'")}
    recent = set(months(*(lambda ms: (ms[-6], ms[-1]))(months(START, end))))
    todo = [ym for ym in months(START, end) if ym not in have or ym in recent]
    s = requests.Session()
    s.headers['User-Agent'] = 'Mozilla/5.0'
    n = fail = streak = 0
    for ym in sorted(todo, reverse=True):
        try:
            rows = fetch(s, ym)
            streak = 0
        except (ComtradeError, requests.RequestException, ValueError) as e:
            fail += 1
            streak += 1
            log(f'  실패 {ym}: {str(e)[:120]}')
            if streak >= 5:                            # 연속 5번이면 서버 문제 — 다음 실행에서 빠진 달부터 이어 받는다
                break
            continue
        finally:
            time.sleep(PAUSE)
        if rows:
            conn.executemany('INSERT OR REPLACE INTO us VALUES (?,?,?,?,?)', rows)
            conn.commit()
            n += len(rows)
    if not fail:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('us_refreshed_at', ?)", (datetime.now().isoformat(timespec='seconds'),))
    conn.commit()
    log(f'미국 수입: {len(todo)}개월 요청, {n:,}줄, 실패 {fail} · 마지막 달 {conn.execute("SELECT MAX(ym) FROM us").fetchone()[0]}')
    return 1 if fail else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args()
    conn = connect()
    conn.executescript(SCHEMA)
    if a.status:
        r = conn.execute('SELECT COUNT(*), MIN(ym), MAX(ym), COUNT(DISTINCT hs) FROM us').fetchone()
        print(f'us {r[0]:,}줄  {r[1]} ~ {r[2]}  품목 {r[3]}')
        return 0
    return collect(conn, a.force)


if __name__ == '__main__':
    sys.exit(main())
