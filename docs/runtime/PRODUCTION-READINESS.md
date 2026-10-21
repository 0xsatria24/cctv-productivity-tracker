# Production readiness: sequential work

Updated 22 October 2026. Scope: the `21f5` checkout. Keep Python and measure native/runtime costs before changing language. The current release remains an internal pilot. No hardware capacity or commercial accuracy is certified by this work.

The user requested sequential implementation. The 24/72-hour test must be launched manually by the user. No long soak is launched by the agent.

| Order | Work | Current evidence / next gate |
|---|---|---|
| 1 | Reproducible labelled field dataset | Dataset exporter, local annotation editor, provenance, checksums, PTS and split leakage validation implemented. Three supplied clips exported into 1,477 images. Labels still require review. All three belong to one recording-day group. |
| 2 | Detector accuracy and model comparison | Paired offline comparison executed on 15 assistant-reviewed frames / 29 reference boxes: YOLOX GPU/CPU, NanoDet CPU and rejected ROI-zoom experiment. Confidence sweep and interactive error review implemented. Human review, held-out data and model qualification remain open. See [stage 2 evidence](DETECTOR-EVALUATION.md). |
| 3 | Working/Idle meaning | PRD measures presence/occupancy. Existing Working/Idle is a motion heuristic. Task/rest recognition and stationary work remain unvalidated. |
| 4 | Durable tracking/session correctness | Existing ByteTrack and conservative weak recovery have regression tests. Application-session persistence, annotated IDF1/HOTA and identity-crossing acceptance remain separate gates. Prior implementations in other checkouts are not assumed integrated here. |
| 5 | Duration correctness | Zone accounting distinguishes UNKNOWN. Offline replay now uses the live image transform and weak candidates. Full person-session/ground-truth duration acceptance remains pending. |
| 6 | Native inference isolation | Bounded fair scheduling exists. Native model execution still shares the app process. Supervised inference-process isolation is not completed by this batch. |
| 7 | Reliability soak | New manual API observer and launch wrapper provided; existing synthetic fleet runner accepts up to 72 hours. Unit/browser checks and dry-run only. User must run the long tests. |
| 8 | Supported hardware/camera capacity | Requires target hardware, real cameras, enabled recording/uploads and measured limits. No camera-count promise. |
| 9 | Video/runtime optimization | Shared bounded capture and OpenVINO exist. Async requests, hardware decode and quantization require separately measured accuracy/capacity comparisons. |
| 10 | Monitoring/alerts | Existing engine telemetry plus manual observer capture progress, age, queue/drop counters and resources. Product alert delivery/operations acceptance remains pending. |
| 11 | Storage/recovery | Existing recording/cloud/backup features require explicit fault tests, interrupted upload/file tests and restored-recording playback evidence. |
| 12 | Security/deployment | Existing loopback auth, protected credentials, supervisor/service and release scripts need clean-machine, service-account, upgrade and rollback acceptance. Network deployment requires its own reviewed auth/TLS/RBAC boundary. |

Work proceeds through these gates in order. Preparing a tool is not equivalent to completing the associated field acceptance. This batch completes the dataset/evaluation tooling and the specifically requested manual-test program. It does not complete all twelve production gates.

## Stage 1: local dataset and annotation

From the repository root, use the existing Python 3.12 environment:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
.\.venv\Scripts\python.exe -m cctv_tracker.dataset annotate --dataset runtime/production-dataset-factory-20180903 --port 8773
```

Open <http://127.0.0.1:8773>. The annotation tool is separate from the dashboard. Stop it with Ctrl+C. Labels are saved atomically into `runtime/production-dataset-factory-20180903/labels.json`. No labels are uploaded.

Workflow:

1. Enter the reviewer name. Pick the scenario tags. Draw all visible person boxes, including distant people, using the visible-body extent consistently. Do not invent the outline behind a machine. Entirely invisible people have no box.
2. Use anonymous IDs consistently within each clip only. If identity through an occlusion is uncertain, use a separate ID and a comment. IDs do not prove employee identity.
3. Mark a frame reviewed only after checking every person. An explicitly reviewed empty frame has no boxes and the Empty tag. Unreviewed empty arrays are excluded from accuracy calculations.
4. The copy-previous button creates a draft. Check geometry and identity again before marking reviewed. Edits invalidate the frame's review state.
5. Human, assistant and pseudo-label provenance remain explicit. Assistant/pseudo labels never constitute independent ground truth. Two open tabs cannot silently overwrite newer labels: stale revisions are rejected.

The three original files remain unchanged. Exports, local labels, model predictions and paths are under ignored `runtime/`, outside Git. Rights to redistribute the original dataset still require review.

Preparation used native media PTS, rejected corrupted decoded frames and preserved aspect ratio at a maximum long side of 640 pixels with JPEG quality 75, matching live capture. Sampling at a maximum of 2 FPS can miss short events and is suitable for initial detection review. It does not certify continuous tracking.

| Source | Decoded frames | Corrupt frames rejected | Exported review frames |
|---|---:|---:|---:|
| 093131.mp4 | 3,975 | 264 | 493 |
| 091812.mp4 | 3,959 | 265 | 491 |
| 100656.mp4 | 3,975 | 265 | 493 |

Files include source/image SHA256, native FPS, original media timestamps and group metadata. All clips are `pilot` data from `factory-20180903`. Nearby clips from the same recording day are not independent held-out sites. Split validation rejects a recording group or duplicate source checksum spanning train/validation/test within a manifest.

To prepare a different recording group, create a fresh directory:

```powershell
.\.venv\Scripts\python.exe -m cctv_tracker.dataset prepare --video 'C:\Videos\another-day.mp4' --group site-A-day-2 --split test --sample-fps 2 --output runtime/dataset-another-day
```

## Stage 2: frozen baseline, then accuracy

The current private baseline is `runtime/production-dataset-factory-20180903/baseline-yolox-openvino-gpu.json`. It contains 1,477 real inference outputs, model checksum, provider and runtime metadata. It is not a set of labels. The measured GPU model-call median was approximately 92 ms and P95 159 ms in this offline run; this is not a real-time multi-camera capacity benchmark.

After label review, run:

```powershell
.\.venv\Scripts\python.exe -m cctv_tracker.dataset evaluate --dataset runtime/production-dataset-factory-20180903 --predictions runtime/production-dataset-factory-20180903/baseline-yolox-openvino-gpu.json --output runtime/production-dataset-factory-20180903/evaluation-reviewed-1.json
```

Evaluation reports person-box precision/recall/F1 at confidence 0.45 and IoU 0.5, with per-clip and scenario breakdowns. Matching maximizes match count before total IoU, rather than greedily assigning the highest pair. It includes false positives on reviewed empty frames. Missing predictions count as misses; review and prediction coverage are explicit. It refuses mismatched manifests, nonfinite boxes and unfinished baselines. Output remains `production_qualified=false`, including on a perfect pilot result.

Continuous tracking metrics will use a densely annotated sequence and the reference [TrackEval implementation](https://github.com/JonathonLuiten/TrackEval) for HOTA/IDF1. Current person-box metrics are explicitly not HOTA, IDF1 or AP. Fine-tuning and threshold selection must use training/validation data; the held-out test group stays frozen.

The existing zone-duration evaluator remains a separate command documented in [PILOT-HARDENING.md](PILOT-HARDENING.md). Its image preparation now shares the live capture transform, uses low-confidence tracking candidates for UNKNOWN evidence, drops corrupt/duplicate frames and marks the unsampled tail UNKNOWN. Media-time replay does not model wall-clock scheduler overload.

## Manual 24/72-hour test

The new observer watches an already running dashboard. It does not start/stop cameras, change recording settings, open a webcam or upload anything. Prepare the desired cameras, recording, cloud destination and preview layout yourself before launching. Keep the computer awake and reserve sufficient disk space.

Validate the command without starting any test:

```powershell
.\scripts\run-manual-soak.ps1 -DurationHours 24 -ValidateOnly
```

Launch manually when ready:

```powershell
.\scripts\run-manual-soak.ps1 -DurationHours 24 -Url 'http://127.0.0.1:8767'
```

For process-tree CPU and RSS, provide the current app/supervisor PID:

```powershell
.\scripts\run-manual-soak.ps1 -DurationHours 24 -ProcessId 12345
```

Replace `12345` with the current PID, not a PID from an earlier report. Without it CPU/RSS checks are explicitly skipped. Use `-DurationHours 72` for the later soak. No scheduling or automatic launch is configured.

Outputs go into a fresh `runtime/manual-soak-<UTC timestamp>` directory:

- `result.json`: RUNNING until requested duration completes, or FAILED/CANCELLED; measured elapsed time, findings and skipped checks. Completion alone does not imply acceptance. `acceptance_passed` covers the observer's configured checks only, never the twelve release gates.
- `samples.jsonl`: per-camera committed progress, effective FPS, session resets, result age, rolling engine latency, available queue/capture counters and zone states; optional process resources and free disk. Memory remains bounded instead of retaining a 24-hour list in RAM.
- `manual-events.example.json`: example for a separate `manual-events.jsonl` operator log. It is not fabricated fault evidence.

Ctrl+C or creating an empty `STOP` file in that output directory cancels the observer, with `acceptance_passed=false`. It leaves the app running. Never reuse an output directory for a new run.

Advanced thresholds and individual camera selection:

```powershell
.\.venv\Scripts\python.exe scripts/soak_dashboard.py --url http://127.0.0.1:8767 --hours 24 --output runtime/soak-custom-1 --camera '<camera-id>' --pid 12345 --min-fps 2 --max-age-ms 1500 --max-rss-mb 3072 --max-growth-mb 256
```

Default thresholds are pilot checks, not contractual SLOs: 60-second startup grace, 30-second no-progress/persistent-condition window, 0.5 FPS minimum, 5,000 ms result age, 4,096 MiB process-tree RSS, 512 MiB growth after warmup, 1,024 MiB free disk and a 256 MiB log cap. Resource findings persist for the configured condition window. Disk/log exhaustion stops the observer with failure. API session cookies are refreshed after an app restart. Camera IDs remain fixed for the run, so removing a camera cannot silently improve results.

On a dedicated test installation, log and inspect these manual faults individually: disconnect/reconnect a test camera; restart the owned engine; restart the test machine; interrupt/recover a cloud connection; reach a test recording quota; play interrupted/recovered recordings; make and restore a backup with the app stopped. Do not alter the real machine clock or fill the system disk. Use a disposable installation for clock jumps, disk-full and destructive crash tests. Each scenario needs expected behavior, timestamps, recovery evidence and a separate acceptance decision.

The observer does not force crashes or validate video contents, database restore, ground-truth durations, GUI rendering or model accuracy. Its P95/P99 fields are the engine's rolling windows, not whole-day quantiles. Use the existing fixture-only `scripts/soak_fleet.py` separately when simulated capture is intended; it labels its source as simulated and now accepts up to 259,200 seconds.

Free space is measured on the observer output volume. Other recording/cloud volumes require separate monitoring. Brief faults shorter than the polling interval can be missed; retain camera event logs and the manual event journal. For a 72-hour run with many cameras, size `--max-log-mb` and disk reserve explicitly; reaching the cap is a reported failure, not silent log truncation.

## Verification of this batch

Short automated checks cover annotation persistence/navigation, explicit empty-frame review, copied drafts, malformed labels, train/test leakage, confidence/IoU matching, missing predictions, image checksums, corruption policy, offline/live input parity, local-server CSRF and concurrent edits, manual-monitor state and dry-run behavior. Long-duration and target-hardware results remain pending user execution.

Evidence from this batch: backend regression suite 135 passed, 5 skipped, 3 dependency deprecation warnings; final dataset-focused checks 8 passed; annotation browser scenario 1 passed. Both 24-hour and 72-hour wrapper checks returned `NOT_STARTED` in dry-run mode. The real dataset evaluation returned `AWAITING_LABELS` with zero reviewed frames, rather than an invented accuracy score.
