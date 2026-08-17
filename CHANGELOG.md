# Changelog

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
