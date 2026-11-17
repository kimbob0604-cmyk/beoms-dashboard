"""
@DOC_POOL(증권사 리포트를 모아 올리는 텔레그램 공개 채널) 글의 순수 함수: 머리글 파싱 · 증권사·종목 가려내기 ·
네이버 리서치 수집분과 같은 리포트 찾기 · 같은 글 두 번 올린 것 묶기 · 증분 수집 구간  (tests/test_docpool.py)

글 형식 (채널 운영자가 리포트마다 붙이는 요약의 머리 부분만 쓴다. 요약 본문은 화면·공개 파일에 싣지 않는다):
  [종목 또는 주제 / 업종 / 분류]
  제목: …
  작성자: 이름 (증권사)
  작성일: 2026.11.16          ← 없는 글이 많다
  투자의견: BUY               ← 종목 리포트만
  목표주가: 23,000원
  (빈 줄 뒤 요약 본문)
첨부 파일 이름은 대개 `종목_제목_증권사_YYMMDD.pdf` 다.
"""

import re
from datetime import date, datetime
from difflib import SequenceMatcher

# 증권사 표기 → 네이버 리서치에서 쓰는 이름. 별칭은 공백 없이 소문자로 견준다 (앞에 둔 것이 먼저 잡힌다)
BROKERS = [
    ('삼성선물', ['삼성선물']), ('NH선물', ['nh선물']), ('유진투자선물', ['유진투자선물', '유진선물']),
    ('삼성증권', ['삼성증권', 'samsungsecurities']),
    ('미래에셋증권', ['미래에셋증권', '미래에셋대우', 'miraeasset']),
    ('한국투자증권', ['한국투자증권', '한투증권', 'koreainvestment']),
    ('NH투자증권', ['nh투자증권', 'nh증권', 'nhinvestment']),
    ('KB증권', ['kb증권', 'kbsecurities']),
    ('신한투자증권', ['신한투자증권', '신한금융투자', '신한증권', 'shinhansecurities', 'shinhaninvestment']),
    ('하나증권', ['하나증권', '하나금융투자', 'hanasecurities']),
    ('키움증권', ['키움증권', 'kiwoom']),
    ('대신증권', ['대신증권', 'daishin']),
    ('메리츠증권', ['메리츠증권', '메리츠종금증권', 'meritz']),
    ('유안타증권', ['유안타증권', 'yuanta']),
    ('유진투자증권', ['유진투자증권', '유진증권', 'eugeneinvestment']),
    ('한화투자증권', ['한화투자증권', '한화증권', 'hanwhainvestment']),
    ('SK증권', ['sk증권', 'sksecurities']),
    ('IBK투자증권', ['ibk투자증권', 'ibk증권', 'ibks']),
    ('교보증권', ['교보증권', 'kyobosecurities']),
    ('DS투자증권', ['ds투자증권', 'ds증권']),
    ('현대차증권', ['현대차증권', '현대차투자증권', 'hmc투자증권']),
    ('iM증권', ['im증권', '아이엠증권', '하이투자증권', 'imsecurities']),
    ('상상인증권', ['상상인증권', '상상인']),
    ('LS증권', ['ls증권', '이베스트투자증권', '이베스트증권']),
    ('신영증권', ['신영증권']),
    ('다올투자증권', ['다올투자증권', '다올증권', 'daol투자증권', 'daol증권', 'ktb투자증권']),
    ('DB증권', ['db증권', 'db금융투자', 'db투자증권']),
    ('BNK투자증권', ['bnk투자증권', 'bnk증권']),
    ('부국증권', ['부국증권']), ('흥국증권', ['흥국증권']), ('한양증권', ['한양증권']), ('유화증권', ['유화증권']),
    ('케이프투자증권', ['케이프투자증권', '케이프증권']), ('리딩투자증권', ['리딩투자증권']),
    ('토스증권', ['토스증권']), ('카카오페이증권', ['카카오페이증권']), ('우리투자증권', ['우리투자증권']),
    ('한국IR협의회', ['한국ir협의회', 'ir협의회']),
    ('NICE평가정보', ['nice평가정보', '나이스평가정보']), ('서울평가정보', ['서울평가정보']),
    ('나이스디앤비', ['나이스디앤비', 'nice디앤비']), ('한국기업데이터', ['한국기업데이터', '한국평가데이터']),
    ('밸류파인더', ['밸류파인더']), ('그로쓰리서치', ['그로쓰리서치']), ('리서치알음', ['리서치알음']),
    ('스터닝밸류리서치', ['스터닝밸류']), ('지엘리서치', ['지엘리서치']), ('FS리서치', ['fs리서치']),
    ('아이브이리서치', ['아이브이리서치', 'iv리서치']), ('CTT리서치', ['ctt리서치']),
]
# 목록에 없는 곳: '○○증권 · ○○리서치 · ○○은행'처럼 끝말로 알아본다 (은행·평가사 자료도 올라온다)
BROKER_TAIL = re.compile(r'([A-Za-z가-힣]{1,10}(?:투자증권|증권|선물|자산운용|경제연구소|리서치|평가정보|은행|금융센터|자산평가|기업평가))')

OPINIONS = {
    'buy': '매수', '매수': '매수', 'strongbuy': '매수', 'outperform': '매수', 'tradingbuy': '매수',
    'hold': '중립', '중립': '중립', 'neutral': '중립', 'marketperform': '중립',
    'sell': '매도', '매도': '매도', 'underperform': '매도', 'reduce': '매도',
    'overweight': '비중확대', '비중확대': '비중확대', 'underweight': '비중축소', '비중축소': '비중축소',
    'notrated': 'NR', 'nr': 'NR', '투자의견없음': 'NR',
    'positive': '비중확대', 'negative': '비중축소', '보유': '중립', '적극매수': '매수', 'convictionbuy': '매수', 'mperform': '중립',
}
# 긴 표현('건설업 Overweight 유지', 'SK텔레콤 BUY / …') 안에서 찾을 때의 순서: 다른 말에 품기는 말(buy ⊂ strongbuy)이 뒤에 오게
OPINION_SCAN = ['underperform', 'outperform', 'marketperform', 'mperform', 'underweight', 'overweight', 'notrated', 'strongbuy',
                'tradingbuy', '비중확대', '비중축소', '적극매수', '매수', '매도', '중립', '보유', 'buy', 'sell', 'hold', 'neutral',
                'positive', 'negative']
KEY_LINE = re.compile(r'^([가-힣A-Za-z ]{2,10})\s*(?:\([^)]{1,12}\))?\s*[:：]\s*(.*)$')
CODE = re.compile(r'\(\s*A?(\d{6})(?:\.K[SQ])?\s*\)|\bA?(\d{6})\.K[SQ]\b')
TEMPLATE_WORDS = {'기업명', '종목명', '산업명', '카테고리', '기업', '산업', '종목', '주제', '분류'}   # 요약 틀의 자리 표시가 그대로 남은 머리글


def norm(s) -> str:
    """견줄 때 쓰는 꼴: 공백·문장부호를 빼고 소문자로"""
    s = re.sub(r'\(주\)|㈜|주식회사', '', s or '')
    return re.sub(r'[\s·ㆍ・,.\-_:;!?\'"“”‘’()\[\]/&…~]+', '', s).lower()


def is_template(topic) -> bool:
    """'[기업명/산업명/카테고리]'처럼 틀의 자리 표시만 남은 머리글인가"""
    parts = [x.strip() for x in (topic or '').split('/') if x.strip()]
    return bool(parts) and all(x in TEMPLATE_WORDS for x in parts)


def canon_broker(s) -> str:
    """증권사 표기 → 기준 이름. 모르면 ''"""
    n = norm(s)
    if not n:
        return ''
    for name, aliases in BROKERS:
        if any(a in n for a in aliases):
            return name
    return ''


def broker_of(author, file='') -> str:
    """작성자 줄에서 증권사를 찾고, 없으면 첨부 파일 이름의 뒤쪽 토막에서 찾는다"""
    b = canon_broker(author)
    if b:
        return b
    m = BROKER_TAIL.search(author or '')
    if m:
        return m.group(1)
    for tok in reversed(re.sub(r'\.[A-Za-z]{2,5}$', '', file or '').split('_')):
        b = canon_broker(tok)
        if b:
            return b
    return ''


def header(text) -> dict:
    """글 머리 → {topic, 제목, 작성자, 작성일, 투자의견, 목표주가 …}. 첫 빈 줄(또는 다음 [소제목]) 앞까지만 본다.
    제목이 줄바꿈으로 잘려 있으면 이어 붙인다."""
    out, key = {'topic': ''}, None
    lines = (text or '').strip().split('\n')
    if lines and lines[0].strip().startswith('['):
        out['topic'] = lines[0].strip().strip('[]').strip()
        lines = lines[1:]
    for ln in lines:
        ln = ln.strip()
        if not ln:
            if '제목' in out:
                break
            continue
        if ln.startswith('[') or ln.startswith('·'):
            break
        m = KEY_LINE.match(ln)
        if m:
            key = m.group(1).replace(' ', '')
            out.setdefault(key, m.group(2).strip())
        elif key == '제목':
            out['제목'] = f"{out['제목']} {ln}".strip()
        else:
            break
    return out


def is_report(text) -> bool:
    """리포트 요약 글인가 (광고·공지 글을 거른다)"""
    return bool(re.search(r'^제목\s*[:：]', text or '', re.M))


def parse_date(s):
    """'2026.11.16' · '2026-11-16' · '2026. 11. 16.' → 'YYYY-MM-DD'"""
    m = re.search(r'(20\d\d)\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})', s or '')
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def file_date(file):
    """첨부 파일 이름 끝의 날짜 (…_261117.pdf · …_20261116.pdf) → 'YYYY-MM-DD'"""
    m = re.search(r'_(20\d{6}|\d{6})(?:\.[A-Za-z]{2,5})?$', file or '')
    if not m:
        return None
    s = m.group(1)
    s = s if len(s) == 8 else '20' + s
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:])).isoformat()
    except ValueError:
        return None


def report_date(head, file, ts) -> str:
    """리포트 작성일: 글의 '작성일' → 파일 이름 날짜 → 올라온 날. 올라온 날보다 뒤거나 1년 넘게 앞이면 믿지 않는다"""
    posted = ts[:10]
    for d in (parse_date(head.get('작성일')), file_date(file)):
        if d and d <= posted and (date.fromisoformat(posted) - date.fromisoformat(d)).days <= 370:
            return d
    return posted


def opinion_of(s):
    """'BUY' · '매수(유지)' · 'Buy (Maintain)' · '비중확대/유지' · '건설업 Overweight' → 매수/중립/매도/비중확대/비중축소/NR.
    모르는 말은 짧으면(10자 이하, 쉼표·빗금 없음) 그대로, 길면 None (종목 여러 개를 늘어놓은 줄 등)"""
    s = re.sub(r'\(.*?\)', '', s or '').strip()
    n = norm(s)
    if not n:
        return None
    if n in OPINIONS:
        return OPINIONS[n]
    for k in OPINION_SCAN:
        if k in n:
            return OPINIONS[k]
    return s if len(s) <= 10 and not re.search(r'[,/]', s) else None


def goal_of(s):
    """'23,000원' · 'KRW200,000' · '820,000원(하향)' · '180,000원 (기존 230,000원에서 하향)' → 첫 금액(원). 원화가 아니면 None"""
    s = s or ''
    if re.search(r'\$|USD|달러|엔|위안|HKD|유로', s):
        return None
    m = re.search(r'(\d[\d,]*\d|\d)\s*(만\s*원|원)?', s.replace('KRW', ''))
    if not m:
        return None
    v = float(m.group(1).replace(',', ''))
    if m.group(2) and '만' in m.group(2):
        v *= 10000
    return v if v >= 100 else None


def stock_of(head, file, broker, names, codes):
    """종목 코드 찾기: 머리글·제목의 (코드) → 머리글 토막(앞에서부터)의 종목명 → 제목 맨 앞 종목명 → 파일 이름 첫 토막.
    머리글은 '종목 / 업종'이 보통이지만 '항공운송/제주항공'처럼 종목이 뒤에 오기도 해서 토막마다 이름과 똑같은지 본다.
    파일 이름은 머리글이 없거나(요약 없는 PDF) 틀만 남았거나 영문일 때만 본다 — 산업·시황 글의 파일이 대표 종목이나
    'SK_증권_…'·'LS_…'처럼 증권사 이름 토막으로 시작하는 일이 많아서다. 그래서 파일 이름 토막은 증권사 이름에 품겨도 버린다.
    names: {norm(종목명): 코드}, codes: 아는 코드 모음. 이름이 리포트를 낸 증권사와 같으면 종목으로 보지 않는다
    (파일 이름·머리글이 '삼성증권_Metal_Futures…'처럼 증권사로 시작하는 글)."""
    topic, title = head.get('topic', ''), head.get('제목', '')
    for s in (topic, title):
        for m in CODE.finditer(s):
            c = m.group(1) or m.group(2)
            if c in codes:
                return c
    cands = []
    if topic and not is_template(topic):
        cands += [CODE.sub('', x) for x in re.split(r'\s*/\s*', topic)]
    m = re.match(r'^([^:：(\[]{2,24}?)\s*(?:\([^)]*\))?\s*[:：]', title)
    if m:
        cands.append(m.group(1))
    nb = norm(broker)
    for name in cands:
        n = norm(name)
        if n and n != nb and n in names:
            return names[n]
    first = re.split(r'\s*/\s*', topic)[0] if topic else ''
    if file and (not topic or is_template(topic) or not re.search(r'[가-힣]', first)):
        n = norm(file.split('_')[0])
        if n and n not in nb and n in names:
            return names[n]
    return None


def parse_post(row, names, codes) -> dict:
    """DB 행 {id, ts, text, file} → 화면에 쓸 목록 정보. names·codes 는 stock_of 와 같다"""
    head = header(row.get('text') or '')
    file = row.get('file') or ''
    title = head.get('제목') or ''
    if not title and file:      # 요약 글이 없는 PDF: 파일 이름에서 날짜·확장자만 떼어 제목으로
        title = re.sub(r'_(20\d{6}|\d{6})$', '', re.sub(r'\.[A-Za-z]{2,5}$', '', file)).replace('_', ' ')
    broker = broker_of(head.get('작성자', ''), file)
    code = stock_of(head, file, broker, names, codes)
    return {
        'id': row['id'], 'ts': row['ts'], 'date': row['ts'][:10], 'file': file,
        'topic': '' if is_template(head.get('topic')) else head.get('topic', ''),
        'title': title, 'author': head.get('작성자', ''), 'broker': broker, 'code': code,
        'rdate': report_date(head, file, row['ts']),
        'op': opinion_of(head.get('투자의견')), 'goal': goal_of(head.get('목표주가')) if code else None,
        'link': f"https://t.me/DOC_POOL/{row['id']}",
    }


# ------------------------------------------------------------
# 같은 리포트 찾기
# ------------------------------------------------------------

def title_sim(a, b) -> float:
    """제목 닮은 정도 0~1. 한쪽이 다른 쪽을 품으면 1 (채널 제목은 '종목명 (코드): 제목'처럼 앞이 붙기도 한다)"""
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def match_naver(post, cands, max_days=3, min_sim=0.5):
    """네이버 리서치 수집분(cands: 같은 종목의 {id, date, broker, title})에서 같은 리포트의 id 를 찾는다.
    같은 증권사 · 작성일 차이 max_days 이내 가운데 제목이 가장 닮은 것. 날짜가 같으면 제목이 달라도 같은 리포트로 본다
    (한 증권사가 한 종목을 하루에 두 번 내는 일은 드물다). 날짜가 다르면 제목이 min_sim 이상 닮아야 한다. 없으면 None."""
    if not post.get('code') or not post.get('broker'):
        return None
    best, best_key = None, None
    d0 = date.fromisoformat(post['rdate'])
    for c in cands:
        if canon_broker(c['broker']) != post['broker'] and c['broker'] != post['broker']:
            continue
        gap = abs((date.fromisoformat(c['date']) - d0).days)
        if gap > max_days:
            continue
        sim = title_sim(post['title'], c['title'])
        if gap and sim < min_sim:
            continue
        key = (sim, -gap)
        if best_key is None or key > best_key:
            best, best_key = c['id'], key
    return best


def same_title(a, b, min_sim=0.8) -> bool:
    """두 번 올린 글의 제목인가: 요약을 다시 만들면서 낱말이 조금 달라지기도 해서 거의 같으면 같은 것으로 본다.
    한쪽이 다른 쪽을 품는 것은 짧은 쪽이 6자 이상일 때만 인정한다 ('Daily' 같은 짧은 제목이 다 묶이지 않게)."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    if (a in b or b in a) and min(len(a), len(b)) >= 6:
        return True
    return SequenceMatcher(None, a, b).ratio() >= min_sim


def dedupe(posts) -> list:
    """같은 리포트를 두 번 올린 글 묶기: 증권사 · 종목(없으면 주제) · 작성일이 같고 제목이 거의 같으면 먼저 올라온 글만 남기고,
    뒤 글의 id 는 남긴 글의 'dups' 에 적는다. id 오름차순으로 돌려준다."""
    out, groups = [], {}
    for p in sorted(posts, key=lambda p: p['id']):
        kept = groups.setdefault((p['broker'], p['code'] or norm(p['topic']), p['rdate']), [])
        first = next((k for k in kept if same_title(k['title'], p['title'])), None)
        if first is not None:
            first.setdefault('dups', []).append(p['id'])
            continue
        kept.append(p)
        out.append(p)
    return out


# ------------------------------------------------------------
# 증분 수집 구간
# ------------------------------------------------------------

def fetch_ranges(first_id, last_id, edge_id=None) -> list:
    """받을 글 번호 구간 [(lo, hi)…] — lo 초과, hi 미만 (hi None = 최신 글까지).
    first_id·last_id: 이미 훑은 구간의 양 끝 (first_id 초과 ~ last_id 이하를 훑었다. 처음이면 None).
    edge_id: 기준일 바로 앞 글 번호. 처음 받을 때의 시작점이고, 이미 받은 뒤라면 더 과거로 넓힐 때만 쓰인다.
    매일 실행은 (last_id, None) 하나라서 여러 번 돌려도 같은 글을 다시 받지 않는다."""
    if last_id is None:
        return [(edge_id or 0, None)]
    out = []
    if edge_id is not None and first_id is not None and edge_id < first_id:
        out.append((edge_id, first_id + 1))
    out.append((last_id, None))
    return out


def cutoff_kst(days, today=None) -> datetime:
    """오늘에서 days 일 전 0시 (KST 기준 naive)"""
    from datetime import timedelta
    t = today or datetime.now()
    return datetime(t.year, t.month, t.day) - timedelta(days=days)
