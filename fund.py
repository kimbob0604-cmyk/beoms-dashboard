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
    (r'합\s*계|^계$|영업비용\s*계|성격별\s*비용$|매출원가.*판매비|총\s*영업비용', 'total', '비용합계'),
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
GROUP_ORDER = ['원가', '외주비', '인건비', '감가상각비', '지급수수료', '판매수수료', 'R&D', '지급임차료', '수도광열비', '소모품비', '운반비',
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


def clean_label(s: str) -> str:
    s = re.sub(r'\(\s*(주|\*)\s*\d*\s*\)|\(\*\d*\)|\(주\d+\)|\*\d*', '', s or '')
    return re.sub(r'\s+', ' ', s).strip(' :ㆍ·')


def key_of(label: str) -> Tuple[str, str]:
    """줄 이름 → (공통 키, 묶음). 규칙에 없으면 이름 자체가 키, 묶음은 '기타'"""
    lab = clean_label(label)
    flat = lab.replace(' ', '')
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
    is_data = lambda r: len(r) > 1 and any(numeric(x) for x in r[1:])
    first = next((i for i, r in enumerate(grid) if is_data(r)), None)
    if first is None or first == 0:
        return None
    width = max(len(r) for r in grid)
    # 이름 칸이 여러 개인 표(위 칸 '성격별 비용' 아래에 세부 줄): 숫자가 시작하는 칸을 찾아 그 앞의 마지막 글을 줄 이름으로
    starts = [next(i for i, x in enumerate(r) if i and numeric(x)) for r in grid[first:] if is_data(r)]
    vstart = max(set(starts), key=starts.count)
    head = [' '.join(dict.fromkeys(h[c] for h in grid[:first] if c < len(h) and h[c])) for c in range(width)]
    rows = []
    for r in grid[first:]:
        if not is_data(r):
            continue
        label = next((x for x in reversed(r[:vstart]) if x.strip() and not numeric(x)), '')
        if not label:
            continue
        rows.append((clean_label(label), [_num(x) for x in r[vstart:]] + [None] * (width - len(r))))
    return {'cols': head[vstart:], 'rows': rows} if len(rows) >= 3 else None


def col_role(head: str) -> Tuple[Optional[str], Optional[str]]:
    """열 머리말 → (cur|prev, q|ytd|None). '당분기 3개월' → (cur, q), '전기' → (prev, None)"""
    h = head.replace(' ', '')
    who = 'cur' if re.search(r'당(분|반)?기|당기', h) else 'prev' if re.search(r'전(분|반)?기|전기', h) else None
    span = 'q' if re.search(r'3개월|분기중|최근3', h) else 'ytd' if re.search(r'누적|\d개월', h) else None
    return who, span


_PERIOD = re.compile(r'(당|전)\s*(분|반)?\s*기')
_UNIT = re.compile(r'단위\s*[:：]?\s*(백만원|천원|억원|원)')


def group_tables(xml: str, word: str = '성격별') -> List[Dict]:
    """새 형식(XBRL 꼴 문서): <TABLE-GROUP ACLASS="{XBRL}NT_C_D834300"> 안에 [기간·단위 표] → [숫자 표] 가 번갈아 나온다.
    제목에 word 가 든 묶음만. 기간 표의 '당분기'/'전분기' 를 숫자 표 열 머리말 앞에 붙여 돌려준다"""
    out = []
    for m in re.finditer(r'<TABLE-GROUP\s+ACLASS="\{XBRL\}NT_([CS])_(\w+)"[^>]*>', xml):
        end = xml.find('</TABLE-GROUP>', m.end())
        blk = xml[m.end():end if end > 0 else m.end() + 200000]
        title = re.search(r'<TITLE[^>]*>(.*?)</TITLE>', blk, re.S)
        if not title or word not in _text(title.group(1)):
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
            if not pt or who is None or who in used:      # 기간마다 첫 표만 (뒤의 딸린 표 — 종업원급여 내역 등 — 는 뺀다)
                continue
            used.add(who)
            out.append({'basis': m.group(1), 'mult': mult or UNIT['원'], 'unit': unit or '원?',
                        'cols': [f'{who} {h}' for h in pt['cols']], 'rows': pt['rows']})
    return out


def note_tables(xml: str) -> List[Dict]:
    """원문에서 비용의 성격별 분류 표 → [{'basis': 'C'|'S', 'mult': 억원 환산 배수, 'cols', 'rows'}] (문서 순서).
    새 형식(group_tables)이 있으면 그것을, 없으면 표 앞 문장에 '성격별'이 있는 표를 연결·별도 하나씩"""
    out = group_tables(xml)
    if out:
        return out
    titles = [(m.start(), _text(m.group(1))) for m in re.finditer(r'<TITLE[^>]*>(.*?)</TITLE>', xml, re.S | re.I)]
    out, seen = [], set()
    carry = None            # (끝 위치, 단위) — 설명 문장 바로 뒤가 '(단위: …)' 만 든 작은 표일 때 다음 표로 넘긴다
    for m in re.finditer(r'<TABLE\b', xml, re.I):
        prev_end = xml.rfind('</TABLE>', 0, m.start())
        lead = _text(xml[max(prev_end + 8, m.start() - 900):m.start()])
        hit = '성격별' in lead[-400:]
        follow = carry is not None and 0 <= m.start() - carry[0] < 300
        end = xml.find('</TABLE>', m.start())
        if end < 0:
            continue
        body = xml[m.start():end + 8]
        if not hit and not follow:
            small = _text(body) if end - m.start() < 3000 else ''
            # 제목('31. 비용의 성격별 분류 (단위: 천원)')이 작은 표 안에 든 꼴 → 다음 표가 숫자 표
            carry = (end + 8, _UNIT.search(small)) if small and len(small) < 120 and '성격별' in small else None
            continue
        t = parse_table(body)
        u = _UNIT.search(lead[-300:]) or _UNIT.search(_text(body[:1500])) or (carry and carry[1])
        if not t:
            carry = (end + 8, u if not hasattr(u, 'group') else u) if len(_text(body)) < 120 else None
            continue
        carry = None
        title = next((txt for pos, txt in reversed(titles) if pos < m.start()), '')
        basis = 'C' if '연결' in title else 'S'
        if basis in seen:
            continue
        unit = u.group(1) if hasattr(u, 'group') else None
        seen.add(basis)
        out.append({'basis': basis, 'mult': UNIT[unit] if unit else UNIT['원'], 'unit': unit or '원?', **t})
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


def table_facts(t: Dict, end: str, kind: str, fy_end_month: int = 12) -> List[Tuple[str, str, str, str, float, int]]:
    """표 → [(키, 이름, 시작, 끝, 억원, 순서)]. kind: 'Q'(분기·반기보고서) | 'A'(사업보고서).
    3개월/누적 표시가 없는 열은 누적으로 본다(1분기는 둘이 같다). 같은 (당/전, 기간) 열이 겹치면 앞의 것"""
    roles = []
    for h in t['cols']:
        who, span = col_role(h)
        roles.append((who, span or 'ytd'))
    if all(w is None for w, _ in roles):                       # 머리말을 못 읽으면 앞 열 = 당기, 뒤 열 = 전기
        roles = [('cur' if i == 0 else 'prev' if i == 1 else None, 'ytd') for i in range(len(roles))]
    out, used = [], set()
    for ci, (who, span) in enumerate(roles):
        if who is None or (who, span) in used:
            continue
        used.add((who, span))
        st, en = period_of(end, span, fy_end_month, prev=(who == 'prev'))
        agg = {}            # 같은 키의 줄(급여·퇴직급여·복리후생비 → emp)은 더한다 — 보고서마다 줄 나눔이 달라도 누적 차감이 맞게
        for ord_, (label, vals) in enumerate(t['rows']):
            v = vals[ci] if ci < len(vals) else None
            if v is None:
                continue
            k = key_of(label)[0]
            if k in agg:
                agg[k][0] = agg[k][0] if label in agg[k][0].split(' + ') else f'{agg[k][0]} + {label}'
                agg[k][1] += v
            else:
                agg[k] = [label, v, ord_]
        out += [(k, lab, st, en, v * t['mult'], o) for k, (lab, v, o) in agg.items()]
    return out


# ---------------- 분기 환산 ----------------

def _months(st: str, en: str) -> int:
    a, b = date.fromisoformat(st), date.fromisoformat(en)
    return (b.year - a.year) * 12 + b.month - a.month + 1


def quarterize(vals: Dict[Tuple[str, str], float]) -> Dict[str, float]:
    """{(시작, 끝): 값} → {분기 끝: 3개월 값}. 3개월 값이 있으면 그대로, 없으면 같은 시작의 누적끼리 뺀다"""
    out = {}
    for (st, en), v in sorted(vals.items(), key=lambda kv: kv[0][1]):
        n = _months(st, en)
        if n == 3:
            out[en] = v
    for (st, en), v in vals.items():
        n = _months(st, en)
        if n <= 3 or en in out:
            continue
        prev = vals.get((st, months_back(en, 3)))
        if prev is not None:
            out[en] = v - prev
        elif n == 6 and months_back(en, 3) in out:              # 상반기 누적 − 1분기(3개월 값)
            out[en] = v - out[months_back(en, 3)]
    # 누적만 있고 앞 분기들이 3개월 값으로 있는 경우 (연간 − 앞 세 분기)
    for (st, en), v in vals.items():
        n = _months(st, en)
        if en in out or n <= 3 or n % 3:
            continue
        prior = [out.get(months_back(en, k)) for k in range(3, n, 3)]
        if all(p is not None for p in prior):
            out[en] = v - sum(prior)
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
_AGG = re.compile(r'합계|소계|^계$|^보고부문$|^영업부문$|^부문$|총계')
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


def best_subset(rev: Dict[str, Dict[str, float]], names: List[str], adj: Dict[str, float], total: Dict[str, float],
                ends: List[str], tol: float = 0.003) -> Optional[List[str]]:
    """줄을 다 더하면 전체 매출과 안 맞을 때(한 표에 분류가 두 벌 — 상품·제품·가맹점 / 재화의 판매·용역의 제공), 합이 전체 매출과 맞는 줄 묶음을 찾는다.
    분기의 80% 이상(최소 4분기)에서 맞는 묶음 중 줄이 가장 많은 것. 없으면 None. 줄이 12개를 넘으면 찾지 않는다.
    허용 오차는 좁게(0.3%) — 넓으면 작은 줄이 다른 벌의 줄과 바뀌어 들어간다"""
    from itertools import combinations
    qs = [e for e in ends if total.get(e)]
    if not (2 <= len(names) <= 12) or len(qs) < 4:
        return None
    need = max(4, -(-len(qs) * 8 // 10))        # 4분기 이상 맞아야 — 분기가 적으면 우연히 맞는 묶음이 나온다
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
    norm = lambda n: re.sub(r'\s+|부문|사업부', '', n).lower()
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
