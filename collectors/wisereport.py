"""
네이버 종목분석(navercomp.wisereport.co.kr, FnGuide 제공) 컨센서스 탭 파서/페처

사용하는 응답 (컨센서스 탭 c1050001.aspx 가 스스로 호출하는 것과 동일)
- flag=2 : 연간 실적·추정 표 (FY-4A ~ FY+2E)
- flag=4 : 컨센서스 추이 (선택 연도의 현재/1주/1개월/3개월/1년 전)
- c1010001.aspx 헤더 : 시장(KOSPI/KOSDAQ), 거래소 업종, WICS

주의: sDT(날짜) 파라미터는 무시되고 항상 최신값이 온다 → 과거 백필 불가.
"""

import html
import re
from datetime import datetime
from typing import Dict, List, Optional

BASE = 'https://navercomp.wisereport.co.kr'
CNS_URL = BASE + '/company/ajax/c1050001_data.aspx'
OVERVIEW_URL = BASE + '/v2/company/c1010001.aspx'

# flag=4 ACC_CD → metric
TREND_ACC = {
    '121000': 'revenue',
    '121500': 'op',
    '122710': 'ni',
    '312000': 'eps',
    '610100': 'opinion',
}

_YYMM_RE = re.compile(r'(\d{4})\.(\d{2})\(([A-Z])\)')


def to_num(v) -> Optional[float]:
    """'2,366.4' → 2366.4 / '', '-', 'N/A', None → None"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(',', '').strip()
    if s in ('', '-', 'N/A', 'NA'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ------------------------------------------------------------
# 파서 (순수 함수 — 테스트 대상)
# ------------------------------------------------------------

def parse_annual(payload: Dict) -> List[Dict]:
    """flag=2 응답 → 연도별 dict 리스트. 형식이 다르면 ValueError."""
    rows = payload.get('JsonData')
    if rows is None:
        raise ValueError('JsonData 없음')
    out = []
    for r in rows:
        m = _YYMM_RE.fullmatch(str(r.get('YYMM', '')).strip())
        if not m:
            raise ValueError(f"YYMM 형식 변경: {r.get('YYMM')!r}")
        year, month, kind = m.groups()
        row = {
            'fy': int(year),
            'fy_month': int(month),
            'is_estimate': 1 if kind == 'E' else 0,
            'basis': r.get('MAIN'),
            'revenue': to_num(r.get('SALES')),
            'op': to_num(r.get('OP')),
            'ni': to_num(r.get('NP')),
            'eps': to_num(r.get('EPS')),
            'bps': to_num(r.get('BPS')),
            'roe': to_num(r.get('ROE')),
        }
        # 커버리지 없는 종목도 빈 (E) 행이 내려옴 → 값이 하나도 없으면 버림
        if row['is_estimate'] and all(row[k] is None for k in ('revenue', 'op', 'ni', 'eps')):
            continue
        out.append(row)
    return out


def parse_trend(payload: Dict) -> List[Dict]:
    """flag=4 응답 → metric별 dict 리스트 (TREND_ACC 에 있는 항목만)."""
    rows = payload.get('JsonData')
    if rows is None:
        raise ValueError('JsonData 없음')
    out = []
    for r in rows:
        metric = TREND_ACC.get(str(r.get('ACC_CD')))
        if not metric:
            continue
        dt = r.get('DT')
        vals = {}
        for key, src in (('now', 'VAL1'), ('w1', 'VAL2'), ('m1', 'VAL3'), ('m3', 'VAL4'), ('y1', 'VAL5')):
            v = to_num(r.get(src))
            # 그 시점에 해당 연도 컨센서스가 없으면 0 으로 내려옴 (예: 1년 전의 FY+2)
            vals[key] = None if v == 0 else v
        out.append({
            'metric': metric,
            'cns_date': datetime.strptime(dt, '%Y%m%d').strftime('%Y-%m-%d') if dt else None,
            **vals,
        })
    return out


_NAME_RE = re.compile(r'<span class="name">\s*(.*?)\s*</span>', re.S)
_MARKET_RE = re.compile(r'<dt class="line-left">\s*(KOSPI|KOSDAQ|KONEX)\s*:\s*(.*?)\s*</dt>', re.S)
_WICS_RE = re.compile(r'<dt class="line-left">\s*WICS\s*:\s*(.*?)\s*</dt>', re.S)


def parse_overview(page: str) -> Dict:
    """c1010001.aspx HTML 헤더 → 이름/시장/거래소업종/WICS"""
    def grab(rx, idx=1):
        m = rx.search(page)
        return html.unescape(m.group(idx)).strip() if m else None
    return {
        'name': grab(_NAME_RE),
        'market': grab(_MARKET_RE, 1),
        'market_sector': grab(_MARKET_RE, 2),
        'wics': grab(_WICS_RE),
    }


# ------------------------------------------------------------
# 페처
# ------------------------------------------------------------

def _cns_params(code: str, flag: int, fin_gubun: str = 'MAIN', **extra) -> Dict:
    params = {
        'flag': flag,
        'cmp_cd': code,
        'finGubun': fin_gubun,  # MAIN = 주재무제표(보통 연결), IFRSS = 별도
        'frq': 0,               # 연간
        'sDT': datetime.now().strftime('%Y%m%d'),
        'chartType': 'svg',
    }
    params.update(extra)
    return params


def fetch_annual(session, code: str, fin_gubun: str = 'MAIN', timeout: float = 10) -> List[Dict]:
    r = session.get(CNS_URL, params=_cns_params(code, 2, fin_gubun), timeout=timeout)
    r.raise_for_status()
    if not r.text.strip():
        return []
    return parse_annual(r.json())


def fetch_trend(session, code: str, fy: int, fy_month: int, fin_gubun: str = 'MAIN',
                timeout: float = 10) -> List[Dict]:
    params = _cns_params(code, 4, fin_gubun, yymm=f'{fy}{fy_month:02d}', acc_cd='121000')
    r = session.get(CNS_URL, params=params, timeout=timeout)
    r.raise_for_status()
    if not r.text.strip():
        return []
    return parse_trend(r.json())


def fetch_overview(session, code: str, timeout: float = 10) -> Dict:
    r = session.get(OVERVIEW_URL, params={'cmp_cd': code}, timeout=timeout)
    r.raise_for_status()
    return parse_overview(r.text)
