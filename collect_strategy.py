"""
전략 트래커 수집: 증권사 전략 리포트(네이버 리서치 '투자전략')와 텔레그램 공개 채널 글 → db/strategy.db

- 네이버: m.stock.naver.com/api/research/invest 목록에서 추적 시리즈(SERIES)만 골라 담고, 상세의 attachUrl(PDF) 본문을
  .cache/reports/ 에 글자로 남긴다 (bio_reports.pdf_text 재사용).
- 텔레그램: t.me/s/{채널} 공개 미리보기(로그인 없음). 한 페이지 20건, ?before=글번호 로 과거로 넘어간다.
  글 원문은 tgpost 에 그대로 두고(화면에는 싣지 않는다), 주간 리포트 글은 링크된 다올 홈페이지 PDF 를 읽는다.
- 추출: strategy_parse 의 시리즈별 파서로 종목·방향·비중을 pick 에 넣는다.

원문 문장·표는 화면에 옮기지 않는다. 종목 목록·방향 같은 사실과 원문 링크만 쓴다.

  python3 collect_strategy.py            # 새 글만 (네이버 + 텔레그램) + 추출
  python3 collect_strategy.py naver --since 2019-01-01
  python3 collect_strategy.py tg --all   # 채널 처음부터
  python3 collect_strategy.py parse --redo
"""

import argparse
import html
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from bio_reports import pdf_text
import strategy_parse as sp

ROOT = Path(__file__).resolve().parent
STRAT = ROOT / 'db' / 'strategy.db'
UA = {'User-Agent': 'Mozilla/5.0'}
M_API = 'https://m.stock.naver.com/api/research/invest'
CHANNELS = {'bu': 'bottomupquantapproach', 'td': 'toptownquant'}

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc (
  id TEXT PRIMARY KEY, src TEXT, series TEXT, broker TEXT, date TEXT, ts TEXT, title TEXT, url TEXT, pdf TEXT,
  n_pick INTEGER, parsed_at TEXT, err TEXT);
CREATE INDEX IF NOT EXISTS doc_series ON doc(series, date);
CREATE TABLE IF NOT EXISTS pick (
  doc_id TEXT, series TEXT, code TEXT, name TEXT, side TEXT, weight REAL, grp TEXT,
  PRIMARY KEY (doc_id, code, side));
CREATE TABLE IF NOT EXISTS tgpost (ch TEXT, id INTEGER, ts TEXT, text TEXT, links TEXT, PRIMARY KEY (ch, id));
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS nmhist (name TEXT, code TEXT, first TEXT, last TEXT, PRIMARY KEY (name, code));
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(STRAT), timeout=60)
    conn.executescript(SCHEMA)
    return conn


def get(session, url, params=None, tries=3, timeout=25):
    for k in range(tries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(1.5 * (k + 1))
    raise RuntimeError(f'응답 없음: {url}')


# ------------------------------------------------------------
# 네이버 투자전략 리포트
# ------------------------------------------------------------

def collect_naver(conn, since=None, max_pages=450) -> int:
    """목록을 최신부터 훑어 추적 시리즈만 doc 에 넣는다. since 가 없으면 지난번에 본 글 번호까지만."""
    s = requests.Session()
    s.headers.update(UA)
    seen = int((conn.execute("SELECT v FROM meta WHERE k = 'nv_max'").fetchone() or [0])[0])
    top, added = seen, 0
    for page in range(1, max_pages + 1):
        rows = get(s, M_API, {'page': page, 'pageSize': 100}).json()
        if not rows:
            break
        for r in rows:
            rid = int(r['researchId'])
            top = max(top, rid)
            series = sp.naver_series(r.get('brokerName', ''), r.get('title', ''))
            if not series:
                continue
            cur = conn.execute('INSERT OR IGNORE INTO doc (id, src, series, broker, date, title, url) VALUES (?,?,?,?,?,?,?)',
                               (f'nv{rid}', 'naver', series, r['brokerName'], r['writeDate'], r['title'].strip(),
                                f'https://m.stock.naver.com/research/invest/{rid}'))
            added += cur.rowcount
        conn.commit()
        last = rows[-1]
        if since:
            if last['writeDate'] < since:
                break
        elif int(last['researchId']) <= seen:
            break
        time.sleep(0.05)
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('nv_max', ?)", (str(top),))
    # PDF 주소가 없는 글은 상세에서 채운다
    for did, in conn.execute("SELECT id FROM doc WHERE src = 'naver' AND pdf IS NULL").fetchall():
        try:
            c = get(s, f'{M_API}/{did[2:]}').json().get('researchContent') or {}
            conn.execute('UPDATE doc SET pdf = ? WHERE id = ?', (c.get('attachUrl') or '', did))
        except (RuntimeError, ValueError) as e:
            print(f'  상세 실패 {did}: {e}')
        time.sleep(0.05)
    conn.commit()
    print(f'네이버 전략 리포트: 새로 {added}건')
    return added


# ------------------------------------------------------------
# 텔레그램 공개 미리보기
# ------------------------------------------------------------

def parse_tg(page: str) -> list:
    out = []
    for blk in page.split('tgme_widget_message_wrap')[1:]:
        pid = re.search(r'data-post="[^"/]+/(\d+)"', blk)
        ts = re.search(r'<time datetime="([^"]+)"', blk)
        if not pid or not ts:
            continue
        m = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', blk, re.S)
        body = re.sub(r'<[^>]+>', '', html.unescape(re.sub(r'<br\s*/?>', '\n', m.group(1)))) if m else ''
        links = re.findall(r'href="(https?://(?!t\.me)[^"]+)"', blk)
        out.append((int(pid.group(1)), ts.group(1), body, json.dumps(list(dict.fromkeys(links)))))
    return out


def collect_tg(conn, everything=False) -> int:
    s = requests.Session()
    s.headers.update(UA)
    total = 0
    for ch, name in CHANNELS.items():
        have = conn.execute('SELECT MAX(id), MIN(id) FROM tgpost WHERE ch = ?', (ch,)).fetchone()
        newest, oldest = have[0] or 0, have[1] or 0
        before, added = None, 0
        while True:
            posts = parse_tg(get(s, f'https://t.me/s/{name}', {'before': before} if before else None).text)
            if not posts:
                break
            cur = conn.executemany('INSERT OR IGNORE INTO tgpost VALUES (?,?,?,?,?)', [(ch, *p) for p in posts])
            added += cur.rowcount
            conn.commit()
            lo = min(p[0] for p in posts)
            if lo <= 1:
                break
            if not everything and lo <= newest:      # 이미 받은 데까지 왔다
                break
            if everything and oldest and newest and oldest < lo <= newest:
                lo = oldest                          # 받은 구간은 건너뛰고 그 전부터 이어 받는다
            before = lo
            time.sleep(0.35)
        total += added
        print(f'텔레그램 {name}: 새로 {added}건')
    return total


# ------------------------------------------------------------
# 종목명 이력: 옛 글에 나오는 옛 종목명(현대중공업 → HD한국조선해양)을 그 시점의 코드로 바꾸기 위해
# ------------------------------------------------------------

def collect_names(conn, since='2017-01-01') -> int:
    """분기 첫 거래일마다 KRX 전 종목 이름을 받아 nmhist(이름, 코드, 처음·마지막으로 본 날)에 쌓는다"""
    from collect_history import HIST
    from collectors.krx import fetch_daily
    from config import KRX_API_KEY
    hist = sqlite3.connect(f'file:{HIST}?mode=ro', uri=True)
    days = [r[0] for r in hist.execute('SELECT date FROM hday WHERE n > 0 AND date >= ? ORDER BY date', (since,))]
    pick = {}
    for d in days:      # 분기 첫 거래일
        pick.setdefault((d[:4], (int(d[5:7]) - 1) // 3), d)
    want = sorted(set(pick.values()) | {days[-1]})
    done = set(json.loads((conn.execute("SELECT v FROM meta WHERE k = 'nm_dates'").fetchone() or ['[]'])[0]))
    s = requests.Session()
    n = 0
    for d in want:
        if d in done:
            continue
        rows = []
        for market in ('KOSPI', 'KOSDAQ'):
            rows += fetch_daily(s, KRX_API_KEY, d.replace('-', ''), market)
        conn.executemany("""INSERT INTO nmhist VALUES (?,?,?,?) ON CONFLICT(name, code) DO UPDATE SET
                            first = MIN(first, excluded.first), last = MAX(last, excluded.last)""",
                         [(r['name'], r['code'], d, d) for r in rows if r.get('name')])
        done.add(d)
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('nm_dates', ?)", (json.dumps(sorted(done)),))
        conn.commit()
        n += 1
        time.sleep(0.2)
    print(f'종목명 이력: {n}일 추가 · 이름 {conn.execute("SELECT COUNT(*) FROM nmhist").fetchone()[0]}개')
    return n


# ------------------------------------------------------------
# 추출
# ------------------------------------------------------------

def name_rows(conn) -> list:
    """(이름, 코드, 처음 본 날, 마지막으로 본 날)"""
    return conn.execute('SELECT name, code, first, last FROM nmhist').fetchall()


def register_tg_docs(conn):
    """텔레그램 글 가운데 추적 시리즈에 해당하는 글을 doc 으로 올린다 (글 하나 = 문서 하나)"""
    for ch, pid, ts, text, links in conn.execute('SELECT ch, id, ts, text, links FROM tgpost').fetchall():
        series = sp.tg_series(ch, text)
        if not series:
            continue
        kst = sp.to_kst(ts)
        # 주간 리포트 글의 첫 링크가 다올 홈페이지 PDF 로 가는 단축 주소다 (해마다 단축 서비스가 달랐다)
        pdf = next((u for u in json.loads(links) if not re.search(r'youtu|naver\.|t\.me/', u)), '') if series == 'daol_aq' else ''
        conn.execute('INSERT OR IGNORE INTO doc (id, src, series, broker, date, ts, title, url, pdf) VALUES (?,?,?,?,?,?,?,?,?)',
                     (f'tg{ch}{pid}', 'telegram', series, '다올투자증권', kst[:10], kst, sp.first_line(text),
                      f'https://t.me/{CHANNELS[ch]}/{pid}', pdf))
    conn.commit()


def parse_docs(conn, redo=False) -> int:
    names = sp.NameIndex(name_rows(conn))
    register_tg_docs(conn)
    where = '' if redo else 'WHERE parsed_at IS NULL'
    docs = conn.execute(f'SELECT id, src, series, date, title, pdf FROM doc {where} ORDER BY date').fetchall()
    done = 0
    for did, src, series, date, title, pdf in docs:
        err, picks = None, []
        try:
            if src == 'telegram' and series != 'daol_aq':
                ch, pid = did[2:4], int(did[4:])
                text = conn.execute('SELECT text FROM tgpost WHERE ch = ? AND id = ?', (ch, pid)).fetchone()[0]
            elif pdf:
                text = pdf_text(pdf, f'st_{did}')
            else:
                text, err = '', 'PDF 없음'
            if text:
                picks = sp.PARSERS[series](text, names, date)
            elif not err:
                err = '본문 글자 없음'
        except Exception as e:      # 받기·읽기 실패는 기록만 하고 다음으로
            err = f'{type(e).__name__}: {e}'[:200]
        conn.execute('DELETE FROM pick WHERE doc_id = ?', (did,))
        conn.executemany('INSERT OR REPLACE INTO pick VALUES (?,?,?,?,?,?,?)',
                         [(did, series, p['code'], p['name'], p['side'], p.get('weight'), p.get('grp')) for p in picks])
        # 받기 실패(네트워크)는 다음 실행에서 다시 해 본다
        fresh = (datetime.now() - datetime.fromisoformat(date)).days <= 14
        retry = fresh and err and err.startswith(('ConnectionError', 'ReadTimeout', 'HTTPError', 'RuntimeError', 'SSLError'))
        conn.execute('UPDATE doc SET n_pick = ?, parsed_at = ?, err = ? WHERE id = ?',
                     (len(picks), None if retry else datetime.now().isoformat(timespec='seconds'), err, did))
        done += 1
        if done % 50 == 0:
            conn.commit()
            print(f'  추출 {done}/{len(docs)}')
    conn.commit()
    for series, n, np_, ne in conn.execute(
            'SELECT series, COUNT(*), SUM(n_pick > 0), SUM(err IS NOT NULL) FROM doc GROUP BY series'):
        print(f'  {series}: 문서 {n} · 종목 추출 {np_ or 0} · 오류 {ne or 0}')
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', nargs='?', default='all', choices=['all', 'naver', 'tg', 'names', 'parse'])
    ap.add_argument('--since')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--redo', action='store_true')
    a = ap.parse_args()
    conn = connect()
    code = 0
    if a.cmd in ('all', 'naver'):
        try:
            collect_naver(conn, since=a.since)
        except RuntimeError as e:
            print('네이버 실패:', e)
            code = 3
    if a.cmd in ('all', 'tg'):
        try:
            collect_tg(conn, everything=a.all)
        except RuntimeError as e:
            print('텔레그램 실패:', e)
            code = 3
    if a.cmd in ('all', 'names'):
        try:
            collect_names(conn)
        except Exception as e:      # KRX 가 막혀도 추출은 지난 이름표로 한다
            print('종목명 이력 실패:', type(e).__name__)
    if a.cmd in ('all', 'parse'):
        parse_docs(conn, redo=a.redo)
    return code


if __name__ == '__main__':
    sys.exit(main())
