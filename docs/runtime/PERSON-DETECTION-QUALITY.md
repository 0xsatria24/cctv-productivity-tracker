# Perbaikan kualitas deteksi orang

YOLOX ONNX dan OpenVINO memakai preprocessing/postprocessing yang sama. Bobot
model tetap sama; perubahan ini tidak memasang model baru atau ReID.

## Perubahan yang aktif secara default

- Capture RTSP mempertahankan sampai 1280 piksel pada sisi terpanjang dan
  921600 piksel total, tanpa memperbesar gambar sumber. Sebelumnya sisi terpanjang
  dibatasi 640. Rasio gambar dipertahankan, termasuk kamera portrait.
- JPEG capture menggunakan kualitas 90, sebelumnya 75. Ini mempertahankan lebih
  banyak detail sebelum analisis, dengan biaya ukuran frame dan encoding lebih besar.
- Decoder menolak output nonfinite, kelas selain orang, box kosong, dan deteksi
  yang hanya jatuh di padding. Letterbox RGB 640 tetap mengikuti model yang dipin.
- Parameter deteksi dan profile dicatat dalam manifest runtime/run. Skor deteksi,
  hasil normalisasi box, dan sumber frame tetap bisa ditelusuri.

Mode biasa (`balanced`) tetap satu inference per frame dan confidence 0.45.
Peningkatan resolusi capture tidak mengubah input model menjadi 1280; model tetap
640. Dampak terhadap akurasi dan kapasitas RTSP nyata masih harus diukur.

## Mode detail

```powershell
.\run-app.ps1 -DetectionProfile detail
```

Jika mesin tidak menyediakan OpenVINO GPU:

```powershell
.\run-app.ps1 -OpenVinoDevice CPU -DetectionProfile detail
```

Mode ini memproses frame penuh dan empat crop bertumpang tindih. Hasil crop
dipetakan kembali ke koordinat gambar asli, lalu digabung. Full frame tetap
digunakan supaya orang besar yang tidak muat dalam crop tidak hilang.

Box dekat tepi internal crop ditolak karena mungkin merupakan tubuh yang
terpotong. Untuk tambahan dari crop, overlap intersection-over-smaller >= 0.6
dengan box full frame yang lolos NMS dianggap ambigu/duplikat dan box full frame
dipertahankan. Global NMS membuang duplikat lainnya. Kebijakan ini konservatif;
orang berbeda yang sangat bertumpang tindih tetap bisa terlewat dan perlu evaluasi.

Detail memakai sampai lima inference per frame; gambar dengan sisi pendek di
bawah 128 piksel tetap satu pass. Mode ini opsional dan tidak otomatis diaktifkan
untuk semua kamera. Jika hasil melewati batas stale-frame, jalur live yang sudah
ada tetap menolak hasil tersebut sebagai bukti. Jangan memperpanjang timer untuk
menutupi inference yang lambat.

## Konfigurasi

Pilot maupun headless menerima bagian opsional berikut; konfigurasi lama tetap
valid. Parameter khusus ini hanya didukung YOLOX, bukan NanoDet.

```json
"detection": {
  "confidence": 0.45,
  "nms_iou": 0.5,
  "detail": false,
  "tile_overlap": 0.5
}
```

`tile_overlap` menerima 0.1 sampai 0.5. Nilainya adalah overlap relatif terhadap
ukuran tile. Confidence dan NMS IoU harus finite dan berada di antara 0 dan 1.
CLI dashboard menyediakan `--detection-profile` dan `--detection-confidence`.
Launcher juga menerima `-DetectionConfidence`, misalnya 0.35 untuk eksperimen
terukur. Menurunkan confidence dapat menambah false positive; nilai default tidak
diturunkan berdasarkan beberapa sampel. Aturan bukti zona dan identitas sesi
tidak dilonggarkan oleh opsi ini.

## Pengukuran lokal 2026-10-23

Perbandingan OpenVINO CPU, bobot yang sama, confidence 0.45, pada 14 JPEG asli:
12 frame dari empat clip factory yang tersedia dan dua gambar kontrol.
Model dihangatkan dahulu. Masing-masing gambar dieksekusi sekali per profil;
angka ini microbenchmark lokal, bukan hasil beban RTSP multi-kamera.

| Metrik | Balanced | Detail |
| --- | ---: | ---: |
| Median detector latency | 109.5 ms | 496.5 ms |
| P95 detector latency | 134.45 ms | 610.4 ms |
| Frame `091346-60.jpg` | 0 deteksi | 1 deteksi |
| Gambar kontrol kantor | 1 deteksi | 1 deteksi |
| Gambar kontrol publik | 2 deteksi | 2 deteksi |

Pemeriksaan visual menunjukkan box tambahan pada worker membungkuk di frame
`091346-60.jpg`. Pada 13 gambar lain jumlah deteksinya tidak berubah. Beberapa
worker yang jauh atau tertutup tetap terlewat. Dataset belum punya ground truth
box yang independen dan lengkap, sehingga precision/recall dan peningkatan
akurasi umum belum dapat disimpulkan. Menambah jumlah box sendiri bukan bukti
peningkatan akurasi.

Hasil lokal dan gambar pembanding berada di
`runtime/detection-quality-final-20261023/results.json`; sampel input yang tidak
beranotasi berada di `runtime/detection-quality-input-20261023/`.

Untuk mengulang pada folder gambar lain, gunakan direktori output baru:

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_person_detection.py PATH_TO_ORIGINAL_IMAGES --output runtime/detection-evaluation-new --device CPU
```

Jangan gunakan gambar yang sudah digambari bounding box sebagai input evaluasi.
Script tidak menulis database, sesi, atau rekaman kamera. Tidak perlu mengubah
migrasi database. `detection_policy` disimpan di manifest masing-masing run.

## Validasi

Tes unit mencakup remapping crop, padding, internal crop seams, deduplikasi tubuh
parsial, output invalid, konfigurasi lama/baru, factory kedua runtime, batas
resolusi capture, dan envelope frame. Tes model nyata membandingkan ONNX dengan
OpenVINO serta memastikan mode detail menghasilkan dua orang pada sampel publik
dan nol orang pada gambar hitam. Tes lifecycle, accounting, API, dan headless
tetap dijalankan untuk mendeteksi regresi.

Referensi kontrak preprocessing model yang dipin:
[OpenCV Zoo YOLOX demo](https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/models/object_detection_yolox/demo.py),
[decoder model](https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/models/object_detection_yolox/yolox.py).
