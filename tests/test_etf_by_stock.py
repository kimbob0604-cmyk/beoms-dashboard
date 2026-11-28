"""build_etf_by_stock — 주식 수 장부(설정·환매 몫 / 리밸런싱 몫) 합성 데이터 시험"""
import unittest

import build_etf_by_stock as b

DAYS = ['2026-11-12', '2026-11-13', '2026-11-16', '2026-11-17']
NAV = 20000.0                     # ETF NAV (원)
CU = 50000                        # 1 CU 좌수
LS = 1_000_000                    # 상장좌수 → 20 CU


def snap_rows(qa, qb, pa=100000.0, pb=50000.0):
    """종목 A(주가 pa) qa 주, 종목 B(주가 pb) qb 주 — 비중은 1 CU 금액(= CU × NAV) 대비"""
    tot = CU * NAV
    return [['000001', qa, qa * pa / tot * 100, qa * pa], ['000002', qb, qb * pb / tot * 100, qb * pb]]


def data(snaps, flows=None):
    n = len(DAYS)
    return {'end': DAYS[-1], 'days': DAYS,
            'etfs': {'999990': {'n': '합성 ETF', 'cl': [1.0] * n, 'ls': [LS] * n, 'nav': [NAV] * n,
                                'na': LS * NAV, 'bi': None, 'f': flows or [None] * n}},
            'hold': {'999990': {'asof': max(snaps), 'w': [[r[0], r[0], r[2]] for r in snaps[max(snaps)]]}},
            'snap': {'999990': snaps}, 'names': {}}


class LedgerTest(unittest.TestCase):
    def test_cu_is_estimated_and_rounded(self):
        x = data({'2026-11-13': snap_rows(5000, 10000)})
        assert b.cu_of(x['snap']['999990'], x['etfs']['999990']['nav'], DAYS, b.prices(x['snap'])) == CU

    def test_rebalance_goes_to_trade_day_before_pdf(self):
        # 11-17 PDF 에서 A 를 100 주 줄이고 B 를 200 주 늘렸다 → 11-16 매매. 좌수 20 CU
        x = data({'2026-11-13': snap_rows(5000, 10000), '2026-11-16': snap_rows(5000, 10000),
                  '2026-11-17': snap_rows(4900, 10200)})
        reb, known, skipped = b.ledger(x)
        assert DAYS[known] == '2026-11-16'
        a = reb['999990']['000001'][DAYS.index('2026-11-16')]
        assert round(a[0]) == -100 * 20 * 100000 and a[1] == 0
        out = b.build(x)['000001']
        i = out['days'].index('2026-11-16')
        assert out['rb'][i] == round(-100 * 20 * 100000 / 1e8, 2)
        assert out['rb'][-1] is None               # 마지막 거래일 리밸런싱은 다음 PDF 가 와야 안다
        assert out['rows'][0][-1][0] == 'CUT'

    def test_gap_is_flagged_and_split_is_skipped(self):
        # 11-13 PDF 없음 → 11-16 PDF 의 차이는 구간 합. B 는 1:2 분할(수량 두 배·주가 반)
        x = data({'2026-11-12': snap_rows(5000, 10000), '2026-11-16': snap_rows(5100, 20000, pb=25000.0)})
        reb, _, skipped = b.ledger(x)
        assert skipped['split'] == 1 and '000002' not in reb['999990']
        assert reb['999990']['000001'][DAYS.index('2026-11-13')][1] == 1

    def test_creation_share_uses_that_days_basket(self):
        flows = [None, 1e9, 1e9, None]
        x = data({'2026-11-13': snap_rows(5000, 10000), '2026-11-16': snap_rows(4000, 10000)}, flows)
        out = b.build(x)['000001']
        w13, w16 = 5000 * 100000 / (CU * NAV), 4000 * 100000 / (CU * NAV)
        assert out['h'][0] == round(1e9 * w13 / 1e8, 2) and out['h'][1] == round(1e9 * w16 / 1e8, 2)


if __name__ == "__main__":
    unittest.main()
