"""
한국거래소 KIND 공시 검색 — 공시 시각(시:분)

DART 목록 API 는 접수 날짜만 주고 시각을 주지 않는다. 네이버 종목 공시 목록의 시각은 다음 날 아침 일괄 시각(06:50)이라 쓸 수 없다.
KIND 상세검색(details.do)은 공시마다 '2026-11-05 17:59' 같은 시각을 준다.
KIND 접수번호는 DART 접수번호와 달라서, 종목코드·날짜·공시 종류로 DART 이벤트와 맞춘다.
KIND 회사코드는 종목코드 앞 5자리('03310' → 033100).
"""

import html
import re
from typing import Dict, List

URL = 'https://kind.krx.co.kr/disclosure/details.do'

ROW = re.compile(
    r'<td class="txc">(\d{4}-\d{2}-\d{2} \d{2}:\d{2})</td>.*?companysummary_open\(\'(\w+)\'\).*?title=\'([^\']*)\'.*?'
    r'openDisclsViewer\(\'(\d+)\'[^)]*\)" title=\'([^\']*)\'', re.S)
TOTAL = re.compile(r'<em>([\d,]+)</em>')


def parse(page: str) -> Dict:
    rows = [{'dt': dt, 'code': kc + '0' if len(kc) == 5 else kc, 'name': html.unescape(nm).strip(),
             'acpt': acpt, 'title': html.unescape(t).strip()}
            for dt, kc, nm, acpt, t in ROW.findall(page)]
    m = TOTAL.search(page)
    return {'total': int(m.group(1).replace(',', '')) if m else len(rows), 'rows': rows}


def search(session, report_nm: str, from_date: str, to_date: str, page: int = 1, size: int = 100,
           timeout: float = 30) -> Dict:
    """report_nm: 공시 제목 일부 ('' 이면 전체). 날짜는 YYYY-MM-DD. 최신순."""
    data = {'method': 'searchDetailsSub', 'currentPageSize': size, 'pageIndex': page, 'orderMode': 1,
            'orderStat': 'D', 'forward': 'details_sub', 'reportNm': report_nm, 'fromDate': from_date,
            'toDate': to_date, 'bfrDsclsType': 'on', 'marketType': '', 'searchCodeType': '', 'repIsuSrtCd': '',
            'searchCorpName': ''}
    r = session.post(URL, data=data, timeout=timeout)
    r.raise_for_status()
    return parse(r.content.decode('utf-8', 'replace'))
