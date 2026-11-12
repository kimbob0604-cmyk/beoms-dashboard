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


# ---------------- 분봉 ----------------
MINUTE_TR = 'FHKST03010230'      # 주식일별분봉조회 — 약 1년 전까지, 한 번에 120분 (기준 시각부터 거꾸로)
MINUTE_PATH = '/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice'


def _minute_page(session, tok, code, day, hhmmss, market='UN'):
    key, secret = keys()
    h = {'Content-Type': 'application/json; charset=utf-8', 'authorization': f'Bearer {tok}', 'appkey': key, 'appsecret': secret,
         'tr_id': MINUTE_TR, 'custtype': 'P'}
    p = {'FID_COND_MRKT_DIV_CODE': market, 'FID_INPUT_ISCD': code, 'FID_INPUT_HOUR_1': hhmmss, 'FID_INPUT_DATE_1': day,
         'FID_PW_DATA_INCU_YN': 'Y', 'FID_FAKE_TICK_INCU_YN': ''}
    for i in range(3):
        r = session.get(f'{BASE}{MINUTE_PATH}', headers=h, params=p, timeout=15)
        try:
            j = r.json()
        except ValueError:
            j = {}
        if j.get('rt_cd') == '0':
            return j.get('output2') or []
        if j.get('msg_cd') == 'EGW00201' or r.status_code in (429, 500):
            time.sleep(1 + i)
            continue
        raise KisError(f"{code} {day}: {j.get('msg_cd')} {j.get('msg1') or r.status_code}")
    raise KisError(f'{code} {day}: 재시도 초과')


def _minute_day(session, tok, code: str, day: str, start: str, end: str, gap: float, market: str) -> List:
    """day(YYYYMMDD) 의 1분봉 [[HHMM, 종가, 거래량]…] 시각순 (통합: KRX+넥스트레이드). end 부터 거꾸로 120분씩"""
    bars, at = {}, end + '00'
    for _ in range(10):
        rows = _minute_page(session, tok, code, day, at, market)
        time.sleep(gap)
        same = [x for x in rows if x.get('stck_bsop_date') == day]
        for x in same:
            hm = x['stck_cntg_hour'][:4]
            c = _num(x.get('stck_prpr'))
            if c:
                bars[hm] = [hm, c, _num(x.get('cntg_vol')) or 0]
        if not same or len(same) < len(rows):      # 그날이 끝났다 (앞 거래일로 넘어감)
            break
        first = min(x['stck_cntg_hour'] for x in same)
        if first[:4] <= start:
            break
        m = int(first[:2]) * 60 + int(first[2:4]) - 1
        at = f'{m // 60:02d}{m % 60:02d}00'
    return [bars[k] for k in sorted(bars) if start <= k <= end]


TODAY_TR = 'FHKST03010200'       # 주식당일분봉조회 — 오늘 것만, 한 번에 30분. (일별분봉조회는 오늘 날짜를 주면 엉뚱한 옛날 분봉을 섞어 준다)
TODAY_PATH = '/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice'


def _minute_today(session, tok, code: str, start: str, end: str, since: str, gap: float, market: str) -> List:
    """오늘 1분봉 [[HHMM, 종가, 거래량]…] (통합). end 부터 거꾸로 30분씩, start 또는 since(이미 가진 마지막 분) 까지"""
    key, secret = keys()
    h = {'Content-Type': 'application/json; charset=utf-8', 'authorization': f'Bearer {tok}', 'appkey': key, 'appsecret': secret,
         'tr_id': TODAY_TR, 'custtype': 'P'}
    today = time.strftime('%Y%m%d')
    bars, at = {}, end + '00'
    stop = max(start, since)
    for _ in range(30):
        p = {'FID_ETC_CLS_CODE': '', 'FID_COND_MRKT_DIV_CODE': market, 'FID_INPUT_ISCD': code, 'FID_INPUT_HOUR_1': at, 'FID_PW_DATA_INCU_YN': 'Y'}
        for i in range(3):
            r = session.get(f'{BASE}{TODAY_PATH}', headers=h, params=p, timeout=15)
            try:
                j = r.json()
            except ValueError:
                j = {}
            if j.get('rt_cd') == '0':
                break
            if j.get('msg_cd') == 'EGW00201' or r.status_code in (429, 500):
                time.sleep(1 + i)
                continue
            raise KisError(f"{code} 오늘 분봉: {j.get('msg_cd')} {j.get('msg1') or r.status_code}")
        else:
            raise KisError(f'{code} 오늘 분봉: 재시도 초과')
        time.sleep(gap)
        rows = [x for x in j.get('output2') or [] if x.get('stck_bsop_date') == today]
        for x in rows:
            hm = x['stck_cntg_hour'][:4]
            c = _num(x.get('stck_prpr'))
            if c and _num(x.get('cntg_vol')) is not None:
                bars[hm] = [hm, c, _num(x.get('cntg_vol')) or 0]
        if not rows:
            break
        first = min(x['stck_cntg_hour'] for x in rows)
        if first[:4] <= stop:
            break
        m = int(first[:2]) * 60 + int(first[2:4]) - 1
        at = f'{m // 60:02d}{m % 60:02d}00'
    return [bars[k] for k in sorted(bars) if start <= k <= end]


def _traded(bars) -> bool:
    return any(b[2] for b in bars if '0900' <= b[0] <= '1530')


def _un_ok(rows, day) -> bool:
    """통합(UN) 응답의 정규장 줄에 거래량이 있으면 진짜 (넥스트레이드에 없는 종목은 거래량 0 인 가짜 줄)"""
    return any((_num(x.get('cntg_vol')) or 0) > 0 for x in rows if x.get('stck_bsop_date') == day and '090000' <= x['stck_cntg_hour'] <= '153000')


def market_for(session, tok, code: str, day: str, gap: float = 0.11) -> str:
    """그날 분봉을 받을 시장: 15:30 앞 한 쪽만 통합으로 불러 보고 정한다 ('UN' | 'J')"""
    if day == time.strftime('%Y%m%d'):
        key, secret = keys()
        h = {'Content-Type': 'application/json; charset=utf-8', 'authorization': f'Bearer {tok}', 'appkey': key, 'appsecret': secret,
             'tr_id': TODAY_TR, 'custtype': 'P'}
        p = {'FID_ETC_CLS_CODE': '', 'FID_COND_MRKT_DIV_CODE': 'UN', 'FID_INPUT_ISCD': code,
             'FID_INPUT_HOUR_1': min('153000', time.strftime('%H%M00')), 'FID_PW_DATA_INCU_YN': 'Y'}
        rows = session.get(f'{BASE}{TODAY_PATH}', headers=h, params=p, timeout=15).json().get('output2') or []
    else:
        rows = _minute_page(session, tok, code, day, '153000', 'UN')
    time.sleep(gap)
    return 'UN' if _un_ok(rows, day) else 'J'


def minute_day(session, tok, code: str, day: str, start: str = '0800', end: str = '2000', gap: float = 0.11) -> tuple:
    """day(YYYYMMDD) 의 1분봉 [[HHMM, 종가, 거래량]…] 시각순과 쓴 시장. 통합(UN, 넥스트레이드 포함)이 되면 통합,
    넥스트레이드에 없는 종목은 KRX(J — 정규장과 시간외 단일가)"""
    mk = market_for(session, tok, code, day, gap)
    return _minute_day(session, tok, code, day, start, end, gap, mk), mk


def minute_today(session, tok, code: str, start: str = '0800', end: str = '2000', since: str = '', gap: float = 0.11,
                 market: str = '') -> tuple:
    """오늘 1분봉과 쓴 시장. market 을 주면 그 시장으로 since 뒤만 (이어 받기)"""
    mk = market or market_for(session, tok, code, time.strftime('%Y%m%d'), gap)
    return _minute_today(session, tok, code, start, end, since if market else '', gap, mk), mk
