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
DATED = ('growth', 'flow', 'high', 'dart', 'digest')   # 날짜별 JSON + dates.json
CURRENT = ('stocks', 'chart', 'reports', 'events', 'bt', 'st', 'vchart', 'earn')   # 최신 파일만 (vchart = 탐방 탭 차트, earn = 실적 발표 덱 1년)
FILES = ('home.json', 'names.json', 'quotes.json', 'factors.json', 'events.json', 'digest_index.json', 'digest_weekly.json', 'bio.json')   # 최신 단일 파일
# 공개용으로 따로 만든 파일 → 배포본에서의 이름. 탐방 탭: 이 컴퓨터용 visits.json(1:1 대화·공개 채널 원문 포함)은 올리지 않고
# build_visits.public_view 가 줄인 visits_pub.json 을 data/visits.json 으로 올린다
RENAMED = {'visits_pub.json': 'visits.json', 'consumer.json': 'consumer.json',
           'consumer_calls_pub.json': 'consumer_calls.json'}     # 소비재 탭: 컨콜 노트도 공개용 사본(1:1 제외, 공개 채널은 제목·링크만)
KEEP_DAYS = 90
BRANCH = 'gh-pages'
REPO = ROOT / '.publish'   # 배포용 작업 저장소 (gitignore)
# 아직 공개하면 안 되는 화면·데이터 (public/ 기준 경로, 한 줄에 하나). 이 파일이 있으면 배포에서 빼고,
# 다른 화면의 탭 링크도 지운다. 공개해도 되면 해당 줄(또는 파일)을 지우면 된다.
HOLD_FILE = ROOT / 'publish_hold.txt'


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


def held() -> set:
    if not HOLD_FILE.exists():
        return set()
    return {ln.strip() for ln in HOLD_FILE.read_text(encoding='utf-8').splitlines()
            if ln.strip() and not ln.startswith('#')}


def apply_hold(out: Path, hold: set):
    """보류한 파일을 지우고, 다른 화면에서 그 화면으로 가는 탭 링크를 뺀다"""
    for rel in hold:
        f = out / rel
        if f.is_file():
            f.unlink()
        elif f.is_dir():      # 데이터 폴더째 보류 (예: data/st)
            shutil.rmtree(f)
    pages = [h for h in hold if h.endswith('.html')]
    if not pages:
        return
    pat = re.compile(r'\n?[ \t]*<a class="tab[^"]*" href="(?:' + '|'.join(map(re.escape, pages)) + r')">[^<]*</a>')
    for page in out.glob('*.html'):
        s = page.read_text(encoding='utf-8')
        page.write_text(pat.sub('', s), encoding='utf-8')


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
    for src, dst in RENAMED.items():
        if (DATA / src).exists():
            shutil.copy2(DATA / src, out / 'data' / dst)
    hold = held()
    if hold:
        apply_hold(out, hold)
        print('공개 보류:', ', '.join(sorted(hold)))
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


def last_deploy_failed(remote: str, commit: str) -> bool:
    """원격 gh-pages 의 지금 커밋으로 돈 GitHub Pages 배포가 실패·취소로 끝났으면 True.
    배포가 'syncing_files' 타임아웃으로 실패하면 사이트는 옛 상태로 남는데, 내용이 같으면 다시 올리지 않아
    그대로 굳는 문제가 있었다(2026-11-09 11:38). gh 가 없거나 확인이 안 되면 False."""
    m = re.search(r'github\.com[:/]([^/]+/[^/.]+)', remote)
    if not m or not commit:
        return False
    try:
        r = subprocess.run(['gh', 'run', 'list', '-R', m.group(1), '--workflow', 'pages-build-deployment', '-L', '5',
                            '--json', 'status,conclusion,headSha'], capture_output=True, text=True, timeout=30)
        runs = [x for x in json.loads(r.stdout or '[]') if x.get('headSha') == commit]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    return bool(runs) and runs[0]['status'] == 'completed' and runs[0]['conclusion'] in ('failure', 'cancelled', 'timed_out')


def main() -> int:
    # daily.py 와 live.py 가 동시에 배포하면 .publish 작업 저장소가 엉킨다 → 배포는 한 번에 하나 (앞의 배포가 끝날 때까지 기다린다)
    import fcntl
    (ROOT / 'logs').mkdir(exist_ok=True)
    lock = open(ROOT / 'logs' / 'publish.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        return _publish()
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)


def _publish() -> int:
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
        head = subprocess.run(['git', 'rev-parse', f'refs/remotes/origin/{BRANCH}'], cwd=REPO,
                              capture_output=True, text=True).stdout.strip()
        if not last_deploy_failed(remote, head):
            print('바뀐 파일 없음, 배포 건너뜀')
            return 0
        print('지난 배포가 실패해서 같은 내용을 다시 올림')
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
