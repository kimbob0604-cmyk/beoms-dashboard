"""
전략 트래커: 전략 카드의 '최근 호 요지' 관리 (strategy_notes.json — 문서 id → 직접 쓴 한두 문장)

요지는 사람이(예약된 Claude 작업이) 원문을 읽고 자기 말로 쓴다. 원문 문장을 옮기지 않는다.

  python3 strategy_notes.py pending          # 요지가 아직 없는 '전략별 가장 최근 호' 목록 (JSON)
  python3 strategy_notes.py add <id> "요지"  # 요지 저장
"""

import json
import sqlite3
import sys
from pathlib import Path

from collect_strategy import STRAT
from strategy_parse import SERIES

ROOT = Path(__file__).resolve().parent
NOTES = ROOT / 'strategy_notes.json'
CACHE = ROOT / '.cache' / 'reports'
SKIP = ('daol_bu',)      # 종목마다 글이 따로 올라와 '한 호'가 없다 → 카드에 판정 집계를 보여 준다
MAX_LEN = 220


def load() -> dict:
    return json.loads(NOTES.read_text(encoding='utf-8')) if NOTES.exists() else {}


def pending(conn, notes) -> list:
    """전략마다 종목이 추출된 가장 최근 글 하나. 그 글에 요지가 없으면 목록에 넣는다."""
    out = []
    for key, meta in SERIES.items():
        if key in SKIP:
            continue
        row = conn.execute("""SELECT id, date, title, url FROM doc WHERE series = ? AND parsed_at IS NOT NULL AND err IS NULL
                              AND (n_pick > 0 OR series = 'daol_aq') ORDER BY date DESC, COALESCE(ts, date) DESC, id DESC LIMIT 1""",
                           (key,)).fetchone()
        if not row or row[0] in notes:
            continue
        did, date, title, url = row
        item = {'id': did, 'series': key, 'name': meta['l'], 'date': date, 'title': title, 'url': url,
                'picks': [f"{n}({'롱' if s == 'L' else '숏'}{f' {w}%' if w else ''}{f', {g}' if g else ''})"
                          for n, s, w, g in conn.execute('SELECT name, side, weight, grp FROM pick WHERE doc_id = ?', (did,))]}
        text = CACHE / f'st_{did}.txt'
        if text.exists():
            item['text_file'] = str(text)      # 리포트 PDF 본문
        if did.startswith('tg'):
            post = conn.execute('SELECT text FROM tgpost WHERE ch = ? AND id = ?', (did[2:4], int(did[4:]))).fetchone()
            if post:
                item['post'] = post[0]         # 텔레그램 글 본문
        out.append(item)
    return out


def add(conn, did: str, text: str) -> str:
    text = ' '.join(text.split())
    row = conn.execute('SELECT series FROM doc WHERE id = ?', (did,)).fetchone()
    if not row:
        raise ValueError(f'모르는 문서 id: {did}')
    if row[0] in SKIP:
        raise ValueError(f'{row[0]} 은 요지를 달지 않는다')
    if not 20 <= len(text) <= MAX_LEN:
        raise ValueError(f'요지는 20~{MAX_LEN}자 (지금 {len(text)}자)')
    notes = load()
    notes[did] = text
    NOTES.write_text(json.dumps(notes, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return text


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'pending'
    conn = sqlite3.connect(f'file:{STRAT}?mode=ro', uri=True)
    if cmd == 'pending':
        print(json.dumps(pending(conn, load()), ensure_ascii=False, indent=1))
        return 0
    if cmd == 'add' and len(sys.argv) == 4:
        try:
            print('저장:', sys.argv[2], add(conn, sys.argv[2], sys.argv[3]))
            return 0
        except ValueError as e:
            print('실패:', e)
            return 1
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
