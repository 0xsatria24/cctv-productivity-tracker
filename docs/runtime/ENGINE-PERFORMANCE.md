# Engine audit, display timer and visible activity

The later factory-video findings, frame reselection, conservative weak-track recovery and bounded display predictions are documented in [WORKER-BOX-STABILITY.md](WORKER-BOX-STABILITY.md).

## Architecture audited

The working pipeline remains Python, PyAV/FFmpeg RTSP capture, OpenCV JPEG/preprocessing, the existing YOLOX-S model with ONNX Runtime or OpenVINO, ByteTrack, zone association, transactional SQLite accounting and the React dashboard. No replacement model, re-identification network, microservice or GUI dependency was added to the inference process.

Capture is isolated in bounded, stoppable processes. Each reader drains its mailbox to the latest frame; stale frames are rejected before accounting. Inference is serialized fairly through one resident model. The dashboard requests JPEG previews independently of tracking metadata. The same engine construction boundary is used by Headless.

## Findings and changes

1. A displayed managed camera previously opened independent RTSP decoders for preview and inference. It now has one capture owner and a read-only latest-frame subscriber for inference. Active inference keeps its owner alive even when the browser navigates away. Closing a subscriber does not close the owner. First frames must be newer than the subscriber/session anchor, preventing a pre-session frame from entering SQLite accounting.
2. Headless previously constructed a detector for every camera. Headless now shares the same bounded fair scheduler and one detector instance across cameras. Existing `/api/v1` routes are retained. The scheduler has an 18-request hard bound, timeouts, and observable pending/high-water/rejected counters.
3. The old caption depended exclusively on an open, confidently associated workstation visit. Uncertain detections correctly closed that evidence, which also made the visual timer vanish or restart. The caption now uses a separate anonymous track-age timer. Its retained state follows ByteTrack's tracked/lost lifecycle, rather than expiring before a still-retained ID. It survives weak matched detections and short gaps for the same ID. A tracker reset increments an ID epoch so a new lifecycle cannot reuse an old timer key. A new track, expired track or source generation starts a new timer. Zone reports and committed presence durations retain their original confidence rules.
4. The visible activity rule uses bounded sparse optical flow inside measured person boxes, subtracts median background motion, validates forward/backward flow and confirms changes over elapsed seconds. Motion runs on at most 320 x 180 grayscale images with at most 40 points per region. Motion scores are smoothed; transient ambiguous measurements do not flip the label immediately. Existing OpenCV is reused.
5. Display boxes have a short configurable exponential smoothing time constant. Fast motion bypasses smoothing. Raw measured boxes remain the input to zone accounting. No predicted box creates presence evidence.
6. OpenCV and decoder thread counts are bounded and configurable to avoid oversubscription on small frames. Inference pacing uses elapsed-time buckets rather than an exact inter-frame interval that unnecessarily rejected near-boundary frames. Existing model input size, weights, runtime choice, FP32 precision, detection thresholds and confidence requirements were preserved in this change.
7. Bounded telemetry reports capture-to-result age, scheduler wait, detector/preprocess/runtime/postprocess time, accounting, activity, skipped/stale frames and queue counters. Only 120 timing samples per camera are retained.

## Meaning of the two labels and timer

- **Working**: visible motion confirmed for 0.8 seconds by default.
- **Idle**: low visible motion confirmed for 8 seconds by default.

These are motion indicators, not validated action recognition or proof of rest, output or work quality. Stationary tasks, fine hand movements, occlusion, lighting and camera perspective can make this rule unreliable. No activity label is emitted while evidence is insufficient. The timer still appears for a measured confirmed track, independently of whether a zone visit exists. Box captions show only an available Working/Idle label and HH:MM:SS, with the anonymous ID available in the tooltip/structured metadata.

The HH:MM:SS timer is elapsed time since this anonymous track was first observed within its lifecycle, including short ID-preserving gaps. It is not a replacement for committed workstation presence or an activity-duration total. Weak, unmatched detections remain UNKNOWN evidence for zone accounting; they do not establish idle or productive time. Activity labels and track-age displays are not added to productivity reports or exported as validated work results.

## Measured checks

Host: Intel Core i7-1185G7, 8 logical CPUs, approximately 15.7 GiB RAM. Two local CarDA WS30 replays published at 24 FPS, same 640 x 360 JPEG input and YOLOX-S/OpenVINO GPU. Publishers and the browser are outside the measured server process tree; their GPU/system contention can still affect latency. Local capture timestamps start after decode, not at camera exposure.

| Metric | Before visible previews, 30 s | After shared capture, activity and native-thread tuning, 35 s |
| --- | ---: | ---: |
| Server process-tree count | 6 | 4 |
| Peak summed RSS | 630.93 MiB | 515.25 MiB |
| Mean CPU, one logical core = 100% | 102.17% | 107.97% |
| Preview FPS OUT / IN | 23.74 / 23.61 | 24.02 / 24.02 |
| Processed FPS OUT / IN | 4.61 / 4.64 | 4.14 / 4.14 |
| Local capture-to-result P95 OUT / IN | 140 / 163 ms | 489 / 542 ms |
| Local capture-to-result P99 OUT / IN | 192 / 589 ms | 553 / 577 ms |

The measured memory reduction is about 116 MiB (18.3% peak summed RSS). These runs do **not** establish a CPU or latency improvement: visible-motion analysis is an added feature, replay phases/background load differ, and GPU runtime stalls remain. Per-stage telemetry locates long tails in native inference and the shared-model wait, rather than unbounded frame queues. No ultra-low-latency or mini-PC throughput guarantee is made.

The first, more expensive optical-flow implementation was reduced before delivery. Activity-stage means fell from about 7.9/13.9 ms to 5.1/5.2 ms in the sampled GPU runs. Native-thread limits and small-frame motion analysis remain configurable. The GPU remains explicitly selected; no silent device fallback, FP16 conversion or unvalidated INT8 quantization was enabled.

A single-camera **CPU-only engine without GUI** was also run for 20 seconds from the same local RTSP replay. It processed 3.73 FPS; local capture-to-result P95 was 323.56 ms and P99 414.71 ms. Other local GPU monitoring was active, so this is a runtime validation, not an isolated device comparison or an i3/N-series capacity result.

Raw local measurements: `runtime/activity-performance/before-visible.json`, `after-visible.json`, `after-native.json`, `cpu-single/summary.json`, and `soak-final.json`. The initial idle-dashboard recording and the recording without visible preview leases are retained separately and are not used as the visible-workload baseline. Runtime data and source footage are excluded from Git.

A three-minute replay check kept both engines running at approximately 24 FPS preview and 4.29/4.26 FPS processed. The scheduler reached two requests with zero rejected requests; neither camera reported a stale-frame rejection. Summed RSS rose by 11.48 MiB between the first and last sample, with a 520.91 MiB peak. This short run does not establish leak-free operation. It also exposed one timer decrease for a retained ID after occlusion. The lifecycle/epoch change above addresses that defect and has dedicated regression coverage; the follow-up measurement is recorded separately below. The real clips yielded confirmed Working and unconfirmed activity samples, but no confirmed Idle sample. Synthetic static-person checks exercise Idle; field idle/rest accuracy remains unvalidated.

After the lifecycle correction, a separate 89.47-second check sampled 182 track observations across 14 anonymous track keys and found **zero decreasing track-age values for the same ID**. Both cameras processed 4.63 FPS. Capture preview averages were 20.91/20.82 FPS during a browser reload, so this run is a continuity check rather than a comparable 24 FPS throughput result. Local capture-to-result P95 was 446/401 ms and P99 596/638 ms; peak summed RSS was 522.01 MiB and last-minus-first RSS was +15.18 MiB. The camera queues remained bounded with zero scheduler rejections. Raw evidence is `timer-lifecycle-final.json` and `timer-continuity-check.json` in the same measurement directory. This is sampled replay evidence, not a guarantee against every future ID switch or memory leak.

## Configuration

The existing global `--config PATH` JSON accepts these additive fields; defaults are shown:

```json
{
  "inference_fps": 5,
  "capture_fps": 24,
  "capture_queue_size": 1,
  "native_threads": 1,
  "adaptive_inference": false,
  "minimum_inference_fps": 1,
  "activity_enabled": true,
  "activity_idle_seconds": 8,
  "activity_working_seconds": 0.8,
  "box_smoothing_ms": 80
}
```

Merge fields into a deployment's existing configuration rather than replacing its zones or database. `activity_enabled: false` disables motion classification while retaining the lightweight track timer. `box_smoothing_ms: 0` disables display smoothing. Capture queue capacity is restricted to 1..4 and readers still consume the newest item. Explicit backend choices remain `yolox`, `yolox-openvino` and `nanodet`; OpenVINO CPU/GPU selection remains explicit and fails visibly on unsupported hardware.

Adaptive pacing is optional and disabled by default. When enabled it adjusts only inference cadence within the configured min/max, with sample warm-up, a five-second cooldown and sustained recovery hysteresis. It does not change model size, precision or thresholds. With the optional `performance` extra it also considers CPU load and available memory; without psutil it uses latency and reports resource metrics as unavailable. No visual prediction is used as fresh accounting evidence.

For metadata-only Headless output, GUI/rendering modules are not required and images are not encoded in API output. JPEG remains the existing bounded capture-to-detector transport; raw-frame IPC was not introduced without a comparative benchmark. This avoids an unvalidated increase in IPC bandwidth and copies.

## Reproduce and remaining validation

Install development measurement dependencies with `python -m pip install -e ".[performance]"`. Use `scripts/profile_live_engine.py --seconds 30 --output NEW_FILE.json` against the owned local dashboard. It renews its own visible-camera lease and releases it afterwards. Use `scripts/benchmark_engine_runtime.py --url LOCAL_RTSP_URL --device CPU --model MODEL_PATH --seconds 20 --output NEW_DIRECTORY` for a single-camera non-GUI run. Longer monitoring can use the same profiler with a larger duration.

Regression coverage includes timer continuity without zone visits, weak confidence, Working/Idle hysteresis, camera translation, featureless frames, short occlusion, generation changes, fast movement, static-box jitter, bounded performance buffers, adaptive cooldown/disable, one model per Headless service, one capture per managed camera, subscriber ownership, timestamp anchors, stream outage/recovery, final committed intervals and browser navigation/expiry/archive behavior.

The short replay soak is not a 24-hour leak/stability certification. Sustained production operation, real network-jitter distributions, target i3/N-series hardware, low-light detection accuracy, annotated IDF1/HOTA and industrial action/rest classification still need the corresponding hardware and labelled footage. No ID-switch, accuracy or commercial-readiness result is invented from anonymous-ID counts or synthetic tests.

## Sequential production readiness

See [PRODUCTION-READINESS.md](PRODUCTION-READINESS.md) for the dataset/evaluation workflow, current release gates and the manually launched 24/72-hour test program. Creating the test program does not mean a long test has run.
