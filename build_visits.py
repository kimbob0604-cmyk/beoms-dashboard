"""
탐방 노트 탭 데이터: db/visits.db(collect_visits.py) → public/data/visits.json

- 탐방 노트로 볼 만한 글만 고르고(visits.is_note), 여러 방에 전달된 같은 글은 하나로 묶는다.
- 글마다 종목을 찾아(visits.Matcher) 종목별로 모은다. 종목을 못 정한 글은 '기타'로 둔다.
- 종목에는 지금 시총과 영업이익(전년 실적·올해·내년·내후년 추정) → POR = 시총 ÷ 영업이익 을 붙이고,
  글에는 그날의 시총(탐방 당시 시총)을 붙여 '탐방 뒤 시총이 얼마나 변했나'를 보여 준다. 주가가 아니라 시총 기준이다.
- 요약(visit_notes.json)이 있으면 붙인다:  python3 visit_notes.py pending / add

공개 배포 (2026-11-10 사용자 결정으로 탐방 탭 공개): 이 컴퓨터용 visits.json(전부)과 따로 공개용 visits_pub.json 을 만든다(public_view).
  - 주소가 없는 비공개 방의 글: 원문까지 싣는다 (사용자가 그 방 사람들의 허락을 받았다고 한 범위)
  - 주소가 있는 공개 채널의 글: 제목·날짜·방 이름·링크만 (원문은 남의 글이라 옮기지 않고 링크로 보낸다)
  - 1:1 대화의 글: 싣지 않는다 (방 이름이 개인 실명이고, 허락 범위에 들어 있지 않다)
publish.py 가 visits_pub.json 을 배포본의 data/visits.json 으로 올린다.

  python3 build_visits.py
  python3 build_visits.py --db /tmp/x.db --out /tmp/visits.json   # 시험용
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import db
import visits as V
from build_growth import company_mcaps
from build_naver import market_info, por_base
from universe import is_common

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'public' / 'data' / 'visits.json'
VISITS_DB = ROOT / 'db' / 'visits.db'
HISTORY_DB = ROOT / 'db' / 'history.db'
STRAT_DB = ROOT / 'db' / 'strategy.db'
NOTES = ROOT / 'visit_notes.json'
MAX_TEXT = 6000
# 화면에서 뺄 방 (이름 일부, 쉼표로). 예: TG_HIDE_ROOMS=AWAKE,뉴스  — 수집은 그대로 하고 화면만 뺀다
HIDE = [x.strip() for x in os.environ.get('TG_HIDE_ROOMS', '').split(',') if x.strip()]


def load_names(conn, strat: Path = STRAT_DB) -> dict:
    """종목명 → 코드. 지금 이름이 먼저고, 옛 이름(strategy.db nmhist)은 지금 이름과 겹치지 않을 때만 더한다."""
    d = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    names = {r['name']: r['code'] for r in conn.execute('SELECT code, name FROM price_daily WHERE date = ?', (d,))
             if is_common(r['code']) and r['name']}
    if strat.exists():
        s = sqlite3.connect(f'file:{strat}?mode=ro', uri=True)
        try:
            live = set(names.values())
            for name, code in s.execute('SELECT name, code FROM nmhist ORDER BY last'):   # 같은 옛 이름이면 나중 것이 남는다
                if name not in names and code in live:
                    names[name] = code
        except sqlite3.Error:
            pass
        s.close()
    return names


def mcap_then(hist, conn, code: str, day: str):
    """그날(또는 그 전 마지막 거래일)의 보통주 시총(억). 과거 DB(20년) → 없으면 최근 가격 DB"""
    if hist is not None:
        r = hist.execute('SELECT mcap FROM hp WHERE code = ? AND date <= ? AND mcap IS NOT NULL ORDER BY date DESC LIMIT 1',
                         (code, day)).fetchone()
        if r:
            return r[0]
    r = conn.execute('SELECT mcap FROM price_daily WHERE code = ? AND date <= ? ORDER BY date DESC LIMIT 1',
                     (code, day)).fetchone()
    return r[0] if r else None


def note_id(m) -> str:
    return f"{m['chat_id']}:{m['id']}"


def build(conn, vconn, hist=None, summaries=None, names=None) -> dict:
    summaries = summaries or {}
    d = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    info, _ = market_info(conn, d)
    pv = por_base(d)
    prices = {r['code']: dict(r) for r in conn.execute('SELECT code, mcap FROM price_daily WHERE date = ?', (d,))}
    company = company_mcaps(prices)
    matcher = V.Matcher(names if names is not None else load_names(conn))

    vconn.row_factory = sqlite3.Row
    raw = [dict(r) for r in vconn.execute('SELECT * FROM msg ORDER BY date')
           if not any(h in (r['chat'] or '') for h in HIDE)]
    notes = V.group_dupes([m for m in raw if V.is_note(m['text'])])
    dm_rooms = {m['chat'] for m in raw if m['chat_id'] > 0}      # 1:1 대화의 방 이름 = 상대 이름

    by_code, etc = defaultdict(list), []
    for m in notes:
        found = matcher.find(m['text'])
        main = V.primary(found)
        day = m['date'][:10]
        k = V.kind(m['text'])
        item = {
            'id': note_id(m), 'd': day, 'tm': m['date'][11:16], 't': V.title(m['text']), 'rooms': m['rooms'], 'k': k,
            'dm': m['chat_id'] > 0,     # 1:1 대화 (텔레그램 사용자 id 는 양수, 그룹·채널은 음수)
            'pub': bool(m.get('chat_user')),   # 주소(@이름)가 있는 공개 채널·그룹의 글
            'rp': [r for r in m['rooms'] if r not in dm_rooms],   # 공개용 방 목록: 같은 글이 1:1 대화에도 있었다면 그 이름은 뺀다
            'fwd': m['fwd'] or None, 'link': m['link'] or None,
            'lines': V.key_lines(m['text']) if k == 'note' else [V.keyword_line(m['text'])],
            'x': m['text'][:MAX_TEXT], 'sum': summaries.get(note_id(m)),
            'also': [{'c': f['c'], 'n': f['n']} for f in found if not main or f['c'] != main['c']][:6],
        }
        if not main:
            etc.append(item)
            continue
        c = main['c']
        then = mcap_then(hist, conn, c, day)
        common_now = (prices.get(c) or {}).get('mcap')
        if then and common_now and company.get(c):
            then *= company[c] / common_now          # 우선주 포함 회사 시총으로 맞춘다 (지금 비율로 어림)
        item['mc0'] = round(then) if then else None
        by_code[c].append(item)

    cos = []
    for c, items in by_code.items():
        i = info.get(c) or {}
        cos.append({'c': c, 'n': i.get('n') or matcher.codes.get(c), 'mk': i.get('mk'), 'w': i.get('w'),
                    'mc': i.get('mc'), 'p': i.get('p'), 'ch': i.get('ch'),
                    **(pv.get(c) or {'fy0': None, 'ops': []}), 'last': items[0]['d'], 'notes': items})
    cos.sort(key=lambda x: x['last'], reverse=True)

    rooms = defaultdict(int)
    for m in notes:
        for r in m['rooms']:
            rooms[r] += 1
    collected = vconn.execute("SELECT v FROM meta WHERE k = 'collected_at'").fetchone()
    return {
        'date': d, 'built_at': datetime.now().isoformat(timespec='seconds'),
        'collected_at': collected[0] if collected else None,
        'n_raw': len(raw), 'n_notes': len(notes), 'since': notes[-1]['date'][:10] if notes else None,
        'rooms': sorted(([k, v] for k, v in rooms.items()), key=lambda x: -x[1]),
        'cos': cos, 'etc': etc,
    }


def public_view(data: dict) -> dict:
    """공개 배포용으로 줄인 사본. 1:1 대화 글은 빼고, 공개 채널 글은 제목·날짜·방·링크만 남긴다(lim).
    비공개 방 글은 그대로 두되 전달 출처(fwd — 개인 이름일 수 있다)는 지운다."""
    def slim(n):
        n = {**{k: v for k, v in n.items() if k != 'rp'}, 'rooms': n.get('rp', n['rooms']), 'fwd': None}
        return {**n, 'x': '', 'lines': [], 'lim': True} if n.get('pub') else n

    cos = []
    for c in data['cos']:
        notes = [slim(n) for n in c['notes'] if not n.get('dm')]
        if notes:
            cos.append({**c, 'notes': notes, 'last': notes[0]['d']})
    cos.sort(key=lambda x: x['last'], reverse=True)
    etc = [slim(n) for n in data['etc'] if not n.get('dm')]
    rooms = defaultdict(int)
    for n in [n for c in cos for n in c['notes']] + etc:
        for r in n['rooms']:
            rooms[r] += 1
    n_notes = sum(len(c['notes']) for c in cos) + len(etc)
    return {**data, 'public': True, 'cos': cos, 'etc': etc, 'n_notes': n_notes, 'n_raw': None,
            'rooms': sorted(([k, v] for k, v in rooms.items()), key=lambda x: -x[1])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(VISITS_DB))
    ap.add_argument('--out', default=str(OUT))
    a = ap.parse_args()
    if not Path(a.db).exists():
        print('탐방 글 DB 가 아직 없습니다 (collect_visits.py 먼저). 건너뜁니다.')
        return 0
    conn = db.connect()
    vconn = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True)
    hist = sqlite3.connect(f'file:{HISTORY_DB}?mode=ro', uri=True) if HISTORY_DB.exists() else None
    summaries = json.loads(NOTES.read_text(encoding='utf-8')) if NOTES.exists() else {}
    data = build(conn, vconn, hist, summaries)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    pub = public_view(data)
    out.with_name(out.stem + '_pub.json').write_text(json.dumps(pub, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"visits.json: 글 {data['n_raw']}건 → 탐방 노트 {data['n_notes']}건, {len(data['cos'])}종목 + 기타 {len(data['etc'])}건"
          f" · 공개용 {pub['n_notes']}건({len(pub['cos'])}종목, 원문 포함 {sum(1 for c in pub['cos'] for n in c['notes'] if n['x']) + sum(1 for n in pub['etc'] if n['x'])}건)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
