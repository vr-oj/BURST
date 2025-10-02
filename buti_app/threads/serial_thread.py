# buti_app/threads/serial_thread.py

import csv
import math
import time
import serial
import os
import logging
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
import queue

import utils.config as config

log = logging.getLogger(__name__)

# How many seconds of silence on the serial port we interpret as
# "The BUTI Arduino Box has stopped streaming." You can tune this if needed.
IDLE_TIMEOUT_S = 2.0


class SerialThread(QThread):
    data_ready = pyqtSignal(float, int, float, int, float)
    """Emits (time_s, frame_idx, distance, cycle, force)."""
    error_occurred = pyqtSignal(str)  # For reporting errors back to the GUI
    status_changed = pyqtSignal(str)  # For general status updates

    def __init__(self, port=None, baud=config.DEFAULT_SERIAL_BAUD_RATE, test_csv=None, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = (
            baud if baud is not None else config.DEFAULT_SERIAL_BAUD_RATE
        )
        self.ser = None

        # Control flags
        self.running = False
        self._got_first_packet = False  # Have we seen at least one valid line?
        self._last_data_time = None  # Timestamp (time.time()) of last valid packet
        self._stop_requested = False
        self._idle_timeout_enabled = True  # watchdog for streaming silence
        self._idle_warning_active = False


        # For sending commands (not used here, but kept for future)
        self.command_queue = queue.Queue()
        self.mutex = QMutex()
        self.wait_condition = QWaitCondition()

    def set_idle_timeout_enabled(self, enabled: bool):
        """Toggle the idle-timeout watchdog used during streaming."""
        self._idle_timeout_enabled = bool(enabled)
        self._got_first_packet = False
        self._last_data_time = None
        self._idle_warning_active = False

    def run(self):
        """Main loop for reading from the BURST device.

        If a serial ``port`` is provided, the thread opens it and emits
        ``data_ready`` for each valid packet. Lack of new data for
        ``IDLE_TIMEOUT_S`` seconds after the first packet triggers
        shutdown. When no ``port`` is given the thread immediately
        reports an error and exits.
        """
        self.running = True
        self._got_first_packet = False
        self._last_data_time = None

        if not self.port:
            self.error_occurred.emit("No serial port specified")
            self.running = False
            return

        # 1) Attempt to open the real serial port
        try:
            self.ser = serial.Serial(
                self.port,
                self.baud,
                timeout=config.SERIAL_PORT_TIMEOUT_S,
                write_timeout=config.SERIAL_PORT_WRITE_TIMEOUT_S,
            )
            try:
                self.ser.reset_input_buffer()
            except Exception:
                pass
            log.info(f"Opened serial port {self.port} @ {self.baud} baud")
            self.status_changed.emit(f"Connected to {self.port}")
        except Exception as e:
            log.warning(f"Failed to open serial port {self.port}: {e}")
            self.error_occurred.emit(f"Error opening serial: {e}")
            self.ser = None

        # 2) Main loop
        while self.running and not self._stop_requested:
            # 2a) Process any outgoing commands
            try:
                cmd = self.command_queue.get_nowait()
                if self.ser and cmd:
                    self.ser.write(cmd)
                    try:
                        self.ser.flush()  # ensure the bytes leave the host immediately
                    except Exception:
                        log.debug("Serial flush after command write failed; continuing")
                    log.info("Sent command over serial: %r", cmd)
            except queue.Empty:
                pass
            except Exception as e:
                log.error(f"Error sending serial command: {e}")
                self.error_occurred.emit(f"Serial send error: {e}")

            # 2b) If we have a real port configured, handle live reading+reconnect
            if self.port:
                # 2b-i) If `ser` is None, attempt to reopen once per loop iteration
                if self.ser is None:
                    try:
                        self.ser = serial.Serial(
                            self.port,
                            self.baud,
                            timeout=config.SERIAL_PORT_TIMEOUT_S,
                            write_timeout=config.SERIAL_PORT_WRITE_TIMEOUT_S,
                        )
                        try:
                            self.ser.reset_input_buffer()
                        except Exception:
                            pass
                        log.info(f"[SerialThread] Reconnected to {self.port}")
                        self.status_changed.emit(f"Reconnected to {self.port}")
                    except Exception as e_op:
                        # Still cannot open; sleep a bit before retrying
                        log.debug(
                            f"[SerialThread] Reopen failed: {e_op} â†’ retrying in 0.1 s"
                        )
                        self.msleep(100)
                    continue

                # 2b-ii) Now `self.ser` is not None â†’ attempt to read lines
                try:
                    if self.ser.in_waiting > 0:
                        raw = self.ser.readline()
        
                        if raw:
                            line = raw.decode("utf-8", errors="replace").strip()
                            log.debug(f"Raw serial data: {line}")

                            if not line:
                                continue

                            # Some firmware builds interleave status/configuration
                            # messages (e.g. "Preload (mm) = 0.0") or headings
                            # ("Time,Frame,Distance,â€¦") with the numeric CSV
                            # stream.  Those lines should not trip the parser or
                            # spam the log with warnings, so we filter them out
                            # explicitly before attempting conversion.
                            if "," not in line:
                                log.debug(
                                    "Ignoring non-CSV serial line: %s",
                                    line,
                                )
                                continue

                            parts = [fld.strip() for fld in line.split(",")]
                            if len(parts) < 5:
                                log.debug(
                                    "Ignoring short CSV line (<5 fields): %s",
                                    line,
                                )
                                continue

                            try:
                                time_s = float(parts[0])
                                frame_idx_device = int(float(parts[1]))
                                distance = float(parts[2])
                                cycle_idx = int(float(parts[3]))
                                force = float(parts[4])
                            except ValueError:
                                log.debug(
                                    "Ignoring non-numeric CSV line: %s",
                                    line,
                                )
                                continue

                            # Valid packet â†’ emit signal
                            self.data_ready.emit(
                                time_s,
                                frame_idx_device,
                                distance,
                                cycle_idx,
                                force,
                            )

                            # Mark that we've seen at least one packet
                            if not self._got_first_packet:
                                self._got_first_packet = True
                            # Update last-data timestamp and clear idle warning
                            self._last_data_time = time.time()
                            if self._idle_warning_active:
                                self.status_changed.emit(
                                    "BUTI Arduino Box data stream resumed"
                                )
                                self._idle_warning_active = False
                        else:
                            # readline timed out without data; will check idle below
                            pass
                    else:
                        # No bytes waiting; sleep briefly
                        self.msleep(10)

                except serial.SerialException as se:
                    # Port dropped unexpectedly â†’ attempt to reconnect
                    log.error(
                        f"[SerialThread] SerialException: {se} â†’ will attempt reconnect"
                    )
                    self.status_changed.emit("Serial disconnected, retryingâ€¦")
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                    self.ser = None
                    # Wait a short moment before retrying
                    t0 = time.time()
                    while (
                        self.running
                        and not self._stop_requested
                        and (time.time() - t0) < 1.0
                    ):
                        # Sleep in small increments so we remain responsive
                        self.msleep(50)
                    continue

                except Exception as e:
                    log.exception(f"[SerialThread] Unexpected error in read loop: {e}")
                    self.msleep(100)

                # ---- Idle timeout watchdog ---------------------------------
                if (
                    self._idle_timeout_enabled
                    and self._got_first_packet
                    and self._last_data_time is not None
                    and (time.time() - self._last_data_time) > IDLE_TIMEOUT_S
                ):
                    elapsed = time.time() - self._last_data_time
                    if not self._idle_warning_active:
                        msg = f"No data from the BUTI Arduino Box for {elapsed:.1f}s (waiting)"
                        log.warning(f"[SerialThread] {msg}")
                        self.status_changed.emit(msg)
                        self._idle_warning_active = True


        # 3) Clean up on exit
        if self.ser:
            try:
                self.ser.close()
                log.info(f"Closed serial port {self.port}")
            except Exception as e:
                log.exception(f"Error closing serial port {self.port}: {e}")

        self.status_changed.emit("Disconnected")
        self.running = False
        log.info("SerialThread finished.")

    def send_command(self, command_str):
        """
        Queue a command (ASCII + newline) for the BUTI Arduino Box. GUI can call this safely.
        """
        if self.running:
            try:
                cmd_bytes = command_str.encode("ascii")
            except UnicodeEncodeError:
                log.error("Serial command must be ASCII: %s", command_str)
                self.error_occurred.emit("Serial command must be ASCII")
                return

            terminator = getattr(config, "SERIAL_COMMAND_TERMINATOR", b"\n")
            if not isinstance(terminator, (bytes, bytearray)):
                try:
                    terminator = bytes(terminator)
                except Exception:
                    log.warning(
                        "Invalid SERIAL_COMMAND_TERMINATOR (%r) â†’ using newline",
                        terminator,
                    )
                    terminator = b"\n"

            final_command = cmd_bytes + bytes(terminator)
            self.command_queue.put(final_command)
            log.info(f"Queued command: {command_str}")
        else:
            log.warning("Serial thread not running â†’ cannot send command.")
            self.error_occurred.emit("Cannot send: Serial disconnected.")

    def stop(self):
        """
        Ask the thread to exit cleanly. If it doesn't within 2 seconds, forceâ€terminate.
        """
        log.info("Stopping SerialThreadâ€¦")
        self._stop_requested = True
        self.running = False
        self.wait_condition.wakeAll()
        self.quit()
        self.wait(2000)
        if self.isRunning():
            log.warning("SerialThread did not stop gracefully â†’ terminating.")
            self.terminate()
            self.wait(1000)

