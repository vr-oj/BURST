"""Private-pipe bridge to a plugin's independently installed Python runtime."""
import logging
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .controls import CameraControl

log = logging.getLogger(__name__)


class PluginCancelled(Exception):
    pass


class WindowsWorkerHandle:
    """Own the actual interpreter, not just Windows' venv redirector process."""
    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.TerminateProcess.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.api.OpenProcess(0x100001, False, pid)  # SYNCHRONIZE | PROCESS_TERMINATE
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def wait(self, milliseconds):
        return self.api.WaitForSingleObject(self.handle, milliseconds) == 0

    def terminate(self):
        if not self.wait(0):
            self.api.TerminateProcess(self.handle, 1)
            if not self.wait(3000):
                raise RuntimeError("Camera plugin interpreter could not be stopped")

    def close(self):
        self.api.CloseHandle(self.handle)


def worker_path():
    root = Path(sys._MEIPASS) / "buti_app" if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    return root / "burst_camera_plugin" / "worker.py"


class PluginClient:
    def __init__(self, manifest, cancelled=lambda: False, startup_timeout=5):
        self.manifest, self.cancelled = manifest, cancelled
        self.startup_timeout = startup_timeout
        self.process = self.connection = self.stderr = None
        self.failed = None
        self.worker_handle = None

    def __enter__(self):
        if self.cancelled():
            raise PluginCancelled()
        parent, child = multiprocessing.Pipe(duplex=True)
        self.connection = parent
        self.stderr = tempfile.TemporaryFile(mode="w+b")
        handle = child.fileno()
        args = [str(self.manifest.python), "-I", "-u", str(worker_path()), str(handle), str(self.manifest.path)]
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=self.stderr, stderr=self.stderr,
                      cwd=str(self.manifest.path.parent))
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
            self.close(abort=True)
            raise
        finally:
            if os.name == "nt":
                os.set_handle_inheritable(handle, False)
            child.close()
        try:
            deadline = time.monotonic() + self.startup_timeout
            while not self.connection.poll(0.05):
                if self.cancelled():
                    raise PluginCancelled()
                if self.process.poll() is not None or time.monotonic() >= deadline:
                    raise self.failure("Python environment did not start the plugin bridge")
            hello = self.connection.recv()
            if hello.get("api_version") != 1 or type(hello.get("worker_pid")) is not int:
                raise RuntimeError("Camera plugin bridge handshake failed")
            if os.name == "nt":
                self.worker_handle = WindowsWorkerHandle(hello["worker_pid"])
            self.connection.send("ready")
        except Exception:
            self.close(abort=True)
            raise
        return self

    def failure(self, reason):
        code = self.process.poll()
        suffix = f" (exit 0x{code & 0xffffffff:08X})" if code is not None else ""
        self.stderr.seek(0, 2)
        end = self.stderr.tell()
        self.stderr.seek(max(0, end - 4000))
        detail = self.stderr.read().decode("utf-8", errors="replace").strip()
        error = RuntimeError(f"Camera plugin {self.manifest.name}: {reason}{suffix}."
                             + (f"\nPlugin details: {detail}" if detail else ""))
        log.error("%s", error)
        self.failed = error
        return error

    def request(self, method, *args, timeout=10):
        if self.failed:
            raise self.failed
        if self.cancelled():
            raise PluginCancelled()
        try:
            self.connection.send((method, args))
            deadline = time.monotonic() + timeout
            while not self.connection.poll(0.05):
                if self.cancelled():
                    raise PluginCancelled()
                if self.process.poll() is not None:
                    raise self.failure("helper exited unexpectedly")
                if time.monotonic() >= deadline:
                    raise self.failure(f"helper did not respond within {timeout:g} seconds")
            response = self.connection.recv()
        except (EOFError, BrokenPipeError, OSError) as exc:
            raise self.failure("lost its helper connection") from exc
        if "error" in response:
            error = RuntimeError(f"{self.manifest.name}: {response['error']}")
            if response.get("fatal"):
                self.failed = error
            raise error
        return response["result"]

    def close(self, abort=False):
        try:
            if self.worker_handle:
                if not abort and not self.worker_handle.wait(0):
                    try:
                        self.connection.send(("close", ()))
                        abort = not self.worker_handle.wait(1000)
                    except (OSError, EOFError):
                        abort = True
                if abort:
                    self.worker_handle.terminate()
                # The real SDK owner has exited. Reap its optional venv launcher.
                if self.process:
                    try:
                        self.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
                return
            if self.process and self.process.poll() is None:
                if not abort:
                    try:
                        self.connection.send(("close", ()))
                        self.process.wait(timeout=1)
                    except (OSError, EOFError, subprocess.TimeoutExpired):
                        abort = True
                if abort and self.process.poll() is None:
                    self.process.kill()
                    self.process.wait(timeout=3)
        finally:
            if self.worker_handle:
                self.worker_handle.close()
                self.worker_handle = None
            if self.connection:
                self.connection.close()
            if self.stderr:
                self.stderr.close()
            self.process = self.connection = self.stderr = None

    def __exit__(self, exc_type, *args):
        self.close(abort=exc_type not in (None, PluginCancelled))


class PluginControls:
    def __init__(self, client, manifest):
        self.client, self.manifest = client, manifest
        self.snapshot = {}

    def read_controls(self):
        self.snapshot = self.client.request("snapshot")
        return {name: CameraControl(**(value | {"choices": tuple(value["choices"])}))
                for name, value in self.snapshot["controls"].items()}

    def read_diagnostics(self):
        return self.snapshot.get("diagnostics", {}) | {
            "plugin_id": self.manifest.id, "plugin_version": self.manifest.version,
            "plugin_api_version": 1}

    def set_value(self, name, value):
        self.client.request("set", name, value)
