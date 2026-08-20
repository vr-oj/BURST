import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

app_path = str(Path(__file__).parents[1] / "buti_app")
sys.path.insert(0, app_path)
try:
    from utils.plot_scaling import visible_force_limits
finally:
    sys.path.remove(app_path)

try:
    from PyQt5.QtWidgets import QApplication

    sys.path.insert(0, app_path)
    try:
        from ui.canvas.force_plot_widget import ForcePlotWidget
    finally:
        sys.path.remove(app_path)
except ImportError:
    QApplication = None
    ForcePlotWidget = None


class VisibleForceLimitsTests(unittest.TestCase):
    def test_offscreen_extremes_do_not_affect_limits(self):
        limits = visible_force_limits(
            [0.0, 1.0, 2.0, 3.0, 4.0],
            [-500.0, 10.0, 20.0, 30.0, 600.0],
            1.0,
            3.0,
        )

        self.assertEqual(limits, (8.0, 32.0))

    def test_window_with_no_finite_samples_has_no_limits(self):
        limits = visible_force_limits(
            [0.0, 1.0, 2.0],
            [1.0, float("nan"), 3.0],
            0.5,
            1.5,
        )

        self.assertIsNone(limits)


@unittest.skipIf(
    ForcePlotWidget is None,
    "PyQt5 plotting dependencies are unavailable",
)
class ForcePlotAutoscaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.plot = ForcePlotWidget()
        self.plot.times = [0.0, 1.0, 2.0, 3.0, 4.0]
        self.plot.forces = [-500.0, 10.0, 20.0, 30.0, 600.0]
        self.plot._refresh_line_data()

    def tearDown(self):
        self.plot.close()

    def test_y_autoscale_uses_only_samples_in_visible_x_window(self):
        self.plot.set_manual_x_limits(1.0, 3.0)

        self.plot.set_auto_scale_y(True)

        self.assertEqual(self.plot.manual_xlim, (1.0, 3.0))
        self.assertAlmostEqual(self.plot._primary_axis().get_ylim()[0], 8.0)
        self.assertAlmostEqual(self.plot._primary_axis().get_ylim()[1], 32.0)

    def test_changing_x_window_recalculates_auto_y_immediately(self):
        self.plot.set_manual_x_limits(0.0, 1.0)
        self.plot.set_auto_scale_y(True)

        self.plot.set_manual_x_limits(2.0, 3.0)

        self.assertAlmostEqual(self.plot._primary_axis().get_ylim()[0], 18.0)
        self.assertAlmostEqual(self.plot._primary_axis().get_ylim()[1], 32.0)

    def test_new_offscreen_sample_does_not_expand_visible_auto_y(self):
        self.plot.set_manual_x_limits(1.0, 3.0)
        self.plot.set_auto_scale_y(True)

        self.plot.update_plot(5.0, 50_000.0, 0.0, 0, False, True)

        self.assertEqual(self.plot.manual_xlim, (1.0, 3.0))
        self.assertAlmostEqual(self.plot._primary_axis().get_ylim()[0], 8.0)
        self.assertAlmostEqual(self.plot._primary_axis().get_ylim()[1], 32.0)


if __name__ == "__main__":
    unittest.main()
