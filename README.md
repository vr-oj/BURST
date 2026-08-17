# BURST

**BURST** (BUTI Uniaxial Recording of Strain & Tension) is a Python application for synchronized acquisition of force data from the BUTI Arduino Box and live camera imaging. The app listens to the BUTI Arduino Box to stream force measurements, live plots force vs. time, and saves perfectly aligned recordings (CSV + TIFF stack) for later analysis.

---
## Quick Start

1. **Connect BUTI Arduino Box** – Select the BUTI Arduino Box COM port and click **Connect BUTI Arduino Box**.
2. **Set Up Camera** – Choose camera and resolution, then click **Start Camera**.
3. **Adjust Exposure/Gain** – Use the camera controls to fine-tune settings.
4. **Zero BURST** – Ensure the force reading is zeroed before recording.
5. **Choose a Session** – Select or create the session that will contain its Fill folders.
6. **Start Recording** – Click **Start Recording** to begin synchronized acquisition.
7. **Finish Recording** – BURST stops automatically when device data ends, plays a completion chime, and offers one name for the CSV/TIFF pair.
8. **Playback & Export** – Open **Playback** to review the TIFF stack, overlay force data, and export frames.

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
- Recording folder structure groups multiple fills into a named daily session:
  ```
  BURST_ROOT/YYYY-MM-DD/Session Name/FillN/
      trial_name_force.csv   # Force + timing data
      trial_name_video.tif   # Grayscale stack, one frame per BUTI Arduino Box trigger
  ```
- After a fill closes, one optional base-name change is applied transactionally to both files.
- Default save location is `~/Documents/BURST Results`. Set `BURST_RESULTS_DIR` (or the legacy `BUTI_RESULTS_DIR`) to override.
- Playback tools support zoom, pan, ROI selection, exporting annotated frames,
  and cropping an ROI across the complete TIFF recording without changing the
  original recording or its synchronized CSV data.
- A live ROI can also be selected before recording. Its source pixels are saved
  without resampling, and independent left/right and up/down flips apply to both
  the preview and TIFF output.
- A bundled completion chime is enabled by default and can be muted from the
  **Acquisition** menu.

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
1. Download `BURST_Setup_<version>.exe` from the GitHub release or Actions artifact.
2. Run the installer and follow the setup wizard.
3. Install the IC4 SDK and GenTL Producer from The Imaging Source.
4. Launch **BURST** from the Start menu or optional desktop shortcut.

The current installer is not code-signed, so Windows SmartScreen may display an
unknown-publisher warning. An Authenticode signing certificate is required to
remove that warning for an official public release.

### From Source
1. Clone the repository:
   ```bash
   git clone https://github.com/vr-oj/BUTI-acquisition.git
   cd BUTI-acquisition/buti_app
   ```
2. Create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Install the IC4 SDK and GenTL Producer (required for DMK cameras).

### Building a Windows Test Installer

BURST uses one version source: `buti_app/VERSION`. The current version is
`1.3.0`. Update only that file when preparing another release.

To build the installer directly on Windows:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r buti_app\requirements.txt
.venv\Scripts\python.exe -m pip install pyinstaller==6.21.0
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean BURST.spec
iscc installer.iss
```

The installer will be written to
`installer_output\BURST_Setup_1.3.0.exe`.

Once this workflow exists on the default branch, **Actions → Build Windows
Installer → Run workflow** can also build any selected branch. A manual run
creates a short-lived installable artifact without creating a GitHub release.

After the build passes hardware testing, merge it into `main`, then create and
push the matching tag (`v1.3.0`). The tag must point to the release commit and
exactly match the application version with a leading `v`; the build will reject
mismatches and a valid tag will create the GitHub release.

---
## Running BURST

1. Launch the app:
   ```bash
   python buti_app.py
   ```
2. Connect the BUTI Arduino Box:
   - Select the BUTI Arduino Box COM port (e.g., COM8) and click **Connect BUTI Arduino Box**.
   - Confirm the status badge reports *Connected*.
3. Configure the camera:
   - Pick the desired camera/resolution and click **Start Camera** for a live preview.
4. Start recording:
   - Use **Acquisition → Change Recording Session** to select or create the
     session used for subsequent Fill folders.
   - Use **Acquisition → Start Recording** or press **Ctrl+R**.
   - BURST waits for the first BUTI Arduino Box tick before writing data.
5. Stop recording:
   - Let the device run finish naturally, or use **Acquisition → Stop Recording**
     / **Ctrl+T**. Files are finalized automatically, a completion sound plays,
     and BURST offers to rename the CSV/TIFF pair.
6. Crop a recording (optional):
   - Open the recording in **Playback**, select **Draw ROI**, drag over the
     region to retain, and choose **Export Cropped TIFF**. BURST writes a new
     raw TIFF stack and leaves the original TIFF and synchronized CSV intact.

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
