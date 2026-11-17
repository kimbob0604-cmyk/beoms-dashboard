"""
@DOC_POOL 리포트 글 수집: 텔레그램 공개 채널 DOC_POOL 의 리포트 글(요약 머리글 + 첨부 파일 이름) → db/docpool.db

이 채널은 웹 미리보기(t.me/s/)가 막혀 있어 본인 계정 로그인(Telethon)으로만 읽힌다. 탐방 노트와 같은 로그인
(db/tg_user.session, collect_visits.py login)을 그대로 쓴다. 읽기만 하고, PDF 는 내려받지 않는다 (파일 이름·크기만 적는다).

  python3 collect_docpool.py                # 새 글만 — 마지막으로 본 글 번호 뒤부터 (처음이면 최근 92일)
  python3 collect_docpool.py --days 180     # 더 과거까지 넓혀 받기 (이미 받은 구간은 건너뛴다)
  python3 collect_docpool.py status         # 받은 범위·건수

글은 두 가지 꼴로 올라온다: ① PDF 한 글에 요약이 같이 붙은 것, ② PDF 글 뒤에 그 글의 답글로 요약을 단 것.
②는 답글의 요약을 PDF 글 행에 합쳐 리포트 하나가 한 행이 되게 한다. 리포트마다 따라붙는 미리보기 사진 3장과
광고 글은 담지 않는다.

종료 코드: 0 정상 · 3 텔레그램 연결·요청 제한으로 중단(다음 실행에서 이어 받음) · 4 키·로그인 없음(daily.py 는 문제로 치지 않는다)
"""

import argparse
import asyncio
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config  # noqa: F401  (.env → 환경변수)
import docpool as D

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'db' / 'docpool.db'
CHANNEL = 'DOC_POOL'
KST = timezone(timedelta(hours=9))
FIRST_DAYS = 92        # 처음 받을 때 거슬러 갈 날 수 (약 3개월)
BATCH = 200
EXIT_STOPPED, EXIT_SETUP = 3, 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS post (
  id INTEGER PRIMARY KEY,     -- 글 번호 (PDF 글이 있으면 그 번호 → https://t.me/DOC_POOL/{id})
  ts TEXT NOT NULL,           -- 올라온 시각 KST 'YYYY-MM-DDTHH:MM:SS'
  file TEXT,                  -- 첨부 파일 이름 (파일 자체는 받지 않는다)
  size INTEGER,
  text TEXT,                  -- 채널이 붙인 요약 글 (이 컴퓨터에만 둔다. 화면·공개 파일에는 머리글의 목록 정보만)
  text_id INTEGER,            -- 요약이 답글로 따로 올라왔으면 그 글 번호
  fetched_at TEXT);
CREATE INDEX IF NOT EXISTS post_ts ON post(ts);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path: Path = DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_meta(conn, k):
    r = conn.execute('SELECT v FROM meta WHERE k = ?', (k,)).fetchone()
    return r[0] if r else None


def set_meta(conn, k, v):
    conn.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', (k, str(v)))


def meta_int(conn, k):
    v = get_meta(conn, k)
    return int(v) if v not in (None, '') else None


def save(conn, raws) -> int:
    """raws: {id, ts, text, file, size, reply_to} 목록 → 새로 담긴 리포트 수. 같은 글을 다시 넣어도 늘지 않는다.
    - 파일이 있는 글: 한 행. 이미 있으면 비어 있던 요약만 채운다
    - 파일 없는 글이 PDF 글의 답글이면: 그 행의 요약으로 합친다 (이미 요약이 있으면 그대로 둔다)
    - 파일도 답글 대상도 없는 글: 리포트 요약 꼴('제목:' 줄)일 때만 한 행. 광고·공지는 버린다"""
    now = datetime.now().isoformat(timespec='seconds')
    added = 0
    for r in sorted(raws, key=lambda r: r['id']):      # 답글이 PDF 글보다 뒤에 처리되도록
        text = (r.get('text') or '').strip()
        if r.get('file'):
            cur = conn.execute('INSERT OR IGNORE INTO post VALUES (?,?,?,?,?,?,?)',
                               (r['id'], r['ts'], r['file'], r.get('size'), text, None, now))
            if cur.rowcount:
                added += 1
            elif text:
                conn.execute("UPDATE post SET text = ? WHERE id = ? AND COALESCE(text, '') = ''", (text, r['id']))
            continue
        if not text:
            continue
        parent = r.get('reply_to')
        if parent and conn.execute('SELECT 1 FROM post WHERE id = ?', (parent,)).fetchone():
            conn.execute("UPDATE post SET text = ?, text_id = ? WHERE id = ? AND COALESCE(text, '') = ''",
                         (text, r['id'], parent))
            continue
        if D.is_report(text):
            cur = conn.execute('INSERT OR IGNORE INTO post VALUES (?,?,?,?,?,?,?)',
                               (r['id'], r['ts'], '', None, text, None, now))
            added += cur.rowcount
    conn.commit()
    return added


def raw_of(m):
    """Telethon 글 → save 가 받는 꼴. 사진·빈 글은 None"""
    doc = getattr(m, 'document', None)
    name = (getattr(m.file, 'name', None) or '') if (doc is not None and m.file) else ''
    text = m.message or ''
    if not name and not text:
        return None
    return {'id': m.id, 'ts': m.date.astimezone(KST).strftime('%Y-%m-%dT%H:%M:%S'), 'text': text, 'file': name,
            'size': getattr(m.file, 'size', None) if name else None,
            'reply_to': getattr(m.reply_to, 'reply_to_msg_id', None) if m.reply_to else None}


async def _collect(conn, days) -> int:
    from collect_visits import SESSION, client      # 탐방 노트와 같은 로그인 (읽기·import 만)
    from telethon.errors import FloodWaitError
    cl = client()
    if cl is None or not SESSION.exists():
        print('텔레그램 설정 전입니다 (.env 의 TG_API_ID·TG_API_HASH, 그리고 collect_visits.py login). 건너뜁니다.')
        return EXIT_SETUP
    await cl.connect()
    try:
        if not await cl.is_user_authorized():
            print('텔레그램 로그인이 안 돼 있습니다:  python3 collect_visits.py login  (본인이 직접)')
            return EXIT_SETUP
        ent = await cl.get_entity(CHANNEL)
        first, last = meta_int(conn, 'first_id'), meta_int(conn, 'last_id')
        edge = None
        if last is None or days:      # 처음이거나 더 과거로 넓힐 때만 기준일 앞 글 번호를 묻는다
            cut = D.cutoff_kst(days or FIRST_DAYS).replace(tzinfo=KST)
            async for m in cl.iter_messages(ent, limit=1, offset_date=cut):
                edge = m.id
            edge = edge or 0
            if last is None:
                set_meta(conn, 'first_id', edge)
                set_meta(conn, 'since', cut.strftime('%Y-%m-%d'))
                conn.commit()
        seen = added = 0
        for lo, hi in D.fetch_ranges(first, last, edge):
            forward = hi is None
            batch, top = [], lo
            # 오래된 글 → 새 글 순서 (PDF 글이 그 답글보다 먼저 온다). 글이 많으면 요청 사이에 1초씩 쉰다
            async for m in cl.iter_messages(ent, min_id=lo, max_id=hi or 0, reverse=True, wait_time=1):
                seen += 1
                top = m.id
                r = raw_of(m)
                if r:
                    batch.append(r)
                if len(batch) >= BATCH:
                    added += save(conn, batch)
                    batch = []
                    if forward:
                        set_meta(conn, 'last_id', top)      # 끊겨도 여기서부터 이어 받는다
                        conn.commit()
                    print(f'  … 글 {seen}건 훑음, 리포트 {added}건 ({r["ts"][:16] if r else ""} 까지)', flush=True)
            added += save(conn, batch)
            if forward:
                set_meta(conn, 'last_id', max(top, last or 0))
            else:
                set_meta(conn, 'first_id', lo)
                set_meta(conn, 'since', D.cutoff_kst(days).strftime('%Y-%m-%d'))
            conn.commit()
    except FloodWaitError as e:
        print(f'텔레그램 요청 제한: {e.seconds}초 뒤에 다시 받을 수 있습니다. 받은 데까지 저장하고 멈춥니다.')
        return EXIT_STOPPED
    finally:
        await cl.disconnect()
    set_meta(conn, 'collected_at', datetime.now().isoformat(timespec='seconds'))
    conn.commit()
    n, lo_ts, hi_ts = conn.execute('SELECT COUNT(*), MIN(ts), MAX(ts) FROM post').fetchone()
    print(f'@DOC_POOL: 글 {seen}건 훑음, 새 리포트 {added}건 · 모두 {n}건' + (f' ({lo_ts[:10]} ~ {hi_ts[:16]})' if n else ''))
    return 0


def collect(days=None, tries=4) -> int:
    conn = connect()
    for i in range(tries):
        try:
            return asyncio.run(_collect(conn, days))
        except sqlite3.OperationalError as e:
            # 로그인 파일(db/tg_user.session)을 다른 수집(탐방·실적 글)이 쓰는 중이면 잠긴다 → 조금 기다렸다 이어서
            if 'locked' not in str(e) or i == tries - 1:
                print(f'DB 오류: {e}')
                return EXIT_STOPPED
            print(f'로그인 파일이 다른 수집에 잠겨 있음 — 30초 뒤 다시 ({i + 1}/{tries - 1})', flush=True)
            time.sleep(30)
        except (OSError, ConnectionError, asyncio.TimeoutError) as e:
            print(f'텔레그램 연결 실패: {e}')
            return EXIT_STOPPED
    return EXIT_STOPPED


def status() -> int:
    conn = connect()
    n, lo, hi = conn.execute('SELECT COUNT(*), MIN(ts), MAX(ts) FROM post').fetchone()
    if not n:
        print('받은 글이 없습니다.')
        return 0
    print(f"리포트 {n}건, {lo[:16]} ~ {hi[:16]} · 훑은 글 번호 {get_meta(conn, 'first_id')} 초과 ~ {get_meta(conn, 'last_id')} · "
          f"마지막 수집 {get_meta(conn, 'collected_at')}")
    for mon, k, f, t in conn.execute("SELECT substr(ts, 1, 7), COUNT(*), SUM(file != ''), SUM(COALESCE(text, '') != '') "
                                     'FROM post GROUP BY 1 ORDER BY 1'):
        print(f'  {mon}: {k}건 (PDF {f}, 요약 글 {t})')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', nargs='?', default='collect', choices=['collect', 'status'])
    ap.add_argument('--days', type=int, help='오늘에서 이만큼 전까지 거슬러 받는다')
    a = ap.parse_args()
    if a.cmd == 'status':
        return status()
    try:
        import telethon  # noqa: F401
    except ImportError:
        print('telethon 이 없습니다:  pip3 install telethon')
        return EXIT_SETUP
    return collect(a.days)


if __name__ == '__main__':
    sys.exit(main())
