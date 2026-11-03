"""
이익 성장 탭 데이터 빌드: DB → public/data/growth/{기준일}.json

- 기준일 D 의 KRX 종가·시총 + "컨센 기준일 ≤ D" 인 가장 최근 컨센서스 스냅샷
- 시총은 보통주 + 우선주 합 (POR 등 회사 단위 배수용)
- 필터·정렬·합계는 프론트에서 하고, 여기서는 종목별 계산값만 만든다

CLI
  python3 build_growth.py                    # 가장 최근 가격일
  python3 build_growth.py --date 2026-11-02
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import db
import growth
from universe import is_common

OUT_DIR = Path(__file__).parent / 'public' / 'data' / 'growth'
MIN_COVERAGE = 0.9   # 스냅샷 추정치 보유 종목 수가 역대 최대의 90% 미만이면 덜 받은 것으로 보고 안 씀


def _round(v, nd):
    return None if v is None else round(v, nd)


def pick_snapshot(conn, d: str):
    """
    컨센 기준일이 d 이하인 가장 최근 스냅샷 (as_of, cns_date).
    수집이 중간에 끊긴 스냅샷(추정치 보유 종목 수가 최대치의 MIN_COVERAGE 미만)은 건너뛴다.
    추정치 보유 종목으로 세는 건 평일 수집(--covered-only)이 추정치 없는 종목을 아예 안 받기 때문이다.
    """
    rows = conn.execute(
        """SELECT t.as_of, MAX(t.cns_date) AS cns_date,
                  (SELECT COUNT(DISTINCT a.code) FROM consensus_annual a
                   WHERE a.as_of = t.as_of AND a.is_estimate = 1) AS n_est
           FROM consensus_trend t GROUP BY t.as_of ORDER BY t.as_of DESC""").fetchall()
    best = max((r['n_est'] for r in rows), default=0)
    for r in rows:
        if r['cns_date'] <= d and r['n_est'] >= best * MIN_COVERAGE:
            return r['as_of'], r['cns_date']
    return None, None


def company_mcaps(prices):
    """보통주 코드 → 보통주+우선주 시총 합 (우선주는 앞 5자리가 같고 끝자리≠0)"""
    pref = defaultdict(float)
    for p in prices.values():
        if not is_common(p['code']):
            pref[p['code'][:5]] += p['mcap']
    return {c: p['mcap'] + pref.get(c[:5], 0) for c, p in prices.items() if is_common(c)}


def slim(calc):
    out = {}
    for period, metrics in calc.items():
        out[period] = {}
        for m, v in metrics.items():
            out[period][m] = {
                'b': v['base'], 'n': v['next'],
                'g': _round(v['g'], 4), 'k': v['bucket'],
                'mb': _round(v['mult_base'], 2), 'mn': _round(v['mult_next'], 2),
                'lb': 1 if v['low_base'] else 0,
                'w1': _round(v['rev_w1'], 4), 'm1': _round(v['rev_m1'], 4), 'm3': _round(v['rev_m3'], 4),
            }
            if period == 'y0':  # 올해 추정치 리비전 (y1 의 출발 연도는 y0 의 다음 연도와 같아 중복)
                out[period][m].update({'bw1': _round(v['rev_b_w1'], 4), 'bm1': _round(v['rev_b_m1'], 4),
                                       'bm3': _round(v['rev_b_m3'], 4)})
    return out


def build(conn, d: str) -> dict:
    as_of, cns_date = pick_snapshot(conn, d)
    if not as_of:
        raise SystemExit(f'{d}: 쓸 수 있는 컨센서스 스냅샷 없음')

    prices = {r['code']: dict(r) for r in conn.execute('SELECT * FROM price_daily WHERE date = ?', (d,))}
    if not prices:
        raise SystemExit(f'{d}: 가격 데이터 없음 (collect_prices.py 먼저)')
    mcaps = company_mcaps(prices)
    meta = {r['code']: dict(r) for r in conn.execute('SELECT * FROM stock_meta')}

    annual, trend = defaultdict(list), defaultdict(list)
    for r in conn.execute('SELECT * FROM consensus_annual WHERE as_of = ?', (as_of,)):
        annual[r['code']].append(dict(r))
    for r in conn.execute('SELECT * FROM consensus_trend WHERE as_of = ?', (as_of,)):
        trend[r['code']].append(dict(r))

    as_of_date = date.fromisoformat(d)
    stocks, skipped = [], defaultdict(int)
    for code, rows in annual.items():
        if not any(r['is_estimate'] for r in rows):
            continue
        p = prices.get(code)
        if not p:
            skipped['가격 없음'] += 1
            continue
        res = growth.compute_stock(rows, trend[code], mcaps[code], p['close'], as_of_date)
        if not res:
            skipped['계산 불가'] += 1
            continue
        m = meta.get(code, {})
        stocks.append({
            'c': code, 'n': p['name'], 'mk': p['market'],
            'w': m.get('wics'), 'mc': round(mcaps[code]),
            'p': p['close'], 'ch': p['change_pct'],
            'fy0': res['fy0'], 's': res['series'], 'st': res['streak'],
            'k': slim(res['calc']),
        })

    checked_at = conn.execute("SELECT MAX(fetched_at) FROM collect_log WHERE as_of = ? AND status != 'error'", (as_of,)).fetchone()[0]
    fy0s = [s['fy0'] for s in stocks]
    return {
        'date': d,
        'cns_date': cns_date,
        'checked_at': checked_at,
        'fy0': max(set(fy0s), key=fy0s.count) if fy0s else None,  # 헤더 표기용 (대부분 12월 결산)
        'stocks': stocks,
        '_skipped': dict(skipped),
    }


def write(data: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    skipped = data.pop('_skipped')
    path = OUT_DIR / f"{data['date']}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    dates = sorted((p.stem for p in OUT_DIR.glob('20*.json')), reverse=True)
    (OUT_DIR / 'dates.json').write_text(json.dumps(dates), encoding='utf-8')
    print(f"{path.name}: {len(data['stocks'])}종목, 컨센 {data['cns_date']}, "
          f"{path.stat().st_size / 1024:.0f}KB, 제외 {skipped}")
    return path


def main():
    ap = argparse.ArgumentParser(description='이익 성장 탭 JSON 빌드')
    ap.add_argument('--date', help='YYYY-MM-DD (기본: 가장 최근 가격일)')
    args = ap.parse_args()
    conn = db.connect()
    d = args.date or conn.execute('SELECT MAX(date) FROM price_daily').fetchone()[0]
    if not d:
        sys.exit('가격 데이터 없음')
    write(build(conn, d))


if __name__ == '__main__':
    main()
