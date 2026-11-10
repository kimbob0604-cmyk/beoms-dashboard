"""
탐방 노트 수집: 내 텔레그램 계정이 들어가 있는 방에서 '탐방'이 들어간 글 → db/visits.db

공개 미리보기(t.me/s/)로는 비공개 방을 읽을 수 없어서, 본인 계정으로 로그인한 클라이언트(Telethon)를 쓴다.
읽기만 한다 (검색·글 읽기). 글을 보내거나 읽음 표시를 바꾸지 않는다.

준비 (한 번):
  1) https://my.telegram.org → API development tools 에서 api_id·api_hash 발급
  2) .env 에  TG_API_ID=…  TG_API_HASH=…  두 줄
  3) python3 collect_visits.py login     # 전화번호 → 텔레그램으로 온 코드 → (있으면) 2단계 비밀번호. 본인이 직접 입력
     로그인 정보는 db/tg_user.session 에 남는다. 이 파일은 계정 열쇠라서 git·배포에 넣지 않는다(.gitignore).

  python3 collect_visits.py                    # 새 글만 (처음이면 최근 365일)
  python3 collect_visits.py --days 1095        # 최근 3년까지 거슬러 받기
  python3 collect_visits.py --all              # 처음부터 전부
  python3 collect_visits.py rooms              # 글이 잡힌 방과 건수
  python3 collect_visits.py scan "방 이름"      # 그 방의 글을 통째로 훑어 '탐방'이 든 글을 담는다 (검색이 놓친 글 보충)
  python3 collect_visits.py import result.json # 텔레그램 데스크톱 '채팅 기록 내보내기'(JSON) 파일에서 담기 (API 없이)
  python3 collect_visits.py logout             # 이 컴퓨터의 로그인 정보 지우기
  python3 collect_visits.py --topic concall    # 같은 방식으로 컨콜(실적 발표 컨퍼런스콜) 노트 → db/concall.db (소비재 탭이 쓴다)

텔레그램 검색은 낱말 앞부분으로 찾는다. '탐방'은 '탐방노트'는 찾지만 '기업탐방'은 못 찾으므로 KEYWORDS 를 여러 개 둔다.
담을 때는 본문에 '탐방'이 실제로 있는 글만 남긴다.
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config  # noqa: F401  (.env → 환경변수)

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'db' / 'visits.db'
SESSION = ROOT / 'db' / 'tg_user.session'
KST = timezone(timedelta(hours=9))
KEYWORDS = [k.strip() for k in os.environ.get('TG_KEYWORDS', '탐방,기업탐방,탐방노트,탐방후기,회사탐방').split(',') if k.strip()]
MUST = ('탐방',)       # 본문에 이 가운데 하나는 있어야 담는다
# 주제별 설정: 검색어(텔레그램은 낱말 앞부분으로 찾는다) · 본문 필수 낱말 · 저장 DB
TOPICS = {
    'visit': {'keywords': KEYWORDS, 'must': MUST, 'db': DB},
    'concall': {'keywords': ['컨콜', '컨퍼런스콜', '컨퍼런스', '콘퍼런스콜', '어닝콜', '실적발표회'],
                'must': ('컨콜', '컨퍼런스콜', '컨퍼런스 콜', '콘퍼런스콜', '콘퍼런스 콜', '어닝콜', '어닝스콜', '실적발표회',
                         'Conference Call', 'conference call', 'Earnings Call', 'earnings call'),
                'db': ROOT / 'db' / 'concall.db'},
}
FIRST_DAYS = 365
OVERLAP_DAYS = 3       # 새 글만 받을 때도 마지막으로 받은 날의 며칠 전부터 다시 본다 (늦게 고친 글·전달 글)
EXIT_SETUP = 4         # 키·로그인 없음 (daily.py 는 이 코드를 문제로 치지 않는다)

SCHEMA = """
CREATE TABLE IF NOT EXISTS msg (
  chat_id INTEGER, id INTEGER, chat TEXT, chat_user TEXT, date TEXT, sender TEXT, fwd TEXT, text TEXT, link TEXT,
  file TEXT, src TEXT, fetched_at TEXT, PRIMARY KEY (chat_id, id));
CREATE INDEX IF NOT EXISTS msg_date ON msg(date);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path: Path = DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=60)
    conn.executescript(SCHEMA)
    return conn


def save(conn, rows, must=MUST) -> int:
    """rows: dict 목록. 이미 있는 글은 본문·방 이름만 고친다(수정된 글). 새로 담긴 수를 돌려준다."""
    now = datetime.now().isoformat(timespec='seconds')
    added = 0
    for r in rows:
        if not r.get('text') or not any(m in r['text'] for m in must):
            continue
        cur = conn.execute('INSERT OR IGNORE INTO msg VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (r['chat_id'], r['id'], r.get('chat') or '', r.get('chat_user') or '', r['date'],
                            r.get('sender') or '', r.get('fwd') or '', r['text'], r.get('link') or '',
                            r.get('file') or '', r.get('src') or 'tg', now))
        if cur.rowcount:
            added += 1
        else:
            conn.execute('UPDATE msg SET text = ?, chat = ? WHERE chat_id = ? AND id = ?',
                         (r['text'], r.get('chat') or '', r['chat_id'], r['id']))
    conn.commit()
    return added


# ------------------------------------------------------------
# 텔레그램 (Telethon)
# ------------------------------------------------------------

def api_keys():
    api_id, api_hash = os.environ.get('TG_API_ID', ''), os.environ.get('TG_API_HASH', '')
    if not api_id.isdigit() or not api_hash:
        return None
    return int(api_id), api_hash


def client():
    from telethon import TelegramClient
    keys = api_keys()
    if not keys:
        return None
    return TelegramClient(str(SESSION), *keys, receive_updates=False, device_model="Beom's Dashboard",
                          lang_code='ko', system_lang_code='ko')


def name_of(ent) -> str:
    if ent is None:
        return ''
    t = getattr(ent, 'title', None)
    if t:
        return t
    return ' '.join(x for x in (getattr(ent, 'first_name', None), getattr(ent, 'last_name', None)) if x)


def link_of(chat, mid: int) -> str:
    """공개 방은 t.me/이름/글번호, 비공개 채널·슈퍼그룹은 t.me/c/번호/글번호 (그 방에 들어가 있는 계정만 열린다)"""
    user = getattr(chat, 'username', None)
    if user:
        return f'https://t.me/{user}/{mid}'
    if type(chat).__name__ == 'Channel':
        return f'https://t.me/c/{chat.id}/{mid}'
    return ''


def row_of(m) -> dict:
    chat = m.chat
    fwd = m.forward
    origin = ''
    if fwd is not None:
        origin = name_of(getattr(fwd, 'chat', None)) or name_of(getattr(fwd, 'sender', None)) or (getattr(fwd, 'from_name', None) or '')
    return {
        'chat_id': m.chat_id, 'id': m.id, 'chat': name_of(chat), 'chat_user': getattr(chat, 'username', None) or '',
        'date': m.date.astimezone(KST).strftime('%Y-%m-%dT%H:%M:%S'), 'sender': name_of(m.sender), 'fwd': origin,
        'text': m.message or '', 'link': link_of(chat, m.id),
        'file': (getattr(m.file, 'name', None) or '') if m.file else '', 'src': 'tg',
    }


async def ready(cl) -> bool:
    await cl.connect()
    if await cl.is_user_authorized():
        return True
    print('텔레그램 로그인이 안 돼 있습니다:  python3 collect_visits.py login')
    return False


async def do_login() -> int:
    from getpass import getpass
    cl = client()
    if cl is None:
        print('.env 에 TG_API_ID, TG_API_HASH 가 없습니다. https://my.telegram.org → API development tools 에서 발급해 넣으세요.')
        return EXIT_SETUP
    await cl.start(phone=lambda: input('전화번호 (+8210…): ').strip(),
                   code_callback=lambda: input('텔레그램 앱으로 온 로그인 코드: ').strip(),
                   password=lambda: getpass('2단계 인증 비밀번호 (화면에 안 보임): '))
    me = await cl.get_me()
    await cl.disconnect()
    for f in SESSION.parent.glob(SESSION.name + '*'):
        f.chmod(0o600)
    print(f'로그인 완료: {name_of(me)}. 이제  python3 collect_visits.py  로 받습니다.')
    return 0


async def do_logout() -> int:
    cl = client()
    if cl is not None and SESSION.exists():
        await cl.connect()
        if await cl.is_user_authorized():
            await cl.log_out()          # 텔레그램 쪽 세션도 끊는다 (설정 > 기기 목록에서 사라짐)
        else:
            await cl.disconnect()
    for f in SESSION.parent.glob(SESSION.name + '*'):
        f.unlink()
    print('로그인 정보를 지웠습니다.')
    return 0


async def do_collect(days, everything: bool, topic: str = 'visit') -> int:
    cfg = TOPICS[topic]
    cl = client()
    if cl is None or not SESSION.exists():
        print('텔레그램 설정 전입니다 (.env 의 TG_API_ID·TG_API_HASH, 그리고 login). 건너뜁니다.')
        return EXIT_SETUP
    if not await ready(cl):
        await cl.disconnect()
        return EXIT_SETUP
    conn = connect(cfg['db'])
    last = conn.execute("SELECT MAX(date) FROM msg WHERE src = 'tg'").fetchone()[0]
    if everything:
        cutoff = None
    elif days:
        cutoff = datetime.now(KST) - timedelta(days=days)
    elif last:
        cutoff = datetime.fromisoformat(last).replace(tzinfo=KST) - timedelta(days=OVERLAP_DAYS)
    else:
        cutoff = datetime.now(KST) - timedelta(days=FIRST_DAYS)
    total = 0
    try:
        for kw in cfg['keywords']:
            batch, seen, added = [], 0, 0
            async for m in cl.iter_messages(None, search=kw):      # entity 없음 = 내 모든 방 검색
                if cutoff and m.date < cutoff:
                    break
                seen += 1
                batch.append(row_of(m))
                if len(batch) >= 200:
                    added += save(conn, batch, cfg['must'])
                    batch = []
            added += save(conn, batch, cfg['must'])
            total += added
            print(f"'{kw}' 검색: {seen}건 확인, 새로 {added}건")
    finally:
        await cl.disconnect()
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('collected_at', ?)", (datetime.now().isoformat(timespec='seconds'),))
    conn.commit()
    n = conn.execute('SELECT COUNT(*), COUNT(DISTINCT chat_id) FROM msg').fetchone()
    print(f"{'탐방' if topic == 'visit' else '컨콜'} 글: 새로 {total}건, 모두 {n[0]}건 ({n[1]}개 방)" + (f', {cutoff:%Y-%m-%d} 이후' if cutoff else ''))
    return 0


async def do_scan(room: str, days) -> int:
    cl = client()
    if cl is None or not SESSION.exists() or not await ready(cl):
        return EXIT_SETUP
    conn = connect()
    cutoff = datetime.now(KST) - timedelta(days=days or FIRST_DAYS)
    try:
        hits = [d async for d in cl.iter_dialogs() if room.lower() in (d.name or '').lower()]
        if len(hits) != 1:
            print(f"'{room}' 에 맞는 방이 {len(hits)}개입니다:", ', '.join(d.name for d in hits[:20]) or '없음')
            return 1
        batch, seen, added = [], 0, 0
        async for m in cl.iter_messages(hits[0].entity, offset_date=None):
            if m.date < cutoff:
                break
            seen += 1
            if m.message and MUST in m.message:
                batch.append(row_of(m))
            if len(batch) >= 100:
                added += save(conn, batch)
                batch = []
        added += save(conn, batch)
        print(f'{hits[0].name}: {seen}건 훑음, 새로 {added}건 ({cutoff:%Y-%m-%d} 이후)')
    finally:
        await cl.disconnect()
    return 0


# ------------------------------------------------------------
# 텔레그램 데스크톱 내보내기(JSON)
# ------------------------------------------------------------

def export_text(t) -> str:
    """내보내기의 text 는 문자열이거나, 문자열·{type, text} 조각의 목록이다"""
    if isinstance(t, str):
        return t
    return ''.join(x if isinstance(x, str) else x.get('text', '') for x in t or [])


def parse_export(data: dict) -> list:
    """방 하나 내보내기({name, id, messages}) 또는 전체 내보내기({chats: {list: […]}}) → 글 목록"""
    chats = data.get('chats', {}).get('list') if 'chats' in data else [data]
    out = []
    for ch in chats or []:
        cid, name = ch.get('id') or 0, ch.get('name') or ''
        public = ch.get('type', '').startswith('public')
        for m in ch.get('messages', []):
            if m.get('type') != 'message':
                continue
            text = export_text(m.get('text'))
            if not text:
                continue
            link = f'https://t.me/c/{cid}/{m["id"]}' if 'channel' in ch.get('type', '') or 'supergroup' in ch.get('type', '') else ''
            out.append({'chat_id': cid, 'id': m['id'], 'chat': name, 'chat_user': '', 'date': (m.get('date') or '')[:19],
                        'sender': m.get('from') or '', 'fwd': m.get('forwarded_from') or '', 'text': text,
                        'link': '' if public else link, 'file': m.get('file_name') or '', 'src': 'export'})
    return out


def do_import(path: str) -> int:
    rows = parse_export(json.loads(Path(path).read_text(encoding='utf-8')))
    conn = connect()
    added = save(conn, rows)
    print(f'{path}: 글 {len(rows)}건 가운데 탐방 글 새로 {added}건')
    return 0


def do_rooms(topic: str = 'visit') -> int:
    conn = connect(TOPICS[topic]['db'])
    rows = conn.execute('SELECT chat, COUNT(*), MIN(date), MAX(date) FROM msg GROUP BY chat_id ORDER BY 2 DESC').fetchall()
    for chat, n, lo, hi in rows:
        print(f'{n:5d}건  {lo[:10]} ~ {hi[:10]}  {chat}')
    if not rows:
        print('받은 글이 없습니다.')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', nargs='?', default='collect', choices=['collect', 'login', 'logout', 'rooms', 'scan', 'import'])
    ap.add_argument('arg', nargs='?')
    ap.add_argument('--days', type=int)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--topic', default='visit', choices=list(TOPICS))
    a = ap.parse_args()
    if a.cmd == 'rooms':
        return do_rooms(a.topic)
    if a.cmd == 'import':
        if not a.arg:
            ap.error('import 뒤에 result.json 경로')
        return do_import(a.arg)
    try:
        import telethon  # noqa: F401
    except ImportError:
        print('telethon 이 없습니다:  pip3 install telethon')
        return EXIT_SETUP
    if a.cmd == 'login':
        return asyncio.run(do_login())
    if a.cmd == 'logout':
        return asyncio.run(do_logout())
    if a.cmd == 'scan':
        if not a.arg:
            ap.error('scan 뒤에 방 이름')
        return asyncio.run(do_scan(a.arg, a.days))
    return asyncio.run(do_collect(a.days, a.all, a.topic))


if __name__ == '__main__':
    sys.exit(main())
