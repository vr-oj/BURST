# Camera SDK plugins for labs

BURST has three camera routes: built-in IC4, Micro-Manager for supported device
adapters, and optional lab-developed SDK plugins. Plugins use the existing camera
selector, exposure/gain controls, preview, recorder and Arduino timing workflow.
Installing an SDK alone does not create a plugin. A developer must implement the
SDK translation and validate it with the actual camera. No BURST fork is needed.

## Installing a lab-provided plugin

1. Install the vendor's camera drivers and runtime following the lab's instructions.
2. Install the plugin's own **64-bit Python 3.10 or later** environment, NumPy,
   and vendor Python bindings (or the developer's ctypes/C++ wrapper). The Python
   version must be one the SDK supports. It need not match BURST's embedded Python.
3. Put the plugin folder in `%LOCALAPPDATA%\BURST\CameraPlugins`. The layout is
   `CameraPlugins\my_lab_camera\plugin.json` alongside the adapter's Python code.
   Keep SDK binaries and Python dependencies in the plugin environment or the
   vendor's installation, not in BURST's Program Files directory.
4. Configure `python` in the manifest to point to that environment's `python.exe`.
   The lab can distribute an installer to perform these steps. BURST does not run
   pip, download drivers, or install dependencies automatically.
5. Restart BURST or use **Refresh Devices**. Plugin cameras appear after the
   background search finishes. Choose one and use **Start Camera** normally.

**Acquisition → Advanced → Camera plugins…** opens the folder and shows discovery
errors, missing dependencies, and a Cancel search button. Searches allow ten
seconds per plugin and sixty seconds overall, plus bounded helper cleanup. Partial
results are retained. Stop the camera before refreshing plugins. For deployment
or development, `BURST_CAMERA_PLUGIN_PATH` replaces the default search location;
it contains parent directories separated by `;` on Windows.

Set `"enabled": false` in a manifest to disable it, or remove its folder while
BURST is closed. Duplicate valid IDs are rejected, rather than picking a copy.
Explicit native, Micro-Manager and plugin routes remain selectable separately.
No hardware identity is guessed from a display name.

Plugins execute trusted lab code with the user's permissions. Process isolation
protects BURST from SDK crashes and conflicting libraries; it is not a security
sandbox. Install only plugins from developers you trust.

## Manifest and runtime

```json
{
  "api_version": 1,
  "id": "my_lab_camera",
  "name": "My Lab SDK",
  "version": "1.0.0",
  "python": ".venv/Scripts/python.exe",
  "entry_point": "adapter:LabCamera",
  "dll_directories": ["C:/Program Files/Vendor/SDK/bin"],
  "enabled": true
}
```

`python` and DLL directories accept absolute paths or paths relative to the
manifest. The entry point is a module and class, not a script command. It must
construct a no-argument subclass of `burst_camera_plugin.CameraPlugin`.
Remove `dll_directories` or use `[]` when no extra DLL search path is needed.
IDs are 3–64 lowercase letters/digits/underscores beginning with a letter; built-in
IDs are reserved. API versions must match exactly. Plugin versions identify the
lab's release and are included in recording diagnostics.

BURST ships API v1 and its helper **as source resources**, including in PyInstaller
builds. It launches the helper using the manifest's Python in isolated mode (`-I`)
and supplies the API import path. All vendor imports and SDK operations happen in
that helper, on one thread, outside Qt and the native IC4 process. Frames cross a
private inherited pipe as owned bytes, with primitive metadata; no SDK pointers,
Qt objects or NumPy pickles cross Python environments. Standard library modules,
NumPy and the vendor's dependencies must be available in the plugin environment.
No network listener is started.

Each discovery or camera session owns a helper. Errors, crashes and ten-second
request timeouts report back to BURST. A nonresponsive helper is terminated after
bounded cleanup. Drivers can still need recovery after a native crash. API v1
does not support plugins spawning independent persistent camera helper processes.

## Developer interface

The reference source is `buti_app/burst_camera_plugin/__init__.py`. Import its
`CameraPlugin`, `Device`, `Mode`, `Control`, `TriggerState` and `Frame` types.
The runnable example is `examples/camera_plugin/adapter.py` in the BURST repository.
It generates synthetic 12-bit pixels and intentionally refuses external triggers.

| Method | Required behavior |
| --- | --- |
| `discover()` | Return `Device` objects with stable IDs, names, and optional vendor/serial/modes. Enumerate without changing hardware settings. |
| `open(device_id, mode)` | Open exactly that camera and selected acquisition mode (`None` means its configured default). |
| `controls()` | Return actual readback and current capabilities; omit unsupported controls. |
| `set_control(name, value)` | Apply to hardware; do not implement preview-only brightness as exposure/gain. |
| `configure_trigger(source)` | `None`: free-running preview. `auto`: reuse a configured physical input or the only unambiguous input. An explicit input must be honored. Return expected `TriggerState`. |
| `read_trigger()` | Read current hardware timing after acquisition starts; never just echo the last requested state. |
| `start()` | Clear old queued frames, then start acquisition. A failed partial start must be safe to stop. |
| `next_frame(timeout_ms)` | Return the next frame in acquisition order, or `None` on timeout. Report buffer overflow/dropped frames as errors; never silently return only the newest frame. |
| `stop()` | Stop promptly, even with no external pulses. Do not wait indefinitely for a frame. |
| `close()` | Release all SDK resources; tolerate failed initialization and repeated calls. |
| `diagnostics()` | Optional JSON dictionary, including SDK version and useful acquisition information. |

Methods must return within the helper's request deadline. The normal frame wait
is 100 ms. No preview images for five seconds is an error; externally armed
acquisition may wait without incoming pulses. On failures during writes/timing,
BURST closes the stream. An adapter should restore settings if a write partially
fails, and make subsequent `close()` safe.
Values rejected against reported ranges/choices before reaching the SDK show a
control error without stopping acquisition.

### Shared controls

| Name | API units/type |
| --- | --- |
| `exposure` | Numeric microseconds (`us`); BURST displays milliseconds. |
| `gain` | Numeric, with the real unit (e.g. `dB` or `camera units`). |
| `fps` | Numeric Hz, writable only if it actually controls camera acquisition. |
| `auto_exposure`, `auto_gain` | Native values mapped to `Off` and `Continuous`. Do not invent hardware automatic modes. |
| `pixel_format` | String with reported choices; keep data layout consistent with the selected format. |
| `vendor:Name` | Additional numeric/text/enum properties under **Camera properties…**. Named sensitivity/readout modes belong here rather than in the numeric gain field. |

Report `minimum`, `maximum`, `increment`, `choices`, `writable`, `unit` and
`value_type` (`float`, `int`, `enum`, `str`). Set `limits_known=False` when no numeric
range is available; the slider is disabled but numeric entry remains available.
Set `requires_stop=True` for changes that need acquisition stopped. BURST performs
the stop/write/restart sequence. Report unavailable/locked controls on each
snapshot; do not cache capabilities permanently. `diagnostics()["control_issues"]`
may explain missing controls by their standard names. Extra properties must not
silently switch preview to external triggering; that fails the session's readback.

BURST requests 10 FPS preview only when `fps` is exposed and writable. Report real
camera readback; the application measures delivered frames separately. A failed
10 FPS request is logged and normal rate guidance still applies.

### Recording and data integrity

`TriggerState(external=True, input="Line1", settings={...})` means an externally
triggered **single exposure per Arduino pulse**. The settings dictionary contains
actual adapter-specific timing values, including edge/source/selector where
applicable. Software triggers, trigger-first sequences, and guessed physical
inputs do not satisfy this contract. A camera with unsupported triggering must
raise an error. Preview-only plugins remain usable in explicitly selected
approximate mode; they never silently fall back to it.

BURST stops preview, configures triggering, verifies readback after starting the
stream, then signals the existing recorder to prepare. Only recorder readiness
can start the Arduino. Failed arming does not start the box. The adapter must
preserve exposure, gain, auto settings, geometry, pixel format and any other image
settings through arm/restore; the bridge compares the reported standard image
controls and `image_width`, `image_height`, `image_bit_depth` when reported in
`diagnostics()`. It skips comparing changing exposure/gain readbacks while those auto modes
are active. The plugin must restore any preview frame-rate enables it changed.
Neither the plugin nor its camera SDK should open the Arduino's serial port.

Return `Frame(pixels, bit_depth, camera_frame_id, metadata)`. Supported layouts are
native-endian `uint8`/`uint16` 2D mono and `uint8` `(height,width,3)` **RGB**. Convert
packed/Bayer/BGR formats correctly in the adapter and document transformations.
Mono TIFF pixels preserve their original bit depth; only the preview is scaled to
8 bits. The pipe copies pixels before the next SDK call can reuse a buffer.

Use genuine consecutive camera image IDs when available, otherwise `None`.
Do not substitute a host incrementing counter. Put hardware timestamps and their
units/clock origin in JSON metadata, for example `camera_timestamp_ns` and
`timestamp_clock`. They remain distinct from BURST's host receipt times and are
not assumed to share the Arduino clock. The existing recorder associates frames
with requested Arduino counter transitions, including sparse Capture settings;
it retains missing-frame, counter and recording-lag checks.

## Example and validation

From Command Prompt, copy `examples\camera_plugin` into the plugin folder. In the
copied folder (Python 3.12 is just an example supported by the simulator):

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install numpy
```

Refresh BURST to select **SIMULATED camera (no hardware trigger)**. No hardware is
used. Do not distribute this example as a validated physical camera integration.
For an actual adapter, install its SDK dependencies into this same dedicated venv
and replace the implementation/manifest with the lab's version.

Developers working in the BURST checkout can run the reusable preview validator:

```bat
.venv\Scripts\python.exe scripts\validate-camera-plugin.py "C:\path\to\plugin.json"
```

This discovers/selects a camera, validates frames/controls, restarts acquisition,
and verifies preview resumes. It changes the camera to free-running preview and
requests 10 FPS where supported. Close other camera programs before running it.
Use `--device ID` with multiple devices. Optional `--trigger-source auto` also
arms/checks external readback and restores preview. The validator sends no Arduino
commands or trigger pulses. It does not certify physical timing.

Before a lab distributes a plugin, also validate:

- Actual exposure/gain changes in saved pixels; unsupported controls remain disabled.
- Manual/auto settings and sensor geometry survive preview → arm → restore.
- Correct external input/edge, failed readback, missing pulses, sparse Capture,
  actual camera counters and stop without incoming frames.
- Known physical timing with the real Arduino/cable/camera combination, not just
  matching CSV/TIFF counts. Keep a report naming camera, firmware, driver, SDK,
  plugin version, acquisition mode and measured timing.
- Repeated recordings, disconnect/reconnect, buffer overflow, missing SDKs,
  stop/restart, and operation using the packaged BURST build on a clean computer.

Repository regression tests (`test_camera_plugins.py`) exercise isolated runtime
loading, raw pixel preservation, failure containment, timing readback, cancellation
and the common UI/recording lifecycle with simulated devices. Real SDK adapters
and physical timing still need the lab's hardware validation.
