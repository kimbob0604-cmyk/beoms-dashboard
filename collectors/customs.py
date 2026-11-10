"""
관세청 수출입 통계 (공공데이터포털 apis.data.go.kr/1220000) — XML 만 준다, 페이징 없음

| 함수 | 포털 ID | 필수 | 내용 |
|---|---|---|---|
| fetch_items         | 15101609 | 기간, (HS 앞자리) | 전국 × HS10 월별 금액(달러)·중량(kg) |
| fetch_item_country  | 15100475 | 기간(12개월 이내), 국가, (HS 앞자리) | 전국 × HS10 × 국가 |
| fetch_sigungu       | 15134343 | 기간, 시도, HS6 | 시군구 × HS6 월별 금액(천 달러 → 달러로 바꿔 돌려준다). 중량 없음 |

- 기간은 YYYYMM. 한 번에 12개월까지만 부른다.
- 시도 코드는 2026-07 개편(전남광주통합특별시 12 신설, 광주 29·전남 46 은 2026-06 신고분까지)을 따른다.
- 응답 형식·한도는 KBJ 프로젝트의 실측(docs/probe_results.md §2)과 같다. 하루 한도는 데이터셋마다 약 10,000회.
"""

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional
from urllib.parse import unquote

BASE = 'https://apis.data.go.kr/1220000'
PATHS = {'items': '/Itemtrade/getItemtradeList', 'item_country': '/nitemtrade/getNitemtradeList',
         'sigungu': '/sigunguperprlstperacrs/getSigunguPerPrlstPerAcrs'}
# (코드, 이름, 쓸 수 있는 첫 달, 마지막 달)
SIDO = [('11', '서울특별시', None, None), ('12', '전남광주통합특별시', '202607', None), ('26', '부산광역시', None, None),
        ('27', '대구광역시', None, None), ('28', '인천광역시', None, None), ('29', '광주광역시', None, '202606'),
        ('30', '대전광역시', None, None), ('31', '울산광역시', None, None), ('36', '세종특별자치시', None, None),
        ('41', '경기도', None, None), ('43', '충청북도', None, None), ('44', '충청남도', None, None),
        ('46', '전라남도', None, '202606'), ('47', '경상북도', None, None), ('48', '경상남도', None, None),
        ('50', '제주특별자치도', None, None), ('51', '강원특별자치도', None, None), ('52', '전북특별자치도', None, None)]
_PERIOD = re.compile(r'(\d{4})\D{0,2}(\d{1,2})\D?')


class CustomsError(RuntimeError):
    pass


def to_num(v) -> Optional[float]:
    s = str(v if v is not None else '').replace(',', '').strip()
    if s in ('', '-'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def period(raw) -> Optional[str]:
    """'2026.01'·'202601'·'2026년 01월' → '2026-01'. 합계 줄('총계')은 None"""
    m = _PERIOD.fullmatch(str(raw or '').strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return f'{m.group(1)}-{int(m.group(2)):02d}'


def hs_norm(raw, width: int = None) -> str:
    """숫자로 온 HS 는 앞자리 0 이 빠져 있을 수 있다 → 자릿수(짝수, 또는 width)를 맞춘다"""
    s = re.sub(r'\D', '', str(raw or ''))
    if not s:
        return ''
    return s.zfill(width) if width else ('0' + s if len(s) % 2 else s)


def parse_items(text: str) -> List[Dict]:
    """공통 XML 봉투를 벗겨 item 목록(dict). resultCode 가 00 이 아니면 예외, 03(NODATA)은 빈 목록"""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise CustomsError(f'XML 아님: {text[:80]!r}') from e
    code = (root.findtext('header/resultCode') or root.findtext('.//returnReasonCode') or '').strip()
    if code == '03':
        return []
    if code not in ('00', '0'):
        msg = (root.findtext('header/resultMsg') or root.findtext('.//returnAuthMsg') or '').strip()
        raise CustomsError(f'resultCode={code} {msg}')
    return [{c.tag: (c.text or '').strip() for c in it} for it in root.iterfind('body/items/item')]


def call(session, key: str, name: str, params: Dict, timeout: float = 30) -> List[Dict]:
    if not key:
        raise CustomsError('DATAGO_KEY 없음')
    key = unquote(key) if '%' in key else key        # 포털의 '인코딩 키'를 넣어 둔 경우
    r = session.get(BASE + PATHS[name], params={'serviceKey': key, **params}, timeout=timeout)
    if r.status_code != 200:
        raise CustomsError(f'HTTP {r.status_code}')
    return parse_items(r.content.decode('utf-8', 'replace'))


def fetch_items(session, key, start: str, end: str, hs: str = None) -> List[Dict]:
    """전국 × HS10: [{ym, hs, name, usd, kg}] (수출만)"""
    rows = call(session, key, 'items', {'strtYymm': start, 'endYymm': end, **({'hsSgn': hs} if hs else {})})
    out = []
    for r in rows:
        ym = period(r.get('year'))
        hs10 = hs_norm(r.get('hsCode'))
        if ym and hs10:
            out.append({'ym': ym, 'hs': hs10, 'name': r.get('statKor') or '', 'usd': to_num(r.get('expDlr')), 'kg': to_num(r.get('expWgt'))})
    return out


def fetch_item_country(session, key, start: str, end: str, country: str, hs: str = None) -> List[Dict]:
    """전국 × HS10 × 국가(ISO 2자리): [{ym, hs, country, usd, kg}]"""
    rows = call(session, key, 'item_country', {'strtYymm': start, 'endYymm': end, 'cntyCd': country, **({'hsSgn': hs} if hs else {})})
    out = []
    for r in rows:
        ym = period(r.get('year'))
        hs10 = hs_norm(r.get('hsCd'))
        if ym and hs10:
            out.append({'ym': ym, 'hs': hs10, 'country': country, 'usd': to_num(r.get('expDlr')), 'kg': to_num(r.get('expWgt'))})
    return out


def fetch_sigungu(session, key, start: str, end: str, sido: str, hs6: str) -> List[Dict]:
    """시군구 × HS6: [{ym, sido, sgg, hs6, usd, cnt}] — 금액은 달러로 바꿔서"""
    rows = call(session, key, 'sigungu', {'strtYymm': start, 'endYymm': end, 'HsSgn': hs6, 'sidoCd': sido})
    out = []
    for r in rows:
        ym = period(r.get('priodTitle'))
        usd = to_num(r.get('expUsdAmt'))
        if ym and r.get('sggNm'):
            out.append({'ym': ym, 'sido': sido, 'sgg': r['sggNm'].strip(), 'hs6': hs_norm(r.get('hsSgn'), 6),
                        'usd': usd * 1000 if usd is not None else None, 'cnt': to_num(r.get('expCnt'))})
    return out


def sido_for(start: str, end: str) -> List[str]:
    """그 기간(YYYYMM) 전체에 쓸 수 있는 시도 코드"""
    return [c for c, _, lo, hi in SIDO if (lo is None or start >= lo) and (hi is None or end <= hi)]
