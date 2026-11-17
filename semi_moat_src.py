"""
반도체 탭 해자(moat) 근거 문장 뽑기 (docs/semi-plan.md §3) → .cache/semi_moat_src.json

국내 종목마다 가장 최근 사업보고서 원문(펀더 수집 캐시, 없으면 DART 에서 받아 캐시)의 'II. 사업의 내용' 에서
점유율·독점·국산화·세계 최초·인증·특허·진입장벽·경쟁 요소가 든 문장을 뽑는다.
해자 문장(semi_assets.json 의 moat)은 이 문장 안에서만 쓴다 — 근거 없는 서술을 막으려고.
"""
import gzip
import html
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests

import config  # noqa: F401
from collect_fund import DOCS, document

ROOT = Path(__file__).parent
OUT = ROOT / '.cache' / 'semi_moat_src.json'
KW = [(r'점유율|M/S|시장 ?지배', 3), (r'독점|독자|유일|단독', 3), (r'세계 ?최초|국내 ?최초|업계 ?최초|최초로', 2), (r'국산화', 2),
      (r'1위|선두|최대 규모|최고 수준', 2), (r'진입 ?장벽|경쟁 ?우위|경쟁력|차별화|기술력', 1), (r'특허|인증|퀄|Qual|승인|양산 적용', 1),
      (r'HBM|AI|고대역폭|서버|데이터센터|SOCAMM|CXL|첨단 패키징|하이브리드', 1)]


def section(xml: str) -> str:
    """사업의 내용 본문 (표 글은 줄인다)"""
    t = re.sub(r'<TABLE.*?</TABLE>', ' ', xml, flags=re.S | re.I)
    t = html.unescape(re.sub(r'<[^>]+>', '\n', t))
    t = re.sub(r'[ \t　]+', ' ', t)
    i = re.search(r'II\.\s*사업의\s*내용', t)
    j = re.search(r'III\.\s*재무에\s*관한\s*사항', t[i.end():]) if i else None
    if not i:
        return ''
    return t[i.end(): i.end() + j.start()] if j else t[i.end(): i.end() + 200000]


def snippets(text: str, k: int = 12) -> list:
    sents = re.split(r'(?<=[다음함됨임])\.\s+|\n+', text)
    seen, scored = set(), []
    for s in sents:
        s = s.strip(' -·○●▶□※\t')
        if not (25 <= len(s) <= 400):
            continue
        sc = sum(w for pat, w in KW if re.search(pat, s, re.I))
        key = re.sub(r'\W', '', s)[:60]
        if sc >= 2 and key not in seen:
            seen.add(key)
            scored.append((sc, s[:320]))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:k]]


def main():
    a = json.loads((ROOT / 'semi_assets.json').read_text(encoding='utf-8'))
    cur = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    conn = sqlite3.connect(str(ROOT / 'db' / 'fund.db'))
    key = os.environ.get('DART_API_KEY', '')
    s = requests.Session()
    got = fail = 0
    for st in a['stocks']:
        code = st.get('code')
        if not code:
            continue
        r = conn.execute("SELECT rcept_no, period_end FROM fund_report WHERE code = ? AND kind = 'A' ORDER BY period_end DESC, rcept_no DESC LIMIT 1", (code,)).fetchone()
        if not r:
            cur[code] = {'n': st['n'], 'rno': None, 'snips': []}
            continue
        rno, pe = r
        if cur.get(code, {}).get('rno') == rno and cur[code].get('snips'):
            continue
        try:
            cached = (DOCS / f'{rno}.xml.gz').exists()
            xml = document(s, key, rno)
            if not cached:
                time.sleep(0.3)
        except Exception as e:
            fail += 1
            print(code, st['n'], '원문 실패', type(e).__name__)
            continue
        cur[code] = {'n': st['n'], 'rno': rno, 'period': pe, 'snips': snippets(section(xml))}
        got += 1
    OUT.write_text(json.dumps(cur, ensure_ascii=False), encoding='utf-8')
    n0 = sum(1 for v in cur.values() if not v.get('snips'))
    print(f'근거 문장: {got}종목 새로, 문장 없음 {n0}, 실패 {fail}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
