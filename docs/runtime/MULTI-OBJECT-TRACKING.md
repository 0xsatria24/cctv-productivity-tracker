# Multi-object tracking satu kamera

Implementasi memakai ByteTrack dari `supervision==0.26.1` yang sudah dipin oleh
project. Tidak memasang tracker kedua atau model ReID. Perubahan aktif pada
pipeline terintegrasi, replay, dan headless setelah aplikasi dimulai ulang.

## Perubahan

### Langkah gerak mengikuti jeda antar-observasi

Sebelumnya adapter menambah umur frame ByteTrack untuk elapsed time, tetapi
Kalman filter hanya memprediksi satu langkah setiap panggilan. Orang bergerak
dapat keluar dari prediksi ketika inference melambat, meskipun gap masih dalam
batas bukti yang didukung.

Adapter sekarang memajukan prediksi internal dan umur track bersama-sama untuk
langkah waktu yang terlewat. Pecahan langkah dibawa ke update berikutnya agar
cadence seperti 0.3 detik pada target 5 FPS tidak terus kehilangan setengah tick.
Tetap ada minimal satu update backend per observasi nyata. Ini adaptasi discrete
ByteTrack terhadap cadence, bukan estimator continuous-time baru.

Tidak ada pemanggilan update dengan deteksi kosong buatan. Deteksi kosong hanya
dikirim jika hasil pengamatan aktual memang kosong. Prediksi internal tidak
dikembalikan sebagai box orang atau ditulis sebagai bukti kehadiran.

Prediksi tambahan dibatasi oleh `max_prediction_steps`. Jika dibutuhkan pekerjaan
di atas batas, tracker direset dan epoch ID dinaikkan. Evidence gap dan pergantian
generasi juga tetap mereset tracker. SessionManager memiliki aturan recovery
sendiri dan tidak otomatis mewarisi ID raw yang baru.

### Binding ke box terukur

Setiap input deteksi memiliki `source_index` dalam `Detections.data`. ByteTrack
mengembalikan subset deteksi dengan metadata tersebut. Adapter memetakan ID
melalui indeks, bukan mencari ulang box berdasarkan kesamaan float.

Box dan confidence output tetap berasal dari deteksi input yang sama; urutan
output tracker dan perubahan box internal tidak menjadi bukti baru. Indeks atau
ID duplikat pada hasil binding ditolak pada kedua sisi. Raw ID yang sudah ada pada
input tidak dipercaya jika backend tidak memberikan binding yang sah.

Penggabungan ID raw dengan kamera/generasi dan epoch tetap dipertahankan, sehingga
reset ByteTrack tidak menghidupkan kembali kunci ID lama. `session_id` tetap
menjadi identitas kontinuitas aplikasi yang terpisah dari ID raw.

### Retensi dan sesi lemah

Lost track yang melewati buffer dibuang sebelum association, bukan menunggu
cleanup backend setelah matching. Buffer dinyatakan dalam detik dan dikonversi
ke tick sesuai cadence konfigurasi. Buffer tidak memberi hak menyambung orang
yang keluar kamera atau melewati batas recovery sesi.

Deteksi di bawah `rules.strong_confidence` tidak lagi membuat sesi baru setiap
frame. ByteTrack masih boleh memakai deteksi lemah untuk association raw sesuai
algoritmanya, tetapi ini bukan bukti identitas atau durasi. Deteksi tetap dapat
ditampilkan sebagai `UNASSIGNED`; aturan zona tetap memberi UNKNOWN jika hanya
ada bukti lemah. Continuity/recovery sesi tidak dilonggarkan untuk mengejar raw ID.

## Konfigurasi

Bagian opsional berikut tersedia pada config pilot dan headless. Config lama
tetap menggunakan default yang sama untuk threshold ByteTrack.

```json
"tracking": {
  "activation_threshold": 0.25,
  "matching_threshold": 0.8,
  "lost_buffer_seconds": 1.0,
  "confirmation_frames": 1,
  "max_prediction_steps": 30
}
```

- `activation_threshold`: threshold pembagian confidence di ByteTrack. Backend
  memakai threshold tambahan `activation_threshold + 0.1` untuk memulai track.
- `matching_threshold`: batas biaya association backend; ini bukan probabilitas
  kecocokan identitas orang. Kalibrasi dengan rekaman berlabel sebelum mengubahnya.
- `lost_buffer_seconds`: retensi raw lost track; default 1 detik, bukan retensi
  sesi aplikasi 10 detik. Batas evidence gap tetap berlaku secara terpisah.
- `confirmation_frames`: konfirmasi raw track; tidak mengubah konfirmasi zona.
- `max_prediction_steps`: batas langkah per observasi, termasuk langkah backend
  aktual; rentang valid 1 sampai 120.

Untuk mengambil config khusus dengan aplikasi terintegrasi:

```powershell
.\.venv\Scripts\python.exe -m cctv_tracker --config config/pilot.example.json dashboard --openvino-device CPU
```

Threshold detektor tetap terpisah. Jika detektor sudah membuang box berconfidence
rendah, ByteTrack tidak bisa memakai box itu untuk tahap association keduanya.
Menurunkan threshold harus diuji terhadap false positive, bukan dilakukan
otomatis oleh tracking.

## Diagnostik dan persistence

Snapshot pipeline menambahkan objek `tracking`: jumlah deteksi terukur, binding
matched/unmatched, track confirmed/tentative/lost, extra prediction steps,
binding yang ditolak, lost track yang expired, epoch, dan alasan reset.
Jika sumber unavailable, snapshot menyatakan `available=false` dan alasan
gangguannya, sehingga statistik frame sebelumnya tidak terlihat sebagai data baru.

Kebijakan `tracking_policy` disimpan pada manifest masing-masing engine run.
Tidak ada migrasi database baru. Upsert sesi, timer, mapping dan checkpoint tetap
atomik. Snapshot dan overlay tetap mengikuti token frame/run/mapping yang sudah ada.

## Pengujian yang bisa diulang

```powershell
.\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider --basetemp runtime/mot-tests-new
.\.venv\Scripts\python.exe scripts/validate_multi_object_tracking.py --output runtime/mot-check-new
```

Validator membandingkan adapter dari `HEAD:src/cctv_tracker/vision.py` dengan
working tree menggunakan versi ByteTrack yang sama. Baseline harus diperiksa
kembali jika HEAD sudah berisi perbaikan ini.

Untuk smoke replay video lokal dengan database evaluasi terpisah:

```powershell
.\.venv\Scripts\python.exe scripts/validate_multi_object_tracking.py --output runtime/mot-video-new --video PATH_TO_VIDEO.mp4 --max-video-frames 40
```

Smoke replay memakai OpenVINO CPU, sample tiap 0.5 detik media PTS, dan zona uji
seluruh gambar yang belum dikalibrasi. Script tidak memakai kamera fisik atau
database produksi. Frame beranotasi dan JSON disimpan di direktori output baru.

## Hasil lokal 2026-10-23

Pada fixture dua orang bergerak, urutan waktu 0, 0.2, 0.4, 0.6, 0.8, 1.6, 1.8,
dan 2 detik, adapter baseline kehilangan binding pada kedua orang setelah gap
0.8 detik dan membuat ID raw baru. Adapter baru mempertahankan ID masing-masing:

| Metrik fixture | Baseline | Baru |
| --- | ---: | ---: |
| Deteksi terukur | 16 | 16 |
| Deteksi dengan binding raw | 14 | 16 |
| Jumlah ID raw orang A | 2 | 1 |
| Jumlah ID raw orang B | 2 | 1 |
| Penggabungan raw lintas label | 0 | 0 |

Tes crowd juga memeriksa 32 box terukur selama 12 frame dengan urutan input
dibalik-balik: setiap box harus mempunyai ID unik dan stabil. Tes sesi yang sudah
ada tetap menguji crossing, occlusion, pergantian ID, penggantian orang di posisi
sama, kamera offline, stale frame, dan rollback.

Smoke replay pertama pada 40 sampel `090455.mp4` berhasil, SQLite integrity `ok`,
dan menghasilkan 13 sesi berbeda. Angka sesi tersebut belum bisa diartikan
sebagai jumlah worker; deteksi yang terputus dan recovery konservatif masih
dapat memecah sesi. File belum memiliki ground truth identitas yang lengkap.
Hasil ini bukan validasi akurasi identitas pabrik atau jaminan kapasitas 32 orang
pada kamera nyata. ReID dan evaluasi video berlabel masih diperlukan untuk
menangani identitas yang ambigu.

Rujukan algoritma:
[ByteTrack paper](https://arxiv.org/abs/2110.06864) dan
[dokumentasi Supervision 0.26.1](https://supervision.roboflow.com/0.26.1/trackers/).
