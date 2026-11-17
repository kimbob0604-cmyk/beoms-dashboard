"""
ETF 기계적 수급 — KBJ 가 내보낸 종목별 ETF 흐름(~/kbj-site/data/etf/stocks*.json) → public/data/etf_flow.json

KBJ(kbj/engines/etf/stock_flows.py)가 ETF 순설정·환매 금액에 운용사 PDF 구성 비중을 곱해 종목마다 더한 값이다.
'순유입 몫' = 설정·환매로 생긴 바스켓 매매 추정(LP·운용사가 실제로 사고판 금액). 주가 움직임 중 펀더멘털이 아닌 부분이 얼마인지 본다.
구성종목을 아는 ETF 만 들어가서(덮은 비율 coverage) 값은 하한이다.

KBJ 는 기간(1·5·20일) × 정렬(순유입·순유출·거래대금 대비)마다 상위 100종목을 따로 내보낸다. 여기서 기간마다 합쳐 한 파일로 만든다.
KBJ 내보내기가 없으면(다른 컴퓨터) 아무것도 하지 않는다.

  python3 build_etf_flow.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = Path.home() / 'kbj-site' / 'data' / 'etf'
OUT = ROOT / 'public' / 'data' / 'etf_flow.json'
PERIODS = (1, 5, 20)
SORTS = ('in', 'out', 'pct')
DEFAULT_PERIOD, DEFAULT_SORT = 5, 'in'           # KBJ 기본값 — 파일 이름에서 빠진다


def src_name(period: int, sort: str) -> str:
    parts = ([f'period-{period}'] if period != DEFAULT_PERIOD else []) + ([f'sort-{sort}'] if sort != DEFAULT_SORT else [])
    return 'stocks' + ('@' + '.'.join(parts) if parts else '') + '.json'


def eok(v):
    return None if v is None else round(v / 1e8, 1)


def row(r: dict) -> dict:
    return {'c': r['code'], 'n': r.get('name'), 'in': eok(r.get('inflow')), 'pct': r.get('inflow_pct'),
            'tp': r.get('turnover_pct'), 'ne': r.get('n_etfs'),
            'top': [[e.get('name') or e['code'], eok(e.get('inflow'))] for e in (r.get('top_etfs') or [])]}


def build(src: Path = SRC):
    out, meta = {}, None
    for p in PERIODS:
        rows, head = {}, None
        for s in SORTS:
            f = src / src_name(p, s)
            if not f.exists():
                continue
            d = json.loads(f.read_text(encoding='utf-8'))
            head = head or d
            for r in d['data']['rows']:
                rows.setdefault(r['code'], row(r))
        if head is None:
            continue
        meta = meta or head
        dd = head['data']
        out[str(p)] = {'start': dd.get('start'), 'end': dd.get('end'), 'coverage': dd.get('coverage_pct'),
                       'n_etfs': dd.get('n_etfs_known'), 'n_total': dd.get('n_total'), 'rows': list(rows.values())}
    if not out:
        return None
    return {'as_of': meta.get('as_of'), 'generated_at': meta.get('generated_at'), 'holdings_asof': meta['data'].get('holdings_asof'),
            'notes': meta.get('notes', []), 'periods': out}


def main() -> int:
    data = build()
    if data is None:
        print(f'KBJ ETF 내보내기가 없습니다 ({SRC}). 건너뜁니다.')
        return 0
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"etf_flow.json: {data['as_of']} · " + ' · '.join(f"{p}일 {len(v['rows'])}종목(덮은 비율 {v['coverage']:.0f}%)" for p, v in data['periods'].items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
