# Stage 2: detector comparison and accuracy diagnosis

Date: 22 October 2026. Checkout: `21f5`. This stage implements and executes paired detector comparison, confidence sweeps, object-size recall diagnostics and private visual error review. No live model, inference threshold, calibration, recording policy or dashboard behavior is changed. No 24/72-hour test is launched.

## Evidence and limits

The original evaluation dataset has 1,477 frames from three same-view factory recordings on one day. At the start of this stage the user's `labels.json` had zero reviewed frames. That file and its draft edits were preserved.

The assistant visually examined six evenly spaced unoverlaid frames per recording, before reading the model predictions. Three frames with unclear heavily occluded background outlines were left unreviewed. A separate preliminary snapshot contains **15 reviewed frames and 29 visible-body person boxes**, all with `label_source=assistant`. Anonymous IDs are frame-local box labels, not tracking identities. Tight outlines for distant, cropped and occluded people require human correction. No empty scene, crossing, low-light or independent site/day acceptance is represented by this selection.

Private artifacts under ignored `runtime/detector-stage2/`:

- `labels-assistant-pilot.json`: separate assistant reference; never merged into the user's labels.
- `yolox-openvino-gpu.json`: measured YOLOX-S/OpenVINO FP32 GPU candidates.
- `yolox-cpu.json`: same YOLOX-S weights, ONNX Runtime CPU.
- `nanodet-cpu.json`: different, already installed NanoDet model, ONNX Runtime CPU.
- `yolox-openvino-zoom-gpu.json`: same YOLOX-S plus one exploratory ROI zoom pass.
- `comparison-final/comparison.json`, `summary.csv`, `review.html`, `labels-snapshot.json`: frozen diagnostic results, self-contained interactive review and label snapshot.

Both models were already installed. We downloaded no weights and changed no licenses. Model checksums, provider/runtime metadata, selected frame keys and label snapshot hashes are retained. The verified pinned upstream reference is the [OpenCV Zoo YOLOX implementation](https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/object_detection_yolox), with the [NanoDet implementation](https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/object_detection_nanodet) used as the smaller-model reference.

## Measured pilot results

Confidence 0.45, IoU 0.5, the same 15 images and 29 assistant reference boxes for every row. Each profile received two warmup calls before timing. Calls ran sequentially, in separate Python invocations. Timing includes reading the cached JPEG and the detector call, not camera decode, scheduling, tracking, GUI or recording. Desktop/background load was not controlled, so this is not a certified hardware speed comparison.

| Profile | TP | FP | FN | Precision | Recall | F1 | Image-call P50 | Image-call P95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| YOLOX OpenVINO GPU | 8 | 0 | 21 | 100.0% | 27.6% | 43.2% | 54.2 ms | 67.5 ms |
| YOLOX ONNX CPU | 8 | 0 | 21 | 100.0% | 27.6% | 43.2% | 168.7 ms | 283.0 ms |
| NanoDet ONNX CPU | 10 | 1 | 19 | 90.9% | 34.5% | 50.0% | 24.4 ms | 30.6 ms |
| YOLOX GPU with ROI zoom | 8 | 0 | 21 | 100.0% | 27.6% | 43.2% | 116.9 ms | 125.8 ms |

These percentages are **diagnostic agreement with assistant box estimates**, not validated factory accuracy. Zero false positives on this small nonempty selection does not establish field precision. NanoDet's higher pilot recall and lower measured call time do not establish that it is the best production detector.

Object-height diagnosis uses an explicit local definition, not COCO's small-object metric:

- Height below one third of the frame: **0/16 matched** for all four profiles at confidence 0.45.
- Height at least one third of the frame: **8/13 matched** for standard/zoom YOLOX and **10/13** for NanoDet.

Frame-level scenario metrics include all people in frames with that tag. They do not isolate the tagged person's behavior. The separate height-bin diagnostic is per ground-truth object.

## Experiments and decisions

The evaluator swept confidence 0.10, 0.20, 0.25, 0.35, 0.45, 0.55 and 0.65. Weak YOLOX measured candidates are cached separately from display detections. A legacy or NanoDet cache filtered at 0.45 cannot support a lower-threshold experiment; its unavailable rows are labelled `UNAVAILABLE_BELOW_CACHE_FLOOR`, not assigned a false zero score.

For standard YOLOX, confidence 0.25 gave 8 TP / 1 FP; 0.10 gave 9 TP / 2 FP. Lowering the threshold alone did not recover the small/far workers in this sample. The sweep is exploratory pilot analysis; it does not choose a deployment threshold.

The zoom experiment uses the same model on the full image and normalized region `(0.30, 0.00, 0.55, 0.40)` around the rear station. Coordinates are mapped back to the source image. Candidates touching artificial crop boundaries are rejected; true source edges are allowed. Cross-pass duplicates use IoU suppression. Regions and the candidate count are bounded. This region was chosen from the pilot scene, so it is not an independent test configuration.

This ROI experiment produced no matching improvement and added another inference pass. **Do not adopt it for live use based on this result.** `ZoomExperiment` is referenced only by the offline dataset runner and its tests; live `engine.py`, Enterprise and Headless do not construct it.

The results point toward data/model-domain and visibility problems worth investigating: distant or occluded bodies are being missed by multiple runtimes, including the same-weight CPU/GPU paths. This is an inference from the pilot evidence, not proof of a particular training defect. Changing application language would not supply the missing labelled examples or improve the model's learned person features.

## Review and reproduce

From the repository root:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
.\.venv\Scripts\python.exe -m cctv_tracker.detector_report_server --directory runtime/detector-stage2/comparison-final --port 8774
```

Open <http://127.0.0.1:8774>. Controls switch detector, confidence and scenario, filter error frames, navigate frames, and toggle reference/predicted boxes. Solid green is reference, dashed green a missed reference, blue a matched prediction and orange a false positive. Reference provenance and pilot limits stay visible. The HTML embeds the selected images and needs no external service. The preview serves only the generated document, with loopback Host checks; it does not expose a directory listing or label JSON endpoints.

To create a fresh cache after reviewing a separate label snapshot:

```powershell
$env:CCTV_MODEL_DIR = 'C:\Users\muham\OneDrive\Documents\ChatGPT\cctv 2\models'
.\.venv\Scripts\python.exe -m cctv_tracker.dataset baseline --dataset runtime/production-dataset-factory-20180903 --labels runtime/detector-stage2/labels-assistant-pilot.json --reviewed-only --warmup 2 --detector yolox-openvino --device GPU --output runtime/detector-stage2/new-yolox-cache.json
```

For CPU YOLOX use `--detector yolox --device CPU`; for the smaller reference use `--detector nanodet --device CPU`. No automatic device fallback is allowed. Add `--zoom-region 0.30,0,0.55,0.40` only to reproduce the offline experiment. Every output path must be new.

Generate another paired comparison without inference:

```powershell
.\.venv\Scripts\python.exe -m cctv_tracker.detector_evaluation --dataset runtime/production-dataset-factory-20180903 --labels runtime/detector-stage2/labels-assistant-pilot.json --prediction 'YOLOX GPU=runtime/detector-stage2/yolox-openvino-gpu.json' --prediction 'NanoDet CPU=runtime/detector-stage2/nanodet-cpu.json' --output runtime/detector-stage2/comparison-new
```

The comparison refuses mismatched datasets, incomplete inference runs and missing paired predictions on reviewed frames. Geometry is checked. Report rendering verifies image checksums, escapes embedded JSON and keeps arbitrary comments as text. Partial/unreviewed labels never become empty-scene ground truth.

## Remaining acceptance for stage 2

1. Independently correct/review the boxes, especially far/occluded people. Include complete nonempty and empty scenes, crossings, lighting variation and representative workstation views.
2. Add another recording group/day/site for held-out acceptance. Keep source hashes and groups separate across train/validation/test. Nearby timestamps from this one camera do not provide that separation.
3. Use the validation split to compare thresholds and model candidates. A candidate proposal needs complete human validation, support from people and empty frames, and a distinct nonempty test group. It remains unapplied until held-out acceptance. A multi-threshold sweep is explicitly blocked on the test split.
4. If existing weights still miss the domain, fine-tune in a separate training environment on the corrected training split and re-evaluate on frozen data. **No training was performed here.** Fifteen assistant-labelled images are insufficient evidence for a production fine-tune or accuracy claim. The installed loader also verifies a pinned model hash and 80-class output contract; a custom fine-tuned artifact needs a versioned manifest, output/parser compatibility tests and held-out acceptance before deployment, not replacement of the ONNX file in place.

The current proposal state is `NOT_ELIGIBLE`: pilot split, no complete human review, insufficient support including empty scenes, and no distinct held-out group. `production_qualified=false` and `live_configuration_changed=false` are explicit. The stage's implementation and pilot experiments are complete; independent model qualification remains open.

## Verification

29 short Python tests passed for dataset validation, paired metrics, missing/filtered predictions, threshold guards, report escaping/checksums, preview isolation, coordinate mapping, crop-edge rejection, duplicate suppression and zone replay parity. Two synthetic browser scenarios passed: the new detector report controls and the existing annotation editor. All four real-model profile runs completed on the same 15 selected images. The generated real-data report preview returned HTTP 200. No long-duration test or training job was started.
