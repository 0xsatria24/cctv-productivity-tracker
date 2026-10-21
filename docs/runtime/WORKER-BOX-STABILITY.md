# Worker box continuity follow-up

Validated locally on 2026-10-21. This follows the shared-capture work in [ENGINE-PERFORMANCE.md](ENGINE-PERFORMANCE.md).

## Findings

The three 640 x 480, 15 FPS factory clips contain bent workers, occlusion by equipment, and weak person detections. A fixed 30-second segment from each clip was sampled at 3 FPS. Detector candidate outputs were cached once and reused for the association comparison. Of 270 samples, 91 contained only candidates below the existing 0.45 display/new-track threshold. The detector still uses the same licensed YOLOX-S ONNX weights, RGB preprocessing, OpenVINO GPU FP32, 640 x 640 input, 0.10 candidate threshold, 0.45 strong/new-track threshold and 0.25 tracker activation threshold.

PyAV flagged 30, 31 and 31 corrupt decoded frames among the first 451 decoded frames of the clips (file order: 093131, 091812, 100656). The original files are retained. The local replay publisher now skips flagged corrupt frames and preserves source-time gaps instead of playing the remaining frames faster. RTSP capture also rejects flagged corrupt frames and exposes a `corrupt_dropped` counter. Encoded artifacts that a decoder does not flag can still pass through; this is not video repair.

The initial live comparison showed a 237 ms local capture-to-result P95 for one camera and approximately 795-810 ms for three. Scheduler waits reached hundreds of milliseconds. Each camera selected its input before waiting for the shared model, so the queued input aged even though the capture mailbox itself was bounded.

## Changes

- The fair inference scheduler selects the newest available frame after obtaining the model turn and rechecks its freshness before inference. Its returned frame supplies the image, generation and timestamps used for tracking and accounting. No second model instance or unbounded queue was introduced. `refreshed_frames` reports the reselections.
- A recently lost track can participate in ByteTrack's low-score matching again only within one second, with IoU at least 0.60 to exactly one weak measurement, and no competing retained track with IoU at least 0.30. The detector confidence is not raised. The normal tracker still performs the association; no match creates a prediction as measured evidence. Weak results remain UNKNOWN for zone accounting.
- Per-person expiry uses elapsed time since the last real measurement, even when other workers remain visible. Tiny stationary-box jitter is damped at low inference FPS; fast motion and material size changes bypass that extra damping.
- Separate `display_predictions` can cover a brief missing detection for at most one second since the last real measurement. Their motion is capped and coordinates stay inside the frame. The dictionary has a 128-track hard bound and resets on source generation changes. Predictions have `evidence: PREDICTED`, no confidence and no Working/Idle claim.
- The dashboard draws predictions with a faded dashed border. Server responses subtract the age of the source frame from prediction lifetime. The browser subtracts request time and clears the prediction on its own deadline, including when metadata stops arriving. The small caption remains a track-age timer. Unconfirmed detections do not display a fabricated zero-duration timer.
- Prediction rows are separate from `detections`, `count`, zone association, database visits, event logs and report exports. Headless shares these engine changes and retains its existing routes.

## Fixed-frame continuity check

Each row below uses 90 identical sampled frames before and after association changes. The displayed prediction column assumes a 200 ms presentation delay. A visibility transition means the entire sampled frame changes between zero and at least one visible box; it is not a per-person identity-switch or accuracy measure.

| Clip | Measured empty frames before / after | Visibility transitions before / after measured | Display transitions after bounded prediction |
| --- | ---: | ---: | ---: |
| 093131.mp4 | 41 / 40 | 12 / 12 | 4 |
| 091812.mp4 | 38 / 31 | 17 / 21 | 5 |
| 100656.mp4 | 14 / 12 | 8 / 8 | 4 |
| Total | 93 / 83 | 37 / 41 | 13 |

Measured detections remain intermittent; the second clip actually has more measured visibility transitions as additional weak observations are recovered. The display has fewer blank transitions because short predictions bridge some of those gaps. These are separate outcomes. Anonymous-ID counts remain 3, 2 and 1; they do not establish the number of real identity switches. The cache includes the same damaged decoded frames on both sides, so detector inputs are identical in this comparison.

Reproduce with `scripts/benchmark_worker_boxes.py --model MODEL.onnx --cache NEW_CACHE.json --output RESULT.json VIDEO1.mp4 VIDEO2.mp4 VIDEO3.mp4`. Use a new cache to evaluate a different model or different source frames. An existing cache intentionally reuses its saved detector candidates and evaluates every saved clip without running inference again. Raw footage, candidate caches, measurements and databases stay under ignored local runtime paths.

## Configuration and validation

Live follow-up on the same i7-1185G7 host, same model/device and the same three replay files:

| Metric | Before | After |
| --- | ---: | ---: |
| Single-camera processed FPS | 2.66 | 5.06 |
| Single-camera capture-to-result P95 / P99 | 237 / 327 ms | 219 / 286 ms |
| Three-camera processed FPS | 2.24-2.28 each | 2.89-2.92 each |
| Three-camera capture-to-result P95 | 795-810 ms | 309-327 ms |
| Three-camera capture-to-result P99 | 819-1001 ms | 393-616 ms |
| Three-camera polled result source-age P95 | 1071-1231 ms | 609-667 ms |
| Three-camera preview capture FPS | approximately 15 | approximately 14 |
| Three-camera mean CPU, one logical core = 100% | 88.49% | 98.89% |
| Three-camera peak summed process RSS | 570.56 MiB | 573.59 MiB |

The final three-camera check lasted 44.57 seconds and reported no scheduler rejection or stale-frame rejection. Frame reselection counters advanced and model execution still averaged roughly 93-96 ms per invocation, so this does not claim that the model itself became faster. Queue waiting remains visible in telemetry; the input is refreshed after that wait. The process RSS last-minus-first was -4.25 MiB in this short window, which is not a long-duration leak test.

These sequential live runs use different replay phases, warm-up state and desktop load. The replay publisher also changed to skip corrupt input, so capture FPS differs. Treat the latency/FPS comparison as observed local evidence, not an isolated causal benchmark or a guarantee for other hardware. CPU and RAM did not improve. Local latency starts after decode and ends at publication; browser polling, rendering, camera exposure and original stream buffering add delay. Raw evidence is in ignored `runtime/worker-box-fix/{before,after}-{single,three}.json` files.

Two additive global JSON settings are `track_recovery_seconds: 1` and `display_prediction_seconds: 1`. Both accept 0..1 seconds; zero disables the corresponding behavior. Zone evidence thresholds are unchanged. Reducing display prediction time reduces the chance of a stale visual position but exposes more missed detections.

Backend regression: 119 passed, 5 skipped. Tests cover weak recovery after a missed sample, ambiguous overlapping workers, expiry while another worker stays visible, scheduler reselection after waiting, stale-input rejection without executing the model, prediction bounds/generation/expiry, and a live accounting check where the predicted box remains visible while the measured count is zero and the zone becomes EMPTY. The UI regressions cover dashed prediction styling, no predicted activity claim, timer continuity, video refresh and expiry when metadata is interrupted. Optional real-model tests account for skips when the local model path is absent.

No labelled person boxes or identity ground truth were supplied. Precision, recall, IDF1, HOTA and industrial action recognition accuracy remain unmeasured. A long disappearance, severe occlusion or sustained weak detection still removes the box. Training or selecting a detector for these factory poses requires a separate labelled evaluation; visual prediction cannot establish that accuracy.
