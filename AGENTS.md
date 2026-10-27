# Replay and live parity

The user's standing instruction is that replay is the reference for live CCTV.
Apply every applicable replay engine feature, fix, setting and UI/UX change to
live in the same task, starting now. Do not leave live on an older implementation.

- Prefer shared modules/components for detection, area association, occupancy
  confirmation, evidence thresholds, timers, ArUco, calibration and overlays.
- The active workstation mode bypasses person tracking and ReID. Keep applicable
  fixes to the experimental person mode consistent across both paths as well.
- Add or update tests comparing replay and live on the same measured evidence.
  Preserve matching outcomes for area state, duration and marker check-in.
- Keep source adapters explicit: replay uses media time, seek and interval
  deduplication; live uses monotonic capture time and committed SQLite records.
  Replay must never write production accounting or invent evidence in skipped
  footage. Live must never count camera outages as occupied time.
- Reuse the editor, labels, results and fullscreen behavior. Source-specific
  connection and playback controls must reflect what that source actually supports.
- Validate both paths before reporting completion. Clearly report unavailable
  physical-camera validation; do not claim accuracy or FPS from synthetic tests.
