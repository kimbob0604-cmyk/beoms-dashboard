import unittest
from datetime import date

import bio_events as be

TODAY = date(2026, 11, 10)


class TestExtractEvents(unittest.TestCase):
    def one(self, text):
        ev = be.extract_events(text, today=TODAY)
        self.assertTrue(ev, text)
        return ev

    def test_pdufa_exact_day(self):
        e = self.one('MOLBREEVI BLA PDUFA Target Action Date Set for November 22, 2026. Other text follows here.')[0]
        self.assertEqual((e['date'], e['precision'], e['kind']), ('2026-11-22', 'day', 'regulatory'))

    def test_calendar_year_topline(self):
        e = self.one('The Company expects to report topline data across potentially registrational trials of IMVT-1402 '
                     'in Graves’ disease (GD) and myasthenia gravis (MG) in calendar year 2027.')[0]
        self.assertEqual((e['date'], e['precision'], e['kind']), ('2027-12-31', 'year', 'readout'))

    def test_quarter_words_and_codes(self):
        e = self.one('Phase 3 ENGAGE target enrollment has been reached, with topline results expected in the first quarter of 2027.')[0]
        self.assertEqual((e['date'], e['precision']), ('2027-03-31', 'quarter'))
        ev = self.one('MOLBREEVI MAAs Under Review by the EMA and the U.K. MHRA; Decisions Expected in Q1 2027 and Q4 2026, respectively.')
        self.assertEqual(sorted(x['date'] for x in ev), ['2026-12-31', '2027-03-31'])
        self.assertTrue(all(x['kind'] == 'regulatory' for x in ev))

    def test_half_year(self):
        e = self.one('The SUMMIT Phase 3 trial was initiated in August, with topline results anticipated in the second half of 2027.')[0]
        self.assertEqual((e['date'], e['precision']), ('2027-12-31', 'half'))
        e = self.one('Topline data from the FOCUS-2 trial are expected in 2H27 according to the company plan.')[0]
        self.assertEqual(e['date'], '2027-12-31')

    def test_past_and_unrelated_ignored(self):
        self.assertEqual(be.extract_events('The PDUFA target action date was August 22, 2026 before the extension.', today=TODAY), [])
        self.assertEqual(be.extract_events('Cash runway extends into the first half of 2028 based on the operating plan.', today=TODAY), [])

    def test_html_to_text(self):
        self.assertEqual(be.html_to_text('<p>A&nbsp;B</p><script>x</script>C'), 'A B. C')


class TestTrialChanges(unittest.TestCase):
    def test_changes(self):
        old = [{'id': 'N1', 'done': '2027-06', 'status': 'RECRUITING', 'title': 't1'},
               {'id': 'N2', 'done': '2027-01', 'status': 'RECRUITING', 'title': 't2'}]
        new = [{'id': 'N1', 'done': '2027-09', 'status': 'RECRUITING', 'title': 't1'},
               {'id': 'N2', 'done': '2027-01', 'status': 'ACTIVE_NOT_RECRUITING', 'title': 't2'},
               {'id': 'N3', 'done': '2028-01', 'status': 'RECRUITING', 'title': 't3'}]
        ch = {c['id']: c for c in be.trial_changes(old, new)}
        self.assertEqual(ch['N1']['change'], '완료 예정일 변경')
        self.assertEqual((ch['N1']['before'], ch['N1']['after']), ('2027-06', '2027-09'))
        self.assertTrue(ch['N2']['change'].startswith('상태 변경'))
        self.assertEqual(ch['N3']['change'], '새 시험')
        self.assertEqual(be.trial_changes([], new), [])   # 첫 실행은 비교 대상이 없어 변경 없음


if __name__ == '__main__':
    unittest.main()
