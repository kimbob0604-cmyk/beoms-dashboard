#!/usr/bin/env python3
"""Beom's Study 를 대시보드와 다른 사이트로 배포한다: GitHub 저장소 beoms-study 의 gh-pages
→ https://kimbob0604-cmyk.github.io/beoms-study/

- 대시보드 사이트(publish.py)에는 Study 가 올라가지 않는다(publish_hold.txt). Study 는 여기서만 올린다.
- .env 의 STUDY_PASS 가 없으면 아무것도 하지 않는다. 데이터·그림은 study_crypt.py 로 잠가 올린다(<경로>.enc + lock.json).
- 올리는 것: study.html → index.html, css/app.css·study.css, js/util.js·study_chart.js·study.js, 잠근 data/study.
  종목 상세 패널(stock.js 등)은 대시보드 데이터가 필요해 넣지 않는다 → 화면의 종목·반도체·바이오 링크는 대시보드로 연다(study.js 의 DASH).
- publish.py 와 같은 방식: gh-pages 를 커밋 하나짜리로 새로 만들어 강제 푸시(히스토리 안 쌓임), 바뀐 파일만 올라간다.
  publish.py 가 대시보드 배포 뒤에 부른다. 혼자 돌려도 된다:

  python3 publish_study.py
"""
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import publish as P
import study_crypt

ROOT = P.ROOT
PUBLIC = P.PUBLIC
REPO = ROOT / '.publish_study'       # 배포용 작업 저장소 (gitignore)
SITE_REPO = 'beoms-study'
BRANCH = 'gh-pages'
ASSETS = ('css/app.css', 'css/study.css', 'js/util.js', 'js/study_chart.js', 'js/study.js')
DASH_ONLY = ('plot.js', 'dartfmt.js', 'fund.js', 'stock.js')   # 종목 패널용 — Study 사이트에선 뺀다


def remote_url() -> str:
    origin = P.git('remote', 'get-url', 'origin', cwd=ROOT)
    return re.sub(r'[^/:]+?(\.git)?$', SITE_REPO + '.git', origin)


def ensure_pages(remote: str):
    """첫 배포 뒤 저장소의 GitHub Pages 를 gh-pages 브랜치로 켠다 (이미 켜져 있으면 그대로)"""
    m = re.search(r'github\.com[:/]([^/]+/[^/.]+)', remote)
    if not m:
        return
    repo = m.group(1)
    if subprocess.run(['gh', 'api', f'repos/{repo}/pages'], capture_output=True).returncode == 0:
        return
    r = subprocess.run(['gh', 'api', '-X', 'POST', f'repos/{repo}/pages', '-f', f'source[branch]={BRANCH}', '-f', 'source[path]=/'],
                       capture_output=True, text=True)
    print('GitHub Pages 켬' if r.returncode == 0 else f'GitHub Pages 켜기 실패: {r.stderr.strip()[:200]}')


def stage(out: Path, pw: str) -> int:
    page = (PUBLIC / 'study.html').read_text(encoding='utf-8')
    page = re.sub(r'\n<script src="js/(?:' + '|'.join(map(re.escape, DASH_ONLY)) + r')"></script>', '', page)
    page = re.sub(r'((?:js|css)/[\w.-]+\.(?:js|css))\?v=[\w]+', r'\1', page)   # 손으로 붙인 ?v= 를 지우고 stamp_assets 가 내용 해시로
    (out / 'index.html').write_text(page, encoding='utf-8')
    for rel in ASSETS:
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PUBLIC / rel, out / rel)
    n, size = study_crypt.encrypt_into(out / 'data' / 'study', pw)
    P.stamp_assets(out)
    (out / '.nojekyll').touch()
    (out / 'robots.txt').write_text('User-agent: *\nDisallow: /\n')
    print(f'Study 사이트: 잠근 파일 {n}개, {size / 1e6:.0f}MB')
    return n


def main() -> int:
    pw = study_crypt.password()
    if not pw:
        print('STUDY_PASS 가 없어 Study 사이트 배포를 건너뜀 (.env)')
        return 0
    if not (PUBLIC / 'data' / 'study' / 'index.json').exists():
        print('Study 데이터 없음 (python3 build_study.py 먼저)')
        return 1
    remote = remote_url()
    if not (REPO / '.git').exists():
        REPO.mkdir(exist_ok=True)
        P.git('init', '-q', '-b', BRANCH, cwd=REPO)
        P.git('config', 'core.logAllRefUpdates', 'false', cwd=REPO)
        P.git('remote', 'add', 'origin', remote, cwd=REPO)
    P.git('remote', 'set-url', 'origin', remote, cwd=REPO)
    subprocess.run(['git', 'fetch', '-q', '--depth', '1', 'origin', BRANCH], cwd=REPO, capture_output=True)
    for p in REPO.iterdir():
        if p.name != '.git':
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    stage(REPO, pw)
    P.git('add', '-A', cwd=REPO)
    tree = P.git('write-tree', cwd=REPO)
    remote_tree = subprocess.run(['git', 'rev-parse', f'refs/remotes/origin/{BRANCH}^{{tree}}'], cwd=REPO,
                                 capture_output=True, text=True).stdout.strip()
    if tree == remote_tree and '--always' not in sys.argv:
        print('Study 사이트: 바뀐 파일 없음, 배포 건너뜀')
        return 0
    name = P.git('config', 'user.name', cwd=ROOT)
    email = P.git('config', 'user.email', cwd=ROOT)
    env = {'GIT_AUTHOR_NAME': name, 'GIT_AUTHOR_EMAIL': email, 'GIT_COMMITTER_NAME': name, 'GIT_COMMITTER_EMAIL': email}
    import os
    commit = subprocess.run(['git', 'commit-tree', tree, '-m', f'Study 갱신 {datetime.now():%Y-%m-%d %H:%M}'],
                            cwd=REPO, check=True, capture_output=True, text=True, env={**os.environ, **env}).stdout.strip()
    P.git('update-ref', f'refs/heads/{BRANCH}', commit, cwd=REPO)
    P.git('push', '-q', '--force', 'origin', f'{BRANCH}:{BRANCH}', cwd=REPO)
    P.git('update-ref', f'refs/remotes/origin/{BRANCH}', commit, cwd=REPO)
    subprocess.run(['git', 'prune', '--expire=now'], cwd=REPO, capture_output=True)
    ensure_pages(remote)
    print(f'Study 사이트 배포 완료 → https://kimbob0604-cmyk.github.io/{SITE_REPO}/')
    return 0


if __name__ == '__main__':
    sys.exit(main())
