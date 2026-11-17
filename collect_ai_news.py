"""
AI 인프라 새 소식 감지 (docs/semi-plan.md §11) → db/semi.db ai_news

semi_ai.json 의 feeds(엔비디아 뉴스룸·기술 블로그, 구글 클라우드 컴퓨트, AWS, MS·Azure, 메타 엔지니어링, Next Platform, SemiAnalysis, Tom's Hardware)
에서 최근 글을 받아, 가속기·랙·메모리·패키징 낱말이 든 글만 남긴다.
규격표(semi_ai.json chips·racks)에 아직 없는 이름이 나오면 'new' 표시 — 화면에서 "규격표 검토 필요"로 보인다.
규격표 자체는 사람이 출처를 보고 고친다(자동으로 숫자를 바꾸지 않는다).
"""
import html
import json
import re
import sqlite3
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent
AI = ROOT / 'semi_ai.json'
DB = ROOT / 'db' / 'semi.db'
H = {'User-Agent': "Mozilla/5.0 (Beom's Dashboard feed reader)"}

# 걸러 낼 낱말 (대소문자 무시). 묶음 이름은 화면 칩
TOPICS = {
    'GPU': r'\b(GPU|Blackwell|Rubin|Vera|GB[23]00|B[23]00|R[23]00|NVL\d+|Kyber|Feynman)\b',
    'ASIC': r'\b(TPU|Ironwood|Trainium\d?|Inferentia|Maia|MTIA|ASIC|Instinct|MI[34]\d\dX?|Helios)\b',
    '메모리': r'\b(HBM\d?E?|SOCAMM\d?|LPDDR\d?X?|GDDR7|CXL|DRAM|NAND|eSSD|KV cache)\b',
    '패키징': r'\b(CoWoS|SoIC|hybrid bond\w*|chiplet|substrate|ABF|glass core)\b',
    '네트워크': r'\b(NVLink|NVSwitch|InfiniBand|Spectrum-X|Ultra ?Ethernet|UALink|co-packaged optics|CPO|transceiver|1\.6T|3\.2T)\b',
    '전력·냉각': r'\b(800 ?V ?DC|liquid[- ]cool\w*|power shelf|gigawatt)\b',
}
# 일반 매체는 제목에 데이터센터급 낱말이 있어야 (게임용 GPU·PC 글 거르기)
GENERAL = ("Tom's Hardware", 'Next Platform', "What's New")
STRONG = r'\b(Blackwell|Rubin|Vera|GB[23]00|B[23]00|NVL\d+|TPU|Ironwood|Trainium|Maia|MTIA|Instinct|MI[34]\d\dX?|HBM\d?E?|SOCAMM|CoWoS|NVLink|data ?cent(er|re)|hyperscal\w*|AI (server|rack|factory|chip|accelerator)s?)\b'
SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_news (
    url TEXT PRIMARY KEY, src TEXT, title TEXT, date TEXT, tags TEXT, names TEXT, new TEXT, at TEXT
);
"""


def items(xml: str):
    """RSS item / Atom entry → [(제목, 링크, 날짜 iso, 요약)]"""
    out = []
    for blk in re.findall(r'<(?:item|entry)\b.*?</(?:item|entry)>', xml, re.S):
        g = lambda tag: (re.search(rf'<{tag}\b[^>]*>(.*?)</{tag}>', blk, re.S) or [None, ''])[1]
        title = html.unescape(re.sub(r'<!\[CDATA\[|\]\]>|<[^>]+>', '', g('title'))).strip()
        link = g('link').strip() or (re.search(r'<link\b[^>]*href="([^"]+)"', blk) or [None, ''])[1]
        link = re.sub(r'<!\[CDATA\[|\]\]>', '', link).strip()
        raw = g('pubDate') or g('published') or g('updated') or g('dc:date')
        try:
            d = parsedate_to_datetime(raw.strip()).date().isoformat()
        except (TypeError, ValueError):
            d = raw.strip()[:10] or None
        desc = html.unescape(re.sub(r'<!\[CDATA\[|\]\]>|<[^>]+>', ' ', g('description') or g('summary')))[:600]
        if title and link:
            out.append((title, link, d, desc))
    return out


# 제품 이름 꼴 (가족 이름 + 뒤 낱말) — 규격표 글에 없으면 새 제품으로 본다
FAMILY = r'\b(?:TPU ?v?\d+\w*(?: (?:Max|Pro|Ultra))?|Rubin(?: (?:Ultra|CPX|HPC|Max))?|Vera(?: (?:Rubin|CPU))?|Blackwell(?: Ultra)?|Feynman|Kyber|Trainium ?\d+\w*|Inferentia ?\d*|MI ?\d{3}\w*|Maia ?\d+|MTIA ?\w+|Ironwood|HBM\d\w*|SOCAMM ?\d*|NVL ?\d+|GB\d00|Spectrum-\d|ConnectX-\d+|NVLink ?\d*)\b'


def names_of(title: str) -> list:
    """제목 속 제품 이름. 'Our newest TPUs: 8tx and 8i Max' 처럼 가족 이름이 떨어져 있으면 'TPU 8tx'·'TPU 8i Max' 로 붙인다"""
    out = {m.group(0).strip() for m in re.finditer(FAMILY, title, re.I)}
    if re.search(r'\bTPUs?\b', title):
        out |= {f'TPU {m.group(0)}' for m in re.finditer(r'\b\d+(?:tx|t|i|e|p)\b(?: Max)?', title)}
    return sorted(out)


def new_names(names: list, known: str) -> list:
    """규격표 글(known_text)에 없는 이름"""
    return [x for x in names if x and x.lower().replace(' ', '') not in known]


def known_text(ai: dict) -> str:
    """규격표(칩·랙·부품)의 글 전부 — 새 제품명인지 볼 때 쓴다"""
    return json.dumps({k: ai.get(k) for k in ('chips', 'racks', 'bom', 'nv_notes')}, ensure_ascii=False).lower().replace(' ', '')


def main():
    ai = json.loads(AI.read_text(encoding='utf-8'))
    known = known_text(ai)
    conn = sqlite3.connect(str(DB))
    conn.executescript(SCHEMA)
    have = {r[0] for r in conn.execute('SELECT url FROM ai_news')}
    sess = requests.Session()
    n = fail = 0
    for f in ai.get('feeds', []):
        try:
            r = sess.get(f['rss'], headers=H, timeout=20)
            r.raise_for_status()
        except requests.RequestException as e:
            fail += 1
            print(f['n'], '실패', type(e).__name__)
            continue
        for title, link, d, desc in items(r.content.decode('utf-8', 'replace')):
            if link in have:
                continue
            text = f'{title} {desc}'
            tags = [t for t, pat in TOPICS.items() if re.search(pat, text, re.I)]
            if not tags or (any(g in f['n'] for g in GENERAL) and not re.search(STRONG, title, re.I)):
                continue
            names = names_of(title)
            new = new_names(names, known)      # 규격표에 없는 제품명 (예: Rubin HPC, TPU 8tx) — 화면은 빌드 때 다시 계산
            conn.execute('INSERT OR IGNORE INTO ai_news VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                         (link, f['n'], title, d, ','.join(tags), ','.join(names), ','.join(new),
                          datetime.now().isoformat(timespec='seconds')))
            n += 1
    conn.commit()
    print(f'AI 소식 {n}건 새로 (피드 {len(ai.get("feeds", []))}개, 실패 {fail})')
    return 1 if fail > len(ai.get('feeds', [])) // 2 else 0


if __name__ == '__main__':
    sys.exit(main())
