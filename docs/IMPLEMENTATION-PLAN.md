# Implementation Plan — Python V1

Versi: 1.0 · 11 Oktober 2026. Ini urutan implementasi dan gate, bukan estimasi tanggal rilis.

## Runtime progress, 14 October 2026

The single-camera pilot now connects webcam/RTSP capture, actual YOLOX inference, ByteTrack, calibrated polygons, confirmed intervals/events, SQLite and React live reports. This implements a testable slice of M5-M8 and the web dashboard path. It does not close the full milestones: target-scene accuracy, supervisor recovery, multi-camera benchmarks, production API/GUI, schedules, backup/restore and packaging still require their acceptance gates. Details and evidence: [LIVE-ENGINE.md](runtime/LIVE-ENGINE.md).

## 1. Milestones

| ID | Output | Gate sebelum lanjut |
|---|---|---|
| M0 | Spike Python/PySide6/PyAV/ONNX/FastAPI, CPU/GPU build matrix | Decode timeout, frozen spawn, shared memory cleanup, credential backend, model parser/license manifest terbukti pada OS target |
| M1 | Package skeleton, immutable config, clocks, logging, migrations | SQL constraints, secret redaction, unknown keys, unsupported schema gate |
| M2 | Domain interval/schedule/metrics tanpa kamera | Golden fixtures P+A+U=T, pending unknown, count/session grouping, clipping, DST, clock discontinuity |
| M3 | Single writer, event ledger/checkpoint/replay | Rollback/retry equivalence, duplicate mismatch rejection, crash checkpoint gap, source sequence |
| M4 | Local supervisor dan headless engine | Satu instance, GUI close tetap running, restart backoff, child ownership/cleanup |
| M5 | Capture satu kamera dan shared buffer | Timeout/hang, stale generation, no torn frames, bounded memory, camera URI redaction |
| M6 | Detector adapter dan ByteTrack | Manifest/parser/coordinate transforms benar; CPU replay fixture; predicted tracks tidak memperpanjang bukti palsu |
| M7 | Zone association dan state machine terhubung | Seated/back-facing, adjacent desks, ambiguity, offline, quality, confirmation dan count-unavailable |
| M8 | FastAPI HTTP contract dan jobs | Auth/schema, idempotency/If-Match, query timeout, job interrupted, no SQL/path execution |
| M9 | Aggregate/report service | Cache publication atomic, exact/custom vs retained caches, peak/count coverage, stable pagination |
| M10 | PySide6 dashboard/editor/live view | Main thread responsive, close/reconnect, overlay frame match, pending/unknown terlihat |
| M11 | WebSocket status/preview + CSV | Slow client tidak memblokir accounting, resync, coherent snapshot, safe CSV text |
| M12 | Backup/retention/restore | Verified backup round trip, FK anchors/history horizon, pre-restore backup, restore completion receipt bertahan |
| M13 | Multi-camera/performance benchmark | 1→4→target kamera, FPS/latency/CPU/RAM/VRAM/queue/coverage tercatat per hardware/model |
| M14 | Packaging/pilot/soak | Fresh machine install, Windows/Linux target matrix, 24 jam termasuk fault injection |

M2–M3 harus matang sebelum menilai keberhasilan berdasarkan bounding box di live view. M8 bisa memakai fake domain adapter setelah interface M2 stabil; implementasi tidak harus menunggu seluruh CV pipeline selesai.

## 2. Traceability ke PRD

| PRD requirement | Modul/desain | Milestone |
|---|---|---|
| FR-01 Cameras | API camera/config/credential + capture adapter | M5/M8/M10 |
| FR-02 Ingestion | Worker generation, bounded shared buffer, watchdog | M4/M5 |
| FR-03 Detection | ONNX manifest/provider/parser | M0/M6 |
| FR-04 Tracking | Per-generation tracker dan time-aware aging | M6 |
| FR-05 Workspaces | Versioned polygons, scene review, exclusive group | M7/M10 |
| FR-06 Presence | Zone intervals dan conservative unknown | M2/M3/M7 |
| FR-07 History | Event ledger, intervals, period_statistics | M3/M9 |
| FR-08 Dashboard | API snapshot + durability/coverage | M8/M10 |
| FR-09 Live view | Preview subscription dan frame-matched overlay | M10/M11 |
| FR-10 Analytics | Query snapshot, clipping, graphs | M9/M10 |
| FR-11 Reports | CSV job, managed artifact, metadata | M9/M11 |
| FR-12 Reliability | Supervisor, checkpoint, recovery, backup/restore | M3/M4/M12/M14 |

## 3. Data fixtures yang diperlukan

- Satu workspace dengan perubahan count 1→2 tanpa perubahan presence.
- ENTER/EXIT dengan confirmation delay dan satu frame false negative.
- Kamera offline sepuluh menit serta engine restart dengan sesi terbuka.
- Worker mati sambil memegang frame lock; inference response dari generation lama.
- Dua meja adjacent dan room yang overlap dengan desk.
- Shift overnight, holiday, overlapping schedule, DST fold/nonexistent time.
- Config/model/camera scene berubah dalam hari yang sama.
- Disk full, writer queue saturation, long reader/export dan restore saat job aktif.
- Dataset retained vs expired detail dengan exact custom query.

Gunakan annotated replay untuk domain/CV correctness dan live RTSP untuk transport/reliability. Rekaman pilot hanya dipakai sesuai penyimpanan yang disetujui lokasi; default production tetap tanpa raw recording.

## 4. Benchmark dan definition of done

Benchmark mencatat hardware/OS/driver/runtime/model hash, input/inference size, codec, decode FPS, effective inference FPS/kamera, result age p95, CPU/RAM/VRAM, writer lag, frame drops, reconnect, occupancy precision/recall, serta coverage. Test 20 kamera bukan gate yang diasumsikan lolos oleh desain; hasil menentukan supported capacity.

V1 selesai ketika semua AC PRD lulus pada pilot scope, backup sudah diuji restore, resource bounds terbukti 24 jam, laporan cocok dengan golden interval fixture, dan install/uninstall/update procedure terdokumentasi pada OS target. Full OpenAPI schema validation, FastAPI generated-contract diff, HTTP/WebSocket integration, dan platform lifecycle tests merupakan gate implementasi, bukan hasil dari review dokumen.

## 5. Scope berikutnya

V1.5: employee assignment dengan effective-time, correction overlay + audit log, local RBAC, alert, Excel/PDF. V2: site-server/PostgreSQL/public API dengan auth/TLS/scope, serta web dashboard. Model TensorRT, hardware decode, batching atau C++ dipilih melalui profiling dan benchmark; tidak menjadi migration wajib.
