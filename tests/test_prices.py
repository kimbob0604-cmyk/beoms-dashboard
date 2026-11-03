import unittest
from datetime import date, datetime

import collect_prices as P


class ExpectedSessionTest(unittest.TestCase):
    def test_after_close_is_today(self):
        self.assertEqual(P.expected_session(datetime(2026, 11, 3, 18, 40)), date(2026, 11, 3))

    def test_early_morning_is_previous_weekday(self):
        self.assertEqual(P.expected_session(datetime(2026, 11, 4, 7, 10)), date(2026, 11, 3))
        self.assertEqual(P.expected_session(datetime(2026, 11, 9, 7, 10)), date(2026, 11, 6))  # 월요일 → 금요일

    def test_market_hours_is_none(self):
        self.assertIsNone(P.expected_session(datetime(2026, 11, 3, 12, 10)))

    def test_weekend_evening_is_friday(self):
        self.assertEqual(P.expected_session(datetime(2026, 11, 7, 18, 40)), date(2026, 11, 6))


if __name__ == '__main__':
    unittest.main()
