# Replay box / ReID correction

The HTTP replay path now runs appearance preparation in a background worker. There is one worker slot per ReplayTracking instance, no frame queue, and at most one pending sample per stream. Workers read copied session state; only the request thread applies recovery. Results must retain generation and mapping, be no older than 500 ms of media time, and pass the current motion gate. Seek replaces the runtime; old work cannot commit into it. Offline callers retain synchronous processing by default for reproducible evaluation.

Tracked low-confidence observations are included only in display_detections, marked WEAK. Accounting detections and workstation evidence remain unchanged. Recovery and duration tests cover one-time transfer and no charging of absence.

The browser displays the captured image with its matching boxes and media timestamp. Inference latency no longer makes valid boxes expire against an advancing video. The display updates at detection cadence (roughly 5 FPS maximum), not source-video FPS. A 1.5-second wall-clock watchdog drops stalled results; pause, seek and invalidation reject late responses. The 0.4-second prediction bound still applies between source observations, not to network transit while displaying a matching captured image.

Local engine instances previously shared a host-only cctv_session cookie across ports. The cookie name now includes the externally requested port, retaining HttpOnly, SameSite and origin checks. Both local engines (8765 and 8770) were restarted with the updated code.

## Evidence

- runtime/box-fix/off.json and on.json: same first 25 seconds of user file 075831.mp4, 126 frames each, SHA256 28663405ec1c52bdbdb987287b11c18a55830f21454c123425d1b0b391ea8651.
- OFF versus ACTIVE background ReID: zero differing detector geometry/confidence frames. Both have 37 frames without public detections and 25 frames without display boxes. ACTIVE executed 40 samples, with 78 interval skips, 7 pending responses and one cold-start budget rejection. This benchmark uses the conservative motion recovery policy; the running demo uses short_occlusion, covered separately by synthetic recovery tests.
- Timings are descriptive only: other desktop/test work overlapped; no speedup claim.
- Background regression tests hold extraction behind an event while multiple detector responses complete, check bounded work and seek disposal, and exercise actual asynchronous recovery with one timer transfer.
- Browser verification: local video playback with active ReID, synchronized canvas and boxes, weak observations, reset and seek. Screenshot: runtime/box-fix/preview.png.
- Backend results: runtime/box-fix/tests-final.xml. Frontend unit tests: 27 passed; production build passed.

## Remaining limits

This fixes request blocking, mismatched presentation and competing local cookies. It does not prove detector recall, identity accuracy, long-term re-entry or crowded-scene accuracy. The footage has no verified person labels; empty output frames must not be presented as a measured false-negative rate. Detector gaps and session fragmentation still occur. Predictions remain bounded rather than keeping a departed person's box indefinitely.

The earlier runtime/production-audit/task-only.patch predates these changes and is not a rollback for this revision. Preserve preexisting uncommitted changes when reviewing or reverting.
