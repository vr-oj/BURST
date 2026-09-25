import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
from cameras.ic4_recording_rate import IC4RecordingRate
sys.path.pop(0)


class FeatureError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Feature error {code}")


class Node:
    def __init__(self, value, minimum=1.0, maximum=75.0, mode="NONE", increment=None, values=()):
        self._value, self.minimum, self.maximum = value, minimum, maximum
        self.increment_mode = NS(name=mode)
        self._increment, self.valid_value_set = increment, values
        self.writes = []
        self.on_write = lambda value: value

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self.writes.append(value)
        self._value = self.on_write(value)

    @property
    def increment(self):
        if self.increment_mode.name != "INCREMENT":
            raise AssertionError("Continuous properties must not be queried for an increment")
        return self._increment


class Properties:
    def __init__(self, nodes):
        self.nodes = nodes

    def get(self, name):
        if name not in self.nodes:
            raise FeatureError(101)
        return self.nodes[name]

    find_float = find_boolean = find_enumeration = get


class IC4RecordingRateTests(unittest.TestCase):
    def setUp(self):
        self.nodes = {"AcquisitionFrameRate": Node(10.0), "ExposureTime": Node(4480.0),
                      "Gain": Node(0.0), "ExposureAuto": Node("Off"), "GainAuto": Node("Off"),
                      "TriggerOverlap": Node("ReadOut"), "TriggerMode": Node("Off")}
        self.props = Properties(self.nodes)
        self.sdk = NS(ErrorCode=NS(GenICamFeatureNotFound=101))
        self.rate = IC4RecordingRate(self.sdk, self.props)

    def test_no_enable_switch_prepares_75_and_restores_user_preview_rate_for_each_run(self):
        for preview in (10.0, 20.0):
            self.nodes["AcquisitionFrameRate"].value = preview
            self.rate.prepare()
            self.assertEqual(self.nodes["AcquisitionFrameRate"].value, 75.0)
            self.assertEqual(self.nodes["ExposureTime"].value, 4480.0)
            self.assertEqual(self.nodes["Gain"].value, 0.0)
            details = self.rate.readback()
            self.assertEqual(details["preview_frame_rate_fps"], preview)
            self.assertEqual(details["configured_frame_rate_fps"], 75.0)
            self.assertIn("AcquisitionFrameRateEnable", details["unavailable"])
            self.assertEqual(details["readback"]["TriggerOverlap"], "ReadOut")
            self.rate.restore()
            self.assertEqual(self.nodes["AcquisitionFrameRate"].value, preview)
        self.assertEqual(self.nodes["ExposureTime"].writes, [])
        self.assertEqual(self.nodes["Gain"].writes, [])

    def test_supported_limiter_is_disabled_verified_and_restored_without_changing_rate(self):
        for original in (True, False):
            enabled = self.nodes["AcquisitionFrameRateEnable"] = Node(original)
            self.rate.prepare()
            self.assertFalse(enabled.value)
            self.assertEqual(self.rate.details["strategy"], "disable_frame_rate_limit")
            self.rate.restore()
            self.assertEqual(enabled.value, original)
        self.assertEqual(self.nodes["AcquisitionFrameRate"].writes, [])

    def test_failed_limit_disable_blocks_arming_instead_of_silently_continuing(self):
        enabled = self.nodes["AcquisitionFrameRateEnable"] = Node(True)
        enabled.on_write = lambda value: True
        with self.assertRaisesRegex(RuntimeError, "readback.*expected False"):
            self.rate.prepare()
        self.assertEqual(self.nodes["AcquisitionFrameRate"].writes, [])

    def test_long_exposure_limits_selected_rate_without_shortening_exposure(self):
        self.nodes["ExposureTime"]._value = 100000.0
        self.rate.prepare()
        self.assertEqual(self.nodes["AcquisitionFrameRate"].value, 10.0)
        self.assertEqual(self.nodes["ExposureTime"].writes, [])
        self.rate.restore()

    def test_native_maximum_is_not_rounded_and_depends_on_current_format(self):
        for maximum in (75.0, 37.0, 3.2395):
            node = self.nodes["AcquisitionFrameRate"] = Node(2.0, maximum=maximum)
            self.rate.prepare()
            self.assertEqual(node.value, maximum)
            self.rate.restore()
            self.assertEqual(node.value, 2.0)

    def test_discrete_rates_respect_exposure_and_increment(self):
        self.nodes["ExposureTime"]._value = 40000.0  # at most 25 FPS
        for node, expected in ((Node(10., mode="VALUE_SET", values=(5., 10., 20., 30., 75.)), 20.),
                               (Node(10., minimum=1., mode="INCREMENT", increment=3.), 25.)):
            self.nodes["AcquisitionFrameRate"] = node
            self.rate.prepare()
            self.assertEqual(node.value, expected)
            self.rate.restore()

    def test_changed_rate_after_stream_start_is_rejected(self):
        self.rate.prepare()
        self.nodes["AcquisitionFrameRate"]._value = 10.0
        with self.assertRaisesRegex(RuntimeError, "changed while arming"):
            self.rate.verify()
        self.rate.restore()

    def test_exposure_clipping_causes_failure_and_restores_original_values(self):
        node = self.nodes["AcquisitionFrameRate"]
        def write(value):
            if value == 75.0:
                self.nodes["ExposureTime"]._value = 1000.0
            return value
        node.on_write = write
        with self.assertRaisesRegex(RuntimeError, "ExposureTime changed"):
            self.rate.prepare()
        self.assertEqual(node.value, 10.0)
        self.assertEqual(self.nodes["ExposureTime"].value, 4480.0)

    def test_auto_modes_are_preserved_but_auto_values_can_change(self):
        self.nodes["ExposureAuto"]._value = "Continuous"
        self.nodes["GainAuto"]._value = "Continuous"
        self.rate.prepare()
        self.nodes["ExposureTime"]._value = 5000.0
        self.nodes["Gain"]._value = 1.0
        self.rate.verify()
        self.rate.restore()
        self.assertEqual(self.nodes["ExposureTime"].value, 5000.0)
        self.assertEqual(self.nodes["ExposureAuto"].value, "Continuous")

    def test_transport_error_is_not_misidentified_as_absent_enable_switch(self):
        self.props.find_boolean = lambda name: (_ for _ in ()).throw(FeatureError(102))
        with self.assertRaisesRegex(RuntimeError, "Feature error 102"):
            self.rate.prepare()
        self.assertEqual(self.nodes["AcquisitionFrameRate"].writes, [])

    def test_clamped_write_is_rejected_and_rolled_back(self):
        self.nodes["AcquisitionFrameRate"].on_write = lambda value: min(value, 60.0)
        with self.assertRaisesRegex(RuntimeError, "readback"):
            self.rate.prepare()
        self.assertEqual(self.nodes["AcquisitionFrameRate"].value, 10.0)

    def test_absent_rate_controls_and_invalid_limits_block_recording(self):
        del self.nodes["AcquisitionFrameRate"]
        with self.assertRaisesRegex(RuntimeError, "no verifiable frame-rate control"):
            self.rate.prepare()
        for maximum in (float("nan"), float("inf"), -1.0):
            self.nodes["AcquisitionFrameRate"] = Node(10.0, maximum=maximum)
            with self.assertRaisesRegex(RuntimeError, "invalid frame-rate range"):
                self.rate.prepare()

    def test_failed_preview_restore_is_reported_and_can_be_retried(self):
        self.rate.prepare()
        node = self.nodes["AcquisitionFrameRate"]
        node.on_write = lambda value: 75.0
        with self.assertRaisesRegex(RuntimeError, "Could not restore"):
            self.rate.restore()
        node.on_write = lambda value: value
        self.rate.restore()
        self.assertEqual(node.value, 10.0)


if __name__ == "__main__":
    unittest.main()
