# Multi-camera dashboard and pilot hardening

15 October 2026. This increment adds concurrent RTSP analysis to the React dashboard, persistent camera configuration, verified backup/restore, a process supervisor, Windows SCM integration, release installation checks, and local video evaluation. These features advance the V1 pilot; they do not certify physical camera capacity or close every PRD acceptance criterion.

## Dashboard workflow

1. Open **Pemantauan Live** and **Tambah kamera**. Registration persists under the selected database's sibling `<stem>-fleet` directory. The registry encrypts the complete RTSP URL with Windows DPAPI CurrentUser. On Linux it uses Fernet with a local mode-0600 key; protect the data directory and backup copies. There is no plaintext URL in status or reports.
2. Select a camera, wait for its preview, and choose **Atur zona kamera**. Draw and save its workstation polygons. The profile is bound to the camera fingerprint and image aspect ratio.
3. Choose **Mulai analisis kamera**. Repeat for another camera. Each camera has independent tracking, sessions, unknown gaps, calibration and a SQLite ledger. A bounded FIFO shares one detector instance so model memory is not multiplied per camera. Slow/late observations are rejected and become unknown; the 16-camera registry limit is not a throughput guarantee.
4. Enable **Pulihkan otomatis** per camera if it should resume after process restart or engine failure. Manual stop clears the desired-running flag. Failed engines have exponential retry delays and a five-attempt cap; 60 seconds of healthy operation resets the counter. Ordinary RTSP reconnect continues inside each engine.
5. Use **Kamera laporan** or **Laporan kamera ini** to select the camera whose metrics, timeline and CSV are displayed. Reports are per camera, not a sum of unique people across views. Archiving a camera stops it, removes it from the wall and preserves historical reports. Re-registering creates a new identity/history.

Analysis continues when the browser changes pages or closes. Preview subscriptions are still on demand. The legacy webcam/primary RTSP session remains available, with separate history; a browser webcam necessarily depends on browser frame delivery. Duplicate analysis of the primary RTSP source in the managed fleet is rejected. Managed-camera overlays use image and observations from the same snapshot.

Changing URL/name and cross-camera report aggregation are not added in this increment. Register the replacement source and recalibrate it; archived history remains available. Calendar/holiday/break accounting still has `schedule_applied=false`.

## Backup and restore

**Pengaturan → Backup dan pemulihan** provides manual backup, daily automatic backup, retention of backup snapshots (1–365 days), verification and exact offline restore instructions. A job completes only after SQLite integrity, foreign-key, schema/checksum and artifact checksum checks. Each database is independently consistent; there is no single transaction across independent camera ledgers. At least two newest backups and pre-restore safety snapshots are kept. This retention policy does not delete observation history.

Backups include replay, primary live, every managed-camera ledger, calibration and encrypted registry/key. They exclude video and model files. Schedule runs only while the engine is alive. Backups remain on the same local disk; off-device disaster recovery is a separate operational responsibility.

Restore requires stopping the app and supervisor/service. Use the command shown by the dashboard, or:

```powershell
python -m cctv_tracker.maintenance --database 'C:\Data\dashboard-pilot.sqlite3' list
python -m cctv_tracker.maintenance --database 'C:\Data\dashboard-pilot.sqlite3' verify --backup-id '<id>'
python -m cctv_tracker.maintenance --database 'C:\Data\dashboard-pilot.sqlite3' restore --backup-id '<id>'
```

Restore verifies every source before writing, acquires application/writer locks, makes a pre-restore backup, and writes a durable transaction journal. A crash during restore blocks application startup; rerun the same restore command to finish. A completion receipt survives restoration. Windows credential recovery requires the same machine/account. Stop other CLI tools accessing those databases during maintenance.

## Supervisor and Windows service

The installed `run.ps1` starts `cctv_tracker.supervisor`, which owns the app process tree, probes loopback health, applies bounded restart backoff, and requests graceful shutdown. A Windows Job Object closes owned child/capture processes even when forced cleanup is needed. Engine checkpoints bound the recovery gap. An inference worker unresponsive for 60 seconds causes unhealthy status; ordinary camera network failure does not restart the whole application. Five failed restarts stop the supervisor; inspect `supervisor-status.json` and logs rather than looping forever.

Development invocation:

```powershell
python -m cctv_tracker.supervisor --state-dir runtime/supervisor --health-url http://127.0.0.1:8765/health -- python -m cctv_tracker --database 'C:\Data\dashboard-pilot.sqlite3' dashboard --port 8765
```

The release contains `install-service.ps1`. From an elevated PowerShell, in the extracted installation directory:

```powershell
.\install-service.ps1 -Action Install
Start-Service CCTVWorkspace
# Stop before restore or upgrading:
Stop-Service CCTVWorkspace
# Remove registration without deleting data:
.\install-service.ps1 -Action Uninstall
```

This uses the native Windows SCM host in `windows_service.py`, not a scheduled task. Select the account that owns the camera credentials and grant it service logon and installation/model/data directory access. The script registers but does not silently replace or start an existing service. The SCM path still needs a target-machine install/start/stop/reboot test before service deployment acceptance. Linux can run the generic supervisor under a site-managed systemd service; a Linux installer matrix has not been verified here.

## Packaging

```powershell
cd prototype
npm ci
npm run build
cd ..
python scripts/build_editions.py
```

Separate `dist/editions/cctv-enterprise-0.2.0.zip` and `cctv-headless-0.2.0.zip` contain versioned wheels. Enterprise includes compiled frontend, supervisor launcher, service installer and these instructions. `install.ps1` verifies release file checksums, creates a Python 3.12 environment and installs the locked runtime plus edition wheel. It creates `deployment.json` with local data outside source/cloud-sync folders. Put `webcam-yolox.onnx` in `models`; edit deployment configuration for CPU/GPU selection. Node is not needed on the installed client. Headless still requires its signed license/configuration and uses its separate dependency lock.

For offline installation, prepare a `wheelhouse` containing all lock-file dependencies and use `install.ps1 -Offline`. Stop the app/service before upgrading; existing deployments receive a pre-upgrade backup. Python 3.12 itself and model weights are not bundled. This is a scripted Python installation, not a frozen single-file EXE.

## Local recording evaluation

`cctv_tracker.evaluation` reads an existing video without changing it and runs YOLOX/OpenVINO → ByteTrack → polygon association → the actual SQLite interval pipeline. Supply annotated occupied/empty/unknown intervals per zone and an explicit coverage minimum:

```powershell
python -m cctv_tracker.evaluation --video 'C:\Videos\sample.avi' --annotations 'annotations.json' --output runtime/evaluation-new --min-coverage 0.8 --detector yolox-openvino --device GPU
```

Annotation format:

```json
{"version":1,"annotation_source":"reviewer and review method","zones":[{"id":"desk1","name":"Desk 1","polygon":[[0,0],[1,0],[1,1],[0,1]],"intervals":[{"start_seconds":0,"end_seconds":10,"state":"OCCUPIED"},{"start_seconds":10,"end_seconds":20,"state":"EMPTY"}]}]}
```

Ground-truth time must be relative to the first video frame. Intervals must not overlap; missing predicted evidence counts as unknown. Output includes a duration-weighted confusion matrix, precision/recall over valid observations, recall including unknown, coverage, model/runtime, latency percentiles, predictions and database. Both classes must have measurable metrics to meet numeric thresholds. Preliminary assistant-reviewed samples do not substitute for independent complete scene annotations or production AC-12.

## Soak and performance

```powershell
python scripts/soak_fleet.py --output runtime/soak-new --seconds 86400 --cameras 4 --detector yolox-openvino --device GPU --image 'C:\Data\sample-frame.jpg'
```

The fixture uses simulated capture and alternating repeated-image/blank frames. With OpenVINO selected, actual inference, tracking and SQLite run; `--detector fixture` explicitly injects detections. One source periodically disconnects. Measurements include RSS, CPU time, per-camera effective FPS, result age, inference time, threads and disk usage. It enforces memory/disk limits, progress timeouts and final database/duration invariants. `result.json` remains RUNNING until the requested duration completes. Creating `STOP` in the output directory requests graceful cancellation. Outputs are local and ignored by Git. Physical RTSP/network stability, representative footage and supported hardware capacity still need their own benchmark.
