# Operational UI improvements

Implemented 15 October 2026 in the integrated React dashboard. This increment addresses the seven requested UI/UX priorities using the existing Python engine and report API.

Navigation update: Kamera is merged into Pemantauan Live. The six primary destinations are Ringkasan, Pemantauan Live, Workstation, Analitik, Laporan and Pengaturan. Camera previews, setup and management remain available in the Live view. Legacy `#/cameras` links are replaced with `#/live` without adding a history entry or recreating the webcam capture. The standalone mock prototype follows the same navigation and exposes its camera configuration beneath the Live view.

| Priority | Result |
|---|---|
| 1. Camera-first monitoring | Existing 1/4/9/16 camera wall retained, separate webcam control row, focus/fullscreen and per-source preview/analysis labels |
| 2. Guided setup | Four steps: select source, verify connection, calibrate zones, start monitoring. Saved calibration must match the actual camera and image aspect ratio |
| 3. Visual hierarchy | Shared panel, spacing, typography, action and responsive layout rules; current operations appear above period statistics |
| 4. Operational language | Session, saved observations, people observed and data completeness replace internal terms in primary screens; runtime/model details are in Settings diagnostics |
| 5. Useful overview | Actual camera connection state, fresh active-source observations, zone state counts, latest saved record, next actions and period summaries |
| 6. Feedback | Connection/start/stop states, waiting for permission/frame, report/export loading, confirmed calibration save, actionable failures and explicit empty data |
| 7. Reports | Local-date daily/seven-day/custom/shift filters, overnight shifts, duration bars, unknown-reason breakdown, CSV export and direct workstation timeline drill-down |

## Data semantics

The reporting source defaults to Camera live. Users may explicitly select Replay simulasi; the source preference is retained locally. Current live counts always come from the live endpoint, independently of the selected reporting source. Replay durations are never represented as current live presence.

Unavailable or stale live observations display as unavailable. Counts are cleared after lost polling/freshness evidence, stopped sessions and connection failures. The overview does not infer counts from saved assignments or add headcounts across cameras. Additional RTSP previews remain preview-only; the existing single active accounting source limit is preserved.

Shift selection is an explicit time-range filter for one selected date, not an employee schedule or automatic break calendar. An end time earlier than the start time crosses to the following local day. Reports cover all stored sessions in a dated range. Future ranges are rejected; an ongoing range ends at the time the user applies the filter. The applied bounds and IANA timezone are shown. Custom nonexistent or ambiguous DST wall times are rejected rather than silently shifted.

Unknown durations are retained and explained. Occupancy uses occupied divided by occupied plus empty time. Coverage uses observed divided by eligible monitoring time. Multi-workstation duration is accumulated workstation time, not worker productivity or person-hours. API/CSV reporting semantics remain unchanged (`schedule_applied=false`).

Calibration/start/stop continue to use the existing API. Successful calibration feedback follows a successful save. A stop success message waits for the session to finish. Model loading, detection, tracking, accounting and persisted data are unchanged.

## Verification

Run from the prototype directory:

```powershell
npm test
npm run build
npm run test:engine
npm run test:webcam
```

The new pure tests cover location time conversion, invalid dates, overnight shifts, seven-day ranges, 23/25-hour DST days, ambiguous/nonexistent local times and stale/live count semantics. Browser coverage includes real API query bounds, CSV export, timeline drill-down, empty/future ranges, runtime diagnostics, navigation, responsive widths and the complete webcam calibration/monitoring flow with synthetic video. Tests do not open a physical webcam.

The optional three-RTSP rig and its environment flag are described in [CAMERA-WALL.md](../runtime/CAMERA-WALL.md). Synthetic footage remains explicitly labeled. This UI increment does not establish commercial detection accuracy or new multi-camera inference capacity.

Completed verification: 10 frontend domain tests, six dashboard/API browser tests and 14 webcam/camera-wall browser tests passed, including the optional three-RTSP rig. The production frontend build and whitespace check passed. The screenshot artifacts are under `prototype/verification/screenshots/operations-*.png`; all camera footage used in verification was synthetic.

## Launch

From the repository root:

```powershell
.\run-app.ps1 -Detector yolox-openvino -OpenVinoDevice GPU -DatabasePath runtime/integrated-pilot.sqlite3
```

Open http://127.0.0.1:8765/ and refresh after rebuilding an existing server. The independent Vite mock prototype remains a separate mode.
