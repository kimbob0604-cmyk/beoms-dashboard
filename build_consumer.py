"""
소비재 탭 데이터: 관세청 수출 통계(db/trade.db) + 종목 설정(consumer_assets.json) → public/data/consumer.json

- 업황: 품목 묶음(consumer_hs.json)별 전국 월 수출(금액·중량 → 단가), 전년 대비, 국가별, 수출 상위 시군구
- 종목: 밸류체인 단계, 시총·POR, 수출 흐름(시군구×품목 또는 전국 묶음)의 월 시리즈,
        분기 수출(원화 환산)과 분기 매출의 전년비 상관(r)·수출이 설명하는 매출 비중, 수출로 본 분기 매출 추정(프리뷰)
- 급등 탐색: 시군구×HS6 의 3개월 수출이 크게 뛴 곳
- 컨콜: DART 기업설명회(IR) 공시(consumer.json) + 텔레그램 컨콜 노트(consumer_calls.json — 방의 글 원문이라 공개 배포에서 뺀다)

환율은 월평균 원/달러(yfinance KRW=X, trade.db fx 표에 넣어 둔다). 분기 매출은 history.db fin(DART), 분기 컨센서스는 cns_quarter.

  python3 build_consumer.py
"""

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import consumer as K
import db
import visits as V
from build_naver import growth_extract, market_info, por_base
from collect_trade import DB as TRADE_DB, HS_FILE, connect as trade_connect

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'public' / 'data'
OUT, OUT_CALLS = DATA / 'consumer.json', DATA / 'consumer_calls.json'
ASSETS = ROOT / 'consumer_assets.json'
HISTORY_DB = ROOT / 'db' / 'history.db'
CONCALL_DB = ROOT / 'db' / 'concall.db'
COUNTRY = {'US': '미국', 'CN': '중국', 'JP': '일본', 'HK': '홍콩', 'VN': '베트남', 'TW': '대만', 'TH': '태국', 'SG': '싱가포르',
           'MY': '말레이시아', 'ID': '인도네시아', 'PH': '필리핀', 'RU': '러시아', 'AE': 'UAE', 'SA': '사우디', 'GB': '영국',
           'DE': '독일', 'FR': '프랑스', 'NL': '네덜란드', 'PL': '폴란드', 'AU': '호주', 'CA': '캐나다', 'MX': '멕시코',
           'IN': '인도', 'KZ': '카자흐스탄', 'TR': '튀르키예', 'ES': '스페인', 'IT': '이탈리아', 'BR': '브라질'}
CALL_WORDS = ('컨콜', '컨퍼런스콜', '컨퍼런스 콜', '콘퍼런스콜', '콘퍼런스 콜', '어닝콜', '어닝스콜', '실적발표회',
              'Conference Call', 'conference call', 'Earnings Call', 'earnings call')
TOP_COUNTRIES, TOP_SGG, SURGE_MIN_USD, SURGE_MIN_YOY, MAX_CALLS = 8, 8, 2_000_000, 0.5, 8
HEAT = ['US', 'CN', 'JP', 'HK', 'VN', 'TW', 'RU', 'AE', 'EU']          # 품목×국가 표의 열. EU 는 아래 나라들의 합
EU = ('DE', 'FR', 'NL', 'PL', 'ES', 'IT')
SCAN_TOP = 2          # 묶음마다 보여 줄 자동 탐색 후보 수


# ------------------------------------------------------------
# 환율 (월평균 원/달러)
# ------------------------------------------------------------

def fx_rates(tconn, ms: list) -> dict:
    """{ym: 원/달러}. 없는 달만 yfinance 로 받아 trade.db 에 넣는다. 못 받으면 가까운 달 값으로 채운다"""
    tconn.execute('CREATE TABLE IF NOT EXISTS fx (ym TEXT PRIMARY KEY, krw REAL)')
    have = dict(tconn.execute('SELECT ym, krw FROM fx'))
    this = date.today().strftime('%Y-%m')
    if any(m not in have for m in ms) or this in ms:
        try:
            import yfinance as yf
            h = yf.Ticker('KRW=X').history(start=f'{ms[0]}-01', interval='1d')['Close']
            by = defaultdict(list)
            for ts, v in h.items():
                if v == v:
                    by[ts.strftime('%Y-%m')].append(float(v))
            for ym, vs in by.items():
                if ym != this:                   # 이번 달은 아직 평균이 아니다
                    have[ym] = sum(vs) / len(vs)
                    tconn.execute('INSERT OR REPLACE INTO fx VALUES (?,?)', (ym, have[ym]))
            tconn.commit()
        except Exception as e:                   # 네트워크·형식 문제 — 있는 값으로 간다
            print('환율 받기 실패:', type(e).__name__, str(e)[:80])
    out, last = {}, None
    for m in ms:
        last = have.get(m, last)
        out[m] = last
    first = next((v for v in out.values() if v), 1350.0)
    return {m: (v or first) for m, v in out.items()}


# ------------------------------------------------------------
# 수출 시리즈
# ------------------------------------------------------------

class Trade:
    def __init__(self, tconn, hs: dict):
        self.c = tconn
        self.hs = hs
        self.groups = {g['id']: g for g in hs['groups']}
        last = tconn.execute('SELECT MAX(ym) FROM item').fetchone()[0]
        self.months = K.months(f"{hs['start_year']}-01", last) if last else []
        self.pos = {m: i for i, m in enumerate(self.months)}
        self._sgg = {}
        self._sgg_months = None
        self._greg = {}

    def _blank(self):
        return [None] * len(self.months)

    def _hs_where(self, g, col='hs'):
        """묶음의 전국 품목 조건. hs10 이 있으면 그것만(미용기기), 없으면 hs6 앞자리"""
        if g.get('hs10'):
            return f"{col} IN ({','.join('?' * len(g['hs10']))})", list(g['hs10'])
        return '(' + ' OR '.join(f'{col} LIKE ?' for _ in g['hs6']) + ')', [h + '%' for h in g['hs6']]

    def national(self, gid: str):
        """(월 금액, 월 중량) 달러·kg"""
        w, args = self._hs_where(self.groups[gid])
        usd, kg = self._blank(), self._blank()
        for ym, u, k in self.c.execute(f'SELECT ym, SUM(usd), SUM(kg) FROM item WHERE {w} GROUP BY ym', args):
            if ym in self.pos:
                usd[self.pos[ym]], kg[self.pos[ym]] = u, k
        return usd, kg

    def items(self, gid: str, n=6):
        """최근 12개월 수출이 큰 세부 품목 [(hs10, 이름, 12개월 합)]"""
        w, args = self._hs_where(self.groups[gid])
        since = self.months[-12] if len(self.months) >= 12 else self.months[0]
        return [(h, nm, u) for h, nm, u in self.c.execute(
            f'SELECT hs, MAX(name), SUM(usd) FROM item WHERE {w} AND ym >= ? GROUP BY hs ORDER BY 3 DESC LIMIT ?', args + [since, n])]

    def countries(self, gid: str):
        """{국가: 월 금액}. 국가별 통계는 HS6 줄(또는 hs10 지정 묶음은 그 HS10)"""
        g = self.groups[gid]
        keys = g.get('hs10') or g['hs6']
        out = {}
        for ym, c, u in self.c.execute(
                f"SELECT ym, country, SUM(usd) FROM item_country WHERE hs IN ({','.join('?' * len(keys))}) GROUP BY ym, country", keys):
            if ym in self.pos:
                out.setdefault(c, self._blank())[self.pos[ym]] = u
        return out

    def sgg_rows(self, hs6: str):
        """{(시도, 시군구): 월 금액} — HS6 하나"""
        if hs6 not in self._sgg:
            d = {}
            for ym, sido, sgg, u in self.c.execute('SELECT ym, sido, sgg, usd FROM sgg WHERE hs6 = ?', (hs6,)):
                if ym in self.pos and u is not None:
                    d.setdefault((sido, sgg), self._blank())[self.pos[ym]] = u
            self._sgg[hs6] = d
        return self._sgg[hs6]

    def sgg_months(self) -> set:
        """시군구 통계가 들어온 달 (백필이 덜 됐으면 일부만)"""
        if self._sgg_months is None:
            self._sgg_months = {r[0] for r in self.c.execute('SELECT DISTINCT ym FROM sgg')}
        return self._sgg_months

    def group_regions(self, gid: str) -> dict:
        """{(시도, 시군구): 그 묶음의 월 금액} — 지역 자동 탐색용 (한 번 계산해 둔다)"""
        if gid not in self._greg:
            have = self.sgg_months()
            out = {}
            for hs6 in self.groups[gid]['hs6']:
                for key, v in self.sgg_rows(hs6).items():
                    acc = out.setdefault(key, [0.0 if m in have else None for m in self.months])
                    for i, x in enumerate(v):
                        if x is not None and acc[i] is not None:
                            acc[i] += x
            self._greg[gid] = out
        return self._greg[gid]

    def regional(self, gid: str, regions: list):
        """그 지역들의 묶음 수출 월 금액. 시군구 통계가 없는 달은 None, 있는데 그 지역 값이 없으면 0"""
        have = self.sgg_months()
        out = [0.0 if m in have else None for m in self.months]
        hit = False
        for hs6 in self.groups[gid]['hs6']:
            for (sido, sgg), v in self.sgg_rows(hs6).items():
                if K.region_match(sido, sgg, regions):
                    hit = True
                    for i, x in enumerate(v):
                        if x is not None and out[i] is not None:
                            out[i] += x
        return out if hit else None


def tail(v, n):
    return [None if x is None else round(x) for x in v[-n:]]


def group_cards(t: Trade) -> list:
    out = []
    for g in t.hs['groups']:
        if g.get('sgg_only'):          # 전국 합이 의미 없는 묶음(지역 흐름에만 쓴다)
            continue
        usd, kg = t.national(g['id'])
        price = [u / k if u and k else None for u, k in zip(usd, kg)]
        cs = t.countries(g['id'])
        last12 = lambda v: sum(x or 0 for x in v[-12:])
        total12 = last12(usd)
        top = sorted(cs.items(), key=lambda kv: -last12(kv[1]))[:TOP_COUNTRIES]
        sggs = defaultdict(lambda: [None] * len(t.months))
        for hs6 in g['hs6']:
            for (sido, name), v in t.sgg_rows(hs6).items():
                acc = sggs[(sido, name)]
                for i, x in enumerate(v):
                    if x is not None:
                        acc[i] = (acc[i] or 0) + x
        top_sgg = sorted(sggs.items(), key=lambda kv: -last12(kv[1]))[:TOP_SGG]
        out.append({
            'id': g['id'], 'sector': g['sector'], 'label': g['label'], 'note': g.get('note'), 'mixed': bool(g.get('mixed')),
            'hs6': g['hs6'], 'usd': tail(usd, len(usd)), 'yoy': K.yoy(usd), 'yoy3': K.yoy(usd, span=3),
            'price_yoy3': K.yoy([p for p in price], span=3) if all(p is not None for p in price[-15:]) else None,
            'kg_yoy3': K.yoy(kg, span=3), 'usd12': round(total12),
            'items': [{'hs': h, 'n': nm, 'usd12': round(u or 0)} for h, nm, u in t.items(g['id'])],
            'countries': [{'c': c, 'n': COUNTRY.get(c, c), 'usd': tail(v, 36), 'usd12': round(last12(v)),
                           'share': last12(v) / total12 if total12 else None, 'yoy3': K.yoy(v, span=3)} for c, v in top],
            'sgg': [{'sido': k[0], 'n': k[1], 'usd12': round(last12(v)), 'yoy3': K.yoy(v, span=3)} for k, v in top_sgg if last12(v) > 0],
            'heat': heat_row(cs, total12, len(t.months)),
        })
    return out


def heat_row(cs: dict, total12: float, n: int) -> dict:
    """{국가: [3개월 전년비, 최근 12개월 비중]} — 품목×국가 표의 한 줄. EU 는 여섯 나라의 합"""
    eu = [None] * n
    for c in EU:
        for i, x in enumerate(cs.get(c) or []):
            if x is not None:
                eu[i] = (eu[i] or 0) + x
    out = {}
    for c in HEAT:
        v = eu if c == 'EU' else cs.get(c)
        if not v or not any(v):
            continue
        s12 = sum(x or 0 for x in v[-12:])
        out[c] = [K.yoy([x or 0 for x in v], span=3), s12 / total12 if total12 else None]
    return out


# ------------------------------------------------------------
# 종목
# ------------------------------------------------------------

def scan_regions(t: Trade, gid: str, fx: dict, rev_q: dict, skip: list) -> list:
    """그 종목의 분기 매출과 같이 움직이는 수출 지역 후보 (묶음 하나). 이미 흐름으로 잡은 지역(skip)은 뺀다.
    수백 개 지역을 훑으므로 우연히 맞는 곳이 나올 수 있다 → 기준을 더 엄하게(SCAN_R·SCAN_NQ) 보고, 후보로만 보여 준다."""
    if len(rev_q) < K.SCAN_NQ:
        return []
    last4 = sorted(rev_q)[-4:]
    rev4 = sum(rev_q[q] for q in last4)
    out = []
    for (sido, name), usd in t.group_regions(gid).items():
        if K.region_match(sido, name, skip) or rev4 <= 0:
            continue
        rough = sum((u or 0) * fx[m] / 1e8 for u, m in zip(usd[-15:], t.months[-15:])) * 12 / 15     # 대략의 연간 수출(억원)
        if not (K.COVER_MIN * 0.5 <= rough / rev4 <= K.COVER_MAX * 2):                              # 규모가 전혀 안 맞는 지역은 계산도 안 한다
            continue
        st = flow_stats(t, usd, fx, rev_q)
        if K.qualified(st['r'], st['nq'], st['cover']) and st['r'] >= K.SCAN_R and st['nq'] >= K.SCAN_NQ:
            out.append(((sido, name), st))
    return sorted(out, key=lambda x: -x[1]['r'])[:SCAN_TOP]


def returns(conn) -> dict:
    """{code: (1개월, 3개월 수정주가 수익률)} — 시총 변화로 읽는다. 신고가 탭의 가격 행렬을 같이 쓴다"""
    try:
        import build_newhigh as NH
        m = NH.matrix(conn, NH.load_base(conn.execute('SELECT MIN(date) FROM price_daily').fetchone()[0]))
    except Exception as e:            # 과거 가격 DB 가 없을 때
        print('시총 변화 계산 건너뜀:', type(e).__name__)
        return {}
    C, out = m['C'], {}
    for code, i in m['idx'].items():
        row = C[i]
        if row[-1] != row[-1]:
            continue
        r = lambda k: round(float(row[-1] / row[-1 - k] - 1), 4) if len(row) > k and row[-1 - k] == row[-1 - k] and row[-1 - k] > 0 else None
        out[code] = (r(21), r(63))
    return out


def fin_quarters(hconn, code: str, acc: str = 'sales') -> dict:
    """{분기: 매출 또는 영업이익(억)} — 연결(CFS) 우선"""
    rows = defaultdict(list)
    for year, reprt, fs, cur, cur_add in hconn.execute(
            'SELECT year, reprt, fs, cur, cur_add FROM fin WHERE code = ? AND acc = ?', (code, acc)):
        rows[fs].append({'year': year, 'reprt': reprt, 'cur': cur, 'cur_add': cur_add})
    pick = rows.get('CFS') or rows.get('OFS') or []
    return {q: v / 1e8 for q, v in K.single_quarters(pick).items() if v is not None}


def revenue_quarters(hconn, code: str) -> dict:
    return fin_quarters(hconn, code, 'sales')


def margin_4q(rev_q: dict, op_q: dict):
    """최근 4개 분기(매출·영업이익이 둘 다 있는) 합산 영업이익률. 없으면 None"""
    qs = sorted(set(rev_q) & set(op_q))[-4:]
    rev = sum(rev_q[q] for q in qs)
    return sum(op_q[q] for q in qs) / rev if len(qs) == 4 and rev > 0 else None


def flow_stats(t: Trade, usd: list, fx: dict, rev_q: dict) -> dict:
    """흐름 하나의 통계: 전년비, 분기 수출(억원), 매출과의 상관, 수출이 설명하는 매출 비중"""
    krw = [None if u is None else u * fx[m] / 1e8 for u, m in zip(usd, t.months)]
    exp_q = {q: s for q, (s, k) in K.quarter_sums(t.months, krw).items() if k == 3}
    r, n = K.yoy_corr(exp_q, rev_q)
    common = [q for q in sorted(set(exp_q) & set(rev_q))][-4:]
    cover = sum(exp_q[q] for q in common) / sum(rev_q[q] for q in common) if len(common) == 4 and sum(rev_q[q] for q in common) > 0 else None
    return {'usd': tail(usd, len(usd)), 'yoy': K.yoy(usd), 'yoy3': K.yoy(usd, span=3), 'r': r, 'nq': n, 'cover': cover, 'exp_q': exp_q}


def is_qualified(f: dict) -> bool:
    """회사 수출로 확인된 흐름인가. 자동 탐색 후보(scan)는 검수 전이라 확인으로 치지 않는다"""
    return f['kind'] == 'sigungu' and f['basis'] != 'scan' and K.qualified(f['r'], f['nq'], f['cover'])


def pick_main(flows: list) -> dict:
    """대표 흐름: 회사 수출로 확인된 지역 흐름(상관·비중 통과) → 채널 근거 지역 흐름 → 전국 묶음.
    본사 소재지 흐름(hq)은 확인되지 않으면 대표로 쓰지 않는다."""
    good = sorted((f for f in flows if is_qualified(f)), key=lambda f: -f['r'])
    if good:
        return good[0]
    ch = [f for f in flows if f['kind'] == 'sigungu' and f['basis'] == 'channel']
    if ch:
        return ch[0]
    nat = [f for f in flows if f['kind'] == 'national']
    return nat[0] if nat else (flows[0] if flows else None)


def consensus_quarter(conn, code: str, q: str) -> tuple:
    """분기 컨센서스 (매출, 영업이익) 억. cns_quarter 의 period 는 분기 끝 달(YYYYMM). 없으면 (None, None)"""
    period = f'{q[:4]}{int(q[5]) * 3:02d}'
    r = conn.execute('SELECT sales, op FROM cns_quarter WHERE code = ? AND period = ? AND sales IS NOT NULL ORDER BY as_of DESC LIMIT 1',
                     (code, period)).fetchone()
    return (r[0], r[1]) if r else (None, None)


def consensus_sales(conn, code: str, q: str):
    return consensus_quarter(conn, code, q)[0]


def build_stocks(conn, hconn, t: Trade, assets: dict, fx: dict, d: str) -> list:
    info, _ = market_info(conn, d)
    pv, gx = por_base(d), growth_extract(d)
    ret = returns(conn)
    labels = {g['id']: g['label'] for g in t.hs['groups']}
    out = []
    for s in assets['stocks']:
        code = s['code']
        rev_q = revenue_quarters(hconn, code) if hconn is not None else {}
        op_q = fin_quarters(hconn, code, 'op') if hconn is not None else {}
        flows = []
        for f in s['flows']:
            usd = t.regional(f['group'], f['regions']) if f['kind'] == 'sigungu' else t.national(f['group'])[0]
            if usd is None or not any(usd):
                continue
            st = flow_stats(t, usd, fx, rev_q)
            names = [r.split(':')[1] for r in f.get('regions', [])]
            flows.append({'id': f['id'], 'kind': f['kind'], 'group': f['group'], 'basis': f['basis'], 'nature': f['nature'],
                          'label': f"{labels[f['group']]} — {'·'.join(dict.fromkeys(names)) if names else '전국'}", **st})
            flows[-1]['ok'] = is_qualified(flows[-1])
        ch = [f for f in flows if f['kind'] == 'sigungu' and f['basis'] == 'channel']
        if len(ch) > 1:                               # 채널 근거 지역 흐름이 여럿이면 합친 '회사 흐름'도 본다
            usd = [None if any(f['usd'][i] is None for f in ch) else sum(f['usd'][i] for f in ch) for i in range(len(t.months))]
            flows.insert(0, {'id': 'c-all', 'kind': 'sigungu', 'group': ch[0]['group'], 'basis': 'channel', 'nature': 'company',
                             'label': '회사 흐름 합 — ' + ' + '.join(f['label'].split(' — ')[0] for f in ch), **flow_stats(t, usd, fx, rev_q)})
            flows[0]['ok'] = is_qualified(flows[0])
        main = pick_main(flows)
        taken = [r for f in s['flows'] if f['kind'] == 'sigungu' for r in f['regions']]
        for gid in s['groups']:                       # 자동 탐색 후보 (대표 흐름 선정에는 쓰지 않는다)
            for (sido, name), st in scan_regions(t, gid, fx, rev_q, taken):
                flows.append({'id': f's-{gid}-{sido}-{name}', 'kind': 'sigungu', 'group': gid, 'basis': 'scan', 'nature': 'candidate',
                              'label': f"{labels[gid]} — {name}", 'ok': False, **st})
        prev, past, nxt = None, [], None
        opm = margin_4q(rev_q, op_q)
        if main and is_qualified(main):
            todo = [q for q in sorted(main['exp_q']) if q not in rev_q]
            if todo:
                cs, co = consensus_quarter(conn, code, todo[-1])
                prev = K.preview(main['exp_q'], rev_q, todo[-1], cs, opm=opm, cns_op=co)
            # 진행 중인 분기: 들어온 달만으로 분기 수출을 어림해 같은 식에 넣는다 (달이 다 차면 위의 프리뷰로 바뀐다)
            krw = [None if u is None else u * fx[m] / 1e8 for u, m in zip(main['usd'], t.months)]
            part = K.partial_quarter(t.months, krw)
            if part and part[0] not in rev_q:
                cs, co = consensus_quarter(conn, code, part[0])
                nxt = K.preview({**main['exp_q'], part[0]: part[1]}, rev_q, part[0], cs, opm=opm, cns_op=co)
                if nxt:
                    nxt = {**nxt, 'months': part[2], 'verdict': None}      # 덜 찬 분기는 판정을 내지 않는다
            past = [{'q': h['q'], 'est': round(h['est']), 'act': round(h['act']), 'err': round(h['err'], 4)}
                    for h in K.hindcast(main['exp_q'], rev_q)]
        qs = sorted(set(rev_q) | set(main['exp_q'] if main else {}))[-14:]
        # 화면에서 프록시(흐름)를 바꿔 다시 계산할 때 쓰는 값: 분기 매출, 아직 실적이 안 나온 분기의 컨센서스, 영업이익률
        last_rev = max(rev_q) if rev_q else ''
        cnsq = {q: list(consensus_quarter(conn, code, q)) for q in sorted({K.quarter(m) for m in t.months}) if q > last_rev}
        i = info.get(code) or {}
        out.append({
            'c': code, 'n': s['name'], 'sector': s['sector'], 'stage': s['stage'], 'memo': s.get('memo') or None,
            'reviewed': bool(s.get('reviewed')), 'mk': i.get('mk'), 'w': i.get('w'), 'mc': i.get('mc'), 'p': i.get('p'), 'ch': i.get('ch'),
            **(pv.get(code) or {'fy0': None, 'ops': []}), 'gx': gx.get(code),
            'ret1': (ret.get(code) or (None, None))[0], 'ret3': (ret.get(code) or (None, None))[1],
            'main': main['id'] if main else None,
            'flows': [{k: v for k, v in f.items() if k != 'exp_q'} for f in flows],
            'q': [{'q': q, 'rev': round(rev_q[q]) if q in rev_q else None,
                   'exp': round(main['exp_q'][q]) if main and q in main['exp_q'] else None} for q in qs],
            'preview': prev, 'next': nxt, 'past': past,
            'rq': {q: round(v, 1) for q, v in sorted(rev_q.items())[-28:]}, 'opm': round(opm, 4) if opm is not None else None,
            'cnsq': {q: v for q, v in cnsq.items() if v[0] is not None},
        })
    return out


def surges(t: Trade, assets: dict) -> list:
    out = []
    for g in t.hs['groups']:
        if g.get('mixed') or g.get('sgg_mixed'):
            continue
        for hs6 in g['hs6']:
            for (sido, name), v in t.sgg_rows(hs6).items():
                if len(v) < 15 or any(x is None for x in v[-3:]):
                    continue
                cur = sum(v[-3:])
                y = K.yoy([x or 0 for x in v], span=3)
                if cur < SURGE_MIN_USD or y is None or y < SURGE_MIN_YOY:
                    continue
                stocks = [s['name'] for s in assets['stocks'] for f in s['flows']
                          if f['kind'] == 'sigungu' and f['group'] == g['id'] and K.region_match(sido, name, f['regions'])]
                out.append({'g': g['id'], 'label': g['label'], 'hs6': hs6, 'sgg': name, 'usd3': round(cur), 'yoy3': y,
                            'inc': round(cur - cur / (1 + y)), 'stocks': sorted(set(stocks)), 'spark': tail(v, 24)})
    return sorted(out, key=lambda x: -x['inc'])[:40]


# ------------------------------------------------------------
# 컨콜 · 탐방
# ------------------------------------------------------------

def ir_filings(conn, codes: dict, d: str, days: int = 60) -> list:
    since = (date.fromisoformat(d) - timedelta(days=days)).isoformat()
    return [{'c': c, 'n': codes[c], 'd': dt, 't': title, 'no': no} for no, dt, c, title in conn.execute(
        "SELECT rcept_no, date, code, title FROM dart_filing WHERE kind = 'ir' AND date >= ? ORDER BY date DESC, rcept_no DESC", (since,))
            if c in codes]


def call_notes(codes: dict, names: dict, path: Path = CONCALL_DB) -> dict:
    """{종목코드: [컨콜 노트…]} — 텔레그램에서 받은 글 가운데 제목 구역에 컨콜 낱말이 있고 그 종목의 글인 것"""
    if not path.exists():
        return {}
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    raw = [dict(r) for r in conn.execute('SELECT * FROM msg ORDER BY date')]
    notes = V.group_dupes([m for m in raw if V.is_note(m['text'], CALL_WORDS) and V.kind(m['text'], CALL_WORDS) == 'note'])
    matcher = V.Matcher(names)
    out = defaultdict(list)
    for m in notes:
        p = V.primary(matcher.find(m['text']))
        if not p or p['c'] not in codes or len(out[p['c']]) >= MAX_CALLS:
            continue
        out[p['c']].append({'id': f"{m['chat_id']}:{m['id']}", 'd': m['date'][:10], 'tm': m['date'][11:16], 't': V.title(m['text']),
                            'rooms': m['rooms'], 'link': m['link'] or None, 'lines': V.key_lines(m['text'], 6), 'x': m['text'][:5000]})
    return dict(out)


def visit_counts(path: Path = DATA / 'visits.json') -> dict:
    if not path.exists():
        return {}
    return {c['c']: {'n': sum(1 for n in c['notes'] if n.get('k') == 'note'), 'last': c['last']}
            for c in json.loads(path.read_text(encoding='utf-8'))['cos']}


def build(conn, tconn, hconn=None) -> tuple:
    hs = json.loads(HS_FILE.read_text(encoding='utf-8'))
    assets = json.loads(ASSETS.read_text(encoding='utf-8'))
    t = Trade(tconn, hs)
    if not t.months:
        return None, None
    d = conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    fx = fx_rates(tconn, t.months)
    stocks = build_stocks(conn, hconn, t, assets, fx, d)
    codes = {s['c']: s['n'] for s in stocks}
    from build_visits import load_names
    calls = call_notes(codes, load_names(conn))
    vis = visit_counts()
    for s in stocks:
        s['calls'] = {'n': len(calls.get(s['c'], [])), 'last': calls[s['c']][0]['d'] if calls.get(s['c']) else None}
        s['visits'] = vis.get(s['c'])
    sm = sorted(t.sgg_months())
    data = {
        'date': d, 'built_at': datetime.now().isoformat(timespec='seconds'), 'last_ym': t.months[-1], 'months': t.months,
        'sgg_from': sm[0] if sm else None, 'sgg_to': sm[-1] if sm else None,
        'fx_last': round(fx[t.months[-1]], 1), 'fx': [round(fx[m], 1) for m in t.months], 'chains': assets['chains'], 'groups': group_cards(t), 'stocks': stocks,
        'surge': surges(t, assets), 'ir': ir_filings(conn, codes, d),
        'r_ok': K.R_OK, 'band': K.BAND, 'cover_min': K.COVER_MIN, 'cover_max': K.COVER_MAX, 'mae_ok': K.MAE_OK,
        'min_q': K.MIN_Q, 'min_nq': K.MIN_NQ,
    }
    return data, {'built_at': data['built_at'], 'calls': calls}


def main() -> int:
    if not TRADE_DB.exists():
        print('수출 통계 DB 가 아직 없습니다 (collect_trade.py 먼저). 건너뜁니다.')
        return 0
    conn, tconn = db.connect(), trade_connect()
    hconn = sqlite3.connect(f'file:{HISTORY_DB}?mode=ro', uri=True) if HISTORY_DB.exists() else None
    data, calls = build(conn, tconn, hconn)
    if data is None:
        print('수출 통계가 비어 있습니다. 건너뜁니다.')
        return 0
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    OUT_CALLS.write_text(json.dumps(calls, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    pv = [s for s in data['stocks'] if s['preview']]
    print(f"consumer.json: {data['last_ym']}까지 · 묶음 {len(data['groups'])} · 종목 {len(data['stocks'])} · 프리뷰 {len(pv)} · "
          f"급등 {len(data['surge'])} · IR {len(data['ir'])} · 컨콜 노트 {sum(len(v) for v in calls['calls'].values())}건 "
          f"(시군구 {data['sgg_from']}~{data['sgg_to']})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
