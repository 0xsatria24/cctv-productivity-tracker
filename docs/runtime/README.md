# Python occupancy pilot

Implemented on 12 October 2026 following the decision to establish anonymous occupancy before optional employee identification. This is a tested first runtime increment, not a completed CCTV product.

Later on 12 October, the dashboard was connected to this runtime at the user's request. [Dashboard integration](DASHBOARD-INTEGRATION.md) documents the one-server launcher, live checkpoint polling, replay controls, reports, CSV, and administrative employee/assignment forms. The read-only `serve-pilot` mode remains available; `dashboard` enables the integrated pilot. Statements below about the original isolated frontend describe the earlier increment.

## Available behavior

- Python 3.12 package, isolated environment, pinned dependencies, strict settings, credential redaction, rotating logs, and repeatable SQLite migrations.
- Actual ByteTrack adapter with run/generation-scoped anonymous IDs. Only fresh measured detections enter zone accounting; lost-track predictions are not presence evidence.
- Normalized polygon association, exclusive workstation assignment, overlap ambiguity, occupied/empty confirmation, unknown quality/gaps, count segments, and elapsed duration accounting.
- Event checkpoints and interval projections committed atomically to SQLite WAL with synchronous FULL, thread ownership, and an OS lease preventing a second engine writer.
- Recovery closes evidence at the committed watermark. Downtime is queried as unknown. An interrupted run cannot carry occupied duration into the next run.
- Manual employee registry and time-bounded workstation assignments. Reports keep `observed_employee_id=null`, `identity_source=anonymous`, and `assignment_is_observed_identity=false`.
- Offline local-video replay through PyAV, a supplied ONNX artifact, ByteTrack, zones, and SQLite. Model hash/license/shape/parser checks are mandatory. No automatic weight downloads.
- Optional authenticated, read-only pilot API on loopback. These `/pilot/v1` endpoints are a small pilot interface, not implementation of the complete production OpenAPI contract.

No face registration, face templates, recognition, or biometric database is implemented. Identity remains an independent future concern; failing to identify someone does not erase occupancy.

## Run the already installed demo

Open PowerShell:

```powershell
Set-Location -LiteralPath 'C:\Users\muham\OneDrive\Documents\ChatGPT\cctv 2'
& .\.venv\Scripts\python.exe -m cctv_tracker --log-dir runtime\logs demo --output-dir runtime\demos
```

The fixture covers 17 seconds, two example desks, multiple occupants, camera unavailability, re-confirmation, and empty confirmation. Input detections are synthetic, while tracking, domain transitions, migrations, and database writes execute actual code. The command prints the new database path, run ID, durations in microseconds, coverage, and utilization as fractions. It can be repeated without overwriting any database. `1_000_000` microseconds is one second.

Development databases under `runtime/` are disposable test artifacts and ignored by Git. For an installed deployment, omit development overrides: database and logs default to `%LOCALAPPDATA%\CCTVTracker`, outside source and OneDrive. `demo` defaults to its separate `demos` subdirectory, creating a unique database each time. A fixed replay file must use a fresh database or a later nonoverlapping timestamp; the engine refuses backwards history.

## Reproduce the environment

Python 3.12 x64 is currently the tested interpreter; other Python/OS/GPU combinations require a dependency spike.

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.windows-cpu.lock.txt
& .\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m cctv_tracker --log-dir runtime\logs doctor
```

The lock is a fully pinned installed dependency snapshot for Windows/Python 3.12/CPU, including build and test dependencies. It is not a GPU lock or a cryptographically hashed supply-chain lock. Primary dependency choices live in `pyproject.toml`. Development optional groups are `vision`, `api`, and `test`. `tzdata` supplies timezone data on Windows.

## Read persisted results and register an assignment

Replace the database path with the path printed by `demo`:

```powershell
$pilotDb = 'runtime\demos\replay-REPLACE.sqlite3'
& .\.venv\Scripts\python.exe -m cctv_tracker --log-dir runtime\logs --database $pilotDb report --start '2026-10-12T09:00:00+07:00' --end '2026-10-12T09:00:17+07:00'
& .\.venv\Scripts\python.exe -m cctv_tracker --log-dir runtime\logs --database $pilotDb workspaces
& .\.venv\Scripts\python.exe -m cctv_tracker --log-dir runtime\logs --database $pilotDb employee-add 'Karyawan Contoh'
```

Use the returned employee and workstation UUIDs:

```powershell
& .\.venv\Scripts\python.exe -m cctv_tracker --log-dir runtime\logs --database $pilotDb assign --employee 'EMPLOYEE_UUID' --workspace 'WORKSPACE_UUID' --start '2026-10-12T09:00:00+07:00' --end '2026-10-12T17:00:00+07:00'
```

Overlapping assignments for a workstation are rejected. Assignments annotate the workstation's administrative responsibility, never the observed person. Current pilot reports use the monitoring window; `schedule_applied=false` is explicit. Scheduled daily/weekly/monthly/yearly production reports still require the calendar/aggregation milestones.

## Supply a local video and model later

```powershell
& .\.venv\Scripts\python.exe -m cctv_tracker --log-dir runtime\logs --config config\pilot.example.json --database runtime\video-pilot.sqlite3 replay-video 'C:\path\recording.mp4' --model 'C:\path\detector.onnx' --manifest 'C:\path\manifest.json' --start '2026-10-12T09:00:00+07:00'
```

Calibrate polygons for the actual scene first. `config/model-manifest.example.json` documents required artifact metadata. Supply a correctly licensed model and its SHA256; the sample contains placeholders and is deliberately not runnable as a detector. Supported inputs are one float32 NCHW tensor. Parsers support `[1,N,6]` pixel `xyxy,score,class` output and `[1,4+classes,anchors]` raw YOLO output with pixel `cx,cy,w,h`. Normalized outputs, objectness-style legacy models, segmentation, pose, and other output formats are rejected or require a dedicated adapter.

The offline replay uses video presentation timestamps and an explicit timezone-aware anchor, not processing speed, to calculate durations. It is not live RTSP capture. Decoder failures abort the replay rather than fabricating empty observations. Available CPU provider has been tested; CUDA availability is checked explicitly, with no silent session fallback. Node/npm is not required by the Python pilot.

## Optional pilot API

Initialize or select a demo database, then set a session token without publishing it:

```powershell
$env:CCTV_LOCAL_TOKEN = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
& .\.venv\Scripts\python.exe -m cctv_tracker --log-dir runtime\logs --database $pilotDb serve-pilot --port 8765
```

Routes: `GET /pilot/v1/status` and `GET /pilot/v1/reports?start_utc_us=...&end_utc_us=...`; requests require `Authorization: Bearer <session token>`. Server binds `127.0.0.1`, one worker, with access logging disabled. It serves durable database results and does not start capture or inference. The React prototype is not connected to it. Remote access, authentication roles, complete jobs/WebSocket contracts, and GUI integration remain later milestones.

## Verification and remaining gates

```powershell
$env:MPLCONFIGDIR = Join-Path $PWD 'runtime\matplotlib'
& .\.venv\Scripts\python.exe -m pytest
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m pip wheel --no-deps --no-build-isolation --wheel-dir runtime\wheels .
```

[Results](RESULTS.md) record the actual checks. The generated ONNX/video integration fixture validates native adapter plumbing, not person detection accuracy. No usable site recording/model has been supplied yet; the user explicitly selected synthetic replay first.

Setup step 1 is implemented. M0 is a CPU dependency/integration spike so far, not complete platform certification. M2/M3/M6/M7 have initial tested slices; their full gates remain open. Live RTSP workers/shared buffers, supervisor lifecycle, schedules/DST, durable event replay/rebuild, full API/GUI, GPU performance, verified production backup/restore, installer, and 24-hour pilot remain unfinished. Capacity and occupied/empty precision/recall are not established by synthetic tests.

Technical references: [PyAV](https://pyav.org/docs/stable/api/_globals.html), [Supervision ByteTrack](https://supervision.roboflow.com/0.26.1/trackers/), [ONNX Runtime Python](https://onnxruntime.ai/docs/api/python/api_summary.html). The native PySide6 production UI in the design documents remains planned; the web/installer alternative discussed in chat has not been implemented as a production migration.
