import json
import sqlite3
import unittest
from datetime import datetime

import build_docpool as B
import collect_docpool as C
import docpool as D

# 시험용 가짜 종목·가짜 글 (실제 회사·리포트와 무관). 증권사 이름만 실제 표기를 쓴다
NAMES = {D.norm(n): c for n, c in {'가나전자': '111110', '다라중공업': '222220', '삼성증권': '016360', '마바 테크': '333330'}.items()}
CODES = set(NAMES.values())

POST = """[가나전자 / 반도체 장비]
제목: 3Q26 Review: 기대보다 빠른 회복
작성자: 홍길동 팀장, 김철수 Research Associate (삼성증권)
투자의견: BUY
목표주가: 23,000원

[3분기 실적]
· 매출액 2,800억 원, 영업이익 153억 원을 기록하며 컨센서스 상회
· 이 줄은 요약 본문이라 화면·공개 파일에 실리면 안 된다"""
FILE = '가나전자_3Q26_Review_기대보다_빠른_회복_삼성증권_261117.pdf'


def row(i=10, ts='2026-11-17T16:22:07', text=POST, file=FILE):
    return {'id': i, 'ts': ts, 'text': text, 'file': file}


class HeaderTest(unittest.TestCase):
    def test_fields(self):
        h = D.header(POST)
        self.assertEqual(h['topic'], '가나전자 / 반도체 장비')
        self.assertEqual(h['제목'], '3Q26 Review: 기대보다 빠른 회복')          # 제목 안의 ':' 는 그대로
        self.assertEqual(h['투자의견'], 'BUY')
        self.assertEqual(h['목표주가'], '23,000원')
        self.assertNotIn('매출액', json.dumps(h, ensure_ascii=False))          # 빈 줄 뒤 본문은 안 읽는다

    def test_wrapped_title_and_blank_lines(self):
        h = D.header('[디지털 자산 / 산업분석]\n제목: 디지털 자산 Weekly (토큰증권,\n실거래 시장으로)\n작성자: 홍길동 (삼성증권)\n\n\n[소제목]\n· 본문')
        self.assertEqual(h['제목'], '디지털 자산 Weekly (토큰증권, 실거래 시장으로)')
        self.assertEqual(h['작성자'], '홍길동 (삼성증권)')

    def test_keys_with_parenthesis_and_date(self):
        h = D.header('[가나전자 (111110) / 반도체]\n제목: 가\n작성자: 홍길동 (유안타증권)\n작성일: 2026.11.03\n투자의견: NOT RATED\n현재주가 (11/2): 29,600원')
        self.assertEqual(h['작성일'], '2026.11.03')
        self.assertEqual(h['현재주가'], '29,600원')

    def test_no_bracket_and_ads(self):
        self.assertEqual(D.header('제목: 가\n작성자: 나')['topic'], '')
        self.assertTrue(D.is_report(POST))
        self.assertFalse(D.is_report('아몬드 음료, 190ml, 24개\n-48% 할인\n이전가격 : 26,400원'))


class BrokerTest(unittest.TestCase):
    def test_author_forms(self):
        for a, want in [('홍길동 (삼성증권)', '삼성증권'), ('SK증권 홍길동, R.A 김철수', 'SK증권'), ('홍길동 / 상상인증권', '상상인증권'),
                        ('삼성증권 리서치센터', '삼성증권'), ('Gildong Hong (Samsung Securities)', '삼성증권'),
                        ('홍길동 (IM증권)', 'iM증권'), ('홍길동 연구위원 (YUANTA Research)', '유안타증권'),
                        ('홍길동 (NH투자증권 리서치본부)', 'NH투자증권'), ('홍길동 수석연구원 (삼성선물)', '삼성선물'),
                        ('홍길동 (하나금융투자)', '하나증권'), ('홍길동 (가상리서치)', '가상리서치')]:
            self.assertEqual(D.broker_of(a), want, a)

    def test_falls_back_to_file_name(self):
        self.assertEqual(D.broker_of('', '가나전자_제목_하이투자증권_261014.pdf'), 'iM증권')
        self.assertEqual(D.broker_of('가나전자 IR팀', '가나전자_기업설명회IR_개최_20261117.pdf'), '')

    def test_canon_matches_naver_names(self):
        self.assertEqual(D.canon_broker('iM증권'), 'iM증권')
        self.assertEqual(D.canon_broker('한국IR협의회'), '한국IR협의회')
        self.assertEqual(D.canon_broker('모르는곳'), '')


class StockTest(unittest.TestCase):
    def find(self, text, file='', broker='키움증권'):
        return D.stock_of(D.header(text), file, broker, NAMES, CODES)

    def test_topic_name_and_code(self):
        self.assertEqual(self.find('[가나전자 / 반도체]\n제목: 가'), '111110')
        self.assertEqual(self.find('[모르는회사 (222220) / 조선]\n제목: 가'), '222220')       # 코드가 이름보다 먼저
        self.assertEqual(self.find('[마바테크/게임/기업분석]\n제목: 가'), '333330')             # 띄어쓰기 달라도
        self.assertIsNone(self.find('[보험 / 산업분석]\n제목: 분할 매수'))
        self.assertEqual(self.find('[항공운송/가나전자]\n제목: 방한객 역대 최대'), '111110')    # 종목이 뒤 토막에
        self.assertEqual(self.find('[㈜다라중공업/지주회사/기업분석]\n제목: 가'), '222220')

    def test_title_and_file_fallback(self):
        self.assertEqual(self.find('[기업명/산업명/카테고리]\n제목: 다라중공업 (222220): 수혜는 지속'), '222220')
        self.assertEqual(self.find('[기업명/산업명/카테고리]\n제목: 다라중공업: 수혜는 지속'), '222220')
        self.assertEqual(self.find('[Gana Electronics / 반도체]\n제목: 3Q preview', file='가나전자_3Q_preview_키움증권_261103.pdf'), '111110')
        self.assertIsNone(self.find('[한국 CPI / 물가동향]\n제목: (2026. 11. 16.) 근원 상승률', file='한국_CPI_LS증권_261103.pdf'))

    def test_file_name_only_when_topic_is_unusable(self):
        names = {**NAMES, 'sk': '034730', 'ls': '006260'}
        codes = CODES | {'034730', '006260'}
        find = lambda text, file, broker: D.stock_of(D.header(text), file, broker, names, codes)
        # 산업·시황 글: 파일이 증권사 이름 토막이나 대표 종목으로 시작해도 종목 글이 아니다
        self.assertIsNone(find('[화장품 산업/아마존 동향]\n제목: Weekly Check', 'SK_증권_홍길동_화장품_Weekly_SK증권_260916.pdf', 'SK증권'))
        self.assertIsNone(find('[방위산업]\n제목: 조달 방식의 변화', '가나전자_조달_방식의_변화_대신증권_261004.pdf', '대신증권'))
        # 요약 없는 PDF 는 파일 이름뿐이라 첫 토막을 보되, 증권사 이름에 품기는 토막(SK ⊂ SK증권)은 버린다
        self.assertIsNone(find('', 'SK_증권_홍길동_ESG_스냅샷_SK증권_261001.pdf', 'SK증권'))
        self.assertEqual(find('', '가나전자_홍길동_실적_선방_LS증권_261101.pdf', 'LS증권'), '111110')
        self.assertEqual(find('', 'LS_3Q26_Review_키움증권_261101.pdf', '키움증권'), '006260')

    def test_broker_name_is_not_the_stock(self):
        text = '[삼성증권 / METAL FUTURES / 원자재 시황]\n제목: 위험 회피에 하락'
        self.assertIsNone(self.find(text, file='삼성증권_Metal_Futures_삼성선물_261014.pdf', broker='삼성증권'))
        self.assertEqual(self.find('[삼성증권 / 증권]\n제목: 3Q26 Review', broker='키움증권'), '016360')   # 다른 곳이 쓴 삼성증권 리포트


class ParseTest(unittest.TestCase):
    def test_parse_post(self):
        p = D.parse_post(row(), NAMES, CODES)
        self.assertEqual((p['code'], p['broker'], p['op'], p['goal']), ('111110', '삼성증권', '매수', 23000.0))
        self.assertEqual(p['title'], '3Q26 Review: 기대보다 빠른 회복')
        self.assertEqual(p['rdate'], '2026-11-17')
        self.assertEqual(p['link'], 'https://t.me/DOC_POOL/10')

    def test_pdf_without_summary_uses_file_name(self):
        p = D.parse_post(row(text='', file='보험_펀더멘털_격차_심화_구간_신한투자증권_20261116.pdf'), NAMES, CODES)
        self.assertEqual(p['title'], '보험 펀더멘털 격차 심화 구간 신한투자증권')
        self.assertEqual((p['broker'], p['code'], p['rdate']), ('신한투자증권', None, '2026-11-16'))

    def test_dates(self):
        self.assertEqual(D.file_date('a_b_261117.pdf'), '2026-11-17')
        self.assertEqual(D.file_date('a_b_20260812.pdf'), '2026-08-12')
        self.assertIsNone(D.file_date('a_b_삼성증권.pdf'))
        self.assertIsNone(D.file_date('a_b_269917.pdf'))
        self.assertEqual(D.parse_date('2026. 11. 3.'), '2026-11-03')
        h = D.header(POST)
        self.assertEqual(D.report_date(h, 'a_260812.pdf', '2026-08-17T17:36:22'), '2026-08-12')    # 늦게 올라온 글
        self.assertEqual(D.report_date(h, 'a_261231.pdf', '2026-08-17T17:36:22'), '2026-08-17')    # 올라온 날보다 뒤면 안 믿는다
        self.assertEqual(D.report_date({'작성일': '2026.08.14'}, 'a_260812.pdf', '2026-08-17T00:00:00'), '2026-08-14')

    def test_opinion_and_goal(self):
        for s, want in [('BUY', '매수'), ('매수(유지)', '매수'), ('Buy (Maintain)', '매수'), ('비중확대 (유지)', '비중확대'),
                        ('Outperform', '매수'), ('NOT RATED', 'NR'), ('Trading Buy', '매수'), ('', None), (None, None),
                        ('비중확대/유지', '비중확대'), ('적극 매수 유지', '매수'), ('건설업 Overweight 유지', '비중확대'), ('Positive', '비중확대'),
                        ('M.PERFORM', '중립'), ('보유', '중립'), ('Underperform', '매도'), ('★★★★☆', '★★★★☆'),
                        ('가나전자, 다라중공업', None), ("미국 국채 '축소', 한국 국채 '확대'", None)]:
            self.assertEqual(D.opinion_of(s), want, s)
        for s, want in [('23,000원', 23000), ('KRW200,000', 200000), ('820,000원(하향)', 820000),
                        ('180,000원 (기존 230,000원에서 하향)', 180000), ('42,000원 (직전 대비 20.0% 상향, 상승여력 33.5%)', 42000),
                        ('23만원', 230000), ('$250', None), ('N/A', None), ('', None)]:
            self.assertEqual(D.goal_of(s), want, s)


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.p = D.parse_post(row(), NAMES, CODES)
        self.nv = [{'id': 1, 'date': '2026-11-17', 'broker': '삼성증권', 'title': '기대보다 빠른 회복'},
                   {'id': 2, 'date': '2026-11-17', 'broker': '키움증권', 'title': '3Q26 Review: 기대보다 빠른 회복'},
                   {'id': 3, 'date': '2026-11-10', 'broker': '삼성증권', 'title': '3Q26 Review: 기대보다 빠른 회복'}]

    def test_same_broker_same_day(self):
        self.assertEqual(D.match_naver(self.p, self.nv), 1)             # 다른 증권사(2)·일주일 전(3)은 아니다
        self.assertIsNone(D.match_naver(self.p, self.nv[1:]))

    def test_other_day_needs_similar_title(self):
        near = [{'id': 4, 'date': '2026-11-16', 'broker': '삼성증권', 'title': '전혀 다른 이야기'},
                {'id': 5, 'date': '2026-11-15', 'broker': '삼성증권', 'title': '3Q26 Review - 기대보다 빠른 회복'}]
        self.assertEqual(D.match_naver(self.p, near), 5)
        self.assertIsNone(D.match_naver(self.p, near[:1]))

    def test_alias_and_missing_fields(self):
        p = {**self.p, 'broker': 'iM증권'}
        self.assertEqual(D.match_naver(p, [{'id': 6, 'date': '2026-11-17', 'broker': '하이투자증권', 'title': '가'}]), 6)
        self.assertIsNone(D.match_naver({**self.p, 'code': None}, self.nv))
        self.assertIsNone(D.match_naver({**self.p, 'broker': ''}, self.nv))

    def test_title_sim(self):
        self.assertEqual(D.title_sim('가나전자 (111110): 수혜는 지속', '수혜는 지속'), 1.0)
        self.assertLess(D.title_sim('수혜는 지속', '이익 전망 상향'), 0.5)


class DedupeTest(unittest.TestCase):
    def test_same_report_posted_twice(self):
        a = D.parse_post(row(10), NAMES, CODES)
        b = D.parse_post(row(15, ts='2026-11-17T18:00:00', file='가나전자_기대보다_빠른_회복_삼성증권_20261117.pdf'), NAMES, CODES)
        c = D.parse_post(row(20, text=POST.replace('삼성증권', '키움증권')), NAMES, CODES)
        out = D.dedupe([c, b, a])
        self.assertEqual([p['id'] for p in out], [10, 20])
        self.assertEqual(out[0]['dups'], [15])

    def test_nearly_same_title(self):
        a = D.parse_post(row(10, text=POST.replace('기대보다 빠른 회복', '공급계약 코멘트: 기판 마진 부족')), NAMES, CODES)
        b = D.parse_post(row(15, text=POST.replace('기대보다 빠른 회복', '공급계약 코멘트: 기판 마진도 부족')), NAMES, CODES)
        c = D.parse_post(row(20, text=POST.replace('기대보다 빠른 회복', '이익 전망 상향')), NAMES, CODES)
        self.assertEqual([p['id'] for p in D.dedupe([a, b, c])], [10, 20])
        self.assertTrue(D.same_title('가나전자 (111110): 수혜는 지속된다', '수혜는 지속된다'))
        self.assertFalse(D.same_title('Daily', 'Daily Brief 11/17'))            # 짧은 제목은 품는 것만으로 묶지 않는다
        self.assertFalse(D.same_title('', ''))

    def test_template_topic(self):
        self.assertTrue(D.is_template('기업명/산업명/카테고리'))
        self.assertTrue(D.is_template('기업 / 산업 / 카테고리'))
        self.assertFalse(D.is_template('가나전자 / 산업'))
        p = D.parse_post(row(text='[기업/산업/카테고리]\n제목: 가나전자: 수주 코멘트\n작성자: 홍길동 (iM증권)', file=''), NAMES, CODES)
        self.assertEqual((p['topic'], p['code']), ('', '111110'))

    def test_untitled_posts_are_kept(self):
        a = {'id': 1, 'broker': '', 'code': None, 'topic': '', 'title': '', 'rdate': '2026-11-17'}
        self.assertEqual(len(D.dedupe([a, {**a, 'id': 2}])), 2)


class RangeTest(unittest.TestCase):
    def test_first_run_starts_at_edge(self):
        self.assertEqual(D.fetch_ranges(None, None, 203474), [(203474, None)])
        self.assertEqual(D.fetch_ranges(None, None), [(0, None)])

    def test_daily_run_only_after_last(self):
        self.assertEqual(D.fetch_ranges(203474, 251144), [(251144, None)])
        self.assertEqual(D.fetch_ranges(203474, 251144, 230000), [(251144, None)])       # 기준일이 이미 받은 구간 안

    def test_widen_to_the_past(self):
        self.assertEqual(D.fetch_ranges(203474, 251144, 180000), [(180000, 203475), (251144, None)])

    def test_cutoff(self):
        self.assertEqual(D.cutoff_kst(92, datetime(2026, 11, 17, 16, 0)), datetime(2026, 8, 17))


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(C.SCHEMA)

    def raw(self, i, text='', file='', reply_to=None):
        return {'id': i, 'ts': f'2026-11-16T10:35:{i % 60:02d}', 'text': text, 'file': file, 'size': 100 if file else None, 'reply_to': reply_to}

    def test_twice_adds_nothing(self):
        raws = [self.raw(10, POST, FILE), self.raw(11), self.raw(14, POST.replace('가나전자', '다라중공업'), 'b_261116.pdf')]
        self.assertEqual(C.save(self.conn, raws), 2)
        self.assertEqual(C.save(self.conn, raws), 0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM post').fetchone()[0], 2)

    def test_reply_summary_merges_into_pdf_row(self):
        raws = [self.raw(98, POST, reply_to=97), self.raw(97, '', FILE)]      # 답글이 먼저 와도 번호순으로 처리
        self.assertEqual(C.save(self.conn, raws), 1)
        r = self.conn.execute('SELECT * FROM post').fetchone()
        self.assertEqual((r['id'], r['file'], r['text_id']), (97, FILE, 98))
        self.assertIn('제목: 3Q26 Review', r['text'])

    def test_reply_arriving_in_a_later_run(self):
        self.assertEqual(C.save(self.conn, [self.raw(97, '', FILE)]), 1)
        self.assertEqual(C.save(self.conn, [self.raw(98, POST, reply_to=97)]), 0)       # 새 행이 아니라 합쳐진다
        self.assertEqual(self.conn.execute('SELECT text_id FROM post WHERE id = 97').fetchone()[0], 98)

    def test_reply_does_not_overwrite_existing_summary(self):
        C.save(self.conn, [self.raw(38, POST, FILE), self.raw(39, '다른 글\n제목: 나', reply_to=38)])
        r = self.conn.execute('SELECT text, text_id FROM post WHERE id = 38').fetchone()
        self.assertTrue(r['text'].startswith('[가나전자'))
        self.assertIsNone(r['text_id'])

    def test_ads_dropped_text_only_report_kept(self):
        ad = self.raw(52, '아몬드 음료, 190ml, 24개\n-48% 할인')
        self.assertEqual(C.save(self.conn, [ad, self.raw(53, '', reply_to=52), self.raw(60, POST)]), 1)
        self.assertEqual([r[0] for r in self.conn.execute('SELECT id FROM post')], [60])


class BuildTest(unittest.TestCase):
    INFO = {'111110': {'n': '가나전자', 'mk': 'KOSPI', 'mc': 12000, 'p': 20000, 'ch': 1.5, 'w': '반도체', 'pd': '2026-11-17'}}

    def test_day_json_has_list_fields_only(self):
        posts = D.dedupe([D.parse_post(row(10), NAMES, CODES),
                          D.parse_post(row(12, ts='2026-11-17T09:00:00', file='보험_제목_신한투자증권_20261114.pdf',
                                           text='[보험 / 산업분석]\n제목: 분할 매수\n작성자: 홍길동 (신한투자증권)\n투자의견: 비중확대 (유지)\n\n· 본문 요약'),
                                       NAMES, CODES)])
        nv = {'111110': [{'id': 77, 'date': '2026-11-17', 'broker': '삼성증권', 'title': '기대보다 빠른 회복'}]}
        out = B.day_json('2026-11-17', posts, self.INFO, nv)
        self.assertEqual(out['sum'], {'n': 2, 'stock': 1, 'stocks': 1, 'other': 1, 'brokers': 2, 'nv': 1, 'only': 0})
        s = out['stocks'][0]
        self.assertEqual((s['c'], s['n'], s['mc']), ('111110', '가나전자', 12000))
        self.assertNotIn('pd', s)
        self.assertEqual(s['r'][0], {'id': 10, 't': '16:22', 'b': '삼성증권', 'ti': '3Q26 Review: 기대보다 빠른 회복',
                                     'op': '매수', 'g': 23000.0, 'nv': 77})
        self.assertEqual(out['others'][0], {'id': 12, 't': '09:00', 'b': '신한투자증권', 'ti': '분할 매수', 'rd': '2026-11-14',
                                            'op': '비중확대', 'tp': '보험 / 산업분석'})
        text = json.dumps(out, ensure_ascii=False)
        for leak in ('매출액', '본문', '.pdf', '홍길동'):      # 요약 본문·파일 이름·작성자는 싣지 않는다
            self.assertNotIn(leak, text)

    def test_unknown_code_goes_to_others(self):
        p = D.parse_post(row(10), NAMES, CODES)
        out = B.day_json('2026-11-17', [p], {}, {})          # 시세 정보에 없는 종목
        self.assertEqual((len(out['stocks']), len(out['others'])), (0, 1))


if __name__ == '__main__':
    unittest.main()
