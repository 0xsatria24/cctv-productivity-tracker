# Multi-camera monitoring pilot

The integrated React dashboard now opens Kamera and Pemantauan Live with a CCTV camera wall. It uses the existing solid dark surfaces, restrained teal, small radii, text statuses and native cursor from DESIGN_SYSTEM.md. The production desktop architecture and single-source accounting pipeline are unchanged.

## Use

```powershell
.\run-app.ps1 -Detector yolox-openvino -OpenVinoDevice GPU -DatabasePath runtime/integrated-pilot.sqlite3
```

Open http://127.0.0.1:8765/#/live and refresh after rebuilding. The three display modes share one camera workspace:

- **Grid** is the default balanced view with 1, 4, 9 or 16 display slots (initially 2 × 2).
- **Fokus** enlarges the selected camera and keeps up to five companion cameras visible. Companion pages leave the primary camera pinned; selecting a companion makes it the primary camera. Each source occupies only one slot.
- **Video wall** uses the saved grid density with smaller gaps and compact tile information. It hides the camera directory and selection inspector, preserving their settings for the other modes. Camera names, connection states, webcam controls and the mode picker remain available.

Changing modes keeps the selected camera, overlay switches and grid density. All modes reuse the existing source components; switching layout does not recreate the webcam media track. Layar penuh expands the viewport in any mode, and the mode picker remains available in fullscreen. Smaller viewports scroll within the grid rather than silently reducing the selected density.

- The left list searches camera names and selects a camera. Daftar kamera toggles this list.
- Tambah kamera opens a labeled name/RTSP form. Each source has its own connection state and image. Adding a record does not claim a successful connection.
- Click a tile to select it. Double-click, Enter on a tile, or Fokus opens Fokus with the selected camera as primary and other cameras as companions. Escape outside a form/dialog or Kembali ke grid returns to the saved grid density. Removing or hiding the primary selects an available source without changing modes.
- Sembunyikan dari grid removes a source from the current view. Select it in the left list to restore it. Hapus removes an additional preview connection after a confirmation dialog.
- Webcam lokal retains the existing browser capture and YOLOX pipeline. Its settings button opens device, resolution, mirror and fit controls. Layout/focus/navigation do not recreate its media track or detector sampling loop. Use Deteksi to show person boxes; Zona controls calibrated polygon visibility. These switches do not change accounting rules.
- Pencatatan dan kalibrasi zona expands the existing source/calibration controls beneath the camera wall. Active sessions remain visible. Laporan still uses the existing live/replay data selection.

## What runs concurrently

The pilot supports multiple **RTSP previews**, alongside the webcam and an existing live-engine RTSP source. Up to 16 additional RTSP sources can be registered during an application session. Grid pages prevent a source from occupying two tiles. Streams are identified by canonical endpoint excluding credentials; an endpoint already used by the live engine reuses that preview rather than showing a duplicate tile/starting another visible decoder.

**Detection/tracking/accounting still processes one active source.** Additional feeds are explicitly labeled Preview saja and do not produce counts, zone durations, or reports. Starting live-engine RTSP leaves the webcam video connected and pauses its detector requests until the engine becomes available again. This is not a 16-camera inference capacity claim.

Each RTSP preview uses the existing isolated PyAV capture process with a one-frame mailbox, 640-pixel longest edge and sampled frames. The browser pulls latest JPEGs with bounded requests, clears stale/missing frames and never labels a missing image Live. Use a camera/NVR substream for a multi-preview installation. The rig verified three RTSP feeds concurrently with a webcam; installation capacity and smoothness at 9/16 connected feeds still need hardware-specific measurement.

Only displayed RTSP previews receive renewable visibility leases. Fokus requests its primary and visible companions; Grid and Video wall request their current page. Changing modes/pages, hiding a source, or hiding the browser tab releases demand for previews no longer displayed. Multiple viewers are independent. Browser departure expires demand within 12 seconds; the bounded decoder shutdown then releases resources. This affects extra previews, not the live accounting session.

RTSP names/URLs remain in server memory for the current application process. They disappear when Python restarts. URLs/passwords are excluded from API metadata, localStorage and SQLite. Preferences saved locally are only display mode, grid density, list visibility and overlay toggles. Camera selection and pagination last for the current UI session. No audio or image/video recording is added. Persistent camera registry/credential storage remains a separate production feature.

## Local preview API

All routes use the existing loopback authentication, cookie/bearer session, Origin validation and no-store responses:

| Route | Behavior |
|---|---|
| GET /pilot/v1/camera-wall | Camera names, opaque IDs, connection state and fresh-frame time; no endpoint/secret |
| POST /pilot/v1/camera-wall/cameras | Add name and validated RTSP endpoint in memory |
| DELETE /pilot/v1/camera-wall/cameras/{id} | Release and remove a preview source |
| POST /pilot/v1/camera-wall/view | Renew a viewer's visible source IDs; an empty list releases demand |
| GET /pilot/v1/camera-wall/cameras/{id}/frame.jpg | Latest fresh JPEG plus X-Frame-Time and X-Frame-Sequence; 404 when unavailable |

These routes neither create engine runs nor write observation intervals. Capture errors use fixed sanitized text. The manager releases child processes on shutdown.

## Verification

15 October display-mode checks: 14 frontend unit tests passed, along with three focused camera-wall browser tests. The optional real synthetic-RTSP rig was skipped in this run. Checks cover webcam track continuity across all modes, shared camera selection/density/overlays, primary and companion pagination, visibility demand, fullscreen mode switching, reload preferences and 1440/1100/760 widths. The multi-source mode test uses explicitly labeled metadata/image fixtures; it verifies UI behavior rather than decoder or 16-camera performance. Reviewed screenshots are in `prototype/verification/screenshots/camera-mode-{grid,focus,wall}-1440.png`.

Python verification covers independent source frames, viewport demand, lease expiry, source uniqueness across credential changes, secret redaction, authentication/Origin validation and absence of reporting mutations. Browser checks cover 1/4/9/16 layouts, camera focus, search, fullscreen, 1440/1100/760 widths, independent images, disconnect feedback, webcam navigation continuity, real OpenVINO inference, calibration and SQLite reporting.

The optional four-display verification uses three distinct synthetic RTSP publishers and Chromium's fake webcam. No physical camera is opened:

Completed checks on 14 October: 58 Python tests passed; 14 webcam/camera-wall/live browser tests (including the optional real three-RTSP rig) and three existing dashboard integration tests passed. The final focused backend run also verified canonical endpoint deduplication and live/API compatibility. Frontend build and whitespace checks passed.

```powershell
# Requires the optional MediaMTX test binary under runtime/rtsp-test-server/.
# This helper owns a localhost-only test server and stops it on Ctrl+C.
.\.venv\Scripts\python.exe scripts/run_camera_wall_test_sources.py
```

In another PowerShell terminal, with the dashboard test server on port 8766:

```powershell
cd prototype
$env:CCTV_WALL_RTSP_TEST = '1'
npm run test:webcam
```

Without that environment flag the optional three-RTSP test is skipped. Test media says SYNTHETIC TEST CAMERA / NO PHYSICAL CCTV. The saved screenshot under prototype/verification/screenshots/camera-wall-four-synthetic-1440.png is a test record, not installed camera footage.
