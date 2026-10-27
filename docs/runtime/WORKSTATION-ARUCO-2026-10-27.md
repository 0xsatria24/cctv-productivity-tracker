# Workstation area + check-in ArUco

## Cara menjalankan

Klik `Jalankan CCTV.cmd`, atau jalankan `npm.cmd run dev:workstation` dari folder `prototype`. Halaman: http://127.0.0.1:5174/#/live. Launcher memakai database pilot terpisah di `runtime/workstation-demo` dan ReID nonaktif.

1. Masukkan video replay. Mode awal adalah **Workstation + check-in ArUco**.
2. Buka **Atur area**. Klik **Tambah area**, tarik kotak di gambar, lalu geser bulatan sudut untuk merapikan batas. Beri nama area dan klik **Simpan area**. Koordinat angka tersedia hanya di Pengaturan lanjutan.
3. Bila ingin identitas check-in, buka **Kenali pekerja dengan marker (opsional)** dan tambah marker dengan ID 0–49 dan nama/kode pemilik. Kamus tetap **DICT_4X4_50**. Unduh PNG dari formulir, cetak datar dengan tepi putih utuh, dan uji ukuran pada kamera asli. Template lokal juga tersedia di `runtime/aruco-workstation/aruco-4x4-50-7.png`.
4. Terapkan zona, aktifkan **Deteksi preview**, lalu putar video. Video berjalan terpisah dari analisis, yang mengambil maksimal dua sampel per detik video.
5. Tunjukkan marker di depan tubuh dalam zona. Check-in memerlukan tiga pembacaan konsisten selama minimal 0,4 detik, zona terkonfirmasi terisi satu orang, dan pusat marker dapat dikaitkan dengan tepat satu deteksi tubuh berkualitas cukup.
6. **Unduh durasi CSV** menyimpan total sesi per area. Nama pada CSV adalah check-in terakhir, bukan pemilik seluruh durasi area.

## Arti timer dan nama

- Terisi, kosong dan tidak pasti dihitung berdasarkan waktu video, tanpa pengali jumlah orang dan tanpa bergantung ID tracker.
- Pergantian orang atau marker tidak mereset total area. Bukti lemah, perubahan status yang belum terkonfirmasi, dan jeda pengamatan masuk waktu tidak pasti.
- Marker yang hilang tidak membuat area kosong. Nama check-in terakhir tetap ditampilkan sebagai pendaftaran sebelumnya; verifikasi marker ditampilkan terpisah.
- Marker ganda, ID yang belum terdaftar, area ambigu, lebih dari satu orang, atau marker di luar deteksi tubuh tidak mengonfirmasi identitas.
- Area terkonfirmasi kosong menghapus pendaftaran. Marker yang terkonfirmasi pada area lain memindahkan pendaftaran, tanpa menduplikasinya.
- Pause membekukan hasil. Seek dan putar ulang mempertahankan total; interval waktu video yang sudah dianalisis tidak dihitung dua kali. Waktu yang dilompati saat seek tidak diklaim sebagai waktu terisi.
- Simpan tanpa perubahan dan mengubah nama mempertahankan timer. Perubahan batas area atau cara pengaitan membuat versi baru untuk area yang terdampak; hasil versi lama masuk Riwayat area dan CSV.
- Hasil area dicatat sebagai checkpoint lokal di folder `replay-state` di samping database pilot. Checkpoint ditulis berkala sekitar dua detik, saat pause dan saat engine berhenti dengan normal. Kegagalan penyimpanan ditampilkan; CSV tetap tersedia. Pemadaman mendadak masih dapat menghilangkan sampel sejak checkpoint terakhir.
- Pilih ulang file yang sama pada browser dan alamat aplikasi yang sama untuk memuat hasil. Kunci file memakai nama, ukuran dan waktu modifikasi; mengubah metadata file atau menggunakan browser lain membuat sesi terpisah. File video tetap dipilih manual setelah refresh. Data lama sebelum fitur checkpoint tidak dapat direkonstruksi otomatis.
- Mode tracking orang lama tetap tersedia sebagai pilihan eksperimental. Mode area melewati ByteTrack, sesi per orang, dan ReID.

## Hasil verifikasi

- 334 tes backend lulus; 28 tes frontend lulus; build produksi dan `git diff --check` lulus.
- PNG ID 0, 7 dan 49 dibaca ulang dengan decoder OpenCV asli. PNG terhalang tidak dipakai sebagai pembacaan valid.
- Endpoint diuji dengan JPEG marker hasil generator dan deteksi orang yang dikontrol oleh tes: check-in, penolakan identitas ambigu, penggantian marker, area kosong, seek, autentikasi, dan isolasi dari accounting produksi.
- Browser diuji pada video pengguna `075831.mp4`: membuat zona dan registry, menerapkan kalibrasi, playback, pause, marker download dan CSV download. Rekaman itu tidak memiliki marker, sehingga tidak diberi nama pekerja secara otomatis.
- CSV hasil uji: `runtime/aruco-workstation/browser-export.csv`. Pada zona uji dan segmen yang diamati: 86,1993 detik terisi, 41,8295 detik kosong, 102,4931 detik tidak pasti; cakupan sekitar 55,5%. Zona ini hanya untuk demonstrasi, belum divalidasi sebagai batas workstation sebenarnya.
- Laporan tes: `runtime/aruco-workstation/tests-final.xml`.

## Batas penggunaan saat ini

Implementasi ini merupakan pilot replay lokal. Belum ada validasi badge fisik pada jarak, sudut, pencahayaan dan kompresi kamera lokasi; belum ada klaim akurasi identitas atau FPS kamera yang terukur. Kehadiran di area tidak membuktikan aktivitas kerja. Check-in marker mengidentifikasi label yang didaftarkan untuk marker dan tidak membuktikan pemakainya terus berada di sana.

Untuk pemakaian live yang dicatat sebagai laporan produksi, konfigurasi kamera, penyimpanan check-in dan validasi lapangan perlu diintegrasikan tersendiri; fitur replay ini tetap terisolasi dari accounting produksi.
