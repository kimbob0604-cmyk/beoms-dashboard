"""
실적 공시 속보 — 관심 종목의 실적 공시가 @darthacking 에 올라오면 예상치 대비와 함께 텔레그램으로 (교보·다올 채널의 공시 속보와 같은 모양)

collect_earn.py 가 장중(live.py, 10분마다)에 받아 둔 db/earn.db 의 earn_post 에서 아직 안 보낸 글만 고른다.
관심 종목 = 소비재 탭 종목(consumer_assets.json) + 월간 수출 확정치 종목(export_watch.json) + earn_alert.json 의 extra.
같은 회사·같은 분기는 처음 한 번만 보낸다(잠정실적 공정공시 뒤 분기보고서). 처음 돌릴 때는 지금까지의 글을 보낸 것으로 표시만 한다.

  python3 earn_alert.py              # 새 글 미리보기 (보내지 않음)
  python3 earn_alert.py --notify     # 새 글을 보낸다 (live.py·daily.py 가 실적 글 수집 뒤에 부른다)
"""

import argparse
import html
import json
import sqlite3
import sys
from pathlib import Path

import requests

import earn as E
from tg_notify import send, tg_target

ROOT = Path(__file__).resolve().parent
EARN_DB = ROOT / 'db' / 'earn.db'
CFG = ROOT / 'earn_alert.json'
LINK = 'https://kimbob0604-cmyk.github.io/beoms-dashboard/dart.html'
CASE = dict(E.CASES)
SCHEMA = 'CREATE TABLE IF NOT EXISTS alert_meta (k TEXT PRIMARY KEY, v TEXT)'


def watch_codes() -> dict:
    """{종목코드: 이름}"""
    out = {}
    for s in json.loads((ROOT / 'consumer_assets.json').read_text(encoding='utf-8'))['stocks']:
        out[s['code']] = s.get('name')
    for c in json.loads((ROOT / 'export_watch.json').read_text(encoding='utf-8'))['cats']:
        for it in c['items']:
            if it.get('c'):
                out.setdefault(it['c'], it['n'])
    if CFG.exists():
        for c, n in json.loads(CFG.read_text(encoding='utf-8')).get('extra', {}).items():
            out.setdefault(c, n)
    return out


def eok(v) -> str:
    if v is None:
        return '-'
    a = abs(v)
    s = f'{int(a // 10000)}조 {a % 10000:,.0f}억' if a >= 10000 else f'{a:,.0f}억'
    return ('-' if v < 0 else '') + s


def line(label: str, a, e) -> str:
    if a is None:
        return ''
    if e is None:
        return f'{label} {eok(a)}'
    r = E.ratio(a, e)
    t = E.tag(a, e, E.SALES_T if label == '매출액' else E.OP_T)
    mark = {'beat': ' 🔺', 'miss': ' 🔻'}.get(t, '')
    return f'{label} {eok(a)} (예상 {eok(e)} / {r * 100:+.0f}%){mark}' if r is not None else f'{label} {eok(a)} (예상 {eok(e)})'


def message(p: dict) -> str:
    case = E.case_of(E.tag(p['s'], p['se'], E.SALES_T), E.tag(p['o'], p['oe'], E.OP_T))
    q = p.get('period') or ''
    head = f"⚡️ <b>{html.escape(p['name'] or p['code'])}</b> {q[2:4] + 'Q' + q[-1] if len(q) == 6 else ''}"
    head += f" {'잠정' if '잠정' in (p.get('report') or '') else '실적'}" + (f' — <b>{CASE[case]}</b>' if case else '')
    rows = [line('매출액', p['s'], p['se']), line('영업이익', p['o'], p['oe']), line('순이익', p['n'], p['ne'])]
    meta = f"{p['ts'][5:16].replace('-', '/')} {E.session(p['ts'])} · 시총 {eok(p['mcap'])}" if p.get('mcap') else p['ts'][5:16]
    out = [head, meta, *[r for r in rows if r], html.escape(p.get('report') or '')]
    if p.get('rcp'):
        out.append(f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={p['rcp']}")
    return '\n'.join(out)


def pending(conn, codes: dict) -> list:
    conn.execute(SCHEMA)
    row = conn.execute("SELECT v FROM alert_meta WHERE k = 'last_id'").fetchone()
    top = conn.execute('SELECT MAX(id) FROM earn_post').fetchone()[0] or 0
    if row is None:                                   # 처음: 과거 글은 보낸 것으로
        conn.execute("INSERT OR REPLACE INTO alert_meta VALUES ('last_id', ?)", (str(top),))
        conn.commit()
        return []
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute('SELECT * FROM earn_post WHERE id > ? ORDER BY id', (int(row[0]),))]
    conn.row_factory = None
    out = []
    for r in rows:
        if r['code'] not in codes:
            continue
        # 같은 회사·같은 분기는 처음 한 번만 (잠정실적 공정공시 뒤 분기보고서가 또 올라온다)
        if r.get('period') and conn.execute('SELECT 1 FROM earn_post WHERE code = ? AND period = ? AND id < ? LIMIT 1',
                                            (r['code'], r['period'], r['id'])).fetchone():
            continue
        if any(o['code'] == r['code'] and o.get('period') == r.get('period') for o in out):
            continue
        out.append(r)
    return out


def mark(conn, last_id: int):
    conn.execute("INSERT OR REPLACE INTO alert_meta VALUES ('last_id', ?)", (str(last_id),))
    conn.commit()


def notify(conn, log=print, dry=False) -> int:
    codes = watch_codes()
    posts = pending(conn, codes)
    top = conn.execute('SELECT MAX(id) FROM earn_post').fetchone()[0] or 0
    if not posts:
        if not dry:
            mark(conn, top)
        log('실적 속보: 새 글 없음')
        return 0
    token, chat, enabled = tg_target()
    if dry or not (enabled and token and chat):
        for p in posts:
            log(message(p) + '\n')
        log(f'실적 속보: {len(posts)}건 미리보기' + ('' if dry else ' (보내기 꺼짐 — .env EXPORT_TG_ENABLED=1)'))
        return 0 if dry else 4
    for p in posts:
        try:
            send(message(p), token, chat)
        except (requests.RequestException, RuntimeError) as e:
            log(f'실적 속보 실패 {p["name"]}: {e}')
            return 1                                   # 보낸 글까지만 표시돼 있으니 다음 실행이 이어 보낸다
        mark(conn, p['id'])
    mark(conn, top)
    log(f'실적 속보: {len(posts)}건 보냄 ({", ".join(p["name"] for p in posts)})')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--notify', action='store_true')
    a = ap.parse_args()
    if not EARN_DB.exists():
        print('db/earn.db 가 없습니다 (collect_earn.py 먼저). 건너뜁니다.')
        return 4
    conn = sqlite3.connect(str(EARN_DB), timeout=60)
    return notify(conn, dry=not a.notify)


if __name__ == '__main__':
    sys.exit(main())
