"""Private pipe RPC: MMCore/adapter DLLs never share BURST's Qt process.

The helper enters before the application imports Qt. Pipe handles are inherited
only by the child we start; camera frames do not travel over a network socket.
"""
import logging
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

log = logging.getLogger(__name__)


class MicroManagerCancelled(Exception):
    pass


class MicroManagerClient:
    def __init__(self, cancelled=lambda: False):
        self.cancelled = cancelled
        self.process = None
        self.connection = None
        self.stderr = None

    def __enter__(self):
        parent, child = multiprocessing.Pipe(duplex=True)
        self.connection = parent
        self.stderr = tempfile.TemporaryFile(mode="w+b")
        handle = child.fileno()
        args = [sys.executable]
        if not getattr(sys, "frozen", False):
            args += ["-u", str(Path(__file__).resolve().parents[1] / "buti_app.py")]
        args += ["--burst-mm-worker", str(handle)]
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=self.stderr, stderr=self.stderr)
        # A PyInstaller parent's DLL directory can otherwise leak its Qt runtime
        # into the helper. The helper clears it before importing any native code.
        if os.name == "nt":
            os.set_handle_inheritable(handle, True)
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {"handle_list": [handle]}
            kwargs.update(startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        else:
            kwargs["pass_fds"] = (handle,)
        try:
            self.process = subprocess.Popen(args, **kwargs)
        except Exception:
            self.close()
            raise
        finally:
            if os.name == "nt":
                os.set_handle_inheritable(handle, False)
            child.close()
        return self

    def _failure(self, reason):
        code = self.process.poll() if self.process else None
        if self.process and code is None:
            try:
                code = self.process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
        suffix = f" (exit 0x{code & 0xffffffff:08X})" if code is not None else ""
        tail = ""
        if self.stderr:
            self.stderr.seek(0, 2)
            end = self.stderr.tell()
            self.stderr.seek(max(0, end - 8000))
            tail = self.stderr.read().decode("utf-8", errors="replace").strip()
        message = f"Micro-Manager helper {reason}{suffix}. BURST remains open."
        if tail:
            log.error("%s\nDriver output:\n%s", message, tail)
        else:
            log.error(message)
        return RuntimeError(message + " Check that other camera programs are closed and that adapter/runtime versions match."
                            + ("\nDriver details: " + tail[-2000:] if tail else ""))

    def request(self, method, *args, timeout=30):
        if self.cancelled():
            raise MicroManagerCancelled()
        try:
            self.connection.send((method, args))
            deadline = time.monotonic() + timeout
            while not self.connection.poll(0.1):
                if self.cancelled():
                    raise MicroManagerCancelled()
                if self.process.poll() is not None:
                    raise self._failure("exited unexpectedly")
                if time.monotonic() >= deadline:
                    raise self._failure(f"did not respond within {timeout:g} seconds")
            response = self.connection.recv()
        except (EOFError, BrokenPipeError, OSError) as exc:
            raise self._failure("lost its connection") from exc
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]

    def close(self, abort=False):
        if self.process is not None:
            if abort and self.process.poll() is None and not (os.name == "nt" and getattr(sys, "frozen", False)):
                # A timed-out discovery must not spend another two seconds
                # asking the same unresponsive native driver to stop.
                self.process.kill()
                self.process.wait(timeout=5)
            if self.process.poll() is None:
                try:
                    self.connection.send(("close", ()))
                    self.process.wait(timeout=2)
                except (OSError, EOFError, subprocess.TimeoutExpired):
                    log.warning("Stopping an unresponsive Micro-Manager helper")
                    if os.name == "nt" and getattr(sys, "frozen", False):
                        # One-file bootloaders may have a child process. Stop the
                        # entire helper tree so a wedged adapter cannot stay open.
                        try:
                            subprocess.run([str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "taskkill.exe"),
                                            "/PID", str(self.process.pid), "/T", "/F"],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=5, check=False)
                        except (OSError, subprocess.TimeoutExpired):
                            log.exception("Could not stop Micro-Manager helper process tree")
                    if self.process.poll() is None:
                        self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.stderr is not None:
            self.stderr.close()
            self.stderr = None

    def __exit__(self, exc_type, *args):
        self.close(abort=exc_type is not None)


class MicroManagerService:
    """Native operations, used only inside the helper (or with test doubles)."""
    def __init__(self, sdk):
        self.sdk = sdk
        self.session = None
        self.adapter = None
        self.preview_rate_switches = {}

    def dispatch(self, method, args):
        from .micro_manager_backend import MicroManagerSession, MicroManagerControls
        if method in {"inspect_installation", "discover_library"}:
            from . import micro_manager_discovery
            return getattr(micro_manager_discovery, method)(self.sdk, *args)
        if method == "probe":
            with MicroManagerSession(self.sdk, args[0]) as session:
                result = {"cameras": list(session.core.getLoadedDevicesOfType(self.sdk.CameraDevice)),
                          "selected": session.camera, "version": session.core.getVersionInfo(),
                          "api": session.core.getAPIVersionInfo()}
                result["modes"] = {}
                result["controls"] = {}
                if session.profile.get("bindings") or session.profile.get("timing"):
                    # A mapping belongs to one camera, not other devices in a cfg.
                    result["cameras"] = [session.camera]
                for camera in result["cameras"]:
                    session.core.setCameraDevice(camera)
                    session.camera = camera
                    from .micro_manager_trigger import MicroManagerTrigger
                    session.trigger = MicroManagerTrigger(session.core, camera, session.profile.get("timing"),
                                                         session.profile.get("bindings"))
                    result["modes"][camera] = {"width": session.core.getImageWidth(),
                                               "height": session.core.getImageHeight()}
                    result["controls"][camera] = MicroManagerControls(session).read_controls()
            return result
        if method == "open":
            self.session = MicroManagerSession(self.sdk, args[0])
            self.session.__enter__()
            self.adapter = MicroManagerControls(self.session)
            self.session.trigger.preview()
            fps_name = "fps"
            fps = self.adapter.read_controls().get(fps_name)
            if fps and fps.writable:
                try:
                    self.adapter.set_value(fps_name, "10")
                except Exception as exc:
                    log.warning("Could not request 10 FPS: %s", exc)
            source = args[1] if len(args) > 1 else ""
            return self.dispatch("timing", (source,))
        if method == "timing":
            from .trigger import verify_external_trigger
            source = args[0]
            before = self.adapter.read_controls()
            preserved = {name: before[name].value for name in ("pixel_format", "mm:Binning", "mmcore:Sensor ROI (x,y,width,height)")
                         if name in before}
            for name, auto in (("exposure", "auto_exposure"), ("gain", "auto_gain")):
                if name in before and (auto not in before or before[auto].value == "Off"):
                    preserved[name] = before[name].value
            preserved.update({name: before[name].value for name in ("auto_exposure", "auto_gain") if name in before})
            self.session.stop()
            self.trigger_configuration = {}
            self.trigger_input = None
            core, camera = self.session.core, self.session.camera
            if source:
                self.trigger_configuration, self.trigger_input = self.session.trigger.arm(source)
                for name in (() if self.session.trigger.timing.get("external") else ("Frame Rate Control Enabled", "AcquisitionFrameRateEnable")):
                    try:
                        if core.hasProperty(camera, name) and not core.isPropertyReadOnly(camera, name):
                            self.preview_rate_switches.setdefault(name, core.getProperty(camera, name))
                            core.setProperty(camera, name, "0")
                    except Exception:
                        log.info("Adapter frame-rate switch %s could not be disabled.", name)
            else:
                self.session.trigger.preview()
            if not source:
                for name, value in self.preview_rate_switches.items():
                    core.setProperty(camera, name, value)
                self.preview_rate_switches.clear()
            after = self.adapter.read_controls()
            for name, value in preserved.items():
                if name not in after or after[name].value != value:
                    raise RuntimeError(f"Camera timing changed image setting '{name}'. BURST has not started the Arduino.")
            self.session.start()
            if source:
                verify_external_trigger(lambda n: core.getProperty(camera, n), self.trigger_configuration)
            return self.dispatch("snapshot", ())
        if method == "snapshot":
            return {"controls": self.adapter.read_controls(), "diagnostics": self.adapter.read_diagnostics(),
                    "trigger_configuration": getattr(self, "trigger_configuration", {}),
                    "trigger_input": getattr(self, "trigger_input", None)}
        if method == "set":
            if getattr(self, "trigger_configuration", {}):
                raise RuntimeError("Stop recording before changing camera properties.")
            self.adapter.set_value(*args)
            return None
        if method == "next":
            core = self.session.core
            if core.isBufferOverflowed():
                raise RuntimeError("Micro-Manager image buffer overflow. Reduce acquisition rate or resolution.")
            if core.getRemainingImageCount():
                import numpy as np
                components, bit_depth = core.getNumberOfComponents(), core.getImageBitDepth()
                metadata = {}
                if hasattr(self.sdk, "Metadata"):
                    tags = self.sdk.Metadata()
                    pixels = core.popNextImageMD(tags)
                    for key in tags.GetKeys():
                        try:
                            metadata[str(key)] = tags.GetSingleTag(key).GetValue()
                        except Exception:
                            pass
                else:
                    pixels = core.popNextImage()
                return (np.array(pixels, copy=True), components, bit_depth, {"micro_manager": metadata,
                        "timestamp_semantics": "adapter_metadata_not_assumed_exposure_time"})
            if not core.isSequenceRunning():
                raise RuntimeError("The camera stopped sequence acquisition.")
            return None
        raise ValueError(f"Unknown Micro-Manager operation: {method}")

    def close(self):
        self.adapter = None
        if self.session is not None:
            self.session.close()
            self.session = None


class RemoteMicroManagerControls:
    def __init__(self, client, snapshot):
        self.client, self.snapshot = client, snapshot

    def read_controls(self):
        self.snapshot = self.client.request("snapshot", timeout=10)
        return self.snapshot["controls"]

    def read_diagnostics(self):
        return self.snapshot["diagnostics"]

    def set_value(self, name, value):
        self.client.request("set", name, value, timeout=10)


def worker_main(handle):
    # This function must execute before Qt, NumPy, pymmcore or any vendor SDK
    # import. Do not inherit a PyInstaller parent's DLL search directory.
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
        from .runtime import configure_dll_paths, _dll_directories
        configure_dll_paths()
        # Some MM adapters use LoadLibrary (rather than the Python DLL search
        # API) to resolve vendor dependencies, so advertise these in this child only.
        os.environ["PATH"] = os.pathsep.join([*_dll_directories, os.environ.get("PATH", "")])
    # Windowed PyInstaller applications set sys.stderr to None even when their
    # parent supplies a diagnostic handle. Recover that handle for driver logs.
    if sys.stderr is None:
        if os.name == "nt":
            import msvcrt
            ctypes.windll.kernel32.GetStdHandle.restype = ctypes.c_void_p
            error_handle = ctypes.windll.kernel32.GetStdHandle(-12)
            if error_handle and error_handle != ctypes.c_void_p(-1).value:
                sys.stderr = os.fdopen(msvcrt.open_osfhandle(error_handle, os.O_WRONLY), "w", buffering=1)
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w")
    import faulthandler
    faulthandler.enable(file=sys.stderr)
    logging.basicConfig(level=logging.INFO)
    if os.name == "nt":
        from multiprocessing.connection import PipeConnection
        connection = PipeConnection(handle)
    else:
        connection = Connection(handle)
    service = None
    try:
        while True:
            method, args = connection.recv()
            if method == "close":
                break
            try:
                if service is None:
                    import pymmcore
                    service = MicroManagerService(pymmcore)
                connection.send({"result": service.dispatch(method, args)})
            except Exception as exc:
                log.exception("Micro-Manager helper operation %s failed", method)
                connection.send({"error": str(exc)})
    except (EOFError, BrokenPipeError):
        pass
    finally:
        if service is not None:
            service.close()
        connection.close()
