# Camera backends and SDK installation

BURST discovers every available backend at startup and when **Refresh Devices** is
clicked. Select a camera and acquisition mode, then **Start Camera**. A manufacturer
selection is not required. Stop the current stream before refreshing or changing
devices. Missing/broken optional SDKs are reported in the diagnostic log, not in
startup dialogs.

| Backend | Camera/runtime requirements |
| --- | --- |
| Native IC4 | The Imaging Source runtime/drivers and `imagingcontrol4` |
| Micro-Manager | `pymmcore`, compatible 64-bit Micro-Manager device adapters and vendor drivers; automatic camera setup where supported, otherwise a saved `.cfg` |
| Lab SDK plugin | A developer-provided BURST camera API v1 plugin, its own Python environment, SDK bindings and vendor drivers |

IC4 remains the default native integration; everyday users can connect other
cameras through Micro-Manager. Labs with developers can instead provide a direct
SDK plugin, described in the [camera plugin guide](camera-plugins.md). Installing
a vendor SDK alone does not create a connection: its Micro-Manager adapter or a
BURST plugin must expose the required features. All routes are optional at runtime.

## Micro-Manager setup for installed BURST

1. Install compatible **64-bit Micro-Manager** and the vendor drivers required by
   its camera adapter. Confirm your camera works in Micro-Manager's Live view.
2. Close Micro-Manager and other camera programs. In BURST open
   the **Camera Device** dropdown and choose its last item, **Micro-Manager Camera Setup…**.
   Stop the camera first if it is streaming. The installation from
   a saved connection is reused; BURST also looks in standard installation folders.
   Use **Change folder…** if needed and choose **Find cameras**. IC4 cameras
   connect directly and do not require this setup.
3. Discovery checks adapters in separate helper processes, with a ten-second
   request budget per adapter and a sixty-second search budget (plus process cleanup).
   **Cancel search** keeps results already found. SpinnakerC model/serial choices
   and adapters implementing device detection can identify cameras automatically.
   No configuration values, serial numbers or hub connections are guessed.
   Setup shows a short result; **Details…** contains missing SDKs, adapter/API
   errors and initialization requirements.
   An installation is usable only when its adapter actually loads with BURST's MMCore.
4. If your camera needs additional setup, native dialogs or other devices, save a
   camera hardware configuration (`.cfg`) from Micro-Manager in a permanent user
   folder. Prefer a camera-only configuration: loading it initializes **all** devices
   named in it. Choose **Load configuration…** and select that file; BURST loads
   and checks it automatically.
   Discovery/configuration loading does not certify image acquisition or timing. Select a camera, click
   **Add camera**, then **Save**. Multiple configurations can be saved;
   the same dialog removes saved entries without deleting any files.
5. Select the saved Micro-Manager entry from **Camera Device** and start the preview.
   The resolution selector shows the dimensions read during setup, or says that
   resolution will be read on start for older saved profiles. It updates to the
   opened camera's actual dimensions. During preview **Resolution** also offers
   reported binning choices, **Full sensor**, and **Custom sensor region…** where
   available. These affect camera acquisition; the separate recording crop only
   changes saved images. Geometry and pixel type initially come from the connection.
   Let delivery stabilize before recording. The preview rate
   readiness check and recording lag guard apply.

BURST stores discovered connections, mappings and configuration **paths** in per-user settings. It does not copy or
modify the `.cfg`; leave it and its referenced resources in place. Saved entries
are candidates, not a claim that the camera is connected. Refreshing devices does
not load a Micro-Manager configuration or initialize microscope hardware.

Micro-Manager's native libraries run in a separate helper process during both setup
and acquisition. This keeps them separate from Qt and BURST's native IC4 integration.
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
Controls lock during recording. MMCore's standard exposure interface supplies
milliseconds to the existing exposure UI. Documented aliases map gain, automatic
modes, FPS and pixel format into the normal controls. Ambiguous names are left
unmapped with an explanation. Gain uses documented units (SpinnakerC: dB), or
**camera units** when unknown. Writable numeric controls without reported limits
use numeric fields with up/down arrows and a disabled slider. Type a value and
press Enter (or leave the field), or use the arrows; BURST shows the camera's
readback. The camera validates values when its limits are unknown. BURST does
not invent a camera range.
Controls locked only during streaming can be changed by briefly stopping preview;
permanently read-only and initialization properties stay disabled. Applied values
come from camera readback, including quantization. Unsupported layouts are rejected
and the previous setting/preview is restored; failed restoration is reported.

**Advanced options → Advanced camera mapping…** in setup is optional. Select a saved camera, choose
existing properties and their native units, and assign native automatic/manual
enum values. Two timing tabs support ordered property/value assignments for preview
and external triggering. Leave both empty for automatic timing setup. These contain
data only, never scripts. Timing mappings must not change mapped image controls.
BURST validates the connected adapter's property names and values before using a
mapping, and checks readback again when arming. Invalid mappings cannot start the box.

Saved mappings take precedence over documented aliases. **Export profile…**
and **Import profile…** under Advanced options share the connection/mapping as JSON. The receiving
lab still needs compatible drivers/adapters and must select its own installation,
configuration path and camera serial. After import, verify the local paths, choose
**Check configuration**, add the camera, then Save. Advanced mapping can repair a stale imported or saved mapping.
Legacy profiles remain readable. Nothing needs copying into Program Files/BURST.
Explicitly saved MM entries remain selectable even when a native SDK also lists
that camera. Discovery deduplicates only by reliable vendor/serial identity or the
same connection.

The source/build requirements pin `pymmcore==12.5.0.75.0` (MMCore 12.5.0,
device API **75**, module API **10**). Micro-Manager adapters must match that API
and architecture. Installing an older Micro-Manager release or a mismatched SDK
can fail even when its own GUI works. The setup error reports the bridge's required
API. End users of a packaged build do not install Python or wheels; the release
must include the bridge. Source users update their environment with Command Prompt:

```bat
.venv\Scripts\python.exe -m pip install -r buti_app\requirements.txt
```

Acquisition uses MMCore's dedicated continuous-acquisition API and sequence buffer,
detects reported overflow, and copies images
before native buffers can be reused. Supported images are single-channel 8/16-bit
monochrome and packed 32-bit RGB. High-bit-depth monochrome is scaled for the 8-bit
preview while the original source pixels are preserved separately for TIFF recording.
Float, RGB64, packed monochrome and multi-camera/channel payloads fail with an explanation instead of
being interpreted incorrectly.

Software pairing uses Off/Internal triggering when the adapter exposes a recognized
TriggerMode property. Arduino trigger mode requires a supported trigger interface or validated timing
mapping, as described below. An unavailable interface fails arming with guidance. The configured source waits for pulses without the software
preview timeout. MMCore's nominal sequence interval does not reliably set camera FPS.
BURST requests 10 through AcquisitionFrameRate where exposed. Measured delivery and
requested-image accounting remain separate from physical timing validation.

References: [Micro-Manager Python integration](https://micro-manager.org/Using_the_Micro-Manager_python_library),
[supported hardware](https://micro-manager.org/Device_Support),
[MMCore API](https://micro-manager.org/apidoc/MMCore/latest/class_c_m_m_core.html).

## FLIR cameras through Micro-Manager

1. Install the vendor runtime/drivers required by your Micro-Manager adapter.
   The tested Blackfly S uses Micro-Manager's **SpinnakerC** device adapter and
   the installed Spinnaker runtime. Confirm preview in Micro-Manager, then close it.
2. In BURST's Micro-Manager Camera Setup, choose **Find cameras**, or import the
   camera's working `.cfg`, then add and save the connection.
3. Select the **Micro-Manager** camera entry and start preview. Controls come from
   that adapter. SpinnakerC's property names and units are mapped to BURST's normal
   controls; BURST does not load the camera through a separate native FLIR backend.

No PySpin wheel is needed for this connection. Leave Micro-Manager's adapter DLLs
in its installation and use the vendor installer for runtime dependencies. Do not
copy DLLs or wheels into BURST's installation folder. See the
[SpinnakerC adapter instructions](https://micro-manager.org/SpinnakerC) for matching
adapter/runtime requirements and [tested combinations](micro-manager-validation.md).

## Controls and runtime discovery

Exposure is displayed in milliseconds (controller values are microseconds), gain
in documented adapter units or **camera units**, and frame rate in Hz. Controls
are enabled only when supported and writable. Camera writes execute in the
acquisition worker; the UI reads detached capability snapshots. Recording disables
changes. A writable numeric property without reported bounds supports numeric
entry with its slider disabled.

The vendor installer should configure its runtime dependencies. If a helper reports
missing dependent DLLs, **BURST_CAMERA_DLL_PATH** can supply additional runtime
folders, separated by semicolons on Windows. BURST does not scan vendor SDK folders
or load GenTL producers directly. Restart BURST and reopen the terminal or launcher
after installing drivers or changing runtime paths; an already-running terminal may
still pass obsolete paths to the camera helper.

`BURST_CAMERA_BACKEND` / `BUTI_CAMERA_BACKEND` are optional diagnostic filters:
`auto` (default) or `all` enables IC4, Micro-Manager and installed camera plugins;
`ic4`, `micromanager` or `plugin:your_plugin_id` selects one connection. A comma-separated list is also accepted. Removed backend
names do not fall back to another integration; clear an old filter to restore the
normal camera list. Normal use needs no environment settings.

## Windows executable packaging

`BURST.spec` bundles `imagingcontrol4` and `pymmcore` when installed in the build
environment. An absent optional bridge does not abort a development build, but
releases must include the bridges for the advertised camera connections. The build
excludes the removed direct Spinnaker, GenTL and OpenCV capture packages, even if
left installed in the developer's environment. Camera API v1 plugins use their
own Python/SDK environments; the packaged application includes their bridge as
source resources. The earlier experimental in-process backend plugin mechanism
is not supported.

The Inno Setup installer packages BURST; it does not install camera SDKs/drivers or
Micro-Manager. Users install compatible Micro-Manager adapters and their vendor
runtime dependencies separately. Adding a camera through an existing compatible
Micro-Manager adapter does not require a new BURST build or a Python wheel. An
arbitrary SDK cannot be added to an installed BURST executable by copying files
beside it. Test the packaged application on a clean Windows PC before distribution.

## Everyday use of an installed BURST application

Users do not need this repository, Python, pip, or wheel files. Install BURST and
the required camera software, close other camera programs, and connect the camera.

| Camera connection | What the user needs |
| --- | --- |
| Native IC4 camera | BURST with IC4 support plus the compatible vendor runtime/drivers. Refresh Devices, select the camera and start preview. |
| Micro-Manager camera | BURST with its Micro-Manager bridge, matching 64-bit device adapters and vendor drivers. Use Find cameras or select a saved `.cfg` in Camera Setup; BURST remembers the connection. |

A camera needs a compatible adapter exposing the required controls. Cameras with
unavailable trigger controls can use explicitly selected approximate pairing; they
cannot provide Arduino-triggered recording through an unsupported interface.
Distributors should document tested camera/adapter/runtime combinations alongside
each release. Hardware compatibility and clean-machine installation must be checked
before that release is distributed.

## Frame rate and trigger timing

BURST requests 10 FPS for preview by default. Recording uses the Arduino's
trigger-counter transitions rather than assuming one image per force sample.
Read [Arduino compatibility](arduino.md) for the firmware protocol and rate setup.

In **Follow box Capture** mode, every force sample is saved. A counter increase
requests one associated image; repeated counters intentionally request none.
In approximate software mode, the first row is only a baseline because its trigger
phase is unknown. Triggered recording instead requires a zeroed box counter and
includes the first image when the first reported counter is 1. A constant
counter produces a CSV with no TIFF. This follows the box's emitted requests,
including capture changes, without pretending to read its menu selections.

For a camera delivering 6.84 FPS, BUTI v5.1/v5.2 Advanced settings → Delay (ms) = 200
requests approximately 5 force samples/second. Capture Every then requests about
5 images/second. Alternatively, at Delay = 100 and Capture 1 in 5, all approximately
10 force samples/second are saved with about 2 images/second. The actual rates are
observed from device timestamps and counters; they are not remotely configurable.

A slow preview prompts guidance before recording. A warm preview is required for
software image recording; a configured, armed camera is required in trigger mode. During acquisition, more than one second of outstanding requested
images stops recording and requests a device stop. Backwards/nonadvancing device
time or a backwards counter also stops recording for review. Gaps in trigger counts
are reported. These checks cannot establish exposure synchronization.

Start Camera always opens live preview. Start Recording automatically switches to
Arduino triggering before starting the box, then Stop Recording returns to preview
without reopening the camera or resetting image settings. GenICam backends request
FrameStart, RisingEdge and the selected physical input and verify them after arming. BURST reuses a selected Line
input or chooses the only available Line input; ambiguous inputs require one-time
setup in camera properties/vendor tools. No typed trigger-name prompt is part of
normal recording. Physical wiring is still required and cannot be detected by this check.

The DMK 37BUX250 has a fixed `TRIGGER_IN` and no `TriggerSource` property. Its IC4
backend verifies the mode, frame-start selector and edge; the manifest records the
documented fixed input separately from actual property readback.

Micro-Manager is a separate camera connection, not a wrapper around BURST's IC4
backend. Its device adapter determines the controls available to BURST:

- GenICam adapters can expose `TriggerMode` or `Trigger Mode` (and corresponding
  source, selector and activation properties). BURST translates these names;
  SpinnakerC uses the spaced names. Its `Frame Rate` control also drives BURST's FPS control.
- TIScam uses `TriggerMode = Internal/External`. BURST switches that control and
  verifies it again after sequence acquisition starts. Input selection, frame-start
  semantics and edge polarity are not exposed through this adapter. Configure and
  validate those in the camera's native settings; the manifest lists them as
  unexposed, not verified. TIScam requires its own compatible TIS drivers; installing
  IC4 alone does not establish TIScam compatibility. Its pulse-wait is released before
  stopping a sequence, and images from that transition are excluded from recording.
- Other adapters can preview using their configured settings and expose their
  native properties. Unfamiliar or ambiguous trigger-mode names do not block
  preview; BURST attempts acquisition and checks that frames arrive. If needed,
  verify Live in Micro-Manager, close it, and load that camera configuration in
  BURST. Custom preview assignments can be saved independently under Advanced
  camera mapping; custom external assignments require preview assignments too,
  so BURST can restore preview. A successful preview does not validate triggering. An
  unrecognized trigger interface reports that limitation rather than treating a
  missing property as proof the camera lacks hardware triggering.

The same recorder associates images and Arduino rows for every backend. Adapter
readback and automated tests do not replace a triggered hardware acceptance run,
including stop/restart with no arriving pulses, for each adapter/camera combination.

Unsupported cameras can preview normally and remain usable through
**Acquisition → Advanced → Allow approximate software pairing**, with explicit
consent and visible timing labels. This choice resets when switching cameras or
restarting BURST; failures never silently fall back. Use ZERO on the box before each
triggered run. Hardware mode buffers either arrival order and checks native frame
IDs where supplied by the camera connection (currently native IC4). See the Arduino
guide for remaining detection limits and required physical timing validation.

TIFF metadata identifies the force sample associated with each saved page and the
saved image index. Playback uses this association for sparse recordings. Host
receipt/processing timestamps are diagnostic only; they are not exposure timestamps.
MMCore's image tags are retained under `pixels.camera_metadata.micro_manager` in
TIFF metadata. `ImageNumber`, `ElapsedTime-ms` and `TimeReceivedByCore` are **not**
promoted to hardware frame IDs or exposure timestamps. The genuine hardware ID field
remains empty when the adapter does not supply one. Matching counts are association
checks, not physical timing certification.
Owned monochrome 8/16-bit data from IC4 and Micro-Manager are recorded independently
of the 8-bit preview. Color conversion paths may save RGB8; per-page metadata states
whether native depth was preserved.

## Hardware acceptance checks

Mocked tests cover discovery, missing SDKs, selection, capabilities, frame lifetime,
failure cleanup, ROI/mirroring, and TIFF/force recording. Before a hardware release:

See [recorded Micro-Manager validation](micro-manager-validation.md) for tested
camera/adapter combinations and outstanding physical tests.

- IC4: compare resolution/pixel formats, defaults, auto exposure/gain, frame rate,
  image intensity and long recordings against the prior release.
- Each Micro-Manager camera/adapter combination: discover/start/stop/restart; disconnect;
  camera already in use; long runs; available manual/auto controls; grayscale and
  color conversion; repeated refresh and application shutdown.
- Mixed cameras: unified labels, stable refresh selection, conservative duplicates.
- All paths: live ROI, both mirrors, associated force + TIFF recording, metadata,
  playback, and shutdown during/after a run.
