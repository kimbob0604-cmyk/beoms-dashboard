"""
구글 트렌드 검색 관심도 (trends_watch.json) → public/data/trends.json

pytrends 없이 구글 트렌드 화면이 쓰는 두 요청(explore → widgetdata/multiline)을 그대로 부른다. 공식 API 가 아니라
가끔 HTTP 429 로 막힌다 — 그때는 그 묶음만 직전 파일의 값을 그대로 둔다(덮어쓰지 않는다).

- 한 요청에 키워드 5개까지. 넘으면 anchor 키워드를 매 묶음에 같이 넣고, anchor 합이 같도록 배율을 맞춰 이어 붙인다.
- geos 가 여럿이면 나라마다 받은 지수(그 나라 안에서 0~100)를 주마다 평균한다.
- 주간(5년). 일주일에 한 번만 받는다(파일이 6일보다 오래됐을 때).
- 값은 '상대 검색지수'다. 판매량이 아니고, 묶음 사이 숫자는 비교하지 않는다.

  python3 collect_trends.py           # 6일 지났으면 받는다
  python3 collect_trends.py --force
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
CFG = ROOT / 'trends_watch.json'
OUT = ROOT / 'public' / 'data' / 'trends.json'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'
BASE = 'https://trends.google.com/trends/api'
PAUSE = 2.0
MAX_KW = 5


class TrendsError(RuntimeError):
    pass


def _json(text: str):
    return json.loads(text[text.index('{'):])        # 앞에 붙는 ")]}'," 를 뗀다


def session() -> requests.Session:
    s = requests.Session()
    s.headers['User-Agent'] = UA
    try:
        s.get('https://trends.google.com/trends/explore?geo=US', timeout=20)   # 쿠키(NID). 429 여도 쿠키는 온다
    except requests.RequestException:
        pass
    return s


def fetch(s, kws: list, geo: str, tf: str) -> tuple:
    """키워드 ≤5개의 주간 지수 → (주 시작일 목록, {kw: [값]})"""
    req = {'comparisonItem': [{'keyword': k, 'geo': geo, 'time': tf} for k in kws], 'category': 0, 'property': ''}
    for attempt in range(3):
        r = s.get(f'{BASE}/explore', params={'hl': 'en-US', 'tz': '-540', 'req': json.dumps(req)}, timeout=30)
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise TrendsError(f'explore HTTP {r.status_code}')
        w = next(x for x in _json(r.text)['widgets'] if x['id'] == 'TIMESERIES')
        time.sleep(PAUSE)
        r2 = s.get(f'{BASE}/widgetdata/multiline',
                   params={'hl': 'en-US', 'tz': '-540', 'req': json.dumps(w['request']), 'token': w['token']}, timeout=30)
        if r2.status_code != 200:
            raise TrendsError(f'multiline HTTP {r2.status_code}')
        rows = [x for x in _json(r2.text)['default']['timelineData'] if not x.get('isPartial')]   # 아직 안 끝난 주는 뺀다
        labels = [datetime.fromtimestamp(int(x['time'])).strftime('%Y-%m-%d') for x in rows]
        return labels, {k: [x['value'][i] for x in rows] for i, k in enumerate(kws)}
    raise TrendsError('HTTP 429 (요청이 많다고 막힘)')


def batches(kws: list, anchor: str = None) -> list:
    if len(kws) <= MAX_KW:
        return [kws]
    rest = [k for k in kws if k != anchor]
    return [[anchor] + rest[i:i + MAX_KW - 1] for i in range(0, len(rest), MAX_KW - 1)]


def stitch(parts: list, anchor: str) -> dict:
    """[{kw: [값]}] → anchor 합이 첫 묶음과 같도록 배율을 맞춰 합친다"""
    base = sum(parts[0][anchor]) or 1
    out = dict(parts[0])
    for p in parts[1:]:
        k = base / (sum(p[anchor]) or 1)
        out.update({kw: [round(v * k, 1) for v in vals] for kw, vals in p.items() if kw != anchor})
    return out


def blend(per_geo: list) -> dict:
    """나라별 {kw: [값]} → 주마다 평균"""
    kws = per_geo[0].keys()
    n = len(per_geo)
    return {k: [round(sum(g[k][i] for g in per_geo) / n, 1) for i in range(len(per_geo[0][k]))] for k in kws}


def collect_group(s, g: dict, tf: str) -> dict:
    kws = [x['kw'] for x in g['kws']]
    labels, per_geo = None, []
    for geo in g['geos']:
        parts = []
        for b in batches(kws, g.get('anchor')):
            lb, vals = fetch(s, b, geo, tf)
            if labels and lb != labels:
                n = min(len(lb), len(labels))
                lb, vals, labels = lb[-n:], {k: v[-n:] for k, v in vals.items()}, labels[-n:]
                per_geo = [{k: v[-n:] for k, v in x.items()} for x in per_geo]
                parts = [{k: v[-n:] for k, v in x.items()} for x in parts]
            labels = lb
            parts.append(vals)
            time.sleep(PAUSE)
        per_geo.append(stitch(parts, g['anchor']) if len(parts) > 1 else parts[0])
    v = blend(per_geo) if len(per_geo) > 1 else per_geo[0]
    return {'id': g['id'], 'label': g['label'], 'note': g.get('note'), 'geos': g['geos'], 'labels': labels,
            'series': [{**x, 'v': v[x['kw']]} for x in g['kws']], 'at': datetime.now().isoformat(timespec='seconds')}


def collect(force: bool = False, log=print) -> int:
    old = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else None
    if old and not force and datetime.now() - datetime.fromisoformat(old['built_at']) < timedelta(days=6):
        log('구글 트렌드: 6일이 안 지나 건너뜀')
        return 0
    cfg = json.loads(CFG.read_text(encoding='utf-8'))
    prev = {g['id']: g for g in (old or {}).get('groups', [])}
    s = session()
    groups, fail = [], 0
    for g in cfg['groups']:
        try:
            groups.append(collect_group(s, g, cfg['time']))
            log(f"  {g['label']}: {len(groups[-1]['labels'])}주")
        except (TrendsError, requests.RequestException, KeyError, StopIteration, ValueError) as e:
            fail += 1
            log(f"  실패 {g['label']}: {str(e)[:120]} — 직전 값 유지")
            if g['id'] in prev:
                groups.append({**prev[g['id']], 'stale': True})
    if not groups:
        return 1
    OUT.write_text(json.dumps({'built_at': datetime.now().isoformat(timespec='seconds') if not fail else (old or {}).get('built_at', datetime.now().isoformat(timespec='seconds')),
                               'time': cfg['time'], 'groups': groups}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    log(f'구글 트렌드: 묶음 {len(groups)}개, 실패 {fail}')
    return 1 if fail else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    return collect(ap.parse_args().force)


if __name__ == '__main__':
    sys.exit(main())
