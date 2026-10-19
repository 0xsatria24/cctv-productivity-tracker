# Tracking stability verification

## Problems and changes

- The smooth preview discarded observations 500 ms after capture, including results that had only just completed a slow inference. Overlay freshness now uses both capture age (maximum 3 seconds) and time since completed inference (maximum 1.5 seconds). The client subtracts request latency and expires results even when metadata requests fail.
- Video JPEG polling is capped at 24 requests/second. Lightweight tracking metadata is requested independently at up to 5 requests/second. Per-frame base64 image encoding and repeated observation serialization are no longer needed for the camera tiles.
- YOLOX retains person candidates down to confidence 0.10 for ByteTrack association. Raw untracked detections still require 0.45; new tracks require 0.45. Weak measurements can continue an existing anonymous ID.
- ByteTrack's loss buffer is scaled to the configured gap in seconds, rather than unintentionally becoming about one second at 5 FPS. Reset on a source generation change or a gap beyond the configured limit remains in place.
- Weak unmatched candidates remain available to zone accounting as UNKNOWN. They do not become displayed new people or turn uncertain zones into EMPTY. Confidence requirements for confirmed occupancy are unchanged. Predicted/lost boxes never extend presence duration.
- Overlay labels include the anonymous track number, allowing an operator to distinguish loss of a visual box from an ID change.

## Reproducible video comparison

Both local CarDA WS30 recordings were sampled at 5 FPS, resized to the same 640 x 360 frames and encoded at JPEG quality 75. Each frame was inferred once with the same YOLOX-S/OpenVINO GPU model. Before/after tracking branches consumed the same model output with their respective candidate thresholds and loss-buffer settings.

| Recording | Samples | Empty display samples, before / after | Display presence toggles, before / after | Unique track IDs, before / after |
| --- | ---: | ---: | ---: | ---: |
| OUT, session 004, 60.93 seconds | 305 | 199 / 198 | 4 / 4 | 2 / 2 |
| IN, session 003, 54.90 seconds | 275 | 127 / 100 | 35 / 13 | 6 / 6 |

The IN sequence has 62.9% fewer toggles in whether any measured box is displayed. This is an unlabelled continuity comparison, not a precision, recall, identity accuracy, productivity or worker-count benchmark. A person can be present but fully occluded; sample inspection of OUT shows substantial obstruction by the car door and equipment. The benchmark does not solve full occlusion or guarantee an identity across different cameras.

Detailed local measurements are in `runtime/tracking-continuity-final/summary.json` and the per-video JSON files. These files and source footage are excluded from Git. Timings in that run were affected by concurrent testing and are not a clean before/after inference-speed comparison.

To reproduce, use `scripts/benchmark_tracking_continuity.py --model PATH --output NEW_OUTPUT_DIRECTORY --device GPU --fps 5 VIDEO1 VIDEO2` with the project virtual environment. The benchmark compares measured boxes, without a display-only prediction buffer.

## Regression coverage

Tests cover weak candidate decoding, anonymous-ID continuity at low confidence, recovery after a brief occlusion, UNKNOWN accounting for weak unmatched candidates, no presence duration from lost-track predictions, freshness after slow inference, result expiry, independent video refresh, camera removal and retained history. Browser tests use explicitly synthetic camera/model fixtures; the recorded-video benchmark uses the real model.
