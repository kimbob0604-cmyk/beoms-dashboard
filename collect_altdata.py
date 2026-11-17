"""
K뷰티 대체데이터 (Amazon 점유율·TikTok Shop GMV 지수·Reddit 언급) — newsbot 커버리지 대시보드의 공개 JSON 을 그대로 받아 둔다

원자료(Amazon 순위 가중 SKU 점유율, Kalodata TikTok Shop GMV, Reddit 글 분석)는 유료·자체 수집이라 직접 만들 수 없어서,
2026-11-16 사용자 요청으로 newsbot 이 공개한 kbeauty_altdata.json 을 하루 한 번 받아 public/data/altdata.json 으로 둔다.
남의 집계라 **공개 배포에는 올리지 않는다**(publish.py FILES 에 없고 publish_hold.txt 에도 적었다) — 이 컴퓨터 화면에서만 본다.
받기에 실패하면 직전 파일을 그대로 둔다.

  python3 collect_altdata.py           # 오늘 아직 안 받았으면
  python3 collect_altdata.py --force
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'public' / 'data' / 'altdata.json'
SRC = 'https://newsbot-3uj.pages.dev/kbeauty_altdata.json'
PAGE = 'https://newsbot-3uj.pages.dev/coverage/coverage'


def collect(force: bool = False, log=print) -> int:
    if OUT.exists() and not force:
        old = json.loads(OUT.read_text(encoding='utf-8'))
        if old.get('fetched_at', '')[:10] == date.today().isoformat():
            log('대체데이터: 오늘 이미 받음')
            return 0
    try:
        r = requests.get(SRC, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        r.raise_for_status()
        d = r.json()
        if not isinstance(d.get('companies'), dict):
            raise ValueError('companies 없음 — 형식이 바뀌었다')
    except (requests.RequestException, ValueError) as e:
        log(f'대체데이터 실패: {str(e)[:150]} — 직전 파일 유지')
        return 1
    d['fetched_at'] = datetime.now().isoformat(timespec='seconds')
    d['src'], d['page'] = SRC, PAGE
    OUT.write_text(json.dumps(d, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    log(f"대체데이터: {len(d['companies'])}개 회사 · 원자료 {d.get('data_through')} (갱신 {d.get('updated_at')})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    return collect(ap.parse_args().force)


if __name__ == '__main__':
    sys.exit(main())
