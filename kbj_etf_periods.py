"""
KBJ 컨테이너 안에서 도는 읽기 전용 스크립트 — 종목별 ETF 수급(1·5·20일 × 순유입·순유출·거래대금 대비)을
KBJ 사이트 내보내기(~/kbj-site/data/etf/stocks*.json)와 같은 모양으로 내보낸다.

KBJ 사이트(com.kbj.site)를 더 굴리지 않기로 해서(2026-11-26) build_etf_flow.py 가 사이트 내보내기 대신 이걸 부른다.
`docker exec -i kbj-scheduler-1 python - 상위개수` . 출력: {"기간:정렬": Envelope JSON} (stdout, 한 줄 JSON). 로그는 stderr.
DB 에 쓰지 않는다. 이 파일은 KBJ 파이썬(kbj 패키지)으로만 돈다 — 대시보드 쪽에서 import 하지 않는다.
"""
import json
import sys

PERIODS = (1, 5, 20)
SORTS = ('in', 'out', 'pct')


def main(limit):
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
    ctx = app.state.kbj.read
    out = {}
    for p in PERIODS:
        for so in SORTS:
            try:
                env = etf_stock_flows(ctx, sort=so, period=p, limit=limit)
            except Exception as e:      # 자료가 없으면(NoData) 건너뛴다
                print(p, so, '없음', type(e).__name__, file=sys.stderr)
                continue
            out[f'{p}:{so}'] = env.model_dump(mode='json')
            print(p, so, len(env.data.rows), '종목', file=sys.stderr)
    json.dump(out, sys.stdout, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
