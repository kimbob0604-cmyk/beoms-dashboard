"""
탐방 노트 요약 관리 (visit_notes.json — "방번호:글번호" → 직접 쓴 두세 문장)

요약은 사람이(예약된 Claude 작업이) 글을 읽고 자기 말로 쓴다: 무엇을 하는 회사인지보다 이번 탐방에서 새로 나온 것
(가이던스·수주·증설·일정·리스크)을 숫자와 함께. 화면에서는 글 제목 아래 '요약'으로 보인다.

  python3 visit_notes.py pending [--limit 20]   # 요약이 아직 없는 탐방 노트 (최신순, JSON)
  python3 visit_notes.py add <id> "요약"        # 저장
"""

import json
import sqlite3
import sys
from pathlib import Path

import visits as V
from collect_visits import DB

ROOT = Path(__file__).resolve().parent
NOTES = ROOT / 'visit_notes.json'
MIN_LEN, MAX_LEN = 20, 400


def load(path: Path = NOTES) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def pending(conn, notes: dict, limit: int = 20) -> list:
    """요약이 없는 탐방 노트. 여러 방에 전달된 같은 글은 화면에 남는 첫 글 하나만."""
    rows = [{'chat_id': r[0], 'id': r[1], 'chat': r[2], 'date': r[3], 'text': r[4]}
            for r in conn.execute('SELECT chat_id, id, chat, date, text FROM msg ORDER BY date')]
    out = []
    for m in V.group_dupes([r for r in rows if V.is_note(r['text'])]):
        nid = f"{m['chat_id']}:{m['id']}"
        if nid not in notes:
            out.append({'id': nid, 'date': m['date'], 'room': m['chat'], 'title': V.title(m['text']), 'text': m['text']})
        if len(out) >= limit:
            break
    return out


def add(conn, nid: str, text: str, path: Path = NOTES) -> str:
    text = ' '.join(text.split())
    try:
        chat_id, mid = (int(x) for x in nid.split(':'))
    except ValueError:
        raise ValueError(f'id 는 "방번호:글번호" 꼴: {nid}')
    if not conn.execute('SELECT 1 FROM msg WHERE chat_id = ? AND id = ?', (chat_id, mid)).fetchone():
        raise ValueError(f'모르는 글 id: {nid}')
    if not MIN_LEN <= len(text) <= MAX_LEN:
        raise ValueError(f'요약은 {MIN_LEN}~{MAX_LEN}자 (지금 {len(text)}자)')
    notes = load(path)
    notes[nid] = text
    path.write_text(json.dumps(notes, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return text


def main() -> int:
    args = sys.argv[1:]
    cmd = args[0] if args else 'pending'
    if not DB.exists():
        print('탐방 글 DB 가 아직 없습니다 (collect_visits.py 먼저).')
        return 1
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    if cmd == 'pending':
        limit = int(args[args.index('--limit') + 1]) if '--limit' in args else 20
        print(json.dumps(pending(conn, load(), limit), ensure_ascii=False, indent=1))
        return 0
    if cmd == 'add' and len(args) == 3:
        try:
            print('저장:', args[1], add(conn, args[1], args[2]))
            return 0
        except ValueError as e:
            print('실패:', e)
            return 1
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
