"""
맥이 잘 때 공개 사이트 홈을 장중 시세로 갱신 — GitHub Actions(.github/workflows/cloud-live.yml)가 10분마다 부른다.

평소에는 맥의 live.py 가 10분마다 DB 로 home.json·quotes.json 을 다시 만들어 배포한다. 맥이 자면(덮개를 닫는 등) 사이트가
전날 밤 배포본에 멈춘다(2026-11-18 09:00~10:34). 그 사이를 이 스크립트가 맡는다: 배포본(gh-pages)의
home.json·quotes.json·live_base.json 을 읽고, 네이버 시세·지수만 새로 받아 장중 칸을 다시 계산해 그 자리에 쓴다.

다시 계산하는 칸: 지수(종가·등락·투자자별 순매수·상승/하락 수·1분봉·순매수 스냅샷(빈 시각은 다음 금융)·오늘 일봉), 시장 폭(breadth),
업종 등락, 시총 상위(big), 급등·급락(movers), 거래대금 급증(spike), quotes.json, 다른 카드 종목들의 가격·등락률.
그대로 두는 칸: 신고가·수급·리비전·목표가·공시·리포트 목록과 이동평균 시장 폭 (맥이 깨어나 다시 만든다).
계산 규칙은 build_home.py 와 같다. 기준(전일 종가·회사 시총·업종·20일 평균 거래대금)은 맥이 만든 live_base.json.

맥이 최근 15분 안에 배포했으면(home.json 의 built, by 없음) 아무것도 안 한다 — 맥이 깨어 있으면 맥 것이 우선이다.
맥이 다음에 배포하면 gh-pages 를 새로 만들어 강제 푸시하므로 여기서 올린 커밋은 자연히 사라진다.

GitHub Actions 에서 혼자 돌아야 하므로 표준 라이브러리와 collectors/naver.py(표준 라이브러리만 씀)만 쓴다.

  python3 cloud_live.py site <gh-pages 폴더> [--force]
  종료 코드: 0 갱신함(커밋할 것 있음), 10 건너뜀(장 시간 밖·휴장·맥이 갱신 중), 1 실패
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import index_snap  # noqa: E402
from collectors import naver  # noqa: E402

# build_home.py 와 같은 값
BIG = 60
SECTOR_MIN = 5
MOVER_MIN_MCAP = 3000
SPIKE_X, SPIKE_MCAP, SPIKE_AVG = 3.0, 500, 5
PERIODS = ('w1', 'm1', 'm3')
QUOTE_MIN_ROWS = 2000
INDEX = (('KOSPI', '코스피'), ('KOSDAQ', '코스닥'), ('FUT', '코스피200 선물'))
SNAP_END = {'KOSPI': '15:30', 'KOSDAQ': '15:30', 'FUT': '15:45'}
OPEN, CLOSE = '09:00', '15:50'
MAC_FRESH = timedelta(minutes=15)
DELAY = 0.3
SKIP, FAIL = 10, 1


def kst_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).replace(tzinfo=None)


class _Resp:
    def __init__(self, status, content):
        self.status_code, self.content = status, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f'HTTP {self.status_code}')

    def json(self):
        return json.loads(self.content.decode('utf-8'))


class Session:
    """collectors/naver.py 가 부르는 requests.Session.get 모양만 urllib 로"""
    def get(self, url, params=None, timeout=10):
        if params:
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        for k in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return _Resp(r.status, r.read())
            except OSError:
                if k == 2:
                    raise
                time.sleep(2)


def fetch_quotes(session) -> list:
    rows = []
    for market in ('KOSPI', 'KOSDAQ'):
        page = 1
        while True:
            res = naver.fetch_market_list(session, market, page)
            rows += res['rows']
            if page * 100 >= res['total']:
                break
            page += 1
            time.sleep(DELAY)
    return rows


def slim(c, i, **extra):
    return {'c': c, 'n': i['n'], 'mk': i['mk'], 'mc': i['mc'], 'p': i['p'], 'ch': i['ch'], 'w': i['w'], **extra}


def live_info(base: dict, quotes: list) -> dict:
    """기준 × 장중 시세 → {종목: n, mk, mc, p, ch, w, tv, av} (build_home.apply_live 와 같은 계산)"""
    ws, out = base['w'], {}
    for r in quotes:
        b = base['s'].get(r['code'])
        if not b or not r['close'] or r['change_pct'] is None:
            continue
        mk, mc, p0, wi, av = b
        out[r['code']] = {'n': r['name'], 'mk': 'KOSPI' if mk == 0 else 'KOSDAQ', 'mc': round(mc * r['close'] / p0),
                          'p': r['close'], 'ch': r['change_pct'], 'w': ws[wi] if wi >= 0 else None,
                          'tv': r['trd_val'], 'av': av}
    return out


def periods_now(old_home: dict, info: dict) -> dict:
    """옛 home 의 종목별 기간 수익률을 지금 가격으로 옮긴다: (1+w1)·(지금가/그때가) − 1"""
    out = {}
    rows = list(old_home.get('big') or [])
    for s in (old_home.get('sectors') or {}).get('all', []):
        rows += s.get('top', [])
    for r in rows:
        i = info.get(r['c'])
        if not i or not r.get('p'):
            continue
        k = i['p'] / r['p']
        out[r['c']] = {key: (round(((1 + r[key] / 100) * k - 1) * 100, 2) if r.get(key) is not None else None)
                       for key in PERIODS}
    return out


def sectors(info: dict, old: dict, per: dict) -> dict:
    """업종별 시총 가중 등락률 (build_home.build_sectors). 업종의 기간 수익률은 옛 값 그대로"""
    acc = defaultdict(lambda: [0.0, 0.0, []])
    for c, i in info.items():
        if i['w'] and i['mc']:
            a = acc[i['w']]
            a[0] += i['mc'] * i['ch']
            a[1] += i['mc']
            a[2].append((c, i))
    prev = {s['w']: s for s in (old or {}).get('all', [])}
    secs = []
    for w, (s, m, members) in acc.items():
        if len(members) < SECTOR_MIN:
            continue
        members.sort(key=lambda x: -x[1]['mc'])
        secs.append({'w': w, 'ch': round(s / m, 2), 'k': len(members), 'mc': round(m),
                     **{k: prev[w][k] for k in PERIODS if w in prev and k in prev[w]},
                     'top': [slim(c, i, **per.get(c, {k: None for k in PERIODS})) for c, i in members[:3]]})
    secs.sort(key=lambda x: -x['ch'])
    return {'all': secs, 'n': len(secs)}


def spike(info: dict) -> dict:
    rows = [slim(c, i, x=round(i['tv'] / i['av'], 1), tv=round(i['tv']), av=round(i['av']))
            for c, i in info.items()
            if i['av'] and i['av'] >= SPIKE_AVG and i['mc'] >= SPIKE_MCAP and i['tv'] >= i['av'] * SPIKE_X]
    rows.sort(key=lambda r: -r['x'])
    return {'d': None, 'live': True, 'n': len(rows), 'list': rows[:10]}


def index_entry(session, code: str, name: str, old: dict, now: datetime, daum: list = None) -> dict:
    """build_home.build_index 의 한 지수 (일봉은 옛 1년치에 오늘 봉만 바꾼다)"""
    rows = naver.fetch_index(session, code)
    time.sleep(DELAY)
    last = rows[-1]
    flow = next((r for r in reversed(rows) if r['frgn'] is not None), None)
    minute = naver.fetch_index_minute(session, code, last['date'])
    time.sleep(DELAY)
    snap = [s for s in (old or {}).get('snap', []) if (old or {}).get('d') == last['date']]
    today = now.strftime('%Y-%m-%d')
    if last['date'] == today and last['frgn'] is not None and minute:
        t = min(now.strftime('%H:%M'), SNAP_END[code], minute[-1]['t'])
        snap = sorted([s for s in snap if s[0] != t] + [[t, last['frgn'], last['org'], last['ind'], last['prog']]])
    if last['date'] == today and daum:      # 빈 시각은 다음 금융 시간대별 값으로 (index_snap.combine 규칙)
        snap = index_snap.combine(code, snap, daum)
    ohlc = {k: list(v) for k, v in ((old or {}).get('ohlc') or {'d': [], 'o': [], 'h': [], 'l': [], 'c': [], 'v': []}).items()}
    try:
        for b in naver.fetch_index_ohlc(session, code, 3):
            d = int(b['date'].replace('-', ''))
            vals = {'d': d, 'o': b['open'], 'h': b['high'], 'l': b['low'], 'c': b['close'], 'v': b['volume']}
            if ohlc['d'] and ohlc['d'][-1] == d:
                for k, v in vals.items():
                    ohlc[k][-1] = v
            elif not ohlc['d'] or ohlc['d'][-1] < d:
                for k, v in vals.items():
                    ohlc[k].append(v)
                    del ohlc[k][0]
        time.sleep(DELAY)
    except (OSError, ValueError) as e:
        print(f'  {code} 일봉 실패 (옛 값 유지): {e}')
    at = now.isoformat(timespec='seconds') if flow and flow['date'] == today else (old or {}).get('at')
    return {'c': code, 'n': name, 'd': last['date'], 'v': last['close'], 'ch': last['change_pct'],
            'fd': flow and flow['date'], 'at': at,
            'f': flow and flow['frgn'], 'o': flow and flow['org'], 'i': flow and flow['ind'], 'pg': flow and flow['prog'],
            'up': flow and flow['up'], 'dn': flow and flow['down'], 'fl': flow and flow['flat'],
            'prev': rows[-2]['close'] if len(rows) > 1 else None,
            'min': [[m['t'], m['price']] for m in minute], 'snap': snap, 'ohlc': ohlc}


def patch_rows(obj, info: dict):
    """홈의 나머지 카드(리비전·목표가·수급·신고가·공시·리포트)에 들어 있는 종목 행의 가격·시총·등락률을 지금 값으로"""
    if isinstance(obj, list):
        for x in obj:
            patch_rows(x, info)
    elif isinstance(obj, dict):
        i = info.get(obj.get('c')) if isinstance(obj.get('c'), str) else None
        if i and 'p' in obj:
            obj['p'], obj['mc'] = i['p'], i['mc']
            if obj.get('ch') is not None:
                obj['ch'] = i['ch']
        for v in obj.values():
            if isinstance(v, (list, dict)):
                patch_rows(v, info)


def update(home: dict, quotes_json: dict, base: dict, quotes: list, session, now: datetime) -> tuple:
    info = live_info(base, quotes)
    stamp = now.isoformat(timespec='seconds')
    q = {**quotes_json, '_d': now.strftime('%Y-%m-%d'), '_t': stamp,
         **{c: [i['p'], i['ch']] for c, i in info.items()}}
    per = periods_now(home, info)
    old_idx = {x['c']: x for x in home.get('idx', [])}
    daum = index_snap.fetch_daum(now.strftime('%Y-%m-%d'))
    idx = []
    for code, name in INDEX:
        try:
            idx.append(index_entry(session, code, name, old_idx.get(code), now, daum.get(code)))
        except (OSError, ValueError, KeyError) as e:
            print(f'  지수 {code} 실패 (옛 값 유지): {e}')
            if code in old_idx:
                idx.append(old_idx[code])
    big = sorted(info.items(), key=lambda x: -x[1]['mc'])[:BIG]
    movers = [(c, i) for c, i in info.items() if i['mc'] >= MOVER_MIN_MCAP]
    rest = {k: v for k, v in home.items() if k in ('rev', 'tgt', 'flow', 'high', 'dart', 'reports')}
    patch_rows(rest, info)
    out = {**home, **rest, 'built': stamp, 'live': stamp, 'by': 'cloud', 'idx': idx,
           'breadth': {m: {'up': sum(i['ch'] > 0 for i in info.values() if i['mk'] == m),
                           'dn': sum(i['ch'] < 0 for i in info.values() if i['mk'] == m),
                           'fl': sum(i['ch'] == 0 for i in info.values() if i['mk'] == m)} for m in ('KOSPI', 'KOSDAQ')},
           'sectors': sectors(info, home.get('sectors'), per),
           'spike': spike(info),
           'big': [slim(c, i, **per.get(c, {k: None for k in PERIODS})) for c, i in big],
           'movers': {'up': [slim(c, i) for c, i in sorted(movers, key=lambda x: -x[1]['ch'])[:8]],
                      'dn': [slim(c, i) for c, i in sorted(movers, key=lambda x: x[1]['ch'])[:8]]}}
    return out, q, len(info)


def mac_fresh(home: dict, now: datetime) -> bool:
    if home.get('by') == 'cloud' or not home.get('built'):
        return False
    return now - datetime.fromisoformat(home['built']) < MAC_FRESH


def site(folder: Path, force: bool = False, session=None, now=None) -> int:
    now = now or kst_now()
    hm = now.strftime('%H:%M')
    if not force and (now.weekday() >= 5 or not OPEN <= hm <= CLOSE):
        print(f'{now:%Y-%m-%d %H:%M} 장 시간 밖 — 건너뜀')
        return SKIP
    data = folder / 'data'
    try:
        home = json.loads((data / 'home.json').read_text(encoding='utf-8'))
        quotes_json = json.loads((data / 'quotes.json').read_text(encoding='utf-8'))
        base = json.loads((data / 'live_base.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        print(f'배포본 읽기 실패: {e}')
        return FAIL
    if not force and mac_fresh(home, now):
        print(f"{hm} 맥이 {home['built'][11:16]}에 배포함 — 건너뜀")
        return SKIP
    session = session or Session()
    try:
        quotes = fetch_quotes(session)
    except (OSError, ValueError, KeyError) as e:
        print(f'시세 받기 실패: {e}')
        return FAIL
    if len(quotes) < QUOTE_MIN_ROWS:
        print(f'시세 {len(quotes)}종목만 받음 — 쓰지 않음')
        return FAIL
    day = max(r['date'] for r in quotes)
    if not force and day != now.strftime('%Y-%m-%d'):
        print(f'시세 날짜 {day} — 휴장일로 보고 건너뜀')
        return SKIP
    if base.get('d') and base['d'] >= day:
        print(f"기준 {base['d']} 이 시세 날짜 {day} 보다 늦지 않음 — 맥의 장 마감 빌드가 이미 반영됨, 건너뜀")
        return SKIP
    home, q, n = update(home, quotes_json, base, quotes, session, now)
    for name, obj in (('home.json', home), ('quotes.json', q)):
        (data / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    ix = ' · '.join(f"{x['n']} {x['v']:,.2f} ({x['ch']:+.2f}%)" for x in home['idx'] if x.get('v') is not None)
    print(f'{hm} 장중 갱신: 종목 {n} · {ix}')
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == 'site':
        return site(Path(sys.argv[2]), force='--force' in sys.argv)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
