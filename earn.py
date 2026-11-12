"""
실적 발표 덱: @darthacking 글 파싱 · 서프/미스 판정 · 발표 시각 기준 주가 반응 (순수 함수 — 네트워크·DB 없음)

collect_earn.py 가 글과 분봉을 받아 db/earn.db 에 넣고, build_earn.py 가 여기 함수로 판정·계산한다.
"""

import re
from bisect import bisect_left, bisect_right
from datetime import datetime
from typing import Dict, List, Optional, Sequence

SALES_T = 0.05      # 매출: 예상치 대비 ±5% 넘으면 서프·미스
OP_T = 0.10         # 영업이익: ±10% (적자 예상→흑자는 서프, 흑자 예상→적자는 미스)
PRE_END = '09:00'   # 이 전이면 장전
IN_END = '15:20'    # 이 뒤면 장후 (15:20~15:30 은 종가 단일가 — 사실상 다음 반응이 시간외·다음 날)

# 덱 묶음 (화면 열 순서)
CASES = [('both', '동반 서프'), ('op', '영업이익 서프'), ('sales', '매출 서프'), ('miss', '영업이익 미스'), ('inline', '부합')]

_KEYS = {'매출액': 's', '매출': 's', '영업익': 'o', '영업이익': 'o', '순이익': 'n', '순익': 'n'}
_AMT = r'-?\s*(?:[\d,]+\s*조\s*)?[\d,]*\s*억|-?\s*[\d,]+\s*조'
_ROW = re.compile(rf'^\s*(매출액|매출|영업익|영업이익|순이익|순익)\s*:\s*({_AMT})\s*\(\s*예상치\s*:\s*(-|{_AMT})', re.M)
_TS = re.compile(r'^\s*(\d{4})\.?(\d{2})\.?(\d{2})\s+(\d{2}):(\d{2}):(\d{2})')
_CORP = re.compile(r'기업명\s*:\s*(.+?)\s*\(\s*시가총액\s*:\s*([^)]*)\)\s*(?:A([0-9A-Z]{6}))?')
_REPORT = re.compile(r'보고서명\s*:\s*(.+)')
_PRELIM = re.compile(r'잠정실적\s*:\s*([YN])')
_CODE_LINK = re.compile(r'code=([0-9A-Z]{6})|disclosure/([0-9A-Z]{6})')
_RCP = re.compile(r'rcpNo=(\d{14})')
_PERIOD = re.compile(r'^\s*(\d{4})\.(\d)Q\b', re.M)


def amount(s: str) -> Optional[float]:
    """'4조 9,653억' → 49653, '-42억' → -42, '-' → None (억원)"""
    s = (s or '').replace(' ', '').replace(',', '')
    if not s or s == '-':
        return None
    neg = s.startswith('-')
    s = s.lstrip('-')
    m = re.fullmatch(r'(?:(\d+)조)?(\d*)억?', s)
    if not m or not (m.group(1) or m.group(2)):
        return None
    v = int(m.group(1) or 0) * 10000 + int(m.group(2) or 0)
    return float(-v if neg else v)


def parse_post(text: str, posted: Optional[datetime] = None) -> Optional[Dict]:
    """채널 글 하나 → {ts, name, mcap, code, report, prelim, period, rcp, s, se, o, oe, n, ne} (실적 글이 아니면 None).
    예상치가 '-' 또는 '0억'(예전 형식)이면 그 항목의 예상치는 None. 실제치가 0억이면서 세 항목이 다 0이면(채널 오류) None."""
    if not text or '예상치' not in text:
        return None
    rows = {}
    for k, a, e in _ROW.findall(text):
        key = _KEYS[k]
        if key in rows:
            continue
        ev = amount(e)
        rows[key] = (amount(a), ev if ev else None)
    if 's' not in rows and 'o' not in rows:
        return None
    if all((rows.get(k) or (0,))[0] in (0, None) for k in ('s', 'o', 'n')):
        return None
    m = _TS.match(text)
    if m:
        ts = '{}-{}-{} {}:{}:{}'.format(*m.groups())
    elif posted:
        ts = posted.strftime('%Y-%m-%d %H:%M:%S')
    else:
        return None
    c = _CORP.search(text)
    code = c.group(3) if c and c.group(3) else None
    if not code:
        lm = _CODE_LINK.search(text)
        code = (lm.group(1) or lm.group(2)) if lm else None
    rep = _REPORT.search(text)
    pre = _PRELIM.search(text)
    rcp = _RCP.search(text)
    per = _PERIOD.search(text)
    out = {'ts': ts, 'name': c.group(1).strip() if c else None, 'mcap': amount(c.group(2)) if c else None, 'code': code,
           'report': re.sub(r'\s+', ' ', rep.group(1)).strip() if rep else '', 'prelim': pre.group(1) if pre else None,
           'period': f'{per.group(1)}Q{per.group(2)}' if per else None, 'rcp': rcp.group(1) if rcp else None}
    for k in ('s', 'o', 'n'):
        a, e = rows.get(k, (None, None))
        out[k], out[k + 'e'] = a, e
    return out


def first_release(p: Dict) -> Optional[bool]:
    """그 분기 실적의 첫 발표인가. True/False, 예전 형식 정기보고서처럼 글만으로 모르면 None"""
    rep = p.get('report') or ''
    if '정정' in rep or '[기재' in rep:
        return False
    if '잠정' in rep:
        return True
    if re.match(r'(분기|반기|사업)보고서', rep):
        return {'N': True, 'Y': False}.get(p.get('prelim'))
    return False


def ratio(a, e) -> Optional[float]:
    if a is None or e is None or e == 0:
        return None
    return (a - e) / abs(e)


def tag(a, e, t) -> Optional[str]:
    """'beat' | 'miss' | 'inline' | None(예상치 없음). 부호가 바뀌면 크기와 상관없이"""
    if a is None or e is None:
        return None
    if e < 0 <= a and a != 0:
        return 'beat'
    if e > 0 > a:
        return 'miss'
    r = ratio(a, e)
    if r is None:
        return None
    return 'beat' if r >= t else 'miss' if r <= -t else 'inline'


def case_of(st: Optional[str], ot: Optional[str]) -> Optional[str]:
    """덱 묶음 (CASES). 영업이익 예상치가 없으면 매출로만"""
    if st is None and ot is None:
        return None
    if st == 'beat' and ot == 'beat':
        return 'both'
    if ot == 'beat':
        return 'op'
    if ot == 'miss':
        return 'miss'
    if st == 'beat':
        return 'sales'
    return 'inline'


def session(ts: str) -> str:
    hm = ts[11:16]
    return '장전' if hm < PRE_END else '장중' if hm < IN_END else '장후'


def reaction_day(ts: str, days: Sequence[str]) -> tuple:
    """(반응 거래일, 시간대). 휴장일 발표는 다음 거래일 장전. 장후는 다음 거래일. days = 정렬된 거래일 목록"""
    d, ss = ts[:10], session(ts)
    i = bisect_left(days, d)
    if i >= len(days):
        return None, ss
    if days[i] != d:                 # 주말·휴장일
        return days[i], '장전'
    if ss == '장후':
        return (days[i + 1] if i + 1 < len(days) else None), ss
    return d, ss


# ---------------- 분봉 ----------------
# 하루 분봉 = [[ 'HHMM', 종가, 거래량 ], …] 시각순 (통합 기준: 08:00~20:00, 넥스트레이드 없는 종목은 09:00~15:30)

def to_min(hm: str) -> int:
    return int(hm[:2]) * 60 + int(hm[2:4])


def price_at(bars: List, hm: str, before: bool = True) -> Optional[float]:
    """hm(HHMM) 이전(포함) 마지막 체결가. before=False 면 hm 이후 첫 체결가"""
    if not bars:
        return None
    keys = [b[0] for b in bars]
    if before:
        i = bisect_right(keys, hm) - 1
        return bars[i][1] if i >= 0 else None
    i = bisect_left(keys, hm)
    return bars[i][1] if i < len(bars) else None


def regular(bars: List) -> List:
    """정규장(09:00~15:30) 분봉"""
    return [b for b in bars if '0900' <= b[0] <= '1530']


def add_min(hm: str, k: int) -> str:
    m = to_min(hm) + k
    return f'{m // 60:02d}{m % 60:02d}'


def ret(p, base) -> Optional[float]:
    return None if p is None or not base else p / base - 1


def minute_reaction(ts: str, ss: str, day0: List, day1: List, prev_close: Optional[float]) -> Dict:
    """분봉 반응. day0 = 발표일 분봉, day1 = 장후 발표의 다음 거래일 분봉(장전·장중이면 빈 목록),
    prev_close = 장전 발표의 전 거래일 정규장 종가.
    기준가: 장중 = 발표 직전 체결가, 장후 = 그날 정규장 종가, 장전 = 전날 종가.
    반환 {base, m5, m30, m60, close(반응일 정규장 종가), nxt(장후: 넥스트레이드 20:00 무렵 마지막), open(반응일 시가)}"""
    hm = ts[11:13] + ts[14:16]
    out = {}
    if ss == '장중':
        base = price_at(day0, add_min(hm, -1)) or price_at(regular(day0), '0900', before=False)
        react = day0
        for k in (5, 30, 60):
            t = add_min(hm, k)
            out[f'm{k}'] = ret(price_at(react, t), base) if t <= '1530' else None
        out['close'] = ret(price_at(regular(day0), '1530'), base)
        out['open'] = None
    elif ss == '장후':
        base = price_at(regular(day0), '1530')
        after = [b for b in day0 if b[0] > '1530']
        for k in (5, 30, 60):
            t = add_min(hm, k)
            out[f'm{k}'] = ret(price_at(after, t), base) if after and after[0][0] <= t else None
        out['nxt'] = ret(after[-1][1], base) if after else None
        r1 = regular(day1)
        out['open'] = ret(r1[0][1] if r1 else None, base)
        out['close'] = ret(price_at(r1, '1530'), base)
    else:   # 장전: 넥스트레이드 프리마켓(08:00~08:50) 이 있으면 거기서 먼저 반응
        base = prev_close
        r0 = regular(day0)
        out['m5'] = out['m60'] = None
        pre = [b for b in day0 if b[0] < '0900']
        out['nxt'] = ret(pre[-1][1], base) if pre else None
        out['open'] = ret(r0[0][1] if r0 else None, base)
        out['m30'] = ret(price_at(r0, '0930'), base)
        out['close'] = ret(price_at(r0, '1530'), base)
    out['base'] = base
    return out


def path(ts: str, bars: List, lo: int = -30, hi: int = 120, step: int = 5) -> List[Optional[float]]:
    """장중 발표: 발표 −30~+120분을 step 분 간격으로, 발표 직전 체결가 대비 수익률. 정규장 밖은 None"""
    hm = ts[11:13] + ts[14:16]
    reg = regular(bars)
    base = price_at(reg, add_min(hm, -1))
    out = []
    for k in range(lo, hi + 1, step):
        t = add_min(hm, k)
        out.append(round(ret(price_at(reg, t), base) * 100, 2) if base and '0900' <= t <= '1530' and price_at(reg, t) else None)
    return out


def active(bars: List) -> List:
    """앞뒤로 거래가 없는 분(시간외 빈 시간 등)을 잘라낸다"""
    idx = [i for i, b in enumerate(bars) if len(b) > 2 and b[2]]
    return bars[idx[0]:idx[-1] + 1] if idx else bars


def sample(bars: List, every: int = 5) -> List:
    """카드 미니 차트용: every 분마다 마지막 체결가 [[HHMM, 종가]…]"""
    out, last = [], None
    for hm, c, *_ in bars:
        slot = to_min(hm) // every
        if slot != last:
            out.append([hm, c])
            last = slot
        else:
            out[-1] = [hm, c]
    return out


# ---------------- 일봉 ----------------

def daily_reaction(adj: Dict[str, float], opens: Dict[str, float], closes: Dict[str, float], idx: Dict[str, float],
                   days: Sequence[str], d0: str) -> Dict:
    """반응일 d0 기준 일봉 반응 (전 거래일 종가 = 0). adj = 수정 종가, opens/closes = 그날 원 시가·종가(갭 계산), idx = 지수 종가.
    {gap, d0, d1, d5, d20} 와 초과수익 {x0, x1, x5, x20} (같은 시장 지수 차감). 없는 칸은 None"""
    i = bisect_left(days, d0)
    if i >= len(days) or days[i] != d0 or i == 0:
        return {}
    pb = days[i - 1]
    out = {'gap': ret(opens.get(d0), closes.get(pb))}
    for k, n in (('d0', 0), ('d1', 1), ('d5', 5), ('d20', 20)):
        j = i + n
        if j >= len(days):
            out[k] = out['x' + k[1:]] = None
            continue
        r = ret(adj.get(days[j]), adj.get(pb))
        m = ret(idx.get(days[j]), idx.get(pb))
        out[k] = r
        out['x' + k[1:]] = None if r is None or m is None else r - m
    return out


def summarize(xs: List[Optional[float]]) -> Optional[Dict]:
    """{n, avg, med, up(오른 비율)} — 위아래 1% 를 잘라낸 평균 대신 극단값 ±50% 로 자른 평균"""
    v = sorted(max(-0.5, min(0.5, x)) for x in xs if x is not None)
    if not v:
        return None
    n = len(v)
    med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    return {'n': n, 'avg': round(sum(v) / n * 100, 2), 'med': round(med * 100, 2), 'up': round(sum(1 for x in v if x > 0) / n * 100)}
