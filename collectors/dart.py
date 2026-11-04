"""
금융감독원 Open DART: 공시 목록 + 공시 원문(XML)에서 항목 뽑기

- list.json      : 날짜별 공시 목록 (corp_cls Y=유가증권, K=코스닥)
- document.xml   : 공시 원문 (ZIP 안의 XML). 표 칸을 순서대로 늘어놓은 뒤 '항목 이름 → 다음 칸' 으로 읽는다.

종류(kind)는 공시 제목으로 정한다. 원문 양식은 거래소 서식이라 회사마다 같다.
금액은 원 단위 그대로, 잠정실적은 억원으로 바꿔 둔다.
"""

import html
import io
import re
import zipfile
from typing import Dict, List, Optional

API = 'https://opendart.fss.or.kr/api'

# 공시 제목(공백 제거) 안의 문구 → 종류. 위에서부터 먼저 맞는 것.
KINDS = [
    ('단일판매ㆍ공급계약해지', 'contract_x'),
    ('단일판매ㆍ공급계약체결', 'contract'),
    ('영업(잠정)실적(공정공시)', 'earn'),
    ('결산실적공시예고', 'preview'),
    ('기업설명회(IR)개최', 'ir'),
    ('주식소각결정', 'cancel'),
    ('자기주식취득신탁계약체결결정', 'trust'),
    ('자기주식취득결정', 'buyback'),
    ('전환사채권발행결정', 'cb'),
    ('신주인수권부사채권발행결정', 'bw'),
    ('교환사채권발행결정', 'eb'),
    ('유상증자결정', 'rights'),
    ('무상증자결정', 'bonus'),
    ('최대주주변경', 'holder'),
    ('타법인주식및출자증권취득결정', 'invest'),
    ('현금ㆍ현물배당결정', 'dividend'),
    ('투자판단관련주요경영사항', 'biz'),
]
SKIP = ('최대주주등소유주식변동신고서', '만기전', '해지결정', '취득결과', '처분', '첨부정정', '첨부추가')


def kind_of(report_nm: str) -> Optional[str]:
    n = re.sub(r'\s+', '', report_nm)
    if any(s in n for s in SKIP):
        return None
    for key, k in KINDS:
        if key in n:
            return k
    return None


def fetch_list(session, key: str, day: str, timeout: float = 20) -> List[Dict]:
    """day: YYYYMMDD. 그날 전체 공시 (유가·코스닥만)"""
    rows, page = [], 1
    while True:
        r = session.get(f'{API}/list.json', params={'crtfc_key': key, 'bgn_de': day, 'end_de': day,
                                                    'page_no': page, 'page_count': 100}, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        if j.get('status') == '013':   # 조회된 데이터 없음
            return []
        if j.get('status') != '000':
            raise ValueError(f"DART {j.get('status')}: {j.get('message')}")
        rows += j['list']
        if page >= int(j['total_page']):
            break
        page += 1
    return [r for r in rows if r.get('corp_cls') in ('Y', 'K') and r.get('stock_code')]


def cells_of(xml: str) -> List[str]:
    xml = re.sub(r'<style.*?</style>', '', xml, flags=re.S)
    out = (html.unescape(re.sub(r'\s+', ' ', c)).strip() for c in re.split(r'<[^>]+>', xml))
    return [c for c in out if c]


def fetch_cells(session, key: str, rcept_no: str, timeout: float = 30) -> List[str]:
    r = session.get(f'{API}/document.xml', params={'crtfc_key': key, 'rcept_no': rcept_no}, timeout=timeout)
    r.raise_for_status()
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        raise ValueError(f'원문 없음: {r.content[:120]!r}')
    raw = z.read(sorted(z.namelist())[0])
    for enc in ('utf-8', 'euc-kr', 'cp949'):
        try:
            return cells_of(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return cells_of(raw.decode('utf-8', 'replace'))


# ---------- 칸 읽기 ----------
def _norm(s: str) -> str:
    return re.sub(r'\s+', '', s)


def find(c: List[str], label: str, start: int = 0) -> int:
    """label 로 시작하는 첫 칸 위치 (공백 무시). 없으면 -1"""
    lab = _norm(label)
    for i in range(start, len(c)):
        if _norm(c[i]).startswith(lab):
            return i
    return -1


def after(c: List[str], label: str, k: int = 1, start: int = 0) -> Optional[str]:
    i = find(c, label, start)
    if i < 0 or i + k >= len(c):
        return None
    v = c[i + k]
    return None if v in ('-', '') else v


def num(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).replace(',', '').replace(' ', '').strip()
    neg = s.startswith('(') and s.endswith(')')
    s = s.strip('()')
    m = re.fullmatch(r'[-+]?\d+(\.\d+)?', s)
    if not m:
        return None
    x = float(s)
    return -x if neg else x


def ymd(v) -> Optional[str]:
    if not v:
        return None
    m = re.search(r'(\d{4})\s*[-.년]\s*(\d{1,2})\s*[-.월]\s*(\d{1,2})', v)
    return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else None


# ---------- 종류별 ----------
def _span(c, label, stop):
    """label 칸 다음부터 stop 으로 시작하는 칸 전까지 이어 붙인 글 (여러 칸으로 나뉜 계약명)"""
    i = find(c, label)
    if i < 0:
        return None
    out = []
    for x in c[i + 1:i + 8]:
        if _norm(x).startswith(_norm(stop)):
            break
        out.append(x)
    s = ' '.join(out).strip()
    return None if s in ('', '-') else s


def parse_contract(c):
    # 유가증권 양식: '1. 판매ㆍ공급계약 구분' + '- 체결계약명', 코스닥 양식: '1. 판매ㆍ공급계약 내용'
    name = after(c, '-체결계약명') or _span(c, '1.판매ㆍ공급계약내용', '2.')
    return {
        'name': name,
        'amt': num(after(c, '계약금액(원)')) or num(after(c, '계약금액총액(원)')) or num(after(c, '확정계약금액')),
        'rev': num(after(c, '최근매출액(원)')),
        'pct': num(after(c, '매출액대비(%)')),
        'party': after(c, '3.계약상대'),
        'region': after(c, '4.판매ㆍ공급지역'),
        'start': ymd(after(c, '시작일')), 'end': ymd(after(c, '종료일')),
    }


def parse_contract_x(c):
    return {
        'name': after(c, '-체결계약명') or _span(c, '1.판매ㆍ공급계약내용', '2.') or after(c, '계약명'),
        'amt': num(after(c, '해지금액(원)')) or num(after(c, '계약금액(원)')) or num(after(c, '계약금액총액(원)')),
        'pct': num(after(c, '매출액대비(%)')),
        'party': after(c, '계약상대'),
        'reason': after(c, '해지사유'),
    }


EARN_ROWS = [('sales', ('매출액', '영업수익', '수익(매출액)', '순영업수익')), ('op', ('영업이익',)),
             ('pbt', ('법인세비용차감전',)), ('cnp', ('지배기업', '지배주주')), ('np', ('당기순이익',))]
UNITS = {'원': 1e-8, '천원': 1e-5, '백만원': 1e-2, '억원': 1.0}


def parse_earn(c):
    unit = 1e-2
    for x in c:
        m = re.search(r'단위\s*:\s*([천백만억]*원)', x)
        if m:
            unit = UNITS.get(m.group(1), unit)
            break
    period = next((x.strip('()') for x in c if re.fullmatch(r'\(\d{4}년 \d분기\)|\(\d{4}년 (상|하)반기\)|\(\d{4}년\)', x)), None)
    end = ymd(after(c, '당기실적', 3))
    if not period and end:   # 별도 양식은 '(2026년 3분기)' 칸이 없다 → 끝나는 달로 (12월 결산 기준)
        q = {'03': '1분기', '06': '2분기', '09': '3분기', '12': '4분기'}.get(end[5:7])
        period = f'{end[:4]}년 {q}' if q else None
    rows = {}
    for i in range(len(c) - 8):
        if c[i + 1] != '당해실적':
            continue
        lab = _norm(c[i])
        key = next((k for k, keys in EARN_ROWS if any(lab.startswith(_norm(w)) or _norm(w) in lab for w in keys)
                    and not (k == 'sales' and '이익' in lab)), None)
        if not key or key in rows:
            continue
        v, prev, qoq, _, yv, yoy = (c[i + 2 + j] for j in range(6))
        rows[key] = {'v': _eok(num(v), unit), 'prev': _eok(num(prev), unit), 'qoq': num(qoq),
                     'yv': _eok(num(yv), unit), 'yoy': num(yoy)}
    return {'period': period, 'end': end, 'rows': rows}


def _eok(v, unit):
    return None if v is None else round(v * unit, 1)


def parse_preview(c):
    return {'date': ymd(after(c, '결산실적공시예정일') or after(c, '3.결산실적공시예정일')),
            'start': ymd(after(c, '시작일')), 'end': ymd(after(c, '종료일')),
            'note': after(c, '4.기타투자판단에참고할사항')}


def parse_ir(c):
    i = find(c, '일시')
    t = c[i + 2] if i >= 0 and i + 2 < len(c) and re.fullmatch(r'\d{1,2}:\d{2}.*', c[i + 2]) else None
    return {'date': ymd(after(c, '일시')), 'time': t, 'place': after(c, '장소'),
            'who': after(c, '2.참가대상자'), 'how': after(c, '4.개최방법'),
            'what': after(c, '6.주요설명회내용') or after(c, '3.개최목적')}


def parse_cancel(c):
    return {'shares': num(after(c, '보통주식(주)')), 'total': num(after(c, '보통주식(주)', start=find(c, '2.발행주식총수'))),
            'amt': num(after(c, '4.소각예정금액(원)')), 'how': after(c, '6.소각할주식의취득방법'),
            'date': ymd(after(c, '7.소각예정일'))}


def parse_buyback(c):
    return {'shares': num(after(c, '보통주식', start=find(c, '1.취득예정주식'))),
            'amt': num(after(c, '보통주식', start=find(c, '2.취득예정금액'))),
            'start': ymd(after(c, '시작일')), 'end': ymd(after(c, '종료일')),
            'why': after(c, '5.취득목적'), 'how': after(c, '6.취득방법')}


def parse_trust(c):
    return {'amt': num(after(c, '1.계약금액(원)')), 'start': ymd(after(c, '시작일')), 'end': ymd(after(c, '종료일')),
            'why': after(c, '3.계약목적'), 'broker': after(c, '5.계약체결기관')}


def parse_bond(c):
    i = find(c, '발행대상자명')
    investors = []
    if i >= 0:
        for x in c[i + 6:i + 200]:
            if x.startswith(('※', '【')) or re.match(r'\d+\.\s', x):
                break
            if (x in ('-', '') or num(x) is not None or len(x) > 40 or x.startswith(('(', '"'))
                    or any(w in x for w in ('선정', '이사회', '관계', '해당사항', '거래내역', '최대주주'))):
                continue
            if x not in investors:
                investors.append(x)
    cs = find(c, '전환청구기간')
    if cs < 0:
        cs = find(c, '권리행사기간')
    if cs < 0:
        cs = find(c, '교환청구기간')
    return {
        'kind': after(c, '종류', start=find(c, '1.사채의종류')),
        'amt': num(after(c, '2.사채의권면')),
        'how': after(c, '8.사채발행방법'),
        'price': num(after(c, '전환가액(원/주)')) or num(after(c, '행사가액(원/주)')) or num(after(c, '교환가액(원/주)')),
        'floor': num(after(c, '최저조정가액(원)')),
        'cpn': num(after(c, '표면이자율(%)')), 'ytm': num(after(c, '만기이자율(%)')),
        'pay': ymd(after(c, '12.납입일') or after(c, '납입일')),
        'from': ymd(after(c, '시작일', start=cs)) if cs >= 0 else None,
        'to': ymd(after(c, '종료일', start=cs)) if cs >= 0 else None,
        'ratio': num(after(c, '주식총수대비비율(%)')),
        'investors': [x for x in investors if x and x != '-'],
    }


def parse_rights(c):
    s = find(c, '4.자금조달의목적')
    e = find(c, '5.증자방식')
    total = sum(num(c[k + 1]) or 0 for k in range(s, e) if s >= 0 and e > s and c[k].endswith('(원)'))
    return {'common': num(after(c, '보통주식(주)')), 'other': num(after(c, '기타주식(주)')),
            'amt': total or None, 'how': after(c, '5.증자방식'),
            'price': num(after(c, '보통주식(원)', start=find(c, '6.신주발행가액')))}


def parse_bonus(c):
    return {'common': num(after(c, '보통주식(주)')), 'per': num(after(c, '보통주식(주)', start=find(c, '4.1주당신주배정주식수'))),
            'date': ymd(after(c, '5.신주배정기준일'))}


def parse_holder(c):
    b = find(c, '변경전')
    a = find(c, '변경후')
    return {'before': after(c, '최대주주등', start=b) if b >= 0 else None,
            'before_pct': num(after(c, '소유비율(%)', start=b)) if b >= 0 else None,
            'after': after(c, '최대주주등', start=a) if a >= 0 else None,
            'after_pct': num(after(c, '소유비율(%)', start=a)) if a >= 0 else None,
            'reason': after(c, '2.변경사유'), 'why': after(c, '3.지분인수목적')}


def parse_invest(c):
    return {'target': after(c, '회사명'), 'amt': num(after(c, '취득금액(원)')),
            'eq_pct': num(after(c, '자기자본대비(%)')), 'own_pct': num(after(c, '지분비율(%)')),
            'why': after(c, '5.취득목적'), 'date': ymd(after(c, '6.취득예정일자'))}


def parse_dividend(c):
    return {'type': after(c, '1.배당구분'), 'dps': num(after(c, '보통주식', start=find(c, '3.1주당배당금'))),
            'yld': num(after(c, '보통주식', start=find(c, '4.시가배당률'))),
            'total': num(after(c, '5.배당금총액(원)')), 'date': ymd(after(c, '6.배당기준일'))}


def parse_biz(c):
    title = after(c, '1.제목')
    i = find(c, '2.주요내용')
    body = []
    if i >= 0:
        for x in c[i + 1:i + 40]:
            if x.startswith(('3.', '※ 관련공시')) or len(' '.join(body)) > 400:
                break
            if '투자유의' in x or '보장하지' in x or x.startswith('※'):
                continue
            body.append(x)
    return {'title': title, 'body': ' '.join(body)[:400]}


PARSERS = {'contract': parse_contract, 'contract_x': parse_contract_x, 'earn': parse_earn, 'preview': parse_preview,
           'ir': parse_ir, 'cancel': parse_cancel, 'buyback': parse_buyback, 'trust': parse_trust,
           'cb': parse_bond, 'bw': parse_bond, 'eb': parse_bond, 'rights': parse_rights, 'bonus': parse_bonus,
           'holder': parse_holder, 'invest': parse_invest, 'dividend': parse_dividend, 'biz': parse_biz}


def parse(kind: str, cells: List[str]) -> Dict:
    return PARSERS[kind](cells)


# ---------- 분기 컨센서스 (네이버 종목 분기 재무의 추정 열) ----------
def parse_quarter_cns(payload: Dict) -> Dict[str, Dict]:
    """{'202609': {'sales': 764, 'op': -259, 'np': -319, 'cnp': None}} — 추정(isConsensus=Y) 열만, 억원"""
    fi = payload.get('financeInfo') or {}
    keys = [t['key'] for t in fi.get('trTitleList', []) if t.get('isConsensus') == 'Y']
    names = {'매출액': 'sales', '영업이익': 'op', '당기순이익': 'np', '지배주주순이익': 'cnp'}
    out = {k: {} for k in keys}
    for row in fi.get('rowList', []):
        f = names.get(row.get('title'))
        if not f:
            continue
        for k in keys:
            v = (row.get('columns', {}).get(k) or {}).get('value')
            out[k][f] = num(v)
    return {k: v for k, v in out.items() if v.get('op') is not None or v.get('sales') is not None}


def fetch_quarter_cns(session, code: str, timeout: float = 10) -> Dict[str, Dict]:
    r = session.get(f'https://m.stock.naver.com/api/stock/{code}/finance/quarter', timeout=timeout)
    r.raise_for_status()
    return parse_quarter_cns(r.json())
