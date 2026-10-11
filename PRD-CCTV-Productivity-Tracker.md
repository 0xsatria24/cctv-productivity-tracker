# PRD — CCTV Productivity & Working-Hours Tracker

Versi: 1.3 — Python V1 dengan technical design  
Tanggal: 11 Oktober 2026  
Status: Draf untuk acuan implementasi  
Target: aplikasi desktop/on-premise, Windows dan Linux  
Pasar awal: B2B, SMB dan mid-market dengan CCTV yang sudah tersedia

Sumber konteks: chat [Perbandingan C++ Python](https://chatgpt.com/g/g-p-6aac1cb3a7c48191a3b13d444c03bfb4-productivity-worker-v-1/c/6aac148d-9834-83ec-807f-c99d03471849) di project **Productivity worker v.1**. PRD lama meminta database SQLite atau alternatif, GUI, record harian/mingguan/bulanan/tahunan, serta analisis dan grafik. Berdasarkan keputusan pengguna pada 11 Oktober 2026, V1 menggunakan **Python + SQLite + PySide6 (Qt)**. Tahapan V1/V1.5/V2 mengikuti PRD lama, dengan aturan kualitas data, definisi metrik, dan kriteria penerimaan yang diperjelas. C++ menjadi opsi optimasi modul setelah profiling; migrasi bahasa tidak menjadi syarat versi produksi. Pilihan model, target performa, dan pembagian rilis merupakan usulan desain.

## 1. Ringkasan dan tujuan produk

Aplikasi mengubah video CCTV menjadi catatan kehadiran teramati, durasi penggunaan workstation, periode workstation kosong, dan statistik occupancy. Pengguna melihat kondisi langsung dan tren historis melalui GUI.

Pertanyaan yang harus dapat dijawab:

- Workstation mana yang sedang digunakan?
- Berapa lama setiap workstation digunakan dalam suatu periode?
- Kapan penghuni terlihat masuk dan keluar dari zona kerja?
- Bagaimana pola occupancy per jam, hari, minggu, bulan, dan tahun?
- Berapa banyak hasil yang didukung rekaman observasi yang valid?
- Kamera mana yang bermasalah dan memengaruhi kelengkapan laporan?

Istilah “productivity tracker” merupakan nama konsep produk. Metrik yang tersedia adalah **presence, occupancy, dan utilization**. Kehadiran di meja tidak membuktikan hasil kerja, dan meninggalkan meja tidak membuktikan bahwa seseorang berhenti bekerja.

## 2. Pengguna dan kebutuhan

| Pengguna | Kebutuhan utama |
|---|---|
| Owner/operations manager | Ringkasan penggunaan ruang, tren, dan laporan |
| Supervisor | Timeline workstation serta peninjauan observasi |
| Admin/IT | Konfigurasi CCTV, zona, database, backup, dan kesehatan sistem |
| Viewer, pada V1.5 | Membaca dashboard sesuai ruang lingkup akses |

MVP digunakan pada satu mesin di satu lokasi. Proses utama tetap berjalan tanpa koneksi internet selama CCTV dapat diakses melalui jaringan lokal.

## 3. Ruang lingkup rilis

| Rilis | Fitur |
|---|---|
| V1/MVP | RTSP, person detection, tracking, polygon zona, presence sessions, SQLite, agregasi harian sampai tahunan, dashboard, live view, grafik dasar, CSV, camera health, backup dan restore |
| V1.5 | Employee/workstation mapping, koreksi dengan audit log, role Admin/Manager/Viewer, alert, perbandingan departemen, ekspor Excel/PDF |
| V2 | PostgreSQL, banyak lokasi, dashboard web, API eksternal, SSO, integrasi HRIS, fitur enterprise |

Face recognition bersifat opsional setelah fondasi tracking stabil. ONVIF discovery, cloud synchronization, mobile dashboard, automatic zone calibration, anomaly detection, dan payroll integration merupakan pengembangan berikutnya.

V1 melaporkan occupant dan workstation. Laporan individual baru tersedia ketika metode identitas yang digunakan dapat dijelaskan dan ditampilkan kepada pengguna. GUI menggunakan API internal lokal pada engine; menutup jendela tidak menghentikan pencatatan. Autostart OS/service tetap tahap deployment berikutnya.

## 4. Alur penggunaan

1. Admin menambahkan kamera, memasukkan RTSP URL serta kredensial, lalu menjalankan connection test.
2. Admin membuka preview, menggambar polygon meja/ruang, menetapkan jenis zona dan kapasitasnya.
3. Admin menetapkan timezone lokasi, jam operasional, hari kerja, hari libur, dan jadwal istirahat bila diperlukan.
4. Engine menjalankan detection, tracking, dan zone association.
5. Perubahan status menghasilkan event yang disimpan dan dibentuk menjadi sesi.
6. Dashboard memperbarui occupancy, durasi sesi, kesehatan kamera, dan data coverage.
7. Pengguna memilih periode serta zona untuk membuka analytics dan mengekspor CSV.
8. Backup berjalan sesuai jadwal; admin dapat memverifikasi dan memulihkan backup.

## 5. Kebutuhan fungsional V1

| ID | Modul | Perilaku wajib |
|---|---|---|
| FR-01 | Cameras | Tambah/edit/nonaktifkan kamera; test connection; konfigurasi FPS inference |
| FR-02 | Video ingestion | Decode stream; kendalikan antrean frame; reconnect otomatis |
| FR-03 | Detection | Deteksi person dengan model dan threshold yang dapat dikonfigurasi |
| FR-04 | Tracking | Track ID per kamera dan per sesi engine; toleransi occlusion singkat |
| FR-05 | Workspaces | Polygon dari preview; jenis desk/room/area; kapasitas; exclusion zone |
| FR-06 | Presence | Event enter/exit; sesi; occupied/empty/unknown; durasi teramati |
| FR-07 | History | Penyimpanan event dan sesi; agregasi daily/weekly/monthly/yearly |
| FR-08 | Dashboard | KPI, tren, status kamera, coverage, dan waktu pembaruan terakhir |
| FR-09 | Live view | Grid/fullscreen; bounding box, track ID, polygon, durasi sesi |
| FR-10 | Analytics | Filter periode/lokasi/zona; grafik; drill-down ke sesi |
| FR-11 | Reports | CSV sesuai filter aktif, timezone, definisi metrik, dan coverage |
| FR-12 | Reliability | Backup, restore, restart recovery, logging, status gangguan penyimpanan |

Track ID bukan employee ID. Track ID juga tidak menjamin bahwa orang yang terlihat pada hari atau kamera berbeda adalah individu yang sama.

Untuk zona yang terlihat dari beberapa kamera, V1 menetapkan satu kamera utama untuk perhitungan zona tersebut. Kamera lain dapat digunakan untuk preview. Fusion antarkamera memerlukan rancangan dan validasi terpisah.

## 6. Identitas dan employee mapping

| Mode | Hasil yang dapat dinyatakan |
|---|---|
| Anonymous, V1 | Ada occupant/track di zona tertentu |
| Assigned workstation, V1.5 | Zona diasosiasikan ke employee berdasarkan penugasan yang berlaku |
| Identitas terverifikasi, opsional | Observasi dikaitkan dengan employee melalui metode verifikasi tambahan |

Penugasan “Desk A01 → Employee 001” adalah asumsi penempatan, bukan bukti siapa yang sedang duduk. GUI dan laporan harus menampilkan identity source, confidence bila tersedia, serta status unknown/unverified.

Workstation assignment memiliki tanggal mulai/akhir sehingga perubahan penempatan tidak mengubah identitas histori secara diam-diam. Face recognition tidak diperlukan untuk menghitung occupancy dan utilization.

## 7. Aturan event dan sesi

State zona: **OCCUPIED**, **EMPTY**, dan **UNKNOWN**. State kamera: **ONLINE**, **DEGRADED**, **OFFLINE**, dan **RECONNECTING**.

Event minimum:

- ENTER: keberadaan di zona telah dikonfirmasi.
- EXIT: zona kosong telah dikonfirmasi.
- OBSERVATION_LOST / OBSERVATION_RESTORED: kualitas observasi hilang/pulih.
- CAMERA_LOST / CAMERA_RESTORED: stream kamera hilang/pulih.
- ENGINE_STARTED / ENGINE_STOPPED: batas sesi proses untuk pemulihan.

ENTER dan EXIT memakai debounce/grace period yang dapat dikonfigurasi untuk mengurangi perubahan status akibat satu frame. Nilai awal harus dikalibrasi pada kamera pilot. Waktu bukti pertama, waktu konfirmasi, dan versi aturan disimpan agar hasil dapat ditelusuri. V1 menghitung waktu pending confirmation sebagai UNKNOWN; state baru mulai saat konfirmasi, tanpa backdating. Count yang belum pasti dapat unavailable meskipun presence jelas.

Aturan wajib:

- Sesi menggunakan interval mulai inklusif dan akhir eksklusif.
- Beberapa orang di satu workstation tidak menggandakan durasi occupied workstation itu.
- Occlusion atau confidence rendah yang tidak dapat diselesaikan menjadi UNKNOWN.
- Kamera offline tidak menghasilkan away time.
- Sesi yang kehilangan observasi dibatasi pada waktu observasi valid terakhir; rentang berikutnya menjadi UNKNOWN.
- Sesi yang terbuka saat crash ditandai interrupted ketika aplikasi pulih.
- Event memiliki ID unik dan penulisan ulang tidak membuat duplikasi.
- Perubahan polygon membuat versi konfigurasi baru; histori lama tetap menggunakan versi asalnya.
- Koreksi pada V1.5 mencatat alasan, pelaku, waktu, dan nilai sebelumnya.

## 8. Definisi metrik

Untuk suatu zona dan periode yang dipilih, setelah dipotong dengan jadwal analisis:

- **T**: total durasi yang masuk jadwal analisis.
- **P**: durasi occupied yang valid.
- **A**: durasi empty yang valid.
- **U**: durasi unknown, termasuk gap kamera dan gangguan observasi.

Identitas dasar: **T = P + A + U**. Istirahat terjadwal dikeluarkan dari T ketika filter “jam kerja terjadwal” dipilih. Tampilan “seluruh jam operasional” dapat menyertakannya dan harus diberi label berbeda.

| Metrik | Definisi |
|---|---|
| Presence/workstation occupied time | P |
| Empty/away from workstation time | A; tidak berarti orang tersebut tidak bekerja |
| Data coverage | (P + A) / T × 100% |
| Workstation utilization | P / (P + A) × 100% |
| Occupancy | Jumlah occupant teramati pada zona valid di suatu waktu |
| Peak occupancy | Nilai occupancy maksimum yang teramati pada periode |
| First seen / last seen | Waktu observasi valid pertama/terakhir dalam cakupan kamera |
| Session count | Jumlah sesi occupied yang dimulai dalam periode |
| Average daily presence | Total P dibagi jumlah hari eligible menurut filter kalender |

Jika denominator nol, tampilkan **N/A**, bukan 0%. Utilization selalu ditampilkan bersama coverage. Total lokasi menyertakan jumlah zona yang teramati dan tidak menyatakan headcount global unik jika identitas lintas kamera belum tersedia.

Untuk banyak workstation, utilization lokasi dihitung dari total occupied workstation-seconds dibagi total valid workstation-seconds. Nilai rata-rata tidak dihitung dengan merata-ratakan persentase zona secara sederhana.

Contoh ilustratif: periode 8 jam, occupied 6 jam, empty 1 jam, unknown 1 jam. Coverage = 87,5%; utilization selama waktu teramati = 85,7%. Satu jam unknown tetap ditampilkan terpisah.

## 9. Record harian, mingguan, bulanan, tahunan

| Periode | Record dan analisis |
|---|---|
| Harian | P/A/U, coverage, first/last seen, jumlah sesi, sesi terpanjang, timeline |
| Mingguan | Total durasi, grafik per hari, rata-rata hari eligible, heatmap jam × hari |
| Bulanan | Tren harian, total durasi, rata-rata occupancy, peak occupancy, utilization zona |
| Tahunan | Tren per bulan, total durasi, pola penggunaan ruang dan perbandingan periode |

Timestamp disimpan dalam UTC. Batas hari, minggu, bulan, dan tahun mengikuti timezone lokasi. Shift yang melewati tengah malam dipecah untuk agregasi kalender, sementara shift ID tetap tersedia untuk laporan per shift.

Agregasi berupa cache yang dapat dibangun ulang dari sesi dan observation gaps. Query custom range harus memotong interval secara tepat, termasuk sesi yang mulai sebelum periode dan berakhir sesudah periode. Record dapat berstatus provisional selama periode belum berakhir.

## 10. GUI dan analytics

Menu V1: **Dashboard, Live Cameras, Cameras, Workspaces, Analytics, Reports, Settings**. Menu Employees dan Alerts ditambahkan di V1.5.

| Halaman | Isi utama |
|---|---|
| Dashboard | Occupants teramati, workstation occupied/valid/total, total presence, utilization, coverage, kamera aktif, tren |
| Live Cameras | Grid, fullscreen, overlay, zona, track ID, status stream, staleness indicator |
| Cameras | Connection test, konfigurasi, FPS, latency, dropped frames, reconnect count |
| Workspaces | Polygon editor, jenis zona, kapasitas, konfigurasi dan versi |
| Analytics | Filter tanggal/zona/lokasi, grafik, tabel sesi, unknown gaps |
| Reports | Preview tabel, filter, CSV export dan metadata laporan |
| Settings | Company, timezone, kalender, detection, performance, database, retention, backup |

Grafik yang direncanakan: line chart untuk tren, bar chart perbandingan zona/periode, stacked bar occupied/empty/unknown, heatmap jam × hari, dan occupancy timeline. Perbandingan employee/departemen hanya tersedia jika identity mapping mendukungnya.

Setiap KPI dapat ditelusuri ke interval sumber. Status kamera putus dan hasil yang sudah lama tidak diperbarui terlihat jelas. Decode, inference, ekspor, dan agregasi berjalan di luar GUI thread.

## 11. Database dan penyimpanan

SQLite adalah pilihan V1 untuk deployment satu mesin. Database aktif berada pada disk lokal mesin pemrosesan, terpisah dari folder source code dan folder sinkronisasi cloud.

| Tabel | Data utama |
|---|---|
| cameras | ID, nama, alamat stream tanpa secret, referensi kredensial, konfigurasi |
| workspaces | ID, nama, lokasi, jenis, kapasitas |
| workspace_configurations | Kamera utama, polygon, version, effective time |
| engine_runs | ID run, versi engine/model, waktu mulai/akhir |
| event_log | Ledger ID/sequence unik, event typed, checkpoint dan projection mutation |
| camera_generations | Namespace capture/tracker yang berubah pada reconnect/restart |
| zone_intervals | Sumber canonical state/count zona, interval dan evidence watermark |
| track_visits | Diagnostik track; tidak menjadi sumber utilization |
| period_statistics | Cache ber-grain DAY/WEEK/MONTH/YEAR, durasi dan denominator |
| aggregation_runs / aggregate_publications | Source sequence, versi kalender/metrik, publication cache |
| schedule_versions | Timezone, kalender, jam operasional dan break rules berversi |
| command_receipts / api_jobs | Idempotency mutation dan pekerjaan API yang panjang |
| schema_migrations | Versi skema |
| backup_jobs | Waktu, hasil, ukuran, lokasi backup |
| employees, V1.5 | Kode, nama, departemen, status |
| workstation_assignments, V1.5 | Employee, zona, masa berlaku, sumber mapping |
| corrections/audit_logs, V1.5 | Perubahan, alasan, pelaku, timestamp |

Indexes disesuaikan untuk pencarian kamera/zona dan interval waktu. Repository memisahkan logic CV dari database sehingga PostgreSQL dapat ditambahkan kemudian.

SQLite WAL dipertimbangkan untuk pola baca/tulis lokal; pengaturan checkpoint dan transaksi harus diuji pada workload pilot. [Dokumentasi SQLite WAL](https://www.sqlite.org/wal.html).

## 12. Arsitektur dan teknologi

```text
CCTV / RTSP
    → Decode & frame sampling
    → Person detection
    → Multi-object tracking
    → Zone association
    → State & event processor
    → SQLite events, sessions, observation gaps
    → Aggregation service
    → PySide6 (Qt) desktop GUI / reports
```

| Komponen | Pilihan desain |
|---|---|
| Engine dan application logic | Python |
| Project setup | pyproject.toml, virtual environment, dependency versions yang dikunci setelah spike |
| Frame processing | OpenCV dan NumPy |
| Video ingestion | PyAV/FFmpeg dalam capture worker per kamera |
| Detector | Model person detection keluarga YOLO, model/version dipilih saat benchmark |
| Baseline inference | ONNX Runtime |
| NVIDIA optimization | TensorRT setelah baseline benar |
| Tracking | ByteTrack; BoT-SORT sebagai alternatif |
| GUI | PySide6 (Qt 6), Qt Widgets untuk baseline desktop, PyQtGraph untuk grafik |
| Database | SQLite melalui sqlite3; PostgreSQL pada V2 |
| Reporting | CSV pada V1; Excel/PDF pada V1.5 |
| API internal | FastAPI/Uvicorn satu worker, HTTP/WebSocket pada loopback |

Python mengatur pipeline dan business logic, sementara inference menggunakan ONNX Runtime atau TensorRT melalui API Python. GUI memakai PySide6, binding resmi Qt untuk Python. Versi Python serta kompatibilitas OpenCV, PySide6, inference runtime, dan GPU dipastikan pada spike sebelum dependency dikunci. [ONNX Runtime Python](https://onnxruntime.ai/docs/get-started/with-python.html), [TensorRT Python API](https://docs.nvidia.com/deeplearning/tensorrt/latest/inference-library/python-api-docs.html), [Qt for Python](https://doc.qt.io/qtforpython-6/).

Pisahkan modul video, inference, tracking, zones, events, database, analytics, GUI, logging, dan backup. Sediakan interface inference/repository serta event contract internal; API jaringan publik masuk V2.

GUI dan engine terpisah; supervisor lokal menjaga lifecycle. Capture memakai proses per kamera dan shared buffer terbatas. Inference session dimuat sekali dalam engine dan dijadwalkan antar kamera. Decode, inference, query, dan agregasi berjalan di luar GUI thread. GUI mengakses command/query engine melalui API lokal dan tidak membuka SQLite langsung. Writer tunggal menyimpan ledger, interval dan checkpoint dalam transaksi. Perpindahan frame serta penggunaan RAM/VRAM ikut diukur.

Python dapat tetap digunakan untuk produksi jika lolos target performa dan reliability. C++ dipertimbangkan hanya untuk modul yang terbukti menjadi bottleneck setelah optimasi model, decoding, antrean, dan perpindahan data. Penggantian modul harus mempertahankan event contract serta hasil perhitungan dan dibuktikan melalui benchmark sebelum/sesudah.

## 13. Performa dan reliability

Pilot dimulai dengan 1–4 kamera. Target skala produksi dari PRD lama adalah 20 CCTV per mesin, input 1080p, inference 5–10 FPS/kamera, dengan RTX 4060 sebagai salah satu kandidat hardware benchmark. Angka ini **target uji**, bukan kapasitas yang sudah terverifikasi.

Benchmark mencatat versi Python/dependency, model, ukuran input inference, codec, CPU, RAM, GPU/VRAM, jumlah kamera, decode FPS, inference FPS, latency, dan dropped frames. Profiling memisahkan waktu decoding, preprocessing, inference, tracking, zone association, transfer frame, dan database agar sumber bottleneck dapat diidentifikasi. Jumlah kamera sendiri tidak menentukan kebutuhan migrasi ke C++.

Persyaratan tambahan:

- Antrean frame dibatasi; overload tidak menambah latency tanpa batas.
- Gangguan satu kamera tidak menghentikan kamera lain.
- Backoff reconnect dan status gangguan terlihat di GUI.
- Disk penuh/database error membuat persistence status terdegradasi dan interval terdampak tidak dianggap lengkap.
- Log tidak memuat password atau RTSP URL yang mengandung secret.
- Shutdown normal menyelesaikan transaksi serta menutup sesi.
- Target awal refresh dashboard maksimal 2 detik; report agregat p95 maksimal 2 detik pada dataset dan hardware uji yang disepakati.
- Soak test minimal 24 jam tanpa crash, deadlock, atau pertumbuhan memori yang tidak terkendali.

## 14. Backup, retention, dan akses

Backup otomatis dijadwalkan harian dengan hasil sukses/gagal yang terlihat. Backup konsisten menggunakan mekanisme seperti SQLite Online Backup API; pemulihan dilakukan melalui alur maintenance yang tervalidasi. [Dokumentasi SQLite Online Backup API](https://www.sqlite.org/backup.html).

Default usulan: raw video tidak disimpan; detail event/interval 1 tahun; aggregate 3 tahun; backup harian 30 hari. Metadata anchor yang masih direferensikan cache dipertahankan sesuai kebutuhan integritas. Admin dapat mengubahnya sesuai kebijakan lokasi. Retention juga berlaku pada backup dan ekspor yang dikelola aplikasi. Setelah detail dihapus, GUI menjelaskan keterbatasan drill-down/rebuild dan hanya menyediakan cache bucket yang sesuai; custom range exact tidak dipenuhi dengan prorata aggregate.

Video/frame diproses sementara. Snapshot untuk debug bersifat opt-in dan memiliki retention pendek. Kredensial kamera disimpan melalui penyimpanan secret yang sesuai platform.

V1 diasumsikan sebagai instalasi lokal dengan akses melalui account OS yang dikelola lokasi. Sebelum penggunaan bersama beberapa role, V1.5 menyediakan autentikasi dan audit:

| Kemampuan | Admin | Manager | Viewer |
|---|---|---|---|
| Dashboard/analytics | Ya | Sesuai scope | Sesuai scope |
| Live view | Ya | Sesuai scope | Sesuai scope |
| Kamera/zona/settings | Ya | Tidak | Tidak |
| Export | Ya | Sesuai scope | Tidak |
| Koreksi observasi | Ya | Sesuai scope | Tidak |
| Delete/restore/config retention | Ya | Tidak | Tidak |

Alert V1.5 meliputi kamera offline, backup gagal, dan workstation kosong melebihi threshold dalam jadwal yang valid. Threshold dapat dikonfigurasi, alert dideduplicasi, dan periode unknown tidak memicu alert “away”.

## 15. Kriteria penerimaan

| ID | Skenario | Hasil yang harus dipenuhi |
|---|---|---|
| AC-01 | RTSP tersambung | Preview, status, dan pipeline aktif |
| AC-02 | Person masuk/keluar zona | Event/sesi mengikuti aturan debounce tanpa duplikasi |
| AC-03 | Occlusion, low confidence | Hasil tidak pasti ditandai unknown |
| AC-04 | Kamera diputus 10 menit | Kamera lain tetap berjalan; gap 10 menit tidak menjadi away |
| AC-05 | Restart dengan sesi terbuka | Sesi lama ditandai interrupted; periode tanpa observasi tidak ditambah ke presence |
| AC-06 | Dua orang pada satu desk | Durasi occupied desk dihitung sekali |
| AC-07 | Boundary kalender/custom range | Interval dipotong tepat; total periode konsisten tanpa double counting |
| AC-08 | Replay event/agregasi | Jumlah record dan total durasi tetap sama |
| AC-09 | CSV export | Angka sesuai GUI; periode, timezone, identity source, coverage tersedia |
| AC-10 | Backup/restore | Backup dapat dibuka, data/config dipulihkan, validasi database lulus |
| AC-11 | Soak test | 24 jam operasi dengan resource terukur dan tanpa crash/deadlock |
| AC-12 | Pilot beranotasi | Usulan target: precision dan recall occupied/empty masing-masing ≥90% pada interval evaluasi valid; coverage minimum pilot ditetapkan sebelum uji |

Untuk AC-12, rekaman pilot mencakup orang membelakangi kamera, beberapa occupant, occlusion, perubahan cahaya, dan workstation kosong. Unknown dilaporkan terpisah bersama coverage agar akurasi tidak diperbaiki hanya dengan menolak sebagian besar interval. Target dan toleransi waktu final disetujui setelah kalibrasi pilot.

## 16. Urutan implementasi

1. Setup proyek Python, pyproject.toml, virtual environment, konfigurasi, logging, dan database migrations.
2. RTSP capture satu kamera, reconnect, dan antrean terbatas.
3. Person detection dengan ONNX Runtime.
4. Tracking dan namespace track per engine run.
5. Polygon editor serta zone association.
6. State machine, event, sesi, observation gaps, dan restart recovery.
7. Daily/weekly/monthly/yearly aggregation dan interval clipping.
8. PySide6 dashboard, live view, dan analytics dengan worker di luar GUI thread.
9. CSV export, backup, restore, dan retention.
10. Multi-camera benchmark, kalibrasi, dan soak test.
11. Packaging aplikasi Python/PySide6 untuk Windows/Linux serta pilot lokasi; uji instalasi pada mesin tanpa development environment.

Deliverable V1: aplikasi desktop terpasang, konfigurasi kamera/zona, SQLite, laporan dan grafik, CSV, backup yang sudah diuji restore, dokumentasi instalasi, dan hasil benchmark. Tidak ada estimasi tanggal rilis sebelum spike teknis dan pilot scope selesai.

## 17. Pengembangan produk

Konsep paket dari PRD lama: Demo dengan kamera/history terbatas, Professional untuk analytics satu lokasi, dan Enterprise untuk banyak lokasi serta integrasi. Batas kamera dan harga ditetapkan setelah benchmark dan validasi pelanggan; estimasi harga dalam percakapan lama tidak menjadi komitmen pada dokumen ini.

Fondasi implementasi tetap **person detection → tracking → workspace → events → aggregation**. Employee identity ditambahkan sebagai layer dengan sumber dan tingkat verifikasinya.

## 18. Rancangan teknis pendamping

[Architecture](docs/ARCHITECTURE.md), [Technical Design](docs/TECHNICAL-DESIGN.md), [Database Design](docs/DATABASE-DESIGN.md), [API Design](docs/API-DESIGN.md), [SQL reference](docs/database/001_initial.sql), [OpenAPI contract](docs/api/openapi.json), dan [Implementation Plan](docs/IMPLEMENTATION-PLAN.md) memperjelas PRD ini. Angka kapasitas dan runtime acceptance belum terverifikasi oleh pembuatan dokumen.

Tahap desain UI/UX: [UI/UX Specification](UI_UX_SPEC.md), [Design System](DESIGN_SYSTEM.md), [Component Inventory](COMPONENT_INVENTORY.md), [Screen Implementation Plan](SCREEN_IMPLEMENTATION_PLAN.md), serta [proposal visual](docs/ui/VISUAL_REVIEW.md). GUI tetap native PySide6; contoh visual tidak menambahkan employee classification atau video recording ke scope V1.

