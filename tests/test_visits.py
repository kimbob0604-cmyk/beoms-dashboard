import sqlite3
import tempfile
import unittest
from pathlib import Path

import build_naver
import build_visits as B
import collect_visits as C
import db
import visit_notes as N
import visits as V

# 시험용 가짜 종목·가짜 글 (실제 회사와 무관)
NAMES = {'가나전자': '111110', '다라중공업': '222220', '대상': '333330', '마바': '444440', 'ABC': '555550',
         '사아바이오': '666660', '옛가나전자': '111110'}
M = V.Matcher(NAMES)

NOTE = """[탐방] 가나전자 (111110) 2분기 탐방 노트
- 올해 매출 가이던스 3,200억, 영업이익 400억 (OPM 12.5%)
- 2공장 증설로 CAPA 1.5배, 내년 하반기 가동
- 주요 고객사는 다라중공업. 수주 잔고 5,000억
잡담: 분위기 좋았음
- 시총 4,000억 수준에서 내년 영업이익 600억 목표"""


class NoteTest(unittest.TestCase):
    def test_is_note(self):
        self.assertTrue(V.is_note(NOTE))
        self.assertFalse(V.is_note('가나전자 탐방 다녀오신 분 계신가요?'))          # 짧은 잡담
        self.assertFalse(V.is_note(NOTE.replace('탐방', '방문')))                  # 키워드 없음
        self.assertFalse(V.is_note('탐방 ' + '가' * 300))                          # 길지만 한 줄

    def test_title_and_key_lines(self):
        self.assertEqual(V.title(NOTE), '[탐방] 가나전자 (111110) 2분기 탐방 노트')
        self.assertEqual(V.clean_line('1) ▶ 2공장 증설'), '2공장 증설')
        lines = V.key_lines(NOTE)
        self.assertEqual(lines[0], '올해 매출 가이던스 3,200억, 영업이익 400억 (OPM 12.5%)')
        self.assertEqual(lines[1], '2공장 증설로 CAPA 1.5배, 내년 하반기 가동')
        self.assertIn('시총 4,000억 수준에서 내년 영업이익 600억 목표', lines)
        self.assertFalse(any('잡담' in ln for ln in lines))                       # 숫자 없는 줄은 빠진다
        self.assertEqual(len(V.key_lines(NOTE, limit=2)), 2)

    def test_dedupe_ignores_spacing_and_marks(self):
        self.assertEqual(V.dedupe_key(NOTE), V.dedupe_key(NOTE.replace('- ', '• ').replace('\n', '\n\n')))
        self.assertNotEqual(V.dedupe_key(NOTE), V.dedupe_key(NOTE.replace('가나전자', '다라중공업')))

    def test_group_dupes_keeps_first_and_lists_rooms(self):
        msgs = [{'text': NOTE, 'date': '2026-11-03T10:00:00', 'chat': '방B'},
                {'text': NOTE, 'date': '2026-11-02T09:00:00', 'chat': '방A'},
                {'text': NOTE.replace('가나전자', '사아바이오'), 'date': '2026-11-04T09:00:00', 'chat': '방A'}]
        out = V.group_dupes(msgs)
        self.assertEqual([m['date'][:10] for m in out], ['2026-11-04', '2026-11-02'])
        self.assertEqual(out[1]['rooms'], ['방A', '방B'])


class KindTest(unittest.TestCase):
    def test_note_vs_mention(self):
        self.assertEqual(V.kind(NOTE), 'note')
        alert = '가나전자(+8.2%)\n- 증권사: 시험증권\n- 투자의견: --\n- 탐방노트: 턴어라운드 시그널(6페이지)\n- 기타'
        self.assertEqual(V.kind(alert), 'mention')
        self.assertEqual(V.keyword_line(alert), '탐방노트: 턴어라운드 시그널(6페이지)')

    def test_title_skips_bare_url(self):
        self.assertEqual(V.title('https://example.com/abc\n가나전자 탐방 정리\n본문'), '가나전자 탐방 정리')
        self.assertEqual(V.title('https://example.com/abc'), 'https://example.com/abc')


class MatchTest(unittest.TestCase):
    def test_primary_is_title_company(self):
        found = M.find(NOTE)
        self.assertEqual(V.primary(found)['c'], '111110')
        self.assertEqual([f['c'] for f in found], ['111110'])      # 다라중공업은 본문에 한 번뿐이라 빠진다

    def test_code_only(self):
        text = 'A222220 탐방\n내용 없음\n끝'
        self.assertEqual(V.primary(M.find(text))['c'], '222220')

    def test_common_word_needs_title_or_code(self):
        body = '오늘 탐방 메모\n둘째 줄\n셋째 줄\n이번 탐방 대상 기업은 비공개. 대상 선정 기준은 실적.'
        self.assertEqual(M.find(body), [])                         # '대상'은 보통 낱말
        self.assertEqual(V.primary(M.find('대상 탐방 후기\n' + body))['c'], '333330')
        self.assertEqual(M.find('탐방 메모\n둘째\n셋째\n마바 얘기, 마바 얘기'), [])   # 두 글자 이름도 제목·코드가 있어야

    def test_not_inside_other_word(self):
        self.assertEqual(M.find('현대상사 탐방\n현대상사 좋음\n끝'), [])            # '대상'이 다른 낱말 속
        self.assertEqual(M.find('ABCD 탐방\nABCD 좋음\n끝'), [])                   # 영문 이름은 뒤 글자도 본다
        self.assertEqual(V.primary(M.find('ABC는 탐방 결과 좋음\n둘\n셋'))['c'], '555550')   # 조사가 붙는 건 괜찮다

    def test_short_name_followed_by_hangul(self):
        self.assertEqual(M.find("'마바광'을 보자 탐방\n마바광 좋다\n끝"), [])           # 마바광 ≠ 마바
        self.assertEqual(V.primary(M.find('마바는 탐방 결과 좋음\n둘\n셋'))['c'], '444440')   # 조사는 괜찮다

    def test_old_name_maps_to_same_code(self):
        self.assertEqual(V.primary(M.find('옛가나전자 탐방\n둘\n셋'))['c'], '111110')

    def test_schedule_post_has_no_primary(self):
        text = '이번 주 탐방 일정: 가나전자, 다라중공업, 사아바이오, ABC\n신청은 댓글\n끝'
        self.assertIsNone(V.primary(M.find(text)))
        self.assertIsNone(V.primary([]))

    def test_body_mentions_tie_has_no_primary(self):
        text = '탐방 메모\n둘째 줄\n셋째 줄\n가나전자 좋다 가나전자 좋다\n사아바이오 좋다 사아바이오 좋다'
        self.assertIsNone(V.primary(M.find(text)))


class ExportTest(unittest.TestCase):
    EXPORT = {'name': '시험방', 'type': 'private_supergroup', 'id': 1234, 'messages': [
        {'id': 1, 'type': 'service', 'date': '2026-11-01T09:00:00', 'text': ''},
        {'id': 2, 'type': 'message', 'date': '2026-11-01T09:01:00', 'from': '홍', 'forwarded_from': '원 채널',
         'text': ['[탐방] ', {'type': 'bold', 'text': '가나전자'}, ' 메모']},
        {'id': 3, 'type': 'message', 'date': '2026-11-01T09:02:00', 'from': '김', 'text': '점심 뭐 먹지'},
    ]}

    def test_parse_export(self):
        rows = C.parse_export(self.EXPORT)
        self.assertEqual([r['id'] for r in rows], [2, 3])
        self.assertEqual(rows[0]['text'], '[탐방] 가나전자 메모')
        self.assertEqual((rows[0]['chat'], rows[0]['fwd'], rows[0]['link']), ('시험방', '원 채널', 'https://t.me/c/1234/2'))
        self.assertEqual(len(C.parse_export({'chats': {'list': [self.EXPORT, self.EXPORT]}})), 4)

    def test_save_keeps_only_keyword_and_updates_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = C.connect(Path(tmp) / 'v.db')
            rows = C.parse_export(self.EXPORT)
            self.assertEqual(C.save(conn, rows), 1)                # '점심' 글은 버린다
            rows[0]['text'] += ' (수정)'
            self.assertEqual(C.save(conn, rows), 0)                # 같은 글은 새로 세지 않고
            self.assertEqual(conn.execute('SELECT text FROM msg').fetchall(), [('[탐방] 가나전자 메모 (수정)',)])   # 본문만 고친다


class SummaryTest(unittest.TestCase):
    def test_pending_and_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = C.connect(Path(tmp) / 'v.db')
            C.save(conn, [{'chat_id': 7, 'id': 1, 'chat': '방', 'date': '2026-11-02T09:00:00', 'text': NOTE},
                          {'chat_id': 7, 'id': 2, 'chat': '방', 'date': '2026-11-02T09:05:00', 'text': '탐방 가실 분?'}])
            path = Path(tmp) / 'notes.json'
            todo = N.pending(conn, {})
            self.assertEqual([t['id'] for t in todo], ['7:1'])     # 잡담은 요약 대상이 아니다
            with self.assertRaises(ValueError):
                N.add(conn, '7:9', '없는 글에는 요약을 달 수 없다. 스무 자를 넘기는 문장.', path)
            with self.assertRaises(ValueError):
                N.add(conn, '7:1', '너무 짧음', path)
            N.add(conn, '7:1', '증설로 내년 생산 능력이 1.5배가 되고, 회사는 내년 영업이익 600억을 목표로 한다.', path)
            self.assertEqual(N.pending(conn, N.load(path)), [])


class BuildTest(unittest.TestCase):
    def test_build_groups_by_company_with_cap_and_por(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            conn = db.connect(tmp / 'd.db')
            conn.executemany('INSERT INTO price_daily (date, code, name, market, close, change_pct, mcap) VALUES (?,?,?,?,?,?,?)', [
                ('2026-11-09', '111110', '가나전자', 'KOSDAQ', 10000, 1.5, 4000),
                ('2026-11-09', '111115', '가나전자우', 'KOSDAQ', 8000, 0.0, 400),      # 우선주는 회사 시총에 더한다
                ('2026-11-09', '222220', '다라중공업', 'KOSPI', 50000, -1.0, 90000)])
            vconn = C.connect(tmp / 'v.db')
            C.save(vconn, [
                {'chat_id': 1, 'id': 10, 'chat': '방A', 'date': '2026-10-02T09:00:00', 'text': NOTE, 'link': 'https://t.me/c/1/10'},
                {'chat_id': 2, 'id': 77, 'chat': '방B', 'date': '2026-10-03T12:00:00', 'text': NOTE, 'fwd': '방A'},
                {'chat_id': 1, 'id': 11, 'chat': '방A', 'date': '2026-10-02T09:01:00', 'text': '탐방 수고하셨습니다'},
                {'chat_id': 1, 'id': 12, 'chat': '방A', 'date': '2026-10-05T09:00:00',
                 'text': '이번 주 탐방 일정 안내\n월요일 오전 10시 집결\n신청은 댓글로 부탁드립니다. ' + '자세한 내용은 공지 참고. ' * 10}])
            hist = sqlite3.connect(':memory:')
            hist.execute('CREATE TABLE hp (date TEXT, code TEXT, mcap REAL)')
            hist.executemany('INSERT INTO hp VALUES (?,?,?)', [('2026-10-01', '111110', 2000), ('2026-10-06', '111110', 3000)])
            pv = {'111110': {'fy0': 2026, 'ops': [[2025, 300, 0], [2026, 400, 1], [2027, 600, 1]]}}
            orig, B.por_base = B.por_base, lambda d: pv
            try:
                out = B.build(conn, vconn, hist, {'1:10': '직접 쓴 요약'}, names=NAMES)
            finally:
                B.por_base = orig
            self.assertEqual((out['n_raw'], out['n_notes'], out['date']), (4, 2, '2026-11-09'))
            self.assertEqual([c['c'] for c in out['cos']], ['111110'])
            co = out['cos'][0]
            self.assertEqual((co['n'], co['mk'], co['mc'], co['fy0']), ('가나전자', 'KOSDAQ', 4400, 2026))
            self.assertEqual(co['ops'][-1], [2027, 600, 1])
            note = co['notes'][0]
            self.assertEqual((note['id'], note['d'], note['rooms'], note['sum']), ('1:10', '2026-10-02', ['방A', '방B'], '직접 쓴 요약'))
            self.assertEqual(note['mc0'], 2200)             # 10/1 보통주 2,000억 × (회사 4,400 ÷ 보통주 4,000)
            self.assertEqual(note['link'], 'https://t.me/c/1/10')
            self.assertEqual((note['k'], note['dm']), ('note', True))   # 방 번호가 양수 = 1:1 대화
            self.assertEqual([n['id'] for n in out['etc']], ['1:12'])       # 종목 없는 일정 공지
            self.assertEqual(out['rooms'][0], ['방A', 2])

    def test_public_view_drops_dm_and_slims_public_channels(self):
        note = lambda i, **kw: {'id': i, 'd': '2026-10-0' + i[-1], 't': '제목', 'rooms': ['방' + i], 'x': '원문', 'lines': ['줄'], 'fwd': '홍길동',
                                'dm': False, 'pub': False, 'sum': None, **kw}
        data = {'cos': [{'c': 'A', 'last': '2026-10-03', 'notes': [note('3', dm=True), note('2', pub=True), note('1')]},
                        {'c': 'B', 'last': '2026-10-04', 'notes': [note('4', dm=True)]}],
                'etc': [note('5', dm=True), note('6', pub=True)], 'rooms': [], 'n_notes': 6, 'n_raw': 9}
        pub = B.public_view(data)
        self.assertEqual([c['c'] for c in pub['cos']], ['A'])                    # 1:1 글만 있던 종목은 빠진다
        a = pub['cos'][0]
        self.assertEqual((a['last'], [n['id'] for n in a['notes']]), ('2026-10-02', ['2', '1']))
        self.assertEqual((a['notes'][0]['x'], a['notes'][0]['lines'], a['notes'][0]['lim']), ('', [], True))   # 공개 채널: 제목·링크만
        self.assertEqual((a['notes'][1]['x'], a['notes'][1]['fwd']), ('원문', None))                            # 비공개 방: 원문 그대로, 전달 출처는 지움
        self.assertEqual([n['id'] for n in pub['etc']], ['6'])
        self.assertEqual((pub['n_notes'], pub['public'], dict(map(tuple, pub['rooms']))), (3, True, {'방2': 1, '방1': 1, '방6': 1}))
        self.assertEqual(len(data['cos'][0]['notes']), 3)                        # 원본은 그대로
        both = {'cos': [{'c': 'A', 'last': 'x', 'notes': [note('1', rooms=['방1', '홍길동'], rp=['방1'])]}], 'etc': [], 'rooms': []}
        n = B.public_view(both)['cos'][0]['notes'][0]
        self.assertEqual((n['rooms'], 'rp' in n), (['방1'], False))             # 같은 글이 1:1 대화에도 있었으면 그 이름은 뺀다

    def test_por_series_from_growth_stock(self):
        s = {'fy0': 2026, 's': {'op': [[2024, 100.0, 0], [2025, 200.0, 0], [2026, 300.0, 1], [2027, None, 1], [2028, 500.0, 1]]}}
        self.assertEqual(build_naver.por_series(s), {'fy0': 2026, 'ops': [[2025, 200.0, 0], [2026, 300.0, 1], [2028, 500.0, 1]]})
        self.assertIsNone(build_naver.por_series({'fy0': 2026, 's': {'op': [[2024, 100.0, 0]]}}))


if __name__ == '__main__':
    unittest.main()
