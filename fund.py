"""
펀더멘털 축적: 분기 비용 구조 (순수 함수 — 네트워크·DB 없음). 계획 docs/fundamental-plan.md

- note_tables   DART 원문(document.xml)에서 '비용의 성격별 분류' 주석 표를 읽는다 (연결·별도, 단위, 당기·전기 × 3개월·누적)
- quarterize    (시작, 끝) 기간 값들 → 분기 값 (3개월 값 우선, 없으면 누적끼리 뺀다. 4Q = 연간 − 3Q 누적)
- key_of/group  회사마다 다른 줄 이름 → 공통 키·묶음 (원가·인건비·감가상각비 …)
- bridge        OPM 변화 = 묶음별 매출 대비 비중 변화의 합
- evidence      리포트 문장 중 요인 낱말이 든 문장 (숫자 ↔ 설명)
- model         컨센서스 매출을 비용 구조에 넣어 본 영업이익 (변동비 = 비율, 고정비 = 금액)
"""

import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

UNIT = {'원': 1e-8, '천원': 1e-5, '백만원': 1e-2, '억원': 1.0}

# 줄 이름 → (공통 키, 묶음). 위에서부터 먼저 맞는 규칙. 묶음 이름은 화면 행 이름
RULES: List[Tuple[str, str, str]] = [
    (r'합\s*계|^계$|소\s*계|영업비용\s*계|성격별\s*비용$|매출원가.*판매비|총\s*영업비용|^총\s*비용$|^비용\s*계$|^총\s*계$', 'total', '비용합계'),
    (r'^매출원가$|^제조원가$|^판매비와(일반)?관리비$|^판매관리비$|^판관비$', 'total', '비용합계'),    # 기능별 소계 줄 — 비용 줄이 아니다
    (r'대손', 'baddebt', '기타'),                                                              # 대손상각비는 감가상각이 아니다
    (r'사용권', 'rou', '감가상각비'),
    (r'무형', 'amort', '감가상각비'),
    (r'감가상각|상각비', 'dep', '감가상각비'),
    (r'재고자산.*변동|제품.*재공품|재공품.*변동|재고.*증감', 'inv', '원가'),
    (r'원재료|원부재료|부재료|상품.*매입|재고자산.*매입|매입액|재료비|상품매출원가', 'raw', '원가'),
    (r'외주|용역비|임가공', 'outs', '외주비'),
    (r'종업원|급여|인건비|퇴직|복리후생|상여|주식보상', 'emp', '인건비'),
    (r'연구|개발비', 'rnd', 'R&D'),
    (r'판매수수료|판매촉진|판촉', 'promo', '판매수수료'),
    (r'지급수수료|수수료|기술사용료|로열티', 'fee', '지급수수료'),
    (r'임차', 'rent', '지급임차료'),
    (r'수도광열|전력|동력|유틸리티|가스수도', 'util', '수도광열비'),
    (r'소모품', 'supp', '소모품비'),
    (r'운반|물류|운송|운임', 'freight', '운반비'),
    (r'수선', 'repair', '수선비'),
    (r'광고|마케팅|홍보', 'ad', '광고선전비'),
    (r'기타', 'other', '기타'),
]
GROUP_ORDER = ['공시 안 된 비용', '매출원가', '판매비와관리비', '영업비용', '원가', '외주비', '인건비', '감가상각비', '지급수수료', '판매수수료', 'R&D', '지급임차료', '수도광열비', '소모품비', '운반비',
               '수선비', '광고선전비', '기타']
FIXED = {'인건비', '감가상각비', '지급임차료'}       # 매출이 변해도 금액이 잘 안 변하는 묶음 (모델에서 금액 유지)

# 요인별 낱말 (리포트 문장 ↔ 숫자)
WORDS = {
    '원가': ['원가', '원재료', '원자재', '판가', 'ASP', '단가', '믹스', '가동률', '수율', '스프레드', '재고', '환율', '원료'],
    '외주비': ['외주', '임가공'],
    '인건비': ['인건비', '성과급', '상여', '인력', '급여', '채용', '일회성 비용'],
    '감가상각비': ['감가상각', '증설', '상각비', 'CAPEX', '설비투자', '신공장', '고정비'],
    '지급수수료': ['수수료', '로열티'],
    'R&D': ['연구개발', 'R&D', '개발비'],
    '운반비': ['운반비', '물류비', '운임', '물류'],
    '광고선전비': ['광고', '마케팅', '판촉'],
    '수도광열비': ['전력비', '전기요금', '유틸리티', '에너지 비용'],
    '마진': ['마진', '수익성', '영업이익률', 'OPM', '비용'],
}


_GENERIC_TOTAL = r'성격별비용|비용|영업비용|총|총비용|매출원가및판매비와관리비|매출원가및판매비와일반관리비|매출원가,판매비와관리비|기능별항목|성격별비용의기능별배분|매출원가|제조원가|판매비와관리비|판매비와일반관리비|판매관리비|판관비'


def clean_label(s: str) -> str:
    s = re.sub(r'\(\s*(주|\*)\s*\d*\s*\)|\(\*\d*\)|\(주\d+\)|\*\d*', '', s or '')
    return re.sub(r'\s+', ' ', s).strip(' :ㆍ·')


def key_of(label: str) -> Tuple[str, str]:
    """줄 이름 → (공통 키, 묶음). 규칙에 없으면 이름 자체가 키, 묶음은 '기타'"""
    lab = clean_label(label)
    flat = lab.replace(' ', '')
    # '종업원급여비용 합계'처럼 특정 비용의 합계는 그 비용 줄이다 (전체 합계가 아니다). 앞말이 일반적인 것만 전체 합계·소계
    m = re.match(r'(.+?)의?(합계|소계|총계)$', flat)
    if m and not re.fullmatch(_GENERIC_TOTAL, re.sub(r'\(.*?\)', '', m.group(1))):
        flat = m.group(1)
    elif m:
        flat = re.sub(r'\(.*?\)', '', flat)                 # '성격별 비용(중단영업 포함) 합계' → 전체 합계
    for pat, key, grp in RULES:
        if re.search(pat, flat):
            return key, grp
    # 규칙에 없는 줄: 보고서마다 표기가 조금 달라도('재고자산의 매입' ↔ '재고자산 매입액') 같은 키가 되게 조사·꼬리말을 뗀다
    norm = re.sub(r'\(.*?\)|[,·ㆍ/]', '', flat)
    norm = re.sub(r'의|및|등', '', norm)
    norm = re.sub(r'(비용|금액|액|비|료)$', '', norm) or flat
    return 'x:' + norm, '기타'


# ---------------- 원문 주석 표 ----------------

def _text(html: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'&nbsp;|&#160;', ' ', re.sub(r'<[^>]+>', ' ', html))).strip()


def _num(s: str) -> Optional[float]:
    t = re.sub(r'[\s,]', '', s)
    if t in ('', '-', '－', '―', '–'):
        return 0.0 if t else None
    neg = t.startswith(('(', '△', '-', '▲')) or t.endswith(')')
    t = re.sub(r'[()△▲\-]', '', t)
    if not re.fullmatch(r'\d+(\.\d+)?', t):
        return None
    return -float(t) if neg else float(t)


def _cells(tr: str) -> List[Tuple[str, int, int]]:
    out = []
    for m in re.finditer(r'<T([HDUE])([^>]*)>(.*?)</T[HDUE]>', tr, re.S | re.I):
        attr = m.group(2)
        cs = re.search(r'COLSPAN="?(\d+)', attr, re.I)
        rs = re.search(r'ROWSPAN="?(\d+)', attr, re.I)
        out.append((_text(m.group(3)), int(cs.group(1)) if cs else 1, int(rs.group(1)) if rs else 1))
    return out


def parse_table(table: str) -> Optional[Dict]:
    """<TABLE>…</TABLE> → {'cols': [열 머리말…], 'rows': [(이름, [값…])]} (숫자 열만). 머리말은 여러 줄이면 이어 붙인다"""
    trs = re.findall(r'<TR[^>]*>(.*?)</TR>', table, re.S | re.I)
    grid, pend = [], {}          # pend: 열 위치 → (남은 줄 수, 글) — ROWSPAN
    for tr in trs:
        row, c = [], 0
        for txt, cs, rs in _cells(tr):
            while c in pend:
                left, t = pend[c]
                row.append(t)
                pend[c] = (left - 1, t)
                if pend[c][0] <= 0:
                    del pend[c]
                c += 1
            for _ in range(cs):
                row.append(txt)
                if rs > 1:
                    pend[c] = (rs - 1, txt)
                c += 1
        while c in pend:
            left, t = pend[c]
            row.append(t)
            pend[c] = (left - 1, t)
            if pend[c][0] <= 0:
                del pend[c]
            c += 1
        if row:
            grid.append(row)
    if len(grid) < 3:
        return None
    numeric = lambda x: _num(x) is not None and bool(re.search(r'\d', x))
    dash = lambda x: x.strip() in ('-', '－', '–', '―')          # 값이 없다는 표시 — 숫자 칸이다 (줄 이름이 아니다)
    yearish = lambda x: bool(re.fullmatch(r'(19|20)\d\d\s*(년|년도)?', x.strip()))    # 머리말이 '2023 / 2022' 인 표가 있다
    is_data = lambda r: len(r) > 1 and any(numeric(x) and not yearish(x) for x in r[1:])
    first = next((i for i, r in enumerate(grid) if is_data(r)), None)
    if first is None or first == 0:
        return None
    width = max(len(r) for r in grid)
    # 이름 칸이 여러 개인 표(위 칸 '성격별 비용' 아래에 세부 줄): 숫자가 시작하는 칸을 찾아 그 앞의 마지막 글을 줄 이름으로
    starts = [next(i for i, x in enumerate(r) if i and (numeric(x) or dash(x))) for r in grid[first:] if is_data(r)]
    vstart = max(set(starts), key=starts.count)
    head = [' '.join(dict.fromkeys(h[c] for h in grid[:first] if c < len(h) and h[c])) for c in range(width)]
    rows = []
    for r in grid[first:]:
        if not is_data(r):
            continue
        label = next((x for x in reversed(r[:vstart]) if x.strip() and not numeric(x) and not dash(x)), '')
        if not re.search(r'[가-힣A-Za-z]', label):       # 이름이 없는 줄('-' 등)은 줄이 아니다
            continue
        rows.append((clean_label(label), [_num(x) for x in r[vstart:]] + [None] * (width - len(r))))
    return {'cols': head[vstart:], 'rows': rows} if len(rows) >= 3 else None


def is_nature_table(t: Dict) -> bool:
    """비용 표인가: 인건비나 감가상각 줄이 있고, 비용 종류가 둘 이상이며, 자산 변동표(기초·취득·처분·기말)가 아니어야 한다.
    '성격별'·'영업비용'이라는 말은 재고자산 표(사업의 내용)·무형자산 변동표(상각비가 영업비용에 포함) 앞에도 나오고,
    주석 뒤에는 주당이익·금융손익 표가 이어진다 — 그런 표를 비용 표로 읽지 않으려고"""
    rows = [label.replace(' ', '') for label, _ in t['rows']]
    cols = [h.replace(' ', '') for h in t.get('cols', [])]
    # 줄 이름이 기초·취득·기말… 이거나 열 머리말이 취득원가·상각누계액·기초… 이면 자산 변동표. ('장부금액 공시금액'은 새 형식 비용 표 머리말이라 보지 않는다)
    if sum(1 for l in rows if re.match(r'(기초|기말|취득|처분|순장부)', l)) >= 2 or \
            sum(1 for h in cols if re.search(r'(기초|기말|취득원가|취득$|처분|상각누계|정부보조금)', h)) >= 2:
        return False
    keys = {key_of(label)[0] for label, _ in t['rows']}
    kinds = keys & {'emp', 'dep', 'amort', 'rou', 'raw', 'inv', 'fee', 'freight', 'ad', 'promo', 'rent', 'util', 'supp', 'repair', 'outs', 'rnd', 'other'}
    return bool(keys & {'emp', 'dep', 'amort', 'rou'}) and len(kinds) >= 2

def col_role(head: str) -> Tuple[Optional[str], Optional[str]]:
    """열 머리말 → (cur|prev, q|ytd|None). '당분기 3개월' → (cur, q), '전기' → (prev, None)"""
    h = head.replace(' ', '')
    who = 'cur' if re.search(r'당(분|반)?기|당기', h) else 'prev' if re.search(r'전(분|반)?기|전기', h) else None
    span = 'ytd' if re.search(r'누적', h) else 'q' if re.search(r'3개월|분기중|최근3|[당전]\d분기', h) else 'ytd' if re.search(r'\d개월', h) else None
    return who, span


_PERIOD = re.compile(r'(당|전)\s*(분|반)?\s*기')
_UNIT = re.compile(r'단위\s*[:：]?\s*(백만원|천원|억원|원)')


NATURE_WORDS = ('성격별', '영업비용')                 # '영업비용' 주석: 손익계산서를 성격별로 쓰는 회사(게임·통신·플랫폼·바이오)
SGA_WORDS = ('판매비와관리비', '판매비와일반관리비', '판매관리비')   # 성격별 분류가 없는 회사의 대체: 판관비 내역 (띄어쓰기는 지우고 비교)


def _has(text: str, words) -> bool:
    flat = re.sub(r'\s+', '', text)
    return any(w in flat for w in words)


def group_tables(xml: str, words=NATURE_WORDS) -> List[Dict]:
    """새 형식(XBRL 꼴 문서): <TABLE-GROUP ACLASS="{XBRL}NT_C_D834300"> 안에 [기간·단위 표] → [숫자 표] 가 번갈아 나온다.
    제목에 word 가 든 묶음만. 기간 표의 '당분기'/'전분기' 를 숫자 표 열 머리말 앞에 붙여 돌려준다"""
    out = []
    for m in re.finditer(r'<TABLE-GROUP\s+ACLASS="\{XBRL\}NT_([CS])_(\w+)"[^>]*>', xml):
        end = xml.find('</TABLE-GROUP>', m.end())
        blk = xml[m.end():end if end > 0 else m.end() + 200000]
        title = re.search(r'<TITLE[^>]*>(.*?)</TITLE>', blk, re.S)
        if not title or not _has(_text(title.group(1)), words):
            continue
        who, mult, unit, used = None, None, None, set()
        for t in re.findall(r'<TABLE\b.*?</TABLE>', blk, re.S):
            txt = _text(t)
            if len(txt) < 80 and (_PERIOD.search(txt) or _UNIT.search(txt)):      # 기간·단위 표
                pm, um = _PERIOD.search(txt), _UNIT.search(txt)
                if pm:
                    who = '당기' if pm.group(1) == '당' else '전기'
                if um:
                    mult, unit = UNIT[um.group(1)], um.group(1)
                continue
            pt = parse_table(t)
            if not pt or who is None or who in used or not is_nature_table(pt):      # 기간마다 첫 표만 (뒤의 딸린 표 — 종업원급여 내역 등 — 는 뺀다)
                continue
            used.add(who)
            out.append({'basis': m.group(1), 'mult': mult or UNIT['원'], 'unit': unit or '원?', 'first': True,
                        'cols': [f'{who} {h}' for h in pt['cols']], 'rows': pt['rows']})
    return out


def note_tables(xml: str, words=NATURE_WORDS) -> List[Dict]:
    """원문에서 비용 주석 표 → [{'basis': 'C'|'S', 'mult': 억원 환산 배수, 'cols', 'rows'}] (문서 순서).
    새 형식(group_tables)이 있으면 그것을, 없으면 표 앞 문장에 words('성격별'·'영업비용', 또는 판관비)가 있는 표를 연결·별도 하나씩"""
    out = group_tables(xml, words)
    if out:
        return out
    titles = [(m.start(), _text(m.group(1))) for m in re.finditer(r'<TITLE[^>]*>(.*?)</TITLE>', xml, re.S | re.I)]
    out, seen, n_follow = [], set(), {}
    carry = None            # (끝 위치, 단위, 허용 간격) — 설명 문장 바로 뒤가 '(단위: …)' 만 든 작은 표일 때, 또는 표 뒤에 표가 이어질 때 다음 표로 넘긴다
    for m in re.finditer(r'<TABLE\b', xml, re.I):
        prev_end = xml.rfind('</TABLE>', 0, m.start())
        lead = _text(xml[max(prev_end + 8, m.start() - 900):m.start()])
        hit = _has(lead[-400:], words)
        follow = carry is not None and 0 <= m.start() - carry[0] < carry[2]
        end = xml.find('</TABLE>', m.start())
        if end < 0:
            continue
        body = xml[m.start():end + 8]
        if not hit and not follow:
            small = _text(body) if end - m.start() < 3000 else ''
            # 제목('31. 비용의 성격별 분류 (단위: 천원)')이 작은 표 안에 든 꼴 → 다음 표가 숫자 표
            carry = (end + 8, _UNIT.search(small), 300) if small and len(small) < 120 and _has(small, words) else None
            continue
        t = parse_table(body)
        u = _UNIT.search(lead[-300:]) or _UNIT.search(_text(body[:1500])) or (carry and carry[1])
        if not t:
            carry = (end + 8, u, carry[2] if carry else 300) if len(_text(body)) < 120 else None
            continue
        if not is_nature_table(t):           # 재고자산 표, 주당이익 표 …
            carry = (end + 8, u, carry[2]) if follow and carry else None
            continue
        title = next((txt for pos, txt in reversed(titles) if pos < m.start()), '')
        basis = 'C' if '연결' in title else 'S'
        unit = u.group(1) if hasattr(u, 'group') else None
        if hit and basis in seen and not follow:
            carry = None
            continue
        # 그 주석의 첫 표(first) 뒤에 바로 이어지는 표들(전기 표, 3개월 표 …)도 돌려준다 — 기준값과 맞을 때만 쓰인다(table_facts)
        first = basis not in seen
        if not first and n_follow.get(basis, 0) >= 5:
            carry = None
            continue
        seen.add(basis)
        n_follow[basis] = n_follow.get(basis, 0) + (0 if first else 1)
        out.append({'basis': basis, 'mult': UNIT[unit] if unit else UNIT['원'], 'unit': unit or '원?', 'first': first, **t})
        carry = (end + 8, unit and _UNIT.search(f'단위: {unit}'), 1500)      # 뒤따르는 표(전기 표 등)는 조금 떨어져 있어도
    return out


def months_back(end: str, n: int) -> str:
    """end(월말) 에서 n 개월 앞 월말"""
    d = date.fromisoformat(end)
    y, mth = d.year, d.month - n
    while mth <= 0:
        y, mth = y - 1, mth + 12
    nxt = date(y + (mth == 12), mth % 12 + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def period_of(end: str, span: str, fy_end_month: int = 12, prev: bool = False) -> Tuple[str, str]:
    """보고 기간 끝·종류(q|ytd) → (시작, 끝). prev 면 1년 전 같은 기간"""
    if prev:
        end = months_back(end, 12)
    e = date.fromisoformat(end)
    if span == 'q':
        n = 3
    else:
        n = (e.month - fy_end_month) % 12 or 12
    start = date.fromisoformat(months_back(end, n)) + timedelta(days=1)
    return start.isoformat(), end


_DISC = re.compile(r'중단영업|중단사업')      # 중단영업 비용 줄: 사업보고서 표에만 들어가는 경우가 있어 뺀다 (분기 표·영업이익과 범위를 맞춘다)


def _col_totals(t: Dict, ci: int, with_sum: bool = True) -> List[float]:
    """열 하나에서 '합계'일 수 있는 값들 (억원): 가장 큰 합계·소계 꼴 줄, 그 값에서 중단영업 줄을 뺀 값, (with_sum 이면) 나머지 줄의 합.
    합계 꼴 줄이 여럿이면(매출원가 소계 · 판관비 소계 · 합계) 가장 큰 것만 — 소계가 다른 기간의 합계와 우연히 맞는 일이 있다"""
    tot, rest, disc = [], 0.0, 0.0
    for label, vals in t['rows']:
        v = vals[ci] if ci < len(vals) else None
        if v is None:
            continue
        if _DISC.search(label) and key_of(label)[0] != 'total':
            disc += v * t['mult']
        elif key_of(label)[0] == 'total':
            tot.append(v * t['mult'])
        else:
            rest += v * t['mult']
    big = [max(tot, key=abs)] if tot else []
    return big + ([big[0] - disc] if big and disc else []) + ([rest] if with_sum else [])


def assign_columns(t: Dict, oracle: Dict[Tuple[str, str], List[float]], tol: float = 0.005,
                   with_sum: bool = True) -> Dict[int, Tuple[Tuple[str, str], float]]:
    """표의 열 → 기간. 머리말 문구('당반기 당2분기', '제59기', '매출원가/판관비/합계')가 회사마다 달라서, 같은 보고서의 손익 숫자를 기준값으로 쓴다:
    oracle = {(시작, 끝): [매출원가+판관비, 매출−영업이익]} (억원). 열의 합계가 어느 기간의 기준값과 0.5% 안에서 맞으면 그 열은 그 기간.
    with_sum=False 면 합계 줄이 있는 열만 본다 — 뒤따르는 표는 줄의 합이 우연히 맞는 일이 있다(주당이익 표의 숫자 합이 비용 합계와 0.5% 차이였다).
    {열 번호: ((시작, 끝), 맞은 합계)} — 한 기간에 열 하나(앞의 것). 기간이 같은 값(1분기의 3개월 = 누적)은 그대로 한 기간"""
    out, used = {}, set()
    for ci in range(len(t['cols'])):
        cands = [x for x in _col_totals(t, ci, with_sum) if abs(x) > 0.01]
        best = None
        for pe, refs in oracle.items():
            if pe in used:
                continue
            for x in cands:
                for r in refs:
                    if r and abs(x - r) <= abs(r) * tol and (best is None or abs(x - r) < best[0]):
                        best = (abs(x - r), pe, x)
        if best:
            out[ci] = (best[1], best[2])
            used.add(best[1])
    return out


def section_rows(t: Dict, ci: int, total: Optional[float]) -> set:
    """구역 제목 줄(아래 줄들의 소계인데 이름이 '연구개발비'처럼 비용 줄 같은 것)의 줄 번호. 합계가 있는데 줄의 합이 그보다 클 때만 찾는다:
    그 줄의 값이 바로 아래 이어지는 줄들의 합과 같고, 그 줄(들)을 빼면 줄의 합 = 합계가 되는 경우"""
    rows = [(i, key_of(lab)[0], (vals[ci] if ci < len(vals) else None)) for i, (lab, vals) in enumerate(t['rows'])]
    if total is None:
        tots = [v * t['mult'] for _, k, v in rows if k == 'total' and v is not None]
        total = max(tots, key=abs) if tots else None
    if total is None:
        return set()
    lines = [(i, v * t['mult']) for i, k, v in rows if k != 'total' and v is not None and not _DISC.search(t['rows'][i][0])]
    excess = sum(v for _, v in lines) - total
    if abs(excess) <= max(0.05, abs(total) * 0.0005):
        return set()
    heads = []
    for n, (i, v) in enumerate(lines):
        for seq in (lines[n + 1:], lines[:n][::-1]):       # 제목 줄(아래 줄들의 합) 또는 꼬리 소계 줄(위 줄들의 합)
            run, cnt = 0.0, 0
            for j, w in seq:
                lo, hi = min(i, j), max(i, j)
                if any(r[1] == 'total' for r in rows[lo + 1:hi]):
                    break
                run += w
                cnt += 1
                if cnt >= 2 and abs(run - v) <= max(0.05, abs(v) * 0.0005) and abs(v) > 0.05:
                    heads.append((i, v))
                    break
            if heads and heads[-1][0] == i:
                break
    for k in range(1, min(len(heads), 3) + 1):         # 제목 줄 1~3개를 빼서 합계가 맞는 조합
        from itertools import combinations
        for sub in combinations(heads, k):
            if abs(excess - sum(v for _, v in sub)) <= max(0.05, abs(total) * 0.0005):
                return {i for i, _ in sub}
    return set()


def table_facts(t: Dict, end: str, kind: str, fy_end_month: int = 12, oracle: Optional[Dict] = None,
                first: bool = True) -> List[Tuple[str, str, str, str, float, int]]:
    """표 → [(키, 이름, 시작, 끝, 억원, 순서)]. kind: 'Q'(분기·반기보고서) | 'A'(사업보고서).
    oracle 이 있고 열이 하나라도 맞으면 맞은 열만 쓴다(assign_columns). 하나도 안 맞으면 머리말로 읽는다 — 그 주석의 첫 표(first)일 때만.
    머리말로 읽을 때: 3개월/누적 표시가 없는 열은 누적으로, 같은 (당/전, 기간) 열이 겹치면 앞의 것.
    당·전 두 쌍인데 3개월/누적 표시가 없으면(머리말 둘째 줄을 못 읽은 표) 3개월·누적 순서로 본다"""
    cols = []                                                    # [(열 번호, 시작, 끝, 맞은 합계 또는 None)]
    if oracle:
        cols = [(ci, pe[0], pe[1], tot) for ci, (pe, tot) in assign_columns(t, oracle, with_sum=first).items()]
        if not cols:                                             # 단위 표시가 없거나 틀린 표: 다른 단위로 맞는지 본다 (원 ↔ 천원 ↔ 백만원)
            for mult in (UNIT['천원'], UNIT['백만원'], UNIT['원']):
                if mult == t['mult']:
                    continue
                t2 = {**t, 'mult': mult}
                hit = assign_columns(t2, oracle, with_sum=first)
                if hit:
                    t, cols = t2, [(ci, pe[0], pe[1], tot) for ci, (pe, tot) in hit.items()]
                    break
    if not cols:
        if not first:
            return []
        roles = [col_role(h) for h in t['cols']]
        # 기능별 행렬(당기 매출원가 / 당기 판관비 / 당기 합계): 합계 열만 쓴다
        func = [bool(re.search(r'매출원가|판매비|관리비|제조원가|연구개발', h)) and not re.search(r'합\s*계|[^가-힣]계$', h.strip()) for h in t['cols']]
        if any(func) and not all(func):
            roles = [(None, None) if f else r for f, r in zip(func, roles)]
        whos = [w for w, _ in roles]
        if whos == ['cur', 'cur', 'prev', 'prev'] and all(sp is None for _, sp in roles) and kind == 'Q':
            roles = [('cur', 'q'), ('cur', 'ytd'), ('prev', 'q'), ('prev', 'ytd')]
        roles = [(w, sp or 'ytd') for w, sp in roles]
        if all(w is None for w, _ in roles):                     # 머리말을 못 읽으면 앞 열 = 당기, 뒤 열 = 전기
            roles = [('cur' if i == 0 else 'prev' if i == 1 else None, 'ytd') for i in range(len(roles))]
        used = set()
        for ci, (who, span) in enumerate(roles):
            if who is None or (who, span) in used:
                continue
            used.add((who, span))
            st, en = period_of(end, span, fy_end_month, prev=(who == 'prev'))
            refs = (oracle or {}).get((st, en))
            if refs:    # 기준값이 있는데 합계가 그 0.6~1.6배 밖이면 전체 비용 표가 아니다 (일부 항목만 공시하는 회사) — 쓰지 않는다
                cands = [x for x in _col_totals(t, ci) if abs(x) > 0.01]
                if not any(0.6 <= x / r <= 1.6 for x in cands for r in refs if r):
                    continue
            cols.append((ci, st, en, None))
    out = []
    for ci, st, en, matched in cols:
        agg, totals = {}, []    # 같은 키의 줄(급여·퇴직급여·복리후생비 → emp)은 더한다 — 보고서마다 줄 나눔이 달라도 누적 차감이 맞게
        skip = section_rows(t, ci, matched)
        disc = 0.0
        for ord_, (label, vals) in enumerate(t['rows']):
            v = vals[ci] if ci < len(vals) else None
            if v is None or ord_ in skip:
                continue
            k = key_of(label)[0]
            if _DISC.search(label) and k != 'total':             # 중단영업 비용 줄은 뺀다 (합계에서도)
                disc += v * t['mult']
                continue
            if k == 'total':                                     # 합계·소계 꼴 줄은 더하지 않는다 — 아래에서 하나만 고른다
                totals.append((label, v * t['mult'], ord_))
            elif k in agg:
                agg[k][0] = agg[k][0] if label in agg[k][0].split(' + ') else f'{agg[k][0]} + {label}'
                agg[k][1] += v * t['mult']
            else:
                agg[k] = [label, v * t['mult'], ord_]
        out += [(k, lab, st, en, v, o) for k, (lab, v, o) in agg.items()]
        if matched is not None:                                  # 기준값과 맞은 합계 (합계 줄이 없으면 줄의 합)
            lab = next((l for l, v, _ in totals if abs(v - matched) < 1e-6), '합계')
            out.append(('total', lab, st, en, matched, 999))
        elif totals:                                             # 머리말로 읽을 때: 합계 꼴 줄 중 가장 큰 것 (소계보다 합계), 중단영업 줄은 뺀다
            lab, v, o = max(totals, key=lambda x: abs(x[1]))
            out.append(('total', lab, st, en, v - disc, o))
        elif agg:                                                # 합계 줄이 없는 표: 줄의 합
            out.append(('total', '줄의 합', st, en, sum(v for _, v, _ in agg.values()), 999))
    return out


# ---------------- 분기 환산 ----------------

def _months(st: str, en: str) -> int:
    a, b = date.fromisoformat(st), date.fromisoformat(en)
    return (b.year - a.year) * 12 + b.month - a.month + 1


def quarterize(vals: Dict[Tuple[str, str], float]) -> Dict[str, float]:
    """{(시작, 끝): 값} → {분기 끝: 3개월 값}. 끝이 이른 것부터:
    ① 3개월 값이 있으면 그대로
    ② 누적 값이면, 같은 회계연도의 앞 분기들이 다 있으면 누적 − 앞 분기들의 합 (4Q = 연간 − 1Q − 2Q − 3Q).
       앞 분기 3개월 값은 그 분기 보고서의 것이라 시점이 같다 — 누적끼리 빼면 나중에 재작성된 누적이 섞일 수 있다
    ③ 앞 분기가 비면 같은 시작의 직전 누적과의 차
    중간 분기가 없으면 지어내지 않는다"""
    out = {}
    for (st, en), v in sorted(vals.items(), key=lambda kv: (kv[0][1], -_months(*kv[0]))):
        n = _months(st, en)
        if n == 3:
            out[en] = v
    for (st, en), v in sorted(vals.items(), key=lambda kv: (kv[0][1], _months(*kv[0]))):
        n = _months(st, en)
        if n <= 3 or n % 3 or en in out:
            continue
        prior = [out.get(months_back(en, k)) for k in range(3, n, 3)]
        if all(p is not None for p in prior):
            out[en] = v - sum(prior)
            continue
        prev = vals.get((st, months_back(en, 3)))
        if prev is not None:
            out[en] = v - prev
    return out


def quarter_series(periods: Dict[Tuple[str, str], Dict[str, float]], keys: List[str], fill: bool) -> Dict[str, Dict[str, float]]:
    """{(시작, 끝): {키: 값}} (기간마다 표 하나) → {키: {분기 끝: 3개월 값}}.
    fill=True: 그 기간의 표에 없는 키는 0 — 표마다 줄 나눔이 달라도(사업보고서 표는 줄이 적다) 묶음의 합이 맞는다.
    fill=False: 없는 키는 비워 둔다 (원본 줄 보기 — 지어내지 않는다)"""
    out = {}
    for k in keys:
        vals = {pe: (d.get(k, 0.0) if fill else d.get(k)) for pe, d in periods.items()}
        out[k] = quarterize({pe: v for pe, v in vals.items() if v is not None})
    return out


def qlabel(end: str) -> str:
    """'2026-09-30' → '3Q26' (12월 결산 기준 달력 분기)"""
    return f'{(int(end[5:7]) - 1) // 3 + 1}Q{end[2:4]}'


# ---------------- 묶음 · 브리지 · 모델 ----------------

def grouped(lines: Dict[str, Dict], q: str) -> Dict[str, float]:
    """한 분기의 줄 {키: {'g': 묶음, 'v': {분기: 값}}} → {묶음: 값}. 합계가 있으면 '기타' = 합계 − 나머지 (합이 맞게)"""
    out = {}
    for k, ln in lines.items():
        v = ln['v'].get(q)
        if v is None or k == 'total':
            continue
        out[ln['g']] = out.get(ln['g'], 0.0) + v
    tot = (lines.get('total') or {}).get('v', {}).get(q)
    if tot is not None:
        named = sum(v for g, v in out.items() if g != '기타')
        out['기타'] = tot - named
    return out


def bridge(g0: Dict[str, float], rev0: float, g1: Dict[str, float], rev1: float) -> List[Tuple[str, float]]:
    """묶음별 매출 대비 비중 변화(%p, 양수 = 비용 비중이 늘어 OPM 을 깎음) — 큰 순"""
    if not rev0 or not rev1:
        return []
    out = [(g, (g1.get(g, 0.0) / rev1 - g0.get(g, 0.0) / rev0) * 100) for g in set(g0) | set(g1)]
    return sorted(out, key=lambda x: -abs(x[1]))


def model(hist: List[Tuple[float, Dict[str, float]]], rev: float) -> Optional[Dict]:
    """최근 분기들 [(매출, {묶음: 값})…] (오래된 것부터) → 매출 rev 일 때의 비용·영업이익.
    고정비성 묶음(FIXED)은 직전 분기 금액, 나머지는 최근(최대 4분기) 매출 대비 비율 평균.
    {'var': {묶음: 비율}, 'fix': {묶음: 금액}, 'cost', 'op', 'opm'}"""
    hist = [(r, g) for r, g in hist if r and g][-4:]
    if not hist or not rev:
        return None
    groups = {g for _, gs in hist for g in gs}
    fix = {g: hist[-1][1].get(g, 0.0) for g in groups if g in FIXED}
    var = {g: sum(gs.get(g, 0.0) / r for r, gs in hist) / len(hist) for g in groups if g not in FIXED}
    cost = sum(fix.values()) + sum(v * rev for v in var.values())
    return {'var': {g: round(v, 5) for g, v in var.items()}, 'fix': {g: round(v, 1) for g, v in fix.items()},
            'cost': round(cost, 1), 'op': round(rev - cost, 1), 'opm': round((rev - cost) / rev * 100, 2)}


# ---------------- 리포트 문장 ----------------

def quarter_of_report(d: str, ends: List[str], lead: int = 20) -> Optional[str]:
    """리포트 날짜 → 그 글이 다루는 분기 끝 (분기 말 lead 일 전부터는 그 분기의 프리뷰로 본다)"""
    cut = (date.fromisoformat(d) + timedelta(days=lead)).isoformat()
    past = [e for e in ends if e <= cut]
    return max(past) if past else None


def evidence(text: str, limit: int = 3) -> List[Tuple[List[str], str]]:
    """글 → [(요인들, 문장)] 요인 낱말이 든 문장. '마진' 같은 일반 낱말만 든 문장은 뒤로"""
    out = []
    for s in re.split(r'(?<=[.!?다음])\s+|\n+', text or ''):
        s = s.strip(' -·•')
        if not (12 <= len(s) <= 220):
            continue
        hits = [g for g, ws in WORDS.items() if any(w.lower() in s.lower() for w in ws)]
        if hits:
            out.append((hits, s))
    out.sort(key=lambda x: (x[0] == ['마진'], -len(x[0])))
    return out[:limit]


# ---------------- 부문·제품·지역 ----------------
VIEW_NAME = {'seg': '부문', 'prod': '제품·서비스', 'geo': '지역'}
_AGG = re.compile(r'합계|소계|^계$|^보고부문$|^영업부문$|^부문$|총계|조정사항전|조정전|^중단영업$|^중단사업$')
_HOME = {'한국', '대한민국', '국내', '국내매출', '내수', '본사소재지국가', '본사 소재지 국가'}


def seg_name(n: str) -> str:
    """줄 이름 정리: 국내를 가리키는 여러 표기(한국·대한민국·내수)는 '국내'로"""
    n = re.sub(r'\s+', ' ', n or '').strip()
    return '국내' if n.replace(' ', '') in {x.replace(' ', '') for x in _HOME} else n


def rename_map(tables: Dict[Tuple[str, str], Dict[str, Dict[str, float]]]) -> Dict[str, str]:
    """{(시작, 끝): {rcept: {이름: 값}}} → {옛 이름: 새 이름}. 같은 기간이 두 보고서에 있을 때, 한쪽에만 있는 이름끼리 값이 같으면 같은 줄이다
    (회사가 이름표를 바꿨다: 캡슐 등 → 캡슐, 기타지역 → 기타 국가). 새 이름 = 더 나중 보고서의 것"""
    out = {}
    for pe, by in tables.items():
        rcs = sorted(by)
        if len(rcs) < 2:
            continue
        new = by[rcs[-1]]
        for r in rcs[:-1]:
            for n, v in by[r].items():
                if n in new or n in out or v is None or abs(v) < 0.05:
                    continue
                cand = [m for m, w in new.items() if m not in by[r] and w is not None and abs(w - v) <= max(0.05, abs(v) * 5e-4)]
                if len(cand) == 1:
                    out[n] = cand[0]
    for k in list(out):                      # 이름이 두 번 바뀐 경우
        seen = {k}
        while out[k] in out and out[k] not in seen:
            seen.add(out[k])
            out[k] = out[out[k]]
    return out
_GENERIC = {'국내', '해외', '기타', '기타부문', '조정', '기타 부문', '외국', '내수', '수출', '본사', '공통'}


def pick_members(q: Dict[str, Dict[str, float]]) -> List[str]:
    """보기 하나의 {이름: {분기: 값}} 에서 줄로 쓸 이름 (조정 제외). 합계·소계 꼴 이름은 빼고,
    '해외'는 다른 나라 줄이 따로 있으면 그 합이라 뺀다 (국내/해외 둘뿐이면 둔다)"""
    names = [n for n in q if n != '조정' and not _AGG.search(n.replace(' ', ''))]
    others = [n for n in names if n not in ('국내', '해외')]
    if '해외' in names and others:
        names.remove('해외')
    return names


def seg_check(members: Dict[str, float], adj: Optional[float], total: Optional[float], tol: float = 0.02,
              partial_ok: bool = False) -> Optional[str]:
    """줄의 합(+조정) = 전체 매출인가. 어긋나면 사유 글, 맞으면 None.
    partial_ok: 합이 전체보다 작은 것은 봐준다 (제품 보기 — 회사가 주요 제품만 적는다)"""
    if total is None or not members:
        return None
    s = sum(v for v in members.values() if v is not None) + (adj or 0.0)
    if partial_ok and s <= total * (1 + tol):
        return None
    if abs(s - total) > max(1.0, abs(total) * tol):
        return f'줄의 합 {s:.1f} ≠ 매출 {total:.1f}'
    return None


def seg_verdict(members: Dict[str, float], adj: Optional[float], total: Optional[float], has_adj_elsewhere: bool = False,
                tol: float = 0.02) -> Tuple[Optional[str], Optional[str]]:
    """(경고, 안내). 줄의 합(+조정)이 전체 매출보다 **크면** 경고 — 같은 매출을 두 번 셌을 수 있다.
    **작으면** 안내 — 그 분기에 일부 줄(국내 매출, 기타 부문 등)이 표시되지 않았을 뿐 보이는 숫자는 맞다.
    조정이 다른 분기에는 있는데 이 분기에만 없어서 큰 경우도 안내 (부문 값은 내부거래 제거 전)"""
    if total is None or not members:
        return None, None
    vals = [v for v in members.values() if v is not None]
    s = sum(vals) + (adj or 0.0)
    gap = s - total
    if abs(gap) <= max(1.0, abs(total) * tol):
        return None, None
    if gap < 0:
        return None, f'줄의 합 {s:.1f} 이 전체 매출 {total:.1f} 보다 {-gap:.1f} 작음 — 이 분기에 표시되지 않은 줄이 있음'
    if (adj is None or abs(adj) < 0.05) and has_adj_elsewhere:
        return None, f'줄의 합 {s:.1f} 이 전체 매출 {total:.1f} 보다 {gap:.1f} 큼 — 이 분기는 내부거래 조정이 표시되지 않음 (부문 값은 조정 전)'
    return f'줄의 합 {s:.1f} > 매출 {total:.1f} ({gap:+.1f}) — 내부거래 제거 전 금액이거나 같은 매출이 두 줄에 들어갔을 수 있음', None


def best_subset(rev: Dict[str, Dict[str, float]], names: List[str], adj: Dict[str, float], total: Dict[str, float],
                ends: List[str], tol: float = 0.003) -> Optional[List[str]]:
    """줄을 다 더하면 전체 매출과 안 맞을 때(한 표에 분류가 두 벌 — 상품·제품·가맹점 / 재화의 판매·용역의 제공), 합이 전체 매출과 맞는 줄 묶음을 찾는다.
    분기의 80% 이상(최소 4분기)에서 맞는 묶음 중 줄이 가장 많은 것. 없으면 None. 줄이 12개를 넘으면 찾지 않는다.
    허용 오차는 좁게(0.3%) — 넓으면 작은 줄이 다른 벌의 줄과 바뀌어 들어간다"""
    from itertools import combinations
    qs = [e for e in ends if total.get(e)]
    if not (2 <= len(names) <= 12) or len(qs) < 2:
        return None
    # 4분기 이상이면 80% 이상, 2~3분기뿐이면 전부 더 좁은 오차(0.1%)로 맞아야 — 분기가 적으면 우연히 맞는 묶음이 나온다
    need = max(4, -(-len(qs) * 8 // 10)) if len(qs) >= 4 else len(qs)
    if len(qs) < 4:
        tol = min(tol, 0.001)
    for k in range(len(names) - 1, 1, -1):
        found = []
        for sub in combinations(names, k):
            ok = sum(1 for e in qs if abs(sum(rev[n].get(e) or 0.0 for n in sub) + (adj.get(e) or 0.0) - total[e]) <= max(1.0, abs(total[e]) * tol))
            if ok >= need:
                found.append((ok, sub))
        if found:
            return list(max(found)[1])
    return None


def merge_similar(vals: Dict[str, Dict], recent: Dict[str, str]) -> Dict[str, Dict]:
    """철자가 거의 같은 이름(Harman/Haman, 'DS 부문'/'DS부문')을 한 줄로. recent = {이름: 그 이름이 마지막으로 쓰인 기간 끝}.
    가장 최근까지 쓰인 이름이 대표이고, 같은 기간 값은 대표 이름의 것을 둔다"""
    from difflib import SequenceMatcher
    norm = lambda n: re.sub(r'\s+|부문|사업부|등$', '', re.sub(r'\s*등$', '', n)).lower()
    reps, out = [], {}
    for n in sorted(vals, key=lambda n: recent.get(n, ''), reverse=True):
        r = next((x for x in reps if norm(x) == norm(n) or (min(len(norm(x)), len(norm(n))) >= 4
                                                             and SequenceMatcher(None, norm(x), norm(n)).ratio() >= 0.8)), None)
        if r is None:
            reps.append(n)
            out[n] = dict(vals[n])
        else:
            out[r] = {**vals[n], **out[r]}
    return out


def contribution(cur: Dict[str, float], prev: Dict[str, float]) -> List[Tuple[str, float]]:
    """전년 동기 대비 매출 증가율에 대한 줄별 기여(%p) = (이번 − 작년) ÷ 작년 합. 큰 순"""
    base = sum(v for v in prev.values() if v is not None)
    if not base:
        return []
    out = [(n, ((cur.get(n) or 0.0) - (prev.get(n) or 0.0)) / abs(base) * 100) for n in set(cur) | set(prev)]
    return sorted(out, key=lambda x: -abs(x[1]))


def mention_key(name: str) -> Optional[str]:
    """부문 이름 → 리포트 문장에서 찾을 낱말 ('DS 부문' → 'DS', '제조부문' → '제조'). 너무 흔한 이름은 None"""
    if name in _GENERIC:
        return None
    k = re.sub(r'\s*(사업)?부문$|\s*사업부$|\s*등$', '', name).strip()
    return k if len(k) >= 2 and k not in _GENERIC else None


def mentions(text: str, names: List[str], limit: int = 3) -> List[Tuple[str, str]]:
    """글에서 부문 이름이 든 문장 [(이름, 문장)]"""
    keys = [(n, mention_key(n)) for n in names]
    keys = [(n, k) for n, k in keys if k]
    out = []
    for s in re.split(r'(?<=[.!?다음])\s+|\n+', text or ''):
        s = s.strip(' -·•')
        if not (12 <= len(s) <= 220):
            continue
        for n, k in keys:
            if re.search(r'(?<![A-Za-z0-9가-힣])' + re.escape(k) if re.match(r'[A-Za-z]', k) else re.escape(k), s):
                out.append((n, s))
                break
        if len(out) >= limit:
            break
    return out
