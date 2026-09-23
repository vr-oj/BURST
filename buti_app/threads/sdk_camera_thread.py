# File: buti_app/threads/sdk_camera_thread.py

import logging

try:
    import imagingcontrol4 as ic4  # type: ignore
except Exception:  # Optional SDK may be installed with missing runtime DLLs
    ic4 = None

import numpy as np
from cameras.frame_data import FrameData
from cameras.trigger import verify_external_trigger
from cameras.ic4_trigger import configure_ic4_trigger
from cameras.timing_thread import TimingCameraThread

from utils.config import DEFAULT_FPS
from cameras.controls import CameraController, IC4Controls
from cameras.ic4_backend import reset_offsets

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(TimingCameraThread):
    """
    Opens the camera (using the DeviceInfo + resolution passed in via set_* methods),
    then starts a QueueSink-based stream. Each new frame is emitted as a QImage via
    frame_ready(QImage, buffer). When stop() is called, stops streaming and closes the device.
    """

    # Emitted once the grabber is open (but before streaming starts).
    grabber_ready = pyqtSignal()

    # Emitted for each new frame: (QImage, raw_buffer_object)
    frame_ready = pyqtSignal(QImage, object)

    # Emitted on error: (message, code_as_string)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        if ic4 is None:
            raise RuntimeError("imagingcontrol4 is not available on this system.")
        self.controller = CameraController()
        self.grabber = None
        self._stop_requested = False

        # Will be set by MainWindow before start():
        self._device_info = None  # an ic4.DeviceInfo instance
        self._resolution = None  # tuple (width, height, pixel_format_name)

        # Keep a reference to the sink so we can stop it later
        self._sink = None
        self._accept_frames = True

    def set_device_info(self, dev_info):
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple):
        # resolution_tuple is (w, h, pf_name), e.g. (2448, 2048, "Mono8")
        self._resolution = resolution_tuple

    def _configure_trigger(self, props, source):
        configured, self.trigger_input = configure_ic4_trigger(
            ic4, props, self._device_info.model_name, source)
        return configured

    def run(self):
        try:
            # ─── Initialize IC4 (with “already called” catch) ─────────────────
            try:
                ic4.Library.init(
                    api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
                )
                log.info("SDKCameraThread: Library.init() succeeded.")
            except RuntimeError as e:
                if "already called" in str(e):
                    log.info("SDKCameraThread: IC4 already initialized; continuing.")
                else:
                    raise

            # ─── Verify device_info was set ────────────────────────────────────
            if self._device_info is None:
                raise RuntimeError("No DeviceInfo passed to SDKCameraThread.")

            # ─── Open the grabber ───────────────────────────────────────────────
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)
            log.info(
                f"SDKCameraThread: device_open() succeeded for "
                f"'{self._device_info.model_name}' (S/N '{self._device_info.serial}')."
            )

            # ─── Apply PixelFormat & resolution ────────────────────────────────

            # ─── DEBUG: Log all available float properties ────────────────────
            log.debug("Available float properties:")
            for p in self.grabber.device_property_map:
                try:
                    val = p.get_value()
                    log.debug(f"{p.identifier} = {val}")
                except Exception:
                    pass

            # ─── Set Default Camera Properties BEFORE Streaming ───────────────
            props = self.grabber.device_property_map
            try:
                exp_prop = props.find_float("ExposureTime")
                exp_prop.value = 10000.0  # Default to 10ms
                log.info("Set ExposureTime to 10000 µs")
            except Exception as e:
                log.warning(f"Could not set ExposureTime: {e}")
            try:
                gain_prop = props.find_float("Gain")
                gain_prop.value = 5.0
                log.info("Set Gain to 5.0")
            except Exception as e:
                log.warning(f"Could not set Gain: {e}")
            try:
                fr_node = props.find_float("AcquisitionFrameRate")
                if fr_node:
                    fr_node.value = float(DEFAULT_FPS)
                    log.info(
                        f"SDKCameraThread: Set AcquisitionFrameRate = {DEFAULT_FPS}"
                    )
            except Exception as e:
                log.warning(
                    f"SDKCameraThread: Could not set AcquisitionFrameRate: {e}"
                )

            if self._resolution is not None:
                w, h, pf_name = self._resolution
                try:
                    pf_node = self.grabber.device_property_map.find_enumeration(
                        "PixelFormat"
                    )
                    if pf_node:
                        pf_node.value = pf_name
                        log.info(f"SDKCameraThread: Set PixelFormat = {pf_name}")
                        reset_offsets(self.grabber.device_property_map)
                        w_node = self.grabber.device_property_map.find_integer("Width")
                        h_node = self.grabber.device_property_map.find_integer("Height")
                        if w_node and h_node:
                            w_node.value = w
                            h_node.value = h
                            log.info(f"SDKCameraThread: Set resolution = {w}×{h}")
                    else:
                        log.warning(
                            "SDKCameraThread: PixelFormat node not found; using default."
                        )
                except Exception as e:
                    log.warning(f"SDKCameraThread: Could not set resolution/PF: {e}")

            # ─── Enable Auto features by default ────────────────────────────

            try:
                ae_node = self.grabber.device_property_map.find_enumeration(
                    "ExposureAuto"
                )
                if ae_node:
                    ae_node.value = "Continuous"
                    log.info("SDKCameraThread: Set ExposureAuto = Continuous")
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set ExposureAuto: {e}")

            try:
                ag_node = self.grabber.device_property_map.find_enumeration("GainAuto")
                if ag_node:
                    ag_node.value = "Continuous"
                    log.info("SDKCameraThread: Set GainAuto = Continuous")
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set GainAuto: {e}")

            # ─── Force Continuous acquisition mode ───────────────────────────────
            try:
                acq_node = self.grabber.device_property_map.find_enumeration(
                    "AcquisitionMode"
                )
                if acq_node:
                    entries = [e.name for e in acq_node.entries]
                    if "Continuous" in entries:
                        acq_node.value = "Continuous"
                        log.info("SDKCameraThread: Set AcquisitionMode = Continuous")
                    else:
                        acq_node.value = entries[0]
                        log.info(f"SDKCameraThread: Set AcquisitionMode = {entries[0]}")
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set AcquisitionMode: {e}")

            # ─── Disable trigger so camera will free‐run ─────────────────────────
            try:
                trig_node = self.grabber.device_property_map.find_enumeration(
                    "TriggerMode"
                )
                if trig_node:
                    trig_node.value = "Off"
                    log.info("SDKCameraThread: Set TriggerMode = Off")
                else:
                    log.warning(
                        "SDKCameraThread: TriggerMode node not found; assuming free‐run."
                    )
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not disable TriggerMode: {e}")

            # ─── Signal “grabber_ready” so UI can enable controls ────────────────
            source = getattr(self, "hardware_trigger_source", "")
            if source:
                try:
                    props.find_boolean("AcquisitionFrameRateEnable").value = False
                except Exception:
                    log.info("IC4 frame-rate enable switch unavailable; monitoring requested images.")
                self.trigger_configuration = self._configure_trigger(props, source)
            adapter = IC4Controls(self.grabber)
            self.controller.open(adapter)

            # ─── Build QueueSink requesting Mono8 (fallback to native PF if needed)─
            try:
                self._sink = ic4.QueueSink(
                    self, [ic4.PixelFormat.Mono16 if self._resolution and self._resolution[2] == "Mono16" else ic4.PixelFormat.Mono8], max_output_buffers=4
                )
            except:
                native_pf = self._resolution[2] if self._resolution else None
                if native_pf and hasattr(ic4.PixelFormat, native_pf):
                    self._sink = ic4.QueueSink(
                        self,
                        [getattr(ic4.PixelFormat, native_pf)],
                        max_output_buffers=1,
                    )
                else:
                    raise RuntimeError(
                        "SDKCameraThread: Unable to create QueueSink for Mono8 or native PF."
                    )

            # ─── Start streaming immediately ───────────────────────────────────────
            from imagingcontrol4 import StreamSetupOption

            self.grabber.stream_setup(
                self._sink,
                setup_option=StreamSetupOption.ACQUISITION_START,
            )
            log.info(
                "SDKCameraThread: stream_setup(ACQUISITION_START) succeeded. Entering frame loop…"
            )

            # ─── Frame loop: IC4 calls frames_queued() whenever a new buffer is ready ─
            if source:
                verify_external_trigger(lambda n: props.find_enumeration(n).value, self.trigger_configuration)
            self.controller.service(adapter)
            self.grabber_ready.emit()
            preview_rate_enable = None

            def switch_timing(requested):
                nonlocal preview_rate_enable
                self._accept_frames = False
                self.grabber.stream_stop()
                if requested:
                    try:
                        node = props.find_boolean("AcquisitionFrameRateEnable")
                        preview_rate_enable = node.value
                        node.value = False
                    except Exception:
                        pass
                    configured = self._configure_trigger(props, requested)
                else:
                    props.find_enumeration("TriggerMode").value = "Off"
                    self.trigger_input = None
                    if preview_rate_enable is not None:
                        props.find_boolean("AcquisitionFrameRateEnable").value = preview_rate_enable
                    configured = {}
                self.grabber.stream_setup(self._sink, setup_option=StreamSetupOption.ACQUISITION_START)
                if configured:
                    verify_external_trigger(lambda n: props.find_enumeration(n).value, configured)
                self._accept_frames = True
                log.info("IC4 acquisition timing: %s", configured or "preview")
                return configured

            while not self._stop_requested:
                self.controller.service(adapter)
                self.service_timing(switch_timing)
                self.msleep(10)

        except Exception as e:
            msg = str(e)
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            log.exception("SDKCameraThread: encountered an error.")
            self.error.emit(msg, code_str)

        finally:
            self.controller.close()
            if self.grabber is not None:
                try:
                    self.grabber.stream_stop()
                except Exception:
                    pass
                try:
                    self.grabber.device_close()
                except Exception as exc:
                    log.warning("IC4 device close failed: %s", exc)
            self._sink = None
            self.grabber = None
            self._device_info = None

    def frames_queued(self, sink):
        """
        This callback is invoked by IC4 each time a new buffer is available.
        Pop the buffer, convert to QImage, emit it, and allow IC4 to recycle it.
        """
        try:
            buf = sink.pop_output_buffer()
            if not self._accept_frames:
                return
            arr = buf.numpy_wrap()  # arr: shape=(H, W) dtype=uint8 or uint16

            # Downconvert 16‐bit to 8‐bit if necessary
            if arr.dtype == np.uint8:
                gray8 = arr
            else:
                max_val = float(arr.max()) if arr.max() > 0 else 1.0
                scale = 255.0 / max_val
                gray8 = (arr.astype(np.float32) * scale).astype(np.uint8)

            h, w = gray8.shape[:2]

            # Build a QImage from single‐channel grayscale
            qimg = QImage(gray8.data, w, h, gray8.strides[0], QImage.Format_Grayscale8)

            # Emit to the UI
            try:
                frame_id = buf.meta_data.device_frame_number
            except Exception:
                frame_id = -1
            self.frame_ready.emit(qimg.copy(), FrameData.copy(arr, pixel_format=str(arr.dtype),
                native_depth_preserved=not self._resolution or self._resolution[2] in {"Mono8", "Mono16"},
                camera_frame_id=frame_id if frame_id >= 0 else None))

        except Exception as e:
            log.error(
                f"SDKCameraThread.frames_queued: Error popping/converting buffer: {e}"
            )
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            self.error.emit(str(e), code_str)

    # ─── Required listener methods for QueueSink ─────────────────────────────
    def sink_connected(self, sink, pixel_format, min_buffers_required) -> bool:
        # Return True so the sink actually attaches
        return True

    def sink_disconnected(self, sink) -> None:
        # Called when the sink is torn down—no action needed
        pass

    def stop(self):
        """
        Request the streaming loop to end. After this, run() will clean up.
        """
        self._stop_requested = True
