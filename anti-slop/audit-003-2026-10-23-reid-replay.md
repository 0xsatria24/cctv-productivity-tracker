# Audit tambahan status ReID replay

Mode: after, pilihan pengguna pada sesi ini. Cakupan: status koneksi ReID,
status per frame di replay, dan launcher npm untuk menjalankan model lokal.
Tampilan mengikuti komponen/caption replay yang sudah ada, tanpa perubahan CSS
atau aset visual. Bukan audit ulang keseluruhan dashboard.

Design read: status operasional untuk pengguna CCTV, mengikuti tampilan replay
yang ada; ENERGY 1 / RHYTHM 1 / MOTION 1. Status diletakkan di bawah hasil deteksi
agar pengguna bisa membedakan deteksi, ekstraksi ciri, dan keputusan timer.

## Delivery gate pada tambahan ini

- Hard Gate PASS: browser menampilkan mode shadow dan penjelasan bahwa pencocokan
  belum mengubah timer; tidak ada angka akurasi atau data orang buatan. Warna
  caption rgb(162,173,186) di atas rgb(27,32,39) menghasilkan kontras 7.19:1.
  Tidak ada horizontal overflow pada viewport browser yang diuji. Import video,
  centang deteksi preview, perubahan kecepatan, dan putar diuji melalui UI.
- Purpose Gate PASS: memakai caption yang sama dengan hasil deteksi; tidak
  menambah gradient, badge, ikon, animasi, atau struktur navigasi baru.
- Liveliness PASS: focal point tetap video pabrik asli; status ReID mengikuti
  frame yang diproses dan menampilkan gallery nyata. Dials mengikuti UI existing.
- Craftsmanship PASS: build Vite berhasil; 49 tes ReID/replay dan 12 tes API/
  dashboard lulus. Gallery antarfile terisolasi, seek membersihkan bukti lama,
  hasil stale tidak menjalankan ekstraksi. Ini memverifikasi tambahan fitur,
  bukan klaim kelulusan semua layout/theme/perangkat dashboard.

## Bukti runtime

- `npm.cmd run dev:reid` menjalankan Vite 5174 dan engine Python 8770.
- Browser `http://localhost:5174/#/live` menampilkan video 075831.mp4 dan status
  ReID shadow. Hostname localhost memisahkan cookie dari engine lama 127.0.0.1.
- Model retail-0287 FP32 diunduh dari storage resmi OpenVINO; ukuran dan SHA-384
  XML/BIN cocok dengan metadata Open Model Zoo, SHA-256 ditulis ke manifest lokal.
- API replay memproses 20 frame video asli, seluruhnya SHADOW; gallery maksimum
  2 sesi, empat crop ditolak karena confidence rendah, tanpa error provider.
- Laporan: `runtime/reid-demo/verification.json`.
- Screenshot: `runtime/reid-demo/replay-ui.png`.
- Tidak ada temuan baru dalam cakupan tambahan ini. Evaluasi akurasi identitas
  dan audit tampilan di semua perangkat belum dilakukan.
