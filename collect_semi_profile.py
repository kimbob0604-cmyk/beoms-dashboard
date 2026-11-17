"""
반도체 밸류체인 국내 후보 종목의 회사 개요·주요 제품 매출 구성 (FnGuide/WiseReport 기업개요 화면) → .cache/semi_profile.json
칸 배정(semi_assets.json)의 근거 자료. 한 번 받고, --refresh 로 다시.

후보: 네이버 업종 '반도체와반도체장비'·'전자장비와기기'·'디스플레이장비및부품'·'통신장비'·'컴퓨터와주변기기'·'전자제품'·'전기장비'·'전기제품'
     + KBJ sector_map 의 반도체 5칸 + 이미 semi_assets.json 에 있는 국내 종목
"""
import argparse
import html
import json
import re
import sqlite3
import time
from pathlib import Path

import requests

from collectors import wisereport as wr

ROOT = Path(__file__).parent
OUT = ROOT / '.cache' / 'semi_profile.json'
SECTORS = ('반도체와반도체장비', '전자장비와기기', '디스플레이장비및부품', '통신장비', '컴퓨터와주변기기', '전자제품', '전기장비', '전기제품')
KBJ_MAP = Path.home() / 'kbj' / 'config' / 'knowledge' / 'sector_map.yaml'
H = {'User-Agent': 'Mozilla/5.0'}


def candidates() -> dict:
    """{code: {n, nv(네이버 업종), kbj(kbj 칸), why}}"""
    names = {x[0]: x[1] for x in json.loads((ROOT / 'public' / 'data' / 'names.json').read_text(encoding='utf-8'))}
    c = sqlite3.connect(str(ROOT / 'db' / 'dashboard.db'))
    nv = {r[0]: r[1] for r in c.execute('SELECT code, name FROM naver_sector')}
    kb = {}
    if KBJ_MAP.exists():
        import yaml
        kb = yaml.safe_load(KBJ_MAP.read_text(encoding='utf-8')).get('map', {})
    out = {}
    for code, n in names.items():
        k = kb.get(code) or {}
        if nv.get(code) in SECTORS or (k.get('sector') or '').startswith('반도체'):
            out[code] = {'n': n, 'nv': nv.get(code), 'kbj': k.get('sector'), 'why': k.get('why')}
    a = json.loads((ROOT / 'semi_assets.json').read_text(encoding='utf-8'))
    for s in a['stocks']:
        if s.get('code') and s['code'] not in out:
            out[s['code']] = {'n': s['n'], 'nv': nv.get(s['code']), 'kbj': (kb.get(s['code']) or {}).get('sector'), 'why': None}
    return out


def clean(s: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s))).strip()


def profile(sess, code: str) -> dict:
    t1 = sess.get(wr.OVERVIEW_URL, params={'cmp_cd': code}, headers=H, timeout=10).text
    m = re.search(r'cmp_comment">(.*?)</(?:ul|div)>', t1, re.S)
    comment = clean(m.group(1))[:600] if m else ''
    t2 = sess.get(wr.BASE + '/v2/company/c1020001.aspx', params={'cmp_cd': code}, headers=H, timeout=10).text
    mix = []
    m = re.search(r'var chartData1 = (\[.*?\]);', t2, re.S)
    if m:
        try:
            mix = [[str(a), float(b)] for a, b in json.loads(m.group(1))]
        except (ValueError, TypeError):
            mix = []
    asof = re.search(r'주요제품 매출구성\((\d{4} / \d{2})\)', t2)
    return {'comment': comment, 'mix': mix, 'mix_asof': asof.group(1).replace(' ', '') if asof else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true')
    args = ap.parse_args()
    cur = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() and not args.refresh else {}
    cands = candidates()
    sess = requests.Session()
    n = fail = 0
    for code, c in cands.items():
        if code in cur and cur[code].get('comment'):
            cur[code].update(c)
            continue
        try:
            cur[code] = {**c, **profile(sess, code)}
            n += 1
        except requests.RequestException as e:
            fail += 1
            print(code, c['n'], '실패', type(e).__name__)
        time.sleep(0.2)
        if n % 50 == 0:
            OUT.parent.mkdir(exist_ok=True)
            OUT.write_text(json.dumps(cur, ensure_ascii=False), encoding='utf-8')
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(cur, ensure_ascii=False), encoding='utf-8')
    print(f'후보 {len(cands)} · 새로 받음 {n} · 실패 {fail}')


if __name__ == '__main__':
    main()
