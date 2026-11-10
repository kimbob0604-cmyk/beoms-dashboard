"""
전략 트래커 빌드: db/strategy.db 의 문서·종목(collect_strategy.py) + 과거 가격(history.db)
→ public/data/st/summary.json (전략별 일별 누적·기간별 성과·신호 성적) + public/data/st/{전략}.json (지금 보유·최근 글)

규칙
- 살 시점: 네이버 리포트는 게시일 다음 거래일 종가. 텔레그램 글은 장중(15:20 전)이면 그날 종가, 아니면 다음 거래일 종가.
- 포트폴리오형(port): 리포트의 목록을 그대로 들고 가다 다음 호가 나오면 교체. 비중이 있으면 그대로, 없으면 같은 금액.
  다음 호가 STALE 거래일 넘게 안 나오면 판다. 끊긴 적이 있으면 가장 최근에 이어진 구간만 성과로 본다.
- 신호형(signal): 글에 실린 종목을 살 시점부터 20·60·120거래일 보유. 보유 중인 종목을 매일 같은 비중으로.
  종목당 최대 1/MIN_N — 보유 종목이 MIN_N개 미만이면 나머지는 현금(0%). 지수와 견줄 때도 그날 투자한 비율만큼만 지수를 센다.
- 비용: 살 때·팔 때 각 COST (피할 종목 묶음은 비용 없음). 비교 지수는 코스피·코스닥 종가 등락률(배당 제외).

  python3 build_strategy.py
"""

import bisect
import sqlite3
import sys
from datetime import datetime

import numpy as np

from build_backtest import load
from build_naver import DATA, write_json
from collect_strategy import STRAT
from strategy_parse import SERIES

OUT = DATA / 'st'
COST = 0.003
HOLDS = (20, 60, 120)
STALE = {'hana_qmp': 50, 'daishin_top10': 50, 'daol_aq': 30}     # 거래일
WINDOWS = (('all', None), ('3y', 750), ('1y', 250), ('6m', 125), ('3m', 63))
CUTOFF = '15:20'
MIN_N = 5      # 신호형: 종목당 최대 1/5. 보유 종목이 5개 미만이면 나머지는 현금 (한두 종목에 전액이 실리지 않게)


def entry_index(days, date, ts=None):
    """그 글을 보고 살 수 있는 첫 종가의 날짜 번호. 아직 그 날이 안 왔으면 None."""
    if ts:
        j = bisect.bisect_left(days, date)
        if j < len(days) and days[j] == date and ts[11:16] < CUTOFF:
            return j
    i = bisect.bisect_right(days, date)
    return i if i < len(days) else None


def port_track(issues, R, T, stale, cost=COST):
    """issues: [(e, {열: 비중})] e 오름차순. → (일별 수익률, 일별 보유 종목 수, 성과로 보는 첫 날 번호)"""
    r, n = np.zeros(T), np.zeros(T, np.int32)
    prev, start = {}, None
    for k, (e, w) in enumerate(issues):
        nxt = issues[k + 1][0] if k + 1 < len(issues) else T - 1
        end = min(nxt, e + stale, T - 1)
        if start is None or (k and e > issues[k - 1][0] + stale):     # 처음이거나 앞 호와 끊겼다 → 여기서 새로 시작
            start, prev = e + 1, {}
        cols = np.array(sorted(w), dtype=np.int64)
        if e + 1 > end:
            continue
        if len(cols):
            w0 = np.array([w[c] for c in cols], float)
            w0 /= w0.sum()
            val = w0 * np.cumprod(1 + np.nan_to_num(R[e + 1:end + 1][:, cols]).astype(np.float64), axis=0)
            tot = val.sum(axis=1)
            r[e + 1:end + 1] = tot / np.concatenate([[1.0], tot[:-1]]) - 1
            n[e + 1:end + 1] = len(cols)
            new = dict(zip(cols.tolist(), w0.tolist()))
            last = dict(zip(cols.tolist(), (val[-1] / tot[-1]).tolist()))
        else:
            new, last = {}, {}
        turn = sum(abs(new.get(c, 0) - prev.get(c, 0)) for c in set(new) | set(prev))
        r[e + 1] = (1 + r[e + 1]) * (1 - cost * turn) - 1
        prev = last
        if end < nxt and last:      # 다음 호가 너무 늦다 → 판다
            r[end] = (1 + r[end]) * (1 - cost) - 1
            prev = {}
    return r, n, start


def signal_track(picks, R, T, hold, cost=COST):
    """picks: [(e, 열)]. 종목마다 e+1 ~ e+hold 보유(보유 중 다시 실리면 연장). → (일별 수익률, 일별 보유 종목 수, 첫 날 번호)"""
    spans, open_ = [], {}
    for e, c in sorted(picks):
        s, t = e + 1, min(e + hold, T - 1)
        if s > T - 1:
            continue
        cur = open_.get(c)
        if cur and s <= cur[1] + 1:
            cur[1] = max(cur[1], t)
            cur[2] = cur[2] or e + hold > T - 1
        else:
            open_[c] = cur = [s, t, e + hold > T - 1, c]
            spans.append(cur)
    if not spans:
        return np.zeros(T), np.zeros(T, np.int32), None
    cols = sorted({sp[3] for sp in spans})
    pos = {c: j for j, c in enumerate(cols)}
    A = np.zeros((T, len(cols)), bool)
    ent, ext = np.zeros(T), np.zeros(T)
    for s, t, alive, c in spans:
        A[s:t + 1, pos[c]] = True
        ent[s] += 1
        if not alive:
            ext[t] += 1
    n = A.sum(axis=1)
    div = np.maximum(n, MIN_N)
    r = (np.nan_to_num(R[:, cols]).astype(np.float64) * A).sum(axis=1) / div
    r -= cost * (ent + ext) / div
    return r, n.astype(np.int32), min(sp[0] for sp in spans)


def exposure(n, kind):
    """그날 투자한 비율 (0~1)"""
    return np.minimum(n, MIN_N) / MIN_N if kind == 'signal' else (n > 0).astype(float)


def metrics(r, inv, start, bm, months, mi, T):
    """기간별: 수익률, 코스피·코스닥 수익률, 최대 낙폭, 달마다 지수를 이긴 횟수.
    지수는 그날 전략이 투자한 비율(inv)만큼만 센다 — 실적 시즌에만 사는 전략이 쉬는 동안의 지수 등락과 비교되지 않게."""
    out = {}
    for key, length in WINDOWS:
        s = start if length is None else max(start, T - length)
        if s >= T:
            continue
        seg = r[s:]
        nav = np.cumprod(1 + seg)
        peak = np.maximum.accumulate(np.concatenate([[1.0], nav]))[1:]
        m = {'inv': round(float(inv[s:].mean()) * 100), 'ret': round((nav[-1] - 1) * 100, 1), 'mdd': round(float((nav / peak - 1).min()) * 100, 1),
             'days': int(T - s), 'from': months['days'][s]}
        if T - s >= 250:
            m['cagr'] = round((nav[-1] ** (250 / (T - s)) - 1) * 100, 1)
        for b in ('k', 'q'):
            m[b] = round((np.prod(1 + bm[b][s:] * inv[s:]) - 1) * 100, 1)
        # 달마다: 그 달에 이 구간에 든 날만으로 전략·지수 수익률을 견준다
        ms = mi[s:]
        wins = {'k': 0, 'q': 0}
        nm = 0
        for j in np.unique(ms):
            mk = ms == j
            if mk.sum() < 5:
                continue
            nm += 1
            a = np.prod(1 + seg[mk])
            for b in ('k', 'q'):
                wins[b] += int(a > np.prod(1 + (bm[b][s:] * inv[s:])[mk]))
        m.update(nm=nm, wk=wins['k'], wq=wins['q'])
        out[key] = m
    return out


def cumlog(r, start):
    return np.round(np.cumsum(np.log1p(np.clip(r[start:], -0.99, None))) * 1e4).astype(int).tolist()


def build():
    x = load()
    days_all = [str(d) for d in x['days']]
    conn = sqlite3.connect(f'file:{STRAT}?mode=ro', uri=True)
    cidx = {c: i for i, c in enumerate(x['codes'].tolist())}
    name = dict(zip(x['codes'].tolist(), x['names'].tolist()))
    market = dict(zip(x['codes'].tolist(), x['markets'].tolist()))

    docs = conn.execute("""SELECT id, series, date, ts, title, url, n_pick, err FROM doc
                           WHERE parsed_at IS NOT NULL ORDER BY date, COALESCE(ts, date), id""").fetchall()
    picks = {}
    for did, code, nm, side, weight, grp in conn.execute('SELECT doc_id, code, name, side, weight, grp FROM pick'):
        picks.setdefault(did, []).append((code, nm, side, weight, grp))
    first = min((d[2] for d in docs if d[6]), default=None)
    if not first:
        print('추출된 종목이 없음 (collect_strategy.py 먼저)')
        return 1
    g0 = max(bisect.bisect_left(days_all, first) - 1, 1)
    days = days_all[g0:]
    T = len(days)
    R = x['R'][g0:]
    P = x['P'][g0:]
    with np.errstate(invalid='ignore', divide='ignore'):
        idx = x['idx'][:, g0 - 1:]
        bm = {'k': np.nan_to_num(idx[0, 1:] / idx[0, :-1] - 1), 'q': np.nan_to_num(idx[1, 1:] / idx[1, :-1] - 1)}
    mnames = sorted({d[:7] for d in days})
    mpos = {m: i for i, m in enumerate(mnames)}
    mi = np.array([mpos[d[:7]] for d in days])
    ctx = {'days': days}
    lvl = {b: np.concatenate([[1.0], np.cumprod(1 + bm[b])]) for b in bm}     # lvl[i+1] = i일 종가까지의 지수 배수

    def ret_since(col, e, to=None):
        """e일 종가에 사서 to일(기본: 마지막 날) 종가까지. (수익률 %, 코스피 대비 %p, 코스닥 대비 %p)"""
        to = T - 1 if to is None else min(to, T - 1)
        a, b = P[e, col], P[to, col]
        if np.isnan(a) or np.isnan(b) or to <= e:
            return None, None, None
        rr = (b / a - 1) * 100
        return (round(float(rr), 1), round(float(rr - (lvl['k'][to + 1] / lvl['k'][e + 1] - 1) * 100), 1),
                round(float(rr - (lvl['q'][to + 1] / lvl['q'][e + 1] - 1) * 100), 1))

    summary, n_skip = [], 0
    for key, meta in SERIES.items():
        mine = [d for d in docs if d[1] == key]
        sides = ('L', 'S') if key in ('daol_bu', 'daol_aq') else ('L',)
        issues = []          # (e 또는 None, 문서, [(열, 코드, 방향, 비중, 묶음)])
        for d in mine:
            did, _, date, ts, title, url, n_pick, err = d
            if err or (not n_pick and key != 'daol_aq'):
                continue
            rows = []
            for code, nm, side, weight, grp in picks.get(did, []):
                if code in cidx:
                    rows.append((cidx[code], code, side, weight, grp))
                else:
                    n_skip += 1
            issues.append((entry_index(days, date, ts), d, rows))
        if not issues:
            continue
        live = [(e, d, rows) for e, d, rows in issues if e is not None]
        pend = [(d, rows) for e, d, rows in issues if e is None]
        tracks, ev = {}, {}
        for side in sides:
            tracks[side] = {}
            cost = COST if side == 'L' else 0.0      # 피할 종목 묶음은 실제로 사는 것이 아니라 비용을 매기지 않는다
            if meta['kind'] == 'port':
                byday = {}
                for e, d, rows in live:      # 같은 날 두 호가 나오면 뒤의 것
                    byday[e] = {col: (w if w else 1.0) for col, _, s, w, _ in rows if s == side}
                r, n, start = port_track(sorted(byday.items()), R, T, STALE[key], cost)
                runs = {'0': (r, n, start)}
            else:
                pk = [(e, col) for e, d, rows in live for col, _, s, _, _ in rows if s == side]
                runs = {str(h): signal_track(pk, R, T, h, cost) for h in HOLDS}
                ev[side] = {}
                for h in HOLDS:      # 신호 하나하나의 h거래일 뒤 수익률 (같은 종목이 5거래일 안에 또 실리면 한 번으로)
                    seen, rs, xk, xq = {}, [], [], []
                    for e, col in sorted(pk):
                        if col in seen and e - seen[col] <= 5:
                            continue
                        seen[col] = e
                        if e + h <= T - 1:
                            a, b, c = ret_since(col, e, e + h)
                            if a is not None:
                                rs.append(a)
                                xk.append(b)
                                xq.append(c)
                    if rs:
                        ev[side][str(h)] = {'n': len(rs), 'avg': round(float(np.mean(rs)), 1), 'med': round(float(np.median(rs)), 1),
                                            'xk': round(float(np.mean(xk)), 1), 'wk': round(float(np.mean(np.array(xk) > 0)) * 100),
                                            'xq': round(float(np.mean(xq)), 1), 'wq': round(float(np.mean(np.array(xq) > 0)) * 100)}
            for h, (r, n, start) in runs.items():
                if start is None or start >= T:
                    continue
                tracks[side][h] = {'i0': int(start), 'nav': cumlog(r, start), 'n': n[start:].tolist(),
                                   'w': metrics(r, exposure(n, meta['kind']), start, bm, ctx, mi, T), 'now': int(n[-1]),
                                   'avgn': round(float(n[start:].mean()), 1)}
        if not any(tracks[s] for s in sides):
            continue

        # ----- 상세: 지금 보유, 최근 신호, 최근 글 -----
        detail = {'k': key}
        recent = [{'d': d[2], 't': d[4], 'u': d[5], 'n': len(rows), 's': ''.join(sorted({r[2] for r in rows}))}
                  for e, d, rows in issues[-60:]][::-1]
        detail['docs'] = recent
        if meta['kind'] == 'port':
            now = {}
            for side in sides:
                seq = [(e, d, {col: (code, w, g) for col, code, s, w, g in rows if s == side}) for e, d, rows in live]
                if not seq:
                    continue
                e, d, cur = seq[-1]
                stale = T - 1 - e > STALE[key]
                held = []
                for col, (code, w, g) in cur.items():
                    k = len(seq) - 1         # 몇 호 연속으로 들어 있었나 → 처음 들어온 날
                    while k > 0 and col in seq[k - 1][2] and seq[k][0] - seq[k - 1][0] <= STALE[key]:
                        k -= 1
                    e0 = seq[k][0]
                    rr, xk, xq = ret_since(col, e0)
                    held.append({'c': code, 'n': name[code], 'mk': market[code], 'w': w, 'g': g, 'd': days[e0], 'r': rr, 'xk': xk, 'xq': xq})
                prev = seq[-2][2] if len(seq) > 1 else {}
                now[side] = {'as': d[2], 'buy': days[e], 'stale': bool(stale), 'list': sorted(held, key=lambda h: -(h['w'] or 0)),
                             'add': [name[cur[c][0]] for c in cur if c not in prev],
                             'del': [name[prev[c][0]] for c in prev if c not in cur]}
            detail['now'] = now
            if pend:
                d, rows = pend[-1]
                detail['pend'] = {'as': d[2], 't': d[4], 'list': [{'c': code, 'n': name[code], 's': s} for _, code, s, _, _ in rows]}
        else:
            sig = []
            for e, d, rows in issues:
                if e is not None and T - 1 - e > max(HOLDS):
                    continue
                for col, code, s, w, g in rows:
                    rr, xk, xq = ret_since(col, e) if e is not None else (None, None, None)
                    sig.append({'c': code, 'n': name[code], 'mk': market[code], 's': s, 'g': g, 'd': d[2],
                                'b': days[e] if e is not None else None, 'age': None if e is None else T - 1 - e,
                                'r': rr, 'xk': xk, 'xq': xq, 'u': d[5]})
            detail['sig'] = sig[::-1]
        write_json(OUT / f'{key}.json', {'built': datetime.now().isoformat(timespec='seconds'), **detail})

        last = issues[-1][1]
        summary.append({'k': key, **meta, 'sides': list(sides), 'docs': len(issues),
                        'first': issues[0][1][2], 'last': last[2], 'last_t': last[4], 'last_u': last[5],
                        'pend': bool(pend), 'tracks': tracks, 'ev': ev,
                        'src': '네이버 리서치' if last[0].startswith('nv') else '텔레그램 공개 채널'})

    out = {'built': datetime.now().isoformat(timespec='seconds'), 'start': days[0], 'end': days[-1], 'days': days,
           'bm': {b: cumlog(bm[b], 0) for b in bm},
           'holds': list(HOLDS), 'min_n': MIN_N, 'cost': COST * 100, 'stale': STALE, 'cutoff': CUTOFF, 'skipped': n_skip, 'series': summary}
    write_json(OUT / 'summary.json', out)
    for s in summary:
        for side, tr in s['tracks'].items():
            for h, t in tr.items():
                w = t['w'].get('all')
                print(f"  {s['l']:<16} {side} {h:>3}  {w['from']}~  수익 {w['ret']:>7}%  코스피 {w['k']:>6}%  코스닥 {w['q']:>6}%  "
                      f"낙폭 {w['mdd']:>6}%  이긴 달 {w['wk']}/{w['nm']}  지금 {t['now']}종목")
    return 0


if __name__ == '__main__':
    sys.exit(build())
