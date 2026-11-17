"""
대시보드 텔레그램 알림 공통 — 월간 수출 확정치(export_watch.py), 실적 공시 속보(earn_alert.py), 월간 의료관광(medical_alert.py)

봇은 TELEGRAM_BOT_TOKEN(이 프로젝트 .env, 없으면 stock-dashboard .env), 방은 EXPORT_TG_CHAT_ID(없으면 TELEGRAM_CHAT_ID).
EXPORT_TG_ENABLED=1 이어야 실제로 보낸다 — 이 스위치 하나로 대시보드 알림 전부를 켜고 끈다.
"""

import os

import requests

import config  # noqa: F401  (.env 를 환경변수로 올린다)


def tg_target():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat = os.environ.get('EXPORT_TG_CHAT_ID') or os.environ.get('TELEGRAM_CHAT_ID', '')
    enabled = os.environ.get('EXPORT_TG_ENABLED', '0') == '1'
    return token, chat, enabled


def send(text: str, token: str, chat: str) -> None:
    r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                      data={'chat_id': chat, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': 'true'},
                      timeout=20)
    if r.status_code != 200 or not r.json().get('ok'):
        raise RuntimeError(f'텔레그램 전송 실패 HTTP {r.status_code}: {r.text[:200]}')
