"""
장중 지수 수급 스냅샷: 맥이 자는 동안에도 투자자별 누적 순매수(개인·외국인·기관·프로그램)를 남긴다.

네이버 지수 API 는 "지금까지의 누적 순매수"만 주고 지난 시각 값은 주지 않는다(시간별 페이지는 서비스 종료).
그래서 맥이 잠든 구간은 나중에 채울 수 없다. GitHub Actions(.github/workflows/cloud-live.yml)가 평일 장중 5분마다
take 를 돌려 저장소의 snap 브랜치에 날짜별 파일로 쌓고, 맥은 깨어난 뒤 merge 로 자기에게 없는 시각만 채운다.

이 파일은 GitHub Actions 에서 혼자 돌아야 하므로 표준 라이브러리만 쓴다 (프로젝트 모듈을 불러오지 않는다).

  python3 index_snap.py take <폴더>   # 지금 값을 <폴더>/YYYY-MM-DD.json 에 더한다 (장 시간 밖·휴장일은 건너뜀)
  python3 index_snap.py merge         # snap 브랜치의 오늘 파일 → db/dashboard.db index_snap 의 빈 시각
                                      # 종료 코드: 0 채운 시각 있음, 10 없음
"""

import json
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = 'https://m.stock.naver.com/api/index/{}/integration'
CODES = ('KOSPI', 'KOSDAQ', 'FUT')          # FUT: 코스피200 선물 최근월물 (프로그램 없음)
SNAP_END = {'KOSPI': '15:30', 'KOSDAQ': '15:30', 'FUT': '15:45'}      # 마감 뒤 값은 마감 칸에 (확정 순매수)
OPEN, LAST = '09:00', '15:59'
KEEP_DAYS = 14
BRANCH = 'snap'
NOTHING = 10


def kst_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).replace(tzinfo=None)


def num(v):
    """'+3,369' → 3369.0, 값이 없으면 None"""
    try:
        return float(str(v).replace(',', '').replace('+', ''))
    except (TypeError, ValueError):
        return None


def get_json(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def parse(integration: dict):
    """→ (거래일 'YYYY-MM-DD', [외국인, 기관, 개인, 프로그램] 억원). 순매수가 아직 없으면 (None, None)"""
    deal = integration.get('dealTrendInfo') or {}
    biz = str(deal.get('bizdate') or '')
    vals = [num(deal.get('foreignValue')), num(deal.get('institutionalValue')), num(deal.get('personalValue')),
            num((integration.get('programTrendInfo') or {}).get('indexTotalReal'))]
    if len(biz) != 8 or vals[0] is None:
        return None, None
    return f'{biz[:4]}-{biz[4:6]}-{biz[6:]}', vals


def take(folder: Path, now: datetime, fetch=get_json, force=False) -> int:
    """지금 값을 그날 파일에 더한다. 바뀐 지수 수를 돌려준다."""
    hm, day = now.strftime('%H:%M'), now.strftime('%Y-%m-%d')
    if not force and (now.weekday() >= 5 or not OPEN <= hm <= LAST):
        print(f'{day} {hm} 장 시간 밖 — 건너뜀')
        return 0
    path = folder / f'{day}.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'date': day}
    changed = 0
    for code in CODES:
        try:
            biz, vals = parse(fetch(API.format(code)))
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f'{code} 받기 실패: {type(e).__name__} {e}')
            continue
        if biz != day:      # 휴장일이거나 개장 전 (어제 값이 남아 있다)
            print(f'{code} 거래일 {biz} ≠ 오늘 {day} — 건너뜀')
            continue
        t = min(hm, SNAP_END[code])
        rows = [r for r in data.get(code, []) if r[0] != t]
        if len(rows) != len(data.get(code, [])) and [t, *vals] in data[code]:
            continue        # 마감 뒤 같은 값을 또 받았다
        data[code] = sorted(rows + [[t, *vals]])
        changed += 1
    if changed:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    old = (now - timedelta(days=KEEP_DAYS)).strftime('%Y-%m-%d')
    for f in folder.glob('20*.json'):
        if f.stem < old:
            f.unlink()
    print(f'{day} {hm} 스냅샷 {changed}개 지수')
    return changed


# ------------------------------------------------------------
# 맥: 받아 둔 스냅샷으로 빈 시각 채우기
# ------------------------------------------------------------

def remote_url(day: str) -> str:
    origin = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=ROOT, capture_output=True, text=True).stdout
    m = re.search(r'github\.com[:/]([^/]+/[^/.\s]+)', origin)
    if not m:
        raise ValueError('origin 이 GitHub 저장소가 아님')
    return f'https://raw.githubusercontent.com/{m.group(1)}/{BRANCH}/{day}.json'


def merge(conn, data: dict, day: str, upto: str = '23:59') -> int:
    """data 의 스냅샷 가운데 index_snap 에 없는 시각만 넣는다 (맥이 직접 받은 값은 건드리지 않는다).
    close 는 그 시각까지의 1분봉 마지막 값."""
    if data.get('date') != day:
        return 0
    added = 0
    for code in CODES:
        have = {r[0] for r in conn.execute('SELECT t FROM index_snap WHERE date = ? AND code = ?', (day, code))}
        for row in data.get(code, []):
            t, frgn, org, ind, prog = row
            if t in have or t > upto:
                continue
            px = conn.execute('SELECT price FROM index_minute WHERE date = ? AND code = ? AND t <= ? ORDER BY t DESC LIMIT 1',
                              (day, code, t)).fetchone()
            conn.execute('INSERT OR IGNORE INTO index_snap (date, code, t, close, frgn, org, ind, prog) VALUES (?,?,?,?,?,?,?,?)',
                         (day, code, t, px[0] if px else None, frgn, org, ind, prog))
            added += 1
    conn.commit()
    return added


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    now = kst_now()
    if cmd == 'take' and len(sys.argv) >= 3:
        take(Path(sys.argv[2]), now, force='--force' in sys.argv)
        return 0      # 받기 실패로 워크플로를 실패시키지 않는다 (5분마다 실패 메일이 오지 않게). 기록은 실행 로그에 남는다
    if cmd == 'merge':
        day = now.strftime('%Y-%m-%d')
        try:
            data = get_json(remote_url(day))
        except urllib.error.HTTPError as e:
            print(f'{now:%H:%M:%S} 원격 스냅샷 없음 ({e.code})')
            return NOTHING
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f'{now:%H:%M:%S} 원격 스냅샷 받기 실패: {type(e).__name__} {e}')
            return NOTHING
        conn = sqlite3.connect(str(ROOT / 'db' / 'dashboard.db'), timeout=30)
        added = merge(conn, data, day, now.strftime('%H:%M'))
        print(f'{now:%H:%M:%S} 원격 스냅샷 {sum(len(data.get(c, [])) for c in CODES)}행 중 빈 시각 {added}개 채움')
        return 0 if added else NOTHING
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
