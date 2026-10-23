# Workstation release target: 31 October 2026

## Implemented on 23 October

- Primary replay totals belong to calibrated workstation IDs. Person replacement,
  new tracker IDs, and rejected ReID matches cannot reset a workstation total.
- Occupied, empty, and unknown durations partition sampled media time. Two seconds
  confirm occupied; five seconds confirm no detection. A contradictory sample ends
  the previous state at its last supporting sample. Missing, weak, ambiguous, and
  long-gap evidence never earns occupied time. Counts do not multiply elapsed time.
- Live already persists workstation intervals independently of person sessions;
  contradictory-frame accounting now follows the same conservative rule.
- Replay has an authenticated polygon editor, overlap/body or visible-foot
  association, server validation, revision checks, and bounded per-file RAM totals.
  Calibration templates persist in this browser after engine acknowledgement.
- Seek, loop, or calibration changes explicitly begin a new replay measurement;
  pause freezes totals. Replay remains non-accounting and never writes reports.
- Person timers and ReID are secondary experimental diagnostics. Predictions are
  short visual aids and never workstation evidence. Employee assignments in the
  registry do not establish a person's observed identity.
- Independent-label evaluation measures precision/recall at IoU 0.5, session ID
  switches, sessions containing multiple labeled people, workstation duration
  error, and coverage. Comparison inputs are saved to disk, not held as a video
  in memory. A Windows CI workflow is configured for regressions and the frontend
  build; its remote execution has not been verified in this change.

## Measured limits

The first 60 seconds of `075831.mp4`, 301 samples at 5 FPS, YOLOX OpenVINO GPU
and active retail-0287 ReID, produced 47 empty detection frames and 2 recoveries.
An explicitly experimental front-area polygon accumulated **18 s occupied and
42 s unknown (30% coverage)**. It retained its occupied total across person
session fragmentation. Warm median was **96.58 ms/frame** while another UI replay
was running; this is not an isolated performance comparison.

Evidence: `runtime/workstation-validation/factory-active.json` and its saved
sample images. This polygon is a UI/continuity test, not an operator-approved
workstation boundary. There are no independent identity/occupancy labels for
this clip yet, so recall, false-merge precision and duration accuracy are **not
measured**. More permissive ReID thresholds cannot repair missed detections.

A second run compared the same 301 JPEGs with ReID off and confidence 0.45:

| Candidate | Empty detection frames | Occupied / unknown | Warm median |
| --- | ---: | --- | ---: |
| YOLOX OpenVINO GPU | 47 | 18.0 / 42.0 s | 56.10 ms |
| NanoDet ONNX CPU | 68 | 17.8 / 42.2 s | 30.31 ms |

NanoDet is faster on these different runtime/device combinations, but produces
more empty frames and no workstation coverage improvement. It is not promoted.
These are measured continuity/latency counts, not ground-truth recall or identity
accuracy. Evidence: `runtime/workstation-validation/detector-comparison.json`.

## Validation commands

```powershell
.venv/Scripts/python.exe -m pytest -o addopts= -q --basetemp=runtime/release-tests -p no:cacheprovider
npm.cmd --prefix prototype test
npm.cmd --prefix prototype run build
.venv/Scripts/python.exe scripts/diagnose_replay_stability.py --video <video.mp4> --seconds 1800 --profiles balanced detail --calibration <zones.json> --reid-mode off --output runtime/release/compare.json
.venv/Scripts/python.exe scripts/evaluate_replay_quality.py --labels <reviewed-labels.json> --results runtime/release/compare.json --profile balanced --output runtime/release/quality.json
```

Choose a new output filename for every diagnostic run. Its `*-frames` directory
contains the exact JPEGs for independent annotation; profiles consume those same
files. The calibration input is `{"association":"bbox_overlap","zones":[...]}`;
each zone has `id`, `name`, and a simple normalized `polygon` of 3–32 points.

Labels use this format (the example below describes the schema, not evidence):

```json
{"schema_version":1,"reviewer":"reviewer's name","frames":[
  {"time":0.0,"people":[{"person_id":"manual-person-A","box":[0.1,0.1,0.3,0.8]}],"zones":{"desk-1":"OCCUPIED"}}
]}
```

Label every sampled frame and every person, including misses; use stable manual
IDs and all configured zones. `UNKNOWN` is an allowed manual state. Results and
labels must have the same advancing timestamps and unchanged calibration.
Duration comparisons use consecutive intervals with the same known manual state
and no more than one second between samples. Unknown-reference intervals do not
prove accuracy. The report always says `production_ready=false`: a labeled clip
alone cannot certify a deployment.

Proposed release gates for the approved camera/view: at least 30 minutes of
independent labels spanning normal movement, bending, occlusion, shift changes,
empty periods and similar uniforms; precision and recall >=90%; workstation
interval duration error <=5% and coverage >=95%; no observed false identity
merge and identity assignment coverage >=95% for the evaluated ReID candidate.
Review metrics separately on held-out footage, not the tuning clip.
These are proposed targets, not achieved accuracy or a guarantee.

## Remaining release work and target dates

| Date | Required evidence |
| --- | --- |
| 23 Oct | Stable workstation clocks, calibration editor, revision isolation, automated regressions and a real-video continuity run. Implemented locally. |
| 24–25 Oct | Operator-approved camera placement/ROIs; complete independent labels on target CCTV footage; separate calibration and held-out recordings. Requires actual deployment input. |
| 26–27 Oct | Compare detector candidates on identical labeled frames. Change weights/profile only if recall, duration error and target-hardware latency improve. Calibrate ReID with same/different-person pairs in a separate split. |
| 28 Oct | Exercise real RTSP disconnect/reconnect, camera/view changes, engine restart, disk-full/write failure, backup restore, multi-camera load and access control on the deployment host. Existing synthetic tests do not replace these runs. |
| 29–30 Oct | At least 24 hours on the deployment host; inspect memory, stalled queues, unknown coverage, database integrity, backup restore and report continuity. |
| 31 Oct | Release only if all measured gates pass and the operator approves the calibrated views. Otherwise retain pilot status with the failed evidence recorded. |

Initial production scope is anonymous workstation occupancy. Per-employee time
needs a separately verified identity/assignment source and explicit uncertainty;
clothes or a ReID session are not that source. A one-camera pilot can meet the
date only if footage, annotation and deployment access are available promptly.
