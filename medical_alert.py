"""
월간 외국인 의료관광 소비 알림 — 데이터랩에 새 달이 들어오면 한 번 텔레그램으로 (다올 '의료관광 소비 금액 현황' 모양)

collect_medical.py 가 받은 db/trade.db 의 med 표(글로벌 = 외국인 전체)에서 전체·피부과·성형외과·약국의 금액, 전년비·전월비,
국적 상위 5개를 낸다. 처음 돌릴 때는 지금 있는 마지막 달을 보낸 것으로 표시만 한다.

  python3 medical_alert.py            # 미리보기
  python3 medical_alert.py --notify   # 새 달이면 보낸다 (daily.py 가 의료 소비 수집 뒤에 부른다)
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import requests

from tg_notify import send, tg_target

ROOT = Path(__file__).resolve().parent
TRADE_DB = ROOT / 'db' / 'trade.db'
LINK = 'https://kimbob0604-cmyk.github.io/beoms-dashboard/consumer.html#med'
CATS = ('피부과', '성형외과', '약국')
TOP = 5


def ym_add(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + k
    return f'{y + m // 12:04d}-{m % 12 + 1:02d}'


def eok(won) -> str:
    v = won / 1e8
    return f'{v / 1e4:,.2f}조' if v >= 1e4 else f'{v:,.0f}억'


def pct(a, b) -> str:
    return '–' if not a or not b else f'{(a / b - 1) * 100:+.0f}%'


def build(conn) -> dict:
    last = conn.execute("SELECT MAX(ym) FROM med WHERE nat_cd = '000'").fetchone()[0]
    if not last:
        return None
    want = (last, ym_add(last, -1), ym_add(last, -12))
    g = {}
    for ym, cat, amt in conn.execute("SELECT ym, cat, amt FROM med WHERE nat_cd = '000' AND ym IN (?,?,?)", want):
        g.setdefault(ym, {})[cat] = amt or 0
    tot = {ym: sum(v.values()) for ym, v in g.items()}
    nat = {}
    for ym, nm, amt in conn.execute("SELECT ym, nat, SUM(amt) FROM med WHERE nat_cd NOT IN ('000', '999') AND ym IN (?, ?) GROUP BY ym, nat",
                                    (last, want[2])):
        nat.setdefault(nm, {})[ym] = amt
    top = sorted(nat.items(), key=lambda kv: -(kv[1].get(last) or 0))[:TOP]
    return {'last': last, 'prev': want[1], 'py': want[2], 'g': g, 'tot': tot, 'top': top}


def message(w: dict) -> str:
    last, prev, py, g, tot = w['last'], w['prev'], w['py'], w['g'], w['tot']
    cur = g.get(last, {})
    lines = [f'<b>🏥 {last[:4]}.{int(last[5:])}월 외국인 의료관광 소비</b> <i>(한국관광 데이터랩 · 외국인 카드 결제)</i>', '',
             f"<b>전체 {eok(tot.get(last, 0))}</b> (YoY {pct(tot.get(last), tot.get(py))}, MoM {pct(tot.get(last), tot.get(prev))})"]
    for c in CATS:
        a = cur.get(c)
        if a:
            share = a / tot[last] * 100 if tot.get(last) else 0
            lines.append(f" &gt; {c} {eok(a)} (YoY {pct(a, g.get(py, {}).get(c))}, MoM {pct(a, g.get(prev, {}).get(c))}) · 비중 {share:.0f}%")
    lines += ['', '<b>국적 상위</b>']
    lines += [f" &gt; {nm} {eok(v.get(last) or 0)} (YoY {pct(v.get(last), v.get(py))})" for nm, v in w['top']]
    lines += ['', f'▶ {LINK}']
    return '\n'.join(lines)


def get_meta(conn, k):
    row = conn.execute('SELECT v FROM meta WHERE k = ?', (k,)).fetchone()
    return row[0] if row else None


def set_meta(conn, k, v):
    conn.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', (k, v))
    conn.commit()


def notify(conn, log=print) -> int:
    w = build(conn)
    if not w:
        log('의료관광 알림: 자료 없음')
        return 4
    done = get_meta(conn, 'med_notified')
    if done is None:                                  # 처음: 지금 달은 보낸 것으로
        set_meta(conn, 'med_notified', w['last'])
        log(f"의료관광 알림: 기준 {w['last']} 로 표시만 함")
        return 0
    if w['last'] <= done:
        log(f"의료관광 알림: {w['last']} 은 이미 보냈다")
        return 0
    token, chat, enabled = tg_target()
    if not (enabled and token and chat):
        log('의료관광 알림: 보내기 꺼짐. 미리보기:\n' + message(w))
        return 4
    try:
        send(message(w), token, chat)
    except (requests.RequestException, RuntimeError) as e:
        log(f'의료관광 알림 실패: {e}')
        return 1
    set_meta(conn, 'med_notified', w['last'])
    log(f"의료관광 알림: {w['last']} 보냄")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--notify', action='store_true')
    a = ap.parse_args()
    conn = sqlite3.connect(str(TRADE_DB), timeout=60)
    if a.notify:
        return notify(conn)
    w = build(conn)
    print(message(w) if w else '자료 없음')
    return 0


if __name__ == '__main__':
    sys.exit(main())
