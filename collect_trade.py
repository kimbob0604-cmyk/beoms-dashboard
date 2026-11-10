"""
소비재 탭 수출 통계 수집: 관세청(공공데이터포털) → db/trade.db

- item          전국 × HS10 월별 수출 금액(달러)·중량(kg)            (15101609, HS4 앞자리로 묶어 부른다)
- item_country  전국 × HS6 × 국가 월별 수출 금액·중량                 (15100475, 국가마다 HS4 앞자리로 → HS6 줄)
- sgg           시군구 × HS6 월별 수출 금액(달러)·건수. 중량은 없다    (15134343, 시도 × HS6 한 쌍씩)

품목·국가 목록은 consumer_hs.json. 키는 config.DATAGO_KEY(.env 의 DATAGO_KEY, 없으면 KBJ 프로젝트 키).
한 번에 12개월까지만 받을 수 있어 해(연도) 단위 창으로 부른다. 지난 해는 한 번 받으면 다시 받지 않고(done 표),
올해 창은 매월 15일경 전월 확정치가 올라오므로 14~21일에 하루 한 번, 그 밖에는 7일에 한 번 다시 받는다(정정 반영).

  python3 collect_trade.py              # 올해 창 갱신 (받을 때가 아니면 건너뜀), 빠진 지난 해 창이 있으면 이어 받음
  python3 collect_trade.py --force      # 올해 창을 지금 다시
  python3 collect_trade.py --status     # 받은 범위
"""

import argparse
import json
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import requests

import config
from collectors import customs as C

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'db' / 'trade.db'
HS_FILE = ROOT / 'consumer_hs.json'
WORKERS = 2          # 동시에 부르는 수. 5 로 올리면 포털이 HTTP 429 로 막는다 (2026-11-10 실측)
PAUSE = 0.15         # 호출 뒤 쉬는 시간(초)
MAX_FAIL = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS item (ym TEXT, hs TEXT, name TEXT, usd REAL, kg REAL, PRIMARY KEY (ym, hs));
CREATE TABLE IF NOT EXISTS item_country (ym TEXT, hs TEXT, country TEXT, usd REAL, kg REAL, PRIMARY KEY (ym, hs, country));
CREATE TABLE IF NOT EXISTS sgg (ym TEXT, sido TEXT, sgg TEXT, hs6 TEXT, usd REAL, cnt REAL, PRIMARY KEY (ym, sido, sgg, hs6));
CREATE INDEX IF NOT EXISTS sgg_hs ON sgg(hs6, sgg);
CREATE TABLE IF NOT EXISTS done (key TEXT PRIMARY KEY, at TEXT, n INTEGER);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path: Path = DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=60)
    conn.executescript(SCHEMA)
    return conn


def load_hs(path: Path = HS_FILE) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def plan(hs: dict) -> dict:
    """품목 사전 → 부를 목록 {hs4: [전국 품목용 앞자리], country_hs: [국가용 앞자리], hs6: [시군구용]}"""
    hs6 = sorted({h for g in hs['groups'] for h in g['hs6']})
    hs10 = sorted({h for g in hs['groups'] for h in g.get('hs10', [])})
    hs4 = sorted({h[:4] for h in hs6})
    return {'hs4': hs4, 'country_hs': hs4 + hs10, 'hs6': hs6}


def windows(year: int, today: date) -> list:
    """그 해의 (시작, 끝) YYYYMM 창. 2026년은 시도 코드 개편(7월) 앞뒤로 나눈다. 아직 오지 않은 달은 뺀다."""
    last = today.year * 100 + today.month
    out = [(f'{year}01', f'{year}06'), (f'{year}07', f'{year}12')] if year == 2026 else [(f'{year}01', f'{year}12')]
    return [(a, min(b, str(last))) for a, b in out if int(a) <= last]


def due(conn, today: date) -> bool:
    """올해 창을 다시 받을 때인가: 14~21일엔 하루 한 번, 그 밖엔 7일에 한 번"""
    row = conn.execute("SELECT v FROM meta WHERE k = 'refreshed_at'").fetchone()
    if not row:
        return True
    last = date.fromisoformat(row[0][:10])
    if last == today:
        return False
    return 14 <= today.day <= 21 or (today - last).days >= 7


def jobs(p: dict, countries: list, start_year: int, today: date) -> list:
    """(key, 종류, 인자) 목록. key 는 done 표의 열쇠"""
    out = []
    for y in range(start_year, today.year + 1):
        for a, b in windows(y, today):
            for h in p['hs4']:
                out.append((f'item|{h}|{a}', y, 'item', (a, b, h)))
            for c in countries:
                for h in p['country_hs']:
                    out.append((f'ic|{c}|{h}|{a}', y, 'ic', (a, b, c, h)))
            for sido in C.sido_for(a, b):
                for h in p['hs6']:
                    out.append((f'sgg|{sido}|{h}|{a}', y, 'sgg', (a, b, sido, h)))
    return out


SQL = {'item': 'INSERT OR REPLACE INTO item VALUES (?,?,?,?,?)',
       'ic': 'INSERT OR REPLACE INTO item_country VALUES (?,?,?,?,?)',
       'sgg': 'INSERT OR REPLACE INTO sgg VALUES (?,?,?,?,?,?)'}
_local = threading.local()


def fetch_job(kind: str, args: tuple) -> list:
    """한 창을 받아 DB 에 넣을 줄(튜플)로 돌려준다. 스레드마다 연결을 따로 쓴다."""
    session = getattr(_local, 's', None)
    if session is None:
        session = _local.s = requests.Session()
    k = config.DATAGO_KEY
    for attempt in range(5):
        try:
            if kind == 'item':
                return [(r['ym'], r['hs'], r['name'], r['usd'], r['kg']) for r in C.fetch_items(session, k, *args)]
            if kind == 'ic':
                return [(r['ym'], r['hs'], r['country'], r['usd'], r['kg']) for r in C.fetch_item_country(session, k, *args)]
            return [(r['ym'], r['sido'], r['sgg'], r['hs6'], r['usd'], r['cnt']) for r in C.fetch_sigungu(session, k, *args)]
        except C.CustomsError as e:
            if 'HTTP 429' not in str(e) or attempt == 4:      # 429 = 너무 빨리 불렀다 → 쉬었다 다시
                raise
            time.sleep(3 * (attempt + 1))
        finally:
            time.sleep(PAUSE)


def collect(conn, force: bool = False, today: date = None, log=print) -> int:
    today = today or date.today()
    hs = load_hs()
    p = plan(hs)
    refresh = force or due(conn, today)
    have = {r[0] for r in conn.execute('SELECT key FROM done')}
    todo = [(key, kind, args) for key, y, kind, args in jobs(p, hs['countries'], hs['start_year'], today)
            if (y == today.year and (refresh or key not in have)) or (y < today.year and key not in have)]
    if not todo:
        log('수출 통계: 받을 것 없음 (올해 창은 14~21일에 하루 한 번, 그 밖엔 7일에 한 번)')
        return 0
    if not config.DATAGO_KEY:
        log('DATAGO_KEY 가 없습니다 (.env 또는 ~/kbj/.env 의 KBJ_DATAGO_KEY). 건너뜁니다.')
        return 4
    todo.sort(key=lambda t: t[2][0], reverse=True)          # 최근 창부터 (중간에 끊겨도 최근 값이 먼저 들어온다)
    n_ok = n_rows = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {}
        it = iter(todo)

        def submit_next():
            for key, kind, args in it:
                futs[pool.submit(fetch_job, kind, args)] = (key, kind)
                return True
            return False

        for _ in range(WORKERS * 2):
            submit_next()
        streak = done_n = 0
        while futs:
            f = next(as_completed(futs))
            key, kind = futs.pop(f)
            done_n += 1
            try:
                rows = f.result()
                conn.executemany(SQL[kind], rows)
                conn.execute('INSERT OR REPLACE INTO done VALUES (?,?,?)', (key, datetime.now().isoformat(timespec='seconds'), len(rows)))
                n_ok += 1
                n_rows += len(rows)
                streak = 0
            except (C.CustomsError, requests.RequestException) as e:
                fail += 1
                streak += 1
                if fail <= 5:
                    log(f'  실패 {key}: {str(e)[:120]}')
            if done_n % 100 == 0:
                conn.commit()
            if done_n % 500 == 0:
                log(f'  {done_n}/{len(todo)} ({time.time() - t0:.0f}초)')
            if streak >= MAX_FAIL:
                log(f'연속 {streak}건 실패 — 중단 (하루 한도이거나 서버 문제). 다음 실행에서 이어 받는다')
                for g in futs:
                    g.cancel()
                break
            submit_next()
    if refresh and not fail:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('refreshed_at', ?)", (datetime.now().isoformat(timespec='seconds'),))
    conn.commit()
    log(f'수출 통계: 호출 {n_ok}/{len(todo)} 성공, {n_rows:,}줄, 실패 {fail} ({time.time() - t0:.0f}초)')
    return 1 if fail else 0


def status(conn):
    for t, col in (('item', 'hs'), ('item_country', 'hs'), ('sgg', 'hs6')):
        r = conn.execute(f'SELECT COUNT(*), MIN(ym), MAX(ym), COUNT(DISTINCT {col}) FROM {t}').fetchone()
        print(f'{t:13s} {r[0]:>9,}줄  {r[1]} ~ {r[2]}  품목 {r[3]}')
    print('done', conn.execute('SELECT COUNT(*) FROM done').fetchone()[0], '창 ·',
          'refreshed_at', (conn.execute("SELECT v FROM meta WHERE k='refreshed_at'").fetchone() or ['–'])[0])


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
