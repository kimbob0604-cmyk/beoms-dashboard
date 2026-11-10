"""
전략 트래커: 어떤 글이 어느 시리즈인지 가르고, 시리즈별로 종목·방향·비중을 뽑는다 (순수 함수 — 네트워크·DB 없음)

파서는 (본문 글자, NameIndex, 글 날짜) → [{'code','name','side','weight','grp'}] 를 돌려준다.
side: 'L'(사라) / 'S'(팔아라·피하라). weight 는 리포트가 비중을 적은 경우만(%), 없으면 None → 같은 금액.
원문 문장은 남기지 않는다. 종목과 방향만 꺼낸다.
"""

import re
from datetime import datetime, timedelta

# 시리즈 정의. kind: 'port' = 다음 호가 나올 때까지 그 목록을 들고 간다 / 'signal' = 종목마다 신호일부터 정해진 기간 보유
SERIES = {
    'hana_qmp': {'l': '하나 실전 퀀트 MP', 'house': '하나증권', 'kind': 'port', 'cycle': '월',
                 'd': '하나증권 퀀트 모델 포트폴리오. 리포트의 종목별 비중 그대로, 다음 호가 나올 때 교체',
                 'how': '코스피 종목을 실적·주가 흐름·수급·가치·배당 점수로 평가해 34종목 안팎을 담는다. 종목마다 코스피 비중보다 얼마나 더 실을지 정하고, 매달 말 리포트에서 바꾼다.'},
    'daishin_top10': {'l': '대신 국내 주식 10선', 'house': '대신증권', 'kind': 'port', 'cycle': '월',
                      'd': '대신증권 "투자 유망 주식/ETF/펀드"의 국내 주식 10선. 같은 금액씩, 다음 호가 나올 때 교체',
                 'how': '대신증권 리서치센터가 시장 전망과 함께 고르는 국내 주식 10개다. 한 번 넣으면 몇 달씩 두고, 호마다 한두 종목을 바꾼다.'},
    'daishin_focus': {'l': '대신 이번 주 포커스', 'house': '대신증권', 'kind': 'signal', 'cycle': '주',
                      'd': '대신증권 "이번 주 포커스"의 주도 테마 종목과 신고가 특징주. 실릴 때마다 같은 금액 매수',
                 'how': '호에 따라 주도 테마 2개와 신고가 특징주, 또는 저평가 우량주와 고배당 유망주를 싣는다. 주도 테마는 200일 이동평균이 오르며 5년 내 최고이고 거래대금이 큰 종목이 가장 많은 테마다.'},
    'yuanta_qwer': {'l': '유안타 QWER 스크리닝', 'house': '유안타증권', 'kind': 'signal', 'cycle': '주',
                    'd': '유안타증권 주간 퀀트(QWER)의 주간 스크리닝 종목. 실릴 때마다 같은 금액 매수',
                 'how': '매주 주제를 정해(실적 시즌, 배당, 낙폭과대 등) 이익 추정치 변화 같은 조건으로 10~30종목을 걸러 낸다. 주제는 몇 주마다 바뀐다.'},
    'daol_bu': {'l': '다올 실적 판정', 'house': '다올투자증권', 'kind': 'signal', 'cycle': '실적 공시마다',
                'd': '다올 퀀트(김경훈) 바텀업 채널의 실적 공시 직후 판정. LONG 은 매수, SHORT 는 피할 종목',
                 'how': '기업이 분기 실적을 공시하면 곧바로 판정한다. 실적이 예상보다 얼마나 강했는지와 주가에 기대가 얼마나 실려 있는지를 조합해, 발표 뒤 주가가 더 오를 종목은 LONG, 내릴 종목은 SHORT, 나머지는 NO POSITION 으로 가른다.'},
    'daol_aq': {'l': '다올 Active Quant', 'house': '다올투자증권', 'kind': 'port', 'cycle': '주',
                'd': '다올 퀀트(김경훈) 주간 리포트의 종목별 포지션 표. Long 종목을 같은 금액씩, 다음 호가 나올 때 교체',
                 'how': '애널리스트 7명 이상이 다루는 종목마다 자체 이익 추정치를 시장 예상과 견줘 Long·Short·No Position 을 매긴다. 실적 시즌 동안 1~2주마다 표를 새로 낸다.'},
}

NAVER_RULES = [
    ('hana_qmp', '하나', r'실전 ?퀀트|Quant MP'),
    ('daishin_top10', '대신', r'투자 ?유망'),
    ('daishin_focus', '대신', r'이번 ?주 ?포커'),
    ('yuanta_qwer', '유안타', r'QWER'),
]


def naver_series(broker: str, title: str):
    for key, b, pat in NAVER_RULES:
        if b in broker and re.search(pat, title):
            return key
    return None


VERDICT = re.compile(r'[「『]\s*(CONVICTION LONG|CONVICTION SHORT|LONG|SHORT|NO POSITION)\s*[」』]\s*실적')


def bu_name(text: str):
    """실적 판정 글의 종목명. 형식이 세 번 바뀌었다:
    「종목」 3Q26 실적발표 / [KTB퀀트 김경훈] 1Q21 【종목】 실적발표 / [SK퀀트 김경훈] (종목) Active Quant의 定石: 실적발표 후 70일 전략"""
    h = first_line(text)
    if '실적' not in h:
        return None
    m = (re.search(r'[「【]\s*(.+?)\s*[」】]', h) or re.search(r'\]\s*\((.+?)\)\s*Active', h)
         or re.search(r'공시된\s*【\s*(.+?)\s*】', text[:300]))
    return re.sub(r'정정\)?|[()]', '', m.group(1)).strip() if m else None


def tg_series(ch: str, text: str):
    head = first_line(text)
    if bu_name(text) and VERDICT.search(text):
        return 'daol_bu'
    if ch == 'td' and re.search(r'Active Quant의 (定石|정석)', head) and re.search(r'https?://', text):      # 리포트 PDF 링크가 달린 글
        return 'daol_aq'
    return None


def to_kst(ts: str) -> str:
    """텔레그램 시각(UTC, +00:00) → 한국 시각 'YYYY-MM-DDTHH:MM:SS'"""
    t = datetime.fromisoformat(ts)
    if t.utcoffset() is not None:
        t = (t - t.utcoffset()).replace(tzinfo=None) + timedelta(hours=9)
    return t.strftime('%Y-%m-%dT%H:%M:%S')


def first_line(text: str) -> str:
    return (text.strip().split('\n')[0] if text and text.strip() else '')[:80]


# ------------------------------------------------------------
# 종목명 → 코드 (그 날짜에 그 이름을 쓰던 종목)
# ------------------------------------------------------------

ALIAS = {   # 리포트가 줄여 쓰는 이름 → 거래소 이름
    '하이닉스': 'SK하이닉스', 'LG엔솔': 'LG에너지솔루션', '삼성바이오': '삼성바이오로직스', '삼바': '삼성바이오로직스',
    '한화에어로': '한화에어로스페이스', '네이버': 'NAVER', '삼성SDS': '삼성에스디에스', '엔씨': '엔씨소프트',
    'LG생건': 'LG생활건강', '아모레': '아모레퍼시픽', 'KAI': '한국항공우주', '포스코': 'POSCO', '기아차': '기아',
    'SKT': 'SK텔레콤', 'HD현대일렉': 'HD현대일렉트릭', '현대일렉': '현대일렉트릭', 'JYP': 'JYP Ent.', 'SM': '에스엠',
    '에스엠엔터': '에스엠', 'YG': '와이지엔터테인먼트', '와이지엔터': '와이지엔터테인먼트', '두산에너빌': '두산에너빌리티',
    'LG CNS': 'LG씨엔에스', 'LGCNS': 'LG씨엔에스', '현대차그룹': None, 'KT&G': 'KT&G', 'SK이노': 'SK이노베이션',
    '한국타이어': '한국타이어앤테크놀로지', '한타': '한국타이어앤테크놀로지', '롯데에너지머티': '롯데에너지머티리얼즈',
    '삼성E&A': '삼성E&A', 'NC소프트': '엔씨소프트', '카뱅': '카카오뱅크', '카페': '카카오페이', 'LG디플': 'LG디스플레이',
    '현대글로비스': '현대글로비스', '한국조선해양': '한국조선해양', '현대미포': '현대미포조선', '미래에셋': '미래에셋증권',
    '한국금융': '한국금융지주', '메리츠금융': '메리츠금융지주', '우리금융': '우리금융지주', '하나금융': '하나금융지주',
    'BNK금융': 'BNK금융지주', 'JB금융': 'JB금융지주', 'DGB금융': 'DGB금융지주', 'KB': 'KB금융', '신한': '신한지주',
    '에코프로BM': '에코프로비엠', '포스코인터': '포스코인터내셔널', '포스코케미칼': '포스코케미칼', '현대건설기계': '현대건설기계',
    'SK바사': 'SK바이오사이언스', 'SK바이오사이언': 'SK바이오사이언스', 'HD현대마린': 'HD현대마린솔루션',
    'CJ대한통운': 'CJ대한통운', '롯데관광': '롯데관광개발', 'GKL': 'GKL', '코스맥스': '코스맥스', '한전': '한국전력',
    '한전KPS': '한전KPS', '가스공사': '한국가스공사', '대한항공': '대한항공', 'HMM': 'HMM', '팬오션': '팬오션',
    'HDC산업개발': 'HDC현대산업개발', 'S&T모디브': 'S&T모티브', '오스템인플란트': '오스템임플란트', 'SKSK가스': 'SK가스',
    '에스엠': '에스엠', 'JYP Ent': 'JYP Ent.', 'SOOP': 'SOOP', '아프리카TV': '아프리카TV', 'NHN엔터': 'NHN',
}


def norm(name: str) -> str:
    return re.sub(r'[\s·]|\(주\)|㈜', '', name or '').upper()


class NameIndex:
    """rows: (이름, 코드, 그 이름을 처음 본 날, 마지막으로 본 날). 같은 이름을 다른 종목이 쓴 적이 있으면 날짜로 고른다."""

    def __init__(self, rows):
        self.by, self.cur = {}, {}
        for name, code, first, last in rows:
            self.by.setdefault(norm(name), []).append((code, first, last))
            if code not in self.cur or last >= self.cur[code][1]:
                self.cur[code] = (name, last)
        self.maxlen = max((len(k) for k in self.by), default=0)
        self.alias = {norm(k): norm(v) for k, v in ALIAS.items() if v}

    def name_of(self, code):
        return self.cur.get(code, (code,))[0]

    def has(self, code):
        return code in self.cur

    def code(self, name, date=None):
        k = norm(name)
        hits = self.by.get(k) or self.by.get(self.alias.get(k, ''))
        if not hits:
            return None
        if len(hits) == 1 or not date:
            return max(hits, key=lambda h: h[2])[0]
        # 날짜가 [first, last] 안에 드는 것, 없으면 가장 가까운 것
        def dist(h):
            return 0 if h[1] <= date <= h[2] else min(abs(_days(date, h[1])), abs(_days(date, h[2])))
        return min(hits, key=lambda h: (dist(h), -int(h[2].replace('-', ''))))[0]

    def lead(self, tokens, i, date=None, maxtok=4):
        """tokens[i:] 맨 앞에서 가장 긴 종목명을 찾는다 → (코드, 쓴 토큰 수) 또는 (None, 0)"""
        for k in range(min(maxtok, len(tokens) - i), 0, -1):
            c = self.code(' '.join(tokens[i:i + k]), date)
            if c:
                return c, k
        return None, 0


def _days(a: str, b: str) -> int:
    return (datetime.fromisoformat(a[:10]) - datetime.fromisoformat(b[:10])).days


def _pick(names, code, side, weight=None, grp=None):
    return {'code': code, 'name': names.name_of(code), 'side': side, 'weight': weight, 'grp': grp}


def _uniq(picks):
    seen, out = set(), []
    for p in picks:
        k = (p['code'], p['side'])
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


# ------------------------------------------------------------
# 하나 실전 퀀트: "업종 종목 시총(억원) 비중(%) KOSPI비중 초과비중 …" 표
# ------------------------------------------------------------

QMP_ROW = re.compile(r'^(\S+)\s+(.+?)\s+([\d,]{4,})\s+(\d{1,2}\.\d{1,2})\s+(\d{1,2}\.\d{1,2})\s+(-?\d{1,2}\.\d{1,2})(?:\s+-?\d+\.\d+)*\s*$')


def parse_hana_qmp(text, names, date=None):
    """비중 합이 100% 근처인 첫 표를 모델 포트폴리오로 본다 (지난달 표가 같이 실리는 호가 있다)"""
    tables, cur = [], []
    for ln in text.split('\n'):
        m = QMP_ROW.match(ln.strip())
        code = m and names.code(m.group(2), date)
        if code:
            cur.append(_pick(names, code, 'L', float(m.group(4)), m.group(1)))
        elif cur and ln.strip() and not re.match(r'^[\d\s.,()%-]+$', ln.strip()):
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    for t in tables:
        t = _uniq(t)
        if len(t) >= 10 and 90 <= sum(p['weight'] for p in t) <= 110:
            return t
    return []


# ------------------------------------------------------------
# 대신 투자 유망: "국내 주식 10선" 표 (티커 종목명 편입일자 시총 YTD)
# ------------------------------------------------------------

TOP10_ROW = re.compile(r'^(\d{6})\s+(.+?)\s+(\d\d\.\d\d\.\d\d)\s')


def parse_daishin_top10(text, names, date=None):
    lines = text.split('\n')
    for i, ln in enumerate(lines):
        if not re.search(r'국내\s*주식\s*10\s*선', ln):
            continue
        out = []
        for row in lines[i + 1:i + 30]:
            row = row.strip()
            if re.search(r'해외\s*주식|ETF|^주\s*:', row):
                break
            m = TOP10_ROW.match(row)
            if m and names.has(m.group(1)):
                out.append(_pick(names, m.group(1), 'L'))
        if len(out) >= 5:
            return _uniq(out)
    return []


# ------------------------------------------------------------
# 대신 이번 주 포커스: "종목 코드 과열수준 1D 1M" 줄, 묶음 제목(주도 테마 N: ○○ / 신고가 특징주)
# ------------------------------------------------------------

FOCUS_ROW = re.compile(r'^(.+?)\s+(\d{6})\s+\S')
FOCUS_HEAD = re.compile(r'^종목\s+코드')


def parse_daishin_focus(text, names, date=None):
    """묶음(주도 테마·신고가 특징주·저평가 우량주·고배당 유망주 …)마다 "종목 코드 …" 표가 있다. 코드가 실제 종목인 줄만 받는다."""
    lines = [ln.strip() for ln in text.split('\n')]
    out, grp = [], None
    for i, ln in enumerate(lines):
        if ln.startswith('Compliance'):
            break
        if FOCUS_HEAD.match(ln) or ln == '종목 코드':
            # 표 머리 위쪽에서 묶음 제목을 찾는다: 숫자·쉼표·콜론으로 끝나지 않는 짧은 줄
            for prev in reversed(lines[max(0, i - 8):i]):
                m = re.match(r'^(?:시장\s*주도\s*테마\s*\d*\s*[:：]\s*)?([가-힣A-Za-z /·&]{2,16})$', prev)
                if m and not prev.endswith(('등', ':')) and prev not in ('예상 배당', '종목 코드', '자본유보율'):
                    grp = m.group(1).strip()
                    break
            continue
        m = FOCUS_ROW.match(ln)
        if m and names.has(m.group(2)) and not ln.startswith('*'):
            out.append(_pick(names, m.group(2), 'L', None, grp))
    return _uniq(out)


# ------------------------------------------------------------
# 유안타 QWER: "주간 스크리닝" 쪽의 종목명 줄 (이름 여러 개가 한 줄에 이어진다)
# ------------------------------------------------------------

QWER_WEEK = re.compile(r'^\[\s*\d+월\s*\d주차\s*\]')
QWER_CODE = re.compile(r'(?:^|\s)A(\d{6})\s+\S')
QWER_PAGE = re.compile(r'(스크리닝|리밸런싱)\.xlsx')
NUMTOK = re.compile(r'^-?[\d,.]+$')


def parse_yuanta_qwer(text, names, date=None):
    """"[11월 1주차] …" 기준 줄 다음의 첫 종목 표에서 '자료' 줄까지. 호마다 표 모양이 달라 세 가지를 받는다:
    A+코드로 시작하는 줄 / 한 줄에 한 종목(종목명 업종 시가총액 …) / 한 줄에 종목명 여러 개가 이어지는 꼴.
    추정치 조정 상·하위를 나열만 하는 "트래킹" 호는 고른 종목이 아니라서 뽑지 않는다."""
    lines = [ln.strip() for ln in text.split('\n')]
    page = next((i for i, ln in enumerate(lines) if QWER_PAGE.search(ln)), None)
    if page is None:
        page = next((i for i, ln in enumerate(lines) if QWER_WEEK.match(ln)), None)
    if page is None:
        return []
    start = next((i for i in range(page, min(page + 30, len(lines)))
                  if '종목명' in lines[i] and not re.search(r'상위|하위', lines[i])), None)
    if start is None:
        return []
    out, frag = [], ''
    for ln in lines[start + 1:start + 70]:
        if ln.startswith(('자료', '주1', '주:', '주 :', '주)')):
            break
        m = QWER_CODE.search(ln)
        if m:
            if names.has(m.group(1)):
                out.append(_pick(names, m.group(1), 'L'))
            continue
        toks, i, got = [], 0, []
        for cand in ([frag + ln, ln] if frag else [ln]):      # 앞 줄에서 잘린 이름을 붙여 보고, 안 되면 이 줄만
            toks, i, got = cand.split(), 0, []
            while i < len(toks):
                c, k = names.lead(toks, i, date)
                if not c:
                    break
                got.append(c)
                i += k
            if got:
                break
        rest = toks[i:]
        row = len(got) == 1 and rest and not NUMTOK.match(rest[0]) and (
            any(re.match(r'^[\d,]{3,}$', t) for t in rest[1:4]) or (len(rest) <= 2 and rest[-1].endswith(',')))
        if len(got) >= 2 or row:
            out += [_pick(names, c, 'L') for c in got]
            frag = ''
        else:      # 종목명이 줄 끝에서 잘린 경우(한화에어 / 로스페이스 …): 글자뿐인 한 토막이면 다음 줄 앞에 붙여 본다
            frag = ln if re.match(r'^[가-힣A-Za-z&]{2,8}$', ln) and not frag else ''
    return _uniq(out)


# ------------------------------------------------------------
# 다올 바텀업: 「종목」 3Q26 실적발표 … 「LONG」 실적임을 알려드립니다 (2018~2021년 글은 괄호 모양이 다르다)
# ------------------------------------------------------------

def parse_daol_bu(text, names, date=None):
    nm, v = bu_name(text), VERDICT.search(text)
    if not nm or not v:
        return []
    verdict = v.group(1)
    if verdict == 'NO POSITION':
        return []
    code = names.code(nm, date)
    if not code:
        raise ValueError(f'종목명 모름: {nm}')
    return [_pick(names, code, 'L' if verdict.endswith('LONG') else 'S', None, verdict)]


# ------------------------------------------------------------
# 다올 Active Quant: 종목별 포지션 표 (순번 종목 실적발표일 숫자… L/S Position Valuation …), 한 줄에 두 칸
# ------------------------------------------------------------

AQ_ROW = re.compile(r'(?:^|\s)\d{1,3}\s+(\D[^\n]*?)\s+\d{1,2}/\d{1,2}\s+(?:(?:-?[\d,.]+|미발표|N/A|적자|흑자|-)\s+){1,6}?'
                    r'(Conviction Long|Conviction Short|Long|Short|No Position)\s+(?:Overvalued|Undervalued|Fair)')


AQ_POS = re.compile(r'(?:Conviction Long|Conviction Short|Long|Short|No Position)\s+(?:Overvalued|Undervalued|Fair)')


def parse_daol_aq(text, names, date=None):
    out, unknown, rows = [], [], 0
    for ln in text.split('\n'):
        for m in AQ_ROW.finditer(ln):
            rows += 1
            pos = m.group(2)
            if pos == 'No Position':
                continue
            code = names.code(m.group(1), date)
            if not code:
                unknown.append(m.group(1))
                continue
            out.append(_pick(names, code, 'L' if pos.endswith('Long') else 'S', None, pos))
    if not rows:
        raise ValueError('포지션 표 없음')
    total = len(AQ_POS.findall(text))      # 표에 적힌 포지션 칸 수. 줄을 일부만 읽었으면(옛 양식) 쓰지 않는다
    if rows < total * 0.9 or len(unknown) > max(1, rows * 0.02):
        raise ValueError(f'표를 일부만 읽음 ({rows}/{total}, 모르는 종목 {len(unknown)})')
    if unknown and not out:
        raise ValueError('종목명 모름: ' + ', '.join(unknown[:5]))
    return _uniq(out)


PARSERS = {
    'hana_qmp': parse_hana_qmp, 'daishin_top10': parse_daishin_top10, 'daishin_focus': parse_daishin_focus,
    'yuanta_qwer': parse_yuanta_qwer, 'daol_bu': parse_daol_bu, 'daol_aq': parse_daol_aq,
}
