"""
KRX Open API 일별매매정보 (시장별 1회 호출로 전 종목 시가·고가·저가·종가·거래량·시총)

- sto/stk_bydd_trd : KOSPI
- sto/ksq_bydd_trd : KOSDAQ
basDd 로 과거 날짜 조회 가능. 당일 데이터는 다음 날 아침에 열린다.
"""

from typing import Dict, List, Optional

BASE = 'https://data-dbg.krx.co.kr/svc/apis'
ENDPOINTS = {'KOSPI': 'sto/stk_bydd_trd', 'KOSDAQ': 'sto/ksq_bydd_trd'}


def _num(v) -> Optional[float]:
    s = str(v or '').replace(',', '').strip()
    if s in ('', '-'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_daily(payload: Dict, market: str) -> List[Dict]:
    rows = payload.get('OutBlock_1')
    if rows is None:
        raise ValueError('OutBlock_1 없음')
    out = []
    for r in rows:
        close = _num(r.get('TDD_CLSPRC'))
        if not close:  # 거래정지 등 종가 없음
            continue
        out.append({
            'date': f"{r['BAS_DD'][:4]}-{r['BAS_DD'][4:6]}-{r['BAS_DD'][6:]}",
            'code': r['ISU_CD'],
            'name': r.get('ISU_NM'),
            'market': market,
            'close': close,
            'change_pct': _num(r.get('FLUC_RT')),
            'mcap': (_num(r.get('MKTCAP')) or 0) / 1e8,       # 억원
            'shares': _num(r.get('LIST_SHRS')),
            'trd_val': (_num(r.get('ACC_TRDVAL')) or 0) / 1e8,  # 억원
            'open': _num(r.get('TDD_OPNPRC')),
            'high': _num(r.get('TDD_HGPRC')),
            'low': _num(r.get('TDD_LWPRC')),
            'volume': _num(r.get('ACC_TRDVOL')),
        })
    return out


def fetch_daily(session, key: str, bas_dd: str, market: str, timeout: float = 30) -> List[Dict]:
    """bas_dd: YYYYMMDD. 휴장일/미공개면 빈 리스트."""
    r = session.get(f'{BASE}/{ENDPOINTS[market]}', params={'basDd': bas_dd},
                    headers={'AUTH_KEY': key}, timeout=timeout)
    r.raise_for_status()
    return parse_daily(r.json(), market)
