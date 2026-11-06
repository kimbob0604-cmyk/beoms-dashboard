"""
퀀트 탭 JSON: public/data/factors.json — 종목별 팩터 원값 (점수는 화면에서 가중치로 계산)

팩터 (모두 '높을수록 좋음'으로 쓰되 vol 만 낮을수록 좋음)
- rev1, rev3  내년 영업이익 추정치 1개월·3개월 변화율 (FnGuide 컨센서스, 이익 성장 JSON)
- grow        내년 영업이익 증가율 (흑자전환은 큰 값으로)
- ey          내년 영업이익 ÷ 시총 (이익수익률, POR 의 역수)
- mom         12-1개월 모멘텀: 1개월 전 종가 ÷ 12개월 전 종가 − 1 (최근 1개월 단기 반전 제외)
- flow        외국인+기관 20일 순매수 ÷ 시총 (%)
- vol         60거래일 일간 수익률 표준편차 × √250 (연율, %)
- shr         최근 90일 자사주 취득·신탁 + 이미 가진 자사주 소각 공시 금액 ÷ 시총 (%) (자회사 공시 제외)

미래 정보가 섞이지 않게 모든 값은 빌드 시점까지 공개된 데이터로만 만든다.
상장폐지 종목은 목록에 없으므로(생존 편향) 과거 성과 비교에는 쓰지 않는다.

  python3 build_factors.py      # build_growth·build_naver·build_dart 뒤
"""

import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta

import db
from build_home import latest_json
from build_naver import DATA, market_info, public, write_json

MIN_MCAP = 300          # 억원
TURNAROUND = 9.99       # 흑자전환 성장률 자리값 (상위로 가게)
FACTORS = ['rev1', 'rev3', 'grow', 'ey', 'mom', 'flow', 'vol', 'shr']
SHR_DAYS = 90


def price_factors(conn, codes):
    """{code: {'mom': .., 'vol': ..}} — ohlc_daily 종가로"""
    closes = defaultdict(list)
    for code, c in conn.execute('SELECT code, close FROM ohlc_daily WHERE close IS NOT NULL ORDER BY code, date'):
        if code in codes:
            closes[code].append(c)
    out = {}
    for code, xs in closes.items():
        f = {}
        if len(xs) >= 253 and xs[-253] > 0:
            f['mom'] = round((xs[-22] / xs[-253] - 1) * 100, 1)
        if len(xs) >= 61:
            rets = [math.log(b / a) for a, b in zip(xs[-61:-1], xs[-60:]) if a > 0 and b > 0]
            if len(rets) >= 40:
                m = sum(rets) / len(rets)
                f['vol'] = round(math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(250) * 100, 1)
        out[code] = f
    return out


def shareholder_return(conn, since):
    """{code: 억원} 최근 자사주 취득·신탁 금액 + 이미 가진 자사주 소각 금액.
    - 자회사의 주요경영사항(모회사가 대신 낸 공시)은 뺀다
    - '장내매수해서 소각'은 같은 돈의 취득 공시와 겹치므로 소각 쪽은 빼고 취득만 센다
    - 정정 공시는 같은 회사·종류·금액이면 한 번만"""
    seen, out = set(), defaultdict(float)
    for r in conn.execute("SELECT code, kind, title, data FROM dart_filing WHERE kind IN ('buyback', 'trust', 'cancel') "
                          "AND date >= ? AND data IS NOT NULL", (since,)):
        if '자회사' in (r['title'] or ''):
            continue
        d = json.loads(r['data']) or {}
        amt = d.get('amt')
        if not amt or (r['code'], r['kind'], amt) in seen:
            continue
        if r['kind'] == 'cancel' and '기취득' not in (d.get('how') or ''):
            continue
        seen.add((r['code'], r['kind'], amt))
        out[r['code']] += amt / 1e8
    return out


def consensus_factors(growth):
    out = {}
    for s in (growth or {}).get('stocks', []):
        op = ((s.get('k') or {}).get('y0') or {}).get('op') or {}
        f = {}
        if op.get('m1') is not None:
            f['rev1'] = round(op['m1'] * 100, 2)
        if op.get('m3') is not None:
            f['rev3'] = round(op['m3'] * 100, 2)
        if op.get('k') == 'turnaround':
            f['grow'] = TURNAROUND * 100
        elif op.get('g') is not None:
            f['grow'] = round(op['g'] * 100, 1)
        if op.get('n') is not None and s.get('mc'):
            f['ey'] = round(op['n'] / s['mc'] * 100, 2)
        out[s['c']] = f
    return out


def build(conn):
    d = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    info, _ = market_info(conn, d)
    info = {c: public(i) for c, i in info.items() if i.get('mc') and i['mc'] >= MIN_MCAP and i.get('p')}
    growth, flow = latest_json('growth'), latest_json('flow')
    cns = consensus_factors(growth)
    fl = {s['c']: s for s in (flow or {}).get('stocks', [])}
    px = price_factors(conn, set(info))
    shr = shareholder_return(conn, (date.fromisoformat(d) - timedelta(days=SHR_DAYS)).isoformat())
    rows = []
    for c, i in sorted(info.items(), key=lambda kv: -kv[1]['mc']):
        f = {**cns.get(c, {}), **px.get(c, {})}
        s = fl.get(c)
        if s and s.get('f20') is not None and s.get('o20') is not None:
            f['flow'] = round((s['f20'] + s['o20']) / i['mc'] * 100, 3)
        f['shr'] = round(shr.get(c, 0) / i['mc'] * 100, 2)
        rows.append([c, i['n'], i['mk'], i.get('w'), i['mc'], i['p'], i['ch']] + [f.get(k) for k in FACTORS])
    return {'date': d, 'built': datetime.now().isoformat(timespec='seconds'),
            'cns': growth and growth.get('cns_date'), 'flow': flow and flow.get('date'),
            'fy': growth and growth['fy0'] + 1, 'f': FACTORS, 'rows': rows}


def main():
    data = build(db.connect())
    write_json(DATA / 'factors.json', data)
    have = {k: sum(r[7 + j] is not None for r in data['rows']) for j, k in enumerate(FACTORS)}
    print(f"factors.json: {len(data['rows'])}종목 · 값 있는 종목 {have}")


if __name__ == '__main__':
    main()
