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
