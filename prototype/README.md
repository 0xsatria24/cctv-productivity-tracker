# CCTV Workspace: interactive design prototype

Integrated camera view update, 14 October 2026: multiple independent previews, 1/4/9/16 layouts, focus, fullscreen, search and per-camera state. Additional RTSP previews are explicitly separate from the single-source accounting engine. See [camera wall](../docs/runtime/CAMERA-WALL.md). This update applies to Python-served engine mode on port 8765; the standalone Vite mock prototype remains a separate mode.

Update 13 October 2026: the integrated dashboard supports webcam person detection through the local Python engine, with capture persisting across routes. See [webcam setup](../docs/runtime/WEBCAM.md). Update 14 October: live zone calibration, tracking, RTSP and SQLite occupancy reports are implemented. See [live engine workflow](../docs/runtime/LIVE-ENGINE.md).

Update 12 October 2026: this frontend also includes an integrated Python-engine pilot. Run `run-app.ps1` from the repository root and open `http://127.0.0.1:8765/`. The Python server issues a local session and serves the built frontend with engine mode enabled. See [Dashboard integration](../docs/runtime/DASHBOARD-INTEGRATION.md). `npm run dev` on port 5173 remains the independent mock design prototype; it does not silently substitute for an unavailable engine.

React + Vite, browser-only. Built on 12 October 2026 from the existing [PRD](../PRD-CCTV-Productivity-Tracker.md), [UI/UX specification](../UI_UX_SPEC.md), and [design system](../DESIGN_SYSTEM.md). The prototype imports the shared [design tokens](../docs/ui/design-tokens.json) without changing them.

Production architecture remains Python, PySide6, ONNX Runtime, SQLite and the local engine API. This directory is a separate design and interaction review artifact, not a production frontend migration. The user's 12 October request explicitly permits labeled mock data and React/Vite for this prototype.

## Launch on this Windows machine

Node.js 22.12 or newer and npm are required. Verified here with Node 24.18.0 and npm 11.16.0. Dependencies are pinned in package.json and package-lock.json.

Open PowerShell and run:

```powershell
Set-Location -LiteralPath 'C:\Users\muham\OneDrive\Documents\ChatGPT\cctv 2\prototype'
npm.cmd ci
npm.cmd run dev
```

Then open **http://127.0.0.1:5173/** in a browser. Keep that terminal running. Ctrl+C stops the server. `npm.cmd` avoids PowerShell execution-policy problems with npm.ps1; in a shell where npm is available normally, `npm ci` and `npm run dev` are equivalent.

Run from a checkout containing this directory and its sibling docs directory because the shared tokens are imported at build time. There are no environment variables, secrets, API keys, CCTV streams, database setup, or backend service to configure.

The dev server binds only 127.0.0.1. If port 5173 is occupied, stop the other dev server or use `npm.cmd run dev -- --port 5174` and open the printed URL. Tests use port 5173.

Vite's dev/build/preview scripts follow the [official Vite guide](https://vite.dev/guide/). The generated build bundles the shared tokens and does not read production files at runtime.

## Build and preview the built prototype

```powershell
npm.cmd run build
npm.cmd run preview
```

Open **http://127.0.0.1:4173/**. The build is generated under prototype/dist, which is ignored by Git. Stop the preview terminal with Ctrl+C.

## What is interactive

- **Ringkasan:** live snapshot, period filters, weighted metric strip, trend series toggles, bucket inspection, camera health navigation, workstation comparisons and event detail.
- **Pemantauan Live:** search/status filters, focus/2×2/3×3 layouts, selection and inspector, optional zone/detection/anonymous-track overlays, fullscreen, preview pause, camera states, manual zone observations and event inspection.
- **Workstation:** search/area/state filters, global sorting/pagination, create/edit properties, polygon drag and coordinate editing, add/delete vertices, undo/redo, geometry validation, revision review and simulated apply acknowledgment.
- **Analitik:** date/workstation/resolution/source filters, historical summaries, trend legend/detail selection, heatmap selection, timeline segments and interval provenance. Missing denominators show N/A.
- **Laporan:** global sort, page navigation, search, full-filter CSV export, accepted/running/completed jobs, cancellation, actual browser download and expired-snapshot recovery.
- **Kamera:** create/edit configuration, mocked credential availability, password visibility, successful/failed connection tests, enable/disable and diagnostic dialogs. Password input is never persisted.
- **Pengaturan:** site/calendar/retention review, mock persistence health, browser-local snapshots, restore review, JSON download and reset.

Global controls:

- **Mulai/Jeda simulasi:** advance one scenario minute every four real seconds. The initial state is paused for repeatable review.
- **+1 menit:** make one deterministic step, generating eligible observation intervals and activity events.
- **Skenario:** normal connections, first camera offline, inference unavailable, persistence failure, expired report or an empty first-run dataset.
- **Pekerjaan:** inspect asynchronous mock jobs and download/cancel results where supported. Most jobs complete in approximately 1.8 seconds.
- **Definisi metrik:** inspect P/A/U, coverage, utilization, anonymous identity and prototype limitations.

## Mock data and semantics

The persistent banner labels all data as simulated. Fixture: six example cameras, twelve anonymous workstations, one year of weekday history, scenario anchor **12 October 2026, 10:42 UTC+07**. The site and all workstation/camera names are fictional. Camera frames are SVG illustrations, not footage or detector output.

P = occupied workstation duration; A = observed empty duration; U = unknown; T = P+A+U. Utilization = P/(P+A). Coverage = (P+A)/T. Totals are duration-weighted. Multiple occupants do not multiply workstation presence time. Zero denominators produce N/A. Employee identity, productivity scores, working/idle classifications and raw-video playback remain outside V1 scope.

The “7 hari terakhir” filter is a rolling date range; weekly report buckets start Monday. Historical fixture schedule is Monday-Friday, 09:00-17:00 with a 12:00-13:00 break. Calendar changes affect future simulation steps, not historical fixture observations. The prototype supports daytime shifts and UTC+07 timezones only; complete shift/DST rules remain part of the production design.

Configuration, manual simulation intervals, events and snapshots persist under browser localStorage key `cctv-design-prototype-v1`. Jobs are session-only. If browser storage is unavailable or full, the current session continues in memory. Reset in Settings restores the fixture and clears pending mock jobs. Reloading a browser is not a production engine-recovery test.

Retention controls simulate detail availability. Original fixture source remains in memory to model retained aggregate results; no SQL/data deletion runs. JSON backups are browser-state snapshots, not verified SQLite backups. All jobs, credential flags and health states are mock behavior.

## Verification

```powershell
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
```

Browser tests use an isolated headless Microsoft Edge context by default on Windows, not the user's signed-in browser profile. An installed Chrome can be selected with:

```powershell
$env:PROTOTYPE_BROWSER_CHANNEL = 'chrome'
npm.cmd run test:e2e
```

Tests start the dev server or reuse one already serving port 5173. They verify navigation/history, simulation transitions, preview freeze, forms, secret exclusion, geometry/revisions, analytics, timeline, export/download/cancel, snapshots/restore, retention, empty states, modal focus and viewport resizing. They also reject application exceptions and external HTTP requests.

Actual browser screenshots are saved in verification/screenshots; failure traces/screenshots are under ignored test-results. The current results and their limits are recorded in [verification/RESULTS.md](verification/RESULTS.md).
