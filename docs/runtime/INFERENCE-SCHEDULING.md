# Penjadwalan inference multi-kamera

Scheduler membagi satu detector/model resident antar-sumber. Headless sebelumnya membuat satu detector per kamera; sekarang semua LiveController dalam satu EngineService memakai giliran pada scheduler yang sama. Tracker, sesi, kalibrasi, capture dan database tetap milik masing-masing kamera.

Dashboard memakai mekanisme yang sama untuk sesi live, preview webcam, dan setiap UUID replay. Sumber RTSP preview pada camera wall tetap hanya capture; perubahan ini tidak mengaktifkan analitik pada seluruh tile. Dashboard masih mendukung satu sesi pencatatan live aktif, sedangkan headless mendukung beberapa kamera yang mencatat bersamaan sesuai batas lisensi.

## Cara kerja

1. Sumber baru meminta giliran. Setiap sumber hanya boleh punya satu permintaan yang menunggu **atau** aktif. Permintaan tambahan untuk sumber yang sama ditolak, sehingga kamera cepat tidak dapat memenuhi antrean.
2. Sumber yang sudah siap dipilih FIFO. Sumber yang menunggu slot FPS dilewati sementara, sehingga tidak menahan sumber lain yang siap. Kamera yang belum mengirim frame tidak memegang giliran model.
3. Detector hanya dipanggil oleh satu sumber pada suatu waktu. Antrean memiliki batas jumlah sumber dan waktu tunggu; tidak membuat worker/model tambahan saat beban naik.
4. Setelah mendapat giliran RTSP, controller membaca ulang mailbox capture nonblocking dan memilih frame lebih baru. JPEG, timestamp dan generation dipindahkan bersama. Frame lama tidak dipakai hanya karena sudah lama mengantre.
5. Umur frame diperiksa sebelum dan sesudah inference. Frame terlalu tua, timestamp yang belum maju, penghentian sesi, dan pembatalan scheduler tidak menghasilkan bukti pencatatan. Timeout/busy menghasilkan error yang dapat dicoba kembali, bukan daftar deteksi kosong.
6. Pipeline mempertahankan perilaku gap: kamera yang tidak punya bukti baru menjadi `UNKNOWN`; durasi tidak diisi dengan prediksi atau observasi kosong buatan.

Batas FPS adalah batas atas per sumber, bukan jaminan FPS tercapai. Lane kamera headless/live mengikuti `Settings.inference_fps` (default 5). Preview webcam dan tiap replay dibatasi 5 panggilan/detik. Warmup kamera menggunakan lane yang sama sehingga ikut memakai anggaran panggilan. Bila inference sendiri lebih lambat, sumber mendapat FPS lebih rendah dan keadaan stale tetap terlihat.

Callback refresh hanya digunakan untuk capture RTSP. JPEG webcam sudah terikat pada permintaan HTTP dan nomor urutnya, sehingga tidak diganti dengan JPEG dari permintaan lain. Replay tetap memakai UUID, generation, sequence dan waktu media; tidak menulis laporan live.

## Konfigurasi

Field berikut opsional. Settings lama tetap dapat dimuat tanpa perubahan:

```json
"scheduling": {
  "queue_capacity": 64,
  "max_streams": 128,
  "max_wait_seconds": 2
}
```

- `queue_capacity`: maksimum sumber yang menunggu, di luar satu sumber aktif; 1..256.
- `max_streams`: maksimum entri metrik sumber yang diingat, minimal queue_capacity dan maksimal 1024. Entri sumber tidak aktif dapat dikeluarkan saat penuh; sumber aktif/menunggu tidak dikeluarkan.
- `max_wait_seconds`: batas menunggu giliran, lebih dari nol dan maksimal 30 detik. Ini **bukan** batas eksekusi native detector.

Pada dashboard, letakkan `scheduling` di settings JSON. Headless menerima field yang sama di file konfigurasinya. Contoh tersedia di config/pilot.example.json, resource pilot bawaan, dan config/headless.example.json. Tidak ada migrasi SQLite baru. Kebijakan scheduling disertakan dalam runtime manifest setiap run baru.

Restart proses engine untuk memakai kode/konfigurasi baru. Mengubah JSON saat engine sedang berjalan tidak mengubah scheduler yang sudah dibuat.

## Diagnostik

Endpoint terautentikasi berikut menyertakan `scheduler`:

- Dashboard `GET /pilot/v1/status`: snapshot global semua sumber.
- Live `GET /pilot/v1/live`: metrik lane sesi live beserta ringkasan antrean global.
- Headless `GET /api/v1/status`: snapshot global dan status kamera. Status tiap kamera hanya menyertakan lane kamera itu, sehingga payload tidak menggandakan seluruh daftar sumber untuk setiap kamera.

Field global: `policy=fifo-per-source`, `closed`, `active_source`, `pending`, batas kapasitas, `high_water`, `completed`, `failed`, `rejected`, `expired`, `cancelled`, dan `refreshed`. Metrik per sumber memuat queue/service time terakhir dan usia completion terakhir. ID sumber hanya berisi ID kamera/UUID replay, bukan URL atau kredensial RTSP.

Hasil inference juga menyertakan `scheduler.source_id`, `queue_ms`, `service_ms`, dan `policy`. Metadata ini tidak menentukan identitas track atau sesi.

`completed` menghitung panggilan model yang selesai, termasuk warmup atau panggilan yang hasilnya kemudian kedaluwarsa/dibatalkan. Angka ini bukan jumlah frame yang masuk accounting. `expired` mencakup batas waktu antrean dan umur frame; satu panggilan dapat tercatat completed sekaligus expired. Gunakan `live.processed` dan checkpoint committed untuk pencatatan. `failed` adalah exception detector; `refreshed` adalah pergantian ke frame RTSP yang lebih baru setelah mendapat giliran.

Shutdown menolak permintaan baru, membangunkan peminta yang mengantre dan menolak hasil dari sesi yang sudah berhenti. Penutupan satu kamera tidak menutup model bersama yang masih dipakai kamera lain.

## Batas implementasi

Pembagian ini mengatasi perebutan model, antrean dari kamera cepat, dan capture kamera yang lambat. Semua sumber masih berbagi kapasitas CPU/GPU yang sama. Tidak ada batching, prioritas live di atas replay, atau deteksi otomatis kapasitas maksimum kamera.

Scheduler tidak memutus native inference yang hang. Peminta lain memiliki batas waktu antrean, tetapi model baru mendapat giliran berikutnya setelah panggilan aktif berakhir. Isolasi proses native dengan kill/restart bukan bagian implementasi ini; jangan menganggap deadline antrean sebagai proteksi hang GPU. Ini juga bukan validasi operasi 24 jam.

## Verifikasi 23 Oktober 2026

Regresi akhir: **189 passed**, tiga warning deprecation dependency. Laporan mesin: runtime/scheduling-validation-20261023/tests.xml. Contoh settings pilot/resource bawaan juga berhasil dimuat dengan SchedulingRules default.

`tests/test_inference_scheduling.py` menguji FIFO per sumber, flood rejection, batas antrean, timeout, cooldown FPS tanpa menahan kamera lain, refresh setelah giliran, umur frame, pembatalan, kegagalan detector, dan batas memori metrik. Integrasi menjalankan empat controller dengan capture sintetis: tiga tetap mencatat saat satu sumber berhenti mengirim frame, hanya satu detector dibuat, sesi tidak tercampur, dan sumber macet tidak membuat interval EMPTY palsu. Permintaan API replay/webcam bersamaan juga melewati scheduler yang sama dan tetap tidak masuk laporan live.

Smoke test menggunakan dua JPEG rekaman pabrik yang sudah ada sebagai empat sumber file, enam panggilan per sumber. Ini bukan empat kamera RTSP nyata dan tidak menulis durasi:

| Runtime | Selesai / gagal | Median queue | Median service | FPS agregat selama uji |
| --- | --- | --- | --- | --- |
| OpenVINO GPU | 24 / 0 | 164 ms | 54.5 ms | 16.49 |
| ONNX CPU, pengulangan tanpa regresi paralel | 24 / 0 | 1680 ms | 562 ms | 1.79 |

Angka menunjukkan pembagian sumber berhasil, bukan jaminan 5 FPS per kamera. CPU pada pengukuran ini jelas tidak memenuhi empat sumber masing-masing 5 FPS. Uji file menerima umur frame maksimal 3 detik; RTSP runtime tetap mengikuti batas umur dari konfigurasinya serta refresh sesudah giliran. File bukti ada di runtime/scheduling-validation-20261023/gpu.json dan cpu-alone.json. cpu.json adalah pengukuran awal yang bersamaan dengan tes regresi; jangan gunakan sebagai kapasitas terisolasi.

Untuk mengulang:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_inference_scheduling.py
.venv/Scripts/python.exe scripts/validate_inference_scheduling.py --images runtime/detection-quality-20261023/090455-0.jpg runtime/detection-quality-20261023/090455-30.jpg --streams 4 --samples 6 --detector yolox-openvino --device GPU --output runtime/scheduling-validation-20261023/gpu.json
```

Untuk menentukan kapasitas operasional, ukur kamera/codec/resolusi/profil detector yang akan dipakai, termasuk kondisi banyak orang, jitter jaringan, dan waktu operasi panjang. Kapasitas antrean 64 bukan klaim sanggup menganalisis 64 kamera.
