# Proposal Visual Review

Tanggal: 11 Oktober 2026. Status: proposal desain siap untuk review arah visual.

## 1. Artefak yang benar-benar diinspeksi

PNG dirender dari tokens dan vector drawing, lalu dibuka dengan image viewer untuk inspeksi. Ini bukan capture aplikasi Qt/CCTV yang berjalan.

| View | Ukuran logical | Output raster | Pemeriksaan visual |
|---|---|---|---|
| [Pemantauan Live](previews/live-monitoring-1600.png) | 1600×1000 | 3200×2000 | Video area dominan, list dan inspector rapat, status/time dipisah, N/A terlihat |
| [Pemantauan Live minimum](previews/live-monitoring-1100.png) | 1100×720 | 2200×1440 | Inspector menjadi akses drawer, camera list/grid tetap terbaca, footer/aksi tidak bertumpuk |
| [Editor workstation](previews/workspace-editor-1600.png) | 1600×1000 | 3200×2000 | Polygon/vertex, property alignment, tabel koordinat, disabled save + alasan |
| [Editor minimum](previews/workspace-editor-1100.png) | 1100×720 | 2200×1440 | List sekunder dilepas, frame menjaga 16:9 dengan letterbox, property/table tetap muat |

Default Live diperiksa sebelum dan setelah perubahan copy kredensial; final versi minimum mengonfirmasi panjang label baru. Editor diperiksa ulang setelah revisi geometri. SVG pasangan tersedia sebagai editable vector source, bukan screenshot runtime.

## 2. Hasil review dan perbaikan

- Surface solid charcoal/graphite, satu accent teal; semantic error/warning terpisah. Tidak ada gradient/glow/blur/shadow/animation atau kartu KPI besar.
- Typographic hierarchy ringkas; metadata menggunakan font caption, numerals/vertex memakai monospace. Essential copy tidak menggunakan font di bawah 12 logical px pada proposal.
- Video tile memberi prioritas pada frame dan status, tanpa frame footage palsu. Semua timestamps/durations/coverage tanpa evidence tampil N/A atau belum tersedia.
- Camera transport, tracking, state zona dan persistence disajikan terpisah. Tidak ada badge LIVE/ONLINE palsu atau productivity score.
- Tidak ada clipping/overlap yang terlihat pada dua ukuran proposal. Branding sidebar pada minimum disesuaikan memakai body font agar tetap muat.
- Geometri draft diperbaiki agar mencakup satu area tempat duduk, bukan dua meja. Label tidak menjadi employee identity; kapasitas dan coordinates adalah proposed configuration, bukan analytics.
- Aspect ratio ilustrasi frame diperbaiki pada minimum; letterbox tidak ikut dalam normalized polygon coordinates.
- Contrast muted text pada selected surface ditingkatkan setelah perhitungan awal 4.49:1; token diperbaiki dan proposal dirender ulang sebelum review akhir.
- Property form menyisakan ruang untuk helper/error, dan save tetap disabled karena frame/rule belum tersedia. Minimum vertex preview menunjukkan sebagian baris + jumlah total; runtime tabel harus menyediakan scroll untuk semua titik.

## 3. Static verification

[VALIDATION_RESULTS.md](VALIDATION_RESULTS.md) memuat hasil otomatis setelah rendering: token contrast, SVG/XML/dimensions, preview disclosure, no numeric analytics, handoff links dan navigation scope. Renderer memakai pengukuran font untuk menolak text yang lebih lebar dari allotted area.

Regenerate:

```text
python docs/ui/render_design_preview.py
python docs/ui/validate_ui_design.py
```

Renderer menggunakan Pillow dan font Segoe UI/Consolas Windows pada environment ini. Asset PNG dibundel agar dapat ditinjau tanpa dependency renderer. Konversi SVG dan PNG berbagi tokens/geometry; text baseline SVG dapat berbeda antar font/browser sehingga PNG menjadi visual acuan review ini.

## 4. Yang belum diverifikasi

Native Qt implementation, actual camera pixels, overlay on moving footage, drag/undo, keyboard/focus, NVDA/Orca, API/WebSocket lifecycle, high-DPI/multi-monitor, throughput dan long-session responsiveness belum dijalankan. Tidak mengklaim production-grade readiness dari preview statis. Implementasi bertahap dan actual screenshot review mengikuti [Screen Implementation Plan](../../SCREEN_IMPLEMENTATION_PLAN.md).
