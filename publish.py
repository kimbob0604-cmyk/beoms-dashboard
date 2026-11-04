"""
GitHub Pages 배포: public/ 화면 + 최근 KEEP_DAYS일 데이터 → origin 의 gh-pages 브랜치

- 날짜별 데이터(growth·flow·high)는 최근 KEEP_DAYS개만, 종목 상세(stocks)·리포트(reports)·홈(home.json)은 현재 파일 그대로.

매번 gh-pages 를 커밋 하나짜리로 새로 만들어 강제 푸시한다. 매일 1MB 가까운 JSON 이 쌓여도
저장소 히스토리가 불어나지 않게 하기 위해서다. 코드(main 브랜치)는 건드리지 않는다.

  python3 publish.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / 'public'
DATA = PUBLIC / 'data'
DATED = ('growth', 'flow', 'high')   # 날짜별 JSON + dates.json
CURRENT = ('stocks', 'reports')     # 최신 파일만
FILES = ('home.json',)              # 최신 단일 파일
KEEP_DAYS = 90
BRANCH = 'gh-pages'


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def stage(out: Path) -> int:
    """배포할 파일을 out 에 모은다. 이익 성장 데이터 날짜 수를 돌려준다."""
    shutil.copytree(PUBLIC, out, ignore=shutil.ignore_patterns('data'), dirs_exist_ok=True)
    counts = {}
    for folder in DATED:
        src, dst = DATA / folder, out / 'data' / folder
        dates = sorted((p.stem for p in src.glob('20*.json')), reverse=True)[:KEEP_DAYS]
        dst.mkdir(parents=True)
        for d in dates:
            shutil.copy2(src / f'{d}.json', dst / f'{d}.json')
        (dst / 'dates.json').write_text(json.dumps(dates))
        counts[folder] = len(dates)
    for folder in CURRENT:
        if (DATA / folder).exists():
            shutil.copytree(DATA / folder, out / 'data' / folder)
    for f in FILES:
        if (DATA / f).exists():
            shutil.copy2(DATA / f, out / 'data' / f)
    (out / '.nojekyll').touch()   # Jekyll 처리 없이 파일 그대로 서빙
    print('배포 데이터:', ', '.join(f'{k} {v}일' for k, v in counts.items()),
          f"· 종목 상세 {len(list((out / 'data' / 'stocks').glob('*.json')))}개")
    return counts['growth']


def main() -> int:
    remote = git('remote', 'get-url', 'origin', cwd=ROOT)
    name = git('config', 'user.name', cwd=ROOT)
    email = git('config', 'user.email', cwd=ROOT)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        n = stage(out)
        if not n:
            print('배포할 데이터 없음 (build_growth.py 먼저)')
            return 1
        git('init', '-q', '-b', BRANCH, cwd=out)
        git('-c', f'user.name={name}', '-c', f'user.email={email}',
            'add', '-A', cwd=out)
        git('-c', f'user.name={name}', '-c', f'user.email={email}',
            'commit', '-q', '-m', f'데이터 갱신 {datetime.now():%Y-%m-%d %H:%M}', cwd=out)
        git('push', '-q', '--force', remote, f'{BRANCH}:{BRANCH}', cwd=out)
    print(f'{BRANCH} 배포 완료')
    return 0


if __name__ == '__main__':
    sys.exit(main())
