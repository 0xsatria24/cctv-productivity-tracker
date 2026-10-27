# CCTV Productivity Tracker — Design Workspace

Update UI/UX 15 Oktober: halaman Kamera memakai grid CCTV dan setup empat langkah; Ringkasan menampilkan kondisi kamera saat ini; Laporan menyediakan filter tanggal/jam shift, penjelasan kelengkapan, ekspor dan timeline. Sumber laporan awal adalah Kamera live. Rincian teknis berada di Pengaturan. Lihat [perbaikan UI operasional](docs/ui/OPERATIONS-IMPROVEMENTS.md).

Auto-save laporan JSON/CSV dan rekaman preview MP4 sekarang tersedia di **Pengaturan**, dengan on/off dan interval terpisah 5 detik sampai 60 menit. Tujuan tambahan dapat berupa folder server/NAS, cloud via rclone, atau S3 compatible; upload berjalan melalui antrean yang tersimpan. Panduan, lokasi file, serta batas kualitas: [Auto-save data dan video](docs/runtime/AUTO-SAVE.md).

Durasi di box memakai usia track anonim agar tidak hilang saat confidence zona turun. Label **Working / Idle** adalah indikator gerak visual, bukan bukti hasil kerja atau istirahat. Audit, konfigurasi, benchmark sebelum/sesudah dan keterbatasan: [Engine performance](docs/runtime/ENGINE-PERFORMANCE.md).

Edisi tambahan **CCTV Headless Engine** tersedia tanpa frontend, dengan API multi-kamera, WebSocket, webhook, dan lisensi offline bertanda tangan. Panduan instalasi, konfigurasi, kontrak API, serta batas validasi: [Headless Engine](docs/runtime/HEADLESS.md). Jalankan `python -m editions.headless --help`; paket Enterprise dan Headless dibuat terpisah dengan `python scripts/build_editions.py`. Kedua edisi menggunakan engine yang sama.

Status: dashboard React sudah terhubung ke engine Python melalui API lokal dan SQLite. Satu server menyajikan UI dan API; replay dapat dimulai/dihentikan dari dashboard. Preview beberapa kamera tersedia dalam grid 1/4/9/16. Kamera RTSP terkelola mendukung analisis bersamaan dengan kalibrasi, histori dan laporan terpisah per kamera. Konfigurasi terenkripsi, pemulihan otomatis, serta backup/restore tersedia. Validasi produksi, uji 24 jam dan instalasi Windows Service pada mesin target belum selesai. Lihat [pilot hardening](docs/runtime/PILOT-HARDENING.md).

Jalankan aplikasi terintegrasi di PowerShell dari folder proyek:

```powershell
& .\run-app.ps1
```

Buka `http://127.0.0.1:8765/` di Chrome/Edge. Script membangun frontend, lalu menjalankan engine/API pada loopback. Database pilot default berada di local app data di luar OneDrive. Panduan dan batasannya: [Dashboard integration](docs/runtime/DASHBOARD-INTEGRATION.md).

Untuk uji webcam, buka halaman **Pemantauan Live**, pilih perangkat, klik **Mulai webcam**, dan izinkan akses kamera di browser. Webcam memakai deteksi orang YOLOX-S melalui OpenVINO lokal dengan bounding box dan jumlah orang; kalibrasi zona dan Mulai pencatatan live mengaktifkan laporan durasi dari kamera asli. Pilih Kamera live sebagai sumber laporan. Jalankan `.\.venv\Scripts\python.exe scripts/setup_webcam_model.py` sekali untuk memasang model. Lihat [setup OpenVINO](docs/runtime/OPENVINO-YOLOX.md) dan [panduan engine live](docs/runtime/LIVE-ENGINE.md).

Stack V1: Python, PySide6/PyQtGraph, PyAV/FFmpeg, OpenCV/NumPy, ONNX Runtime, SQLite, FastAPI/Uvicorn lokal.

Halaman **Pemantauan Live** menyediakan mode **Grid**, **Fokus** (satu kamera utama + lima pendamping), dan **Video wall** dalam satu workspace. Pemilihan kamera, kepadatan grid dan overlay dipakai bersama saat berpindah mode; fullscreen tersedia di ketiganya. Daftar/pencarian kamera dan preview RTSP tetap tersedia. Pengaturan webcam dibuka dari ikon pengaturan pada tile. Aktifkan **Deteksi** untuk menampilkan bounding box. Kamera RTSP baru berlabel **Preview saja** sampai zona disimpan dan analisis dimulai. Konfigurasi kamera tersimpan setelah restart; analisis berjalan di backend saat berpindah halaman. Lihat [panduan camera wall](docs/runtime/CAMERA-WALL.md).

Panduan runtime Python dan demo yang sudah diuji: [Runtime pilot](docs/runtime/README.md). Demo memakai input sintetis berlabel jelas; setiap invocation menghasilkan database baru. Mode Vite menyediakan prototipe mock terpisah; mode dashboard Python memakai data engine dan mendukung preview webcam lokal.

```powershell
Set-Location -LiteralPath 'C:\Users\muham\OneDrive\Documents\ChatGPT\cctv 2'
& .\.venv\Scripts\python.exe -m cctv_tracker --log-dir runtime\logs demo --output-dir runtime\demos
```

| Dokumen | Isi |
|---|---|
| [PRD](PRD-CCTV-Productivity-Tracker.md) | Scope produk, metrik, rilis dan acceptance criteria |
| [Architecture](docs/ARCHITECTURE.md) | Topologi proses, boundary modul, resource ownership |
| [Technical Design](docs/TECHNICAL-DESIGN.md) | Frame pipeline, temporal rules, events, recovery dan runtime |
| [Database Design](docs/DATABASE-DESIGN.md) | ERD, source/projection/cache, transaksi dan retention |
| [API Design](docs/API-DESIGN.md) | Local HTTP/WebSocket contract dan concurrency |
| [OpenAPI 3.1](docs/api/openapi.json) | Endpoint/schema machine-readable |
| [SQL reference](docs/database/001_initial.sql) | Skema executable dengan constraints/indexes/views |
| [Observation contract](docs/contracts/zone-observation.schema.json) | Input typed domain tanpa frame/secret |
| [Implementation Plan](docs/IMPLEMENTATION-PLAN.md) | Milestones, traceability dan validation gates |
| [Production readiness](docs/runtime/PRODUCTION-READINESS.md) | Dataset review, evaluasi akurasi dan program uji 24/72 jam manual |
| [Detector evaluation](docs/runtime/DETECTOR-EVALUATION.md) | Hasil perbandingan model, confidence sweep dan review miss/false positive |
| [Validation results](docs/validation/RESULTS.md) | Hasil pengujian skema referensi dan static contract checks |
| [UI/UX Specification](UI_UX_SPEC.md) | Scope V1, workflow tujuh halaman, state semantics dan interaction |
| [Design System](DESIGN_SYSTEM.md) | Tokens, typography, contrast, component states dan keyboard |
| [Component Inventory](COMPONENT_INVENTORY.md) | Komponen native Qt dan boundary presentation/services |
| [Screen Implementation Plan](SCREEN_IMPLEMENTATION_PLAN.md) | Urutan layar, review gate dan API contract gaps |
| [UI visual review](docs/ui/VISUAL_REVIEW.md) | Preview desain Live/editor pada 1600×1000 dan 1100×720 |
| [UI tokens](docs/ui/design-tokens.json) | Sumber visual machine-readable |
| [Interactive prototype](prototype/README.md) | Prototipe desain React/Vite lokal dengan data mock, interaksi, dan instruksi launch |

Jalankan reference validation dengan Python yang menyediakan sqlite3:

```text
python docs/validation/validate_design.py
```

Validator tidak memerlukan CCTV, GPU, atau network; menghasilkan database sementara, memverifikasi schema/constraints/backup, serta static API contract references. Hasil ini tidak membuktikan inference performance atau kapasitas produksi.

Preview UI adalah proposal statis tanpa stream/angka analytics nyata. Implementasi native PySide6 berjalan satu workflow per increment setelah approval arah desain sesuai prompt pengguna. Preview dapat diregenerasi dengan `python docs/ui/render_design_preview.py` dan diperiksa memakai `python docs/ui/validate_ui_design.py`; renderer menggunakan Pillow/font Windows dan bukan aplikasi runtime.

Pada 12 Oktober 2026 pengguna meminta prototipe interaktif React/Vite khusus desain dengan data simulasi yang jelas. Prototipe berada di `prototype/`, memakai design tokens yang sama, dan tidak mengubah arsitektur produksi. Jalankan dari folder tersebut dengan `npm ci` lalu `npm run dev`; buka `http://127.0.0.1:5173/`. Panduan PowerShell, build/preview dan pengujian ada di [README prototipe](prototype/README.md).
