# BURST

**BURST** (BUTI Uniaxial Recording of Strain & Tension) is a Python application for synchronized acquisition of force data from the BUTI Arduino Box and live camera imaging. The app listens to the BUTI Arduino Box to stream force measurements, live plots force vs. time, and saves perfectly aligned recordings (CSV + TIFF stack) for later analysis.

---
## Quick Start

1. **Connect BUTI Arduino Box** – Select the BUTI Arduino Box COM port and click **Connect BUTI Arduino Box**.
2. **Set Up Camera** – Choose the camera and resolution from the main toolbar, then click **Start Camera**.
3. **Adjust Exposure/Gain** – Use the always-visible **Camera Settings** card above the live camera to fine-tune the full-width controls.
4. **Zero BURST** – Ensure the force reading is zeroed before recording.
5. **Choose a Session** – Select or create the session that will contain its Run folders.
6. **Start Recording** – Click the prominent red **Start Recording** button in the BUTI status strip to begin synchronized acquisition.
7. **Finish Recording** – BURST stops automatically when device data ends, plays the selected completion cue, and shows one window with recording-integrity details, paired-file naming, folder access, and an optional **Open in BRAID** action when BRAID is installed.
8. **Playback & Export** – Open **Playback** and select the TIFF; BURST finds its paired CSV automatically so you can review the stack, overlay force data, and export frames.

---
## Features

### Real-Time Force + Video Recording
- The BUTI Arduino Box acts as the master clock, generating trigger pulses (`CamTrig`) for every frame.
- A matching serial message (`frame_index, time_s, force_value`) is emitted by the BUTI Arduino Box immediately after each pulse.
- BURST waits for the first BUTI Arduino Box tick before writing data, guaranteeing tight synchronization between force readings and captured frames.

### Live Force Plotting
- Streams force data from the BUTI Arduino Box at 460800 baud and renders a live trace with frame index, elapsed time, and force annotations.
- Clears the previous trace once when the first packet of a new device run arrives.
- Detects the end of a run with an adaptive serial-silence timeout while keeping the port connected.

### High-Speed Camera Preview & Control
- Integrates with The Imaging Source cameras via IC Imaging Control 4 (IC4).
- Lists connected USB3 Vision cameras and supported resolutions.
- Provides exposure, gain, and brightness sliders with instant visual feedback.

### Synchronized Output
- Recording folder structure groups multiple runs into a named daily session:
  ```
  BURST_ROOT/YYYY-MM-DD/Session Name/RunN/
      trial_name_force.csv   # Force + timing data
      trial_name_video.tif   # Grayscale stack, one frame per BUTI Arduino Box trigger
  ```
- After a run closes, one optional base-name change is applied transactionally to both files.
- BURST performs a silent readiness check before acquisition. If every check
  passes, recording starts normally; if not, one message explains all items
  that need attention.
- Active files and a small run manifest remain marked as partial until both
  outputs close. BURST periodically flushes them and offers to validate and
  recover readable data after an interrupted app session.
- Default save location is `~/Documents/BURST Results`. Set `BURST_RESULTS_DIR` (or the legacy `BUTI_RESULTS_DIR`) to override.
- Playback tools support zoom, pan, drawn or exact pixel-coordinate ROI
  selection, exporting annotated frames, and cropping an ROI across the
  complete TIFF recording without changing the original recording or its
  synchronized CSV data. The same `X`, `Y`, `Width`, and `Height` can be
  batch-applied to a visible queue of up to five TIFF runs.
- Playback opens large TIFF stacks with bounded, on-demand frame and preview
  caches instead of expanding and pre-rendering the complete recording in RAM.
- A live ROI can also be selected before recording. Its source pixels are saved
  without resampling, and independent left/right and up/down flips apply to both
  the preview and TIFF output. Camera orientation starts unflipped on every app
  launch so a transform from an earlier session cannot silently carry over.
- Several bundled completion cues are available from the **Acquisition** menu,
  with a gentler default, instant preview, and a remembered selection.
- The post-recording integrity card summarizes frame/sample counts, duration,
  file sizes, continuity, and synchronization warnings. Hover over a metric or
  status for a more detailed explanation.
- When BRAID is installed, **Open in BRAID** launches the finalized TIFF using
  a generic file-path handoff. BURST and BRAID remain separate applications;
  each can still be installed and used independently.
- BURST silently checks the official GitHub Releases page after startup. A
  notification appears only when a newer version is available and links to the
  official installer download. **Help → Check for Updates…** runs the same
  check manually; offline automatic checks remain silent.

---
## Under the Hood

BURST relies on a hardware-triggered acquisition model driven by the BUTI Arduino Box:

| Component | Role |
|-----------|------|
| **BUTI Arduino Box** | Master clock that sends trigger pulses and serial messages |
| **Camera**  | Triggered by the BUTI Arduino Box `CamTrig` line |
| **App**     | Listens for the first BUTI Arduino Box message, then records video + CSV |

Each cycle:
1. The BUTI Arduino Box toggles `CamTrig` to expose the camera.
2. The BUTI Arduino Box emits synchronized serial data.
3. BURST pairs the frame with the force reading and saves both.

Key threads:
- **SerialThread** – Reads serial data from the BUTI Arduino Box and emits samples.
- **SDKCameraThread** – Manages the IC4 camera pipeline.
- **RecordingManager** – Writes CSV and TIFF files without blocking the UI.
- **PlaybackWindow** – Replays recorded data with optional force overlays.

---
## Installation

### Windows Executable
1. Download `BURST_Setup_<version>.exe` from the GitHub release.
2. Run the installer and follow the setup wizard.
3. Install the IC4 SDK and GenTL Producer from The Imaging Source.
4. Launch **BURST** from the Start menu or optional desktop shortcut.

Installed builds check for newer GitHub releases automatically without delaying
camera or serial startup. BURST never downloads or installs an update without
the user opening the official release page.

The current installer is not code-signed, so Windows SmartScreen may display an
unknown-publisher warning. An Authenticode signing certificate is required to
remove that warning for an official public release.

### From Source
1. Clone the repository:
   ```bash
   git clone https://github.com/vr-oj/BURST.git
   cd BURST
   ```
2. Create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   ```
3. Install dependencies:
   ```powershell
   .venv\Scripts\python.exe -m pip install -r buti_app\requirements.txt
   ```
4. Install the IC4 SDK and GenTL Producer (required for DMK cameras).

### Building a Windows Release Installer

BURST uses one version source: `buti_app/VERSION`. The current version is
`1.4.0`. Update only that file when preparing another release.

Install the requirements and pinned PyInstaller version once:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r buti_app\requirements.txt
.venv\Scripts\python.exe -m pip install pyinstaller==6.21.0
```

Install Inno Setup 6, then run the complete local release build:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
```

The script checks the Python environment, runs all tests, builds BURST with the
repository's PyInstaller spec, compiles the Inno Setup installer, and writes:

- `installer_output\BURST_Setup_1.4.0.exe`
- `installer_output\BURST_Setup_1.4.0.exe.sha256`

BURST releases are built on the target Windows packaging computer and uploaded
manually; GitHub Actions is not used. After the build passes hardware testing,
merge the release commit into `main`, create the matching `v1.4.0` tag and
GitHub release, paste the `1.4.0` section from `CHANGELOG.md`, and attach both
files above.

---
## Running BURST

1. Launch the app:
   ```powershell
   .venv\Scripts\python.exe buti_app\buti_app.py
   ```
2. Connect the BUTI Arduino Box:
   - Select the BUTI Arduino Box COM port (e.g., COM8) and click **Connect BUTI Arduino Box**.
   - Confirm the status badge reports *Connected*.
3. Configure the camera:
   - Pick the desired camera/resolution and click **Start Camera** for a live preview.
4. Start recording:
   - Use **Acquisition → Change Recording Session** to select or create the
     session used for subsequent Run folders.
   - Use **Acquisition → Start Recording** or press **Ctrl+R**.
   - BURST waits for the first BUTI Arduino Box tick before writing data.
5. Stop recording:
   - Let the device run finish naturally, or use **Acquisition → Stop Recording**
     / **Ctrl+T**. Files are finalized automatically, a completion sound plays,
     and BURST shows one completion window for reviewing integrity, renaming
     the CSV/TIFF pair, and opening the Run folder.
   - Choose a cue from **Acquisition → Completion Sound**. Selecting a cue plays
     a preview and BURST remembers it for future launches. The separate
     **Play Recording Completion Sound** option can silence the cue entirely.
   - The completion window includes an **Open Run Folder** button that can be
     used without closing the window.
   - If BRAID is installed, **Open in BRAID** applies the chosen paired-file
     name and opens the already-saved TIFF for analysis. Finishing the dialog
     without clicking it never launches BRAID.
6. Crop a recording (optional):
   - Open the recording in **Playback** and choose its TIFF. BURST automatically
     identifies the neighboring `<name>_force.csv` paired with
     `<name>_video.tif`.
   - Select **Draw ROI** or enter the exact source-pixel `X`, `Y`, `Width`, and
     `Height`, then choose **Apply ROI**.
   - Choose **Export Cropped TIFF** for the open recording, or add up to five
     TIFFs to **Batch Crop** and choose **Crop Selected TIFFs** to apply the
     shared bounds. Batch results are saved beside each source as
     `<original>_cropped.tif`; existing results are skipped. Original TIFFs and
     synchronized CSV files remain intact.

---
## Troubleshooting

| Issue                | Fix                                                     |
|----------------------|----------------------------------------------------------|
| Camera not listed    | Verify IC4 SDK + GenTL Producer are installed            |
| No serial data       | Check BUTI Arduino Box COM port selection and baud rate  |
| TIFF fails to open   | Use ImageJ/Fiji or Python `tifffile`                     |
| Dropped frames       | Use USB 3.0 and reduce resolution if bandwidth is tight |

---
## License

Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International  
<https://creativecommons.org/licenses/by-nc-sa/4.0/>
