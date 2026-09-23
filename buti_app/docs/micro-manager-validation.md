# Micro-Manager validation — 2026-09-23

Environment: Windows 11, Python 3.12, pymmcore 12.5.0.75.0, Device API 75 /
Module API 10, adapters in `C:\Program Files\Micro-Manager-2.0beta`.
These observations cover the installed adapter builds; they are not a blanket
claim about every release or camera.

| Camera / connection | Checked | Remaining |
| --- | --- | --- |
| Native IC4 / DMK 37BUX250 | Existing automated discovery, controls, default preview, arm/prepare/start ordering, recorder, playback and stop/restart regressions | Physical triggered recording against the release on this setup |
| MM DemoCamera / DCam | Actual native acquisition, metadata, exposure, sensor ROI/full sensor, 16-bit format, rejected 32-bit rollback and continued preview | Not a physical camera |
| MM SpinnakerC / Blackfly S BFS-U3-63S4M, serial 22096769 | Automatic discovery without a cfg; 3072×2048 Mono8 preview (19 frames in a three-second poll window); exposure/gain readback; automatic exposure/gain; Mono16; binning 2→1 (1536×1024→3072×2048); 640×480 sensor ROI→full sensor; FrameStart/Line0/RisingEdge/On readback; waiting without pulses; return to preview in about 0.84 s | Arduino-triggered recording, sparse Capture, missing-pulse detection with this hardware, exposure/force timing measurement |
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

The full 205-test automated suite passed, including the native DemoCamera test.
Automated coverage also exercises profile migration/import/export, explicit mapping
precedence, invalid mappings, integer/native units, missing bounds, dynamic locks,
helper crashes/timeouts/cancellation, duplicate identities, multiple serials,
unsupported layouts, sparse/None capture and counter/timestamp failures.
