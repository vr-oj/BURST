# Changelog

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
