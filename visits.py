"""
탐방 노트 정리 (순수 함수, tests/test_visits.py)

텔레그램 글 본문 → 탐방 노트인지 판별 · 어느 종목 글인지 · 제목 · 핵심 숫자 줄 · 여러 방에 전달된 같은 글 묶기.
수집은 collect_visits.py, 시총·POR 을 붙여 화면 JSON 을 만드는 일은 build_visits.py 가 한다.
"""

import hashlib
import re
from typing import Dict, List, Optional, Tuple

KEYWORD = '탐방'
MIN_LEN = 150          # 이보다 짧으면 잡담("탐방 다녀오신 분?")으로 본다
MIN_LINES = 3
TITLE_LINES = 3        # 제목 구역: 비어 있지 않은 처음 몇 줄
MAX_KEY_LINES = 8

# 종목명이지만 글에서 보통 다른 뜻으로 쓰이는 말. 제목 구역에 있거나 코드가 붙어 있을 때만 종목으로 본다.
COMMON_WORDS = {
    '대상', '선진', '전방', '미래', '상보', '신원', '진도', '서원', '대원', '국보', '남성', '세하', '나무', '레이',
    '동방', '부국', '한창', '대동', '신흥', '동원', '우진', '태양', '인지', '유니온', '동성', '성안', '원익', '코스모',
    '디아이', '서울', '경동', '삼양', '한솔', '대성', '시공', '정상', '가온', '아세아', '에스엠', '이마트', '기아',
}

_HANGUL_OR_WORD = re.compile(r'[0-9A-Za-z가-힣]')
# 짧거나 흔한 이름 뒤에 붙어도 되는 글자: 조사·괄호 (그 밖의 한글이 붙으면 다른 낱말 — '태양광' 속 '태양')
_JOSA = set('은는이가을를의에도와과로랑만')
_URL = re.compile(r'https?://\S+')
_CODE = re.compile(r'(?<![0-9A-Za-z])A?(\d{6})(?![0-9])')
# 핵심 숫자 줄: 숫자 + 단위가 있고 실적·수주·증설 같은 말이 들어간 줄
_NUM = re.compile(r'\d[\d,.]*\s?(?:조|억|만|천|원|%|배|톤|대|개|GW|MW|GWh|MWh|K|k|M|bp|달러|불)')
_TOPIC = re.compile(
    r'매출|영업이익|영익|OP\b|OPM|이익률|마진|순이익|가이던스|목표|전망|예상|컨센|수주|잔고|백로그|CAPA|캐파|케파|증설|'
    r'가동률|ASP|판가|단가|출하|물량|점유율|M/S|시총|밸류|PER|POR|PBR|배당|자사주|CB|유증|투자|CAPEX|capex|'
    r'분기|[1-4]Q|\d{2}년|20\d{2}', re.I)
_BULLET = re.compile(r'^\s*(?:[\-–—•·▶▷►■□●○◆◇*#>✅✔☑📌🔹🔸▪➡→\ufe0f]+\s*|\d{1,2}[.)]\s+)+')   # 머리 기호·번호 (본문 숫자는 남긴다)


def is_note(text: str, keywords=(KEYWORD,)) -> bool:
    """노트로 볼 만한 글인가: 키워드(기본 '탐방')가 있고, 잡담이 아닐 만큼 길다"""
    if not text or not any(k in text for k in keywords):
        return False
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return len(text.strip()) >= MIN_LEN and len(lines) >= MIN_LINES


def clean_line(ln: str) -> str:
    return _BULLET.sub('', ln).strip(' :：-–—')


def head_lines(text: str) -> List[str]:
    return [ln for ln in text.splitlines() if ln.strip()][:TITLE_LINES]


def kind(text: str, keywords=(KEYWORD,)) -> str:
    """'note' = 제목 구역(처음 세 줄)에 '탐방'이 있는 글 (탐방 노트·후기 자체),
    'mention' = 본문 어딘가에서 탐방을 언급만 한 글 (신고가 알림의 '탐방노트: …' 한 줄, 뉴스, 리포트 목록)"""
    head = '\n'.join(head_lines(text))
    return 'note' if any(k in head for k in keywords) else 'mention'


def keyword_line(text: str, keywords=(KEYWORD,)) -> str:
    """키워드가 처음 나오는 줄 (언급 글에서 보여 줄 한 줄)"""
    for ln in text.splitlines():
        if any(k in ln for k in keywords):
            t = clean_line(ln)
            return t if len(t) <= 160 else t[:159] + '…'
    return ''


def title(text: str) -> str:
    """첫 줄(머리 기호 제거). 주소뿐인 줄(노션 링크 등)은 건너뛰고, 모두 주소면 첫 주소. 너무 길면 자른다"""
    first = ''
    for ln in text.splitlines():
        t = clean_line(ln)
        if len(t) < 2:
            continue
        if _URL.fullmatch(t):
            first = first or t
            continue
        return t if len(t) <= 80 else t[:79] + '…'
    return first[:80]


def dedupe_key(text: str) -> str:
    """여러 방에 전달된 같은 글을 묶는 키: 공백·기호를 뺀 앞 400자"""
    core = re.sub(r'[^0-9A-Za-z가-힣]', '', text)[:400]
    return hashlib.sha1(core.encode('utf-8')).hexdigest()[:16]


def key_lines(text: str, limit: int = MAX_KEY_LINES) -> List[str]:
    """숫자와 실적·수주·증설 같은 말이 함께 있는 줄 (제목 줄 제외, 나온 순서대로)"""
    out, seen = [], set()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for ln in lines[1:]:
        t = clean_line(ln)
        if not (12 <= len(t) <= 160) or t in seen:
            continue
        if _NUM.search(t) and _TOPIC.search(t):
            seen.add(t)
            out.append(t)
            if len(out) >= limit:
                break
    return out


class Matcher:
    """종목명 → 코드. names: {이름: 코드} (현재 KRX 보통주 + 옛 이름)"""

    def __init__(self, names: Dict[str, str]):
        self.names = {n: c for n, c in names.items() if len(n) >= 2}
        self.codes = {}
        for n, c in self.names.items():
            self.codes.setdefault(c, n)
        # 긴 이름 먼저: '삼성전자'가 '삼성'보다 먼저 잡힌다
        alts = sorted(self.names, key=len, reverse=True)
        self.rx = re.compile('|'.join(map(re.escape, alts))) if alts else None

    def _hits(self, s: str) -> List[Tuple[str, int]]:
        """(이름, 위치). 앞 글자가 한글·영숫자면 다른 낱말의 일부로 본다 (현대상선 속 '대상')"""
        if not self.rx:
            return []
        out = []
        for m in self.rx.finditer(s):
            if m.start() and _HANGUL_OR_WORD.match(s[m.start() - 1]):
                continue
            name = m.group(0)
            nxt = s[m.end():m.end() + 1]
            if name.isascii() and nxt and re.match(r'[0-9A-Za-z]', nxt):   # 영문 이름은 뒤도 본다 (LG ≠ LGD)
                continue
            if (len(name) <= 2 or name in COMMON_WORDS) and nxt and '가' <= nxt <= '힣' and nxt not in _JOSA:
                continue                                                  # 짧은 이름 뒤 한글 (태양광 ≠ 태양)
            out.append((name, m.start()))
        return out

    def find(self, text: str) -> List[Dict]:
        """
        글에 나온 종목 [{c, n, score, head}] 점수순. 첫 번째가 그 글의 종목.
        제목 구역에 있으면 +10, 코드가 함께 적혀 있으면 +10, 본문 언급 1회당 +1.
        짧거나 흔한 말은 제목 구역·코드 표기가 있을 때만, 그 밖의 이름은 제목 구역이거나 2회 이상일 때만 인정한다.
        """
        lines = [ln for ln in text.splitlines() if ln.strip()]
        head = '\n'.join(lines[:TITLE_LINES])
        coded = {c for c in _CODE.findall(text) if c in self.codes}
        score, in_head, used = {}, set(), {}
        for name, _ in self._hits(text):
            c = self.names[name]
            score[c] = score.get(c, 0) + 1
            used.setdefault(c, set()).add(name)
        for name, _ in self._hits(head):
            in_head.add(self.names[name])
        for c in coded:
            score.setdefault(c, 0)
        out = []
        for c, n_hit in score.items():
            name = self.codes[c]
            weak = all(nm in COMMON_WORDS or len(nm) <= 2 for nm in used.get(c, ()))   # 코드만 적힌 종목은 strong
            strong = c in in_head or c in coded
            if weak and not strong:
                continue
            if not strong and n_hit < 2:
                continue
            out.append({'c': c, 'n': name, 'score': n_hit + (10 if c in in_head else 0) + (10 if c in coded else 0),
                        'head': c in in_head})
        out.sort(key=lambda x: -x['score'])
        return out


def primary(found: List[Dict]) -> Optional[Dict]:
    """글의 주인 종목. 제목 구역에 여러 종목이 나란히 있으면(탐방 일정 공지·여러 종목 묶음) 정하지 않는다."""
    if not found:
        return None
    heads = [f for f in found if f['head']]
    if len(heads) >= 4:
        return None
    top = found[0]
    if len(found) > 1 and found[1]['score'] == top['score'] and not top['head']:
        return None
    return top


def group_dupes(msgs: List[Dict]) -> List[Dict]:
    """
    같은 글(dedupe_key)이 여러 방에 있으면 가장 먼저 올라온 것 하나로 묶고 방 목록을 붙인다.
    msgs: [{'text', 'date', 'chat', ...}] → 같은 dict 에 'rooms': [방 이름…] 추가, 날짜 최신순.
    """
    by = {}
    for m in sorted(msgs, key=lambda x: x['date']):
        k = dedupe_key(m['text'])
        if k in by:
            if m['chat'] not in by[k]['rooms']:
                by[k]['rooms'].append(m['chat'])
        else:
            by[k] = {**m, 'rooms': [m['chat']]}
    return sorted(by.values(), key=lambda x: x['date'], reverse=True)
