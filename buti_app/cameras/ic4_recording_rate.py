"""Separate IC4 preview speed from externally requested image cadence.

Only call from the acquisition worker with acquisition stopped. Some TIS cameras
(including DMK 37BUX250) expose AcquisitionFrameRate without an enable switch;
leaving that sensor-speed control at the preview rate can reject trigger pulses.
"""
import logging
import math

log = logging.getLogger(__name__)


def _optional_node(sdk, props, kind, name):
    try:
        return getattr(props, f"find_{kind}")(name)
    except Exception as exc:
        if getattr(exc, "code", None) == sdk.ErrorCode.GenICamFeatureNotFound:
            return None
        raise


def _same(actual, expected):
    if isinstance(expected, float):
        return math.isclose(float(actual), expected, rel_tol=1e-7, abs_tol=1e-7)
    return actual == expected


def _set_checked(node, value, name):
    if not _same(node.value, value):
        node.value = value
    actual = node.value
    if not _same(actual, value):
        raise RuntimeError(f"{name} readback is {actual!r}, expected {value!r}")


def _highest_rate(node, exposure_us):
    low, high = float(node.minimum), float(node.maximum)
    if not math.isfinite(low) or not math.isfinite(high) or low <= 0 or high < low:
        raise RuntimeError("Camera reported an invalid frame-rate range")
    if exposure_us is not None:
        if not math.isfinite(exposure_us) or exposure_us <= 0:
            raise RuntimeError("Camera reported an invalid exposure time")
        high = min(high, 1_000_000.0 / exposure_us)
    mode = getattr(getattr(node, "increment_mode", None), "name", "NONE")
    if mode == "VALUE_SET":
        values = [float(v) for v in node.valid_value_set if low <= float(v) <= high]
        if not values:
            raise RuntimeError("No camera frame rate preserves the current exposure")
        return max(values)
    if mode == "INCREMENT":
        step = float(node.increment)
        if not math.isfinite(step) or step <= 0:
            raise RuntimeError("Camera reported an invalid frame-rate increment")
        steps = math.floor(math.nextafter((high - low) / step, math.inf))
        high = min(high, low + steps * step)
    if high < low:
        raise RuntimeError("No camera frame rate preserves the current exposure")
    return high


class IC4RecordingRate:
    def __init__(self, sdk, props):
        self.sdk, self.props = sdk, props
        self._restore = []
        self._expected = None
        self._image_settings = []
        self.details = {}

    def _node(self, kind, name):
        return _optional_node(self.sdk, self.props, kind, name)

    def prepare(self):
        if self._expected is not None:
            raise RuntimeError("Camera is already prepared for triggered recording")
        try:
            # Snapshot manual image settings so a rate change cannot silently
            # shorten exposure or alter gain. Automatic modes remain automatic.
            exposure = None
            for name, auto_name in (("ExposureTime", "ExposureAuto"), ("Gain", "GainAuto")):
                node = self._node("float", name)
                auto = self._node("enumeration", auto_name)
                if auto is not None:
                    self._image_settings.append((auto_name, auto, str(auto.value)))
                if node is not None:
                    value = float(node.value)
                    if name == "ExposureTime":
                        exposure = value
                    if auto is None or str(auto.value).lower() == "off":
                        self._image_settings.append((name, node, value))

            enabled = self._node("boolean", "AcquisitionFrameRateEnable")
            rate = self._node("float", "AcquisitionFrameRate")
            self.details = {"preview_frame_rate_fps": float(rate.value) if rate is not None else None}
            if enabled is not None:
                self.details["preview_rate_limit_enabled"] = bool(enabled.value)
                self._restore.append(("AcquisitionFrameRateEnable", enabled, bool(enabled.value)))
                self._expected = ("AcquisitionFrameRateEnable", enabled, False)
                self.details["strategy"] = "disable_frame_rate_limit"
            elif rate is not None:
                self._restore.append(("AcquisitionFrameRate", rate, float(rate.value)))
                self._expected = ("AcquisitionFrameRate", rate, _highest_rate(rate, exposure))
                self.details["strategy"] = "maximum_rate_preserving_exposure"
                self.details["configured_frame_rate_fps"] = self._expected[2]
            else:
                raise RuntimeError("Camera exposes no verifiable frame-rate control for trigger preparation")

            name, node, desired = self._expected
            _set_checked(node, desired, name)
            self.verify()
            log.info("IC4 triggered recording rate prepared: %s", self.details)
        except Exception as exc:
            try:
                self.restore()
            except Exception as restore_exc:
                raise RuntimeError(f"Cannot prepare camera trigger rate: {exc}. Preview restoration also failed: {restore_exc}") from exc
            raise RuntimeError(f"Cannot prepare camera trigger rate: {exc}. BURST has not started the Arduino.") from exc

    def verify(self):
        if self._expected is None:
            return
        name, node, expected = self._expected
        if not _same(node.value, expected):
            raise RuntimeError(f"{name} changed while arming: {node.value!r}, expected {expected!r}")
        for name, node, expected in self._image_settings:
            if not _same(node.value, expected):
                raise RuntimeError(f"Camera {name} changed while preparing triggered recording")

    def readback(self):
        """Record actual timing controls, including explicitly unavailable fields."""
        values, unavailable, errors, units = {}, [], {}, {}
        for kind, names in (
            ("float", ("AcquisitionFrameRate", "ExposureTime", "Gain", "TriggerDelay")),
            ("boolean", ("AcquisitionFrameRateEnable", "IMXLowLatencyTriggerMode")),
            ("enumeration", ("TriggerOverlap", "TriggerMode", "ExposureAuto", "GainAuto")),
        ):
            for name in names:
                try:
                    node = self._node(kind, name)
                    if node is None:
                        unavailable.append(name)
                    else:
                        values[name] = node.value
                        if kind == "float":
                            units[name] = getattr(node, "unit", "")
                except Exception as exc:
                    errors[name] = str(exc)
        return {**self.details, "readback": values, "units": units,
                "unavailable": unavailable, "read_errors": errors}

    def restore(self):
        """Restore the preview control; also undo image changes after failed arming."""
        failures = []
        for name, node, value in reversed(self._restore):
            try:
                _set_checked(node, value, name)
            except Exception as exc:
                failures.append(f"{name}: {exc}")
        for name, node, value in self._image_settings:
            try:
                _set_checked(node, value, name)
            except Exception as exc:
                failures.append(f"{name}: {exc}")
        if failures:
            raise RuntimeError("Could not restore camera preview settings: " + "; ".join(failures))
        self._restore.clear()
        self._image_settings.clear()
        self._expected = None
        self.details = {}
