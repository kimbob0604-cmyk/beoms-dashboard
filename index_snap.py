"""
장중 지수 수급 스냅샷: 맥이 자는 동안에도 투자자별 누적 순매수(개인·외국인·기관·프로그램)를 남긴다.

네이버 지수 API 는 "지금까지의 누적 순매수"만 주고 지난 시각 값은 주지 않는다(시간별 페이지는 서비스 종료).
그래서 맥이 잠든 구간은 나중에 채울 수 없다. GitHub Actions(.github/workflows/cloud-live.yml)가 평일 장중 5분마다
take 를 돌려 저장소의 snap 브랜치에 날짜별 파일로 쌓고, 맥은 깨어난 뒤 merge 로 자기에게 없는 시각만 채운다.

빈 시각은 다음(Daum) 금융의 시간대별 누적 순매수(그날 09:01부터 1~2분 간격, 오늘 치만)로 채운다 (2026-11-18).
- 코스피·코스닥: 개인·외국인·기관 원 단위 → 억원. 같은 시각 값이 네이버와 같다(KRX 원천). 프로그램은 없어서 비워 둔다.
  네이버 스냅샷(프로그램 포함)이 있는 시각은 그대로 두고, 없는 시각만 다음 값으로.
- 코스피200 선물: 다음은 계약 수만 준다 → 계약 수 × 그 분 선물 가격 × 거래승수 25만 원 ÷ 1억 (근사, 네이버 숫자와 1~2% 안).
  네이버 선물 값은 15~20분 늦게 들어오고 시각도 늦은 분봉에 맞춰져 있어, 다음이 덮는 구간은 다음 근삿값만 쓴다.

이 파일은 GitHub Actions 에서 혼자 돌아야 하므로 표준 라이브러리만 쓴다 (프로젝트 모듈을 불러오지 않는다).

  python3 index_snap.py take <폴더>   # 지금 값을 <폴더>/YYYY-MM-DD.json 에 더한다 (장 시간 밖·휴장일은 건너뜀)
  python3 index_snap.py merge         # snap 브랜치의 최근 파일 + 다음 금융 오늘 치 → db/dashboard.db index_snap 의 빈 시각
                                      # 종료 코드: 0 채운 시각 있음, 10 없음
"""

import json
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = 'https://m.stock.naver.com/api/index/{}/integration'
CODES = ('KOSPI', 'KOSDAQ', 'FUT')          # FUT: 코스피200 선물 최근월물 (프로그램 없음)
SNAP_END = {'KOSPI': '15:30', 'KOSDAQ': '15:30', 'FUT': '15:45'}      # 마감 뒤 값은 마감 칸에 (확정 순매수)
OPEN, LAST = '09:00', '15:59'
KEEP_DAYS = 14
BRANCH = 'snap'
NOTHING = 10
MERGE_DAYS = 4                              # 맥이 며칠 자고 깨어나도 snap 브랜치의 지난 파일까지 채운다
DAUM_REF = 'https://finance.daum.net/domestic/investors'
DAUM = {'KOSPI': ('https://finance.daum.net/api/investor/KOSPI/times?page=1&perPage=500', DAUM_REF),
        'KOSDAQ': ('https://finance.daum.net/api/investor/KOSDAQ/times?page=1&perPage=500', DAUM_REF),
        'FUT': ('https://finance.daum.net/api/investor/future/times?page=1&perPage=500&terms=times&pagination=true',
                DAUM_REF + '/DERIVATIVES')}
FUT_MULT = 250_000                          # 코스피200 선물 거래승수 (원)
MINUTE_API = 'https://api.stock.naver.com/chart/domestic/index/FUT/minute?startDateTime={d}0900&endDateTime={d}1545'


def kst_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).replace(tzinfo=None)


def num(v):
    """'+3,369' → 3369.0, 값이 없으면 None"""
    try:
        return float(str(v).replace(',', '').replace('+', ''))
    except (TypeError, ValueError):
        return None


def get_json(url: str, timeout: float = 15, referer: str = None):
    h = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'}
    if referer:
        h['Referer'] = referer      # 다음 금융은 Referer 가 없으면 403
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def parse(integration: dict):
    """→ (거래일 'YYYY-MM-DD', [외국인, 기관, 개인, 프로그램] 억원). 순매수가 아직 없으면 (None, None)"""
    deal = integration.get('dealTrendInfo') or {}
    biz = str(deal.get('bizdate') or '')
    vals = [num(deal.get('foreignValue')), num(deal.get('institutionalValue')), num(deal.get('personalValue')),
            num((integration.get('programTrendInfo') or {}).get('indexTotalReal'))]
    if len(biz) != 8 or vals[0] is None:
        return None, None
    return f'{biz[:4]}-{biz[4:6]}-{biz[6:]}', vals


def daum_rows(code: str, payload: dict, day: str, fut_price=None) -> list:
    """다음 금융 시간대별 응답 → [[시각, 외국인, 기관, 개인, None]] 억원 (day 의 장중 것만, 마감 뒤 값은 마감 칸 하나로).
    선물은 fut_price(시각) → 그 분 선물 가격이 있어야 억원으로 바꿀 수 있다 (없으면 그 행은 뺀다)."""
    end, out = SNAP_END[code], {}
    for x in sorted(payload.get('data') or [], key=lambda x: x.get('date') or ''):
        d = str(x.get('date') or '')
        if d[:10] != day or d[11:16] < OPEN:
            continue
        t = min(d[11:16], end)
        if code == 'FUT':
            p = fut_price(t) if fut_price else None
            if not p:
                continue
            k = p * FUT_MULT / 1e8
            vals = [x.get('foreignSettlement'), x.get('institutionalSettlement'), x.get('privateSettlement')]
            vals = [round(v * k) if v is not None else None for v in vals]
        else:
            vals = [x.get('foreignStraightPurchasePrice'), x.get('institutionStraightPurchasePrice'),
                    x.get('individualStraightPurchasePrice')]
            vals = [round(v / 1e8) if v is not None else None for v in vals]
        if vals[0] is None:
            continue
        out[t] = [t, *vals, None]
    return [out[t] for t in sorted(out)]


def price_at(minute: list):
    """[[시각, 가격]] (시각순) → 시각 t 의 가격 (그 시각까지의 마지막 값, 그 전 값이 없으면 첫 값)"""
    def f(t):
        best = None
        for mt, p in minute:
            if mt > t:
                break
            best = p
        return best if best is not None else (minute[0][1] if minute else None)
    return f


def fetch_daum(day: str, fetch=get_json, fut_minute=None) -> dict:
    """다음 금융에서 day(오늘) 시간대별 누적 순매수 {지수: 행}. 받지 못한 지수는 빠진다.
    fut_minute: [[시각, 선물 가격]] — 없으면 네이버 선물 1분봉을 받는다."""
    out = {}
    for code, (url, ref) in DAUM.items():
        try:
            payload = fetch(url, referer=ref)
            if code == 'FUT':
                if fut_minute is None:
                    raw = fetch(MINUTE_API.format(d=day.replace('-', '')))
                    fut_minute = [[f"{r['localDateTime'][8:10]}:{r['localDateTime'][10:12]}", r['currentPrice']]
                                  for r in raw if str(r.get('localDateTime', '')).startswith(day.replace('-', ''))
                                  and r.get('currentPrice')]
                rows = daum_rows(code, payload, day, price_at(fut_minute))
            else:
                rows = daum_rows(code, payload, day)
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
            print(f'다음 {code} 받기 실패: {type(e).__name__} {e}')
            continue
        if rows:
            out[code] = rows
    return out


def combine(code: str, naver: list, daum: list) -> list:
    """같은 날 스냅샷 합치기. 코스피·코스닥은 네이버(프로그램 포함) 시각을 두고 빈 시각만 다음으로.
    선물은 다음이 덮는 구간(마지막 다음 시각까지)은 다음 근삿값만, 그 뒤 네이버 값은 남긴다."""
    if not daum:
        return sorted(naver)
    if code == 'FUT':
        last = daum[-1][0]
        return sorted(daum + [r for r in naver if r[0] > last])
    have = {r[0] for r in naver}
    return sorted(naver + [r for r in daum if r[0] not in have])


def take(folder: Path, now: datetime, fetch=get_json, force=False, daum=None) -> int:
    """지금 값을 그날 파일에 더한다. 바뀐 지수 수를 돌려준다."""
    hm, day = now.strftime('%H:%M'), now.strftime('%Y-%m-%d')
    if not force and (now.weekday() >= 5 or not OPEN <= hm <= LAST):
        print(f'{day} {hm} 장 시간 밖 — 건너뜀')
        return 0
    path = folder / f'{day}.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'date': day}
    changed = 0
    for code in CODES:
        try:
            biz, vals = parse(fetch(API.format(code)))
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f'{code} 받기 실패: {type(e).__name__} {e}')
            continue
        if biz != day:      # 휴장일이거나 개장 전 (어제 값이 남아 있다)
            print(f'{code} 거래일 {biz} ≠ 오늘 {day} — 건너뜀')
            continue
        t = min(hm, SNAP_END[code])
        rows = [r for r in data.get(code, []) if r[0] != t]
        if len(rows) != len(data.get(code, [])) and [t, *vals] in data[code]:
            continue        # 마감 뒤 같은 값을 또 받았다
        data[code] = sorted(rows + [[t, *vals]])
        changed += 1
    # 다음 금융 하루치 시계열도 같이 남긴다 (맥이 다음 날 깨어나면 다음에서는 지난 날 것을 못 받으므로)
    if daum is None and fetch is get_json:
        daum = lambda: fetch_daum(day)
    got = daum() if daum else {}
    if got and got != data.get('daum'):
        data['daum'] = got
        changed += 1
    if changed:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    old = (now - timedelta(days=KEEP_DAYS)).strftime('%Y-%m-%d')
    for f in folder.glob('20*.json'):
        if f.stem < old:
            f.unlink()
    print(f'{day} {hm} 스냅샷 {changed}개 지수')
    return changed


# ------------------------------------------------------------
# 맥: 받아 둔 스냅샷으로 빈 시각 채우기
# ------------------------------------------------------------

def remote_url(day: str) -> str:
    origin = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=ROOT, capture_output=True, text=True).stdout
    m = re.search(r'github\.com[:/]([^/]+/[^/.\s]+)', origin)
    if not m:
        raise ValueError('origin 이 GitHub 저장소가 아님')
    return f'https://raw.githubusercontent.com/{m.group(1)}/{BRANCH}/{day}.json'


def merge_daum(conn, daum: dict, day: str, upto: str = '23:59') -> int:
    """다음 금융 행으로 index_snap 을 채운다 (combine 규칙). 바뀐 행 수."""
    changed = 0
    for code, rows in daum.items():
        rows = [r for r in rows if r[0] <= upto]
        if not rows:
            continue
        have = {r[0]: list(r) for r in conn.execute(
            'SELECT t, frgn, org, ind, prog FROM index_snap WHERE date = ? AND code = ?', (day, code))}
        want = {r[0]: r for r in combine(code, list(have.values()), rows)}
        drop = [t for t in have if t not in want]
        add = [r for t, r in want.items() if have.get(t) != r]
        for t in drop:
            conn.execute('DELETE FROM index_snap WHERE date = ? AND code = ? AND t = ?', (day, code, t))
        for t, frgn, org, ind, prog in add:
            px = conn.execute('SELECT price FROM index_minute WHERE date = ? AND code = ? AND t <= ? ORDER BY t DESC LIMIT 1',
                              (day, code, t)).fetchone()
            conn.execute('INSERT OR REPLACE INTO index_snap (date, code, t, close, frgn, org, ind, prog) VALUES (?,?,?,?,?,?,?,?)',
                         (day, code, t, px[0] if px else None, frgn, org, ind, prog))
        changed += len(drop) + len(add)
    conn.commit()
    return changed


def merge(conn, data: dict, day: str, upto: str = '23:59') -> int:
    """data 의 스냅샷 가운데 index_snap 에 없는 시각만 넣는다 (맥이 직접 받은 값은 건드리지 않는다).
    close 는 그 시각까지의 1분봉 마지막 값."""
    if data.get('date') != day:
        return 0
    added = 0
    for code in CODES:
        have = {r[0] for r in conn.execute('SELECT t FROM index_snap WHERE date = ? AND code = ?', (day, code))}
        for row in data.get(code, []):
            t, frgn, org, ind, prog = row
            if t in have or t > upto:
                continue
            px = conn.execute('SELECT price FROM index_minute WHERE date = ? AND code = ? AND t <= ? ORDER BY t DESC LIMIT 1',
                              (day, code, t)).fetchone()
            conn.execute('INSERT OR IGNORE INTO index_snap (date, code, t, close, frgn, org, ind, prog) VALUES (?,?,?,?,?,?,?,?)',
                         (day, code, t, px[0] if px else None, frgn, org, ind, prog))
            added += 1
    conn.commit()
    return added


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    now = kst_now()
    if cmd == 'take' and len(sys.argv) >= 3:
        take(Path(sys.argv[2]), now, force='--force' in sys.argv)
        return 0      # 받기 실패로 워크플로를 실패시키지 않는다 (5분마다 실패 메일이 오지 않게). 기록은 실행 로그에 남는다
    if cmd == 'merge':
        today = now.strftime('%Y-%m-%d')
        conn = sqlite3.connect(str(ROOT / 'db' / 'dashboard.db'), timeout=30)
        added, notes = 0, []
        # 네이버 스냅샷이 넣은 행을 다음 금융 규칙(combine)이 다시 빼는 시각이 있어, 행 수만 보면 매번 '채움'이 된다
        # (2026-11-19 장 마감 뒤 9행이 매분 들어갔다 빠짐 → live.py 가 1분마다 홈을 다시 빌드). 실제 내용이 바뀌었는지로 판단한다.
        since = (now - timedelta(days=MERGE_DAYS)).strftime('%Y-%m-%d')
        snap_rows = lambda: set(conn.execute('SELECT date, code, t, close, frgn, org, ind, prog FROM index_snap WHERE date >= ?', (since,)))
        before = snap_rows()
        for back in range(MERGE_DAYS):
            day = (now - timedelta(days=back)).strftime('%Y-%m-%d')
            if (now - timedelta(days=back)).weekday() >= 5:
                continue
            upto = now.strftime('%H:%M') if day == today else '23:59'
            try:
                data = get_json(remote_url(day))
            except urllib.error.HTTPError as e:
                data = None
                if day == today:
                    notes.append(f'원격 스냅샷 없음 ({e.code})')
            except (urllib.error.URLError, OSError, ValueError) as e:
                data = None
                notes.append(f'{day} 원격 스냅샷 받기 실패: {type(e).__name__}')
            daum = (data or {}).get('daum') or {}
            if data:
                n = merge(conn, data, day, upto)
                added += n
                if n:
                    notes.append(f'{day} 원격 스냅샷 {n}개')
            if day == today:      # 다음 금융은 오늘 치만 준다 — 맥이 직접 받는다 (선물 가격은 맥의 1분봉)
                minute = [list(r) for r in conn.execute(
                    "SELECT t, price FROM index_minute WHERE date = ? AND code = 'FUT' ORDER BY t", (day,))]
                daum = {**daum, **fetch_daum(day, fut_minute=minute or None)}
            if daum:
                n = merge_daum(conn, daum, day, upto)
                added += n
                if n:
                    notes.append(f'{day} 다음 금융 {n}행')
        net = added and snap_rows() != before
        if added and not net:
            notes.append('결과는 전과 같음')
        print(f"{now:%H:%M:%S} " + (' · '.join(notes) if notes else '채울 시각 없음'))
        return 0 if net else NOTHING
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
