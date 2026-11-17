"""
네이버 데이터랩 검색어 트렌드 (공식 API) — 시술·톡신 브랜드 주간 검색지수 → public/data/naver_trends.json (다올 '주간 네이버 시술 트렌드' 모양)

trends_watch.json 의 naver.groups. 데이터랩은 2026년에 네이버 클라우드 NAVER API HUB 로 옮겨 갔다 — 이 프로젝트 .env 의
NAVER_HUB_KEY_ID/NAVER_HUB_KEY(API HUB Application 의 Client ID/Secret, '검색어 트렌드' 선택)로 부른다.
없으면 예전 개발자센터 키(NAVER_CLIENT_ID/SECRET)를 쓰는데, 그 앱에는 데이터랩 권한이 없어 401 → 4 로 조용히 건너뛴다.
한 요청에 검색어 묶음 5개까지. 넘으면 anchor 를 매번 넣고 collect_trends.stitch 로 이어 붙인다. 주간, 최근 3년. 주 1회.

  python3 collect_naver_trends.py [--force]
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

import config  # noqa: F401
from collect_trends import batches, stitch

ROOT = Path(__file__).resolve().parent
CFG = ROOT / 'trends_watch.json'
OUT = ROOT / 'public' / 'data' / 'naver_trends.json'
URL = 'https://openapi.naver.com/v1/datalab/search'                       # 예전 개발자센터 (새 데이터랩 권한은 더 못 받는다)
HUB_URL = 'https://naverapihub.apigw.ntruss.com/search-trend/v1/search'    # 네이버 클라우드 NAVER API HUB (요청·응답 모양은 같다)


def endpoint() -> tuple:
    """(주소, 헤더). .env 에 NAVER_HUB_KEY_ID/NAVER_HUB_KEY 가 있으면 API HUB, 없으면 예전 개발자센터 키"""
    if os.environ.get('NAVER_HUB_KEY_ID') and os.environ.get('NAVER_HUB_KEY'):
        return HUB_URL, {'X-NCP-APIGW-API-KEY-ID': os.environ['NAVER_HUB_KEY_ID'], 'X-NCP-APIGW-API-KEY': os.environ['NAVER_HUB_KEY'],
                         'Content-Type': 'application/json'}
    return URL, {'X-Naver-Client-Id': os.environ.get('NAVER_CLIENT_ID', ''), 'X-Naver-Client-Secret': os.environ.get('NAVER_CLIENT_SECRET', ''),
                 'Content-Type': 'application/json'}


class NoScope(RuntimeError):
    pass


def fetch(kws: list, start: str, end: str) -> tuple:
    url, h = endpoint()
    body = {'startDate': start, 'endDate': end, 'timeUnit': 'week', 'keywordGroups': [{'groupName': k, 'keywords': [k]} for k in kws]}
    r = requests.post(url, headers=h, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), timeout=30)
    if r.status_code == 401:
        raise NoScope(r.json().get('errorMessage', '401'))
    r.raise_for_status()
    res = r.json()['results']
    labels = sorted({x['period'] for g in res for x in g['data']})
    vals = {g['title']: [dict((x['period'], x['ratio']) for x in g['data']).get(p, 0.0) for p in labels] for g in res}
    return labels, vals


def collect(force: bool = False, log=print) -> int:
    old = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else None
    if old and not force and datetime.now() - datetime.fromisoformat(old['built_at']) < timedelta(days=6):
        log('네이버 트렌드: 6일이 안 지나 건너뜀')
        return 0
    if not (os.environ.get('NAVER_HUB_KEY_ID') or os.environ.get('NAVER_CLIENT_ID')):
        log('네이버 트렌드: 키 없음(NAVER_HUB_KEY_ID 또는 NAVER_CLIENT_ID) — 건너뜀')
        return 4
    cfg = json.loads(CFG.read_text(encoding='utf-8')).get('naver', {})
    end = date.today()
    # 끝나지 않은 주는 뺀다: 지난 일요일까지
    end -= timedelta(days=(end.weekday() + 1) % 7 or 7)
    start = end - timedelta(days=365 * 3)
    groups = []
    for g in cfg.get('groups', []):
        kws = [x['kw'] for x in g['kws']]
        try:
            parts, labels = [], None
            for b in batches(kws, g.get('anchor')):
                labels, vals = fetch(b, start.isoformat(), end.isoformat())
                parts.append(vals)
            v = stitch(parts, g['anchor']) if len(parts) > 1 else parts[0]
        except NoScope as e:
            log(f'네이버 트렌드: 인증 실패({e}) — .env 에 NAVER API HUB 키(NAVER_HUB_KEY_ID/NAVER_HUB_KEY, 검색어 트렌드 선택)를 넣어야 한다. 건너뜀')
            return 4
        except (requests.RequestException, KeyError, ValueError) as e:
            log(f"  실패 {g['label']}: {str(e)[:120]}")
            continue
        groups.append({'id': g['id'], 'label': g['label'], 'note': g.get('note') or '네이버 검색 비율(묶음 안 최고 = 100)', 'geos': ['KR'],
                       'src': 'naver', 'labels': labels, 'series': [{**x, 'v': v[x['kw']]} for x in g['kws']],
                       'at': datetime.now().isoformat(timespec='seconds')})
    if not groups:
        return 1
    OUT.write_text(json.dumps({'built_at': datetime.now().isoformat(timespec='seconds'), 'groups': groups}, ensure_ascii=False,
                              separators=(',', ':')), encoding='utf-8')
    log(f'네이버 트렌드: 묶음 {len(groups)}개')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    return collect(ap.parse_args().force)


if __name__ == '__main__':
    sys.exit(main())
