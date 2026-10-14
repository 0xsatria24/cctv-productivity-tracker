# Webcam with local person detection

CPU optimization: NanoDet is now the default detector; see [LATENCY.md](LATENCY.md) for measured performance and the YOLOX comparison option.

Update 14 October 2026: webcam tracking, polygon calibration and live duration reports are now implemented. Follow [LIVE-ENGINE.md](LIVE-ENGINE.md) for the current workflow. The notes below describe detection preview mode; starting live accounting stores metadata/intervals in the separate live database, while raw images remain unrecorded.

## Run and try

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts/setup_webcam_model.py
.\run-app.ps1 -DatabasePath runtime/integrated-pilot.sqlite3
```

Open http://127.0.0.1:8765/#/cameras in Chrome or Edge, refresh after updating, select the camera and click **Mulai webcam**. Allow camera permission. The installed model works offline after the initial download. Vite port 5173 remains the standalone mock prototype; use the Python dashboard for this feature.

Camera selection and target resolution share an aligned two-column grid; the three actions occupy a centered separate row. One MediaStream and video/inference component remain mounted across every route. Other pages, including Ringkasan, show a compact live panel. **Hentikan** releases all tracks and aborts the browser request. Closing/reloading the document also releases capture. Nothing starts automatically.

## Real detection and data boundaries

Browser capture requests video only, never audio. At most one JPEG request is in flight per dashboard. Frames are downscaled to a maximum 640-pixel long edge and the next frame is sampled 500 ms after completion; this is intentionally slower than preview FPS. Sampled images go only to the authenticated same-origin local Python API, not a cloud service. Images and detection results stay in memory and are not recorded or inserted into SQLite.

The Python engine runs the actual YOLOX ONNX model on CPU using ONNX Runtime, two intra-op threads, RGB 640x640 top-left letterboxing with padding 114, unnormalized float input, strides 8/16/32, COCO person class, confidence 0.45 and NMS 0.5. Model SHA-256 is verified before loading. CPU processing is serialized with a nonblocking lock; concurrent requests get 429 rather than building an inference queue. The endpoint validates authentication, origin, JPEG content type, 1 MB encoded limit and bounded JPEG header dimensions before decoding.

A successful recent frame displays **Engine deteksi aktif**, person count, confidence boxes, model/provider and inference latency. Preview status is separate from detector status. Zero people means a successful inference with zero accepted detections; a failed/stale request shows no count or boxes. Results older than 2.5 seconds are hidden. Mirror and contain/cover/fullscreen use the same coordinates as video. Boxes are sampled results and may lag moving subjects. No identity or face registration is performed.

Detection preview does not write durations. After calibration and explicit live start, ByteTrack and the zone state machine write live duration reports to a separate database. Camera-specific accuracy evaluation remains required for production. Occlusion, small subjects and camera angle can cause missed detections; confidence is not a validated accuracy percentage.

## Model provenance

Official source: https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/object_detection_yolox

Weights: `object_detection_yolox_2022nov.onnx`, 35,858,002 bytes, SHA-256 `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`. License: Apache-2.0, copy in [YOLOX-LICENSE.txt](YOLOX-LICENSE.txt). Local weights are ignored by Git; the pinned setup script reproduces the download. Pre/postprocessing is adapted from the official OpenCV Zoo YOLOX demo and decoder. No downloaded Python code is executed.

## Failure handling

- Permission denied: allow camera access for the dashboard origin and Windows privacy settings, then retry. Open the same URL in Chrome/Edge if embedded browser permissions block access.
- Missing/busy device: connect/enable the webcam or close the application using it, refresh devices and retry.
- Model missing/checksum failure: run the model setup command above. There is no fake detection fallback.
- Python unavailable/timeout: preview can continue; the detector reports its failure and retries subsequent frames. Stop/restart is always available.
- Interrupted frames: preview reports stalled/muted state and suppresses boxes. Stop and reconnect if it does not recover.

## Verification on 13 October 2026

34 Python tests passed, including real-model blank-frame inference, request validation, authentication and backpressure. A separately downloaded official OpenCV `samples/data/basketball1.png` image produced two person detections at confidence 0.926 and 0.846. This is a smoke test, not an accuracy benchmark.

10 webcam browser tests and 3 existing engine integration browser tests passed; production build passed. Browser tests use an explicitly synthetic moving YUV source and do not activate the physical webcam. They exercise camera lifetime across routes, stop/cancel/denial/device-ended recovery, real frame ingestion, separation from replay data, mirror/fit/fullscreen and detection error recovery. The overlay geometry test uses an explicitly injected response fixture; it does not claim detector accuracy. Hardware behavior still requires trying the user's camera.

```powershell
.\.venv\Scripts\python.exe -m pytest
cd prototype
npm.cmd run build
npm.cmd run test:webcam
npm.cmd run test:engine
```
