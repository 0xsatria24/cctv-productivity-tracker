# Dashboard and Python engine integration

Implemented on 12 October 2026 at the user's request. The shared React frontend now has a pilot engine mode that reads committed SQLite data through FastAPI. One loopback server serves both the built dashboard and API. The design-only mock mode is still independently available on Vite's development server.

## Launch the integrated application

The project's Python environment and frontend dependencies are already installed on this machine. Open PowerShell at the repository root:

```powershell
Set-Location -LiteralPath 'C:\Users\muham\OneDrive\Documents\ChatGPT\cctv 2'
& .\run-app.ps1
```

Open **http://127.0.0.1:8765/** directly in Chrome or Edge. The launcher builds the frontend and runs the API/engine until Ctrl+C. It defaults to `%LOCALAPPDATA%\CCTVTracker\dashboard-pilot.sqlite3`, with production-style logs in local app data. A normal PowerShell policy that prevents scripts can be handled by running the equivalent commands below rather than changing the machine's execution policy.

For development inside the writable workspace:

```powershell
& .\run-app.ps1 -DatabasePath "$PWD\runtime\integrated-pilot.sqlite3"
```

Equivalent explicit commands:

```powershell
Push-Location prototype
npm.cmd run build
Pop-Location
$env:MPLCONFIGDIR = Join-Path $PWD 'runtime\matplotlib'
& .\.venv\Scripts\python.exe -m cctv_tracker --log-dir runtime\logs --database runtime\integrated-pilot.sqlite3 dashboard --port 8765
```

`-Port 8767` selects another port. `-SkipBuild` reuses the existing `prototype/dist` build. The CLI also supports `dashboard --ui-dir <built frontend directory>`. Dependencies are installed using the existing runtime/frontend setup guides; Node is needed to build, but serving the completed application requires only the Python runtime. This is not a frozen executable or installer yet.

## Workflows connected to the engine

- **Ringkasan:** weighted P/A/U durations, coverage/utilization, workstation comparisons, committed event sequence, and checkpoint tables.
- **Pemantauan Live:** start and stop the synthetic replay through the API, see processed-frame progress, and read the latest stored observations. A visible notice states that live CCTV capture and video preview are unavailable.
- **Workstation:** read configured polygons/revisions, inspect a polygon, add employee registry entries, and create bounded manual assignments. These writes persist in SQLite and survive browser/server restarts. Assignment never supplies an observed employee identity.
- **Analitik:** select a stored run, workstation, or UTC range; inspect the timeline and individual committed intervals. Gaps are materialized as UNKNOWN. An unknown reason is split when the evidence reason changes so reconfirmation does not rewrite a previous camera-offline reason.
- **Laporan:** server-filtered workstation results, sorting/pagination/search, and a real CSV response from the same report query. Table-only search is labeled separately from server/export filters.
- **Kamera:** read actual camera configuration records from SQLite. No fake connection-test or live-stream controls are displayed.
- **Pengaturan:** inspect runtime capabilities and connectivity, refresh the connection, and export the active report. Shift calendars, retention, backup/restore settings are not presented as working mutations.

The default query follows the latest run. A pinned historical run does not change automatically. Filtering supports explicit start/end timestamps in UTC; observation display uses the engine's timezone. Report durations are presented with seconds so the 17-second pilot remains readable. Ratios use the sum of duration denominators across workstations. Multiple occupants do not multiply desk occupancy duration.

The dashboard polls authenticated status and committed reports. When the API disconnects, it displays a connection error, retains the last status as a historical snapshot, and disables replay/export actions. It never switches to the old frontend mock dataset. Request cancellation prevents older filtered responses replacing a newer query. Editing a time filter is protected from automatic polling updates.

## Data and replay boundaries

The replay button uses the packaged synthetic detection fixture. Python executes ByteTrack, polygon association, confirmation, unknown handling, and SQLite commits. Subsequent runs append a later timestamp range; old history is preserved. The worker is cancellable at observation boundaries and is stopped on server shutdown. Closing the browser alone does not stop it.

Synthetic replay is refused if the selected database already contains a different data source. Use a separate pilot database to avoid mixing generated observations with a supplied video or production source. The launcher and bare `dashboard` command default to a separate pilot database. Other existing databases can be viewed by choosing them explicitly, but their non-synthetic histories cannot be modified by the synthetic replay button.

Labels distinguish a reachable API from an online CCTV device. The latest workstation state is explicitly a replay snapshot; it is not claimed to describe the current room. There is no illustrated camera frame in engine mode. Real RTSP capture, multi-camera workers, model accuracy, GPU performance, calendar/DST aggregation, full production API/GUI, and validated backup/restore remain later gates. No face recognition or biometric storage is added.

## Local session and API

- Same-origin UI/API on `127.0.0.1`; one Uvicorn worker.
- Per-instance random token in an HttpOnly, SameSite Strict cookie scoped to `/pilot/`. The token is not placed in a JavaScript bundle, query string, localStorage, or an environment file.
- Host checking rejects unrelated hostnames. Browser mutation requests require the exact same Origin, including port; bearer clients without an Origin continue to work.
- The HTML bootstrap refuses cross-site background requests and uses anti-framing headers. Direct navigation is supported. No permissive CORS is enabled.
- Original bearer-authenticated read-only mode remains usable through `serve-pilot`.

Connected endpoints:

| Endpoint | Behavior |
|---|---|
| GET `/pilot/v1/status` | Runs, capabilities, checkpoint, camera/workstation snapshots, employees and assignments |
| GET `/pilot/v1/reports` | Durable report and materialized timeline; optional run/workstation/time filters |
| GET `/pilot/v1/export.csv` | Full server-filtered report CSV with data-source and metric-basis labels |
| POST `/pilot/v1/replay` | Accept one replay worker; duplicate concurrent starts return 409 |
| POST `/pilot/v1/replay/stop` | Request cancellation at the next observation boundary |
| POST `/pilot/v1/employees` | Register an administrative employee |
| POST `/pilot/v1/assignments` | Create an explicit effective-time assignment; overlapping assignments are rejected |

This pilot contract is not the completed production OpenAPI design in `docs/api/openapi.json`. Report query snapshots are coherent database read transactions; API/UI and engine processing use separate connections owned by their threads.

## Checks and screenshots

```powershell
$env:MPLCONFIGDIR = Join-Path $PWD 'runtime\matplotlib'
& .\.venv\Scripts\python.exe -m pytest
Push-Location prototype
npm.cmd run build
npm.cmd run test:engine
npm.cmd run test:e2e
Pop-Location
```

Integrated browser tests start an isolated server on port 8766 with `runtime/dashboard-browser-test.sqlite3`. They do not mutate the user's integrated application database on port 8765. The isolated test database is retained locally for diagnosis and ignored by Git. Tests verify real POST requests, golden durations, filtering, CSV downloads, timeline dialogs, employee/assignment persistence, all seven routes, responsive layout, disconnect behavior, and reconnection without mock fallback.

Actual integration screenshots are saved under `prototype/verification/screenshots/engine-*.png`. [Verification results](DASHBOARD-RESULTS.md) record the checks and remaining limits.

The user explicitly requested this integration after the standalone prototype and Python pilot were complete. It is an initial web client for the Python engine; the earlier native PySide6 UI remains a design option rather than an implemented GUI.
