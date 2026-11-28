"""
KBJ 컨테이너 안에서 도는 읽기 전용 스크립트 — 'ETF 마다 일별 순설정·환매, 종가, 구성 비중'을 JSON 으로 내보낸다.

build_etf_by_stock.py 가 `docker exec -i kbj-scheduler-1 python - [일수]` 로 이 파일을 넘겨 실행한다.
순유입 = KBJ 원장 계산(kbj.engines.etf.flows — 좌수 변화 × NAV, 분할·결측·검산 실패 날은 빠짐)을 그대로 쓴다.
구성 비중 = 마지막 거래일 기준 ETF 마다 가장 최근 운용사 PDF.
주식 수 장부용 = ETF 마다 일별 상장좌수(ls)·NAV(nav)와 기간 안 운용사 PDF 스냅 전부(snap — 1 CU 당 수량·비중·금액).
DB 에 쓰지 않는다. 출력: {end, days, etfs, hold, snap, names} (stdout, 한 줄 JSON). 로그는 stderr.

이 파일은 KBJ 파이썬(kbj 패키지)으로만 돈다 — 대시보드 쪽에서 import 하지 않는다.
"""
import json
import sys
from datetime import timedelta

BACK = 14       # 기간 첫날에 PDF 가 없는 ETF 를 위해 이만큼(달력일) 앞 스냅까지 받는다


def main(n):
    from kbj.config.settings import Settings
    from kbj.services.api.app import create_app
    from kbj.services.api.cache import PgDataVersionSource
    from kbj.services.api.readers.etf import _window
    from kbj.services.runtime.heartbeat import connect_redis
    from kbj.store.db import connect
    from kbj.store.repos import pg_repos

    s = Settings()
    conn = lambda: connect(s, service='api')     # noqa: E731
    app = create_app(s, redis=connect_redis(s.redis_url), repos=pg_repos(conn),
                     data_versions=PgDataVersionSource(conn), static_dir=False)
    ctx = app.state.kbj.read
    days, flows, meta, tds = _window(ctx, n, ctx.today())
    tds = tds[-(n + 1):]                          # 첫날은 등락률 기준(전일 종가)용
    idx = {d: i for i, d in enumerate(tds)}
    etfs = {}
    for code, rows in days.items():
        m = meta.get(code)
        cl, ls, nav = [None] * len(tds), [None] * len(tds), [None] * len(tds)
        last = None
        for r in rows:
            if r.date in idx:
                i = idx[r.date]
                cl[i], ls[i], nav[i] = r.close, r.list_shrs, r.nav
                last = r
        etfs[code] = {'n': (m.name if m is not None else None) or (last.name if last else None),
                      'cl': cl, 'na': last.net_asset if last else None,
                      'bi': last.base_index if last else None, 'f': [None] * len(tds), 'ls': ls, 'nav': nav}
    for f in flows:
        e = etfs.get(f.code)
        if e is not None and f.date in idx and f.counted:
            e['f'][idx[f.date]] = round(f.net_inflow or 0.0)
    held = ctx.repos.etf.latest_holdings(tds[-1])
    hold = {}
    for etf, (asof, rows) in held.items():
        if etf not in etfs:
            continue
        w = [[c, h.name, float(h.wt)] for c, h in rows.items() if h.wt is not None and h.wt > 0 and c != etf]
        if w:
            hold[etf] = {'asof': asof.isoformat(), 'w': w}
    snap, names = {}, {}
    with conn() as c:
        q = c.execute(
            b"SELECT f.ticker, h.asof, h.code, h.qty, h.wt, h.val, h.name FROM prv_etf.holding h "
            b"JOIN prv_etf.fund f USING (fund_id) WHERE h.asof >= %s AND h.code ~ '^[0-9][0-9A-Z]{5}$' "
            b"AND h.qty IS NOT NULL AND h.qty <> 0",
            (tds[1] - timedelta(days=BACK),))
        for etf, asof, code, qty, wt, val, name in q:
            if etf not in etfs or code == etf:
                continue
            if name:
                names[code] = name
            snap.setdefault(etf, {}).setdefault(asof.isoformat(), []).append(
                [code, float(qty), None if wt is None else round(float(wt), 4), None if val is None else round(float(val))])
    print(f'{tds[-1]} ETF {len(etfs)} · 구성 아는 ETF {len(hold)} · 장부 스냅 ETF {len(snap)}', file=sys.stderr)
    json.dump({'end': tds[-1].isoformat(), 'days': [d.isoformat() for d in tds], 'etfs': etfs, 'hold': hold, 'snap': snap, 'names': names},
              sys.stdout, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
