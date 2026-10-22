# UI monitoring merge validation

22 October 2026. Merge `codex/ui-monitoring-improvements` (3fe21c7) into master based on 6e4aa3d. Integration was performed in an isolated checkout; local screenshots and runtime databases were excluded.

The merge retains the unified report navigation, daily reports, explicit camera status, mobile camera selection, prototype 16-slot grid, blank video areas and all-camera fullscreen. Master features retained include persistent managed cameras, concurrent camera analysis, recording settings and destinations, backup/restore, measured track captions and bounded display predictions.

Integration adjustments:

- Registered-camera source resolution supports both preview cameras and managed cameras; an active managed analysis cannot also start through the primary engine.
- Report and daily CSV queries retain the selected camera.
- Managed-camera setup uses its own calibration and analysis controls; the primary webcam/legacy wizard remains separate.
- Primary preview responses retain frame/run/mapping correlation while preserving the snapshot interface used by recording and managed-camera presentation.
- Session snapshots retain tracker IDs required for activity/prediction expiry. Supplied-track test fixtures implement that tracker contract.
- Backup verification checks schema 4 and all four migration checksums, including person sessions.
- Tracker recovery configuration and one-to-one measured-box matching are preserved.

Validation:

- Production frontend build passed; 16 frontend domain/workflow tests passed.
- Complete Python suite: 179 passed, 7 skipped. Skips cover optional model/sample assets and the rclone helper. Optional models were absent in the isolated checkout; existing model files were subsequently referenced for dashboard startup only.
- Final tracker/session/live subset after the last matching/configuration adjustment: 43 passed.
- Browser smoke check used the real merged dashboard with a separate database and a deliberately unavailable loopback RTSP address. Registration selected the matching managed-camera controls; its report action retained the camera selection in unified reports; daily reports, recording settings/destinations and maintenance panels were reachable. No warning/error was captured in the final browser log.
- `git diff --check` passed.

The legacy Playwright suites were not run in full. The smoke check does not validate real camera inference accuracy, multiple live decoders, native fullscreen on an external browser, or production capacity.
