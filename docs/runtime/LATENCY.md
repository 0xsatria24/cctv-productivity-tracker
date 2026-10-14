# CPU inference latency improvement, 14 October 2026

Subsequent quality optimization: YOLOX-S through OpenVINO is now the default runtime. This document records the earlier NanoDet optimization. Current setup/results: [OPENVINO-YOLOX.md](OPENVINO-YOLOX.md).

The screenshot showed YOLOX CPU inference at 730 ms per frame. Hardware inspection found an Intel Core i7-1185G7 (4 cores / 8 threads) and Iris Xe integrated graphics. The existing detector ran ONNX Runtime's CPU provider with a fixed 640x640 input. Reducing webcam preview resolution alone therefore did not reduce the neural network input size.

The integrated dashboard now defaults to NanoDet-m-plus-1.5x_416 on CPU, with two inference threads. The official 3.8 MB OpenCV Zoo ONNX artifact uses 416x416 RGB centered letterboxing and its own normalization/distribution decoder. It is SHA-256 verified: `4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186`. License: [NANODET-LICENSE.txt](NANODET-LICENSE.txt). Source and decoder: https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/object_detection_nanodet . No additional inference dependencies were required.

Measured warmed blank-JPEG processing on this machine:

| Detector | Input | Measured inference |
|---|---|---|
| YOLOX baseline | 640x640 | 272-304 ms |
| NanoDet CPU | 416x416 | 32-45 ms |

The actual running API, measured after other test workloads stopped, returned 30-56 ms inference and 35-63 ms HTTP round trip on warmed blank frames. Under concurrent test load these times rose; performance depends on scene and machine load.

These are local smoke-test measurements, not guaranteed webcam FPS or camera-scene accuracy. Both models detected two people in the same official OpenCV basketball sample. Blank landscape, portrait and square frames produced zero detections. The smaller detector may have different recall on small, occluded or seated subjects; validate against the actual camera scene before relying on duration reports.

Webcam sampling is now capped at 5 requests per second with one in-flight request. The old unconditional 500 ms delay after each response was removed; the next request is scheduled from the start of the previous request. The UI separately displays inference time and complete request/response time. Live response time includes tracking and the durable SQLite checkpoint; disk load can therefore keep response latency above inference latency. The latest-frame RTSP mailbox and conservative UNKNOWN accounting remain in place.

```powershell
# Fast CPU model, default mode
.\.venv\Scripts\python.exe scripts/setup_webcam_model.py --model nanodet
.\run-app.ps1 -Detector nanodet

# Compare the original model
.\.venv\Scripts\python.exe scripts/setup_webcam_model.py --model yolox
.\run-app.ps1 -Detector yolox

# Repeat the detector-only local benchmark without opening a webcam
.\.venv\Scripts\python.exe scripts/benchmark_detectors.py
```

Windows timing also uses the high-resolution monotonic QueryPerformanceCounter clock. Python 3.12 GetTickCount64 had 15.625 ms resolution on this host, which could make two rapidly delivered frames share a timestamp; the ingestion/reconnect tests passed after the clock fix.

Changing detector requires restarting the server and refreshing the dashboard. Start a new live session afterward. The actual selected model checksum/provider are recorded in the run's model artifact, so historical runs retain their provenance. YOLOX remains an explicit option; there is no silent fallback when the selected model is absent.
