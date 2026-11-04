"""
GitHub Pages 배포: public/ 화면 + 최근 KEEP_DAYS일 데이터 → origin 의 gh-pages 브랜치

- 날짜별 데이터(growth·flow·high·dart)는 최근 KEEP_DAYS개만, 종목 상세(stocks)·차트(chart)·리포트(reports)·홈(home.json)은 현재 파일 그대로.

매번 gh-pages 를 커밋 하나짜리로 새로 만들어 강제 푸시한다. 매일 수십 MB 의 JSON 이 바뀌어도
저장소 히스토리가 불어나지 않게 하기 위해서다. 코드(main 브랜치)는 건드리지 않는다.
배포용 저장소(.publish/)를 지워 없애지 않고 두어, 원격에 이미 있는 파일은 다시 올리지 않는다
(장중 10분마다 home.json 만 바뀔 때 몇 KB 만 올라간다).

  python3 publish.py
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / 'public'
DATA = PUBLIC / 'data'
DATED = ('growth', 'flow', 'high', 'dart')   # 날짜별 JSON + dates.json
CURRENT = ('stocks', 'chart', 'reports')   # 최신 파일만
FILES = ('home.json', 'names.json', 'quotes.json')   # 최신 단일 파일
KEEP_DAYS = 90
BRANCH = 'gh-pages'
REPO = ROOT / '.publish'   # 배포용 작업 저장소 (gitignore)


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def stamp_assets(out: Path):
    """HTML 의 js/css 주소에 내용 해시를 붙인다 (?v=…). GitHub Pages 가 10분 캐시하므로,
    배포 직후 옛 스크립트와 새 데이터가 섞여 화면이 깨지는 것을 막는다."""
    def ver(m):
        f = out / m.group(2)
        if not f.exists():
            return m.group(0)
        h = hashlib.sha1(f.read_bytes()).hexdigest()[:8]
        return f'{m.group(1)}{m.group(2)}?v={h}"'
    for page in out.glob('*.html'):
        s = page.read_text(encoding='utf-8')
        page.write_text(re.sub(r'((?:src|href)=")((?:js|css)/[\w.-]+\.(?:js|css))"', ver, s), encoding='utf-8')


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
    if (DATA / 'dart' / 's').exists():   # 종목별 최근 공시
        shutil.copytree(DATA / 'dart' / 's', out / 'data' / 'dart' / 's')
    for folder in CURRENT:
        if (DATA / folder).exists():
            shutil.copytree(DATA / folder, out / 'data' / folder)
    for f in FILES:
        if (DATA / f).exists():
            shutil.copy2(DATA / f, out / 'data' / f)
    stamp_assets(out)
    (out / '.nojekyll').touch()   # Jekyll 처리 없이 파일 그대로 서빙
    print('배포 데이터:', ', '.join(f'{k} {v}일' for k, v in counts.items()),
          f"· 종목 상세 {len(list((out / 'data' / 'stocks').glob('*.json')))}개")
    return counts['growth']


def ensure_repo(remote: str):
    if not (REPO / '.git').exists():
        REPO.mkdir(exist_ok=True)
        git('init', '-q', '-b', BRANCH, cwd=REPO)
        git('config', 'core.logAllRefUpdates', 'false', cwd=REPO)   # 지난 배포 커밋을 붙잡아 두지 않게
        git('remote', 'add', 'origin', remote, cwd=REPO)
    git('remote', 'set-url', 'origin', remote, cwd=REPO)
    # 원격 gh-pages 를 받아 두면 push 가 이미 있는 파일을 빼고 보낸다
    subprocess.run(['git', 'fetch', '-q', '--depth', '1', 'origin', BRANCH], cwd=REPO, capture_output=True)


def main() -> int:
    remote = git('remote', 'get-url', 'origin', cwd=ROOT)
    name = git('config', 'user.name', cwd=ROOT)
    email = git('config', 'user.email', cwd=ROOT)
    ensure_repo(remote)
    for p in REPO.iterdir():   # .git 만 남기고 비운 뒤 새로 채운다
        if p.name != '.git':
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    if not stage(REPO):
        print('배포할 데이터 없음 (build_growth.py 먼저)')
        return 1
    git('add', '-A', cwd=REPO)
    tree = git('write-tree', cwd=REPO)
    remote_tree = subprocess.run(['git', 'rev-parse', f'refs/remotes/origin/{BRANCH}^{{tree}}'], cwd=REPO,
                                 capture_output=True, text=True).stdout.strip()
    if tree == remote_tree and '--always' not in sys.argv:
        print('바뀐 파일 없음, 배포 건너뜀')
        return 0
    env = {'GIT_AUTHOR_NAME': name, 'GIT_AUTHOR_EMAIL': email, 'GIT_COMMITTER_NAME': name, 'GIT_COMMITTER_EMAIL': email}
    commit = subprocess.run(['git', 'commit-tree', tree, '-m', f'데이터 갱신 {datetime.now():%Y-%m-%d %H:%M}'],
                            cwd=REPO, check=True, capture_output=True, text=True,
                            env={**os.environ, **env}).stdout.strip()
    git('update-ref', f'refs/heads/{BRANCH}', commit, cwd=REPO)
    git('push', '-q', '--force', 'origin', f'{BRANCH}:{BRANCH}', cwd=REPO)
    git('update-ref', f'refs/remotes/origin/{BRANCH}', commit, cwd=REPO)
    subprocess.run(['git', 'prune', '--expire=now'], cwd=REPO, capture_output=True)   # 지난 배포의 파일 정리
    print(f'{BRANCH} 배포 완료')
    return 0


if __name__ == '__main__':
    sys.exit(main())
