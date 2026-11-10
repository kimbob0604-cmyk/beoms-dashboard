"""
탐방 탭 차트: 탐방 노트가 있는 종목의 네이버 증권 일봉(최근 500거래일) → public/data/vchart/{code}.json

종목 패널용 차트(data/chart/)는 최근 1년 안쪽이라 1년 전 탐방까지 덮지 못한다. 탐방 종목만 따로 길게 받는다.
네이버 일봉(fchart)은 수정주가이고 오늘 장중 값까지 온다. 지수용으로 쓰던 호출을 종목 코드로 그대로 쓴다.

{"code": 코드, "d": [20241022, …], "o": [...], "h": [...], "l": [...], "c": [...], "v": [...]}   (data/chart 와 같은 꼴)

- 하루 한 번이면 충분하다: 오늘 이미 받은 파일은 건너뛴다(--force 로 다시).
- 실패한 종목은 직전 파일을 그대로 둔다. 탐방 목록에서 빠진 종목의 파일은 지운다.

  python3 collect_visits_chart.py
  python3 collect_visits_chart.py --force
"""

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

from collectors import naver

ROOT = Path(__file__).resolve().parent
VISITS = ROOT / 'public' / 'data' / 'visits.json'
OUT = ROOT / 'public' / 'data' / 'vchart'
COUNT = 500
PAUSE = 0.08
MAX_FAIL = 15          # 연속 실패가 이만큼이면 서버 문제로 보고 멈춘다


def columns(code: str, rows: list) -> dict:
    """일봉 행(날짜순) → 열 단위 배열. 날짜는 20261110 꼴 정수"""
    return {'code': code,
            'd': [int(r['date'].replace('-', '')) for r in rows],
            'o': [r['open'] for r in rows], 'h': [r['high'] for r in rows], 'l': [r['low'] for r in rows],
            'c': [r['close'] for r in rows], 'v': [r['volume'] for r in rows]}


def fresh(path: Path, today: date) -> bool:
    return path.exists() and datetime.fromtimestamp(path.stat().st_mtime).date() == today


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    if not VISITS.exists():
        print('visits.json 이 없습니다 (build_visits.py 먼저). 건너뜁니다.')
        return 0
    codes = [c['c'] for c in json.loads(VISITS.read_text(encoding='utf-8'))['cos']]
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob('*.json'):                     # 탐방 목록에서 빠진 종목
        if f.stem not in codes:
            f.unlink()
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    today, done, skipped, failed, streak = date.today(), 0, 0, [], 0
    for code in codes:
        path = OUT / f'{code}.json'
        if not a.force and fresh(path, today):
            skipped += 1
            continue
        try:
            rows = naver.fetch_index_ohlc(session, code, count=COUNT)    # 같은 주소가 종목 코드도 받는다
            path.write_text(json.dumps(columns(code, rows), separators=(',', ':')), encoding='utf-8')
            done += 1
            streak = 0
        except (requests.RequestException, ValueError) as e:
            failed.append(code)
            streak += 1
            if streak >= MAX_FAIL:
                print(f'연속 {streak}건 실패 — 중단 ({e})')
                break
        time.sleep(PAUSE)
    print(f'탐방 차트: 받음 {done}, 오늘 이미 받음 {skipped}, 실패 {len(failed)} {failed[:10]}')
    return 1 if failed and not done and not skipped else 0


if __name__ == '__main__':
    sys.exit(main())
