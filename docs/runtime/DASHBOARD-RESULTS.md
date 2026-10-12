# Integrated dashboard verification

Verified on 12 October 2026 on Windows with Python 3.12.14, the installed CPU runtime, Vite 8.3.4, and Microsoft Edge. This is a replay pilot, not a live CCTV deployment or a model-accuracy benchmark.

## Completed checks

| Check | Result |
|---|---|
| Full Python suite | 30 passed; one upstream AnyIO deprecation warning |
| Integrated browser suite | 3 passed, exit 0 |
| Original design prototype browser suite | 13 passed, exit 0 |
| Vite production build | Passed; shared UI includes separate mock and engine modes |
| PowerShell launcher syntax | Passed |
| Running application review | Loopback port 8765; replay completed 86/86 frames, checkpoint 86, one stored run |

The integrated browser suite exercised real requests to an isolated Python server on port 8766. It verified starting replay, reading committed durations, server filtering, CSV download, timeline dialogs, employee registration, bounded assignment persistence through reload, seven navigation pages, layout at 1100px, and explicit disconnect/reconnect behavior without mock fallback. The Windows test helper needed explicit termination after assertions completed; the test runner then exited successfully. The application server on port 8765 was retained.

Python coverage includes the existing tracking/domain/database/video plumbing checks and new integrated-session, Origin/Host validation, replay cancellation/restart, unknown-gap accounting, employee/assignment, data-source isolation, CSV, and unknown-reason history checks. Changing UNKNOWN evidence reasons now creates separate intervals so a later reconfirmation cannot erase an earlier camera-offline explanation.

## Golden replay accounting

Each workstation has a 17-second observation range. These durations were checked against SQLite-backed API responses and displayed in the actual UI.

| Workstation | Occupied | Empty | Unknown | Total |
|---|---:|---:|---:|---:|
| Meja A01 | 4.0 s | 1.8 s | 11.2 s | 17.0 s |
| Meja A02 | 0.0 s | 6.0 s | 11.0 s | 17.0 s |
| Sum of workstation durations | 4.0 s | 7.8 s | 22.2 s | 34.0 s |

Weighted utilization is occupied / (occupied + empty), 33.9%. Coverage is (occupied + empty) / total workstation duration, 34.7%. A workstation duration is never multiplied by its number of occupants. The denominator is a monitoring range; no shift calendar is applied. Manual assignments are not observed employee identities.

## Visual review

Reviewed the actual Edge screenshots after the final build:

- `prototype/verification/screenshots/engine-overview-1440.png`: connected engine banner, durable checkpoint, weighted durations, workstation bars, and genuine stored events.
- `prototype/verification/screenshots/engine-analytics-1440.png`: second-level timeline labels, readable state legend, interval detail, and preserved CAMERA_OFFLINE versus PENDING_CONFIRMATION reasons.
- `prototype/verification/screenshots/engine-workstations-1440.png`: actual SQLite registry and administrative assignment forms. Test employee entries exist only in the isolated browser-test database.

An additional browser review of port 8765 started the packaged replay from the visible UI and confirmed COMPLETED, 86 committed checkpoints, and the golden combined durations. The application database is `runtime/integrated-pilot.sqlite3` for this development session. A normal launcher invocation defaults to the separate pilot database in local app data.

## Remaining implementation gates

Real RTSP capture, camera video previews, supplied CCTV/model accuracy evaluation, multi-camera scheduling, GPU capacity, shift/calendar aggregation, installer packaging, and validated backup/restore are not completed by this integration. Synthetic replay is visibly labeled, and its writes are rejected for databases containing a different data source. No face recognition or biometric storage is enabled.

See [launch and integration guide](DASHBOARD-INTEGRATION.md) for the single-command launcher, equivalent explicit commands, API contract, and data boundaries.
