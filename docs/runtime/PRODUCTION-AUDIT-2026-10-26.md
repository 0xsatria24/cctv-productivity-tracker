# CCTV tracking audit, 26 October 2026

Release readiness: **FAIL for the requested production-grade persistent identity system**.
The fixes below are implemented and tested. They do not establish reliable long-term
identity, restart re-identification, or adequate detection quality on this factory video.
This is a validated incremental patch, not completion of every mission requirement.

## Checkout and environment

- Repository: `D:\Projects\cctv 2`, branch `codex/ui-monitoring-improvements`.
- Baseline: `65f7f8d05ec1af7f8887d6d262a18b68065716fe`.
- Existing replay/UI changes and screenshots were present before this audit.
  Only the prediction-lifetime plumbing and its test were added to the already modified
  `prototype/src/replay-domain.js` and `prototype/tests/replay-domain.test.mjs`.
- Windows 11 build 26200; Python 3.12.14; Intel i7-1185G7, eight logical CPUs;
  OpenVINO reports Intel Iris Xe iGPU. No installed torch, Ultralytics, BoxMOT, or TensorRT.
- Installed: numpy 2.2.6, PyAV 16.0.1, ONNX Runtime 1.23.2, OpenCV 4.12.0.88,
  Supervision 0.26.1, OpenVINO 2026.4.1, pytest 8.4.2.
- Tested the existing model artifacts; no downloads, dependency additions,
  quantization, model replacement, production database edits, or deployment.
- YOLOX manifest and bundled notice identify Apache-2.0; the ReID manifest pins
  local XML/BIN hashes and preprocessing. Library code licenses do not establish
  rights for arbitrary replacement model weights. Review any new weights separately.

## Pipeline and ownership audit

| Stage | Source/function | Ownership and behavior |
| --- | --- | --- |
| Capture | `rtsp.capture_worker`, `RtspCapture` | One spawned process per RTSP source; mailbox capacity one; latest-frame replacement; duplicate PTS skipped; backwards PTS creates a generation |
| Webcam ingestion | `LiveController.submit` | Queue capacity one; overload rejected; monotonic sequence required |
| Scheduling | `InferenceScheduler.turn`, `ScheduledDetector.detect_latest` | One resident detector, FIFO among eligible sources, one request per source, bounded waiting; refreshes stale queued camera image before inference |
| Detector | `WebcamDetector.detect`, `OpenVinoYoloX._infer`, `person_detection` | Lock owns mutable inference request/output; top-left RGB 640 letterbox; independent public and weak-candidate thresholds; NMS and proposal caps |
| Tracker | `vision.Tracker.update` | Per-pipeline/replay tracker; generation and large-gap reset; elapsed-time prediction budget; only current measured boxes returned |
| Sessions | `SessionManager.update`, `_pairs`, `_recover` | Single accounting owner; bounded history; mutual unique matches; geometry ambiguity veto; temporary track IDs are not identities |
| Appearance | `ReIdRuntime.prepare/apply/commit`, `Gallery` | Same-frame crops; bounded vectors/metadata; no frame retention; staged gallery publication after accounting commit |
| Events/storage | `Pipeline.feed`, `RunWriter.commit` | UTC anchored to monotonic time; reject stale envelopes before mutation; session, zone and event updates in one SQLite transaction |
| Live rendering | `LiveController.preview_frame` | Bounded eight-frame history; frame sequence/run/mapping metadata; stale previews expire |
| Replay rendering | `ReplayTracking.process/_display_rows`, `ReplayOverlayMotion` | Media time; isolated from production accounting; bounded visual carry; seek/generation reset |
| Multi-camera | `EngineService`, `CameraWall` | Headless cameras have independent controllers, DBs and tracker state; detector is scheduled/shared. Camera wall alone is preview, not multi-camera accounting |

`OnnxDetector` is a separate manifest-based adapter; `WebcamDetector` and
`OpenVinoYoloX` share preprocessing. `ShadowReId` is a compatibility alias, not
another identity engine. Replay intentionally has separate storage semantics.
No evidence justified deleting these paths or replacing ByteTrack.
Ultralytics is not used, so `persist=True` is not an applicable fix.

The installed Supervision implementation replaces `removed_tracks` each update;
it does not append an unlimited removed-track history. Source inspection ruled out
that proposed leak. ReID models can still be duplicated across live pipelines;
this patch does not claim multi-camera model-memory optimization.

## Reproduced defects and implemented changes

1. **Confirmed last-seen timestamp moved on weak observations.**
   `SessionManager.update` updated `last_seen` on every associated low-confidence
   box. Reproduction: confirmed at 1.2 s, weak at 1.4 s, stored last-seen became
   1.4 s. It now remains 1.2 s; kinematic `last_ns` can still advance for association.
   Weak positions also no longer accumulate zone-exit confirmation votes.

2. **Observed duration was not independently available when lost-gap charging was enabled.**
   Added `observed_ns`, accumulated only between consecutive strong observations,
   transferred exactly once on recovery. Snapshots expose `observed_duration_us`,
   `total_elapsed_us`, and `absence_duration_us`. Existing `accumulated_duration_us`
   remains compatible with its configured gap policy. A synthetic 15 s observation,
   3 s absence and recovery retains 15.2 s observed versus 18.2 s legacy accumulated
   with gap charging enabled. `first_seen` remains unchanged on validated recovery.

3. **An unassigned weak replay box was labeled MEASURED.**
   `ReplayTracking.process` previously treated `session is None` as measured
   evidence. A confidence 0.46 box with a 0.50 strong threshold now reports WEAK.

4. **Cold ReID compilation permanently disabled the provider.**
   `ReIdRuntime.prepare` included model initialization in its 150 ms limit and
   permanently disabled ReID after exceeding it. A real-model probe measured
   9302 ms on the first frame, then DISABLED_AFTER_ERROR on both following frames.
   `OpenVinoExtractor.warmup` now reports first initialization. Cold overruns
   produce WARMUP_BUDGET, discard all embeddings/votes for that frame, and allow
   the next frame to retry the warm provider. Steady-state overruns and provider
   errors still disable it. Startup latency itself is not eliminated.

5. **An alive, stalled preview decoder was never restarted.**
   `PreviewCamera._run` only restarted dead/error workers. It now tracks progress
   separately from preview freshness: initial deadline is open + read timeout;
   after receiving a frame, the read timeout applies. Repeated/backwards frame
   timestamps do not refresh the watchdog. The worker is closed before reconnect.
   Both never-delivered and stopped-after-first-frame fixtures failed before this
   fix and now pass.

6. **Visual carry lifetime was hardcoded.**
   `TrackingRules.display_prediction_seconds` is validated in [0,1], default 0.4.
   The replay response carries this policy to both browser display paths.
   Predictions remain marked, never become session or occupancy evidence, and
   expire using media time including response lag. Zero disables the replay
   carry window, including browser holding of old measured boxes. It does not
   change detector/tracker association thresholds.

No separate global `person_id` was fabricated by renaming `session_id`.
ACTIVE/LOST/EXPIRED remains the actual implemented lifecycle. Long-term dormant
identities and cross-restart appearance recovery remain unimplemented.

## Before/after evidence

User-selected folder: `C:\Users\muham\Videos\videos\20180903`.
Selected file: `091346.mp4`, SHA-256
`2d1c55f653202138a86d3ede5f01a2923dd71b8e5ac70d53f52bbf53dcf99683`.
265 seconds, 640x480, 15 source FPS; sampled at 5 FPS, 1325 frames.
The file is byte-identical to the local copy used for the initial 12-second baseline.
The first frame was inspected: workers wear similar clothes and are partly obscured
by machinery. No independently verified identity annotations were supplied.

Both complete-video runs use the same GPU FP32 detector and shadow ReID with
default thresholds. Baseline imports an archived HEAD source tree; the patched
run imports the working tree. Source module paths and package versions are saved
in the JSON reports. Timings are descriptive desktop runs, not controlled capacity
certification; some validation processes overlapped. No speedup is claimed.

| Full selected video | Baseline | Patched |
| --- | ---: | ---: |
| Frames | 1325 | 1325 |
| Warm median processing, ms | 78.86 | 83.56 |
| Warm p95 processing, ms | 153.87 | 150.09 |
| Warm service throughput, FPS | 11.18 | 10.33 |
| Total harness wall time, s | 133.41 | 143.19 |
| Frames disabled after ReID error | 1318 | 0 |
| SHADOW evaluation frames | 3 | 662 |
| SAMPLE_INTERVAL frames | 3 | 662 |
| Initial budget failure | LATENCY_BUDGET, permanent disable | WARMUP_BUDGET, retry succeeds |
| No public detections | 931 | 931 |
| Session starts | 90 | 90 |
| Final retained sessions | 4 | 4 |
| Final gallery identities | 0 | 2 |
| Post-startup sampled RSS, MiB | 466.3-468.9 | 468.1-470.5 |

Shadow mode cannot improve bindings by design. Identical counts/session starts
are not evidence of correct identity. The baseline was faster partly because
ReID stopped doing work; the patched run performs appearance extraction.

On the first 61 samples, balanced versus detail produced 33 versus 30 empty
frames, 6 versus 9 session starts, and 96.98 versus 401.71 ms warm median processing.
Five-pass detail has not demonstrated an acceptable benefit for this scene.
Defaults and confidence thresholds were therefore preserved.

IDF1, HOTA, identity switches, false-match and false-non-match rates are **not
reported** for the real video: these require verified track/identity ground truth.
The large no-detection count is a coverage concern, not a claimed recall score.

Evidence files under `runtime/production-audit/`:

- `baseline-full-video.json`, `after-full-video.json`: full video rows and RSS.
- `baseline-real.json`, `profile-comparison.json`: short detector-profile comparison.
- `baseline-reid-startup.json`: real cold-start reproduction.
- `baseline-synthetic.json`, `after-synthetic.json`: session stress/latency probes.
- `tests.xml`: final backend suite result.
- `rtsp-result.txt`, `rtsp-server.log`: isolated localhost reconnect smoke test.
- `source-first-frame.jpg`: inspected source frame.

## Memory and backpressure

No measured evidence justified quantization, reduced detection resolution, or a
cache rewrite. RSS is approximately 2 MiB higher with working ReID, not lower.
The harness itself retains a bounded list of result rows, which contributes to
its RSS; this is not a pure measurement of long-running server retention.
Iris Xe uses shared memory; dedicated VRAM consumption was not measurable here.

The synthetic 16-person manager retained 16 sessions and 128 history samples.
Baseline Python retained heap was 56,772 then 58,080 bytes after two 1000-frame
phases; patched was 57,404 then 58,664 bytes after two 2000-frame phases, peak
185,312 bytes. Phase lengths differ, so these are bounded-state observations,
not a percentage memory improvement. No overnight soak was executed.
The old validation script's `pipeline_baseline` field only loads HEAD's Pipeline
with current imported dependencies; do not treat that field as a complete
before/after version comparison. The complete-video harness isolates the source tree.

Existing bounds: RTSP mailbox 1, webcam queue 1, preview history 8, scheduler
queue 64 and stream metrics 128, session capacity 256 with eight history samples,
ReID gallery 128 identities x four samples and 30 s TTL, replay capacity 64.
These are finite but not a guarantee that 64 simultaneous replay clients fit
this machine. API overload is rejected; capture keeps recent frames; neither
creates fabricated empty detections. Gallery vectors contain no retained pixels.

## Architecture decision

Retain **A: YOLOX/OpenVINO + pinned ByteTrack + external SessionManager/SQLite**,
with the existing optional conservative ReID component. This is the only locally
measured architecture, and it allows correctness fixes without replacing the
working ingestion, accounting and UI interfaces. It is not a claim that A wins
an unperformed head-to-head benchmark.

| Candidate | Correctness/continuity | FPS, p95, RAM, VRAM | Deployment and maintenance |
| --- | --- | --- | --- |
| A: current ByteTrack + sessions | Short-gap conservative recovery tested; long-term identity incomplete | Local results above; VRAM unavailable | Existing Windows/OpenVINO stack; lowest change cost here |
| B: BoT-SORT, OC-SORT, Deep OC-SORT + persistent gallery | Potential candidates; none solve restart/visit semantics by themselves | Not installed or benchmarked; no invented numbers | New tracker/embedding contracts and labeled comparisons required |
| C: DeepStream/NvDCF + ReID | Needs the same identity/session policy and validation | Not runnable on the detected Intel-only hardware | NVIDIA-supported deployment platform and a substantial stack migration required |

Primary references: [ByteTrack](https://github.com/FoundationVision/ByteTrack),
[BoT-SORT paper](https://arxiv.org/abs/2206.14651),
[BoT-SORT license](https://github.com/NirAharon/BoT-SORT/blob/main/LICENSE),
[OC-SORT](https://github.com/noahcao/OC_SORT),
[Deep OC-SORT](https://github.com/GerardMaggiolino/Deep-OC-SORT), and
[NVIDIA installation requirements](https://docs.nvidia.com/deepstream/text/DS_Installation).
BoT-SORT's upstream code is MIT. This is not a legal certification for a complete
distribution or its external model assets.

FP32 is preserved. FP16/INT8 require an accuracy/calibration evaluation that is
not available. TensorRT/NVIDIA decoding are not appropriate for the detected
hardware. ONNX Runtime and OpenVINO already exist; swapping backends does not
repair missing identity evidence or justify a timer merge.

## Validation and acceptance

- **PASS:** 313 backend tests, 3 dependency deprecation warnings; 27 frontend
  tests; Vite build; `git diff --check`.
- **PASS:** 14 new backend cases cover confirmed time, absence/elapsed time,
  gap accounting separation, weak labels/zone exit, durable fields, prediction
  validation, ReID cold/steady latency, and preview stalls.
- **PASS:** existing tests cover stationary/moving people, motion recovery after
  a 3 s gap, crossings, similar appearance rejection, ambiguous matching, weak
  evidence, variable cadence, stale results, tracker reset, failed checkpoint,
  generation isolation, bounded galleries and four-camera shared scheduling.
- **PASS:** localhost RTSP publisher stop/restart, actual decoder/inference path,
  at least two generations, SQLite integrity/foreign-key checks, and shutdown.
  The synthetic RTSP source is not a person-recognition accuracy test. Coverage
  was only 4.94% during its short reconnect-heavy test; that is not a capacity claim.
- **PASS:** full 265 s supplied video executed through real detector, tracker,
  session manager and shadow ReID. Replay made no production accounting writes.
- **NOT VALIDATED:** full real-camera UI click-through, low-light field accuracy,
  hour-scale soak, real multi-camera capacity, labeled IDF1/HOTA and identity errors.
- **FAIL:** persistent person identity across minutes, source reconnect and
  application restart. Existing run finalization expires sessions; embeddings
  remain memory-only and generation-scoped. DB history is durable, identity
  rehydration is not implemented. Session duration fields surviving DB reopen
  must not be described as restart re-identification.
- **FAIL:** adequate detector continuity on the selected factory scene.

Initial test attempts in the restricted environment encountered default temp
permissions and an asyncio socketpair hang before application execution. Using
workspace temporary directories and allowing local Windows sockets produced
the complete passing suite. No application workaround for the sandbox was added.

Provisional engineering targets for this machine: at 5 inference FPS, warm p95
processing should stay below the 200 ms cadence budget on a controlled single
camera run; preserve the 1 s stale-evidence cutoff. Use the approximately 470 MiB
warm RSS measurement as a baseline for a repeated fixed-workload soak, not a
hard production memory limit. A multi-hour run must show bounded post-warmup
retention before a memory release gate can pass. Tracking-quality thresholds
cannot be calibrated from unlabeled detections; label representative return,
crossing, occlusion and similar-uniform sequences before accepting identity merges.

## Configuration and operational guidance

- Keep ReID `off` in production by default; use `shadow` to collect diagnostics.
  `active` remains available only under its existing conservative gates.
- Keep public confidence 0.45, strong evidence 0.50, tracking-only threshold 0.10,
  and NMS IoU 0.50 until labeled evaluation supports a change.
- Keep `sessions.count_lost_gap=false`. `observed_duration_us` always excludes
  absence, even if a legacy deployment explicitly enables gap charging.
- Session grace defaults to 10 s; motion recovery 3.5 s. Increasing retention
  alone does not make a returning person's identity known.
- `tracking.display_prediction_seconds` defaults to 0.4; set 0 to disable replay
  hold, never increase it to conceal long detector gaps.
- WARMUP_BUDGET means the first late embedding batch was discarded and another
  sample will be attempted. LATENCY_BUDGET on a warm provider still disables
  that runtime. Investigate hardware load/crop counts; do not raise thresholds
  merely to hide slow inference. Startup may still stall a request.
- Review scheduler queue/service latency, expired/refreshed counts, tracker active/
  lost counts, session rejection metrics and ReID status/crop rejection metrics.
  RSS is measured by the benchmark; a continuous production RSS/VRAM exporter
  was not added.
- Gallery privacy remains in-memory TTL/capacity plus explicit clear on generation
  changes. No persistent biometric gallery was introduced. Existing SQLite event
  storage still needs an operational retention policy; this audit does not delete
  historical records or silently change retention.

## Reproduction, deployment and rollback

From the repository root, use a fresh `--basetemp` path for each pytest run:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp runtime/production-audit-rerun --tb=short
npm.cmd --prefix prototype test
npm.cmd --prefix prototype run build
.\.venv\Scripts\python.exe scripts/benchmark_tracking_runtime.py --video 'C:\Users\muham\Videos\videos\20180903\091346.mp4' --output runtime/production-audit/rerun.json --seconds 265 --reid-mode shadow
```

For the baseline, export `src` from commit `65f7f8d` to an isolated directory and
pass its `src` directory using `--source-root`. Do not replace the current checkout.
The benchmark's environment section records which source tree actually loaded.
For the optional detector-profile comparison:

```powershell
.\.venv\Scripts\python.exe scripts/diagnose_replay_stability.py --video 'C:\Users\muham\Videos\videos\20180903\091346.mp4' --output runtime/production-audit/profiles-rerun.json --seconds 12 --device GPU --profiles balanced detail --reid-mode off
```

No DB schema migration is needed. New observed time is included in checkpoint
JSON and `person_sessions.matching_json`; older rows without the field are
unknown, not zero. Existing legacy timing columns remain compatible. Before a
pilot deployment, stop capture cleanly and back up SQLite through its backup API
or after closing writers, including any needed WAL state. Keep a source/config
snapshot. Build the frontend, then launch an isolated pilot database:

```powershell
.\run-app.ps1 -DatabasePath runtime/production-audit-pilot.sqlite3 -Detector yolox-openvino -OpenVinoDevice GPU -DetectionProfile balanced
```

This command is for a controlled pilot; the production release gate above fails.
The task-specific patch `runtime/production-audit/task-only.patch` is prepared
for selective rollback and preserves pre-existing frontend changes:

```powershell
git apply --reverse --check runtime/production-audit/task-only.patch
git apply --reverse runtime/production-audit/task-only.patch
npm.cmd --prefix prototype run build
```

Stop the app before rollback. If the reverse check fails because of later edits,
review the conflicting hunks instead of resetting the checkout. No database
downgrade is required. The reverse dry-run was checked when this report was made;
the actual rollback was not applied.

## Delivery review

- R-31 / comment review PASS: the new runtime comment explains discarded cold-start
  evidence; no decorative or restated implementation comments were added.
- R-35 validation PASS for this code patch: backend/frontend tests and build executed;
  no new UI controls or visual design were delivered. Browser click-through remains
  explicitly unverified.
- C-5 / R-36 evidence PASS: measured results and unavailable metrics are separated;
  no production accuracy, capacity or memory reduction is claimed.
- Visual-design gate items are not applicable to this backend/policy change.
  The skill does not override the explicit user request for executable fixes or an
  honest FAIL release assessment.
