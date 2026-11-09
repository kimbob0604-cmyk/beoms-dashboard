"""
조건 신호 백테스트 (20년): public/data/bt/summary.json + bt/{조합}.json

단타가 아니라 '신호가 나왔을 때 사서 큰 추세를 끝까지 들고 가면 어땠나'를 본다.

- 데이터: db/history.db (collect_history.py). 2010-01-04 부터는 KRX 일별 전 종목(상장폐지 종목 포함, 그날 시총),
  그 전(2005 ~ 2009)은 네이버 수정주가 — 2010년 전에 상장폐지된 종목은 빠진다(그 구간만 생존 편향).
- 신호: 고른 조건을 그날 종가 기준으로 '모두' 만족 (그날까지 알 수 있던 데이터만 사용).
- 매수: 신호 다음 거래일 종가. 신호마다 같은 금액(1단위)을 사고, 팔 때까지 비중을 다시 맞추지 않는다(오른 종목은 비중이 커진다).
- 매도 규칙 3가지 (EXITS):
    h120  : 마지막으로 조건을 만족한 날부터 120거래일(6개월) 뒤
    h250  : 250거래일(1년) 뒤
    trend : 종가가 120일선 아래로 내려가면 (120일선 위에서 조건을 만족할 때만 매수)
  매도도 판단 다음 거래일 종가.
- 비용: 살 때·팔 때 각각 COST(0.3%).
- 투자 대상: 보통주(스팩·리츠 제외), 그 시점 시총 MIN_MCAP(500억) 이상, 20일 평균 거래대금 MIN_TV(5억) 이상.
- 검증: 기간을 앞 절반(전반)·뒤 절반(후반)으로 나눠 따로 계산하고, 2010년 이후(상장폐지 포함 구간)만도 따로 계산.
- 신호 통계(ev): 60거래일 만에 처음 조건을 만족한 날을 '신호 발생'으로 보고 그 뒤 60·120·250거래일 수익률과
  같은 날 대상 전체 평균 대비 초과, 1년 안에 2배가 된 비율.

  python3 build_backtest.py [--no-cache] [--threads 8] [--max 3]
"""

import argparse
import itertools
import math
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from build_naver import DATA, write_json
from collect_history import HIST
from universe import is_common

START = '2006-11-10'
COST = 0.003
MIN_MCAP = 500      # 억원
MIN_TV = 5          # 억원
MAX_COMBO = 3
OUT = DATA / 'bt'
CACHE = Path(__file__).parent / '.cache' / 'bt'
EXCLUDE_NAME = ('스팩', '기업인수목적', '리츠', '인프라투융자', '유전개발', '선박투자', '하이골드', '바다로')

EXITS = [
    ('h120', '6개월 보유', '마지막으로 조건을 만족한 날부터 120거래일 뒤 매도'),
    ('h250', '1년 보유', '마지막으로 조건을 만족한 날부터 250거래일 뒤 매도'),
    ('trend', '120일선 이탈까지', '종가가 120일 이동평균 아래로 내려가면 매도 (120일선 위에서만 매수)'),
]
HOLD_DAYS = {'h120': 120, 'h250': 250}

CONDS = [
    ('nh52', '52주 신고가', '종가가 직전 250거래일 최고 종가 이상 (신고가를 새로 쓴 날)'),
    ('ath', '5년 신고가', '종가가 직전 1,250거래일(5년) 최고 종가 이상 — 상장 3년 이상'),
    ('box', '박스권 돌파', '직전 120일 고점÷저점이 1.35배 이내로 횡보하다가 그 고점을 종가로 돌파'),
    ('align', '이동평균 정배열', '종가 > 20일선 > 60일선 > 120일선'),
    ('above200', '200일선 위 + 상승', '종가 > 200일선이고 200일선이 20일 전보다 높음'),
    ('mom12', '12개월 모멘텀 상위 20%', '최근 1개월을 뺀 12개월 수익률이 대상 종목 중 상위 20%'),
    ('turn', '낙폭 과대 후 추세 전환', '120일 저점이 52주 고점의 60% 이하였는데 종가가 120일선 위, 20일선 > 60일선'),
    ('vsurge', '거래대금 구조적 증가', '20일 평균 거래대금이 250일 평균의 2.5배 이상'),
    ('bigup', '거래 실린 급등', '하루 +8% 이상 오르고 거래대금이 20일 평균의 3배 이상'),
    ('squeeze', '변동성 수축', '60일 변동성이 250일 변동성의 70% 이하'),
    ('frgn', '외국인 순매수 상위 10%', '외국인 20일 순매수 금액 ÷ 시총이 대상 종목 중 상위 10%'),
    ('inst', '기관 순매수 상위 10%', '기관 20일 순매수 금액 ÷ 시총이 대상 종목 중 상위 10%'),
    ('cobuy', '외국인·기관 동반 순매수', '20일 외국인·기관 순매수가 모두 플러스이고 합계가 시총의 0.5% 이상'),
    ('fr_up', '외국인 지분율 상승', '외국인 지분율이 60거래일 전보다 1%p 이상 높음'),
    ('e_turn', '영업이익 흑자전환', '최근 분기 영업이익이 흑자이고 전년 같은 분기는 적자 — 실적 공시 다음 날부터 다음 공시까지 (2016년부터)'),
    ('e_up', '영업이익 +50%↑', '최근 분기 영업이익이 전년 같은 분기보다 50% 이상 늘고(둘 다 흑자) 매출도 증가 (2016년부터)'),
    ('e_rec', '분기 최대 영업이익', '최근 분기 영업이익이 직전 7개 분기 어느 때보다 큼 (2017년부터)'),
    ('large', '대형주 (시총 1조↑)', '그 시점 시총 1조 이상'),
    ('small', '소형주 (시총 2천억↓)', '그 시점 시총 2천억 미만'),
    ('mkt_up', '시장 상승 추세', '코스피가 120일선 위에 있는 날에만 매수'),
]
EXCLUSIVE = [{'large', 'small'}, {'e_turn', 'e_up'}]
FIN_CONDS = ('e_turn', 'e_up', 'e_rec')      # 2016년 이후에만 신호가 있다
FIN_HOLD = 100       # 다음 실적 공시가 없으면 100거래일까지만 유효 (3분기 보고서 → 사업보고서 간격이 약 95거래일)


# ------------------------------------------------------------
# 데이터 → 행렬 (날짜 × 종목)
# ------------------------------------------------------------

def _fill(conn, sql, cidx, didx, mats, params=()):
    for chunk in pd.read_sql_query(sql, conn, params=params, chunksize=400_000):
        ci, di = chunk['code'].map(cidx), chunk['date'].map(didx)
        ok = (ci.notna() & di.notna()).values
        ci, di = ci.values[ok].astype(np.int64), di.values[ok].astype(np.int64)
        for col, M in mats.items():
            M[di, ci] = pd.to_numeric(chunk[col], errors='coerce').values[ok]


def fin_states(conn, cidx, days):
    """분기 실적 → {조건: bool[D, N]} (공시일 다음 거래일부터 다음 공시 전날까지)"""
    import bisect
    from collections import defaultdict
    D, N = len(days), len(cidx)
    raw = defaultdict(dict)       # (code, year, reprt) → {fs: {acc: (cur, cur_add, prev, prev_add)}, 'rcept': ..}
    for code, year, rp, fs, acc, cur, cur_add, prev, prev_add, rcept in conn.execute(
            'SELECT code, year, reprt, fs, acc, cur, cur_add, prev, prev_add, rcept FROM fin'):
        if code in cidx:
            d = raw[(code, year, rp)]
            d.setdefault(fs, {})[acc] = (cur, cur_add, prev, prev_add)
            d['rcept'] = max(d.get('rcept') or '', rcept or '')
    QN = {'11013': 1, '11012': 2, '11014': 3, '11011': 4}
    series = defaultdict(dict)    # code → {(year, q): {'op','op_py','sales','sales_py','date'}}
    for (code, year, rp), d in raw.items():
        fs = 'CFS' if 'op' in d.get('CFS', {}) else 'OFS'
        if 'op' not in d.get(fs, {}) or not d.get('rcept'):
            continue
        q, vals = QN[rp], {}
        for acc in ('op', 'sales'):
            a = d[fs].get(acc)
            if not a:
                continue
            cur, _, prev, _ = a
            if q == 4:            # 사업보고서는 연간 → 3분기 누적을 빼서 4분기만
                q3 = raw.get((code, year, '11014'), {}).get(fs, {}).get(acc)
                if not q3 or q3[1] is None or cur is None:
                    continue
                cur = cur - q3[1]
                prev = prev - q3[3] if prev is not None and q3[3] is not None else None
            vals[acc], vals[acc + '_py'] = cur, prev
        if vals.get('op') is None:
            continue
        r = d['rcept']
        vals['date'] = f'{r[:4]}-{r[4:6]}-{r[6:8]}'
        series[code][(year, q)] = vals
    out = {k: np.zeros((D, N), bool) for k in FIN_CONDS}
    for code, qs in series.items():
        c = cidx[code]
        keys = sorted(qs)
        for (y, q), v in list(qs.items()):    # 전년 같은 분기 값으로 과거 분기를 채운다 (분기 최대 판단용)
            if v.get('op_py') is not None and (y - 1, q) not in qs:
                qs[(y - 1, q)] = {'op': v['op_py'], 'date': None}
        allk = sorted(qs)
        filed = sorted((qs[k]['date'], k) for k in keys)
        for n, (d, k) in enumerate(filed):
            i = bisect.bisect_right(days, d)                     # 공시일 다음 거래일
            if i >= D:
                continue
            nxt = bisect.bisect_right(days, filed[n + 1][0]) if n + 1 < len(filed) else D
            j = min(max(nxt, i + 1), i + FIN_HOLD, D)
            v = qs[k]
            op, py = v['op'], v.get('op_py')
            if py is not None and op > 0 > py:
                out['e_turn'][i:j, c] = True
            sl, slp = v.get('sales'), v.get('sales_py')
            if py is not None and py > 0 and op >= 1.5 * py and (sl is None or slp is None or sl > slp):
                out['e_up'][i:j, c] = True
            p = allk.index(k)
            past = [qs[allk[m]]['op'] for m in range(max(0, p - 7), p)
                    if (allk[p][0] - allk[m][0]) * 4 + allk[p][1] - allk[m][1] <= 7]
            if op > 0 and len(past) >= 7 and op > max(past):
                out['e_rec'][i:j, c] = True
    return out


def load(use_cache=True):
    conn = sqlite3.connect(f'file:{HIST}?mode=ro', uri=True)
    stamp = '-'.join(str(conn.execute(q).fetchone()[0]) for q in (
        'SELECT COUNT(*) FROM hday WHERE n > 0', 'SELECT MAX(date) FROM hday WHERE n > 0',
        "SELECT COUNT(*) FROM hdone WHERE kind = 'fl'", "SELECT COUNT(*) FROM hdone WHERE kind = 'nv'",
        'SELECT MAX(date) FROM fl', 'SELECT COUNT(*) FROM fin'))
    f = CACHE / 'mats.npz'
    if use_cache and f.exists() and (CACHE / 'stamp.txt').exists() and (CACHE / 'stamp.txt').read_text() == stamp:
        z = np.load(f, allow_pickle=True)
        return {k: z[k] for k in z.files}

    krx_days = [r[0] for r in conn.execute('SELECT date FROM hday WHERE n > 0 ORDER BY date')]
    first_krx = krx_days[0]
    pre = [r[0] for r in conn.execute("SELECT date FROM hidx WHERE code = 'KOSPI' AND date < ? ORDER BY date",
                                      (first_krx,))]
    days = pre + krx_days
    didx = {d: i for i, d in enumerate(days)}
    k0 = len(pre)
    names = [(c, n, m) for c, n, m in conn.execute('SELECT code, name, market FROM hname ORDER BY code')
             if is_common(c) and not any(w in (n or '') for w in EXCLUDE_NAME)]
    codes = [c for c, _, _ in names]
    cidx = {c: i for i, c in enumerate(codes)}
    D, N = len(days), len(codes)
    new = lambda: np.full((D, N), np.nan, np.float32)

    CH, MC, TV = new(), new(), new()
    _fill(conn, 'SELECT code, date, chg, mcap, tv FROM hp', cidx, didx, {'chg': CH, 'mcap': MC, 'tv': TV})
    NC, NV = new(), new()
    _fill(conn, 'SELECT code, date, close, volume FROM nv WHERE date < ?', cidx, didx, {'close': NC, 'volume': NV},
          (first_krx,))
    FQ, OQ, FC, FR = new(), new(), new(), new()
    _fill(conn, 'SELECT code, date, frgn, org, close, fr FROM fl', cidx, didx,
          {'frgn': FQ, 'org': OQ, 'close': FC, 'fr': FR})

    R = CH / 100
    # 가격제한폭을 넘는 등락률인데 시총 변화와 1.5배 넘게 어긋나면(감자·병합 뒤 기준가가 안 맞는 날) 시총 변화를 수익률로 쓴다
    with np.errstate(divide='ignore', invalid='ignore'):
        mcr = np.vstack([np.full((1, N), np.nan, np.float32), MC[1:] / MC[:-1] - 1])
        gap = (1 + R) / (1 + mcr)
        odd = (np.abs(CH) > 31) & ~np.isnan(mcr) & ((gap > 1.5) | (gap < 1 / 1.5))
    R[odd] = mcr[odd]
    R[R > 3.0] = 0          # 상장 첫날 상한(+300%)을 넘는 값은 오류로 본다
    bad = 0
    if k0 > 1:      # 2010년 전: 네이버 수정주가의 전일 대비. 하루 ±31% 넘는 값은 수정 누락으로 보고 0 처리 (당시 상하한 15%)
        ncf = pd.DataFrame(NC[:k0]).ffill().values
        with np.errstate(divide='ignore', invalid='ignore'):
            rp = ncf[1:] / ncf[:-1] - 1
        rp[np.isnan(NC[1:k0])] = np.nan
        wrong = np.abs(rp) > 0.31
        bad = int(wrong.sum())
        rp[wrong] = 0
        R[1:k0] = rp
    valid = ~np.isnan(R)
    inside = np.maximum.accumulate(valid, axis=0) & np.maximum.accumulate(valid[::-1], axis=0)[::-1]
    r = np.where(inside, np.clip(np.nan_to_num(R), -0.99, None), 0).astype(np.float64)
    P = np.exp(np.cumsum(np.log1p(r), axis=0)).astype(np.float32)
    P[~inside] = np.nan
    R = np.where(inside, np.nan_to_num(R), np.nan).astype(np.float32)

    if k0:          # 2010년 전 시총 = 첫 KRX 날짜 시총 × 그때 대비 수정주가 비율 (주식 수 변화는 반영 못 함)
        mcv = ~np.isnan(MC)
        first = mcv.argmax(axis=0)
        cols = np.arange(N)
        with np.errstate(divide='ignore', invalid='ignore'):
            ratio = np.where(mcv.any(axis=0), MC[first, cols] / P[first, cols], np.nan)
        MC[:k0] = P[:k0] * ratio[None, :]
        TV[:k0] = NV[:k0] * np.where(np.isnan(FC[:k0]), NC[:k0], FC[:k0]) / 1e8   # 거래량은 수정 전 → 수정 전 종가를 곱한다
    with np.errstate(invalid='ignore'):
        FN, ON = FQ * FC / 1e8, OQ * FC / 1e8          # 순매수 금액, 억원
    idx = np.full((2, D), np.nan)
    for j, code in enumerate(('KOSPI', 'KOSDAQ')):
        for d, cl in conn.execute('SELECT date, close FROM hidx WHERE code = ?', (code,)):
            if d in didx:
                idx[j, didx[d]] = cl
    out = {'days': np.array(days), 'codes': np.array(codes), 'names': np.array([n or '' for _, n, _ in names]),
           'markets': np.array([m or '' for _, _, m in names]), 'k0': np.array(k0), 'bad': np.array(bad),
           'P': P, 'R': R, 'MC': MC, 'TV': TV, 'FN': FN.astype(np.float32), 'ON': ON.astype(np.float32),
           'FR': FR, 'idx': idx, **fin_states(conn, cidx, days)}
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez(f, **out)
    (CACHE / 'stamp.txt').write_text(stamp)
    return out


# ------------------------------------------------------------
# 조건 행렬
# ------------------------------------------------------------

def signals(x):
    """{조건: bool[D, N]}, 투자 대상 univ[D, N], 매도 조건 X[D, N](120일선 아래)"""
    P, R, MC, TV = x['P'], x['R'], x['MC'], x['TV']
    D, N = P.shape

    def roll(a, w, fn, mp=None):
        return getattr(pd.DataFrame(a).rolling(w, min_periods=mp or w), fn)().values.astype(np.float32)

    def sh(a, k):
        return np.vstack([np.full((k, a.shape[1]), np.nan, np.float32), a[:-k]])

    def xrank(v, mask):
        return pd.DataFrame(np.where(mask, v, np.nan)).rank(axis=1, pct=True).values

    with np.errstate(divide='ignore', invalid='ignore'):
        ma20, ma60, ma120, ma200 = (roll(P, w, 'mean') for w in (20, 60, 120, 200))
        hi120, lo120 = roll(P, 120, 'max'), roll(P, 120, 'min')
        hi250 = roll(P, 250, 'max', 200)
        hi1250 = roll(P, 1250, 'max', 750)
        tv20, tv250 = roll(TV, 20, 'mean', 15), roll(TV, 250, 'mean', 200)
        univ = (MC >= MIN_MCAP) & (tv20 >= MIN_TV) & ~np.isnan(P)
        S = {
            'nh52': P >= sh(hi250, 1),
            'ath': P >= sh(hi1250, 1),
            'box': (sh(hi120, 1) / sh(lo120, 1) <= 1.35) & (P > sh(hi120, 1)),
            'align': (P > ma20) & (ma20 > ma60) & (ma60 > ma120),
            'above200': (P > ma200) & (ma200 > sh(ma200, 20)),
            'mom12': xrank(sh(P, 21) / sh(P, 252) - 1, univ) >= 0.8,
            'turn': (lo120 / hi250 <= 0.6) & (P > ma120) & (ma20 > ma60),
            'vsurge': tv20 >= 2.5 * tv250,
            'bigup': (R >= 0.08) & (TV >= 3 * sh(tv20, 1)),
        }
        del hi120, lo120, hi250, hi1250, ma20, ma60, ma200
        S['squeeze'] = roll(R, 60, 'std', 40) <= 0.7 * roll(R, 250, 'std', 200)
        f20, o20 = roll(x['FN'], 20, 'sum', 15), roll(x['ON'], 20, 'sum', 15)
        S['frgn'] = (xrank(f20 / MC, univ) >= 0.9) & (f20 > 0)
        S['inst'] = (xrank(o20 / MC, univ) >= 0.9) & (o20 > 0)
        S['cobuy'] = (f20 > 0) & (o20 > 0) & ((f20 + o20) / MC >= 0.005)
        S['fr_up'] = x['FR'] - sh(x['FR'], 60) >= 1.0
        for k in FIN_CONDS:
            S[k] = x[k]
        S['large'] = MC >= 10000
        S['small'] = MC < 2000
        k = pd.Series(x['idx'][0])
        up = (k > k.rolling(120).mean()).values
        S['mkt_up'] = np.broadcast_to(up[:, None], (D, N))
        X = P < ma120
    return S, univ, X


# ------------------------------------------------------------
# 시뮬레이션
# ------------------------------------------------------------

class Sim:
    """START 이후 구간으로 자른 공용 행렬"""

    def __init__(self, x, univ, X):
        days = [str(d) for d in x['days']]
        self.s0 = next(i for i, d in enumerate(days) if d >= START)
        s0 = self.s0
        self.days = days[s0:]
        self.T = len(self.days)
        self.P = x['P'][s0:]
        self.Pprev = x['P'][s0 - 1:-1]
        self.MC = x['MC'][s0:]
        self.valid = ~np.isnan(self.P)
        self.t = np.arange(self.T, dtype=np.int32)[:, None]
        self.lastX = np.maximum.accumulate(np.where(X[s0:], self.t, -1).astype(np.int32), axis=0)
        self.X = X[s0:]
        R = x['R'][s0:]
        # 비교 기준: 대상 전체 동일가중 (전날 대상이던 종목의 그날 수익률 평균)
        up = univ[s0 - 1:-1] & ~np.isnan(R)
        self.bench = np.where(up, R, 0).sum(axis=1, dtype=np.float64) / np.maximum(up.sum(axis=1), 1)
        idx = x['idx'][:, s0 - 1:]
        with np.errstate(invalid='ignore'):
            self.idx = np.nan_to_num(idx[:, 1:] / idx[:, :-1] - 1)
        self.year = np.array([int(d[:4]) for d in self.days])
        self.years = sorted(set(self.year.tolist()))
        self.half = self.T // 2
        self.q3 = self.half + (self.T - self.half) // 2
        self.i10 = next((i for i, d in enumerate(self.days) if d >= '2010-01-04'), 0)
        wk = [date.fromisoformat(d).isocalendar()[:2] for d in self.days]
        self.widx = [i for i in range(self.T) if i == self.T - 1 or wk[i] != wk[i + 1]]
        # 신호 통계용: 신호 다음 날 종가 기준 60·120·250일 뒤 수익률, 1년 안 최고 상승
        Pf = pd.DataFrame(self.P).ffill().values          # 상장폐지 뒤는 마지막 가격
        self.FW, self.ufw = {}, {}
        u = univ[s0:]
        with np.errstate(divide='ignore', invalid='ignore'):
            for h in (60, 120, 250):
                fw = np.full(self.P.shape, np.nan, np.float32)
                if self.T > h + 2:
                    fw[:self.T - 1 - h] = Pf[1 + h:] / Pf[1:self.T - h] - 1
                self.FW[h] = fw
                ok = u & ~np.isnan(fw)
                self.ufw[h] = np.where(ok, fw, 0).sum(axis=1, dtype=np.float64) / np.maximum(ok.sum(axis=1), 1)
            rev = pd.DataFrame(Pf[::-1]).rolling(250, min_periods=250).max().values[::-1]   # rev[t] = max(Pf[t .. t+249])
            mfe = np.full(self.P.shape, np.nan, np.float32)
            mfe[:self.T - 2] = rev[2:] / Pf[1:self.T - 1] - 1
            self.MFE = mfe

    def span(self, a, b):
        return max((date.fromisoformat(self.days[b - 1]) - date.fromisoformat(self.days[a])).days, 1) / 365.25

    def metrics(self, ret):
        """일간 수익률 → 성과"""
        def cagr(a, b, r=ret):
            return (math.exp(np.log1p(r[a:b]).sum() / self.span(a, b)) - 1) * 100
        nav = np.cumprod(1 + ret)
        sd = ret.std()
        peak = np.maximum.accumulate(nav)
        yr = [round(float(np.prod(1 + ret[self.year == y]) - 1) * 100, 1) for y in self.years]
        yb = [round(float(np.prod(1 + self.bench[self.year == y]) - 1) * 100, 1) for y in self.years]
        h, T, B = self.half, self.T, self.bench
        return {
            'cagr': round(cagr(0, T), 1), 'x': round(cagr(0, T) - cagr(0, T, B), 1),
            'vol': round(float(sd) * math.sqrt(250) * 100, 1),
            'sharpe': round(float(ret.mean() / sd) * math.sqrt(250), 2) if sd > 0 else 0,
            'mdd': round(float((nav / peak - 1).min()) * 100, 1),
            'c1': round(cagr(0, h), 1), 'x1': round(cagr(0, h) - cagr(0, h, B), 1),
            'c2': round(cagr(h, T), 1), 'x2': round(cagr(h, T) - cagr(h, T, B), 1),
            'c10': round(cagr(self.i10, T), 1), 'x10': round(cagr(self.i10, T) - cagr(self.i10, T, B), 1),
            'x3': round(cagr(h, self.q3) - cagr(h, self.q3, B), 1), 'x4': round(cagr(self.q3, T) - cagr(self.q3, T, B), 1),
            'mdd2': round(float((nav[h:] / np.maximum.accumulate(nav[h:]) - 1).min()) * 100, 1),
            'sh2': round(float(ret[h:].mean() / ret[h:].std()) * math.sqrt(250), 2) if ret[h:].std() > 0 else 0,
            'yw': int(sum(a > b for a, b in zip(yr, yb))),
        }, yr, nav

    def run(self, S, mode, names=None, codes=None):
        """S: bool[T, N] (START 이후, 투자 대상 포함). → dict 또는 None"""
        cols = np.flatnonzero(S.any(axis=0))
        if not len(cols):
            return None
        Sc, t = S[:, cols], self.t
        if mode == 'trend':
            lastS = np.maximum.accumulate(np.where(Sc & ~self.X[:, cols], t, -1), axis=0)
            Hd = lastS > self.lastX[:, cols]
        else:
            H = HOLD_DAYS[mode]
            cs = np.cumsum(Sc, axis=0, dtype=np.int32)
            Hd = cs > 0
            if self.T > H + 1:
                Hd[H + 1:] = (cs[H + 1:] - cs[:-H - 1]) > 0
        valid = self.valid[:, cols]
        Hd &= valid
        A = np.zeros_like(Hd)           # 수익이 붙는 날: 판단(t-2) → 매수(t-1 종가) → t
        A[2:] = Hd[:-2]
        A &= valid
        if not A.any():
            return None
        startA, endA = A.copy(), A.copy()
        startA[1:] &= ~A[:-1]
        endA[:-1] &= ~A[1:]
        Pc, Pp = self.P[:, cols], self.Pprev[:, cols]
        bidx = np.maximum.accumulate(np.where(startA, t - 1, -1), axis=0)
        Pb = np.take_along_axis(Pc, np.maximum(bidx, 0), axis=0)
        with np.errstate(divide='ignore', invalid='ignore'):
            W = np.where(A, Pc / Pb, 0)             # 1단위 산 포지션의 오늘 가치
            Wp = np.where(A, Pp / Pb, 0)            # 어제 가치
        ns = startA.sum(axis=1)

        def series(w, wp, entry):
            num = (w - wp).sum(axis=1, dtype=np.float64) - COST * (entry + (w * endA).sum(axis=1, dtype=np.float64))
            den = wp.sum(axis=1, dtype=np.float64)
            return np.clip(np.divide(num, den, out=np.zeros(self.T), where=den > 0), -0.99, None)

        ret = series(W, Wp, ns)
        mcb = np.nan_to_num(np.take_along_axis(self.MC[:, cols], np.maximum(bidx, 0), axis=0))
        retc = series(W * mcb, Wp * mcb, (startA * mcb).sum(axis=1, dtype=np.float64))
        m, yr, nav = self.metrics(ret)
        mc, _, _ = self.metrics(retc)
        held = A.sum(axis=1)
        inv = held > 0
        # 거래별 수익률 (열 순서 → 시작·끝이 짝이 맞는다)
        sc, st = np.nonzero(startA.T)
        ec, et = np.nonzero(endA.T)
        tr = Pc[et, ec] / Pc[st - 1, sc] * (1 - COST) ** 2 - 1
        m.update({
            'capc': mc['cagr'], 'n': round(float(held[inv].mean()), 1) if inv.any() else 0,
            'inv': round(float(inv.mean()) * 100), 'tr': int(len(tr)),
            'win': round(float((tr > 0).mean()) * 100), 'avg': round(float(tr.mean()) * 100, 1),
            'med': round(float(np.median(tr)) * 100, 1), 'big': round(float((tr >= 1).mean()) * 100, 1),
            'hd': round(float((et - st + 1).mean())),
        })
        out = {'m': m, 'yr': yr, 'nav': [int(round(math.log(v) * 1000)) for v in nav[self.widx]],
               'n': [int(v) for v in held[self.widx]]}
        if names is not None:           # 지금 들고 있는 종목 (마지막 날 판단 기준)
            on = np.flatnonzero(Hd[-1])
            rows = []
            if len(on):
                off = np.maximum.accumulate(np.where(~Hd[:, on], t, -1), axis=0)[-1]     # 마지막으로 비보유였던 날
                for j, o in zip(on, off):
                    e = int(o) + 1                      # 신호일
                    c = cols[j]
                    rows.append({'c': codes[c], 'n': names[c], 'd': self.days[e],
                                 'r': round(float(Pc[-1, j] / Pc[e + 1, j] - 1) * 100, 1) if e + 1 < self.T else None,
                                 'mc': round(float(self.MC[-1, c])) if not np.isnan(self.MC[-1, c]) else None})
                rows.sort(key=lambda r: r['d'], reverse=True)
            out['nnow'] = len(rows)
            out['now'] = rows[:50]
        return out

    def events(self, S):
        """신호 발생(60거래일 만에 처음 만족) 뒤 수익률"""
        cs = np.cumsum(S, axis=0, dtype=np.int32)
        prior = np.zeros(S.shape, bool)
        prior[1:] = cs[:-1] > 0
        if self.T > 61:
            prior[61:] = (cs[60:-1] - cs[:-61]) > 0
        on = S & ~prior
        on[-1] = False
        out = {'n': int(on.sum())}
        if not out['n']:
            return out
        r, c = np.nonzero(on)
        for h in (60, 120, 250):
            fw = self.FW[h][r, c]
            ok = ~np.isnan(fw)
            if not ok.any():
                continue
            ex = fw[ok] - self.ufw[h][r[ok]]
            out[f'f{h}'] = round(float(fw[ok].mean()) * 100, 1)
            out[f'x{h}'] = round(float(ex.mean()) * 100, 1)
            if h == 250:
                out['w250'] = round(float((ex > 0).mean()) * 100)
                out['m250'] = round(float(np.median(fw[ok])) * 100, 1)
        mfe = self.MFE[r, c]
        ok = ~np.isnan(mfe)
        if ok.any():
            out['big'] = round(float((mfe[ok] >= 1).mean()) * 100, 1)
        return out


def combos(max_k):
    keys = [k for k, _, _ in CONDS]
    for r in range(1, max_k + 1):
        for c in itertools.combinations(keys, r):
            if not any(ex <= set(c) for ex in EXCLUSIVE):
                yield c


def build(threads=8, max_k=MAX_COMBO, use_cache=True, only=None):
    t0 = time.time()
    x = load(use_cache)
    print(f'데이터 {x["P"].shape[0]}일 × {x["P"].shape[1]}종목 ({time.time() - t0:.0f}초), '
          f'2010 전 수정 누락 의심 {int(x["bad"])}건', flush=True)
    S, univ, X = signals(x)
    sim = Sim(x, univ, X)
    s0 = sim.s0
    u = univ[s0:]
    S = {k: v[s0:] & u for k, v in S.items()}
    names, codes = [str(n) for n in x['names']], [str(c) for c in x['codes']]
    print(f'조건 계산 끝 ({time.time() - t0:.0f}초) · {sim.days[0]} ~ {sim.days[-1]} ({sim.T}일)', flush=True)
    todo = [c for c in combos(max_k) if only is None or '+'.join(c) in only]
    OUT.mkdir(parents=True, exist_ok=True)

    def one(c):
        key = '+'.join(c)
        s = S[c[0]]
        for k in c[1:]:
            s = s & S[k]
        res = {e: sim.run(s, e, names, codes) for e, _, _ in EXITS}
        if not any(res.values()):
            return None
        ev = sim.events(s)
        write_json(OUT / f'{key}.json', {'key': key, 'ev': ev, 'x': {e: r for e, r in res.items() if r}})
        return {'k': key, 'ev': ev, 'x': {e: {**r['m'], 'now': r.get('nnow', 0)} for e, r in res.items() if r}}

    rows, done = [], 0
    with ThreadPoolExecutor(threads) as ex:
        for r in ex.map(one, todo):
            done += 1
            if r:
                rows.append(r)
            if not done % 50:
                print(f'  {done}/{len(todo)} ({time.time() - t0:.0f}초)', flush=True)
    bm, byr, _ = sim.metrics(sim.bench)
    lg = lambda r: [int(round(v * 1000)) for v in np.cumsum(np.log1p(r))[sim.widx]]
    summary = {
        'built': time.strftime('%Y-%m-%d %H:%M'), 'start': sim.days[0], 'end': sim.days[-1], 'cost': COST * 100,
        'min_mcap': MIN_MCAP, 'min_tv': MIN_TV, 'half': sim.days[sim.half], 'q3': sim.days[sim.q3],
        'clean': sim.days[sim.i10], 'fin': list(FIN_CONDS),
        'conds': [{'k': k, 'l': l, 'd': d} for k, l, d in CONDS],
        'exits': [{'k': k, 'l': l, 'd': d} for k, l, d in EXITS],
        'weeks': [sim.days[i] for i in sim.widx], 'years': sim.years,
        'bench': {'univ': lg(sim.bench), 'kospi': lg(sim.idx[0]), 'kosdaq': lg(sim.idx[1])},
        'bench_m': bm, 'bench_yr': byr,
        'idx_m': {k: sim.metrics(sim.idx[j])[0] for j, k in enumerate(('kospi', 'kosdaq'))},
        'idx_yr': {k: [round(float(np.prod(1 + sim.idx[j][sim.year == y]) - 1) * 100, 1) for y in sim.years]
                   for j, k in enumerate(('kospi', 'kosdaq'))},
        'combos': rows,
    }
    if only is None:
        keep = {r['k'] for r in rows}
        for p in OUT.glob('*.json'):
            if p.stem not in keep and p.stem != 'summary':
                p.unlink()
        write_json(OUT / 'summary.json', summary)
    print(f'bt: {summary["start"]} ~ {summary["end"]} · 조합 {len(rows)}개 · 대상 전체 연 {bm["cagr"]}% '
          f'(MDD {bm["mdd"]}%) · {time.time() - t0:.0f}초')
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-cache', action='store_true')
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--max', type=int, default=MAX_COMBO)
    ap.add_argument('--only', help='쉼표로 구분한 조합 키만 (시험용, summary 는 쓰지 않음)')
    a = ap.parse_args()
    s = build(a.threads, a.max, not a.no_cache, set(a.only.split(',')) if a.only else None)
    for e, l, _ in EXITS:
        ok = [c for c in s['combos'] if e in c['x'] and c['x'][e]['n'] >= 5 and c['x'][e]['tr'] >= 100]
        print(f'\n[{l}] 전반 초과수익 상위 → 후반')
        for c in sorted(ok, key=lambda c: -c['x'][e]['x1'])[:8]:
            m = c['x'][e]
            print(f"  {c['k']:34s} 연 {m['cagr']:6.1f}% MDD {m['mdd']:6.1f}% 전반 {m['x1']:+6.1f} 후반 {m['x2']:+6.1f} "
                  f"2010~ {m['x10']:+6.1f} 평균 {m['n']:5.1f}종목 거래 {m['tr']}")


if __name__ == '__main__':
    main()
