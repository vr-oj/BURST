import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
from cameras.ic4_trigger import configure_ic4_trigger
sys.path.pop(0)


class FeatureError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Feature error {code}")


class IC4TriggerTests(unittest.TestCase):
    def setUp(self):
        self.sdk = NS(ErrorCode=NS(GenICamFeatureNotFound=101))
        # Actual DMK 37BUX250 feature layout: no TriggerSource property.
        self.nodes = {"TriggerMode": NS(value="Off"), "TriggerSelector": NS(value="FrameStart"),
                      "TriggerActivation": NS(value="FallingEdge")}
        def enumeration(name):
            if name not in self.nodes:
                raise FeatureError(101)
            return self.nodes[name]
        self.props = NS(find_enumeration=enumeration)

    def test_fixed_input_arms_without_inventing_a_readback_property(self):
        configured, input_info = configure_ic4_trigger(
            self.sdk, self.props, "DMK 37BUX250", "auto")
        self.assertEqual(configured, {"TriggerSelector": "FrameStart",
                                     "TriggerActivation": "RisingEdge", "TriggerMode": "On"})
        self.assertNotIn("TriggerSource", self.nodes)
        self.assertEqual(input_info, {"name": "TRIGGER_IN", "selection": "fixed_by_camera_model"})

    def test_unknown_fixed_input_model_is_not_guessed(self):
        with self.assertRaisesRegex(RuntimeError, "has not been added"):
            configure_ic4_trigger(self.sdk, self.props, "Unknown", "auto")
        self.assertEqual(self.nodes["TriggerMode"].value, "Off")

    def test_fixed_input_does_not_accept_a_different_named_line(self):
        with self.assertRaisesRegex(RuntimeError, "fixed TRIGGER_IN"):
            configure_ic4_trigger(self.sdk, self.props, "DMK 37BUX250", "Line1")
        self.assertEqual(self.nodes["TriggerMode"].value, "Off")

    def test_other_sdk_failures_are_not_treated_as_fixed_input(self):
        def locked(name):
            raise FeatureError(102)
        with self.assertRaises(FeatureError):
            configure_ic4_trigger(self.sdk, NS(find_enumeration=locked), "DMK 37BUX250", "auto")

    def test_fixed_input_still_requires_other_trigger_controls(self):
        del self.nodes["TriggerActivation"]
        with self.assertRaisesRegex(RuntimeError, "Cannot arm"):
            configure_ic4_trigger(self.sdk, self.props, "DMK 37BUX250", "auto")
        self.assertEqual(self.nodes["TriggerMode"].value, "Off")


if __name__ == "__main__":
    unittest.main()
