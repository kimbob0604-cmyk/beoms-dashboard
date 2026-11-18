#!/usr/bin/env python3
"""Study 매일 수집: 텔레그램 @report_figure_by_offset 에 새로 올라온 리포트 PDF 를 받아 섹터별 '받은 편지함'에 쌓는다

  python3 study_tg_daily.py                 # 지난번 이후 새 글 → PDF 받기 → study_src/inbox/<날짜>.json
  python3 study_tg_daily.py --list          # 받지 않고 새 글 목록만
  python3 study_tg_daily.py --since 14713   # 이 글 번호 다음부터 (처음 한 번 또는 다시 받을 때)

- 매일 18:00 예약 작업(Claude)이 이 스크립트를 먼저 돌리고, inbox 의 리포트를 섹터별로 Study 에 정리한다(docs/study-daily.md).
- 로그인은 탐방 노트와 같은 본인 세션(db/tg_user.session)을 복사해 쓴다(study_tg_fetch.py 와 같음). 로그인이 풀리면 멈추고 알린다 — 재로그인은 본인만.
- PDF 만 받는다(이미지·글은 건너뜀). 받은 파일은 데이터로만 다룬다. 원본 PDF 는 study_src/pdf (커밋 안 함).
- 섹터는 파일 이름의 낱말로 먼저 짐작한다(SECTOR_WORDS). 최종 판단은 정리하는 쪽이 표지·목차를 보고 한다.
- 표지 발간일은 build_study.py 가 study_reports.py 로 자동으로 읽는다.
"""
import argparse
import asyncio
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config  # noqa: F401  (.env → 환경변수)
import collect_visits as V

ROOT = Path(__file__).resolve().parent
PDF = ROOT / 'study_src' / 'pdf'
INDEX = PDF / 'rg_index.json'
SEEN = PDF / 'rg_seen.json'
INBOX = ROOT / 'study_src' / 'inbox'
CHANNEL = 'report_figure_by_offset'
KST = timezone(timedelta(hours=9))
MAX_MB = 80          # 이보다 큰 PDF 는 받지 않고 목록에만 적는다
# 섹터 짐작 (앞에 있는 섹터가 먼저 걸린다). 트리 섹터 id = study/tree.json
SECTOR_WORDS = [
    ('semi', ['반도체', '소부장', 'HBM', '메모리', '후공정', '디스플레이', 'IT소재', '파운드리']),
    ('energy', ['2차전지', '이차전지', '배터리', 'ESS', '정유', '석유화학', '석유', '화학']),
    ('power', ['유틸리티', '전력', '원전', '신재생', '태양광', '풍력', '수소', '에너지']),
    ('bio', ['제약', '바이오', '헬스케어', '의료', '비만', '신약']),
    ('cons', ['음식료', '화장품', '유통', '소매', '패션', '담배', '면세', '소비', '뷰티', '의류']),
    ('media', ['엔터', '미디어', '게임', '플랫폼', '통신', '인터넷', '콘텐츠', '광고', '레저', '카지노']),
    ('mobility', ['자동차', '로봇', '로보틱스', '모빌리티', '타이어', '자율주행', '휴머노이드']),
    ('industrials', ['건설', '조선', '운송', '해운', '항공', '철강', '금속', '비철', '기계', '방산', '방위', '부동산', '리츠', '우주']),
    ('fin', ['은행', '보험', '증권', '지주', '금융', '카드']),
    ('smid', ['스몰캡', '미드', '코스닥', '중소형']),
    ('strategy', ['전략', '주식시장', '시장 전망', '자산배분', '경제', '매크로', '채권', '금리', '환율', 'FICC', '퀀트', 'ETF',
                  '크레딧', '원자재', 'Quant', '시황', '투자전략']),
]


STRONG = ('strategy', ['투자전략', '퀀트', 'Quant', '자산배분', '주식시장', 'ETF', '파생', '채권', 'FICC', '경제', '매크로'])


def _topic(name: str) -> str:
    """파일 이름에서 증권사·애널리스트를 뺀 주제 부분 ('교보증권_정희령_…' 의 '증권' 이 금융으로 잡히지 않게)"""
    n = re.sub(r'\.pdf$', '', name)
    n = re.sub(r'^\[[^\]]*\]_?', '', n)
    bits = n.split('_')
    if bits and re.search(r'(증권|투자|리서치|Securities)', bits[0]):
        bits = bits[1:]
        if bits and re.fullmatch(r'[가-힣]{2,4},?', bits[0]):   # 애널리스트 이름 ('이진명,' '김명주' 처럼 쉼표로 이어지면 계속)
            while bits and bits[0].endswith(','):
                bits = bits[1:]
            bits = bits[1:]
    return ' '.join(bits)


def guess_sector(name: str) -> str:
    n = _topic(name)
    if any(w.lower() in n.lower() for w in STRONG[1]):
        return STRONG[0]
    for sec, words in SECTOR_WORDS:
        if any(w.lower() in n.lower() for w in words):
            return sec
    return 'other'


def last_seen() -> int:
    if SEEN.exists():
        return int(json.loads(SEEN.read_text())['last_id'])
    if INDEX.exists():
        return max(int(k) for k in json.loads(INDEX.read_text(encoding='utf-8')))
    return 0


async def run(since: int, list_only: bool) -> int:
    keys = V.api_keys()
    if not keys:
        print('.env 에 TG_API_ID, TG_API_HASH 가 없습니다.')
        return 2
    if not V.SESSION.exists():
        print('텔레그램 로그인이 없습니다 — collect_visits.py login 을 본인이 직접.')
        return 4
    from telethon import TelegramClient
    tmp = Path(tempfile.mkdtemp(prefix='tgsess_'))
    shutil.copy(V.SESSION, tmp / 'tg_user.session')
    cl = TelegramClient(str(tmp / 'tg_user'), *keys, receive_updates=False, device_model="Beom's Dashboard",
                        lang_code='ko', system_lang_code='ko')
    PDF.mkdir(parents=True, exist_ok=True)
    index = json.loads(INDEX.read_text(encoding='utf-8')) if INDEX.exists() else {}
    new, top = [], since
    known = {v['name']: f'rg-{k}' for k, v in index.items()}
    if (PDF / 'dl_index.json').exists():
        known.update({v['name']: k for k, v in json.loads((PDF / 'dl_index.json').read_text(encoding='utf-8')).items()})
    try:
        await cl.connect()
        if not await cl.is_user_authorized():
            print('로그인이 풀려 있습니다 — collect_visits.py login 으로 본인이 다시 로그인하세요.')
            return 4
        ent = await cl.get_entity(CHANNEL)
        async for m in cl.iter_messages(ent, min_id=since, reverse=True, limit=500):
            top = max(top, m.id)
            name = getattr(getattr(m, 'file', None), 'name', None)
            if not getattr(m, 'document', None) or not name or not name.lower().endswith('.pdf'):
                continue
            size = getattr(m.file, 'size', 0) or 0
            dst = PDF / f'rg-{m.id}.pdf'
            row = {'id': m.id, 'key': f'rg-{m.id}', 'name': name, 'size_mb': round(size / 1e6, 1),
                   'date': m.date.astimezone(KST).isoformat(timespec='minutes'), 'sector': guess_sector(name)}
            dup = known.get(name)
            if dup and dup != row['key']:
                row['dup'] = dup        # 이미 받은 리포트(파일로 받은 dl-… 포함) — 다시 정리하지 않는다
            elif size > MAX_MB * 1e6:
                row['skipped'] = f'{MAX_MB}MB 초과'
            elif not list_only and not dst.exists():
                await cl.download_media(m, file=str(dst))
            if not list_only and dst.exists():
                index[str(m.id)] = {'file': dst.name, 'name': name, 'size': size, 'date': m.date.isoformat(), 'channel': CHANNEL}
            new.append(row)
    finally:
        await cl.disconnect()
        shutil.rmtree(tmp, ignore_errors=True)
    for r in new:
        print(f"{r['date'][:16]} {r['id']} {r['size_mb']:>5}MB [{r['sector']}] {r['name'][:70]}{' (' + r['skipped'] + ')' if r.get('skipped') else ''}{' (이미 있음: ' + r['dup'] + ')' if r.get('dup') else ''}")
    print(f'새 PDF {len(new)}건 (글 번호 {since} 다음 ~ {top})')
    if not list_only:
        INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
        SEEN.write_text(json.dumps({'last_id': top, 'at': datetime.now(KST).isoformat(timespec='minutes')}))
        if new:
            INBOX.mkdir(parents=True, exist_ok=True)
            day = datetime.now(KST).strftime('%Y-%m-%d')
            box = INBOX / f'{day}.json'
            old = json.loads(box.read_text(encoding='utf-8')) if box.exists() else []
            seen = {r['id'] for r in old}
            box.write_text(json.dumps(old + [r for r in new if r['id'] not in seen], ensure_ascii=False, indent=1), encoding='utf-8')
            print(f'받은 편지함 → {box.relative_to(ROOT)}')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', type=int)
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    return asyncio.run(run(a.since if a.since is not None else last_seen(), a.list))


if __name__ == '__main__':
    sys.exit(main())
