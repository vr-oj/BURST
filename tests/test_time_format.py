import unittest

from buti_app.utils.time_format import format_elapsed_time


class ElapsedTimeFormattingTests(unittest.TestCase):
    def test_formats_minutes_seconds_and_hundredths(self):
        self.assertEqual(format_elapsed_time(0), "00:00.00")
        self.assertEqual(format_elapsed_time(62.34), "01:02.34")
        self.assertEqual(format_elapsed_time(3723.45), "62:03.45")

    def test_rounding_carries_across_boundaries(self):
        self.assertEqual(format_elapsed_time(59.996), "01:00.00")

    def test_negative_values_are_clamped(self):
        self.assertEqual(format_elapsed_time(-1), "00:00.00")


if __name__ == "__main__":
    unittest.main()

