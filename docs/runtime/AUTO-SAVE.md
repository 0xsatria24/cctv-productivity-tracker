# Auto-save laporan dan rekaman video

18 Oktober 2026. Pengaturan ini berlaku untuk dashboard Python/React (Enterprise). Edisi Headless tidak berubah.

## Cara memakai

1. Buka **Pengaturan → Auto-save data dan video**.
2. Aktifkan **Auto-save laporan data**, **Auto-save rekaman video**, atau keduanya. Default keduanya nonaktif.
3. Pilih interval data dan durasi potongan video secara terpisah: 5–3600 detik atau 1–60 menit. Satuan menit membulatkan nilai detik ke menit terdekat, minimal satu menit; nilai akhirnya terlihat sebelum disimpan.
4. Interval dan satuan tetap dapat diubah saat auto-save nonaktif. Tentukan batas folder record, lalu klik **Simpan pengaturan auto-save**. Tombol tetap tersedia meskipun nilai belum berubah. Baris **Pengaturan tersimpan** menunjukkan nilai yang benar-benar diterima backend; perubahan draft baru berlaku setelah disimpan. Pengaturan tetap berlaku setelah restart.
5. File yang selesai tersedia di tabel **File tersimpan**, dengan filter, pagination, dan tautan unduh. Tabel menampilkan 50 entri terbaru; seluruh file tetap berada di folder yang ditampilkan. **Salin lokasi folder** menyalin path untuk dibuka di Explorer.

Menonaktifkan auto-save laporan menghentikan ekspor file berikutnya. Menonaktifkan rekaman video menyelesaikan potongan yang sedang terbuka. Pencatatan transaksi observasi di SQLite tetap berjalan selama sesi analisis aktif, terlepas dari opsi ekspor ini.

## Isi dan kualitas

- **Data:** JSON berisi metadata kamera, zona waktu, run, watermark committed, ringkasan durasi dan interval; CSV berisi ringkasan durasi workstation. Ekspor mengambil snapshot transaksi konsisten dari sesi terbaru masing-masing kamera, termasuk webcam/sesi RTSP utama. Nilai kumulatif sesi bukan delta yang boleh dijumlahkan antarfile. Tidak ada file baru jika watermark tidak berubah. Kamera yang hanya menayangkan preview belum menghasilkan laporan analisis.
- **Video:** H.264 MP4, tanpa audio dan tanpa overlay analisis, dari frame monitoring yang sudah tersedia. Capture preview RTSP membatasi sisi terpanjang sekitar 640 px dan sekitar 4 FPS; webcam mengirim frame analisis hingga sekitar 5 FPS pada sisi terpanjang 640 px. Ini rekaman preview, belum arsip stream asli NVR/full resolution. Timestamp video mengikuti waktu capture, bukan jumlah frame buatan. Frame stale tidak diulang untuk mengisi koneksi putus; potongan ditutup setelah gap lebih dari dua detik. Metadata mencatat jumlah frame, ukuran, waktu, dan gap.
- Video RTSP untuk kamera terdaftar tetap menerima subscription dari layanan record ketika opsi aktif, termasuk kamera preview tanpa kalibrasi. Analisis kamera tidak otomatis dimulai. Rekaman dapat berlanjut saat pindah halaman atau menutup browser selama backend aktif.
- Webcam tetap memerlukan browser mengirim frame dan izin kamera. Menutup browser atau kehilangan frame menghentikan input. Kecepatan inference/jaringan/browser memengaruhi FPS aktual; ini belum recorder independen dari jalur inference.

## Penyimpanan dan kegagalan

Folder: sibling database bernama `<database-stem>-records`. Default batas folder 5120 MB; rentang konfigurasi 512–1048576 MB. Kapasitas diperiksa sebelum penulisan, dengan pemeriksaan total ukuran berkala dua detik. Saat batas tercapai atau disk tersisa kurang dari 256 MB, penulisan record dihentikan dan error tampil di Pengaturan. Video yang masih terbuka diselesaikan jika disk mengizinkan. Batas dapat terlampaui sedikit oleh buffer/finalisasi file; ini bukan disk quota OS. File lama tidak dihapus otomatis. Pindahkan/hapus file lewat Explorer atau tingkatkan batas untuk melanjutkan.

Frame hanya ditahan satu per sumber; encoding dan ekspor berjalan di worker terpisah agar kegagalan record tidak menghentikan accounting. MP4 sedang ditulis bernama `.partial.mp4` dan tidak dapat diunduh dari API sampai finalisasi berhasil. Crash/power loss dapat meninggalkan partial yang perlu diperiksa manual; aplikasi menampilkan jumlahnya. Tidak ada klaim recovery otomatis untuk video terputus.

Backup database menyertakan kebijakan auto-save dan konfigurasi tujuan yang terenkripsi, bukan file CSV/JSON ekspor, katalog/antrean record, atau video. Kredensial rclone eksternal dikelola terpisah. Restore backup lama yang belum memiliki kebijakan menonaktifkan kedua opsi. Salin folder record secara terpisah jika dibutuhkan. Folder `*-records/` diabaikan Git.

## API lokal

- `GET /pilot/v1/recordings`: kebijakan, lokasi folder, status, error, dan 50 file terbaru.
- `POST /pilot/v1/recordings/policy`: seluruh objek konfigurasi, autentikasi dan pemeriksaan Origin sama seperti perubahan lain.
- `GET /pilot/v1/recordings/files/{id}/{json|csv|mp4}`: unduh file final melalui ID allowlist; tidak menerima path filesystem.

```json
{"data_enabled":true,"data_interval_seconds":30,"video_enabled":true,"video_segment_seconds":60,"max_storage_mb":5120}
```

Validasi otomatis mencakup MP4 yang benar-benar didecode, timestamp/frame berubah, rotasi, sumber stale, on/off, persistensi, batas disk, isi laporan committed, autentikasi, dan alur browser. Pengujian memakai input kamera sintetis; kapasitas recorder banyak kamera di perangkat pelanggan masih perlu benchmark.

Perbaikan kontrol: error saat menyimpan tetap terlihat meskipun polling status berhasil, draft tidak dihapus setelah kegagalan, dan pengguna dapat mencoba Simpan kembali. Label on/off menampilkan status draft beserta penanda belum disimpan. Uji regresi mencakup kondisi awal off dan kegagalan backend yang diikuti retry.


## Tujuan cloud dan server lokal

Buka **Pengaturan → Tujuan penyimpanan auto-save**. Pilih tujuan, isi koneksi, aktifkan **Kirim file otomatis**, lalu **Simpan tujuan penyimpanan**. Ini berlaku untuk ekspor laporan dan potongan video. File lokal tetap tersedia sebagai staging dan sumber download. Memilih cloud tidak mengubah sumber database SQLite ke jaringan.

| Tujuan | Konfigurasi |
| --- | --- |
| Lokal aplikasi | Default; tidak mengirim file ke layanan lain |
| Folder/server/NAS | Path absolut atau UNC, misalnya `D:\CCTV-Archive` atau `\\NAS\CCTV`. Akses memakai akun OS yang menjalankan backend. Untuk Windows Service, gunakan UNC karena mapped drive interaktif dapat tidak tersedia. |
| Cloud / SFTP / WebDAV via rclone | Remote bernama yang dibuat lewat `rclone config`; mencakup provider yang mendukung penulisan di [daftar backend rclone](https://rclone.org/overview/). Google Drive, OneDrive, Dropbox, Azure, GCS, dan provider lain mempunyai alur login/izin masing-masing. Dukungan bukan jaminan seluruh layanan cloud tanpa konfigurasi. |
| S3 compatible / MinIO | Endpoint, bucket yang sudah ada, region/provider, access key, secret key, dan session token opsional. AWS dapat memakai endpoint kosong. Region Cloudflare R2 umumnya `auto`; ikuti konfigurasi provider. |

### Memasang dan menghubungkan cloud

Runtime ini memakai helper rclone v1.75.2 yang diunduh dari sumber resmi dan diverifikasi SHA256. Untuk instalasi baru dari source:

```powershell
.\.venv\Scripts\python.exe scripts/setup_storage_transport.py
& .\runtime\tools\rclone\rclone.exe config
```

Atau pasang rclone di PATH. `CCTV_RCLONE_PATH` dapat menunjuk executable tepercaya. Paket Enterprise memasukkan helper di `tools/` jika tersedia saat build. Konfigurasi custom memakai environment rclone standar seperti `RCLONE_CONFIG`.

1. Jalankan perintah **Salin perintah setup cloud** di terminal dengan akun OS yang sama dengan backend.
2. Tambahkan remote, pilih provider, dan selesaikan login/otorisasi. Gunakan fitur enkripsi konfigurasi rclone jika diperlukan. File OAuth/config rclone dikelola oleh rclone; aplikasi tidak mengklaim mengenkripsinya dengan DPAPI.
3. Klik **Perbarui daftar cloud** di dashboard, isi nama remote dan subfolder, lalu simpan.
4. **Uji koneksi tujuan** membuat satu file bernama unik, memverifikasi ukuran/checksum yang didukung, lalu menghapus file uji tersebut. Hasil uji tidak mengunggah rekaman CCTV. Pengujian folder dapat meninggalkan folder tujuan yang kosong.

Kredensial S3 yang dimasukkan langsung di dashboard dienkripsi memakai DPAPI CurrentUser pada Windows atau private-key Fernet pada Unix. GET/status hanya menampilkan flag sudah dikonfigurasi, tidak mengembalikan access key, secret key, atau session token. Nilai kosong mempertahankan kredensial untuk koneksi yang sama. Mengubah endpoint/bucket/region/provider membutuhkan kredensial kembali. Rotasi key baru tidak mewarisi session token lama secara otomatis. Kredensial dikirim ke proses helper melalui environment, bukan command line atau log.

### Antrean dan batas operasional

File baru yang telah final masuk antrean SQLite terpisah. Laporan terdiri dari JSON, CSV, dan metadata; video terdiri dari MP4 dan metadata. Worker transfer tidak memegang lock encoding/accounting ketika melakukan I/O jaringan. Nama tujuan memakai UUID record sehingga retry idempotent. File `.partial.mp4`, database, dan file kredensial tidak diunggah.

- Koneksi gagal: backoff 5 detik sampai 5 menit, maksimal delapan percobaan per file, lalu tampil **Gagal**. **Coba ulang upload gagal** mengaktifkan antrean gagal pada tujuan saat ini.
- Restart: antrean tersimpan; pekerjaan yang terputus dicoba ulang.
- Tujuan berubah: antrean lama tetap terikat ke konfigurasi sebelumnya dan tidak dialihkan diam-diam. Rotasi kredensial dianggap konfigurasi baru. **Antrekan 50 file terbaru** dapat mengirim kembali file yang masih ada ke tujuan saat ini; ini tindakan eksplisit, bukan upload seluruh histori otomatis.
- Pengiriman dimatikan: tidak ada pekerjaan baru yang diambil. Satu transfer yang sudah berjalan dapat selesai. File lokal tidak dihapus otomatis setelah upload.
- Folder/NAS: copy menggunakan file sementara, fsync, verifikasi SHA256 dan rename. Gangguan SMB mengikuti timeout OS; worker transfer berada di luar jalur capture/accounting.
- Cloud: [rclone copyto](https://rclone.org/commands/rclone_copyto/) memakai checksum jika didukung backend, lalu aplikasi memeriksa ukuran objek lewat `lsjson --stat`. Ini tidak menjanjikan checksum SHA256 remote pada semua provider. Tidak ada bucket ACL publik yang dibuat dan tidak ada sync/purge direktori tujuan.
- Kuota lokal tetap berlaku saat offline. Tidak ada janji buffering tanpa batas; ekspor/recording berhenti jika folder penuh, sementara data accounting tetap mengikuti transaksi engine.

Konfigurasi tujuan ikut backup dalam bentuk terenkripsi, tetapi rclone.conf, OAuth token eksternal, antrean transfer dan arsip file tidak ikut backup database. Backup lama tanpa konfigurasi tujuan mengembalikan pengiriman ke lokal/nonaktif.

API tambahan: `GET/POST /pilot/v1/recordings/destination`, `POST .../test`, `GET .../remotes`, `POST .../retry`, dan `POST .../enqueue-recent`. Semua endpoint memakai autentikasi/Origin yang sama dengan auto-save.

Validasi memakai salinan folder aktual, remote alias rclone aktual, server S3 milik test di loopback, dan uji browser yang membandingkan file JSON/CSV/MP4 tujuan dengan sumber. Belum ada kredensial akun cloud pengguna atau NAS fisik yang diberikan, sehingga koneksi ke akun/perangkat tersebut belum diuji.
