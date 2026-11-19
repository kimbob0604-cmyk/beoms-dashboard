#!/usr/bin/env python3
"""
맥 ↔ 클라우드(.github/workflows/cloud-data.yml) 동기화 — 맥이 자는 동안 클라우드가 공시·리포트·수급을 받게 (2026-11-19)

클라우드는 맥과 같은 수집·빌드 코드(cloud_data.py)를 돌린다. 직전 목표가 비교·키워드·수급 5·20일 합계·실적 서프라이즈는
DB 이력이 있어야 해서, 맥이 DB 사본을 올리고 클라우드가 받아 쓴다.

- snapshot (맥, live.py 가 6시간마다): db/dashboard.db 를 sqlite 백업 → lzma 압축 → AES-256-GCM 암호화(.env CLOUD_DB_PASS)
  → 이 저장소의 릴리스 'dbsnap' 첨부 파일로 덮어 올린다(40MB 조각 snap.000…, meta.json). 릴리스 첨부는 덮어쓰면 옛 것이 지워져
  저장소가 불어나지 않는다(git 브랜치에 올리면 매번 48MB 씩 쌓인다). 암호 없이는 열 수 없다.
- beat (맥, live.py 가 5분마다): mac 브랜치에 빈 커밋을 강제 푸시. 그 커밋 시각이 '맥이 깨어 있음' 신호다.
  daily.py 가 길게 돌아도 끊기지 않게 live.py 의 빠른 쪽에서 띄운다. 네트워크가 끊긴 잠깐 깸(DarkWake)에는 신호가 안 가서 클라우드가 맡는다.
- alive (클라우드): mac 브랜치 커밋이 ALIVE_MIN 분 안이면 종료 코드 0 (맥이 맡는다), 아니면 1
- fetch (클라우드): dbsnap 을 받아 풀어 db/dashboard.db 로. 이미 받은 사본이면 그대로(10)

  python3 cloud_sync.py snapshot|beat|alive|fetch
"""
import base64
import hashlib
import json
import lzma
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'db' / 'dashboard.db'
LOG_DIR = ROOT / 'logs'
WORK = ROOT / '.cloudsync'            # 맥: 신호용 작업 저장소·임시 파일 (gitignore)
TAG = 'dbsnap'
PART = 40 * 1024 * 1024
ITER = 200_000
MAGIC = b'BDS1'
ALIVE_MIN = 15
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'


def env_no_token() -> dict:
    """config.py 가 올리는 GITHUB_TOKEN 은 대시보드 내용 쓰기 전용 → 릴리스·푸시는 본인 gh 로그인(keyring)으로 (publish_study 와 같음)"""
    return {k: v for k, v in os.environ.items() if k not in ('GITHUB_TOKEN', 'GH_TOKEN')}


def repo_slug() -> str:
    if os.environ.get('GITHUB_REPOSITORY'):
        return os.environ['GITHUB_REPOSITORY']
    url = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return url.split('github.com')[-1].lstrip(':/').removesuffix('.git')


def password() -> str:
    if not os.environ.get('CLOUD_DB_PASS'):
        try:
            import config  # noqa: F401  (.env → 환경변수)
        except Exception:
            pass
    return os.environ.get('CLOUD_DB_PASS', '')


def _key(pw: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, ITER, 32)


def seal(pw: str, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    return MAGIC + salt + nonce + AESGCM(_key(pw, salt)).encrypt(nonce, data, MAGIC)


def unseal(pw: str, blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if blob[:4] != MAGIC:
        raise ValueError('사본 형식이 다름')
    salt, nonce = blob[4:20], blob[20:32]
    return AESGCM(_key(pw, salt)).decrypt(nonce, blob[32:], MAGIC)


def _lock(name: str):
    import fcntl
    LOG_DIR.mkdir(exist_ok=True)
    f = open(LOG_DIR / f'{name}.lock', 'w')
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return None
    return f


def snapshot() -> int:
    pw = password()
    if not pw:
        print('CLOUD_DB_PASS 가 없어 DB 사본을 올리지 않음 (.env)')
        return 0
    lock = _lock('cloud_snapshot')
    if not lock:
        return 0
    t0 = time.time()
    WORK.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        tmp = Path(tmp)
        src, dst = sqlite3.connect(str(DB), timeout=60), sqlite3.connect(str(tmp / 'snap.db'))
        src.backup(dst)                         # 다른 프로세스가 쓰는 중에도 일관된 사본
        dst.close()
        src.close()
        raw = (tmp / 'snap.db').read_bytes()
        blob = seal(pw, lzma.compress(raw, preset=6))
        files = []
        for i in range(0, len(blob), PART):
            p = tmp / f'snap.{i // PART:03d}'
            p.write_bytes(blob[i:i + PART])
            files.append(p)
        meta = {'at': datetime.now().isoformat(timespec='seconds'), 'db': len(raw), 'size': len(blob),
                'parts': [p.name for p in files], 'sha': hashlib.sha256(blob).hexdigest()}
        (tmp / 'meta.json').write_text(json.dumps(meta))
        slug, env = repo_slug(), env_no_token()
        if subprocess.run(['gh', 'release', 'view', TAG, '-R', slug], capture_output=True, env=env).returncode != 0:
            r = subprocess.run(['gh', 'release', 'create', TAG, '-R', slug, '--prerelease', '--title', 'DB 사본 (암호화, 클라우드 수집용)',
                                '--notes', '맥이 자는 동안 GitHub Actions(cloud-data)가 공시·리포트·수급을 받을 때 쓰는 DB 사본입니다. '
                                          '암호화되어 있어 열 수 없습니다. cloud_sync.py 가 6시간마다 덮어씁니다.'],
                               capture_output=True, text=True, env=env)
            if r.returncode != 0:
                print(f'릴리스 만들기 실패: {r.stderr.strip()[:200]}')
                return 1
        # 조각 수가 줄면 남는 옛 조각을 지운다
        old = subprocess.run(['gh', 'release', 'view', TAG, '-R', slug, '--json', 'assets', '--jq', '.assets[].name'],
                             capture_output=True, text=True, env=env).stdout.split()
        r = subprocess.run(['gh', 'release', 'upload', TAG, '-R', slug, '--clobber', *map(str, files), str(tmp / 'meta.json')],
                           capture_output=True, text=True, env=env, timeout=1800)
        if r.returncode != 0:
            print(f'DB 사본 올리기 실패: {r.stderr.strip()[:200]}')
            return 1
        for name in old:
            if name.startswith('snap.') and name not in meta['parts']:
                subprocess.run(['gh', 'release', 'delete-asset', TAG, name, '-R', slug, '--yes'], capture_output=True, env=env)
    (LOG_DIR / 'cloud_snapshot.stamp').write_text(meta['at'])
    print(f"DB 사본 올림: {meta['db'] / 1e6:.0f}MB → {meta['size'] / 1e6:.0f}MB ({len(meta['parts'])}조각, {time.time() - t0:.0f}초)")
    return 0


def _git(*args, cwd=WORK, env=None, check=True):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, env=env, check=check).stdout.strip()


def beat() -> int:
    """mac 브랜치에 빈 커밋 하나를 강제 푸시 (커밋 시각 = 지금)"""
    lock = _lock('cloud_beat')
    if not lock:
        return 0
    repo = WORK / 'beat'
    env = env_no_token()
    if not (repo / '.git').exists():
        repo.mkdir(parents=True, exist_ok=True)
        _git('init', '-q', cwd=repo)
        _git('config', 'core.logAllRefUpdates', 'false', cwd=repo)
        _git('remote', 'add', 'origin', _git('remote', 'get-url', 'origin', cwd=ROOT), cwd=repo)
    tree = subprocess.run(['git', 'hash-object', '-w', '-t', 'tree', '/dev/null'], cwd=repo, capture_output=True, text=True).stdout.strip() or EMPTY_TREE
    who = {'GIT_AUTHOR_NAME': 'mac', 'GIT_AUTHOR_EMAIL': 'mac@localhost', 'GIT_COMMITTER_NAME': 'mac', 'GIT_COMMITTER_EMAIL': 'mac@localhost'}
    c = subprocess.run(['git', 'commit-tree', tree, '-m', f'맥 깨어 있음 {datetime.now():%Y-%m-%d %H:%M}'], cwd=repo,
                       capture_output=True, text=True, env={**env, **who}).stdout.strip()
    r = subprocess.run(['git', 'push', '-q', '--force', 'origin', f'{c}:refs/heads/mac'], cwd=repo, capture_output=True, text=True,
                       env=env, timeout=60)
    if r.returncode != 0:
        print(f'신호 푸시 실패: {r.stderr.strip()[:200]}')
        return 1
    (LOG_DIR / 'cloud_beat.stamp').write_text(datetime.now().isoformat(timespec='seconds'))
    return 0


def alive() -> int:
    """mac 브랜치 커밋 시각이 ALIVE_MIN 분 안이면 0 (클라우드는 쉰다)"""
    r = subprocess.run(['git', 'fetch', '-q', '--depth', '1', 'origin', 'mac'], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print('맥 신호 없음 (mac 브랜치를 못 받음)')
        return 1
    ts = int(_git('log', '-1', '--format=%ct', 'FETCH_HEAD', cwd=ROOT))
    ago = (time.time() - ts) / 60
    print(f'맥 신호: {ago:.0f}분 전')
    return 0 if ago < ALIVE_MIN else 1


def fetch() -> int:
    """dbsnap 릴리스를 받아 db/dashboard.db 로 (meta.json 의 sha 가 받아 둔 것과 같으면 그대로 — 10)"""
    pw = password()
    if not pw:
        print('CLOUD_DB_PASS 가 없음 (저장소 비밀값)')
        return 1
    slug = repo_slug()
    mark = DB.parent / '.snap_sha'
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        r = subprocess.run(['gh', 'release', 'download', TAG, '-R', slug, '-p', 'meta.json', '-D', str(tmp)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f'DB 사본 정보 받기 실패: {r.stderr.strip()[:200]}')
            return 1
        meta = json.loads((tmp / 'meta.json').read_text())
        if DB.exists() and mark.exists() and mark.read_text() == meta['sha']:
            return 10
        r = subprocess.run(['gh', 'release', 'download', TAG, '-R', slug, '-p', 'snap.*', '-D', str(tmp)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f'DB 사본 받기 실패: {r.stderr.strip()[:200]}')
            return 1
        blob = b''.join((tmp / name).read_bytes() for name in meta['parts'])
        if hashlib.sha256(blob).hexdigest() != meta['sha']:
            print('DB 사본이 덜 받혔음 (조각을 올리는 중일 수 있음)')
            return 1
        raw = lzma.decompress(unseal(pw, blob))
        DB.parent.mkdir(exist_ok=True)
        tmp_db = DB.with_suffix('.tmp')
        tmp_db.write_bytes(raw)
        tmp_db.replace(DB)
        mark.write_text(meta['sha'])
    print(f"DB 사본 받음: {meta['at']} 맥 기준, {len(raw) / 1e6:.0f}MB")
    return 0


def new_pass() -> int:
    """처음 한 번: .env 에 CLOUD_DB_PASS 를 만든다 (이미 있으면 그대로). 값은 화면에 쓰지 않는다"""
    env = ROOT / '.env'
    text = env.read_text(encoding='utf-8') if env.exists() else ''
    if any(line.startswith('CLOUD_DB_PASS=') for line in text.splitlines()):
        print('CLOUD_DB_PASS 가 이미 있음')
        return 0
    env.write_text(text.rstrip('\n') + f"\nCLOUD_DB_PASS={base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('=')}\n",
                   encoding='utf-8')
    print('.env 에 CLOUD_DB_PASS 를 만들었음')
    return 0


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    fn = {'snapshot': snapshot, 'beat': beat, 'alive': alive, 'fetch': fetch, 'new-pass': new_pass}.get(cmd)
    if not fn:
        print(__doc__)
        sys.exit(2)
    sys.exit(fn())
