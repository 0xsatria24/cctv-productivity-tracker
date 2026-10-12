# Python runtime verification

Date: 12 October 2026. Platform: Windows x64. Interpreter: Python 3.12.14. SQLite: 3.53.1.

## Executed checks

- Installed the project and `vision`, `api`, and `test` dependencies into `.venv`; added timezone data required on Windows. Exact installed versions are recorded in `requirements.windows-cpu.lock.txt`.
- `python -m pip check`: passed, no broken requirements.
- `python -m pytest`: **24 passed**, one upstream AnyIO deprecation warning from FastAPI's test-client integration. No application exception or failing assertion remains in the test run.
- Built `cctv_tracker-0.1.0-py3-none-any.whl`: passed. Inspected the archive and verified both SQL migration files plus the packaged demo settings and detection fixture are included. This is a Python wheel, not a Windows installer or frozen executable.
- Ran the CLI demo successfully. Every invocation creates a new database; no existing demo or production database is overwritten.
- Runtime doctor reports PyAV 16.0.1, ONNX Runtime 1.23.2, Supervision 0.26.1, NumPy 2.2.6, OpenCV 4.12.0.88, FastAPI 0.115.12, and Uvicorn 0.34.3. Available inference providers: Azure and CPU. CUDA was not installed or benchmarked.

## Meaningful scenarios covered

- Occupied/empty confirmation with no backdating; count changes preserve presence duration and session continuity.
- Missing evidence, unavailable camera, changed generation, duplicate observations, backward clocks, and query tails.
- Polygon validity, exclusive-group ambiguity, weak detections, and fresh detections without an established track ID.
- Actual ByteTrack continuity, scoped anonymous IDs, and exclusion of lost-track predictions from accounting.
- Real SQLite migrations repeated without duplication, FK/integrity checks, unsupported schemas, migration checksums, rollback, atomic checkpoints, and reports read after reopening the database.
- Abrupt run recovery: occupied evidence stops at the committed watermark, downtime is unknown, old runs are marked interrupted, and the next run establishes new anonymous IDs.
- Second-process writer lease rejection and successful acquisition after release.
- Employee registration, assignment overlap rejection, effective-time filtering, and reports that explicitly keep observed identity unavailable.
- Actual ONNX CPU inference with a generated constant-output test model, inverse letterbox coordinates, person-class filtering, invalid checksum/parser rejection.
- Actual PyAV encode/decode followed by ONNX, ByteTrack, zone rules, and SQLite using a generated synthetic video. This proves native adapter integration, not accuracy of a trained person detector.
- Pilot API authentication/range validation and credential redaction in logging messages and exception traces.
- CLI demo repeatability plus employee/assignment/report commands.

## Golden replay result

The synthetic fixture covers 17 seconds:

| Workstation | Occupied | Empty | Unknown | Total |
|---|---:|---:|---:|---:|
| Meja A01 | 4.0 s | 1.8 s | 11.2 s | 17.0 s |
| Meja A02 | 0.0 s | 6.0 s | 11.0 s | 17.0 s |

All records retain `identity_source=anonymous`; manual assignments do not create an observed employee identity. The source is `SYNTHETIC_REPLAY`. Reports explicitly declare `basis=monitoring_window` and `schedule_applied=false`.

The latest development CLI result was written to `runtime/latest-replay-result.json`, an ignored local artifact. SQLite/logs/wheels under `runtime/` are development data. Installed deployment defaults remain outside OneDrive under local app data.

## Limits

No site footage or trained model was supplied; the user selected synthetic replay. Live RTSP, actual person-detection precision/recall, GPU capacity, 20-camera throughput, PySide6 integration, calendar/DST aggregation, event rebuild, verified production backup/restore, native installer, and 24-hour soak have not been verified or completed. The React design prototype still uses its own mock data. Face registration and recognition are intentionally deferred.
