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
| Installed SDK adapter | A Python package registered in `burst.camera_backends`, plus that adapter's SDK |

The public GenTL bridge packages are included in the source requirements, but all
backends remain optional at runtime. An arbitrary proprietary SDK cannot be driven
without an API adapter. If it provides a compatible GenTL producer, the generic
backend can use it; otherwise an installed adapter implements the contract below.

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

`BURST.spec` bundles IC4, OpenCV and the GenTL bridge **when installed in the build
environment**. An absent SDK no longer aborts a development build. It also collects
installed `burst.camera_backends` entry-point metadata and adapter modules. Install
adapter packages before building; the frozen executable does not search arbitrary
external Python installations for new modules.

Spinnaker binding inclusion is explicit:

```powershell
# First install the matching SDK-supplied cp312 Windows x64 wheel in .venv.
$env:BURST_BUNDLE_PYSPIN = "1"
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
