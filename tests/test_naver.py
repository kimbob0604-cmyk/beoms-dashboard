import json
import unittest
from collections import Counter
from pathlib import Path

import build_naver as B
import keywords as K
from collectors import naver

FIX = Path(__file__).parent / 'fixtures'


def load(name):
    return json.loads((FIX / name).read_text(encoding='utf-8'))


class ParseTest(unittest.TestCase):
    def test_research_list(self):
        rows = naver.parse_research_list(load('naver_research_list.json'))
        self.assertEqual(len(rows), 5)
        self.assertRegex(rows[0]['date'], r'^\d{4}-\d{2}-\d{2}$')
        self.assertIsInstance(rows[0]['id'], int)

    def test_research_detail(self):
        d = naver.parse_research_detail(load('naver_research_97383.json'))
        self.assertEqual(d['code'], '005930')
        self.assertEqual(d['goal'], 400000)
        self.assertEqual(d['heads'], ['환율 부담에도 분기 영업이익 100조원 돌파'])
        self.assertNotIn('<', d['body'])
        self.assertTrue(d['body'].startswith('동사에 대한 목표주가를 40만원으로 유지한다.'))

    def test_flow(self):
        rows = naver.parse_flow(load('naver_flow_005930.json'), '005930')
        self.assertEqual(rows[0]['date'], '2026-11-02')
        self.assertEqual(rows[0]['frgn'], 515900)
        self.assertEqual(rows[0]['close'], 229000)   # 정규장 종가
        self.assertEqual(rows[0]['frgn_ratio'], 46.16)

    def test_high52_drops_etn(self):
        res = naver.parse_high52(load('naver_high52_kospi.json'), 'KOSPI')
        self.assertTrue(all(r['code'] != '520106' for r in res['rows']))
        self.assertEqual(res['rows'][0]['close'], 20700)
        self.assertGreater(res['total'], 0)


class FlowTest(unittest.TestCase):
    def test_streak(self):
        self.assertEqual(B.streak([5, 3, 1, -2, 4]), 3)
        self.assertEqual(B.streak([-1, -1, 2]), -2)
        self.assertEqual(B.streak([0, 5]), 0)
        self.assertEqual(B.streak([]), 0)

    def test_summarize(self):
        rows = [{'frgn': 1000, 'org': -1000, 'ind': 0, 'close': 10000, 'frgn_ratio': 10.0 + i * 0.1}
                for i in range(25)]
        s = B.summarize_flow(rows)
        self.assertEqual(s['f1'], 0.1)        # 1,000주 × 1만원 = 0.1억
        self.assertEqual(s['f5'], 0.5)
        self.assertIsNone(s['f60'])           # 60일치가 없으면 비움
        self.assertEqual(s['fs'], 25)
        self.assertEqual(s['os'], -25)
        self.assertEqual(s['frd'], -2.0)      # 최신 10.0 − 20일 전 12.0

    def test_prev_goals_same_broker(self):
        reps = [{'id': 1, 'code': 'A', 'broker': 'X', 'goal': 100},
                {'id': 2, 'code': 'A', 'broker': 'Y', 'goal': 150},
                {'id': 3, 'code': 'A', 'broker': 'X', 'goal': None},
                {'id': 4, 'code': 'A', 'broker': 'X', 'goal': 120}]
        self.assertEqual(B.prev_goals(reps), {1: None, 2: None, 3: 100, 4: 100})

    def test_opinion(self):
        self.assertEqual(B.opinion('Buy'), '매수')
        self.assertEqual(B.opinion('Strong Buy'), '매수')
        self.assertEqual(B.opinion('MarketPerform'), '중립')
        self.assertIsNone(B.opinion('없음'))


class KeywordTest(unittest.TestCase):
    def test_normalize_josa_only_when_stem_seen(self):
        vocab = Counter({'수요': 3, '수요가': 1, '디스플레이': 2})
        self.assertEqual(K.normalize('수요가', vocab), '수요')
        self.assertEqual(K.normalize('디스플레이', vocab), '디스플레이')
        self.assertEqual(K.normalize('증가', vocab), '증가')         # '증' 은 한 글자라 안 뗌
        self.assertEqual(K.normalize('메모리에서', vocab), '메모리')  # 두 글자 조사는 그냥 뗌

    def test_keep(self):
        self.assertFalse(K.keep('3Q26'))
        self.assertFalse(K.keep('4Q26F'))
        self.assertFalse(K.keep('YoY'))
        self.assertFalse(K.keep('영업이익'))
        self.assertTrue(K.keep('HBM4'))
        self.assertTrue(K.keep('재고'))

    def test_stock_keywords_prefers_specific_terms(self):
        others = [{'id': 10 + i, 'date': '2026-10-01', 'broker': 'Z', 'text': '실적 개선 수주 확대. 수주가 늘었다.'}
                  for i in range(20)]
        mine = [{'id': 1, 'date': '2026-10-30', 'broker': 'A', 'text': 'HBM4 출하 본격화로 수주 확대. 메모리 가격 상승.'},
                {'id': 2, 'date': '2026-10-29', 'broker': 'B', 'text': 'HBM4 비중 확대가 이어진다. 메모리 강세.'},
                {'id': 3, 'date': '2026-10-28', 'broker': 'C', 'text': '수주 증가와 HBM4 판매 호조.'}]
        docs = mine + others
        vocab = K.build_vocab(d['text'] for d in docs)
        df = K.doc_freq(K.doc_terms(d['text'], vocab) for d in docs)
        kws = K.stock_keywords(mine, df, len(docs), vocab, name='테스트')
        self.assertEqual(kws[0]['kw'], 'HBM4')
        self.assertEqual(kws[0]['n'], 3)
        self.assertEqual(kws[0]['hits'][0]['broker'], 'A')   # 최신 리포트 문장 먼저
        self.assertIn('메모리', [k['kw'] for k in kws])

    def test_name_excluded(self):
        docs = [{'id': i, 'date': '2026-10-30', 'broker': 'A', 'text': 'SK하이닉스 HBM 출하. SK 그룹.'} for i in range(3)]
        vocab = K.build_vocab(d['text'] for d in docs)
        df = K.doc_freq(K.doc_terms(d['text'], vocab) for d in docs)
        kws = [k['kw'] for k in K.stock_keywords(docs, df, 10, vocab, name='SK하이닉스')]
        self.assertNotIn('SK', kws)
        self.assertIn('HBM', kws)


if __name__ == '__main__':
    unittest.main()
