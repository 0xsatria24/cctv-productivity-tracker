# Sesi orang, durasi, dan pemulihan tracking

Implementasi ini memakai sesi anonim per kamera. Tidak ada pengenal wajah, appearance embedding, atau model ReID baru. Deteksi berbasis box dan lintasan tidak dapat membuktikan identitas seseorang setelah keluar kamera.

## Penyebab masalah sebelumnya

- `Pipeline.feed` mengambil timer dari `track_visits.last_observed_utc_us - start_utc_us`. `RunWriter.commit` menutup visit saat track tidak ada dalam satu observasi. Deteksi berikutnya memulai visit baru, sehingga timer kembali nol meskipun tracker mengembalikan ID yang sama.
- ByteTrack di-reset setelah evidence gap, tetapi ID lokalnya bisa dipakai ulang dalam generasi kamera yang sama. Sebelumnya kunci hanya `generation:track_id`.
- Menggunakan ID tracker langsung untuk timer tidak memverifikasi kontinuitas identitas. ByteTrack juga bisa menukar ID ketika dua orang berpapasan.
- Preview JPEG dan status deteksi dipoll terpisah; hasil yang berbeda frame dapat tertempel pada gambar yang lebih baru.

## Lifecycle dan pencocokan

`sessions.py` menyimpan `session_id` UUID tersendiri, kamera, generasi stream, first/last seen kalender, akumulasi monotonic/media, status, box terakhir, riwayat terbatas, dan durasi tiap zona. Kunci lifecycle track berubah setelah loss atau pergantian ID. Satu binding aktif hanya memiliki satu sesi; constraint SQLite memeriksa keunikan track aktif dan lifecycle.

1. Track aktif dicocokkan dengan box terukur melalui posisi prediksi, ukuran, dan gerak. ID tracker tidak memecahkan ambiguitas. Kandidat harus menjadi pasangan terbaik pada kedua sisi dengan margin yang cukup. Deteksi boleh tidak memperoleh pasangan.
2. Ketika absen, sesi menjadi `LOST`; timer membeku, binding dilepas, dan box lama tidak dirender. History dan durasinya tetap disimpan.
3. Deteksi yang belum terverifikasi mendapat sesi sementara dengan first seen dan timer sendiri. Pemulihan LOST membutuhkan lintasan lama yang bergerak konsisten, gap terbatas, posisi prediksi yang masuk akal, serta kandidat konsisten selama beberapa observasi. Posisi pertama kandidat harus menunjukkan kemajuan yang sesuai dengan lintasan selama gap. B yang mulai dari posisi terakhir A lalu meniru arah/kecepatannya tetap terpisah pada fixture pengujian.
4. Pemulihan menolak lintasan keluar batas frame, confidence rendah, gerak diam/tidak cukup, dan skor yang ambigu. Ambiguitas crossing memblokir pemulihan sesi lama yang terlibat. Tidak ada penggabungan paksa.
5. Saat pulih, durasi sesi sementara dipindahkan sekali ke sesi lama. `first_seen` sesi lama tetap. Sesi sementara difinalisasi dengan `merged_into` dan durasi nol agar konsumen tidak menghitungnya dua kali. Interval yang tumpang tindih tidak bisa direkonsiliasi.
6. Setelah grace habis, sesi `EXPIRED` difinalisasi di `last_seen`, lalu dikeluarkan dari RAM. Batas kapasitas mengeluarkan LOST tertua; jika semua slot aktif, deteksi berlebih mendapat status `UNASSIGNED` dan timer nol, tanpa mengambil sesi lain.

## Waktu, ROI, dan stream

- Live memakai `perf_counter_ns`; replay video tetap memakai presentation timestamp media. Durasi tidak berasal dari FPS atau jumlah frame. UTC diikat ke anchor kalender dan interval monotonic/media; timestamp input disediakan sebagai `captured_utc_us`, sedangkan event juga memiliki `recorded_utc_us` kalender.
- `count_lost_gap=false`: hanya interval pengamatan yang berlanjut dan interval sesi sementara terverifikasi yang dihitung. Saat reconnect kandidat mulai pada detik 18 dan konfirmasi selesai 18,2, sesi lama 15 detik menjadi 15,2 detik.
- `count_lost_gap=true`: gap dari last seen lama sampai first seen kandidat ditambahkan hanya setelah pemulihan berhasil dan memenuhi batasnya. Contoh yang sama menjadi 18,2 detik. Sesi yang expired tidak mendapat bonus gap.
- Missed detection tidak membuktikan keluar ROI. Status keanggotaan sesi dipertahankan, sementara durasi membeku. Posisi terukur di luar ROI harus konsisten beberapa observasi untuk mengonfirmasi exit. Interval di luar/ambigu tidak ditambahkan.
- Akuntansi zona agregat tetap memakai `ZoneAccumulator`, konfirmasi occupied/empty, dan UNKNOWN untuk bukti yang hilang. Durasi orang tidak dijadikan sumber utilisasi workstation.
- `CAMERA_OFFLINE`, frame stale, dan pergantian generasi memblokir pemulihan berbasis gerak untuk sesi yang terdampak. Jeda offline tidak dihitung, termasuk ketika `count_lost_gap=true`. Tanpa bukti identitas tambahan, orang setelah reconnect memperoleh sesi baru. Stop/crash/run baru juga memfinalisasi state lama tanpa memperpanjang durasi.

## Persistensi, event, dan overlay

Migrasi runtime 004 menambahkan `person_sessions` tanpa mengubah data/migrasi lama. Upsert sesi, durasi zona, checkpoint, dan event dilakukan dalam satu transaksi. Semua binding yang berubah dibersihkan dahulu sebelum dipasang kembali, sehingga pertukaran ID tracker tidak menyebabkan konflik parsial. Hasil tidak dipublikasikan jika commit gagal.

Field API lama (`track_id`, `box`, `confidence`, `workstation_times[].presence_us`, zones) tetap tersedia. Metadata baru antara lain `session_id`, `track_lifecycle`, `mapping_version`, `first_seen_utc_us`, `accumulated_duration_us`, dan snapshot `sessions`, termasuk LOST dengan timer yang membeku. `track_visits` tetap diagnostik, kini memakai kunci lifecycle. Konsumen tidak boleh memakai kunci itu sebagai identitas orang.

Live menambahkan event `SESSION_STARTED`, `SESSION_MAPPING`, `SESSION_LOST`, `SESSION_RECOVERED`, dan `SESSION_EXPIRED`. Perubahan sesi juga tersedia dalam payload checkpoint. Jumlah dan urutan checkpoint replay lama dipertahankan; event ENTER/EXIT dan perhitungan laporan lama tetap berlaku.

Pipeline menolak timestamp/sequence lama, generasi stream yang sudah dipensiunkan, dan versi mapping lama bila disertakan pada `feed`. Live menolak hasil inference yang stale atau selesai setelah stop. Pipeline tetap memiliki satu pemilik/writer; belum ada pool inference paralel baru.

Preview menyimpan maksimal 8 JPEG terproses di RAM untuk memasangkan poll metadata dengan frame yang sama. Request preview opsional menerima `frame_seq` dan `run_id`; respons membawa `X-Frame-Sequence`, `X-Run-Id`, dan `X-Mapping-Version`. UI memakai snapshot sesi yang cocok dengan JPEG tersebut, dan menyembunyikan overlay jika token tidak cocok. Preview tanpa parameter tetap kompatibel.

## Konfigurasi awal

Tambahkan objek `sessions` pada konfigurasi pilot atau headless. Live mengambilnya dari `Settings` engine, sedangkan kalibrasi UI yang sudah ada tetap kompatibel. Contoh tersedia di `config/pilot.example.json` dan `config/headless.example.json`.

| Parameter | Awal | Makna |
| --- | ---: | --- |
| `grace_period_seconds` | 10 | Retensi LOST di RAM, dihitung dari last seen |
| `motion_recovery_seconds` | 3.5 | Maksimum last seen lama ke first seen kandidat |
| `recovery_confirm_observations` | 3 | Observasi kandidat berturut-turut yang lolos |
| `recovery_confirm_seconds` | 0.2 | Rentang minimum konfirmasi gerak |
| `recovery_confirmation_window_seconds` | 1 | Usia maksimum sesi sementara untuk pemulihan |
| `active_position_tolerance` | 0.12 | Batas posisi aktif dalam koordinat frame ternormalisasi; juga dibatasi ukuran box |
| `recovery_position_tolerance` | 0.035 | Batas posisi pemulihan, lebih ketat dan dibatasi ukuran box |
| `recovery_progress_tolerance` | 0.35 | Toleransi relatif kemajuan posisi pertama kandidat sepanjang lintasan yang diprediksi |
| `minimum_motion_speed` | 0.015 | Kecepatan minimum lintasan, koordinat ternormalisasi per detik |
| `minimum_match_score` | 0.55 | Skor minimum setelah hard gate |
| `match_margin` | 0.15 | Margin terhadap kandidat kedua pada kedua sisi |
| `roi_exit_observations` | 3 | Observasi posisi luar ROI untuk konfirmasi exit |
| `max_sessions` | 256 | Batas ACTIVE + LOST per engine kamera |
| `history_size` | 8 | Maksimum sampel box/gerak per sesi |
| `count_lost_gap` | false | Tambahkan gap hanya setelah pemulihan sah |
| `diagnostics` | false | Log INFO opsional untuk mapping, match, penolakan, recovery, dan expiration |

Grace dan jendela pemulihan berbeda: penyimpanan 10 detik tidak memberi hak menyambungkan ulang selama 10 detik. Konfirmasi boleh selesai sampai 1 detik setelah kandidat pertama terlihat, tetapi gap first seen kandidat tetap harus memenuhi 3,5 detik. Sesuaikan parameter terhadap cadence inference aktual, perpindahan box, perspektif kamera, dan hasil berlabel. Memperbesar jendela/toleransi dapat meningkatkan penggabungan salah; memperketatnya meningkatkan fragmentasi. Dengan 3 observasi dan jendela 1 detik, cadence di bawah sekitar 2 FPS akan sering gagal konfirmasi dan perlu konfigurasi yang sesuai.

## Bagian kode yang berubah

| File | Bagian |
| --- | --- |
| `src/cctv_tracker/sessions.py` | Lifecycle, histori terbatas, dua tahap matching, timer monotonic, ROI, rekonsiliasi, diagnostik |
| `src/cctv_tracker/config.py` | `SessionRules`, `Settings.sessions`, validasi dan loading JSON |
| `src/cctv_tracker/vision.py` | Epoch pada reset ByteTrack dan pencocokan output box tanpa memakai deteksi dua kali |
| `src/cctv_tracker/pipeline.py` | Penolakan envelope usang, anchor waktu, sesi per binding, snapshot yang sama untuk commit/API/overlay |
| `src/cctv_tracker/persistence.py` | Migrasi 004, upsert sesi dan event dalam checkpoint, finalisasi run lama/berhenti |
| `src/cctv_tracker/resources/004_person_sessions.sql` | Tabel sesi dan constraint binding aktif unik |
| `src/cctv_tracker/live.py` | Isolasi kamera, penolakan hasil setelah stop, cache preview terbatas beserta token frame |
| `src/cctv_tracker/api.py` | Parameter frame preview dan header korelasi |
| `src/editions/headless/service.py`, `__main__.py` | ID kamera asli di Settings dan konfigurasi sesi headless |
| `prototype/src/camera-wall.jsx` | Overlay dari snapshot yang cocok dengan JPEG; key sesi dan label durasi |
| `config/*.example.json`, `src/cctv_tracker/resources/pilot.example.json` | Contoh konfigurasi sesi |
| `tests/test_sessions.py`, tes live/API/headless/persistence | Skenario wajib, crash/rollback, kompatibilitas dan isolasi |
| `scripts/validate_tracking_sessions.py` | Metrik fixture berlabel serta benchmark latency/heap lokal |
| `prototype/tests/engine/tracking-overlay.spec.js`, `prototype/playwright.tracking.config.js` | Pengujian UI token frame/mapping di server terisolasi port 8778 |

## Validasi yang dapat diulang

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests --basetemp runtime/session-tests-review
.\.venv\Scripts\python.exe scripts/validate_tracking_sessions.py --frames 500 --pipeline-frames 80
cd prototype
npm.cmd test
npm.cmd run build
node node_modules/@playwright/test/cli.js test --config playwright.tracking.config.js
```

`tests/test_sessions.py` menguji sesi 15 detik/loss 3 detik untuk kedua mode gap, ID berubah dan digunakan ulang, B dari lokasi A termasuk gerak serupa, A kembali saat B ada, crossing, posisi mirip, ambiguity, expiration, retensi terpisah dari recovery, ROI, confidence rendah, kapasitas, clock/FPS/sequence, generasi/mapping usang, ByteTrack asli, dan rollback transaksi. Tes live mencakup inference terlambat, stop ketika inference berjalan, dan kegagalan commit. Tes API memverifikasi token JPEG serta pengambilan frame sebelumnya; tes headless memverifikasi isolasi kamera.

Script validasi menghasilkan fixture ground truth sintetis, metrik identity switch/penggabungan salah/fragmentasi setelah rekonsiliasi alias sementara, latency manager, perbandingan pipeline dengan `HEAD`, dan alokasi heap Python. Baseline memakai tracker serta mode SQLite yang sama, dan tidak mencakup inference/decoder. Angka hasil run dicatat di laporan JSON runtime dan ringkasan hasil di bawah.

## Hasil lokal 19 Oktober 2026

- Suite Python final: **89 passed**, 3 warning deprecation dependency, 52,48 detik. Tes API berjalan di luar sandbox setelah diagnosis menunjukkan event loop Windows tertahan pada socket loopback di sandbox.
- Unit frontend: **14 passed**. Vite production build berhasil.
- Uji browser Edge: **1 passed**, 15,3 detik termasuk startup server. Fixture memastikan overlay hilang ketika frame sequence atau mapping version berbeda, dan box B menampilkan timer B walaupun ID tracker digunakan ulang. Ini validasi UI sintetis.
- **11 fixture kualitas** pada script validasi: **0 identity switch aplikasi, 0 penggabungan sesi salah**. Hasil ini berlaku pada fixture tersebut.
- A 15 detik/loss 3 detik: **15,2 detik** dengan gap tidak dihitung, **18,2 detik** dengan gap dihitung. Kandidat baru mulai terlihat pada detik 18 dan selesai konfirmasi pada 18,2; waktu 0,2 detik hanya dihitung sekali.
- B tetap terpisah ketika masuk pada box terakhir A, termasuk ketika B lalu mengikuti arah dan kecepatan A. Pada fixture A kembali sementara B ada, durasi akhir B **2,8 detik** dan A **15,2 detik**.
- Crossing dengan occlusion total menghasilkan **4 fragmen tambahan** (3 sesi per orang) tanpa pertukaran timer. Bukti gerak tidak cukup, expiration, dan reconnect masing-masing menghasilkan 1 fragmen tambahan pada fixture orang yang sama. Fragmentasi ini menunjukkan keterbatasan yang masih ada.

Benchmark Python 3.12.14, Windows 11, **16 orang dalam satu kamera dan satu ROI**:

| Pengukuran | Median | P95 |
| --- | ---: | ---: |
| Manager sesi, 500 observasi | 4,19 ms | 5,95 ms |
| Pipeline baseline HEAD `71ccb519`, 80 observasi | 17,31 ms | 19,95 ms |
| Pipeline dengan sesi dan commit SQLite, 80 observasi | 21,19 ms | 27,43 ms |

Tambahan median pipeline pada run ini **3,89 ms/observasi**. Angka dipengaruhi scheduling CPU dan disk; tidak mengukur decoder atau inference model. Riwayat manager tetap **16 sesi / 128 sampel**. Heap Python manager setelah dua fase 500 observasi: **55.362 → 56.598 byte**, peak **182.878 byte**. Tracemalloc dimulai sebelum manager dibuat; angka tidak mencakup buffer native, preview JPEG, model, atau RSS seluruh proses. Tes kapasitas terpisah menjalankan 1.000 observasi dan memverifikasi batas sesi serta history.

Laporan mesin lengkap: `runtime/tracking-session-validation-final.json`. Histori JPEG memiliki batas terpisah 8 frame per engine; besarnya bergantung ukuran JPEG.

## Keterbatasan

Gerak/box hanya bukti kontinuitas lintasan. Pengganti yang menghasilkan pengamatan identik dengan orang sebelumnya masih tidak dapat dibedakan. Orang diam yang hilang, crossing total, keluar/masuk frame, perubahan arah ekstrem, jitter besar, atau reconnect dapat memecah sesi. Ini tradeoff yang disengaja untuk mengurangi penggabungan dua orang.

Fixture berpakaian mirip direpresentasikan dengan informasi visual yang sama-sama tidak tersedia: tidak ada fitur pakaian atau embedding yang dipakai untuk menggabungkan. Hasil tersebut tidak mengukur diskriminasi pakaian dari rekaman nyata. Belum ada pengukuran akurasi lapangan, ReID, decoder multi-kamera, native memory/RSS, soak panjang, atau kapasitas produksi. Database menyimpan histori audit; batas state di RAM tidak menggantikan kebijakan retensi disk.

## Pembaruan adapter MOT

Perbaikan cadence Kalman/ByteTrack, binding source index, konfigurasi raw tracker,
dan pencegahan sesi dari deteksi lemah dijelaskan di
[MULTI-OBJECT-TRACKING.md](MULTI-OBJECT-TRACKING.md). Aturan konservatif sesi dan
timer di dokumen ini tetap menjadi batas recovery aplikasi.
