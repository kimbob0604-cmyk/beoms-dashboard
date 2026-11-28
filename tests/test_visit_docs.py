import tempfile
import unittest
from pathlib import Path

import build_visits as B
import collect_visits as C
import db
import visit_docs as D
import visits as V

R = 520   # 오른쪽 여백


def ln(t, x1=R, **kw):
    return {'t': t, 'x1': x1, **kw}


class JoinTest(unittest.TestCase):
    def test_wrapped_line_joins_but_bullets_and_questions_do_not(self):
        lines = [ln('Q. 내년 가이던스는?'),                                   # 물음표로 끝난 줄 뒤는 새 줄
                 ln('- 매출 4,100억원, 영업이익 800억원 초중반. 추가 인상분은'),   # 여백까지 찬 줄 → 다음 줄과 잇는다
                 ln('반영하지 않은 수치', x1=200),
                 ln('- 캐파는 내년 2조원', x1=300),
                 ln('다음 문단', x1=300)]                                     # 앞줄이 짧으면(문단 끝) 잇지 않는다
        self.assertEqual(D.join_lines(lines, R), [
            'Q. 내년 가이던스는?', '- 매출 4,100억원, 영업이익 800억원 초중반. 추가 인상분은 반영하지 않은 수치',
            '- 캐파는 내년 2조원', '다음 문단'])

    def test_word_wrap_gap_and_sentence_end(self):
        # 낱말 단위 줄바꿈이라 이어지는 줄도 오른쪽이 비어 있다: 40pt 안쪽이면 잇고, 62pt 안쪽은 문장이 안 끝났을 때만
        self.assertEqual(D.join_lines([ln('현재', x1=R - 45), ln('유상증자는 검토 안 함')], R), ['현재 유상증자는 검토 안 함'])
        self.assertEqual(D.join_lines([ln('이익률은 약 13%다.', x1=R - 50), ln('4분기 전망은')], R), ['이익률은 약 13%다.', '4분기 전망은'])
        self.assertEqual(D.join_lines([ln('있는 셈.', x1=R - 20), ln('다음 문장')], R), ['있는 셈. 다음 문장'])

    def test_bold_start_is_new_paragraph_unless_bold_continues(self):
        lines = [ln('설명이 이어지는 단계임.'), ln('북미 빅테크향이 핵심 과제. 본문', b0=True),
                 ln('굵은 문장이 두 줄로', b0=True, ball=True), ln('넘어간 경우. 본문', b0=True)]
        self.assertEqual(D.join_lines(lines, R), ['설명이 이어지는 단계임.', '북미 빅테크향이 핵심 과제. 본문',
                                                  '굵은 문장이 두 줄로 넘어간 경우. 본문'])

    def test_table_and_heading_lines_stand_alone(self):
        lines = [ln('본문 줄'), ln('[표] 시점 | 이벤트', tbl=True), ln('2027년 | 출시', tbl=True), ln('셀트리온', hd=True)]
        self.assertEqual(D.join_lines(lines, R), ['본문 줄', '[표] 시점 | 이벤트', '2027년 | 출시', '셀트리온'])


class SplitTest(unittest.TestCase):
    def test_analyst_line_in_any_order(self):
        self.assertEqual(D.parse_analyst('iM증권 고의영 반도체/전기전자 (2122-9179)'), {'who': '고의영', 'sector': '반도체/전기전자'})
        self.assertEqual(D.parse_analyst('iM증권 이차전지/디스플레이 정원석(2122-9203)'), {'who': '정원석', 'sector': '이차전지/디스플레이'})
        self.assertEqual(D.parse_analyst('iM 증권 신희철 통신/스몰캡 2122-9187'), {'who': '신희철', 'sector': '통신/스몰캡'})
        self.assertIsNone(D.parse_analyst('- 매출 4,100억원'))

    def test_toc_and_split(self):
        toc = 'iM증권 Corporate Day\n목차\n01  가나전자 ..........  \n02  다라 중공업.......... \n'
        names = D.toc_names(toc)
        self.assertEqual(names, ['가나전자', '다라 중공업'])
        lines = ['가나전자', 'iM증권 홍길동 반도체/전기전자 (2122-0000)', 'Q. 질문?', '- 답', '본문에 가나전자 언급',
                 '다라중공업', 'iM증권 조선/방산 김철수 (2122-0001)', '- 수주 9조']
        cos = D.split_companies(lines, names)
        self.assertEqual([(c['name'], c['who'], c['lines']) for c in cos], [
            ('가나전자', '홍길동', ['Q. 질문?', '- 답', '본문에 가나전자 언급']),       # 애널리스트 줄이 뒤따라야 회사 시작
            ('다라 중공업', '김철수', ['- 수주 9조'])])                                # 띄어쓰기가 달라도 같은 회사

    def test_match_code_and_fixes(self):
        names = {'가나전자': '111110', 'LG이노텍': '011070', '에스엠': '041510'}
        self.assertEqual(D.match_code('LG 이노텍', names), '011070')
        self.assertEqual(D.match_code('SM엔터테인먼트', names, {'SM엔터테인먼트': '041510'}), '041510')
        self.assertIsNone(D.match_code('없는회사', names))
        fixes = [{'from': '39월', 'to': '3~9월', 'why': '물결표 빠짐'}]
        self.assertEqual(D.apply_fixes('적자는 39월 정산분', fixes), '적자는 3~9월 정산분')


class BuildWithDocsTest(unittest.TestCase):
    def test_doc_notes_join_company_cards_and_public_view_keeps_summary_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            conn = db.connect(tmp / 'd.db')
            conn.executemany('INSERT INTO price_daily (date, code, name, market, close, change_pct, mcap) VALUES (?,?,?,?,?,?,?)', [
                ('2026-11-19', '111110', '가나전자', 'KOSDAQ', 9000, 0, 3600),
                ('2026-11-20', '111110', '가나전자', 'KOSDAQ', 9500, 0, 3800),
                ('2026-11-26', '111110', '가나전자', 'KOSDAQ', 10000, 1.5, 4000)])
            vconn = C.connect(tmp / 'v.db')
            C.save(vconn, [{'chat_id': -1, 'id': 10, 'chat': '방A', 'date': '2026-11-25T09:00:00',
                            'text': '[탐방] 가나전자 탐방 노트\n- 올해 매출 3,200억 가이던스\n- 2공장 증설 CAPA 1.5배\n' + '메모 ' * 40}])
            hist = __import__('sqlite3').connect(':memory:')
            hist.execute('CREATE TABLE hp (date TEXT, code TEXT, mcap REAL)')
            hist.execute("INSERT INTO hp VALUES ('2026-11-19', '111110', 3600)")     # 과거 DB 에 11/20 이 빠져 있어도
            docs = [{'id': 'xcd', 'date': '2026-11-20', 'source': '가상증권 Corporate Day', 'file': 'x.pdf', 'cos': [
                {'no': 1, 'name': '가나전자', 'code': '111110', 'who': '홍길동', 'sector': '반도체',
                 'text': 'Q. 4Q 가이던스는?\n- 매출 4,100억원, 영업이익 800억원 예상', 'sum': '4Q 매출 4,100억원 가이던스.'},
                {'no': 2, 'name': '상장안된회사', 'code': None, 'who': '', 'sector': '', 'text': '본문', 'sum': None}]}]
            orig, B.por_base = B.por_base, lambda d: {}
            try:
                out = B.build(conn, vconn, hist, {}, names={'가나전자': '111110'}, docs=docs)
            finally:
                B.por_base = orig
            self.assertEqual((out['n_notes'], out['n_docs']), (3, 2))
            co = out['cos'][0]
            self.assertEqual([n['id'] for n in co['notes']], ['-1:10', 'doc:xcd:1'])     # 날짜 최신순으로 섞인다
            dn = co['notes'][1]
            self.assertEqual((dn['src'], dn['rooms'], dn['sum'], dn['tm']), ('doc', ['가상증권 Corporate Day'], '4Q 매출 4,100억원 가이던스.', ''))
            self.assertEqual(dn['mc0'], 3800)                                            # 가격 DB 의 그날 값 (과거 DB 의 전날 값이 아니라)
            self.assertEqual(dn['lines'], ['매출 4,100억원, 영업이익 800억원 예상'])        # 질문 줄은 빠진다
            self.assertEqual([n['id'] for n in out['etc']], ['doc:xcd:2'])                # 종목 코드가 없으면 '기타'
            self.assertIn(['가상증권 Corporate Day', 2], out['rooms'])
            pub = B.public_view(out)['cos'][0]['notes'][1]
            self.assertEqual((pub['x'], pub['lines'], pub['lim'], pub['sum']), ('', [], True, '4Q 매출 4,100억원 가이던스.'))


if __name__ == '__main__':
    unittest.main()
