# Workstation live and replay position timers

Replay overlays previously displayed lifetime analysis totals. Rewinding through
already counted media could not change those totals and appeared to freeze the
box clock. Classified media intervals now provide the occupied duration up to
the playhead, including while paused. Report totals stay deduplicated. Seeking
does not classify skipped footage, charge gaps, or reset saved measurements.
Old checkpoints retain their totals and acquire position details during replay;
missing historical details are not reconstructed from a total alone.

Live uses the same AreaCalibration, WorkstationOverlay and WorkstationResults
components: drag a box, move corners, name areas, optional ArUco registry,
occupied/empty counters and CSV. RTSP and webcam overlays use compact labels;
individual preview fullscreen keeps settings outside the video and overlays
controls. Camera selection and connection remain prerequisites for calibration.
Changing calibration ends the active live session and keeps prior session data
in the live reports. Legacy homography calibration remains supported separately.

The workstation live path bypasses ByteTrack, SessionManager and ReID. Area
totals derive from the zone intervals committed to SQLite. Camera gaps stop
occupied time. Marker check-in uses the same dictionary and confirmation policy
as replay; reconnect clears identity confirmation. Registered markers do not
establish uninterrupted individual attendance or overwrite employee identity.

The workstation launcher previously opened the prototype Shell because Vite did
not set the engine-dashboard flag. It now opens EngineApp and bootstraps its
same-origin local session before requesting camera and monitoring endpoints.
The existing live transport still supports one analyzed camera at a time.

Validation:

- PASS: 349 backend tests, 33 frontend tests, production frontend build.
- PASS: four new live-area tests cover bypassing person tracking, committed
  totals, stale frames, real ArUco PNG decoding, reconnect, calibration API
  validation, final totals after stop, and persisted configuration.
- PASS: replay backend tests cover interval overlap, skipped footage, legacy
  checkpoints, restart and invalid position intervals. Frontend tests cover
  prefix totals and backward/forward seeks without mutating report totals.
- PASS: real 075831.mp4 browser check, including paused fullscreen seek:
  position 60 seconds shows 20 seconds occupied; position 5 shows zero;
  position 40 shows 6 seconds. Table totals stay 68 occupied and 38 empty.
  Evidence: runtime/seek-timer-browser.json and runtime/seek-timer-fullscreen.png.
- PASS: real dashboard opens EngineApp, exposes live sources and area results,
  and has no observed browser errors during verification.
- PASS: explicitly synthetic UI fixture exercises the actual shared components:
  draw a second area, rename, keyboard corner movement, marker ID 7 and label,
  save two areas with one marker, Escape, loss of evidence and fullscreen.
  The fullscreen frame and image measure 1280 x 800, and the timer holds when
  evidence stops. The fixture HMR root lifecycle was corrected; no new console
  warnings/errors appeared after the final reload.

Delivery Gate, scoped to the changed desktop UI:

- Hard Gate PASS: build and tests above; keyboard, error and empty states,
  fullscreen geometry, settings isolation and real replay seek checked.
- Purpose Gate PASS: existing CCTV palette, area editor and playback icons;
  no new decorative product sections or visual assets. Caption contrast over
  the brightest background is 7.59:1; focus contrast is 7.73:1.
- Liveliness PASS: video remains the focal point; compact overlays and controls
  remain subordinate. Existing direction: ENERGY 1 / RHYTHM 1 / MOTION 1.
- Craftsmanship PASS: shared editor and results, explicit test-fixture labeling,
  preserved report totals, no identity or camera-accuracy claims.

No RTSP camera was configured during verification. Physical camera performance,
badge readability and viewpoint-specific occupancy accuracy remain unvalidated.
UI evidence: runtime/live-area-editor.png. The synthetic fixture never starts
the user's webcam or writes its sample configuration to the live database.
