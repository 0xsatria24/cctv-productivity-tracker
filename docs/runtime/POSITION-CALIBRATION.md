# Kalibrasi posisi dan zona

Tiga metode tersedia di dialog **Atur zona**, baik untuk webcam maupun RTSP:

| Metode | Penentuan zona | Satuan toleransi |
| --- | --- | --- |
| Overlap kotak | Perbandingan luas kotak orang dengan polygon; perilaku lama | Aturan overlap lama |
| Titik kaki pada gambar | Tengah bawah kotak deteksi berada dalam polygon | Fraksi koordinat gambar 0..1 |
| Titik kaki pada lantai | Anchor dan polygon diproyeksikan ke satu bidang lantai | Meter |

Profil lama tetap memakai overlap kotak. Memilih metode baru tidak mengubah interval atau laporan historis.

## Mengatur homography

1. Hubungkan kamera, berhenti mencatat, lalu buka **Atur zona** untuk membekukan frame tanpa mirror.
2. Pilih **Titik kaki pada lantai (homography)**.
3. Pada **Gambar pada frame**, pilih **Empat sudut lantai**. Pilih empat sudut dari sebuah persegi panjang nyata di satu lantai datar, berurutan mengikuti kelilingnya. Titik 1 menjadi asal (0,0), 2 menjadi (lebar,0), 3 menjadi (lebar,kedalaman), dan 4 menjadi (0,kedalaman). Jangan memakai sudut meja atau titik di ketinggian berbeda.
4. Isi lebar sisi 1 ke 2 dan kedalaman sisi 2 ke 3 berdasarkan pengukuran nyata dalam meter. Tidak ada ukuran lantai contoh yang otomatis diterapkan.
5. Pilih **Batas zona**, gambar polygon pada lantai, beri nama dan simpan zona. Seluruh titik zona harus di dalam empat sudut referensi. Area sempit perlu toleransi batas yang sesuai ukurannya.
6. Simpan kalibrasi, kemudian mulai monitoring. Buka kembali dialog untuk memeriksa konfigurasi tersimpan.

Klik pada frame atau gunakan input X/Y dan **Tambah titik koordinat**. **Urungkan titik** mengikuti sasaran gambar aktif. Mengganti metode tidak langsung menghapus titik referensi dalam draft; saat menyimpan mode selain homography, referensi lantai dibuang dari profil.

## Batas bukti

Anchor adalah perkiraan posisi dari kotak deteksi, bukan keypoint kaki atau pengenalan identitas. Orang duduk, kaki tertutup meja/orang lain, deteksi parsial, dan lensa terdistorsi masih dapat menghasilkan posisi salah. Transformasi ini tidak mengoreksi distorsi lensa dan tidak mendeteksi kamera bergeser secara otomatis. Kalibrasikan ulang setelah kamera bergerak, zoom, crop, atau susunan area berubah.

Posisi dalam pita toleransi batas, area yang tumpang tindih dalam satu exclusive group, dan confidence rendah menghasilkan `UNKNOWN` untuk zona terkait. Kotak yang menyentuh 0.995 tinggi gambar dianggap berisiko kaki terpotong. Proyeksi tidak diekstrapolasi ke luar segiempat lantai; bila posisi tidak tersedia, zona yang beririsan dengan kotak dibuat tidak pasti. Deteksi lain yang jelas di zona tetap membuktikan `OCCUPIED`, tetapi jumlah orang menjadi tidak pasti. Ini tidak menghilangkan false negative dari detector.

Asosiasi agregat zona dan timer zona sesi menggunakan fungsi yang sama. Tidak ada tambahan durasi zona selama posisi ambigu. Debounce dan batas gap tetap berlaku. Keberadaan di zona bukan bukti produktivitas atau identitas karyawan.

## Konfigurasi dan audit

Profil kalibrasi live menerima field opsional `position`:

```json
{
  "mode": "homography",
  "image_points": [[0.2, 0.1], [0.8, 0.1], [1, 0.9], [0, 0.9]],
  "floor_width_m": 6,
  "floor_depth_m": 8,
  "image_boundary_margin": 0.01,
  "floor_boundary_margin_m": 0.1
}
```

Angka di atas hanya fixture geometri. Konfigurasi headless melalui API kalibrasi mendukung field yang sama. Untuk replay/pipeline dari file konfigurasi, letakkan `position` di root settings. Semua polygon tetap memakai koordinat gambar ternormalisasi, sehingga overlay lama tetap cocok.

Backend menolak titik berpotongan, cekung, kolinear, tidak finite, area referensi terlalu kecil, dimensi tidak valid, dan zona di luar lantai. Matriks dihitung di server dari empat pasangan titik, bukan diterima dari klien. Dimensi/referensi/toleransi menjadi bagian manifest run dan hash rule set; perubahan menghasilkan revisi konfigurasi zona baru.

Hasil deteksi pipeline menyertakan `position.anchor`, `floor_m`, `available`, `reason`, `method` dan `estimated`. Proyeksi meter hanya tersedia dalam mode homography untuk anchor yang valid. Informasi ini tidak menentukan identitas sesi.

Dasar pemetaan bidang: [OpenCV homography tutorial](https://docs.opencv.org/4.1.0/d9/dab/tutorial_homography.html). Empat titik yang pas kembali ke referensinya hanya membuktikan transformasi matematis; ketepatan lapangan tetap perlu diuji dengan titik lantai lain yang diukur secara independen.

## Verifikasi

`tests/test_positioning.py` memeriksa pemetaan perspektif terhadap OpenCV, penolakan input buruk, toleransi meter, zona ambigu, kaki terpotong, penyimpanan profil/API, revisi audit, serta kesamaan timer sesi dan agregat. Fixture ini tidak mengukur akurasi CCTV nyata.

Panel diuji dengan webcam sintetis melalui:

```powershell
cd prototype
npm.cmd run build
npx.cmd playwright test --config playwright.calibration.config.js
```

Server browser memakai port 8877 dan database uji terpisah di `runtime/calibration-browser-test.sqlite3`, bukan konfigurasi kamera operasional.
