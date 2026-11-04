"""
네이버 증권 파서/페처: 리서치 리포트, 투자자별 순매수, 52주 신고가

사용하는 응답 (네이버 증권 웹·모바일 화면이 스스로 부르는 JSON과 동일)
- m.stock.naver.com/api/research/company?page=&pageSize=     : 종목분석 리포트 목록 (최신순)
- m.stock.naver.com/api/research/company/{id}                : 리포트 본문 요약·투자의견·목표주가
- stock.naver.com/api/stockSecurity/investor-trend/v2/domestic/{code} : 일별 외국인·기관·개인 순매수 수량
- m.stock.naver.com/api/stocks/high52week/{KOSPI|KOSDAQ}     : 그날 52주 신고가를 낸 종목
- m.stock.naver.com/api/index/{KOSPI|KOSDAQ|FUT}/integration|price : 지수·코스피200 선물 일별 종가, 투자자별 순매수, 상승/하락 종목 수
- m.stock.naver.com/api/stocks/marketValue/{KOSPI|KOSDAQ}    : 전 종목 시세 (KRX 가격이 열리기 전 임시 종가)
- api.stock.naver.com/chart/domestic/index/{code}/minute     : 지수 당일 1분봉
- fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day : 지수 일봉 (XML)

주의: 이 API들은 다른 사이트의 브라우저 호출을 막는다(CORS 403). 그래서 맥에서 받아 JSON으로 만든다.
리포트 상세의 prevGoalPrice 는 이전 목표가가 아니라 작성일 주가와 같은 값이라 쓰지 않는다.
"""

import html
import re
from typing import Dict, List, Optional

M_API = 'https://m.stock.naver.com/api'
S_API = 'https://stock.naver.com/api/stockSecurity'


def to_num(v) -> Optional[float]:
    s = str(v if v is not None else '').replace(',', '').replace('+', '').strip()
    if s in ('', '-', 'N/A'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(s: str) -> str:
    """20261030 / 2026-10-30 / 2026-10-30T… → 2026-10-30"""
    s = str(s)
    if re.fullmatch(r'\d{8}', s):
        return f'{s[:4]}-{s[4:6]}-{s[6:]}'
    return s[:10]


# ------------------------------------------------------------
# 리서치
# ------------------------------------------------------------

def parse_research_list(payload) -> List[Dict]:
    if not isinstance(payload, list):
        raise ValueError('리포트 목록 형식 변경')
    return [{
        'id': int(r['researchId']),
        'code': r.get('itemCode'),
        'name': r.get('itemName'),
        'broker': r.get('brokerName'),
        'date': _date(r['writeDate']),
        'title': (r.get('title') or '').strip(),
    } for r in payload]


_HEAD_RE = re.compile(r'<strong>(.*?)</strong>', re.S)


def _text(fragment: str) -> str:
    s = re.sub(r'<br\s*/?>|</p>', '\n', fragment)
    s = html.unescape(re.sub(r'<[^>]+>', '', s))
    return '\n'.join(line.strip() for line in s.splitlines() if line.strip())


def parse_research_detail(payload: Dict) -> Dict:
    """본문 요약을 소제목(<strong>)과 나머지 글로 나눈다."""
    rc = payload.get('researchContent')
    if not rc:
        raise ValueError('researchContent 없음')
    content = rc.get('content') or ''
    heads = [_text(h) for h in _HEAD_RE.findall(content)]
    body = _text(_HEAD_RE.sub('\n', content))
    goal = to_num(rc.get('goalPrice'))
    return {
        'id': int(rc['researchId']),
        'code': rc.get('itemCode'),
        'name': rc.get('itemName'),
        'broker': rc.get('brokerName'),
        'date': _date(rc['writeDate']),
        'title': (rc.get('title') or '').strip(),
        'opinion': (rc.get('opinion') or '').strip() or None,
        'goal': goal or None,           # 목표가 없음은 0으로 온다
        'price': to_num(rc.get('priceAtWriteDate')),
        'heads': [h for h in heads if h],
        'body': body,
        'pdf': rc.get('attachUrl'),
    }


def fetch_research_list(session, page: int, page_size: int = 100, timeout: float = 10) -> List[Dict]:
    r = session.get(f'{M_API}/research/company', params={'page': page, 'pageSize': page_size}, timeout=timeout)
    r.raise_for_status()
    return parse_research_list(r.json())


def fetch_research_detail(session, rid: int, timeout: float = 10) -> Dict:
    r = session.get(f'{M_API}/research/company/{rid}', timeout=timeout)
    r.raise_for_status()
    return parse_research_detail(r.json())


# ------------------------------------------------------------
# 투자자별 순매수
# ------------------------------------------------------------

def parse_flow(payload: Dict, code: str) -> List[Dict]:
    items = payload.get('items')
    if items is None:
        raise ValueError('items 없음')
    out = []
    for it in items:
        k = it.get('krx') or {}
        out.append({
            'date': _date(it['localTradedAt']),
            'code': code,
            'frgn': to_num(k.get('foreignNetVolume')),
            'org': to_num(k.get('organizationNetVolume')),
            'ind': to_num(k.get('individualNetVolume')),
            # 정규장 종가 (closingPrice 는 NXT 애프터마켓까지 반영된 값일 수 있음)
            'close': to_num(k.get('regularMarketClosingPrice')) or to_num(k.get('closingPrice')),
            'frgn_ratio': to_num(it.get('foreignHoldingRatio')),
        })
    return out


def fetch_flow(session, code: str, size: int = 5, timeout: float = 10) -> List[Dict]:
    r = session.get(f'{S_API}/investor-trend/v2/domestic/{code}',
                    params={'exchangeType': 'krx', 'size': size}, timeout=timeout)
    r.raise_for_status()
    return parse_flow(r.json(), code)


# ------------------------------------------------------------
# 52주 신고가
# ------------------------------------------------------------

def parse_high52(payload: Dict, market: str) -> Dict:
    stocks = payload.get('stocks')
    if stocks is None:
        raise ValueError('stocks 없음')
    rows = []
    for s in stocks:
        if s.get('stockEndType') != 'stock':   # ETF·ETN 제외
            continue
        rows.append({
            'date': _date(s['localTradedAt']),
            'code': s['itemCode'],
            'name': s.get('stockName'),
            'market': market,
            'close': to_num(s.get('closePriceRaw') or s.get('closePrice')),
            'change_pct': to_num(s.get('fluctuationsRatio')),
            'mcap': (to_num(s.get('marketValueRaw')) or 0) / 1e8,
            'trd_val': (to_num(s.get('accumulatedTradingValueRaw')) or 0) / 1e8,
        })
    return {'total': int(payload.get('totalCount') or 0), 'rows': rows}


def fetch_high52(session, market: str, page: int = 1, page_size: int = 100, timeout: float = 10) -> Dict:
    r = session.get(f'{M_API}/stocks/high52week/{market}',
                    params={'page': page, 'pageSize': page_size}, timeout=timeout)
    r.raise_for_status()
    return parse_high52(r.json(), market)


def fetch_market_list(session, market: str, page: int = 1, page_size: int = 100, timeout: float = 10) -> Dict:
    """
    시총순 전 종목 시세. 신고가 목록과 응답 모양이 같다.
    closePrice 는 네이버 통합 시세라 장 마감 뒤에도 넥스트레이드 시간외 거래(~20:00)를 따라 움직인다.
    등락률은 KRX 전일 종가 대비. KRX 정규장 종가 자체는 이 응답에 없다.
    """
    r = session.get(f'{M_API}/stocks/marketValue/{market}',
                    params={'page': page, 'pageSize': page_size}, timeout=timeout)
    r.raise_for_status()
    return parse_high52(r.json(), market)


# ------------------------------------------------------------
# 지수 (홈 탭)
# ------------------------------------------------------------

def parse_index(integration: Dict, prices: List[Dict], code: str) -> List[Dict]:
    """
    지수 일별 종가(prices, 최신순) + 최근 거래일의 투자자별 순매수(억원)·프로그램 순매수·상승/하락 종목 수.
    순매수 등은 dealTrendInfo 의 날짜 행에만 붙고, 나머지 날은 None 이다.
    """
    if not isinstance(prices, list) or 'dealTrendInfo' not in integration:
        raise ValueError('지수 응답 형식 변경')
    rows = {}
    for p in prices:
        d = _date(p['localTradedAt'])
        rows[d] = {'date': d, 'code': code, 'close': to_num(p.get('closePrice')),
                   'change_pct': to_num(p.get('fluctuationsRatio')),
                   'frgn': None, 'org': None, 'ind': None, 'prog': None,
                   'up': None, 'down': None, 'flat': None}
    deal = integration.get('dealTrendInfo') or {}
    d = _date(deal.get('bizdate', ''))
    if d in rows:
        ud = integration.get('upDownStockInfo') or {}
        cnt = lambda *ks: sum(int(to_num(ud.get(k)) or 0) for k in ks) if ud else None
        rows[d].update({
            'frgn': to_num(deal.get('foreignValue')),
            'org': to_num(deal.get('institutionalValue')),
            'ind': to_num(deal.get('personalValue')),
            'prog': to_num((integration.get('programTrendInfo') or {}).get('indexTotalReal')),
            'up': cnt('upperCount', 'riseCount'), 'down': cnt('lowerCount', 'fallCount'), 'flat': cnt('steadyCount'),
        })
    return sorted(rows.values(), key=lambda r: r['date'])


FCHART = 'https://fchart.stock.naver.com/sise.nhn'
CHART_API = 'https://api.stock.naver.com/chart/domestic'


def parse_fchart(text: str, code: str) -> List[Dict]:
    """<item data="20261029|시가|고가|저가|종가|거래량" /> → 일봉 행 (날짜순)"""
    out = []
    for m in re.finditer(r'<item data="([^"]+)"', text):
        f = m.group(1).split('|')
        if len(f) < 6:
            continue
        o, h, l, c, v = (to_num(x) for x in f[1:6])
        if c:
            out.append({'date': _date(f[0]), 'code': code, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v})
    if not out:
        raise ValueError('fchart 일봉 없음')
    return out


def fetch_index_ohlc(session, code: str, count: int = 260, timeout: float = 10) -> List[Dict]:
    r = session.get(FCHART, params={'symbol': code, 'timeframe': 'day', 'count': count, 'requestType': 0},
                    timeout=timeout)
    r.raise_for_status()
    return parse_fchart(r.content.decode('euc-kr', 'replace'), code)


def parse_minute(rows: List[Dict], day: str) -> List[Dict]:
    """1분봉 → [{'t': 'HH:MM', 'price': …}] (day 의 것만)"""
    if not isinstance(rows, list):
        raise ValueError('분봉 응답 형식 변경')
    key = day.replace('-', '')
    return [{'t': f"{r['localDateTime'][8:10]}:{r['localDateTime'][10:12]}", 'price': r['currentPrice']}
            for r in rows if str(r.get('localDateTime', '')).startswith(key) and r.get('currentPrice')]


def fetch_index_minute(session, code: str, day: str, timeout: float = 10) -> List[Dict]:
    """day: YYYY-MM-DD"""
    k = day.replace('-', '')
    r = session.get(f'{CHART_API}/index/{code}/minute',
                    params={'startDateTime': f'{k}0900', 'endDateTime': f'{k}1545'}, timeout=timeout)   # 선물은 15:45 마감
    r.raise_for_status()
    return parse_minute(r.json(), day)


def fetch_index(session, code: str, days: int = 60, timeout: float = 10) -> List[Dict]:
    """code: KOSPI | KOSDAQ | FUT(코스피200 선물 최근월물. 프로그램·등락 종목 수는 없음)"""
    r1 = session.get(f'{M_API}/index/{code}/integration', timeout=timeout)
    r1.raise_for_status()
    r2 = session.get(f'{M_API}/index/{code}/price', params={'page': 1, 'pageSize': days}, timeout=timeout)
    r2.raise_for_status()
    return parse_index(r1.json(), r2.json(), code)
