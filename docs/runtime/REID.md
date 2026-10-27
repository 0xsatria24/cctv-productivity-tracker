# Person ReID: off, shadow dan active

Implementasi tersedia di `src/cctv_tracker/reid/`: kontrak frame dan embedding,
validasi konfigurasi, crop dari JPEG asli, provider OpenVINO, gallery RAM,
matcher konservatif, dan diagnostik. `runtime.py` menghubungkan modul tersebut
ke `Pipeline`; webcam/RTSP melalui `LiveController` meneruskan JPEG frame yang
sama dengan hasil detektor. Crop mengikuti urutan box terukur keluaran tracker,
bukan urutan detektor sebelum tracking atau gambar preview terbaru.

Default `Settings.reid.mode` adalah `off`. Mode `shadow` menghasilkan keputusan
`REJECT`, `PENDING`, atau `WOULD_MATCH`, tanpa mengubah binding sesi, durasi, atau
rekap area. Mode `active` sudah menerapkan keputusan ke SessionManager, sehingga
sesi yang lolos konfirmasi dapat kembali memakai session_id dan durasi lamanya.
Threshold masih eksperimental: evaluasi kamera berlabel yang memadai untuk
klaim akurasi lapangan belum dilakukan.

## Konfigurasi

Tambahkan field berikut ke konfigurasi engine untuk memakai artifact lokal yang
sudah diperiksa. Path relatif dihitung dari direktori file konfigurasi.

```json
{
  "reid": {
    "mode": "active",
    "recovery_policy": "motion",
    "manifest_path": "../models/reid/evaluated-model/manifest.json",
    "device": "CPU"
  }
}
```

Tidak ada download otomatis atau model ReID bawaan. Threshold default adalah
nilai awal untuk pengujian mekanik, belum hasil kalibrasi kamera. Jangan
mengartikan cosine similarity sebagai probabilitas identitas.

Manifest berikut menunjukkan format; ganti semua placeholder dengan metadata
artifact sebenarnya. Provider menerima IR XML/BIN, satu input NCHW batch 1,
dan satu output `[1, dimensions]` atau `[1, dimensions, 1, 1]`.

```json
{
  "model_id": "replace-with-model-version",
  "source": "replace-with-artifact-source",
  "license": "replace-with-artifact-license",
  "precision": "FP32",
  "preprocessing_revision": "resize-linear-v1",
  "dimensions": 256,
  "xml": {"path": "model.xml", "sha256": "replace-with-64-lowercase-hex"},
  "bin": {"path": "model.bin", "sha256": "replace-with-64-lowercase-hex"},
  "input": {
    "layout": "NCHW", "color": "BGR", "height": 256, "width": 128,
    "mean": [0, 0, 0], "scale": [1, 1, 1]
  }
}
```

Ukuran, warna, mean, dan scale harus mengikuti kontrak model yang dipilih.
Preprocessing: resize bilinear, perubahan BGR ke RGB bila diminta, kemudian
`(pixel - mean) * scale`, float32 NCHW. Hash XML dan BIN dicek sebelum load;
identitas pembanding mencakup kedua hash dan seluruh spesifikasi preprocessing.
Provider menggunakan [infer request OpenVINO](https://docs.openvino.ai/2026/openvino-workflow/running-inference/inference-request.html).

## Batas runtime

- Crop kecil, blur, di tepi frame, bentuk tubuh tidak layak, confidence rendah,
  dan overlap berisiko ditolak. Overlap bukan ukuran occlusion sebenarnya.
- Ekstraksi sinkron dibatasi cadence dan jumlah crop. Anggaran latency diperiksa
  setelah ekstraksi; ini bukan timeout keras untuk native inference. Jika
  terlampaui atau provider error, hasil dibuang dan ReID dinonaktifkan untuk
  run tersebut. Restart run diperlukan setelah memperbaiki model/perangkat.
- Observasi detektor tetap diproses saat ReID gagal. Frame usang ditolak pipeline
  sebelum ekstraksi, gallery, dan accounting dimutasi.
- Gallery dibatasi TTL, jumlah sesi, dan sampel. Scope kamera/run/generasi dan
  model harus cocok; offline/reconnect membersihkan bukti lama.
- Matching memakai konsensus minimal dua sampel gallery yang paling sesuai,
  sehingga beberapa pose tidak harus mirip dengan setiap pose lama. Satu sampel
  outlier tidak cukup. Mutual best dan margin dua sisi tetap wajib, disertai
  konfirmasi dari beberapa frame dan waktu minimum.
- `Pipeline` accounting selalu memakai policy `motion`, termasuk bila konfigurasi
  replay meminta `short_occlusion`. Policy motion mempertahankan larangan
  recovery orang diam, visible exit, reconnect, dan kandidat gerak ambigu.
  Active accounting mensyaratkan `count_lost_gap=false`.
- Hanya replay tanpa accounting yang bisa memakai policy `short_occlusion`:
  orang diam dapat dipulihkan bila kualitas crop, posisi, gap waktu, appearance,
  margin dan konfirmasi lolos. Exit samping/bawah, perjalanan keluar di atas,
  jarak tidak masuk akal, dan ambiguity tetap ditolak. Kepala terpotong batas
  atas pada kamera tinggi tidak otomatis dianggap orang keluar.
- Gallery dan vote baru diterapkan setelah checkpoint database berhasil.
  Sampel provisional dipindahkan sekali setelah rekonsiliasi committed.
  Active menulis keputusan penting ke `reid_decisions` dalam transaksi yang sama
  dengan sesi, mapping dan checkpoint (migrasi 005). Tidak ada audit untuk setiap
  pasangan skor atau query tanpa gallery yang eligible. Shadow tidak mengubah
  timer/binding; statistik ringkas tersedia pada `latest.reid`.
- Crop dan embedding hanya berada di RAM, tidak dipersistenkan atau diekspos
  melalui API. Snapshot berisi keputusan dan jumlah gallery, tanpa vektor/gambar.
- Replay sintetis tetap berjalan tanpa piksel (`NO_PIXELS` bila shadow).
  Pemanggil `Pipeline.feed` lain dapat memasok `frame_jpeg` yang sesuai frame.
  Jalur preview lokal `ReplayTracking` juga menjalankan ReID active/shadow bila
  dikonfigurasi. Gallery terpisah per file dan generasi seek; model provider
  dibagi antarstream dengan lock inferensi. Replay tetap tanpa accounting.

Penanganan confidence turun, box terakhir, dan daftar timer terbaru dijelaskan
di [REPLAY-STABILITY.md](REPLAY-STABILITY.md), beserta hasil uji dan batasnya.

## Menjalankan replay dari npm

Unduh artifact resmi dan verifikasi checksum terlebih dahulu, dari root project:

```powershell
.venv/Scripts/python.exe scripts/setup_reid_model.py
cd prototype
npm.cmd run dev:reid
```

Buka `http://localhost:5174/#/live`, pilih video, centang **Deteksi preview**,
lalu **Putar**. Status ReID muncul di bawah video. Engine terpisah memakai port
8770 dan database pengujian `runtime/reid-demo/dashboard.sqlite3`. Gunakan
hostname `localhost` tersebut agar cookie sesi terpisah dari dashboard lama
di `127.0.0.1`. `npm run dev` biasa tetap memakai konfigurasi engine yang ada.

Launcher demo memakai YOLOX OpenVINO GPU dan ReID CPU, mode active eksperimental,
policy `short_occlusion`, gap maksimal 2 detik, 3 observasi dan waktu konfirmasi
minimal 0,4 detik. Crop memerlukan confidence 0,55 dan similarity minimal 0,85,
margin 0,08. Profil ini belum merupakan kalibrasi akurasi produksi. UI menampilkan
jumlah recovery visual yang benar-benar diterapkan; timer provisional menampilkan
"Memastikan identitas..." selama konfirmasi, lalu berpindah ke sesi lama saat
diterima. Waktu selama kehilangan tidak ditambahkan. Demo memakai
anggaran ekstraksi 5000 ms agar cold compilation dapat diuji. Angka tersebut
bukan target latency live. Frame visual lama tetap disembunyikan UI. Model yang
diunduh adalah retail-0287 FP32 Open Model Zoo 2023.0; SHA-384 XML/BIN diverifikasi
terhadap metadata resmi, kemudian SHA-256 dicatat dalam manifest lokal.

Uji ulang API lokal dengan video sendiri:

```powershell
.venv/Scripts/python.exe scripts/verify_reid_replay.py --video C:/path/video.mp4
```

Hasil ringkas disimpan di `runtime/reid-demo/verification.json`, tanpa embedding
atau crop. Uji ini membuktikan eksekusi model, bukan akurasi identitas.

## Verifikasi

Tes `test_reid_*` mencakup quality gate, korelasi frame/model, output invalid,
batas gallery, ambiguity dua arah, konfirmasi waktu, kesetaraan durasi off/shadow,
error provider, budget latency, hasil usang, serta gagal commit. Tes OpenVINO CPU
memakai graph sintetis untuk memeriksa preprocessing dan normalisasi sebenarnya.
Graph tersebut tidak mengukur kemampuan mengenali ulang worker.

Uji aktif juga memeriksa transfer durasi tepat sekali, beda penampilan/posisi,
seragam sama dengan kandidat ambigu, seek, crop buruk, kepala terpotong,
exit, audit atomik dan rollback gagal commit. Pemeriksaan lapangan tetap memerlukan
rekaman kamera berlabel dan evaluasi false merge, ID switch, fragmentasi,
error durasi, serta latency pada mesin target. Hasil uji aktif tersedia di
[REID-ACTIVE-RESULTS.md](REID-ACTIVE-RESULTS.md). Rencana lengkap ada di
[REID-IMPLEMENTATION-PLAN.md](REID-IMPLEMENTATION-PLAN.md).
