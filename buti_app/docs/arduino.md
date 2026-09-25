# Arduino compatibility and camera timing

BURST adapts to the published BUTI v5.1/v5.2 protocol. Firmware reviewed:
[DrN8PhD/BUTI, revision ab190510](https://github.com/DrN8PhD/BUTI/tree/ab1905103b0c22400b254295f509f1d727680827).
BURST does not flash or alter the box. Its bundled v4.0 sketch is historical;
its menu behavior must not be assumed to describe newer installed firmware.

## What can be controlled remotely

- **Run without recording / Start Recording** sends `G`. **Stop Device / Stop Recording** sends `S`.
  Start Recording prepares the camera and files before starting the box;
  Run without recording saves no files.
- **Box status…** shows the last received experiment header and observed cadence.
- Remote **Home** is unavailable: published v5 firmware has no `H` handler. Use Home on the box.
- The former **Reset** button is replaced by Box status. `R` starts execution and
  resets the time origin; it is not the onboard Zero action and is not sent.
- Remote **Step** is unavailable pending firmware fixes to its timestamps and trigger counter.
  Unsupported Home and Step controls are not shown on the main panel.

The firmware has no settings-query/set protocol, no firmware-version report and no
command acknowledgement. BURST cannot implement automatic bidirectional menu
synchronization without firmware support. Change box settings on the box. BURST
displays what the box reports, replaces header snapshots instead of retaining stale
omitted values, and clears them on transport reconnection. Unreported values remain
unknown. A queued Start/Stop command is not proof that the box executed it.

## Sampling and Capture

In v5.1/v5.2 Advanced settings, **Delay (ms)** sets the requested sample interval:
100 ms is about 10 force samples/second; 200 ms is about 5. Actual timing also depends
on ADC averaging and the firmware workload. BURST observes actual device timestamps.
The separate **Samples** setting controls averaging, not the output sample rate.

**Capture** divides camera trigger requests, not force samples. Every requests one
image per sample; 1 in 5 requests one per five samples; None emits no capture requests.
BURST follows increases in the transmitted Frame counter rather than guessing the
menu value. Repeated counters are valid. An unchanged counter alone cannot prove
that None was selected, so the displayed selection remains unknown until measured.

Under Acquisition → Advanced → BURST recording mode:

- **Follow box Capture:** keep every force row and save images for trigger-counter
  increases. A run with no requested images produces CSV only, with no empty TIFF.
- **Force only:** save all force rows without requiring a camera. This is a BURST
  output choice and does not change the box's trigger output.

The CSV retains the original five columns first, then adds `sample_index` and
`image_requested`, followed by available experiment metadata. TIFF pages carry the
associated sample index, saved-image index and force value. Playback uses page
associations for sparse recordings. External analysis software must support these
associations; do not assume equal CSV-row and TIFF-page counts.

## Preview and recording

Start Camera opens a normal live preview for exposure/gain and ROI adjustment.
Start Recording automatically stops the preview stream, enables and verifies
Arduino triggering, opens a fresh recorder, and then sends G. Preview images cannot
enter that recording. Stop Recording drains the recording before restoring preview
on the same open camera, preserving exposure/gain and other image settings.
Arduino-triggered recording is the default. BURST never silently changes modes after failure.

For native IC4 cameras, preview FPS is separate from Arduino recording cadence.
Before arming, BURST disables the camera's frame-rate limiter when that switch is
available. Otherwise it selects the highest rate reported for the current image
format/resolution, capped to preserve the current exposure. This handles cameras
such as DMK 37BUX250 that expose AcquisitionFrameRate without
AcquisitionFrameRateEnable. BURST verifies rate and manual image settings again
after acquisition starts, and restores the user's preview rate when recording
ends. A rejected setting or changed readback prevents the Arduino from starting.
The run manifest records `trigger_rate_control`, including unavailable properties.
The camera card's receiving FPS measures delivered images; a camera operating at
75 FPS can deliver 10 triggered images per second when the box requests 10.
Exposure/readout and transfer capacity still limit the trigger cadence that a
particular camera can sustain. Micro-Manager and plugin timing remain governed by
their supported adapters and mappings.

**Software pairing (approximate):** explicitly enable **Acquisition → Advanced →
Allow approximate software pairing** when this limitation is acceptable. The choice
resets when changing cameras or restarting BURST. It works with free-running cameras
exposed by a supported IC4 or Micro-Manager connection. No trigger cable is required. BURST associates the next
available image in arrival order with each requested sample. The first row only
establishes the trigger-counter baseline and has no image association. Different
camera/serial delivery delays remain; equal counts do not prove timing alignment.

**Arduino hardware trigger:** requires a camera with an external frame-trigger
input, electrically compatible wiring, a supported adapter, and a validated setup.
BURST reuses the camera's selected physical Line input, or selects its only available
physical Line input. If several inputs exist and none is selected, configure the wired
input once in Camera properties or the vendor utility. BURST cannot detect which
wire is connected. GenICam interfaces request FrameStart / RisingEdge / that input /
TriggerMode On and verify readback after acquisition starts. The IC4 DMK 37BUX250
uses its documented fixed input instead of a selectable source. Micro-Manager
translates its adapter's property names; TIScam uses Internal/External and cannot
report the input, selector or edge. Those settings require native configuration and
validation and are listed as unexposed in the manifest. See [camera adapter details](cameras.md#frame-rate-and-trigger-timing).
Incompatible trigger interfaces report an error. Connected cameras without a
supported trigger interface remain usable in Software pairing mode.

Use **ZERO on the box** before each triggered recording and keep the box stopped
while BURST arms. The normal preview runs before recording; once armed, the camera
waits for box pulses without reporting a preview timeout. After the
recorder is ready, BURST sends G. The first counter must be 0 or 1; otherwise BURST
stops. Images and serial events are buffered in either arrival order. Pending events
over one second, extra images, counter gaps or time resets are errors requiring
review. Where the SDK provides camera frame IDs, gaps, duplicates and resets stop
recording before the unexpected image is paired; IDs are retained in TIFF metadata.
Adapters that do not expose these IDs still use event-count and timeout checks.
Neither method can certify an undetected missed initial pulse or simultaneous losses
in both streams. At stop, a short drain interval allows in-flight events to arrive. Exposure
or serial delays exceeding one second are outside this workflow's current limits.

Trigger configuration and event checks are **not physical timing certification**.
The firmware measures/averages force, updates its display, emits a pulse and then
sends serial data; the printed timestamp is not a measured camera exposure time.
Validate pulse polarity/width, voltage compatibility, exposure delay, capture counts,
and force-to-exposure offset/jitter on the actual apparatus before relying on precise
synchronization. No software fallback may be labelled hardware synchronized.

## Recording safeguards and remaining limits

A camera below the normal 10 FPS preview target displays guidance before
recording. Use Delay = 200 ms with Capture Every for approximately 5 images/second,
or use sparse capture while keeping a higher force-sample rate. These are box changes,
not BURST settings writes. The old manual 5 FPS readiness override has been removed.

The recorder checks requested versus saved images rather than force-row equality.
Missing requested images stop acquisition for review. Backwards/nonadvancing device
time also stops recording; untrustworthy Step data are not silently repaired.
CSV-only runs support completion, naming and crash recovery.

Owned monochrome camera pixels are saved separately from the 8-bit preview, preserving
supported 16-bit data. Color/vendor conversion and plugin preview fallbacks identify
their precision limitations in TIFF metadata. Receipt timestamps are diagnostics,
not camera exposure timestamps or a clock calibration.

Firmware work remains necessary for acknowledged settings read/write, version
discovery, remote Home/Zero, reliable Step timestamps/counters, and any firmware
buffer/timing defects. BURST does not fabricate those capabilities.
