"""
월간 수출 확정치: 관심 품목 × 회사 지역(export_watch.json) → 월·분기 표, 텔레그램 알림

관세청 시군구 × HS6 수출(db/trade.db, collect_trade.py)에서 품목마다 회사 공장·신고 지역의 금액을 더한다.
- 월: 최근 13개월 금액과 전년 동월비(YoY)·전월비(MoM)
- 분기: 진행 중인 분기(QTD, 들어온 달까지)와 지난 8개 분기, 전년 동기비·전분기비.
  QTD 의 전년비는 작년 같은 달들끼리(10월만 있으면 작년 10월과) 비교한다. 전분기비는 완결 분기만.

확정치는 매월 15일 전후에 올라온다. collect_trade.py 가 전월 확정치를 빠짐없이 받아야(실패 없이 끝난 갱신) trade.db meta 의
complete_ym 이 그 달이 되고, 여기서는 그 달까지만 쓴다(중간에 끊긴 수집으로 반쪽짜리 숫자를 보내지 않게).

알림은 새 달(complete_ym)이 처음 생긴 날 한 번만 보낸다(meta watch_notified). 봇은 .env 의 TELEGRAM_BOT_TOKEN,
방은 EXPORT_TG_CHAT_ID(없으면 TELEGRAM_CHAT_ID). EXPORT_TG_ENABLED=1 이어야 실제로 보낸다 — 아니면 미리보기만 남긴다.

  python3 export_watch.py                  # 최신 달 메시지 미리보기 (보내지 않음)
  python3 export_watch.py --notify         # 새 달이면 보낸다 (daily.py 가 수출 통계 수집 뒤에 부른다)
  python3 export_watch.py --notify --force # 이미 보낸 달이어도 다시 보낸다
  python3 export_watch.py --mark 2026-10   # 그 달은 보낸 것으로 표시만 (첫 설정 때 지난 달을 다시 보내지 않게)
"""

import argparse
import html
import json
import os
import sqlite3
import sys
from pathlib import Path

import requests

import config  # noqa: F401  (.env 를 환경변수로 올린다)
import consumer as K

ROOT = Path(__file__).resolve().parent
CFG = ROOT / 'export_watch.json'
TRADE_DB = ROOT / 'db' / 'trade.db'
N_MONTHS, N_QUARTERS = 13, 8


# ------------------------------------------------------------
# 계산
# ------------------------------------------------------------

def load_cfg(path: Path = CFG) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def ym_add(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + k
    return f'{y + m // 12:04d}-{m % 12 + 1:02d}'


def complete_ym(tconn) -> str:
    """빠짐없이 받은 마지막 달. meta complete_ym 이 없으면(예전 DB) 시군구 통계의 마지막 달"""
    row = tconn.execute("SELECT v FROM meta WHERE k = 'complete_ym'").fetchone()
    if row and row[0]:
        return row[0]
    return tconn.execute('SELECT MAX(ym) FROM sgg').fetchone()[0]


def region_series(tconn, hs6: list, regions: list, months: list) -> list:
    """그 지역들 × HS6 들의 월 금액(달러). 시군구 통계가 없는 달은 None, 있는데 그 지역 값이 없으면 0"""
    have = {r[0] for r in tconn.execute(
        'SELECT DISTINCT ym FROM sgg WHERE ym BETWEEN ? AND ?', (months[0], months[-1]))}
    out = {m: (0.0 if m in have else None) for m in months}
    q = (f'SELECT ym, sido, sgg, SUM(usd) FROM sgg WHERE hs6 IN ({",".join("?" * len(hs6))}) AND ym BETWEEN ? AND ? '
         'GROUP BY ym, sido, sgg')
    for ym, sido, sgg, usd in tconn.execute(q, (*hs6, months[0], months[-1])):
        if out.get(ym) is not None and usd and K.region_match(sido, sgg, regions):
            out[ym] += usd
    return [out[m] for m in months]


def ratio(a, b):
    return None if a is None or not b else a / b - 1


def quarter_label(ym: str) -> str:
    return f'{(int(ym[5:7]) - 1) // 3 + 1}Q{ym[2:4]}'


def quarters(months: list, v: list, n: int = N_QUARTERS) -> list:
    """[{q, v, yoy, qoq, qtd, nm}] 최근 분기부터. 진행 중인 분기는 qtd=True, nm=들어온 달 수"""
    by = dict(zip(months, v))
    last = months[-1]
    qi = (int(last[5:7]) - 1) // 3
    q_start = f'{last[:4]}-{qi * 3 + 1:02d}'
    out = []
    for k in range(n + 1):
        s = ym_add(q_start, -3 * k)
        ms = [ym_add(s, i) for i in range(3)]
        got = [m for m in ms if m <= last]
        nm = len(got)
        vals = [by.get(m) for m in got]
        if any(x is None for x in vals):
            break
        cur = sum(vals)
        py = [by.get(ym_add(m, -12)) for m in got]
        yoy = ratio(cur, sum(py)) if all(x is not None for x in py) else None
        out.append({'q': quarter_label(s), 'v': round(cur), 'yoy': yoy, 'qtd': nm < 3, 'nm': nm})
    for i, x in enumerate(out):
        nxt = out[i + 1] if i + 1 < len(out) else None
        x['qoq'] = ratio(x['v'], nxt['v']) if nxt and not x['qtd'] else None
    return out[:n + 1]


def build(tconn, cfg: dict = None) -> dict:
    """화면·메시지에 쓰는 표. 월은 최근 13개월, 분기는 QTD + 8개 분기"""
    cfg = cfg or load_cfg()
    last = complete_ym(tconn)
    span = [ym_add(last, -k) for k in range(12 * 3 + 2, -1, -1)]     # 계산용 3년+ (분기 전년비)
    cats = []
    for c in cfg['cats']:
        items = []
        for it in c['items']:
            v = region_series(tconn, it.get('hs6') or c['hs6'], it['regions'], span)
            cur, prev, py = v[-1], v[-2], v[-13]
            items.append({
                'n': it['n'], 'c': it.get('c'), 'label': it['label'], 'hs6': it.get('hs6') or c['hs6'],
                'usd': cur, 'yoy': ratio(cur, py), 'mom': ratio(cur, prev),
                'm': [None if x is None else round(x) for x in v[-N_MONTHS:]],
                'q': quarters(span, v),
            })
        cats.append({'name': c['name'], 'hs6': c['hs6'], 'items': items})
    return {'last_ym': last, 'months': span[-N_MONTHS:], 'cats': cats, 'link': cfg.get('link')}


# ------------------------------------------------------------
# 메시지
# ------------------------------------------------------------

def _musd(v) -> str:
    return '–' if v is None else f'{v / 1e6:,.1f}백만달러'


def _pct(r) -> str:
    return '–' if r is None else f'{r * 100:+.1f}%'


def message(w: dict) -> str:
    """텔레그램 HTML 본문. 품목마다 회사(지역) 금액 (YoY, MoM)"""
    y, m = w['last_ym'][:4], int(w['last_ym'][5:7])
    lines = [f'<b>📦 {y}.{m}월 수출 확정치</b> <i>(관세청 시군구 × HS6)</i>', '']
    for i, c in enumerate(w['cats'], 1):
        lines.append(f'<b>{i}. {html.escape(c["name"])}</b>')
        for it in c['items']:
            tag = '' if it['c'] else ' <i>(비상장)</i>'
            lines.append(f' &gt; {html.escape(it["n"])} {html.escape(it["label"])}{tag} '
                         f'{_musd(it["usd"])} (YoY {_pct(it["yoy"])}, MoM {_pct(it["mom"])})')
        lines.append('')
    if w.get('link'):
        lines.append(f'▶ {w["link"]}')
    return '\n'.join(lines).strip()


# ------------------------------------------------------------
# 보내기
# ------------------------------------------------------------

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


def get_meta(tconn, k: str):
    row = tconn.execute('SELECT v FROM meta WHERE k = ?', (k,)).fetchone()
    return row[0] if row else None


def set_meta(tconn, k: str, v: str) -> None:
    tconn.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', (k, v))
    tconn.commit()


def notify(tconn, force: bool = False, log=print) -> int:
    """새 달이면 보내고 0. 보낼 것 없으면 0, 설정이 꺼져 있으면 4, 실패 1"""
    w = build(tconn)
    done = get_meta(tconn, 'watch_notified')
    if not force and done and w['last_ym'] <= done:
        log(f'수출 알림: {w["last_ym"]} 은 이미 보냈다')
        return 0
    text = message(w)
    token, chat, enabled = tg_target()
    if not (enabled and token and chat):
        log(f'수출 알림: 보내기가 꺼져 있다 (.env EXPORT_TG_ENABLED=1, TELEGRAM_BOT_TOKEN, EXPORT_TG_CHAT_ID). 미리보기:\n{text}')
        return 4
    try:
        send(text, token, chat)
    except (requests.RequestException, RuntimeError) as e:
        log(f'수출 알림 실패: {e}')
        return 1
    set_meta(tconn, 'watch_notified', w['last_ym'])
    log(f'수출 알림: {w["last_ym"]} 보냄')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--notify', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--mark')
    a = ap.parse_args()
    if not TRADE_DB.exists():
        print('수출 통계 DB 가 아직 없습니다 (collect_trade.py 먼저). 건너뜁니다.')
        return 4
    tconn = sqlite3.connect(str(TRADE_DB), timeout=60)
    if a.mark:
        set_meta(tconn, 'watch_notified', a.mark)
        print(f'{a.mark} 을 보낸 것으로 표시했다')
        return 0
    if a.notify:
        return notify(tconn, a.force)
    print(message(build(tconn)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
