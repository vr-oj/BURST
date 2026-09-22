import unittest

from buti_app.utils.buti_metadata import ButiMetadataParser


class ButiMetadataParserTests(unittest.TestCase):
    def _parse(self, lines):
        parser = ButiMetadataParser()
        completed = []
        for line in lines:
            result = parser.feed_line(line)
            if result:
                completed.append(result)
        return completed

    def test_parses_complete_v5_2_header(self):
        completed = self._parse(
            [
                "Experiment Type: Constant Velocity",
                "----------------------------------------",
                "Preload = 4.700 mm",
                "Deform = 0.940 mm",
                "Deform = 20 %",
                "# of Steps = 1880",
                "Rate Fwd = 0.100 mm/sec",
                "Rate Rev = 0.250 mm/sec",
                "Cycles = 10",
                "Wire diameter = 0.325 mm",
                "Constant Tension = 125.0 mN",
                "----------------------------------------",
                "Time,Frame,Distance,Cycle,Force",
            ]
        )

        self.assertEqual(
            completed,
            [
                {
                    "experiment_type": "Constant Velocity",
                    "preload_mm": 4.7,
                    "deformation_mm": 0.94,
                    "deformation_percent": 20,
                    "steps": 1880,
                    "rate_forward_mm_s": 0.1,
                    "rate_reverse_mm_s": 0.25,
                    "cycles": 10,
                    "wire_diameter_mm": 0.325,
                    "constant_tension_mn": 125.0,
                }
            ],
        )

    def test_parses_legacy_v4_header_spellings(self):
        completed = self._parse(
            [
                "Stress Relaxation",
                "Preload (mm) = 1.3000",
                "Deform (mm) = 0.2600",
                "Deform (%) = 20",
                "Steps (#) = 520",
                "Rate Fwd (mm/sec) = 0.0250",
                "Rate Rev (mm/sec) = 0.1000",
                "Cycles (#) = 5",
                "Time,Frame,Distance,Cycle,Force",
            ]
        )

        self.assertEqual(completed[0]["experiment_type"], "Stress Relaxation")
        self.assertEqual(completed[0]["preload_mm"], 1.3)
        self.assertEqual(completed[0]["deformation_percent"], 20)
        self.assertEqual(completed[0]["steps"], 520)
        self.assertEqual(completed[0]["cycles"], 5)

    def test_emits_each_header_independently(self):
        parser = ButiMetadataParser()
        for line in (
            "Preload = 1.000 mm",
            "Cycles = 2",
            "Time,Frame,Distance,Cycle,Force",
        ):
            first = parser.feed_line(line)

        for line in (
            "Preload = 2.000 mm",
            "Time,Frame,Distance,Cycle,Force",
        ):
            second = parser.feed_line(line)

        self.assertEqual(first, {"preload_mm": 1.0, "cycles": 2})
        self.assertEqual(second, {"preload_mm": 2.0})

    def test_numeric_sample_is_left_for_existing_csv_parser(self):
        parser = ButiMetadataParser()
        self.assertIsNone(parser.feed_line("0.125,42,1.5,2,8.75"))


if __name__ == "__main__":
    unittest.main()
