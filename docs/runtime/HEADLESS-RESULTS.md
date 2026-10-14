# Headless validation — 14 October 2026

- Full regression suite: **64 passed** before adding the SDK HTTP test (one Starlette deprecation warning).
- Follow-up headless, webcam, NanoDet and OpenVINO suite: **18 passed**, including the new SDK HTTP test. Total distinct tests covered: **65**. Uvicorn/WebSocket dependency deprecation warnings remain.
- Headless tests cover signed-license tampering, expiry, wrong edition, camera limits, auth, isolated camera databases, OpenAPI, authenticated WebSocket, synthetic concurrent capture with shared real tracking/accounting, webhook signature/retry/cursor persistence, UI-free imports and the stdlib SDK against a real loopback HTTP server.
- Built `dist/editions/cctv-enterprise-0.1.0.zip` and `dist/editions/cctv-headless-0.1.0.zip` successfully.
- Inspected both wheels: shared engine, pipeline, live controller, vision, detector and RTSP modules are byte-identical. Headless has no frontend assets or dashboard/API UI module; its runtime lock selects `opencv-python-headless`.
- Extracted the headless wheel into a temporary directory and launched its actual CLI with a temporary signed test license, while a Python import hook rejected Qt, Tkinter and dashboard modules. Authenticated HTTP status succeeded. Test keys and runtime data were temporary and are not shipped.

Limits: packaged startup reused the development interpreter's installed runtime dependencies; a fresh-machine installation of every dependency was not performed. Concurrent-camera testing used synthetic transport and injected detections, not physical CCTV. Existing detector tests ran against the locally available models/runtime. No 16-camera throughput claim, production service-supervisor acceptance, ONVIF discovery or processed RTSP output validation is made. Enterprise commercial license enforcement remains unchanged.
