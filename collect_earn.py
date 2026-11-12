"""
실적 발표 덱 수집 → db/earn.db

  python3 collect_earn.py posts            # @darthacking 의 실적 글 (처음엔 2021년부터 전부, 이후엔 새 글만)
  python3 collect_earn.py minutes          # 최근 1년 실적 발표의 분봉 (KIS 통합 1분봉, 이미 받은 날은 건너뜀)
  python3 collect_earn.py minutes --today  # 오늘 발표한 종목만 다시 (장중 갱신용)
  python3 collect_earn.py all

글: 사용자 텔레그램 계정(db/tg_user.session)으로 공개 채널 @darthacking 을 '예상치' 로 서버 검색한다 — 실적 글에만 이 낱말이 있다.
원문은 저장하지 않고 파싱한 숫자만 남긴다. 세션이 없으면 4로 끝난다.
분봉: 발표일 08:00~20:00, 장후 발표면 다음 거래일 08:00~15:30 도. 예상치가 있는(비교 가능한) 발표만.

종료 코드: 0 정상, 1 일부 실패, 3 서버 응답 없음, 4 로그인·키 없음
"""

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

import config  # noqa: F401
import earn
from collectors import kis

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'db' / 'earn.db'
HIST = ROOT / 'db' / 'history.db'
MAIN = ROOT / 'db' / 'dashboard.db'
CHANNEL = 'darthacking'
SINCE = '2021-01-01'
MINUTE_DAYS = 360          # KIS 과거 분봉은 약 1년
log = logging.getLogger('collect_earn')

SCHEMA = """
CREATE TABLE IF NOT EXISTS earn_post (
    id      INTEGER PRIMARY KEY,   -- 채널 글 번호
    ts      TEXT NOT NULL,         -- 채널이 공시를 잡은 시각 (KST, 초)
    code    TEXT, name TEXT, mcap REAL,
    report  TEXT, prelim TEXT, period TEXT, rcp TEXT,
    s REAL, se REAL, o REAL, oe REAL, n REAL, ne REAL   -- 매출·영업이익·순이익 실제/예상 (억원)
);
CREATE INDEX IF NOT EXISTS earn_post_code ON earn_post (code, ts);
CREATE TABLE IF NOT EXISTS minute_day (
    code TEXT NOT NULL, date TEXT NOT NULL,
    bars TEXT NOT NULL,            -- [[HHMM, 종가, 거래량]…] 통합(KRX+넥스트레이드)
    done INTEGER NOT NULL,         -- 그날이 끝난 뒤 받았으면 1 (아니면 다시 받는다)
    at TEXT,
    mk TEXT,                       -- 받은 시장 UN(통합) / J(KRX — 넥스트레이드에 없는 종목)
    PRIMARY KEY (code, date)
);
"""


def connect(path=DB):
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if 'mk' not in {r[1] for r in conn.execute('PRAGMA table_info(minute_day)')}:
        conn.execute('ALTER TABLE minute_day ADD COLUMN mk TEXT')
    return conn


NAMES_CACHE = ROOT / '.cache' / 'dart_names.json'


def dart_names() -> dict:
    """DART 회사 목록의 정식 이름 → 종목코드 (현대자동차·케이티앤지·엘에스일렉트릭 꼴). 7일 캐시"""
    import io
    import os
    import re
    import time
    import zipfile
    if NAMES_CACHE.exists() and time.time() - NAMES_CACHE.stat().st_mtime < 7 * 86400:
        return json.loads(NAMES_CACHE.read_text(encoding='utf-8'))
    key = os.environ.get('DART_API_KEY', '')
    if not key:
        return {}
    try:
        r = requests.get('https://opendart.fss.or.kr/api/corpCode.xml', params={'crtfc_key': key}, timeout=60)
        xml = zipfile.ZipFile(io.BytesIO(r.content)).read('CORPCODE.xml').decode('utf-8')
    except (requests.RequestException, zipfile.BadZipFile, KeyError) as e:
        log.warning('DART 회사 목록 실패: %s', e)
        return {}
    out = {}
    for block in xml.split('<list>')[1:]:
        nm = re.search(r'<corp_name>(.*?)</corp_name>', block)
        st = re.search(r'<stock_code>\s*(\w{6})\s*</stock_code>', block)
        if nm and st:
            out[nm.group(1).strip()] = st.group(1)
    NAMES_CACHE.parent.mkdir(exist_ok=True)
    NAMES_CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    return out


def name_codes() -> dict:
    """옛 형식 글(종목코드 없음)용 이름 → 코드. 거래소 이름(hname, 겹치면 최근 것)이 먼저, 없으면 DART 정식 이름"""
    out = dict(dart_names())
    if HIST.exists():
        for code, name in sqlite3.connect(f'file:{HIST}?mode=ro', uri=True).execute('SELECT code, name FROM hname ORDER BY last'):
            out[name] = code
    return out


def fill_codes(conn) -> int:
    """코드 없이 저장된 글에 이름으로 코드를 채운다 (이름 표가 나중에 늘어난 경우)"""
    names = name_codes()
    rows = [(names[n], i) for i, n in conn.execute('SELECT id, name FROM earn_post WHERE code IS NULL AND name IS NOT NULL') if n in names]
    with conn:
        conn.executemany('UPDATE earn_post SET code = ? WHERE id = ?', rows)
    return len(rows)


# ---------------- 글 ----------------

async def _posts(conn, min_id: int, before=None) -> int:
    from collect_visits import client
    c = client()
    if c is None:
        return -4
    await c.connect()
    try:
        if not await c.is_user_authorized():
            return -4
        ent = await c.get_entity(CHANNEL)
        names = name_codes()
        rows, seen = [], 0
        async for m in c.iter_messages(ent, search='예상치', min_id=min_id, offset_date=before):
            seen += 1
            if m.date.year < int(SINCE[:4]):
                break
            kst = (m.date + timedelta(hours=9)).replace(tzinfo=None)
            p = earn.parse_post(m.message or '', kst)
            if not p:
                continue
            if not p['code'] and p['name']:
                p['code'] = names.get(p['name'])
            rows.append((m.id, p['ts'], p['code'], p['name'], p['mcap'], p['report'], p['prelim'], p['period'], p['rcp'],
                         p['s'], p['se'], p['o'], p['oe'], p['n'], p['ne']))
            if len(rows) >= 500:
                save_posts(conn, rows)
                log.info('  글 %d개 저장 (%s 까지)', len(rows), p['ts'][:10])
                rows = []
        save_posts(conn, rows)
        return seen
    finally:
        await c.disconnect()


def save_posts(conn, rows):
    with conn:
        conn.executemany('INSERT OR REPLACE INTO earn_post VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)


def collect_posts(conn) -> int:
    """새 글(마지막 id 뒤) → 그다음 아직 2021년까지 못 내려갔으면 가장 오래된 글 앞으로 더 (검색은 한 번에 1만 개까지)"""
    try:
        min_id = conn.execute('SELECT COALESCE(MAX(id), 0) FROM earn_post').fetchone()[0]
        seen = asyncio.run(_posts(conn, min_id))
        while seen != -4:
            ots = conn.execute('SELECT MIN(ts) FROM earn_post').fetchone()[0]
            if not ots or ots[:10] <= SINCE[:4] + '-02-20':      # 채널 첫 글 2021-02-17
                break
            # 검색 결과는 1만 개까지라, 가장 오래된 글 시각(KST → UTC) 앞부터 다시
            before = datetime.fromisoformat(ots).replace(tzinfo=timezone.utc) - timedelta(hours=9)
            more = asyncio.run(_posts(conn, 0, before))
            log.info('  더 오래된 글 %d개 (%s 까지)', more, conn.execute('SELECT MIN(ts) FROM earn_post').fetchone()[0][:10])
            if more <= 0:
                break
    except (OSError, ConnectionError) as e:
        log.error('텔레그램 연결 실패: %s', e)
        return 3
    if seen == -4:
        log.info('텔레그램 로그인 없음 — 건너뜀')
        return 4
    filled = fill_codes(conn)
    n, miss = conn.execute('SELECT COUNT(*), SUM(code IS NULL AND (se IS NOT NULL OR oe IS NOT NULL)) FROM earn_post').fetchone()
    log.info('실적 글: 전체 %d (이름으로 코드 채움 %d, 예상치 있는데 코드 모름 %d)', n, filled, miss or 0)
    return 0


# ---------------- 분봉 ----------------

def trading_days() -> list:
    """거래일 목록: history.db hday + dashboard.db 최근 가격일 + (그 뒤 오늘까지) 평일"""
    days = set()
    if HIST.exists():
        days |= {r[0] for r in sqlite3.connect(f'file:{HIST}?mode=ro', uri=True).execute('SELECT date FROM hday WHERE date >= ?', (SINCE,))}
    if MAIN.exists():
        days |= {r[0] for r in sqlite3.connect(f'file:{MAIN}?mode=ro', uri=True).execute(
            'SELECT DISTINCT date FROM ohlc_daily WHERE date >= ?', ((date.today() - timedelta(days=30)).isoformat(),))}
    last = max(days) if days else SINCE
    d = date.fromisoformat(last) + timedelta(days=1)
    while d <= date.today() + timedelta(days=7):      # 아직 확정 전인 날·다음 주는 평일로 둔다 (휴장일이면 분봉이 비어 있다)
        if d.weekday() < 5:
            days.add(d.isoformat())
        d += timedelta(days=1)
    return sorted(days)


def events(conn, days, since: str):
    """분봉이 필요한 (종목, 날짜) — 예상치가 있는 첫 발표만"""
    need = set()
    for r in conn.execute('SELECT * FROM earn_post WHERE ts >= ? AND code IS NOT NULL AND (se IS NOT NULL OR oe IS NOT NULL)', (since,)):
        p = dict(r)
        if earn.first_release(p) is False:
            continue
        d0, ss = earn.reaction_day(p['ts'], days)
        day = p['ts'][:10]
        if day in days:
            need.add((p['code'], day))
        if d0 and d0 != day:
            need.add((p['code'], d0))
    return need


def collect_minutes(conn, today_only=False) -> int:
    days = trading_days()
    today = date.today().isoformat()
    since = today if today_only else (date.today() - timedelta(days=MINUTE_DAYS)).isoformat()
    need = {(c, d) for c, d in events(conn, days, since) if d <= today}
    have = {(r[0], r[1]) for r in conn.execute('SELECT code, date FROM minute_day WHERE done = 1')}
    old = {(r[0], r[1]): (json.loads(r[2]), r[3]) for r in conn.execute(
        'SELECT code, date, bars, mk FROM minute_day WHERE done = 0 AND date = ?', (today,))}
    todo = sorted(need - have, key=lambda x: (x[1], x[0]), reverse=True)
    log.info('분봉: 필요 %d · 받을 %d', len(need), len(todo))
    if not todo:
        return 0
    if not all(kis.keys()):
        log.info('KIS 키 없음 — 건너뜀')
        return 4
    s = requests.Session()
    try:
        tok = kis.token(s)
    except (requests.RequestException, kis.KisError) as e:
        log.error('KIS 토큰 실패: %s', e)
        return 3
    errors = fails = 0
    now = datetime.now()
    for i, (code, d) in enumerate(todo, 1):
        try:
            if d == today:      # 오늘은 당일분봉 API (가진 마지막 분 뒤만 더 받는다)
                prev, mk = old.get((code, d)) or ([], '')
                end = min('2000', now.strftime('%H%M'))
                new, mk = kis.minute_today(s, tok, code, end=end, since=prev[-1][0] if prev and mk else '', market=mk if prev else '')
                bars = sorted({b[0]: b for b in prev + new}.values())
                done = int(now.strftime('%H%M') >= '2005')
            else:
                bars, mk = kis.minute_day(s, tok, code, d.replace('-', ''))
                done = 1
            with conn:
                conn.execute('INSERT OR REPLACE INTO minute_day (code, date, bars, done, at, mk) VALUES (?, ?, ?, ?, ?, ?)',
                             (code, d, json.dumps(bars, separators=(',', ':')), done, now.isoformat(timespec='seconds'), mk))
            fails = 0
        except requests.RequestException as e:
            errors += 1
            fails += 1
            log.warning('%s %s 네트워크 실패: %s', code, d, e)
            if fails >= 5:
                return 3
        except kis.KisError as e:
            errors += 1
            log.warning('%s', e)
        if i % 200 == 0:
            log.info('  %d/%d', i, len(todo))
    log.info('분봉 완료: %d건, 오류 %d', len(todo), errors)
    return 1 if errors > max(10, len(todo) // 10) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description='실적 발표 덱 수집 (@darthacking 글 · KIS 분봉)')
    ap.add_argument('what', choices=['posts', 'minutes', 'all'])
    ap.add_argument('--today', action='store_true', help='minutes: 오늘 발표만')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    conn = connect()
    codes = []
    if args.what in ('posts', 'all'):
        codes.append(collect_posts(conn))
    if args.what in ('minutes', 'all'):
        codes.append(collect_minutes(conn, args.today))
    real = [c for c in codes if c != 4]
    if not real:
        return 4
    return 3 if 3 in real else 1 if 1 in real else 0

if __name__ == '__main__':
    sys.exit(main())
