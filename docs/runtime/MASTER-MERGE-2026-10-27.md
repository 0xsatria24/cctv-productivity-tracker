# Master integration, 27 October 2026

Merged `codex/ui-monitoring-improvements` at `8bbd9bd` into master at `29c4cb0`, preserving both histories.

The combined application keeps master's persistent multi-camera fleet, recordings and storage destinations, recovery, backup/restore and performance reporting. It also includes shared replay/live workstation evidence, ArUco check-in, area calibration, overlays, fullscreen, replay checkpoints, confidence separation and experimental person/ReID changes.

Conflict resolutions and compatibility fixes:

- Dashboard, replay and managed-camera lanes share the new bounded per-source inference scheduler. The previous FairDetector import remains available for existing callers.
- Per-camera live controllers use the shared workstation engine and editor. Managed-camera results display that camera's area state and duration. Editing an active managed camera stops its accounting session before calibration can be changed.
- Replay and live use the same configured weak-track recovery and display-prediction limit. Weak tracking proposals remain separate from public detections and do not create occupancy evidence.
- Dataset baselines, zoom experiments and occupancy evaluation consume both public detections and separate weak proposals. Exported proposals are never ground truth. The older occupancy evaluator remains available alongside frame/session evaluation.
- Live RTSP capture and offline frame preparation share the aspect-preserving JPEG transform, retaining up to 720p detail. Missing source time bases do not invalidate monotonic live capture.
- Backup verification uses the installed migration list, verifies the ReID migration checksum, and accepts older supported schemas for migration when the database is opened. Recording and maintenance controls remain accessible in Settings.
- Updated legacy tests and browser fixtures to reflect source-bound detector lanes and separate weak proposals. Added migration compatibility/checksum coverage and a browser test for the combined managed-camera workflow.

Validation of the merged sources:

- Backend: 445 passed, 2 skipped. The skipped cases require the optional official rclone helper, which is not installed. JUnit output: `runtime/merge-master-20261027-verified.xml`.
- Frontend: 34 domain tests passed; production build passed.
- Browser: `merge-workstation.spec.js` passed using a local synthetic camera. It exercises area editing, committed occupied state, workstation results, fullscreen entry/exit, recording settings, backup creation and checksum verification, with no page errors.
- Both parent branches' tests are retained, including shared-evidence replay/live parity checks.

No physical camera, live FPS, field accuracy, cloud upload transport or long-duration production soak validation is claimed by this merge. Local videos, models, databases, credentials and runtime test outputs remain excluded from Git by `.gitignore`.
