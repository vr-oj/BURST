# BURST

**BURST** (BUTI Uniaxial Recording of Strain & Tension) is a Python application for synchronized acquisition of force data from the BUTI Arduino Box and live camera imaging. The app listens to the BUTI Arduino Box to stream force measurements, live plots force vs. time, and saves perfectly aligned recordings (CSV + TIFF stack) for later analysis.

---
## Quick Start

1. **Connect BUTI Arduino Box** – Select the BUTI Arduino Box COM port and click **Connect BUTI Arduino Box**.
2. **Set Up Camera** – Choose camera and resolution, then click **Start Camera**.
3. **Adjust Exposure/Gain** – Use the camera controls to fine-tune settings.
4. **Zero BURST** – Ensure the force reading is zeroed before recording.
5. **Start Recording** – Click **Start Recording** to begin synchronized acquisition.
6. **Stop Recording** – Click **Stop Recording** when the trial is complete.
7. **Playback & Export** – Open **Playback** to review the TIFF stack, overlay force data, and export frames.

---
## Features

### Real-Time Force + Video Recording
- The BUTI Arduino Box acts as the master clock, generating trigger pulses (`CamTrig`) for every frame.
- A matching serial message (`frame_index, time_s, force_value`) is emitted by the BUTI Arduino Box immediately after each pulse.
- BURST waits for the first BUTI Arduino Box tick before writing data, guaranteeing tight synchronization between force readings and captured frames.

### Live Force Plotting
- Streams force data from the BUTI Arduino Box at 460800 baud and renders a live trace with frame index, elapsed time, and force annotations.

### High-Speed Camera Preview & Control
- Integrates with The Imaging Source cameras via IC Imaging Control 4 (IC4).
- Lists connected USB3 Vision cameras and supported resolutions.
- Provides exposure, gain, and brightness sliders with instant visual feedback.

### Synchronized Output
- Recording folder structure:
  ```
  BURST_ROOT/YYYY-MM-DD/FillN/
      recording_*.csv   # Force + timing data
      recording_*.tif   # Grayscale stack, one frame per BUTI Arduino Box trigger
  ```
- Default save location is `~/Documents/BURST Results`. Set `BURST_RESULTS_DIR` (or the legacy `BUTI_RESULTS_DIR`) to override.
- Playback tools support zoom, pan, ROI selection, and exporting annotated frames.

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
1. Download the latest BURST release from the GitHub Releases page.
2. Extract the archive into a folder (e.g., `C:\Program Files\BURST`).
3. Install the IC4 SDK and GenTL Producer from The Imaging Source.
4. Launch `BURST.exe`.

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
   - Use **Acquisition → Start Recording** or press **Ctrl+R**.
   - BURST waits for the first BUTI Arduino Box tick before writing data.
5. Stop recording:
   - Use **Acquisition → Stop Recording** or press **Ctrl+T**. Files are finalized automatically.

---
## BUTI Arduino Box Firmware (BURST_v3_02)

- The BUTI Arduino Box firmware loops at a configurable interval (`startup.timeDelay`).
- The firmware toggles `CamTrig` HIGH→LOW to expose a single frame.
- Streams `frame_index, elapsed_time_s, force_value` from the BUTI Arduino Box over serial with microsecond precision.

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
