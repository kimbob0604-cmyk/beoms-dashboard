import unittest

import numpy as np

import build_strategy as B
import collect_strategy as C
import strategy_parse as P

NAMES = P.NameIndex([
    ('삼성전자', '005930', '2017-01-02', '2026-11-09'), ('SK하이닉스', '000660', '2017-01-02', '2026-11-09'),
    ('LS ELECTRIC', '010120', '2020-04-01', '2026-11-09'), ('CJ', '001040', '2017-01-02', '2026-11-09'),
    ('CJ CGV', '079160', '2017-01-02', '2026-11-09'), ('한화에어로스페이스', '012450', '2018-04-02', '2026-11-09'),
    ('현대중공업', '009540', '2017-01-02', '2019-04-01'), ('HD한국조선해양', '009540', '2023-07-03', '2026-11-09'),
    ('현대중공업', '329180', '2021-10-01', '2023-04-03'), ('HD현대중공업', '329180', '2023-07-03', '2026-11-09'),
    ('LG전자', '066570', '2017-01-02', '2026-11-09'), ('HMM', '011200', '2020-04-01', '2026-11-09'),
    ('코스맥스', '192820', '2017-01-02', '2026-11-09'), ('한전기술', '052690', '2017-01-02', '2026-11-09'),
])
codes = lambda picks: [p['code'] for p in picks]


class NameTest(unittest.TestCase):
    def test_same_name_by_date(self):
        # '현대중공업'은 2019년까지 009540(지금 HD한국조선해양), 2021~2023년에는 329180
        self.assertEqual(NAMES.code('현대중공업', '2018-05-03'), '009540')
        self.assertEqual(NAMES.code('현대중공업', '2022-08-01'), '329180')

    def test_spacing_and_alias(self):
        self.assertEqual(NAMES.code('SK 하이닉스'), '000660')
        self.assertEqual(NAMES.code('하이닉스'), '000660')
        self.assertIsNone(NAMES.code('없는종목'))

    def test_longest_name_first(self):
        self.assertEqual(NAMES.lead('CJ CGV 삼성전자'.split(), 0), ('079160', 2))
        self.assertEqual(NAMES.lead('CJ 삼성전자'.split(), 0), ('001040', 1))


class ParseTest(unittest.TestCase):
    def test_hana_qmp_takes_table_summing_to_100(self):
        rows = ['IT 삼성전자 12,452,573 50.0 27.1 22.9 -1.1 0.3'] + [
            f'산업재 {n} 100,000 5.0 0.3 4.7 0.6 1.5' for n in ('SK하이닉스', 'LS ELECTRIC', 'CJ', 'CJ CGV', 'LG전자', 'HMM',
                                                              '코스맥스', '한전기술', '한화에어로스페이스', 'HD한국조선해양')]
        text = '업종 종목 시총(억원) 비중(%)\n' + '\n'.join(rows) + '\n자료: Quantiwise'
        picks = P.parse_hana_qmp(text, NAMES, '2026-10-28')
        self.assertEqual(len(picks), 11)
        self.assertEqual(picks[0]['weight'], 50.0)
        self.assertEqual(picks[0]['grp'], 'IT')
        self.assertEqual(P.parse_hana_qmp('\n'.join(rows[:3]), NAMES), [])     # 비중 합이 100% 근처가 아니면 표로 보지 않는다

    def test_daishin_top10_stops_before_overseas(self):
        text = ('국내 주식 10선\n티커 종목명\n' + '\n'.join(f'{c} 이름 26.08.10 116.6 51.2' for c in
                ('005930', '000660', '010120', '001040', '066570')) + '\n주: 음영은 신규 편입\n해외 주식 10선\n011200 엉뚱 26.01.01 1.0 1.0')
        self.assertEqual(codes(P.parse_daishin_top10(text, NAMES)), ['005930', '000660', '010120', '001040', '066570'])

    def test_daishin_focus_groups(self):
        text = ('시장 주도 테마 1: 전력설비\n• 설명 줄\n종목 코드 과열 수준 1D(%) 1M(%)\nLS ELECTRIC 010120 -2.1 3.8\n'
                '고배당 유망주\n최근 3 년 내 배당을 늘린 기업:\nHMM, 등\n예상 배당\n종목 코드\n수익률(%)\nHMM 011200 7.9 3,850.1 연간 -27.1\n'
                '없는 999999 1.0 2.0\nCompliance Notice\n삼성전자 005930 1 2')
        picks = P.parse_daishin_focus(text, NAMES)
        self.assertEqual([(p['code'], p['grp']) for p in picks], [('010120', '전력설비'), ('011200', '고배당 유망주')])

    def test_qwer_three_table_shapes(self):
        head = '주간 스크리닝.xlsx\n[8월 4주차] 조건\n종목명 업종 시가총액\n(억원)\n(%)\n'
        row = head + '삼성전자 반도체 10,661,268 218,000\n코스맥스 화장품,의류,\n완구 20,418 135\n자료: 에프앤가이드'
        self.assertEqual(codes(P.parse_yuanta_qwer(row, NAMES)), ['005930', '192820'])
        multi = head + 'CJ CGV LG전자 HMM 미디어 IT가전 운송 8,643 31,545\n자료: 에프앤가이드'
        self.assertEqual(codes(P.parse_yuanta_qwer(multi, NAMES)), ['079160', '066570', '011200'])
        coded = head.replace('종목명 업종', '종목코드 종목명 시장 구분') + 'A000660 SK하이닉스 KS 1,000 2,000\n신규 편입 A011200 HMM 258,310\n자료: FnGuide'
        self.assertEqual(codes(P.parse_yuanta_qwer(coded, NAMES)), ['000660', '011200'])

    def test_qwer_wrapped_name_and_tracking_issue(self):
        text = '주간 스크리닝.xlsx\n[4월 4주차] 조건\n종목명 업종 시가총액\n한화에어\n로스페이스 상사,자본재 212,520 1.55\n자료: x'
        self.assertEqual(codes(P.parse_yuanta_qwer(text, NAMES)), ['012450'])
        track = '3Q25 실적시즌 트래킹.xlsx\n상위 종목코드 종목명\n1 A000660 SK하이닉스 470 551\n자료: x'
        self.assertEqual(P.parse_yuanta_qwer(track, NAMES), [])      # 고른 종목이 아니라 추정치 변화 순위

    def test_daol_bu_formats(self):
        new = '「한전기술」 3Q26 실적발표\n\n11/09 16:33 DART 공시\n☞ 이는 주가 상향 Drift가 발생하는 「LONG」 실적임을 알려드립니다!'
        self.assertEqual(P.tg_series('bu', new), 'daol_bu')
        p = P.parse_daol_bu(new, NAMES, '2026-11-09')[0]
        self.assertEqual((p['code'], p['side'], p['grp']), ('052690', 'L', 'LONG'))
        mid = '[KTB퀀트 김경훈] 1Q21 【LG전자】 실적발표\n◆ 결론\n☞ 이는 주가 하향 Drift가 가장 강하게 발생하는 「CONVICTION SHORT」 실적임을 알려드립니다!'
        self.assertEqual(P.parse_daol_bu(mid, NAMES, '2021-05-14')[0]['side'], 'S')
        old = ('[SK퀀트 김경훈] (현대중공업) Active Quant의 定石: 실적발표 후 70일 전략\n5/3 금일 14:48 공시된 【현대중공업】\n'
               '현재 ②수급레벨(σ)은 「-1 Sigma 이하」수준입니다.\n이는 주가 Drift가 발생하는 『LONG』 실적임을 알려드립니다.')
        self.assertEqual(P.parse_daol_bu(old, NAMES, '2018-05-03')[0]['code'], '009540')      # 그때의 현대중공업
        none = new.replace('「LONG」', '「NO POSITION」')
        self.assertEqual(P.tg_series('bu', none), 'daol_bu')
        self.assertEqual(P.parse_daol_bu(none, NAMES), [])
        self.assertIsNone(P.tg_series('bu', '[DAOL퀀트 김경훈] 3분기 전종목 실적발표 스케줄\n내용'))
        with self.assertRaises(ValueError):
            P.parse_daol_bu(new.replace('한전기술', '없는종목'), NAMES)

    def test_daol_aq_two_columns_per_line(self):
        line = ('6 LG전자 10/7 569 1,952 10,301 7,819 Conviction Short Overvalued Negative Negative Negative '
                '6 HMM 11/13 10,675 8,758 미발표 No Position Undervalued Positive Positive Positive\n'
                '7 삼성전자 10/8 1,250 1,285 1,060 1,074 Long Fair Neutral Neutral Neutral')
        picks = P.parse_daol_aq(line, NAMES)
        self.assertEqual([(p['code'], p['side'], p['grp']) for p in picks],
                         [('066570', 'S', 'Conviction Short'), ('005930', 'L', 'Long')])
        with self.assertRaises(ValueError):
            P.parse_daol_aq('표가 없는 글', NAMES)
        with self.assertRaises(ValueError):      # 표의 절반을 못 읽었으면(양식이 바뀜) 통째로 버린다
            P.parse_daol_aq(line + '\n줄바꿈된 이름 Long Fair\n또 다른 Short Fair\n셋째 Short Overvalued', NAMES)
        self.assertEqual(P.tg_series('td', '[DAOL퀀트 김경훈] Active Quant의 定石 - 11/9\n내용\nhttps://buly.kr/abc'), 'daol_aq')

    def test_naver_series(self):
        self.assertEqual(P.naver_series('하나증권', '[실전 퀀트(Quant MP)] 제목'), 'hana_qmp')
        self.assertEqual(P.naver_series('대신증권', '이번 주 포커 s'), 'daishin_focus')
        self.assertIsNone(P.naver_series('키움증권', '[실전 퀀트] 제목'))

    def test_kst(self):
        self.assertEqual(P.to_kst('2026-11-09T07:37:00+00:00'), '2026-11-09T16:37:00')
        self.assertEqual(P.to_kst('2026-11-09T23:25:00+00:00'), '2026-11-10T08:25:00')

    def test_telegram_page(self):
        page = ('<div class="tgme_widget_message_wrap"><div data-post="ch/12">'
                '<div class="tgme_widget_message_text js-message_text" dir="auto">첫 줄<br/>둘째 &amp; 줄 <a href="https://buly.kr/x">링크</a></div>'
                '<time datetime="2026-11-09T07:37:00+00:00"></time></div>')
        self.assertEqual(C.parse_tg(page), [(12, '2026-11-09T07:37:00+00:00', '첫 줄\n둘째 & 줄 링크', '["https://buly.kr/x"]')])


class TrackTest(unittest.TestCase):
    days = ['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06', '2026-11-09']

    def test_entry_day(self):
        self.assertEqual(B.entry_index(self.days, '2026-11-03'), 2)                               # 네이버: 다음 거래일 종가
        self.assertEqual(B.entry_index(self.days, '2026-11-07'), 5)                               # 주말 글 → 월요일
        self.assertEqual(B.entry_index(self.days, '2026-11-03', '2026-11-03T10:05:00'), 1)        # 텔레그램 장중 → 그날 종가
        self.assertEqual(B.entry_index(self.days, '2026-11-03', '2026-11-03T16:33:00'), 2)        # 장 마감 뒤 → 다음 날
        self.assertIsNone(B.entry_index(self.days, '2026-11-09'))                                 # 아직 살 날이 안 왔다

    def test_port_holds_weights_and_switches(self):
        R = np.zeros((8, 2), np.float32)
        R[2:, 0] = 0.10      # 0번 종목은 매일 +10%
        R[2:, 1] = -0.05
        r, n, start = B.port_track([(1, {0: 3.0, 1: 1.0}), (4, {1: 1.0})], R, 8, 50, cost=0.0)
        self.assertEqual(start, 2)
        self.assertAlmostEqual(r[2], 0.75 * 0.10 + 0.25 * -0.05)
        # 비중을 다시 맞추지 않는다: 둘째 날은 불어난 비중대로
        v0, v1 = 0.75 * 1.1, 0.25 * 0.95
        self.assertAlmostEqual(r[3], (v0 * 1.1 + v1 * 0.95) / (v0 + v1) - 1)
        self.assertAlmostEqual(r[5], -0.05)      # 4일 종가에 1번 종목만으로 교체
        self.assertEqual(n.tolist(), [0, 0, 2, 2, 2, 1, 1, 1])

    def test_port_cost_and_stale(self):
        R = np.zeros((10, 1), np.float32)
        r, n, start = B.port_track([(0, {0: 1.0})], R, 10, 3, cost=0.003)
        self.assertAlmostEqual(r[1], -0.003)     # 살 때
        self.assertAlmostEqual(r[3], -0.003)     # 다음 호가 3거래일 넘게 없어 판다
        self.assertEqual(n.tolist(), [0, 1, 1, 1, 0, 0, 0, 0, 0, 0])
        # 끊긴 뒤 다시 나오면 그 호부터 새로 센다
        r, n, start = B.port_track([(0, {0: 1.0}), (6, {0: 1.0})], R, 10, 3, cost=0.0)
        self.assertEqual(start, 7)

    def test_signal_hold_extend_and_cap(self):
        T = 12
        R = np.full((T, 6), 0.01, np.float32)
        r, n, start = B.signal_track([(0, 0), (2, 0), (1, 1)], R, T, 3, cost=0.0)
        self.assertEqual(start, 1)
        self.assertEqual(n.tolist(), [0, 1, 2, 2, 2, 1, 0, 0, 0, 0, 0, 0])      # 0번은 다시 실려 5일까지, 1번은 4일까지
        self.assertAlmostEqual(r[1], 0.01 / B.MIN_N)                             # 한 종목뿐이면 1/5만 투자
        self.assertAlmostEqual(r[2], 0.02 / B.MIN_N)
        full = [(0, c) for c in range(6)]
        r, n, _ = B.signal_track(full, R, T, 3, cost=0.0)
        self.assertAlmostEqual(r[1], 0.01)                                       # 5개가 넘으면 전액 같은 비중
        self.assertEqual(B.exposure(np.array([0, 2, 5, 9]), 'signal').tolist(), [0, 0.4, 1, 1])
        self.assertEqual(B.exposure(np.array([0, 2]), 'port').tolist(), [0, 1])

    def test_signal_cost(self):
        R = np.zeros((8, 5), np.float32)
        r, n, _ = B.signal_track([(0, c) for c in range(5)], R, 8, 3, cost=0.003)
        self.assertAlmostEqual(r[1], -0.003)     # 다섯 종목을 모두 산 날
        self.assertAlmostEqual(r[3], -0.003)     # 모두 판 날
        r, n, _ = B.signal_track([(6, 0)], R, 8, 3, cost=0.003)
        self.assertAlmostEqual(r[7], -0.003 / B.MIN_N)      # 아직 들고 있으면 파는 비용은 매기지 않는다


class CompositionTest(unittest.TestCase):
    name = {'A': '가', 'B': '나', 'C': '다'}
    doc = lambda self, d: ('id', 'k', d, None, '제목', 'u', 1, None)

    def test_weighted_portfolio_groups_and_changes(self):
        prev = (1, self.doc('2026-09-30'), [(0, 'A', 'L', 60.0, 'IT'), (2, 'C', 'L', 40.0, '금융')])
        cur = (5, self.doc('2026-10-28'), [(0, 'A', 'L', 70.0, 'IT'), (1, 'B', 'L', 30.0, '산업재')])
        c = B.composition('hana_qmp', 'port', [prev, cur], [], '2026-10-01', self.name)
        self.assertEqual(c['groups'], [['IT', 70.0], ['산업재', 30.0]])
        self.assertEqual(c['top'][0], ['가', 70.0])
        self.assertEqual((c['add'], c['del'], c['n']), (['나'], ['다'], 2))

    def test_themes_and_verdict_counts(self):
        cur = (5, self.doc('2026-11-10'), [(0, 'A', 'L', None, '은행'), (1, 'B', 'L', None, '은행'), (2, 'C', 'L', None, '보험')])
        self.assertEqual(B.composition('daishin_focus', 'signal', [cur], [], '2026-10-13', self.name)['blocks'],
                         [['은행', ['가', '나']], ['보험', ['다']]])
        old = (1, self.doc('2026-08-01'), [(0, 'A', 'L', None, 'LONG')])
        new = (5, self.doc('2026-11-05'), [(1, 'B', 'S', None, 'SHORT')])
        mine = [self.doc('2026-08-01'), self.doc('2026-11-05'), self.doc('2026-11-06')]      # 마지막은 판정 없음(NO POSITION)
        c = B.composition('daol_bu', 'signal', [old, new], mine, '2026-10-13', self.name)
        self.assertEqual(c['stats'], {'all': 2, 'L': 0, 'S': 1})
        self.assertEqual((c['names'], c['short']), ([], ['나']))


if __name__ == '__main__':
    unittest.main()
