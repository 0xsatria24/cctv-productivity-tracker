# Confidence terpisah untuk tracking

YOLOX ONNX dan OpenVINO memakai tiga batas dengan fungsi berbeda:

| Batas default | Fungsi |
| --- | --- |
| `detection.tracking_confidence = 0.10` | Kandidat tambahan bagi tracker. |
| `detection.confidence = 0.45` | Deteksi publik, jumlah orang, dan overlay terukur. |
| `rules.strong_confidence = 0.50` | Bukti kuat untuk sesi/durasi. |

ByteTrack yang dipin memakai tahap kedua untuk skor **>0.10 dan <0.25** dengan
`tracking.activation_threshold=0.25`. Sebelumnya decoder membuang semua skor di
bawah 0.45 sehingga jalur itu tidak mendapat kandidat. Implementasi lokal
supervision 0.26.1 diverifikasi; pendekatan dasarnya dijelaskan dalam
[paper ByteTrack](https://www.ecva.net/papers/eccv_2022/papers_ECCV/papers/136820001.pdf).

## Kontrak

- Respons detektor mempertahankan `detections` dan `count` pada threshold publik.
  Kandidat berada di `tracking_candidates`; `tracking_candidate_count` tersedia
  untuk diagnostik. NMS publik dihitung terpisah sehingga kandidat full-frame
  yang lemah tidak menekan deteksi tile yang kuat.
- Kandidat lemah diberi `Detection.tracking_only=True`. Tracker mempertahankan
  flag itu pada binding ID. Maksimal 1024 proposal lemah masuk NMS dan maksimal 128
  kandidat diteruskan per frame; kandidat yang menduplikasi deteksi publik dibuang.
  Skor internal tidak dibulatkan agar kandidat dekat batas 0.10/0.25 tidak
  jatuh ke celah threshold ByteTrack; format skor publik tetap seperti sebelumnya.
- Kandidat hanya dapat melanjutkan sesi ACTIVE dengan raw ID yang sama, unik,
  dan geometri yang cocok secara mutual. Kandidat tidak dapat membuat atau
  memulihkan sesi LOST. ID tracker tetap merupakan petunjuk, bukan identitas.
- Timer orang tidak menghitung interval strong→weak maupun weak→strong.
  Setelah kembali kuat, interval strong→strong berikutnya baru dihitung.
  Weak tidak memperpanjang usia bukti kuat: default setelah 1 detik tanpa bukti
  kuat sesi menjadi LOST meskipun tracker masih memiliki kandidat.
- Recovery motion/ReID juga menggunakan bukti kuat terakhir sebagai batas umur.
  Audit active ReID memakai policy revision v2. Kandidat tidak masuk crop/gallery.
- Kandidat tidak masuk jumlah orang, overlay measured, kunjungan teramati, atau
  bukti occupied workstation. Total zona tetap mengikuti jalur deteksi publik;
  aturan konfirmasi ulang zona tidak diubah dalam tahap confidence ini.
- Deteksi publik yang masih di bawah ambang bukti kuat diberi
  `evidence_state=WEAK`; jalur live tidak menerbitkan label kunjungan "Di meja"
  dari sampel lemah tersebut. Durasi yang sudah terakumulasi tetap tersimpan.
- Berlaku pada replay lokal dan Pipeline live yang juga digunakan headless.
  Detektor tanpa `tracking_candidates`, termasuk NanoDet, tetap dapat digunakan.
  Pemisahan decoder kandidat ini baru tersedia pada kedua backend YOLOX.

## Konfigurasi dan pembanding

```json
"detection": {
  "confidence": 0.45,
  "tracking_confidence": 0.1,
  "nms_iou": 0.5,
  "detail": false,
  "tile_overlap": 0.5
}
```

`tracking_confidence` harus finite dalam [0.1,confidence]. Nilai sama dengan
threshold publik menonaktifkan kandidat tambahan untuk pembanding. Konfigurasi
lama memperoleh default 0.1. Manifest mencatat kedua threshold, batas kandidat,
dan postprocessing `person-separated-confidence-v3`; run live menyimpan kebijakan
deteksi dalam SQLite.

```powershell
.venv/Scripts/python.exe scripts/diagnose_replay_stability.py --video <video.mp4> --seconds 60 --profiles balanced --reid-mode active --tracking-confidence .45 --calibration <zones.json> --output runtime/confidence-validation/baseline.json
.venv/Scripts/python.exe scripts/diagnose_replay_stability.py --video <video.mp4> --seconds 60 --profiles balanced --reid-mode active --tracking-confidence .1 --calibration <zones.json> --output runtime/confidence-validation/separated.json
```

Gunakan nama output baru pada setiap pengukuran. JPEG yang persis digunakan
disimpan di direktori `*-frames`, sehingga deteksi publik dan snapshot zona
dapat dibandingkan tanpa menganggap jumlah sesi sebagai akurasi identitas.

## Batas hasil

Pemisahan confidence memperbaiki masukan bagi asosiasi tracker; ini tidak
membuat detektor menemukan orang baru pada jalur publik. Evaluasi identitas,
false merge dan error durasi tetap memerlukan label independen. Konfirmasi
ulang zona dan peningkatan model deteksi merupakan tahap terpisah berikutnya.

## Uji video 23 Oktober 2026

`075831.mp4`, 60 detik pertama, 301 JPEG pada 5 FPS, YOLOX OpenVINO GPU dan
ReID retail-0287 CPU active. Kedua pengujian dijalankan berurutan dengan replay
browser dihentikan. SHA256 seluruh JPEG, box/confidence deteksi publik, serta
snapshot workstation pada setiap frame diverifikasi identik.

| Pengukuran | Kandidat tambahan off (0.45) | Kandidat terpisah (0.10) |
| --- | ---: | ---: |
| Sesi dimulai, termasuk provisional | 67 | 56 |
| Sesi dimulai dikurangi recovery | 65 | 53 |
| Kandidat tambahan sepanjang pengujian | 0 | 198 |
| Kandidat tambahan mendapat ID tracker | 0 | 65 |
| Recovery ReID diterapkan | 2 | 3 |
| Frame tanpa deteksi publik | 47 | 47 |
| Durasi zona uji terisi / tidak pasti | 18 / 42 s | 18 / 42 s |
| Median warm per frame, termasuk tracking/ReID | 145.42 ms | 146.48 ms |

Jumlah sesi bukan jumlah orang atau ukuran akurasi identitas. Fragmen masih ada;
coverage workstation tetap 30%. Satu tambahan recovery pada 27.8 detik ditinjau
secara visual sebelum/provisional/sesudah: worker depan tetap berada di tempat,
tanpa pergantian orang yang tampak pada sampel tersebut. Itu bukan label
independen, accepted-match precision, atau pembuktian nol false merge.

Bukti lokal: `runtime/confidence-validation/baseline.json`, `separated.json`,
`comparison.json`, beserta direktori JPEG masing-masing. Angka latency hanya
berlaku pada percobaan lokal ini, bukan jaminan beban multi-kamera. Bobot model,
threshold publik, dan aturan konfirmasi ulang workstation tidak diubah.

Validasi otomatis: 299 tes Python penuh lulus; setelah penandaan bukti publik
lemah diperketat, 78 tes terkait live/sesi/API/ReID juga lulus. Uji HTTP model
nyata mencakup 40 frame dari detik20.0–27.8: 40 kandidat tambahan, 12 mendapat ID
tracker, seluruh respons ReID berstatus ACTIVE, dan jumlah baris accounting
SQLite tidak berubah. Integrity check tetap `ok`. Bukti HTTP berada di
`runtime/confidence-validation/http-verification.json`. Pengujian tersebut
membuktikan jalur eksekusi dan isolasi pencatatan, bukan akurasi identitas.
