"""환경변수 로딩: 프로젝트 .env → 없으면 기존 stock-dashboard/.env (키 재사용)"""

import os
from pathlib import Path

ROOT = Path(__file__).parent
_ENV_FILES = [ROOT / '.env', Path.home() / 'stock-dashboard' / '.env']


def _load_env():
    for path in _ENV_FILES:
        if not path.exists():
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"\''))


_load_env()

KRX_API_KEY = os.environ.get('KRX_API_KEY', '')


def _other_key(path: Path, name: str) -> str:
    """다른 프로젝트 .env 에서 키 하나만 읽는다 (그 파일의 나머지 값은 환경변수로 올리지 않는다)"""
    if not path.exists():
        return ''
    for line in path.read_text(encoding='utf-8').splitlines():
        k, _, v = line.strip().partition('=')
        if k.strip() == name:
            return v.strip().strip('"\'')
    return ''


# 공공데이터포털(관세청 수출입) 키: 이 프로젝트 .env 의 DATAGO_KEY, 없으면 KBJ 프로젝트의 KBJ_DATAGO_KEY 를 같이 쓴다
DATAGO_KEY = os.environ.get('DATAGO_KEY') or _other_key(Path.home() / 'kbj' / '.env', 'KBJ_DATAGO_KEY')
