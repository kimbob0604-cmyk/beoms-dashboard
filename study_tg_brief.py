"""Study 매일 정리 뒤 텔레그램 요약: 그날 받은 리포트를 섹터별로 묶어 한 줄씩 보낸다 (2026-11-26 사용자 요청).

  python3 study_tg_brief.py 2026-11-26          # 그 날짜 받은 편지함(study_src/inbox/<날짜>.json)을 보낸다
  python3 study_tg_brief.py 2026-11-26 --dry    # 보내지 않고 메시지만 찍는다

받은 편지함 줄마다 매일 정리 세션이 적어 둔 값을 쓴다:
  done   넣은 문서 id ('·' 로 여러 개) → 문서의 섹터로 묶는다
  brief  한 줄 결론 (60~90자, 쉬운 한국어)
  call   투자의견·목표주가·톱픽 (선택, 짧게)
  skip   건너뛴 이유 → 맨 아래 '건너뜀' 줄
하우스·애널리스트·제목은 study/reports.json, 없으면 파일 이름에서 읽는다.
봇은 Beom's Macro 알림 봇을 같이 쓴다: STUDY_TG_TOKEN·STUDY_TG_CHAT (없으면 MACRO_TG_TOKEN·MACRO_TG_CHAT).
열쇠는 환경변수 → 이 폴더 .env → ~/Beom's Macro/.env 순서로 이름으로만 찾는다. 같은 날짜를 두 번 보내지 않는다(inbox 파일에 sent 기록).
"""
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
INBOX = ROOT / 'study_src' / 'inbox'
SITE = 'https://kimbob0604-cmyk.github.io/beoms-study/study.html'
ENVS = [ROOT / '.env', Path.home() / "Beom's Macro" / '.env']
WD = '월화수목금토일'


def key(*names):
    import os
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    for p in ENVS:
        if p.exists():
            for line in p.read_text(encoding='utf-8').splitlines():
                k, _, v = line.strip().partition('=')
                if k.strip() in names and v.strip():
                    return v.strip().strip('"\'')
    return ''


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sectors():
    """문서 id → (섹터 id, 섹터 이름)"""
    tree = {s['id']: s['name'] for s in load(ROOT / 'study' / 'tree.json')['sectors']}
    out = {}
    for f in (ROOT / 'study' / 'docs').glob('*.json'):
        sec = load(f).get('sector')
        out[f.stem] = (sec, tree.get(sec, sec))
    return out, list(tree)


def who(row, reports):
    r = reports.get(row['key'])
    if r:
        return r['house'], r.get('analyst') or '', r['title']
    parts = Path(row.get('name', '')).stem.split('_')        # 'LS증권_신중호,_정다운_제목_…'
    house = re.sub(r'(투자)?증권$', '', parts[0]) if parts else '?'
    names = []
    rest = parts[1:]
    while rest and (rest[0].endswith(',') or len(rest[0]) <= 4 and re.fullmatch(r'[가-힣]{2,4},?', rest[0])):
        names.append(rest.pop(0).rstrip(','))
    return house, '·'.join(names), ' '.join(rest) or row.get('name', '')


def build(day):
    p = INBOX / f'{day}.json'
    rows = load(p)
    reports = {k: v for k, v in load(ROOT / 'study' / 'reports.json').items() if not k.startswith('_')}
    doc_sec, order = sectors()
    groups, skipped, waiting = {}, [], []
    for row in rows:
        house, an, title = who(row, reports)
        label = f'{house} {an}'.strip()
        if row.get('skip'):
            skipped.append(f'{label} 「{title}」 — {row["skip"]}')
            continue
        if not row.get('done'):
            waiting.append(f'{label} 「{title}」')
            continue
        txt = str(row['done'])            # 'semi-2027·companies-semi' 또는 '1~2장 → power-2027, 3~4장 → energy-2027' 같은 문장
        docs = sorted((d for d in doc_sec if re.search(rf'(?<![\w-]){re.escape(d)}(?![\w-])', txt)), key=lambda d: txt.find(d))
        secs = []
        for d in docs:
            s = doc_sec.get(d)
            if s and s not in secs and s[0] != 'company':
                secs.append(s)
        main = secs[0] if secs else ('etc', '기타')
        groups.setdefault(main, []).append((row, label, title, [s[1] for s in secs[1:]]))
    d = date.fromisoformat(day)
    n = sum(len(v) for v in groups.values())
    L = [f'<b>오늘의 리포트 · {d.month}/{d.day}({WD[d.weekday()]})</b> — {n}건, 섹터 {len(groups)}곳']
    for (sid, sname), items in sorted(groups.items(), key=lambda kv: order.index(kv[0][0]) if kv[0][0] in order else 99):
        L += ['', f'<b>{html.escape(sname)}</b> ({len(items)}) · <a href="{SITE}?n={sid}">Study</a>']
        for row, label, title, also in items:
            line = f'• <b>{html.escape(label)}</b> 「{html.escape(title)}」'
            if row.get('brief'):
                line += f'\n  {html.escape(row["brief"])}'
            if row.get('call'):
                line += f'\n  <i>{html.escape(row["call"])}</i>'
            if also:
                line += f'\n  <i>(함께 넣은 섹터: {html.escape(", ".join(also))})</i>'
            L.append(line)
    if waiting:
        L += ['', f'<i>아직 정리 전 {len(waiting)}건: ' + html.escape(' · '.join(waiting)) + '</i>']
    if skipped:
        L += ['', f'<i>건너뜀 {len(skipped)}건: ' + html.escape(' · '.join(skipped)) + '</i>']
    return L


def chunks(lines, limit=3900):
    """텔레그램 한 메시지 4,096자 제한 — 섹터 단위로 나눈다"""
    out, cur = [], ''
    for ln in lines:
        if len(cur) + len(ln) + 1 > limit and cur:
            out.append(cur.rstrip())
            cur = ''
        cur += ln + '\n'
    if cur.strip():
        out.append(cur.rstrip())
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    day = args[0] if args else date.today().isoformat()
    dry = '--dry' in sys.argv
    p = INBOX / f'{day}.json'
    if not p.exists():
        print(f'study_tg_brief: {p.name} 없음 — 보낼 것 없음')
        return 0
    msgs = chunks(build(day))
    if dry:
        print('\n\n----- 다음 메시지 -----\n\n'.join(msgs))
        return 0
    sent_mark = INBOX / f'.sent-{day}'
    if sent_mark.exists() and '--force' not in sys.argv:
        print(f'study_tg_brief: {day} 는 이미 보냄 (--force 로 다시)')
        return 0
    token, chat = key('STUDY_TG_TOKEN', 'MACRO_TG_TOKEN'), key('STUDY_TG_CHAT', 'MACRO_TG_CHAT')
    if not token or not chat:
        print('study_tg_brief: 봇 열쇠 또는 방 번호(STUDY_TG_CHAT·MACRO_TG_CHAT)가 없어 보내지 않음')
        return 1
    for m in msgs:
        r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage', timeout=30,
                          json={'chat_id': chat, 'text': m, 'parse_mode': 'HTML', 'disable_web_page_preview': True})
        if r.status_code != 200:
            print(f'study_tg_brief: 보내기 실패 {r.status_code} {r.text[:150]}')
            return 1
    sent_mark.write_text(date.today().isoformat(), encoding='utf-8')
    print(f'study_tg_brief: {day} {len(msgs)}개 메시지 보냄')
    return 0


if __name__ == '__main__':
    sys.exit(main())
