"""
KBJ 컨테이너 안에서 도는 읽기 전용 스크립트 — 날짜별 '종목마다 ETF 순유입 몫'(1일)을 JSON 으로 내보낸다.

build_etf_flow.py 가 `docker exec -i kbj-scheduler-1 python - 날짜...` 로 이 파일을 넘겨 실행한다.
KBJ API(/api/etf/stocks)는 오늘 하루·상위 300종목만 주지만, 같은 계산(readers.etf.etf_stock_flows)을
기준 시각만 바꿔 부르면 지난 날짜·전 종목을 얻는다. 구성 비중은 그날 기준 가장 최근 운용사 PDF.
DB 에 쓰지 않는다. 출력: [{date, meta, stale, rows}] (stdout, 한 줄 JSON). 로그는 stderr.

이 파일은 KBJ 파이썬(kbj 패키지)으로만 돈다 — 대시보드 쪽에서 import 하지 않는다.
"""
import json
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta

STALE_DAYS = 7      # 그날보다 이만큼 오래된 PDF 를 쓴 ETF 는 '비중 오래됨'


def main(days):
    from kbj.config.settings import Settings
    from kbj.services.api.app import create_app
    from kbj.services.api.cache import PgDataVersionSource
    from kbj.services.api.readers.etf import etf_stock_flows
    from kbj.services.runtime.heartbeat import connect_redis
    from kbj.store.db import connect
    from kbj.store.repos import pg_repos

    s = Settings()
    conn = lambda: connect(s, service='api')     # noqa: E731
    app = create_app(s, redis=connect_redis(s.redis_url), repos=pg_repos(conn),
                     data_versions=PgDataVersionSource(conn), static_dir=False)
    read = app.state.kbj.read
    out, seen = [], set()
    for d in days:
        at = datetime.fromisoformat(f'{d}T08:00:00+00:00')      # 그날 17시(KST) — 장 마감 뒤
        ctx = replace(read, now=lambda at=at: at)
        try:
            x = etf_stock_flows(ctx, sort='in', period=1, limit=100000).data
        except Exception as e:      # 그날 ETF·구성종목 자료가 없으면(NoData) 건너뛴다
            print(d, '없음', type(e).__name__, file=sys.stderr)
            continue
        end = x.end.isoformat()
        if end in seen:             # 휴장일은 앞 거래일과 같은 값이 나온다
            continue
        seen.add(end)
        held = ctx.repos.etf.latest_holdings(x.end)
        cut = x.end - timedelta(days=STALE_DAYS)
        stale = {etf: a.isoformat() for etf, (a, _) in held.items() if a is not None and a < cut}
        out.append({
            'date': end,
            'meta': {'coverage': x.coverage_pct, 'n_etfs': x.n_etfs_known, 'n_total': x.n_total,
                     'holdings_asof': x.holdings_asof.isoformat() if x.holdings_asof else None},
            'stale': stale,
            'rows': [[r.code, r.name, r.inflow, r.etf_turnover, r.stock_turnover, r.n_etfs,
                      [[e.code, e.name, e.inflow] for e in r.top_etfs]] for r in x.rows if r.inflow],
        })
        print(end, len(out[-1]['rows']), '종목', file=sys.stderr)
    json.dump(out, sys.stdout, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main(sys.argv[1:])
