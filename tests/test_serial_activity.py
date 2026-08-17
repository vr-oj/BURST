import unittest

from buti_app.utils.serial_activity import SerialActivityTracker


class SerialActivityTrackerTests(unittest.TestCase):
    def test_emits_one_boundary_for_each_run(self):
        tracker = SerialActivityTracker()
        self.assertTrue(tracker.note_packet(0.0))
        self.assertFalse(tracker.note_packet(0.1))
        self.assertFalse(tracker.note_packet(0.2))
        self.assertFalse(tracker.poll(2.19))
        self.assertTrue(tracker.poll(2.21))
        self.assertFalse(tracker.poll(20.0))
        self.assertTrue(tracker.note_packet(21.0))

    def test_initial_guard_covers_a_five_second_packet_interval(self):
        tracker = SerialActivityTracker()
        tracker.note_packet(0.0)
        self.assertFalse(tracker.poll(6.4))
        tracker.note_packet(5.0)
        self.assertFalse(tracker.poll(11.4))
        self.assertTrue(tracker.poll(11.6))

    def test_learned_slow_cadence_retains_headroom(self):
        tracker = SerialActivityTracker()
        tracker.note_packet(0.0)
        tracker.note_packet(5.0)
        tracker.note_packet(10.0)
        self.assertEqual(tracker.timeout_seconds, 7.5)
        self.assertFalse(tracker.poll(17.4))
        self.assertTrue(tracker.poll(17.6))

    def test_timeout_is_capped(self):
        tracker = SerialActivityTracker()
        tracker.note_packet(0.0)
        tracker.note_packet(9.0)
        tracker.note_packet(18.0)
        self.assertEqual(tracker.timeout_seconds, 10.0)


if __name__ == "__main__":
    unittest.main()

