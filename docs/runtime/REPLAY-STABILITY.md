# Replay box dan kontinuitas timer

Catatan: halaman ini merekam perbaikan tahap sebelumnya. ReID kini juga memiliki
mode active; status dan hasil terbaru ada di [REID-ACTIVE-RESULTS.md](REID-ACTIVE-RESULTS.md).

Perubahan 23 Oktober 2026:

- Replay mengizinkan deteksi yang confidence-nya turun sedikit untuk melanjutkan
  sesi ACTIVE yang sudah ada, hanya jika ID tracker masih sama dan unik, serta
  geometry dan mutual-best margin lolos. Ini tidak membuat sesi baru atau
  memulihkan sesi LOST dari bukti lemah.
- Durasi hanya bertambah antara dua observasi kuat yang berurutan. Frame lemah,
  termasuk interval sebelum/sesudahnya, tidak menambah durasi. Bukti lemah tidak
  memperpanjang identitas tanpa batas: batas evidence gap tetap mengikuti waktu
  observasi kuat terakhir. Jalur live memakai kebijakan lama secara default.
- Box terakhir dapat ditampilkan maksimal 0,4 detik waktu media, dengan garis
  putus-putus dan label posisi terakhir. Ini bukan deteksi/prediksi kehadiran
  baru. Box tidak dimasukkan ke SessionManager atau akuntansi, timer dibekukan.
  Posisi lama tidak ditampilkan di tepi keluar, melintasi seek/generasi baru,
  atau bertumpuk dengan deteksi orang baru. Latency respons dan playback rate
  ikut mengurangi sisa waktu tampil.
- `detections`/`count` API tetap berisi pengukuran detektor; overlay memakai
  `display_detections` dengan field `measured` dan `evidence_state` terpisah.
- Daftar timer menampilkan sesi ACTIVE lebih dahulu, kemudian sesi LOST terbaru.
  Sesi lama tidak lagi mendesak timer orang yang sedang terlihat keluar layar.
- Capture browser mempertahankan detail hingga sisi terpanjang 960 piksel,
  JPEG quality 0,9, tetap di bawah batas ukuran JPEG endpoint.

## Pengukuran video nyata

Script `scripts/diagnose_replay_stability.py` memakai frame yang sama dari
075831.mp4, 12 detik pertama, sampling 5 FPS, OpenVINO GPU. Ini pengukuran
keluaran detektor/fragmentasi sesi, bukan accepted-match precision atau akurasi
identitas karena belum ada anotasi orang manual.

| Profil / kebijakan | Frame | Frame tanpa deteksi | Sesi dibuat | Median warm |
| --- | ---: | ---: | ---: | ---: |
| Balanced sebelum | 61 | 27 | 6 | 73,38 ms |
| Detail sebelum | 61 | 26 | 7 | 365,01 ms |
| Balanced threshold 0,3 sebelum | 61 | 24 | 6 | 72,71 ms |
| Balanced sesudah | 61 | 27 | 5 | 63,90 ms |

Median antar-run dapat terpengaruh warmup/beban GPU; perubahan sesi bukan klaim
peningkatan akurasi identitas. Dua frame confidence lemah mempertahankan sesi
tanpa menambah timer sesudah perubahan. Mode detail dan threshold 0,3 tidak
dipromosikan ke default karena hasil ini tidak membuktikan manfaat yang cukup.

Bukti JSON tersedia di `runtime/reid-stability/baseline.json`,
`low-confidence-baseline.json`, dan `after.json`; screenshot UI sesudah perubahan
di `runtime/reid-stability/replay-after.png`.

## Batas yang masih ada

Detektor tetap melewatkan orang dalam 27 frame pada cuplikan uji. Visual hold
tidak menyelesaikan occlusion panjang, pose membungkuk, atau recall model yang
rendah. Jika bukti identitas hilang, sesi baru masih dapat dibuat daripada
memindahkan timer antarorang tanpa dasar. ReID tetap shadow dan belum menerima
recovery visual secara aktif. Seek/ulang memang memulai sesi baru; pause
menyembunyikan overlay dan membekukan waktu video.

Validasi: 232 tes backend, 19 tes frontend, dan build Vite lulus. Browser nyata
menampilkan sesi ACTIVE berdurasi 6 detik sebagai baris pertama meskipun masih
ada beberapa fragmen LOST; tidak ada horizontal overflow pada viewport uji.
