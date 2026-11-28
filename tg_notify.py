"""
텔레그램 알림 공통 — 지금은 실적 공시 속보(earn_alert.py)만 쓴다.

2026-11-26 부터 소비재 알림(실적 속보·월간 수출 확정치·의료관광·데일리 브리프)은 전용 봇 @beomjun_consumer_bot 하나로 간다.
설정은 ~/Beom's Consumer/.env 의 CONSUMER_TG_TOKEN · CONSUMER_TG_CHAT · CONSUMER_TG_ENABLED(=1 이어야 보냄)이고,
환경변수에 같은 이름이 있으면 그것이 먼저다. 옛 공용 봇(TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID·EXPORT_TG_ENABLED)으로는
더 이상 넘어가지 않는다 — 전용 값이 비어 있으면 보내지 않고 미리보기만 남긴다.
"""

import os
from pathlib import Path

import requests

import config  # noqa: F401  (.env 를 환경변수로 올린다)

CONSUMER_ENV = Path.home() / "Beom's Consumer" / '.env'


def _consumer_env() -> dict:
    out = {}
    if CONSUMER_ENV.exists():
        for line in CONSUMER_ENV.read_text(encoding='utf-8').splitlines():
            k, _, v = line.strip().partition('=')
            if k and not k.startswith('#'):
                out[k.strip()] = v.strip().strip('"\'')
    return out


def tg_target():
    """(토큰, 방, 켜짐) — Beom's Consumer 봇 설정 (그 폴더 bot.tg_target 과 같은 규칙)"""
    f = _consumer_env()
    get = lambda k: (os.environ.get(k) or f.get(k) or '').strip()  # noqa: E731
    return get('CONSUMER_TG_TOKEN'), get('CONSUMER_TG_CHAT'), get('CONSUMER_TG_ENABLED') == '1'


def send(text: str, token: str, chat: str) -> None:
    r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                      data={'chat_id': chat, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': 'true'},
                      timeout=20)
    if r.status_code != 200 or not r.json().get('ok'):
        raise RuntimeError(f'텔레그램 전송 실패 HTTP {r.status_code}: {r.text[:200]}')
