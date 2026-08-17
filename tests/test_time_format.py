import unittest

from buti_app.utils.time_format import format_elapsed_time


class ElapsedTimeFormattingTests(unittest.TestCase):
    def test_formats_hours_minutes_seconds_and_tenths(self):
        self.assertEqual(format_elapsed_time(0), "00:00:00.0")
        self.assertEqual(format_elapsed_time(62.34), "00:01:02.3")
        self.assertEqual(format_elapsed_time(3723.45), "01:02:03.4")

    def test_rounding_carries_across_boundaries(self):
        self.assertEqual(format_elapsed_time(3599.96), "01:00:00.0")

    def test_negative_values_are_clamped(self):
        self.assertEqual(format_elapsed_time(-1), "00:00:00.0")


if __name__ == "__main__":
    unittest.main()

