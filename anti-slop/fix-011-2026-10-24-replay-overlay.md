# Replay: waktu, gerak box dan label track

Mode during dipilih user pada chat ini. Perubahan berada di D:\Projects\cctv 2.
Arah mengikuti DESIGN_SYSTEM.md: konsol CCTV padat, surface solid, angka tabular,
video sebagai fokus. ENERGY 1 / RHYTHM 1 / MOTION 1. Gerak overlay melayani
pembacaan posisi objek; tidak menambah animasi dekoratif atau aset visual.

Durasi observasi kembali tampil pada label box. Baris pertama memisahkan track
sementara T(epoch.nomor) dari sesi timer S; perubahan sesi tetap terlihat dan
tidak disamarkan sebagai identitas orang yang sudah terkonfirmasi. Waktu video
ditampilkan di sudut frame, termasuk saat dijeda. Ini elapsed media time, bukan
tanggal/jam perekaman yang tidak tersedia dari file.

Renderer mengikuti requestVideoFrameCallback, dengan requestAnimationFrame
sebagai fallback. Perubahan posisi diperhalus dengan konstanta 55 ms waktu media;
estimasi gerak dibatasi 150 ms, kecepatan 0,8 ukuran box per detik, dan batas
frame. Prediksi gerak dinonaktifkan saat box bertumpuk atau kontinuitas geometry
tidak memadai. Estimasi memakai garis putus-putus dan label. Data durasi dan
identitas tetap berasal dari server.

Setiap box kedaluwarsa sendiri paling lambat 400 ms waktu media sejak bukti
terakhir. Sebelumnya expiry satu held box menghapus seluruh packet overlay.
Held box tidak lagi menghapus box orang lain yang masih baru. Seek, generasi
baru, pause dan perubahan sesi tidak mewarisi gerak atau waktu sesi lama.
Target sampling menjadi 5 frame per detik media dan menyesuaikan playback rate;
jumlah frame aktual tetap dibatasi waktu inferensi.

Validasi yang dijalankan:

- Frontend: 26 tes lulus dan build Vite berhasil. Meliputi expiry per orang,
  response lag, playback rate, gerak antarpaket, batas frame, overlap, seek,
  generasi dan raw track sama dengan sesi timer berbeda.
- Backend: 50 tes replay tracking, MOT dan workstation lulus dalam 24,28 detik.
- Inferensi nyata: 12 detik pertama 075831.mp4, 61 frame pada 5 FPS media,
  YOLOX OpenVINO GPU + ReID aktif, 27 frame tanpa deteksi, 3 sesi dibuat,
  median warm 117,01 ms. Ini eksekusi model saat ini, bukan pengukuran akurasi
  identitas atau perbandingan peningkatan detektor.
- Browser: fixture sintetis memakai komponen ReplayOverlay yang sama. Enam belas
  pembacaan DOM berturut-turut menunjukkan perubahan koordinat dengan ID tetap;
  durasi tidak ditambah renderer. Hilangkan orang kedua mempertahankan orang
  pertama; pause memberi nol box; bukti terputus memberi nol box setelah expiry.
- Kontrol fixture yang diperiksa: putar/jeda, seek awal, kecepatan 0,5x/1x/2x,
  putus/pulihkan bukti, hilangkan/kembalikan orang kedua. Keyboard Tab memfokuskan
  Seek awal dengan outline solid, Enter menjalankannya. Reload bersih sesudah
  perbaikan HMR fixture menghasilkan nol error/warning console baru.
- Desktop: scrollWidth 1265 <= viewport 1280. Mobile: 390 <= 390; ukuran SVG
  mengikuti viewport sehingga label tampil sekitar 12 px. Screenshot diperiksa.

Browser tidak mengimpor video nyata: izin pemilihan file pada percobaan sebelumnya
ditolak. Fixture memakai geometry sintetis saja dan tidak memilih/mengirim file
pengguna. Uji video nyata dilakukan offline melalui script diagnosis Python.
Jalur callback decoder native pada video HTML nyata dan akurasi ID kamera live
belum divalidasi dalam uji browser ini. Fragmentasi sesi ketika bukti detektor
hilang tetap ada; smoothing tidak mengubah aturan recovery atau accounting.

Delivery Gate untuk cakupan renderer:

- Hard Gate PASS: build, 26 tes frontend, 50 tes backend, fixture browser,
  expiry/empty/pause states dan viewport diperiksa; data sintetis diberi label.
  Tidak ada kontrol produk baru atau klaim akurasi yang dibuat.
- Purpose Gate PASS: label opaque dengan text.primary pada surface.video
  menjaga keterbacaan; angka tabular membandingkan waktu; garis putus-putus
  menunjukkan estimasi. Label/clock memakai token dan font existing.
- Liveliness PASS: ENERGY 1 / RHYTHM 1 / MOTION 1; video tetap fokus, accent
  existing menandai box, gerak hanya mengikuti objek, tanpa dekorasi tambahan.
- Craftsmanship PASS: timer tidak diinterpolasi, sesi tidak digabung renderer,
  box stale terhapus per orang, kontrol fixture dan keyboard berjalan, hasil
  aktual dan batas validasi dibedakan secara eksplisit.

Bukti lokal:

- runtime/replay-smooth-20261024/real-active.json
- runtime/replay-smooth-20261024/browser-samples.json
- runtime/replay-smooth-20261024/renderer-desktop.png
- runtime/replay-smooth-20261024/renderer-mobile.png
- prototype/verification/replay-overlay-fixture.html
