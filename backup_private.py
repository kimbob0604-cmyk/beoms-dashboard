"""
비공개 저장소(kimbob0604-cmyk/beoms-dashboard-private)에 탐방 노트 원본을 올린다.

공개 저장소·공개 사이트에는 줄인 사본(visits_pub.json)만 올라가고, 원본(1:1 대화·공개 채널 원문 포함)은
이 컴퓨터에만 있었다. 그 원본을 비공개 저장소에 쌓아 둔다. 작업 폴더는 .private/ (대시보드 저장소에서는 gitignore).

- db/visits.sql   : db/visits.db 를 SQL 텍스트로 뜬 것 (sqlite3 visits.db < visits.sql 로 되살린다).
                    바이너리 .db 를 매일 올리면 저장소가 하루 몇 MB 씩 불어나서 텍스트로 둔다 (새 글만 차이로 쌓인다).
- data/visits.json: 탐방 탭 이 컴퓨터용 전체본 (build_visits.py)
- 글이 바뀌지 않았으면(새 글·수정 글 없음) 커밋하지 않는다. 시총만 바뀐 visits.json 은 그때 같이 올라간다.
- 텔레그램 로그인 파일(tg_user.session)과 키는 올리지 않는다.

  python3 backup_private.py          # daily.py 가 탐방 빌드 뒤에 부른다
"""

import hashlib
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / '.private'
SRC_DB = ROOT / 'db' / 'visits.db'
SRC_JSON = ROOT / 'public' / 'data' / 'visits.json'
FINGERPRINT = PRIV / 'db' / 'visits.fingerprint'   # 마지막으로 올린 글 목록의 해시


def git(*args, check=True) -> str:
    return subprocess.run(['git', '-C', str(PRIV), *args], check=check, capture_output=True, text=True).stdout.strip()


def fingerprint(conn) -> str:
    h = hashlib.sha256()
    for row in conn.execute('SELECT chat_id, id, date, chat, text FROM msg ORDER BY chat_id, id'):
        h.update(repr(row).encode())
    return h.hexdigest()


def main() -> int:
    if not (PRIV / '.git').exists():
        print('.private/ 가 비공개 저장소로 준비돼 있지 않습니다. 건너뜁니다.')
        return 0
    if not SRC_DB.exists():
        print('db/visits.db 가 없습니다. 건너뜁니다.')
        return 0
    conn = sqlite3.connect(f'file:{SRC_DB}?mode=ro', uri=True, timeout=60)
    fp = fingerprint(conn)
    old = FINGERPRINT.read_text().strip() if FINGERPRINT.exists() else ''
    if fp != old:
        (PRIV / 'db').mkdir(exist_ok=True)
        (PRIV / 'data').mkdir(exist_ok=True)
        with open(PRIV / 'db' / 'visits.sql', 'w', encoding='utf-8') as f:
            for line in conn.iterdump():
                f.write(line + '\n')
        if SRC_JSON.exists():
            shutil.copyfile(SRC_JSON, PRIV / 'data' / 'visits.json')
        FINGERPRINT.write_text(fp + '\n')
        n, last = conn.execute('SELECT COUNT(*), MAX(date) FROM msg').fetchone()
        git('add', '-A')
        if git('status', '--porcelain'):
            git('commit', '-q', '-m', f'탐방 데이터 {datetime.now():%Y-%m-%d %H:%M} (글 {n}건, 마지막 {str(last)[:10]})')
            print(f'커밋: 글 {n}건')
    else:
        print('새 글 없음 — 커밋하지 않음')
    conn.close()
    # 커밋은 했는데 지난번 푸시가 실패했을 수도 있으니, 원격보다 앞서 있으면 늘 푸시한다
    git('fetch', '-q', 'origin', check=False)
    ahead = git('rev-list', '--count', 'origin/main..HEAD', check=False) or '1'
    if ahead != '0':
        r = subprocess.run(['git', '-C', str(PRIV), 'push', '-q', 'origin', 'main'], capture_output=True, text=True)
        if r.returncode != 0:
            print('푸시 실패 — 다음 실행에서 다시 올립니다')
            return 1
        print(f'푸시: 커밋 {ahead}개')
    return 0


if __name__ == '__main__':
    sys.exit(main())
