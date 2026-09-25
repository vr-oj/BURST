# Camera integration validation — 2026-09-25

## Native IC4 and Arduino-triggered recording — 2026-09-25

Hardware: DMK 37BUX250 (serial 21420300), 2448×2048 Mono8, connected through native
IC4 and the paired BUTI Arduino Box's physical trigger cable.

Direct capability readback confirms that this camera has AcquisitionFrameRate
(1–75 Hz in this mode), but no AcquisitionFrameRateEnable switch. BURST verifies
a limiter disable when supported, or selects a compatible maximum
rate when the switch is absent, then restores the original preview setting.

A camera-only check confirmed 10 FPS preview → external trigger
with 75 Hz operating-rate readback → 10 FPS preview. No frames arrived while waiting
without pulses; preview resumed afterward. Exposure/gain auto modes were retained.
Readback also reported TriggerOverlap=ReadOut, IMXLowLatencyTriggerMode=False,
TriggerDelay=3.1 µs, ExposureTime=4368 µs and Gain=0 dB at arming. A subsequent
camera-only test delivered all 20 software-triggered images requested at 10 Hz
with this setup, then restored preview at 10 FPS. Software triggers do
not validate the electrical trigger cable or physical force/exposure offset.
No serial port was opened and no Arduino commands were sent during those camera-only checks.

The subsequent physical Arduino-triggered run used BURST 1.5.2-rc.1, session
`1.5.2-rc1`, Run1, on 2026-09-25. With preview set to 10 FPS, the manifest confirmed
75 Hz camera operating rate and FrameStart/RisingEdge/TriggerMode On. The run
saved 660 force samples and all 660 requested images over 65.9 seconds, with
0.1-second Arduino sample intervals and approximately 10 FPS image delivery.
All TIFF pages decoded as 2448×2048 Mono8; camera frame IDs were continuous from
0 through 659. There were no duplicate pixel pages, constant images, CSV/image
metadata mismatches, pending samples, or integrity issues. Host receipt minus
serial-processing time averaged 10.6 ms and ranged from 0 to 47 ms, with no growing
backlog during this run.

This validates the IC4 recording workflow on this setup. Host receipt
times and matching counts do not measure the physical force-to-exposure offset.
Other camera/adapter combinations and physical timing precision remain separate
validation tasks. The automated suite ran 221 tests with one native Micro-Manager
DemoCamera test skipped because compatible adapters were unavailable in that
test context; all remaining tests passed.

## PVCAM follow-up — 2026-09-25

A user reported PVCAM preview startup failing on a separate Windows computer.
The vendor utility identifies a Photometrics Kinetix, 2400×2400, USB 3.0, PVCAM
3.10.2 and camera firmware 30.51; the user identified the model as Kinetix22.
The BURST 1.5.0 error was traced to its preview
translator accepting only Off/Internal and rejecting PVCAM's other native names.

BURST 1.5.1 tries configured preview for any adapter with unfamiliar or ambiguous
trigger properties instead of adding camera-specific mode lists. Test doubles
cover unfamiliar enums, unchanged preview settings, actual frame delivery and
no-frame timeout, preview-only mappings, repeat mapped arm/restore, preserved
exposure/gain and post-start readback changes. Unsupported external arming still
fails; a preview-only mapping does not authorize recording. These tests do not exercise a
physical PVCAM camera. Preview, actual pulses, sparse capture, stop without pulses
and force/exposure timing on the Kinetix22 remain unvalidated.

## Original hardware checks

Environment: Windows 11, Python 3.12, pymmcore 12.5.0.75.0, Device API 75 /
Module API 10, adapters in `C:\Program Files\Micro-Manager-2.0beta`.
These observations cover the installed adapter builds; they are not a blanket
claim about every release or camera.

| Camera / connection | Checked | Remaining |
| --- | --- | --- |
| Native IC4 / DMK 37BUX250 | Automated discovery, controls, preview, arm/prepare/start ordering, recorder, playback and stop/restart regressions; 1.5.2-rc.1 physical Arduino-triggered run with 10 FPS preview and 660/660 images saved (details above) | Physical force/exposure offset measurement and broader hardware acceptance checks |
| MM DemoCamera / DCam | Actual native acquisition, metadata, exposure, sensor ROI/full sensor, 16-bit format, rejected 32-bit rollback and continued preview | Not a physical camera |
| MM SpinnakerC / Blackfly S BFS-U3-63S4M, serial 22096769 | Automatic discovery without a cfg; 3072×2048 Mono8 preview (9 frames in a three-second poll window); exposure/gain readback; automatic exposure/gain; Mono16; binning 2→1 (1536×1024→3072×2048); 640×480 sensor ROI→full sensor; FrameStart/Line0/RisingEdge/On readback; waiting without pulses; return to preview in about 0.89 s | Arduino-triggered recording, sparse Capture, missing-pulse detection with this hardware, exposure/force timing measurement |
| MM TIScam / IC4 hardware | Adapter translation and stop-without-pulses behavior covered with test doubles | Compatible legacy driver/configuration and physical acquisition test |

The user confirmed that the trigger cable is connected to the IC4 camera, not
the FLIR. No Arduino commands were sent during the FLIR checks. The camera was
returned to its original image settings after the control test.

The first restricted-process probe could enumerate a USB camera but could not read
its identity. Running the same helper with USB device access found the correct model
and serial and delivered images. This was a test-environment access restriction,
not evidence of a missing trigger cable or unsupported camera.

The FLIR adapter returns rounded numeric properties (for example a requested gain
of 3 reads back as 2.9996). BURST retains actual readback. A rounded maximum FPS must
not be unnecessarily written back to the camera; regression coverage checks this
rollback case. No supported range is inferred from the observed values.

Metadata observed from SpinnakerC includes MM image number, host elapsed time,
receipt time, dimensions and ROI tags. These remain adapter diagnostics. They are
not camera exposure timestamps or trustworthy physical frame counters. Camera
settings/readback and matching video/CSV counts do not certify physical timing.

After removing the direct Spinnaker, GenTL and OpenCV camera integrations and their
obsolete tests, all 188 tests passed, including the native DemoCamera test.
Automated coverage also exercises profile migration/import/export, explicit mapping
precedence, invalid mappings, integer/native units, missing bounds, dynamic locks,
helper crashes/timeouts/cancellation, duplicate identities, multiple serials,
unsupported layouts, sparse/None capture and counter/timestamp failures.

The real SpinnakerC check was repeated after that removal with imports of PySpin,
OpenCV, Harvester and the Python GenICam binding deliberately blocked in both the
parent and helper. Discovery, preview, the controls listed above, no-pulse arming
and return to preview succeeded; no control or restoration errors were reported.
The adapter reported 3.2395 FPS at the start of this check; the short preview proves
acquisition, not sustained 10 FPS or synchronized recording.

The first repeat failed to load the adapter because the test terminal had inherited
obsolete runtime paths from before the vendor SDK installation. Using the current
Windows machine/user PATH resolved loading without copying DLLs or restoring a
vendor-specific search in BURST. No persistent Windows environment settings were
changed. Restart terminals/launchers after installing a vendor runtime.
