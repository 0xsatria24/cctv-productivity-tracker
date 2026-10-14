# Live occupancy engine pilot

Implemented and verified on 14 October 2026. This increment connects live camera input to the existing Python tracking/domain/SQLite pipeline and the integrated React dashboard. It supports one active live source at a time. The production architecture roadmap remains in [ARCHITECTURE.md](../ARCHITECTURE.md); multi-camera scheduling, native packaging and production acceptance remain later gates.

Current quality mode: the default dashboard now uses YOLOX-S through OpenVINO on Intel GPU, keeping input 640x640 and FP32. Setup and measured results: [OPENVINO-YOLOX.md](OPENVINO-YOLOX.md). The earlier NanoDet CPU comparison remains in [LATENCY.md](LATENCY.md).

## Launch

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts/setup_webcam_model.py
.\run-app.ps1
```

Open http://127.0.0.1:8765/#/cameras in Chrome or Edge. The default database stays in local Windows app data. For the existing development dashboard:

```powershell
.\run-app.ps1 -DatabasePath runtime/integrated-pilot.sqlite3
```

The live database is a sibling with the suffix `-live.sqlite3`. Existing replay files and history are preserved. Vite's `npm run dev` at port 5173 remains the standalone mock prototype; it does not provide the Python live engine.

## Webcam workflow

1. Click **Mulai webcam**, grant browser camera permission, and wait for delivered frames.
2. Click **Kalibrasi zona live**. The frame freezes without mirror. Name the zone and click its polygon vertices in order, or enter normalized X/Y coordinates. Use **Simpan zona** for each workstation, then **Simpan kalibrasi live**.
3. Click **Mulai pencatatan live**. The dashboard selects **Kamera live** as the report source. Preview shows anonymous track IDs; the live panel shows confirmed zone states and the last committed frame count.
4. Open Ringkasan, Analitik, or Laporan. Durations, utilization, coverage, intervals, ENTER/EXIT events and CSV now come from the live SQLite ledger. Navigating retains the webcam and its engine session.
5. **Hentikan pencatatan live** ends accounting but leaves webcam preview available. **Hentikan webcam** also requests accounting stop. Closing the browser stops browser-supplied frames; the watchdog records UNKNOWN and ends that source after 15 seconds without valid frames.

## RTSP workflow

Select **CCTV RTSP**, enter the camera RTSP URL, and click **Uji preview RTSP**. The connection test runs the decoder and real detector without recording occupancy. Once a frame arrives, click **Kalibrasi zona live**; this freezes the frame and stops the preview session. Save the polygons, wait for STOPPED, then click **Mulai pencatatan live**. The URL remains in the current page's memory and is not stored in SQLite or returned by status endpoints.

RTSP capture and accounting run in Python independently of the browser. Closing a browser tab keeps RTSP accounting running while the Python dashboard process remains alive. Reopening the dashboard shows its status; the session can be stopped from **Hentikan pencatatan live**. A Python restart requires re-entering the URL and explicitly starting again. No OS autostart or unattended credential persistence is added.

Calibration is bound to a camera fingerprint and source type. Webcam device identifiers are hashed in the browser; RTSP endpoint information is hashed server-side. Frames whose aspect ratio differs from calibration are rejected. A moved camera with unchanged dimensions still requires manual recalibration; automatic scene-change detection is not implemented. Mirror only changes preview presentation, never accounting coordinates.

## Architecture and correctness

- One live coordinator thread owns its SQLite connection and `Pipeline`; API threads never mutate that connection. The existing OS engine lease guards against a second occupancy writer for the same live database.
- Browser ingress has a one-frame queue, a session ID and strictly increasing client sequence. Duplicate/out-of-order frames and obsolete sessions are rejected. The frontend retains only one in-flight frame request. RTSP decoding uses a separate spawned process and a one-frame mailbox; inference receives the latest frame rather than accumulating decoded frames.
- PyAV reads RTSP over TCP with bounded open/read timeouts, low-buffer options, repeated-PTS rejection and reconnect backoff of 2/4/8 seconds. Each restarted decoder or backwards source PTS creates a new tracking generation. A hung native decoder is terminated by its parent during recovery or shutdown.
- The selected detector is a locally installed, checksum-verified Apache-2.0 ONNX artifact. YOLOX-S OpenVINO GPU is the default quality mode; OpenVINO CPU, ONNX YOLOX and NanoDet remain explicit options. See [OPENVINO-YOLOX.md](OPENVINO-YOLOX.md). Model inference is shared and serialized. ByteTrack IDs are scoped to the run and generation. Predicted tracks do not become presence evidence.
- Server monotonic timestamps determine elapsed durations; UTC is anchored when a live run starts. Browser wall-clock timestamps are not trusted for accounting. Decode receipt freshness is enforced; absolute camera capture time is not established without camera clock synchronization.
- Calibrated polygon association, exclusive groups, ambiguous matches and confidence thresholds use the existing domain rules. Occupied/empty states begin at confirmation; pending time remains UNKNOWN. Multiple people do not multiply workstation duration.
- Stale frames, changed aspect ratio, inference interruptions and disconnects cannot extend occupied duration. Watchdog observations close the last proven state at its evidence watermark and fill the rest as UNKNOWN. Defaults: occupied confirmation 2 seconds, empty confirmation 5 seconds, maximum evidence gap 3 seconds. Choose timing based on measured inference/commit latency; too small a gap lowers coverage conservatively.
- A checkpoint transaction atomically stores intervals, anonymous visits and events. Confirmed ENTER/EXIT events include first evidence and confirmation timestamps. Only committed results are published to live status. A failed checkpoint stops accounting; it is not retried using mutated in-memory state. A new run closes unfinished intervals at their durable evidence watermark.
- Live reports and replay reports have separate databases, selectable in the UI and API. Run-scoped reports include only workspaces configured for that run. Configuration revisions and reference dimensions are stored; removed zones are retired when the next run starts. Duration totals satisfy occupied + empty + unknown = eligible monitoring time.
- No audio, raw recording, face registration or identity recognition is added. These are occupancy observations, not a measure of work output. Employee registry and workstation assignments remain explicitly administrative.

## Pilot API additions

All endpoints use the existing bearer or HttpOnly same-origin loopback session authentication. Mutations validate Origin. No camera secret is included in a status response or CSV.

| Endpoint | Behavior |
|---|---|
| `GET /pilot/v1/live` | Lifecycle, camera health, recent detections, confirmed zones and saved calibration profiles |
| `POST /pilot/v1/live/calibration` | Validated camera-bound profile; requires the live session to be stopped |
| `POST /pilot/v1/live/start` | Start webcam/RTSP accounting or explicit preview-only RTSP test |
| `POST /pilot/v1/live/stop` | Stop only the matching session ID |
| `POST /pilot/v1/webcam/frame` | Bounded JPEG; `X-Live-Session` and `X-Frame-Sequence` select accounting; no session means detection preview only |
| `GET /pilot/v1/live/preview.jpg` | Recent processed RTSP/webcam frame held only in memory; 404 when unavailable/stale |
| `GET /pilot/v1/status?dataset=live` | Read the live database snapshot |
| `GET /pilot/v1/reports?dataset=live` | Coherent live intervals/durations; existing time/run/workspace filters apply |
| `GET /pilot/v1/export.csv?dataset=live` | Live CSV with source labels |
| `POST /pilot/v1/employees?dataset=live` and assignments | Administrative registry in the selected live database |

Runtime schema migration 003 adds `live_calibrations`. It preserves v2 ledger data and validates migration checksums. The design OpenAPI document remains the production target contract; these pilot additions are documented here and in [pilot-openapi.json](pilot-openapi.json).

## Verification and practical limits

Verification: 51 Python tests, 11 webcam/live browser tests, 3 dashboard integration browser tests and 6 frontend domain tests passed. Production frontend build passed.

The checks include deterministic occupancy/ENTER/EXIT totals, two-person no-double-counting, live tracking, stale gaps, session/sequence rejection, calibration binding, changed aspect ratio, inference failure, checkpoint failure, schema upgrade, API authentication/origin rules, coherent reports and CSV. Browser verification covers the complete calibration-to-live-report path using the actual ONNX model and an explicitly synthetic video device; it does not open the user's physical webcam.

An actual loopback RTSP publisher/server test ran generated H.264 frames through PyAV decode, YOLOX inference and SQLite. It disconnected the publisher, verified UNKNOWN accounting, then reconnected and verified a new generation and renewed observations. The generated moving rectangle correctly produced zero people. The test database passed SQLite integrity and foreign-key checks. This proves transport and accounting plumbing, not recognition accuracy on a physical CCTV scene.

```powershell
.\.venv\Scripts\python.exe -m pytest
cd prototype
npm.cmd run build
npm.cmd run test:webcam
npm.cmd run test:engine
npm.cmd test
```

The optional RTSP verification uses `scripts/verify_rtsp_engine.py` plus a separately launched MediaMTX test server on `127.0.0.1:8854`. MediaMTX is not required by the application. Verified official test artifact: MediaMTX v1.21.2 Windows amd64, archive SHA-256 `a84224f5a490855684e62ba6fb71e80ea2a5e16aed61883bb58380290e93e467`; all other listeners are disabled in the test config, including MoQ.

Still outstanding for production: camera-specific annotated accuracy tests (seated/back-facing/occlusion/adjacent desks), simultaneous multi-camera scheduling, GPU/throughput benchmarks, long soak tests, supervisor restart policy, secure persisted camera credentials, shift/calendar aggregation, retention/backup/restore, packaging and the native GUI. One active camera source is supported in this pilot.
