# YOLOX-S with OpenVINO

Implemented on 14 October 2026 for the integrated single-camera pilot. The default launcher now uses the original YOLOX-S model through OpenVINO on Intel GPU. NanoDet and the original ONNX Runtime implementation remain explicit comparison options.

## Install and launch

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[vision,api,openvino]"
.\.venv\Scripts\python.exe scripts/setup_webcam_model.py --model yolox
.\run-app.ps1 -Detector yolox-openvino -OpenVinoDevice GPU
```

The tested machine has an Intel Core i7-1185G7 and Iris Xe integrated GPU. OpenVINO 2026.4.1 detects both CPU and GPU. GPU support requires a compatible Intel graphics driver. When GPU is unavailable, the app reports it and does not silently change device or model. Choose CPU explicitly:

```powershell
.\run-app.ps1 -Detector yolox-openvino -OpenVinoDevice CPU
```

The default CLI is equivalent to `dashboard --detector yolox-openvino --openvino-device GPU`. The existing user development database can be retained with `-DatabasePath runtime/integrated-pilot.sqlite3`. Open http://127.0.0.1:8765/#/cameras and refresh after changing the runtime. The preview label displays `YOLOX-S · OpenVINO GPU`. Settings and the status API show the actual execution device, readiness and requested precision.

## What is optimized

- The exact existing `webcam-yolox.onnx` artifact is verified against SHA-256 `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` before loading. Input remains float32 NCHW `[1,3,640,640]`; output remains `[1,8400,85]`.
- ONNX Runtime and OpenVINO use the same preprocessing and postprocessing code. RGB/top-left letterboxing with padding 114, unnormalized input, person class 0, confidence 0.45, NMS 0.5 and normalized coordinate conversion are preserved.
- OpenVINO compiles the graph with `LATENCY`, FP32 inference hint and one typed inference stream. CPU mode uses four threads by default. GPU mode executes on the explicitly requested Intel GPU. No resizing to a smaller model input, weight compression, INT8 quantization or precision reduction is introduced.
- Compilation cache is held in the ignored `models/openvino-cache/` directory. GPU kernel compilation took about 34 seconds on the first cold run; a subsequent cached benchmark still spent about 11 seconds loading the runtime/model. Startup warms the detector before accepting requests, so compilation time is not displayed as a processed live frame.
- One locked infer request is reused; mutable output buffers are decoded while the lock is held. Preview and live accounting share the same model instance. Existing session/sequence checks, latest-frame RTSP capture, ByteTrack, UNKNOWN gaps and durable SQLite checkpoints remain in use.
- Per-run runtime metadata records the actual provider, execution devices, precision and runtime version. The model artifact retains its weight identity; switching execution runtime does not overwrite historical run provenance.

## Measured results

Measurements on this machine, using the same public OpenCV person sample:

| Runtime | Warm median | p95 |
|---|---:|---:|
| ONNX CPU, two threads, initial benchmark under varying load | 608.5 ms | 640.2 ms |
| OpenVINO CPU, two threads | 524.0 ms | 529.1 ms |
| OpenVINO CPU, four threads | 269.5 ms | 283.7 ms |
| OpenVINO Iris Xe GPU, FP32, 20 warmed samples | 80.5 ms | 85.9 ms |

Earlier lightly loaded ONNX CPU measurements were 272-304 ms. The initial sequential benchmark changed with CPU load/thermal state, so these figures are measured examples rather than a guaranteed speedup. GPU warmed samples ranged 73-102 ms in the 20-frame run. Full HTTP/live-accounting latency additionally includes frame encoding, tracking and SQLite persistence.

After restarting the user dashboard on port 8765 with the existing database, ten actual HTTP preview requests with the public test image returned two detections each. Reported processing time ranged 114-247 ms, median 193.5 ms; HTTP round trip median was 199.7 ms. This separate run demonstrates the variability of application latency and must not be presented as the isolated 80.5 ms benchmark. Browser capture/encoding and live SQLite accounting were not part of those ten preview requests. The authenticated status endpoint confirmed a warmed detector, actual execution device `GPU.0`, Iris Xe and FP32.

Runtime equivalence was checked on the original sample, blank frame, portrait-padded sample, dimmed sample, blurred sample and downsampled sample. Detection counts matched ONNX in all six cases. Minimum matched-box IoU exceeded 0.999999; displayed confidence values matched after rounding to three decimals. This is a numerical/runtime smoke test, not a CCTV accuracy or commercial acceptance benchmark.

Repeat the comparison without activating a camera:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_openvino_yolox.py --image models/person-test.png --samples 20
```

`--backend cpu` or `--backend gpu` evaluates a specific backend against the ONNX reference. The optional sample image is not distributed with the app; provide an authorized image path. Reports are written under ignored `runtime/` unless `--output` is specified.

## Verification

Tests cover unchanged YOLOX checksum/input/output contract, FP32 CPU detections, normalized coordinates, infer-request backpressure, explicit rejection of unavailable devices, per-run execution provenance, webcam lifecycle and live calibration/report integration. GPU verification runs against the actual Iris Xe rather than a mocked provider. The optional localhost RTSP test can use this runtime:

Verification completed: 56 Python tests passed; all 11 webcam/live browser tests and all three dashboard integration tests passed against the actual OpenVINO GPU server. The production frontend build, dependency compatibility check and whitespace check passed. The synthetic localhost RTSP test verified EMPTY accounting, UNKNOWN during interruption, reconnection with a new camera generation, and clean SQLite integrity/foreign-key checks. No physical webcam was activated by these automated tests.

```powershell
.\.venv\Scripts\python.exe scripts/verify_rtsp_engine.py --detector yolox-openvino --openvino-device GPU
```

It requires the separately launched synthetic MediaMTX test server described in [LIVE-ENGINE.md](LIVE-ENGINE.md); MediaMTX is not an application dependency.

## References

- [OpenVINO latency optimization](https://docs.openvino.ai/2025/openvino-workflow/running-inference/optimize-inference/optimizing-latency.html)
- [OpenVINO precision control](https://docs.openvino.ai/2025/openvino-workflow/running-inference/optimize-inference/precision-control.html)
- [OpenVINO model caching](https://docs.openvino.ai/2025/openvino-workflow/running-inference/optimize-inference/optimizing-latency/model-caching-overview.html)
- [OpenCV YOLOX model and Apache-2.0 license](https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/object_detection_yolox)

The camera-scene evaluation and production acceptance gates in [LIVE-ENGINE.md](LIVE-ENGINE.md) still apply. The optimization preserves the detector choice and compares numerical outputs; it does not establish an accuracy guarantee for customer scenes.
