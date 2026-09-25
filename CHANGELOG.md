# Changelog

## 1.5.2

BURST integrates natively with IC4 cameras and the paired BUTI Arduino Box's
camera-trigger output. Micro-Manager integration is currently in testing as a
way to add cameras from other manufacturers.

- Prepare native IC4 cameras for Arduino-triggered recording independently of
  preview FPS. Verify a supported rate-limit disable switch, or select the highest
  camera-reported rate compatible with the current exposure when that switch is
  absent. Verify settings after stream start, restore preview FPS after recording,
  and save timing readback in the run manifest. Report preparation failures before
  starting the Arduino. Clarify configured camera speed versus received FPS.
- Document the validated native IC4/Arduino recording setup and label
  Micro-Manager integration as in testing for other camera/adapter combinations.
- Include the Micro-Manager preview compatibility updates and preview-only timing
  mappings from 1.5.1. Each camera/adapter combination still requires validation
  for Arduino-triggered recording.
- Add optional camera SDK plugins for labs, alongside unchanged built-in IC4 and
  Micro-Manager routes. API v1 exposes discovery, shared controls, original pixels,
  camera metadata and verified trigger transitions through the existing recorder.
- Load plugin SDKs in independent Python environments through isolated helpers.
  Include the bridge in packaged builds, with bounded, cancellable background
  discovery and an advanced plugin status/folder panel.
- Include a runnable simulated camera, developer guide and reusable preview
  validator. Automated checks do not certify a third-party camera's physical timing.

Validated on a DMK 37BUX250 with the paired Arduino: the 1.5.2-rc.1 test run saved
all 660 requested images and 660 force samples at approximately 10 FPS, with no
recording-integrity issues. Preview was set to 10 FPS and the camera's recording
operating rate was prepared automatically. See the
[camera validation record](buti_app/docs/micro-manager-validation.md) for the
test scope and remaining hardware checks.

## 1.5.1

- Allow Micro-Manager preview to use the configured camera settings when an
  adapter's trigger-mode names are unfamiliar or ambiguous. Verify actual frame
  delivery instead of rejecting the camera before acquisition. This applies to
  all adapters and adds no camera-specific mode lists.
- Allow saved preview-only timing assignments for custom configurations. External
  mappings still require preview assignments so BURST can restore preview after
  recording. Preview success does not imply that external triggering is configured.
- Give configuration and mapping guidance if no preview frames arrive. Keep
  trigger arming/readback checks and the explicit approximate-recording choice.

Reported on a Photometrics Kinetix22 with PVCAM 3.10.2 on a separate Windows computer.
Automated tests cover configured preview and mapped recording transitions; physical Kinetix22
preview and Arduino-triggered recording still require validation on that computer.

## 1.5.0

- Add optional Micro-Manager camera support alongside native IC4. Find compatible
  cameras or import a configuration, remember successful connections, and expose
  the adapter's available exposure, gain, automatic modes, frame rate and pixel
  format controls. Micro-Manager adapters and vendor drivers remain external.
- Run Micro-Manager discovery and acquisition in isolated helper processes so
  native adapter crashes do not close BURST. Discovery is cancellable and bounded,
  with partial results and guidance for cameras requiring manual configuration.
- Add reported binning, full-sensor acquisition and sensor ROI controls, plus
  optional saved property/trigger mappings and camera profile import/export.
- Keep preview free-running and configure/read back external triggering at the
  recording boundary. Prepare recording files before starting the Arduino, then
  restore preview with image settings preserved. Failed arming does not start the
  Arduino or silently select approximate recording.
- Follow Arduino Capture counter changes, including sparse capture and force-only
  samples. Preserve all force rows, associate requested images, and stop/report
  recording lag or invalid counters/timestamps. Approximate software pairing is
  an explicit advanced choice and is identified in recording metadata.
- Preserve full-resolution IC4 acquisition choices and avoid querying unsupported
  continuous-property increments. Request 10 FPS preview where supported and
  provide guidance for slower cameras and matching Arduino Capture settings.
- Clarify the main recording workflow with Run without recording, a cancellable
  Preparing state, and short reasons when recording is unavailable. Remove
  unsupported Home/Step buttons, label the read-only box dialog Box status, and
  explain ZERO and automatic Arduino start in the welcome instructions.
- Keep up/down arrows on exposure, gain, and frame-rate fields when a
  Micro-Manager adapter does not report limits. Apply typed values after editing,
  preserve camera readback, and keep sliders disabled until a range is available.
- Put Micro-Manager Camera Setup at the end of the Camera Device dropdown,
  including when no cameras are found, and remove its Acquisition menu entry.
- Simplify Micro-Manager camera setup to finding a camera or loading a saved
  configuration, with mappings and profile sharing under Advanced options and
  technical messages under Details. Native IC4 needs no Micro-Manager setup.
- Keep camera input rows readable when Micro-Manager controls or adapter warnings
  appear. Place camera properties and warning details in the settings heading
  and keep recording status on one line.
- Use native IC4 or Micro-Manager for camera connections. Retire the older OpenCV
  developer camera fallback; direct Spinnaker, GenTL and external Python camera
  plugins are not included in this release.
- Parse the BUTI v5.2 serial settings header and preserve its preload,
  deformation, rates, cycles, wire diameter, constant tension, and experiment
  type as appended columns in every sample row of the synchronized CSV. The
  same snapshot is retained in TIFF metadata and the run recovery manifest.

For synchronized recording, connect the Arduino trigger cable and use **ZERO on
the box before each run**. BURST follows the published firmware's Start/Stop
commands; experiment settings must be changed on the box. Image/row association
checks do not certify physical exposure timing. See the
[camera validation record](buti_app/docs/micro-manager-validation.md) for completed
checks and remaining hardware validation. This release targets Windows.

## 1.4.0

- Moved bounded diagnostic logging out of experiment results and into a clearly
  named local application-data folder, added a Help-menu shortcut to it, and
  made crash dialogs identify the exact file users should send for support.
- Added selectable, remembered recording-completion sounds with preview and a
  softer default cue.
- Changed Y-axis autoscaling to fit only force samples inside the visible
  X-axis window and refresh immediately when that window changes.
- Renamed newly created recording folders from `FillN` to `RunN` while
  reserving legacy `FillN` numbers for backward-compatible sessions.
- Combined post-recording file naming and the open-folder choice into one
  completion window.
- Replaced the remembered open-folder prompt with a direct **Open Run Folder**
  button in the completion window.
- Added a user-friendly integrity summary to that completion window, with
  counts, duration, final file sizes, warnings, and explanatory hover text.
- Added silent pre-recording readiness checks that only interrupt the user when
  a prerequisite fails.
- Added crash-safe partial outputs, an atomic run manifest, periodic flushing,
  and guided recovery of readable interrupted recordings on the next launch.
- Added an optional path-only **Open in BRAID** handoff, shown with the BRAID
  logo only when BRAID is installed; neither application depends on the other.

## 1.3.0

BURST 1.3.0 is a focused acquisition, playback, and interface release for the
BUTI Arduino Box and The Imaging Source camera workflow.

### Acquisition and hardware

- Restored reliable BUTI Arduino Box run-start signaling while preserving
  compatibility with firmware 5.2.
- Added first-recording session selection and daily session/Fill organization.
- Improved end-of-run detection for slower device packet cadences.
- Prompts to rename the synchronized CSV/TIFF pair before offering to open its
  folder.
- Added an optional recording-completion sound.

### Camera and live workspace

- Moved camera device, resolution, and Start Camera controls into the main
  toolbar, with Camera and Resolution selectors matching the Arduino port.
- Made camera orientation session-only so a previous flip cannot silently
  affect the next launch.
- Added source-pixel live ROI selection and consistent preview/TIFF transforms.
- Rebalanced the workspace around equal Camera and Plot views, compact
  side-by-side camera settings and capture options, a shallow BUTI status strip,
  and a prominent Start/Stop Recording control.
- Reorganized Plot Controls into clear X- and Y-axis modules.

### Playback and export

- Automatically detects a TIFF recording's neighboring synchronized CSV file.
- Loads large TIFF stacks lazily with bounded frame and preview caches.
- Supports drawn or exact pixel-coordinate ROI selection.
- Applies one shared ROI to a visible batch queue of up to five TIFF recordings
  without changing the originals or synchronized CSV files.
- Polished playback transport and scrubber controls.

### Updates and distribution

- Checks the official GitHub Releases page silently at startup and adds a
  manual **Help → Check for Updates…** command.
- Uses a single `buti_app/VERSION` source for the application, Windows metadata,
  installer, and release validation.
- Provides the established BURST PyInstaller/Inno Setup package, automated
  tests, installer checksum, and a repeatable local Windows release script for
  manual GitHub uploads.
