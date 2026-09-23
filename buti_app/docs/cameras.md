# Camera backends and SDK installation

BURST discovers every available backend at startup and when **Refresh Devices** is
clicked. Select a camera and acquisition mode, then **Start Camera**. A manufacturer
selection is not required. Stop the current stream before refreshing or changing
devices. Missing/broken optional SDKs are reported in the diagnostic log, not in
startup dialogs.

| Backend | Camera/runtime requirements |
| --- | --- |
| IC4 | The Imaging Source runtime/drivers and `imagingcontrol4` |
| Spinnaker | Teledyne FLIR Spinnaker runtime/drivers and its matching `PySpin` wheel |
| Generic USB / OpenCV | A Windows UVC driver and `opencv-python` |
| Generic GenTL | A vendor's 64-bit GenTL producer (`.cti`), its runtime/drivers, and `harvesters` / `genicam` |
| Micro-Manager | `pymmcore`, compatible 64-bit Micro-Manager device adapters, vendor drivers, and a saved camera `.cfg` |
| Installed SDK adapter | A Python package registered in `burst.camera_backends`, plus that adapter's SDK |

The public GenTL bridge packages are included in the source requirements, but all
backends remain optional at runtime. An arbitrary proprietary SDK cannot be driven
without an API adapter. If it provides a compatible GenTL producer, the generic
backend can use it; otherwise an installed adapter implements the contract below.

## Micro-Manager setup for installed BURST

1. Install compatible **64-bit Micro-Manager** and the vendor drivers required by
   its camera adapter. Confirm your camera works in Micro-Manager's Live view.
2. Save a camera hardware configuration (`.cfg`) in a permanent user folder.
   Prefer a camera-only configuration: loading a configuration initializes **all**
   devices named in it, including other microscope hardware. Close Micro-Manager
   and other camera programs before using the camera in BURST.
3. In BURST open **Acquisition → Micro-Manager Camera Setup…**. Browse to the
   Micro-Manager folder containing its device adapters and your `.cfg` file.
4. Choose **Load configuration and find cameras**. This runs outside the GUI
   thread in an isolated helper process, validates configuration loading and lists its cameras, then releases
   them. It does not certify image acquisition or timing. Select a camera, click
   **Add selected camera**, then **Save**. Multiple configurations can be saved;
   the same dialog removes saved entries without deleting any files.
5. Select the saved Micro-Manager entry from **Camera Device**, keep **Camera
   Default**, and start the preview. Geometry and pixel type initially come from
   the configuration. Let delivery stabilize before recording. The normal 10 FPS
   readiness check and recording lag guard apply.

BURST stores configuration **paths** in per-user settings. It does not copy or
modify the `.cfg`; leave it and its referenced resources in place. Saved entries
are candidates, not a claim that the camera is connected. Refreshing devices does
not load a Micro-Manager configuration or initialize microscope hardware.

Micro-Manager's native libraries run in a separate helper process during both setup
and acquisition. This keeps them separate from Qt and BURST's native SDK backends.
A crashed or unresponsive adapter reports an error with its helper exit code and
available driver diagnostics instead of closing BURST. Configuration loading has
a 30-second response timeout; acquisition/control requests have 10-second timeouts.
Cancel in the setup dialog closes its helper. An unresponsive helper is terminated
after a bounded cleanup wait. Vendor drivers may still need recovery after a native
crash. No network service is used; images and commands use a private inherited pipe.
Vendor runtime search paths are configured inside the helper.

During preview, **Camera properties…** exposes the selected adapter's native
property names, values, choices and reported ranges. Read-only and initialization-only
settings cannot be edited. Exposure is also available in milliseconds; sensor ROI
accepts `x,y,width,height` (use `0,0,0,0` to restore the full sensor). Properties may
be rejected by a particular adapter; the dialog shows errors and applied readback.
Changes briefly stop/restart acquisition, reset rate readiness, and last for this
session. Save persistent settings through Micro-Manager's configuration workflow.
Controls lock during recording. Gain units and automatic-control enums are not
guessed: when they are not portable, use the native property panel. The normal
exposure/frame-rate sliders appear only when the corresponding known property
provides usable limits.

The source/build requirements pin `pymmcore==12.5.0.75.0` (MMCore 12.5.0,
device API **75**, module API **10**). Micro-Manager adapters must match that API
and architecture. Installing an older Micro-Manager release or a mismatched SDK
can fail even when its own GUI works. The setup error reports the bridge's required
API. End users of a packaged build do not install Python or wheels; the release
must include the bridge. Source users update their environment with Command Prompt:

```bat
.venv\Scripts\python.exe -m pip install -r buti_app\requirements.txt
```

Acquisition uses the MMCore sequence buffer, detects overflow, and copies images
before native buffers can be reused. Supported images are single-channel 8/16-bit
monochrome and packed 32-bit RGB. High-bit-depth monochrome is scaled by its reported
bit depth to BURST's existing **8-bit preview/TIFF pipeline**; original 16-bit precision
is not preserved. Float, RGB64 and multi-camera/channel payloads fail with an
explanation instead of being interpreted incorrectly.

Trigger settings are preserved from the configuration. Start with internal/free-running
triggering for BURST's preview/readiness workflow. An external-trigger configuration
without incoming pulses will time out; this integration does not implement a complete
Arduino-triggered startup/validation workflow. MMCore's nominal sequence interval
does not reliably set camera FPS. BURST requests 10 through `AcquisitionFrameRate`
where exposed, otherwise the adapter's own properties/configuration set the rate,
and measured delivery determines readiness. Passing readiness never proves exposure
synchronization.

References: [Micro-Manager Python integration](https://micro-manager.org/Using_the_Micro-Manager_python_library),
[supported hardware](https://micro-manager.org/Device_Support),
[MMCore API](https://micro-manager.org/apidoc/MMCore/latest/class_c_m_m_core.html).

## Teledyne FLIR / Edmund Optics setup

1. Install the **64-bit Teledyne Spinnaker SDK/runtime** and camera drivers. Confirm
   the FLIR camera streams in SpinView, then close SpinView to release the camera.
2. Install the **matching SDK-supplied PySpin wheel into BURST's environment**.
   This repository uses 64-bit Python 3.12 and NumPy 2.2.6. Teledyne's Spinnaker
   4.4.0.248 documentation lists Windows 10/11 x64 Python 3.12 support and gives
   this wheel example (use the exact wheel supplied with your installed release):

   ```powershell
   .venv\Scripts\python.exe -m pip install "C:\path\to\spinnaker_python-4.4.0.248-cp312-cp312-win_amd64.whl"
   .venv\Scripts\python.exe -m pip check
   .venv\Scripts\python.exe -c "import PySpin; s=PySpin.System.GetInstance(); print(s.GetLibraryVersion()); s.ReleaseInstance()"
   ```

   `cp312` and `win_amd64` must match Python 3.12 and Windows x64. The wheel version
   must match the installed Spinnaker runtime. Follow that release's NumPy
   requirements too; do not substitute a Python 3.10 wheel or silently downgrade
   BURST's scientific stack. Older SDK releases may not supply a compatible wheel.
   `PySpin` is deliberately not a normal pip requirement. Do not install an
   unrelated PyPI package with the same import/package name.
3. Restart BURST. The camera should appear as **FLIR / Spinnaker**. No backend
   switch is needed. Remove an old `BURST_CAMERA_BACKEND=ic4` setting if present.
4. Choose a mode and start the camera. The grayscale path supports Mono8 and
   deterministic SDK conversion of other monochrome formats. RGB/BGR/Bayer input
   uses RGB8 conversion. Preview and TIFF recording use the same copied QImage,
   including ROI and mirroring. No per-frame intensity normalization is applied
   by the Spinnaker path.

The import check verifies loading, not hardware streaming. SDK/runtime or NumPy ABI
mismatches can fail in native code; use the matched vendor installation rather than
mixing releases. Installation into another Python environment does not extend an
already-built BURST executable; see Windows packaging below.

Sources checked September 22, 2026:
[Teledyne Python compatibility and acquisition](https://softwareservices.flir.com/Spinnaker/latest/getting-started/python.html),
[Spinnaker System lifetime](https://softwareservices.flir.com/Spinnaker/latest/api/pyspin_ref/classes/PySpin.System.html).

## Other installed SDKs through GenTL

Install the camera vendor's SDK/runtime and 64-bit GenTL producer. BURST loads `.cti`
files in directories advertised by the standard **GENICAM_GENTL64_PATH** environment
variable. Many SDK installers set it. When they do not, **BURST_GENTL_PATH** accepts
additional producer files or directories, separated by semicolons on Windows.
BURST only inspects these directories; it does not scan the drive for SDK binaries.
Restart BURST after installing a producer or changing environment variables.

If dependent DLLs cannot be loaded, **BURST_CAMERA_DLL_PATH** accepts extra runtime
directories (also semicolon-separated on Windows). BURST adds producer directories
and common installed Spinnaker `bin64` / `bin64/vs2015` directories to the Windows
DLL search path. The vendor's runtime installer is still required.

The GenTL implementation supports single-component Mono8, unpacked Mono10/12/14/16,
RGB8 and BGR8 images. Higher-depth grayscale uses a fixed right shift to 8-bit.
Packed Bayer, multi-component, and multi-stream payloads need further adapters or
conversion support; select Mono8/RGB8 when the camera offers them. Not every vendor
producer or feature has been validated with hardware.

Native SDK entries take priority over GenTL entries with the same manufacturer and
serial. OpenCV cannot supply a reliable hardware identity, so uncertain generic
duplicates are kept and logged instead of hiding a potentially different camera.

[Harvester project and API](https://github.com/genicam/harvesters),
[Harvester buffer ownership](https://harvesters.readthedocs.io/en/latest/reference/harvester_core.html).

## Controls and generic USB discovery

Exposure is displayed in milliseconds (controller values are microseconds), gain
in dB, and frame rate in Hz. Controls are enabled only when the camera reports a
supported, writable property. Camera writes execute in the acquisition worker;
the UI reads detached capability snapshots. Recording disables changes.

OpenCV probes indices **0–2** only, tries DirectShow then Media Foundation on
Windows, and releases failed capture handles. `BURST_CAMERA_INDEX` (or the legacy
`BUTI_CAMERA_INDEX`) probes one explicit index, including indices above 2. Driver
open calls can still take time; OpenCV supplies no portable camera-open deadline.
USB resolution presets are requests: the live size reports what the device
actually negotiates. Mono8 presets produce grayscale frames. OpenCV controls stay
disabled because portable property units, ranges, and write support cannot be
reliably determined. Use the camera driver's settings where needed.

`BURST_CAMERA_FPS` / `BUTI_CAMERA_FPS` still override the OpenCV requested frame rate.
`BURST_CAMERA_BACKEND` / `BUTI_CAMERA_BACKEND` are optional diagnostic filters:
`auto` (default), `ic4`, `spinnaker`, `gentl`, `opencv`, or a comma-separated list
including installed adapter names. A filter does not silently fall back to another
backend. To choose an alternative SDK for a duplicate device during diagnostics,
filter to that backend and refresh/restart. Normal use needs no filter.

## Adding another SDK adapter

Install a trusted Python package in BURST's environment with an entry point:

```toml
[project.entry-points."burst.camera_backends"]
vendor_sdk = "my_camera_package:Backend"
```

`Backend()` takes no arguments and exposes:

- `key = "vendor_sdk"` (must match the entry-point name; built-in keys are reserved).
- `discover() -> list[CameraDeviceInfo]`, with backend, stable id, display name,
  optional serial/vendor/physical_id, and backend-owned native_info.
- `list_modes(device) -> list[CameraMode]`.
- `create_thread(device, parent=None)` returning a QThread with `set_resolution`,
  `stop`, `controller`, `grabber_ready()`, `frame_ready(QImage, object)`, and
  `error(str, str)`. `stop` requests shutdown without deleting or terminating the
  thread; `finished` is emitted only after native cleanup.
- `close()` for registry-owned resources after acquisition threads have stopped.

Use `cameras.controls.CameraController` for capability snapshots and queued writes.
Its adapter implements `read_controls()` and `set_value(name, value)`, called only
by the acquisition worker. Normalized keys are exposure, gain, fps, auto_exposure,
auto_gain, and pixel_format. Auto enums use Off/Continuous. Omit unknown controls,
units, or ranges rather than guessing. Copy images before emitting them; never
return a native buffer whose storage will be reused/released before signal delivery.
Do not put vendor imports in the UI. An adapter import/discovery failure is isolated
from other backends. Discovery order prefers native SDKs and installed adapters, then GenTL and USB. Set physical_id only for reliable shared identity.

## Windows executable packaging

`BURST.spec` bundles IC4, OpenCV, the GenTL bridge and `pymmcore` **when installed in the build
environment**. An absent SDK no longer aborts a development build. It also collects
installed `burst.camera_backends` entry-point metadata and adapter modules. Install
adapter packages before building; the frozen executable does not search arbitrary
external Python installations for new modules.

Spinnaker binding inclusion is explicit:

```bat
REM First install the matching SDK-supplied cp312 Windows x64 wheel in .venv.
set BURST_BUNDLE_PYSPIN=1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean BURST.spec
```

Without that setting, the frozen build excludes PySpin; FLIR may still be reachable
through an installed compatible GenTL producer. With the setting, absence of the
requested wheel is a clear build error. The spec retains the Python binding but
filters Spinnaker runtime files from collected binaries/data. Install the **matching
Spinnaker runtime and drivers on the destination PC**. GenTL `.cti` producers also
remain external. No vendor SDK installer, license, DLL or producer is committed to
this repository. Review generated distribution contents and the vendor's current
redistribution terms before shipping an executable with its Python binding.

The Inno Setup installer packages BURST; it does not install camera SDKs/drivers.
Building without an SDK is supported, but installing a wheel beside an existing
executable does not retrofit its frozen Python environment. Rebuild with the adapter
or use a source installation. Spinnaker-enabled packaging needs validation on a
clean Windows PC with the target runtime, camera, and the matching Python binding.

## Everyday use of an installed BURST application

Users do not need this repository, Python, pip, or wheel files when their camera
adapter is included in the supplied BURST build. Install BURST and the required
vendor drivers/runtime, connect the camera, select Refresh Devices, choose the
camera and resolution, and start the preview. Close other camera applications first.

| Camera connection | What the user needs |
| --- | --- |
| Windows-compatible USB/UVC camera | Windows camera driver; BURST with OpenCV included. Controls and supported modes depend on the driver. |
| IC4 camera | BURST with IC4 support plus the compatible vendor runtime/drivers. |
| FLIR/Spinnaker camera | A Spinnaker-enabled BURST build plus the matching Spinnaker runtime/drivers. |
| Other GenTL camera | BURST with its GenTL bridge plus a compatible vendor GenTL producer and drivers. The installer must register its producer path; otherwise support must configure it once. |
| Micro-Manager camera | BURST with its Micro-Manager bridge, matching 64-bit device adapters and vendor drivers; select a saved `.cfg` in Camera Setup. |
| Other proprietary SDK | A BURST release containing an adapter for that SDK, plus its required runtime/drivers. Installing an arbitrary SDK alone cannot add support. |

The current BURST installer does not install vendor runtimes or provide an SDK
installation wizard. Distributors should provide the supported camera list and
matching runtime installer/version alongside each release. Hardware compatibility
and clean-machine installation must be checked before that release is distributed.

## Frame rate and trigger timing

BURST requests 10 FPS by default. Let the preview run for at least five seconds.
The preview shows measured delivery rate; recording readiness checks both delivery
and any reported configured/maximum rate. Measured delivery allows 5% tolerance.
A lower rate blocks recording and opens camera help with options to request 10 FPS,
stop and adjust acquisition resolution, use Mono8, shorten exposure, improve lighting,
or check the USB connection and vendor bandwidth settings. IC4, Spinnaker and GenTL
offer smaller sensor regions where available. These may crop the field of view;
the separate recording ROI does not reduce camera transfer bandwidth.

During recording, more than one second of unpaired force samples stops recording
and requests a device stop. Saved files are retained and marked for review. This
limits accumulating lag; it cannot guarantee alignment or recover missing frames.

**A passing rate check is not proof of synchronization.** The FLIR adapter currently
sets `TriggerMode=Off`: frames run independently of the Arduino. A missing trigger
cable prevents hardware-triggered exposure, but does not explain a reported 6.83 FPS
limit in this free-running configuration. Connecting a cable alone changes no software
settings. Hardware synchronization requires electrically compatible wiring, correct
trigger input/source/polarity configuration and validation of exposure-to-force timing.
That trigger workflow is not implemented by the rate check. Recordings currently pair
images and force samples in arrival order; metadata records this limitation and the
measured preview rate. Spinnaker diagnostics also expose rate, exposure, trigger and
available throughput settings in the help dialog and recording metadata.

## Hardware acceptance checks

Mocked tests cover discovery, missing SDKs, selection, capabilities, frame lifetime,
failure cleanup, ROI/mirroring, and TIFF/force recording. Before a hardware release:

- IC4: compare resolution/pixel formats, defaults, auto exposure/gain, frame rate,
  image intensity and long recordings against the prior release.
- FLIR/Spinnaker and each GenTL vendor: discover/start/stop/restart; disconnect;
  camera already in use; long runs; available manual/auto controls; grayscale and
  color conversion; repeated refresh and application shutdown.
- OpenCV: DirectShow and Media Foundation fallback, actual negotiated resolution,
  and USB disconnect behavior.
- Mixed cameras: unified labels, stable refresh selection, conservative duplicates.
- All paths: live ROI, both mirrors, synchronized force + TIFF recording, metadata,
  playback, and shutdown during/after a run.
