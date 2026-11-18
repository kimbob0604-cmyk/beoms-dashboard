#!/usr/bin/env python3
"""Study 데이터를 암호로 잠가 공개 사이트에 올린다 (publish.py 가 부른다)

- 암호는 .env 의 STUDY_PASS (본인이 직접 적는다). 없으면 Study 는 지금처럼 배포에서 빠진다(publish_hold.txt).
- public/data/study/** 파일마다 AES-256-GCM 으로 잠가 <같은 경로>.enc 로 둔다. 원래 이름의 파일은 올리지 않는다.
  열쇠 = PBKDF2-SHA256(암호, salt, 25만 번). salt·반복 횟수·확인용 조각은 data/study/lock.json (비밀 아님).
- 같은 파일은 늘 같은 암호문이 나오게 IV 를 HMAC(열쇠, 경로+내용 해시)로 정한다 → 바뀌지 않은 그림은 다시 올라가지 않는다.
- 잠근 결과는 .cache/study_enc/ 에 두고 원본의 크기·수정 시각이 같으면 다시 잠그지 않는다(장중 10분 배포가 가볍게).
- 화면(study.js)은 lock.json 이 있으면 암호를 물어 브라우저 안에서 풀고, 열쇠를 그 기기에 기억한다.

  python3 study_crypt.py --check     # 암호가 있는지, 잠글 파일 수·크기만 확인
"""
import base64
import hashlib
import hmac
import json
import os
import shutil
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'public' / 'data' / 'study'
CACHE = ROOT / '.cache' / 'study_enc'
SALT = ROOT / '.cache' / 'study_salt.bin'
ITER = 250_000
CHECK = b'beoms-study-ok'
# 배포에서 함께 풀어 줄 화면 파일 (publish_hold.txt 에 적힌 Study 항목)
STUDY_HOLD = {'study.html', 'js/study.js', 'js/study_chart.js', 'css/study.css', 'data/study'}


def password() -> str:
    try:
        import config  # noqa: F401  (.env → 환경변수)
    except Exception:
        pass
    return os.environ.get('STUDY_PASS', '').strip()


def _key(pw: str) -> tuple[bytes, bytes]:
    SALT.parent.mkdir(parents=True, exist_ok=True)
    if not SALT.exists():
        SALT.write_bytes(os.urandom(16))
    salt = SALT.read_bytes()
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, ITER, dklen=32), salt


def _seal(key: bytes, rel: str, data: bytes) -> bytes:
    iv = hmac.new(key, rel.encode() + hashlib.sha256(data).digest(), hashlib.sha256).digest()[:12]
    return iv + AESGCM(key).encrypt(iv, data, None)


def encrypt_into(out_study: Path, pw: str) -> tuple[int, int]:
    """public/data/study → out_study/**.enc + lock.json. (파일 수, 바이트) 를 돌려준다."""
    key, salt = _key(pw)
    tag = hashlib.sha256(key).hexdigest()[:16]          # 암호·salt 가 바뀌면 캐시를 버린다
    man_path = CACHE / 'manifest.json'
    man = json.loads(man_path.read_text()) if man_path.exists() else {}
    if man.get('_tag') != tag:
        shutil.rmtree(CACHE, ignore_errors=True)
        man = {}
    man['_tag'] = tag
    n = size = 0
    seen = set()
    for f in sorted(SRC.rglob('*')):
        if not f.is_file():
            continue
        rel = f.relative_to(SRC).as_posix()
        st = f.stat()
        sig = f'{st.st_size}:{st.st_mtime_ns}'
        enc = CACHE / (rel + '.enc')
        if man.get(rel) != sig or not enc.exists():
            enc.parent.mkdir(parents=True, exist_ok=True)
            enc.write_bytes(_seal(key, rel, f.read_bytes()))
            man[rel] = sig
        dst = out_study / (rel + '.enc')
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(enc, dst)                             # 같은 디스크면 복사 없이 연결
        except OSError:
            shutil.copy2(enc, dst)
        seen.add(rel)
        n += 1
        size += enc.stat().st_size
    for rel in [k for k in man if k != '_tag' and k not in seen]:   # 지워진 원본의 캐시 정리
        (CACHE / (rel + '.enc')).unlink(missing_ok=True)
        man.pop(rel)
    man_path.write_text(json.dumps(man))
    civ = os.urandom(12)
    lock = {'v': 1, 'kdf': 'PBKDF2-SHA256', 'iter': ITER, 'salt': base64.b64encode(salt).decode(),
            'check': base64.b64encode(civ + AESGCM(key).encrypt(civ, CHECK, None)).decode()}
    (out_study / 'lock.json').write_text(json.dumps(lock))
    return n, size


def main():
    pw = password()
    if '--check' in sys.argv:
        files = [f for f in SRC.rglob('*') if f.is_file()]
        print(f"STUDY_PASS {'있음' if pw else '없음 (.env 에 STUDY_PASS=... 를 적어야 공개 배포에 Study 가 올라간다)'}")
        print(f'잠글 파일 {len(files)}개, {sum(f.stat().st_size for f in files) / 1e6:.0f}MB')
        return 0
    if not pw:
        print('STUDY_PASS 가 없습니다 (.env)')
        return 2
    out = ROOT / '.cache' / 'study_test'
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    n, size = encrypt_into(out, pw)
    print(f'잠금 {n}개, {size / 1e6:.0f}MB → {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
