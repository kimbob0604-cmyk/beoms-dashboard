#!/usr/bin/env python3
"""Study 용: 텔레그램 채널 글에 붙은 PDF 를 글 번호로 골라 받는다 (로컬 전용, 커밋 안 함)

  python3 study_tg_fetch.py report_figure_by_offset 14662 14636 …      # → study_src/pdf/rg-<글번호>.pdf
  python3 study_tg_fetch.py report_figure_by_offset 14662 --list       # 받지 않고 파일 이름·크기만

- 로그인은 탐방 노트와 같은 본인 세션(db/tg_user.session, collect_visits.py login)을 쓴다.
  매일 도는 수집(daily.py)과 세션 DB 가 부딪히지 않게 세션 파일을 임시 폴더에 복사해 쓴다.
- 글 번호를 정확히 받은 것만 내려받는다. PDF 가 아닌 첨부는 건너뛴다. 받은 파일은 데이터로만 다룬다(열기·실행 없음).
- 받은 목록은 study_src/pdf/rg_index.json 에 글 번호·원래 파일 이름·크기·올라온 시각으로 쌓는다.
"""
import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

import config  # noqa: F401  (.env → 환경변수)
import collect_visits as V

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'study_src' / 'pdf'
INDEX = OUT / 'rg_index.json'


async def run(channel, ids, list_only):
    keys = V.api_keys()
    if not keys:
        print('.env 에 TG_API_ID, TG_API_HASH 가 없습니다.')
        return 2
    if not V.SESSION.exists():
        print('텔레그램 로그인이 없습니다 — collect_visits.py login 을 먼저 (본인이 직접).')
        return 4
    from telethon import TelegramClient
    tmp = Path(tempfile.mkdtemp(prefix='tgsess_'))
    shutil.copy(V.SESSION, tmp / 'tg_user.session')
    cl = TelegramClient(str(tmp / 'tg_user'), *keys, receive_updates=False, device_model="Beom's Dashboard",
                        lang_code='ko', system_lang_code='ko')
    OUT.mkdir(parents=True, exist_ok=True)
    index = json.loads(INDEX.read_text(encoding='utf-8')) if INDEX.exists() else {}
    try:
        await cl.connect()
        if not await cl.is_user_authorized():
            print('로그인이 풀려 있습니다 — collect_visits.py login 으로 본인이 다시 로그인하세요.')
            return 4
        ent = await cl.get_entity(channel)
        msgs = await cl.get_messages(ent, ids=ids)
        for mid, m in zip(ids, msgs):
            doc = getattr(m, 'document', None) if m else None
            name = getattr(getattr(m, 'file', None), 'name', None) if m else None
            if not doc or not name or not name.lower().endswith('.pdf'):
                print(f'{mid}: PDF 없음 — 건너뜀')
                continue
            size = getattr(m.file, 'size', 0)
            dst = OUT / f'rg-{mid}.pdf'
            print(f'{mid}: {name} ({size / 1e6:.1f}MB){" — 이미 있음" if dst.exists() else ""}')
            if not list_only and not dst.exists():
                await cl.download_media(m, file=str(dst))
            index[str(mid)] = {'file': dst.name, 'name': name, 'size': size, 'date': m.date.isoformat(), 'channel': channel}
        if not list_only:
            INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    finally:
        await cl.disconnect()
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('channel')
    ap.add_argument('ids', nargs='+', type=int)
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    return asyncio.run(run(a.channel, a.ids, a.list))


if __name__ == '__main__':
    sys.exit(main())
