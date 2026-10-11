# CCTV Productivity Tracker — Design Workspace

Status: PRD, rancangan teknis, dan desain UI/UX tahap 3; aplikasi runtime belum diimplementasikan.

Stack V1: Python, PySide6/PyQtGraph, PyAV/FFmpeg, OpenCV/NumPy, ONNX Runtime, SQLite, FastAPI/Uvicorn lokal.

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
| [Validation results](docs/validation/RESULTS.md) | Hasil pengujian skema referensi dan static contract checks |
| [UI/UX Specification](UI_UX_SPEC.md) | Scope V1, workflow tujuh halaman, state semantics dan interaction |
| [Design System](DESIGN_SYSTEM.md) | Tokens, typography, contrast, component states dan keyboard |
| [Component Inventory](COMPONENT_INVENTORY.md) | Komponen native Qt dan boundary presentation/services |
| [Screen Implementation Plan](SCREEN_IMPLEMENTATION_PLAN.md) | Urutan layar, review gate dan API contract gaps |
| [UI visual review](docs/ui/VISUAL_REVIEW.md) | Preview desain Live/editor pada 1600×1000 dan 1100×720 |
| [UI tokens](docs/ui/design-tokens.json) | Sumber visual machine-readable |

Jalankan reference validation dengan Python yang menyediakan sqlite3:

```text
python docs/validation/validate_design.py
```

Validator tidak memerlukan CCTV, GPU, atau network; menghasilkan database sementara, memverifikasi schema/constraints/backup, serta static API contract references. Hasil ini tidak membuktikan inference performance atau kapasitas produksi.

Preview UI adalah proposal statis tanpa stream/angka analytics nyata. Implementasi native PySide6 berjalan satu workflow per increment setelah approval arah desain sesuai prompt pengguna. Preview dapat diregenerasi dengan `python docs/ui/render_design_preview.py` dan diperiksa memakai `python docs/ui/validate_ui_design.py`; renderer menggunakan Pillow/font Windows dan bukan aplikasi runtime.
