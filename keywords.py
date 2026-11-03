"""
리포트 키워드 정리 (순수 함수 — DB/네트워크 없음, 형태소 분석기 없이 동작)

1. 리포트 글(제목·소제목·본문)을 토큰으로 자른다. 조사·서술어 어미를 떼고, 숫자·기간 표기·흔한 말은 버린다.
   조사는 뗀 말이 전체 글에 따로 나온 적이 있을 때만 뗀다 ('수요가'→'수요'는 떼고 '디스플레이'는 그대로).
2. 종목의 최근 리포트에서 '여러 리포트가 함께 쓴 말'일수록, '다른 종목 리포트에는 드문 말'일수록 점수가 높다
   (리포트 수 × idf). 그래서 '실적', '영업이익' 같은 말은 저절로 밀린다.
3. 키워드마다 그 말이 들어간 문장을 최신순으로 붙인다 (근거 문장).
"""

import math
import re
from collections import Counter
from typing import Dict, Iterable, List

# 길게 맞는 것부터 (서술어 어미 → 조사 순으로 뗀다)
PRED_SUFFIXES = sorted([
    '하였다', '하였으며', '하였고', '했으며', '했고', '했다', '한다', '하며', '하고', '하는', '하여', '해야', '하기',
    '하면서', '하겠다', '할', '한', '해', '됐다', '되었다', '된다', '되며', '되고', '되는', '되어', '됐고', '되면서',
    '될', '된', '돼', '이다', '였다', '였으며', '이며', '이고', '이라는', '이라고', '적인', '적으로', '시킬', '시키는',
], key=len, reverse=True)

JOSA = sorted([
    '으로부터', '에서부터', '에게서', '으로서', '으로써', '에서는', '에서도', '에서의', '으로는', '으로도', '으로의',
    '에는', '에도', '에서', '에게', '으로', '까지', '부터', '처럼', '보다', '이나', '와의', '과의', '와는', '과는',
    '로는', '로도', '로의', '이란', '라는', '은', '는', '이', '가', '을', '를', '의', '에', '와', '과', '도', '만', '로',
], key=len, reverse=True)

STOPWORDS = set('''
동사 당사 회사 동사의 목표주가 목표가 투자의견 매수 중립 유지 상향 하향 조정 제시 전망 예상 추정 추정치 기록 대비 증가 감소
성장 성장률 개선 악화 실적 매출 매출액 영업이익 순이익 지배순이익 영업익 이익 컨센서스 분기 연간 올해 내년 전년 하반기
상반기 기존 이후 이전 이번 최근 현재 향후 기대 지속 수준 판단 가능성 영향 반영 확대 축소 회복 부진 둔화 상승 하락 리포트
시장 사업 부문 대한 위한 통해 따른 따라 관련 각각 모두 역시 또한 다만 특히 이는 이에 그리고 하지만 만큼 정도 가장 크게
다소 소폭 대폭 연속 전분기 전년동기 동기 규모 비중 효과 요인 부담 하회 상회 부합 기대치 밸류에이션 주가 억원 조원 원 배
있다 없다 있는 없는 있을 것 것으로 것이다 수 등 및 약 중 내 전 후 대 등의 때문 때문에 경우 가운데 이상 이하 미만 동안
기준 대해 위해 함께 다시 계속 아직 이미 더 덜 매우 상당 상당히 높은 낮은 높아 낮아 크게 작게 같은 다른 주요 전체 일부 신규
여전히 점차 꾸준히 본격 본격적 견조 견조한 양호 양호한 우호적 긍정적 부정적 제한적 업황 실적은 연결 별도 주당 전년비 대비해
가격 비용 수익 수익성 원가 마진 이익률 영업이익률 매출총이익 성장세 증가세 감소세 흐름 구간 시점 시기 국면 상황 환경 모멘텀
투자 투자자 업체 기업 업종 산업 섹터 제품 고객 고객사 글로벌 국내 해외 주주 주주환원 배당 하회한 상회한 부합한 전년대비
최대 최고 최저 사상 역대 기간 연도 당기 전기 적용 산출 산정 할인 할증 멀티플 목표 의견 커버리지 개시 시작 매수의견 BUY
으로 로 에 의 을 를 이 가 은 는 와 과 도 만 원으로 만원 만대 천대 만톤 억달러 달러 개월 조 억 원화기준 불구 발생 진행 가능
추가 중심 달성 견인 반면 평균 확보 인식 전환 제외 포함 감안 고려 대비로 기여 지속될 예상된다 대비해서 이어질 이어 대응
외형 강세 약세 호조 부진한 둔화된 개선된 확대된 감소한 증가한 하락한 상승한 추정된다 판단된다 전망된다 기대된다 보인다
것이 것은 내고 년대비 전년대비로 천억원 천억 억원대 조원대 영익 상단 하단 상단값 평균값 가치 서비스 상승폭 하락폭 감소폭 증가폭 기록했음 대비로는 수치
'''.split())

LATIN_STOP = {'YOY', 'QOQ', 'OPM', 'PER', 'PBR', 'EPS', 'BPS', 'ROE', 'TP', 'OP', 'NP', 'EV', 'EBITDA', 'BUY', 'HOLD',
              'SELL', 'REVIEW', 'PREVIEW', 'VS', 'THE', 'OF', 'AND', 'IN', 'TO', 'FOR', 'ON', 'BY', 'IS', 'E', 'F', 'P',
              'YTD', 'MOM', 'WOW', 'KRW', 'USD', 'BN', 'MN', 'M', 'B', 'K', 'X', 'TPM'}

# 영문 토큰 뒤에 붙은 한글은 조사('DRAM은', 'BMW향'), 한글 토큰 뒤에 붙은 영문·숫자는 이름의 일부('삼성SDI', '아이오닉3')
_TOKEN_RE = re.compile(r'[A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*[가-힣]*|[가-힣]+[A-Za-z0-9]*')
# 기간·숫자 표기: 3Q26, 4Q26F, FY27, 27F, 1H26, 2Q, F26E, 1Q26E-2Q27E …
_PERIOD_RE = re.compile(r'^(?:FY|[1-4]Q|[12]H|Q[1-4]|F)?\d*[QHFE]?\d*[FEP]?$', re.I)
_PERIOD_ANY = re.compile(r'[1-4]Q\d|Q[1-4]\d|\d{2}[EFP](?![A-Za-z])|^FY|^[1-4]Q', re.I)
_SENT_SPLIT = re.compile(r'(?<=[가-힣\)])\.\s+|(?<=다)\.|\n+')


def sentences(text: str) -> List[str]:
    return [s.strip(' ·-•') for s in _SENT_SPLIT.split(text or '') if len(s.strip()) >= 8]


def raw_tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(text or '')


def _strip_pred(tok: str) -> str:
    for suf in PRED_SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 2:
            return tok[:-len(suf)]
    return tok


def normalize(tok: str, vocab: Counter) -> str:
    """조사·서술어 어미 떼기. 한 글자 조사는 뗀 말이 vocab 에 따로 나온 적 있을 때만 뗀다."""
    if tok.startswith('차전지'):   # '2차전지' 의 숫자가 토큰에서 떨어져 나간 꼴
        return '2차전지'
    if not re.match(r'[가-힣]', tok):
        return re.sub(r'[가-힣]+$', '', tok)   # 'HBM과' → 'HBM'
    tok = _strip_pred(tok)
    for j in JOSA:
        if tok.endswith(j):
            stem = tok[:-len(j)]
            if len(stem) < 2:
                continue
            if len(j) >= 2 or vocab.get(stem, 0) > 0:
                return stem
    return tok


def keep(tok: str) -> bool:
    if len(tok) < 2 or tok in STOPWORDS or (tok[0].isdigit() and tok != '2차전지'):
        return False
    if re.match(r'[A-Za-z]', tok):
        if tok.upper() in LATIN_STOP or _PERIOD_RE.match(tok) or _PERIOD_ANY.search(tok):
            return False
        # 약어·모델명만: 대문자 2개 이상이거나 숫자 포함 ('HBM4', 'eSSD', 'K9'). 'Asset', 'Again' 같은 일반 영단어는 버림
        return sum(c.isupper() for c in tok) >= 2 or any(c.isdigit() for c in tok)
    # 서술어로 끝나면 버림 ('증가했다'처럼 떼지 못한 꼴)
    return not re.search(r'(다|며|지만|는데|면서|겠|었|았|였)$', tok)


def doc_terms(text: str, vocab: Counter) -> List[str]:
    return [t for t in (normalize(x, vocab) for x in raw_tokens(text)) if keep(t)]


def build_vocab(texts: Iterable[str]) -> Counter:
    v = Counter()
    for t in texts:
        v.update(raw_tokens(t))
    return v


def doc_freq(term_lists: Iterable[List[str]]) -> Counter:
    df = Counter()
    for terms in term_lists:
        df.update(set(terms))
    return df


def _dedupe(ranked: List[tuple]) -> List[tuple]:
    """'HBM' 과 'HBM4' 처럼 한쪽이 다른 쪽을 포함하면 점수 높은 것만 남긴다."""
    out = []
    for kw, sc in ranked:
        if any(kw in k or k in kw for k, _ in out):
            continue
        out.append((kw, sc))
    return out


def stock_keywords(reports: List[Dict], df: Counter, n_docs: int, vocab: Counter,
                   name: str = '', top: int = 8, per_kw: int = 3) -> List[Dict]:
    """
    reports: 한 종목의 최근 리포트 [{'id','date','broker','text'}] (최신순)
    name: 종목명. 종목명 조각('SK', '하이닉스')은 키워드에서 뺀다.
    → [{'kw', 'n'(언급 리포트 수), 'hits': [{'id','date','broker','s'}]}]
    """
    if not reports:
        return []
    terms = {r['id']: set(doc_terms(r['text'], vocab)) for r in reports}
    local = Counter()
    for t in terms.values():
        local.update(t)
    min_n = 2 if len(reports) >= 3 else 1
    scored = []
    for kw, n in local.items():
        # 전체 리포트에서 한 번만 나온 말(오타·어미가 남은 꼴)은 뺀다
        if n < min_n or df.get(kw, 0) < 2 or _in_name(kw, name):
            continue
        idf = math.log((n_docs + 1) / (df.get(kw, 0) + 1)) + 1
        scored.append((kw, n * idf))
    scored.sort(key=lambda x: -x[1])
    out, used = [], set()
    for kw, _ in _dedupe(scored)[:top]:
        cands = []   # (이미 다른 키워드에 쓴 문장인가, 최신순 위치, 리포트, 문장)
        for i, r in enumerate(reports):
            if kw in terms[r['id']]:
                cands += [(s in used, i, r, s) for s in sentences(r['text']) if kw in s]
        hits, seen_reports = [], set()
        # 리포트마다 한 문장, 최신순. 다른 키워드가 이미 쓴 문장은 뒤로 ('DRAM'·'NAND'가 같은 문장만 보이지 않게)
        for dup, i, r, s in sorted(cands, key=lambda c: (c[0], c[1])):
            if r['id'] in seen_reports:
                continue
            seen_reports.add(r['id'])
            if not hits:
                used.add(s)
            hits.append({'id': r['id'], 'date': r['date'], 'broker': r['broker'], 's': _clip(s, kw)})
            if len(hits) >= per_kw:
                break
        out.append({'kw': kw, 'n': local[kw], 'hits': hits})
    return out


def _in_name(kw: str, name: str) -> bool:
    n = name.replace(' ', '').upper()
    return bool(n) and (kw.upper() in n or n in kw.upper())


def report_keywords(text: str, df: Counter, n_docs: int, vocab: Counter, name: str = '',
                    prefer: Iterable[str] = (), top: int = 3) -> List[str]:
    """리포트 한 건의 키워드. 전체에서 3번 이상 나온 말만 쓰고, 종목 키워드(prefer)에 든 말을 앞세운다."""
    prefer = set(prefer)
    tf = Counter(t for t in doc_terms(text, vocab) if df.get(t, 0) >= 3 and not _in_name(t, name))

    def score(item):
        kw, n = item
        return n * (math.log((n_docs + 1) / (df.get(kw, 0) + 1)) + 1) * (2 if kw in prefer else 1)
    ranked = sorted(tf.items(), key=score, reverse=True)
    return [k for k, _ in _dedupe([(k, 0) for k, _ in ranked])[:top]]


def _clip(s: str, kw: str, width: int = 110) -> str:
    """키워드가 보이도록 문장을 width 자 안팎으로 자른다."""
    if len(s) <= width:
        return s
    i = s.find(kw)
    start = max(0, min(i - width // 3, len(s) - width))
    return ('…' if start else '') + s[start:start + width] + ('…' if start + width < len(s) else '')
