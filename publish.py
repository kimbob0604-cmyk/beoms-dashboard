"""
GitHub Pages 배포: public/ 화면 + 최근 KEEP_DAYS일 데이터 → origin 의 gh-pages 브랜치

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
DATA = PUBLIC / 'data' / 'growth'
KEEP_DAYS = 90
BRANCH = 'gh-pages'


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def stage(out: Path) -> int:
    """배포할 파일을 out 에 모은다. 데이터 날짜 수를 돌려준다."""
    shutil.copytree(PUBLIC, out, ignore=shutil.ignore_patterns('data'), dirs_exist_ok=True)
    dates = sorted((p.stem for p in DATA.glob('20*.json')), reverse=True)[:KEEP_DAYS]
    (out / 'data' / 'growth').mkdir(parents=True)
    for d in dates:
        shutil.copy2(DATA / f'{d}.json', out / 'data' / 'growth' / f'{d}.json')
    (out / 'data' / 'growth' / 'dates.json').write_text(json.dumps(dates))
    (out / '.nojekyll').touch()   # Jekyll 처리 없이 파일 그대로 서빙
    return len(dates)


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
    print(f'{BRANCH} 배포 완료: {n}일치 데이터')
    return 0


if __name__ == '__main__':
    sys.exit(main())
