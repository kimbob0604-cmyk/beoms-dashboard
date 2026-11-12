"""
한국투자증권 Open API (조회 전용): 종목별 투자자 매매동향(일별) — 기관을 금융투자·투신·사모·은행·보험·종금(기타금융)·연기금으로,
그리고 기타법인까지 나눠 준다. 네이버·KRX 무료 화면은 외국인·기관·개인 세 구분뿐이라 이걸 쓴다.

- TR FHPTJ04160001  /uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily
  FID_COND_MRKT_DIV_CODE: J(KRX) · NX(넥스트레이드) · UN(통합). 한 번에 기준일부터 거꾸로 30거래일.
  통합(UN)의 외국인·기관·개인 수량은 네이버 투자자별 매매동향과 같다(2026-11-11 삼성전자로 확인).
  통합 기준의 기관 세부 7개를 더하면 기관 계와 같다(2026-11-12, 2만여 행에서 차이 최대 몇 백만원 — 반올림).
- 금액(*_tr_pbmn)은 백만원, 실제 체결 대금 (네이버 수량 × 종가 어림과 다름).

토큰은 하루 유효, 발급은 1분에 1번이라 파일에 캐시한다. 먼저 이 프로젝트 캐시(.cache/kis_token.json)를,
없으면 같은 키를 쓰는 stock-dashboard 의 캐시를 읽고, 둘 다 만료면 새로 받아 이 프로젝트 캐시에만 쓴다.
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

BASE = 'https://openapi.koreainvestment.com:9443'
ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILES = [ROOT / '.cache' / 'kis_token.json', Path.home() / 'stock-dashboard' / 'cache' / 'kis_token.json']
INVESTOR_TR = 'FHPTJ04160001'
INVESTOR_PATH = '/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily'

# 저장 열 → 응답 필드 (순매수 거래대금, 백만원)
FIELDS = {
    'frgn': 'frgn_ntby_tr_pbmn',      # 외국인
    'ind': 'prsn_ntby_tr_pbmn',       # 개인
    'org': 'orgn_ntby_tr_pbmn',       # 기관 계 = 아래 금융투자~연기금 합
    'sec': 'scrt_ntby_tr_pbmn',       # 금융투자(증권)
    'trust': 'ivtr_ntby_tr_pbmn',     # 투신
    'pef': 'pe_fund_ntby_tr_pbmn',    # 사모펀드
    'bank': 'bank_ntby_tr_pbmn',      # 은행
    'ins': 'insu_ntby_tr_pbmn',       # 보험
    'etcfin': 'mrbn_ntby_tr_pbmn',    # 종금 = 기타금융
    'pension': 'fund_ntby_tr_pbmn',   # 기금 = 연기금 등
    'corp': 'etc_corp_ntby_tr_pbmn',  # 기타법인
    'gov': 'etc_orgt_ntby_tr_pbmn',   # 기타(국가·지자체 등)
}


class KisError(Exception):
    pass


def keys() -> tuple:
    return os.environ.get('KIS_APP_KEY', ''), os.environ.get('KIS_APP_SECRET', '')


def _cached() -> Optional[str]:
    for p in TOKEN_FILES:
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if d.get('token') and time.time() < d.get('expires', 0) - 600:
            return d['token']
    return None


def token(session: requests.Session) -> str:
    tok = _cached()
    if tok:
        return tok
    key, secret = keys()
    if not key or not secret:
        raise KisError('KIS_APP_KEY/KIS_APP_SECRET 없음')
    r = session.post(f'{BASE}/oauth2/tokenP', json={'grant_type': 'client_credentials', 'appkey': key, 'appsecret': secret}, timeout=15)
    d = r.json()
    if not d.get('access_token'):
        raise KisError(f"토큰 발급 실패: {d.get('error_description') or d.get('msg1') or r.status_code}")
    TOKEN_FILES[0].parent.mkdir(exist_ok=True)
    TOKEN_FILES[0].write_text(json.dumps({'token': d['access_token'], 'expires': time.time() + int(d.get('expires_in', 86400))}),
                              encoding='utf-8')
    return d['access_token']


def _num(v) -> Optional[float]:
    s = str(v if v is not None else '').strip()
    if s in ('', '-'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_investor(code: str, out: List[Dict]) -> List[Dict]:
    """output2 → [{date, code, 열…}] 최신순. 거래가 없던 날(거래대금 0, 정지)은 뺀다"""
    rows = []
    for x in out or []:
        d = str(x.get('stck_bsop_date') or '')
        if len(d) != 8 or not _num(x.get('acml_tr_pbmn')):
            continue
        rows.append({'date': f'{d[:4]}-{d[4:6]}-{d[6:]}', 'code': code, **{k: _num(x.get(f)) for k, f in FIELDS.items()}})
    return rows


def investor_daily(session: requests.Session, tok: str, code: str, end: str, market: str = 'UN', retries: int = 3) -> List[Dict]:
    """end(YYYYMMDD)부터 거꾸로 30거래일. 초당 한도에 걸리면 잠깐 쉬고 다시"""
    key, secret = keys()
    h = {'Content-Type': 'application/json; charset=utf-8', 'authorization': f'Bearer {tok}', 'appkey': key, 'appsecret': secret,
         'tr_id': INVESTOR_TR, 'custtype': 'P'}
    p = {'FID_COND_MRKT_DIV_CODE': market, 'FID_INPUT_ISCD': code, 'FID_INPUT_DATE_1': end, 'FID_ORG_ADJ_PRC': '', 'FID_ETC_CLS_CODE': ''}
    for i in range(retries):
        r = session.get(f'{BASE}{INVESTOR_PATH}', headers=h, params=p, timeout=15)
        try:
            j = r.json()
        except ValueError:
            j = {}
        if j.get('rt_cd') == '0':
            return parse_investor(code, j.get('output2'))
        if j.get('msg_cd') == 'EGW00201' or r.status_code in (429, 500):   # 초당 거래건수 초과 등
            time.sleep(1 + i)
            continue
        raise KisError(f"{code}: {j.get('msg_cd')} {j.get('msg1') or r.status_code}")
    raise KisError(f'{code}: 재시도 초과')
