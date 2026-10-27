# Integrasi ReID aktif dan hasil pengujian

`npm.cmd run dev:reid` sekarang mengaktifkan penerapan recovery appearance pada
replay. Kode live/accounting juga mempunyai appearance gate aktif, dengan syarat
gerak tetap ketat dan audit transaksi. Launcher bukan validasi produksi.

Validasi akhir: 244 tes backend dan 19 tes frontend lulus; build Vite berhasil.
Server lokal `http://localhost:5174/#/live` sudah direstart dalam mode aktif.
Tes HTTP server pada 60 frame bagian detik 30 sampai 41,8 juga menghasilkan
status ACTIVE di semua frame dan 2 recovery yang diterapkan, tanpa accounting
rekaman replay. Bukti: `runtime/reid-active/http-active-verification.json`.
UI menampilkan active eksperimental dan tidak memiliki horizontal overflow pada
viewport browser yang diperiksa; screenshot `runtime/reid-active/active-ui.png`.

Database demo dibackup sebelum migrasi dari versi 4 ke 5 di
`runtime/reid-demo/dashboard-before-reid-v5-984789aa.sqlite3`. Database versi 5
sesudah restart menghasilkan `PRAGMA integrity_check = ok`.

## Yang sudah diterapkan

- SessionManager dapat menunda recovery gerak agar keputusan active harus
  melewati appearance matcher. Off dan shadow mempertahankan perilaku sebelumnya.
- PENDING mempertahankan sesi provisional; MATCH memanggil rekonsiliasi sesi,
  memindahkan durasi teramati sekali, memulihkan session_id lama, lalu menghapus
  gallery provisional. Waktu selama hilang tetap nol.
- Gallery memakai minimal dua sampel pendukung dari view/pose yang sesuai;
  satu outlier tidak memadai. Margin dua arah dan one-to-one assignment wajib.
- Policy `motion` untuk accounting. Policy `short_occlusion` hanya untuk replay
  tanpa accounting, dengan scope kamera/file/run/generasi yang sama.
- Audit `reid_decisions` mencatat model/preprocessing hash, input/committed
  mapping version, skor, margin, alasan, serta committed event sequence.
  Sesi dan audit berada dalam satu transaksi; gagal commit tidak memublikasikan
  snapshot atau memperbarui gallery. Embedding dan foto tidak ditulis ke database.
- UI membedakan active eksperimental, shadow, jumlah recovery terkonfirmasi,
  dan timer provisional yang masih menunggu identitas.

## Video nyata: 075831.mp4

Perbandingan 60 detik pertama menggunakan frame identik (301 frame, target
sampling 5 FPS), YOLOX OpenVINO GPU, ReID retail-0287 FP32 CPU. Parameter model
tetap; threshold similarity tidak diturunkan untuk mengejar hasil demonstrasi.

| Pengukuran | Off | Active |
| --- | ---: | ---: |
| Frame tanpa deteksi | 47 | 47 |
| Sesi yang dimulai, termasuk provisional | 67 | 67 |
| Recovery visual diterapkan | 0 | 2 |
| Sesi yang dimulai dikurangi rekonsiliasi | 67 | 65 |
| Median waktu warm per frame | 49,90 ms | 57,62 ms |

Recovery diterapkan pada 33,6 dan 40,6 detik. Review gambar sebelum, provisional
dan sesudah pada kedua kejadian memperlihatkan worker yang tetap berada di area
yang sama; tidak tampak pergantian orang pada dua kejadian itu. Ini review dua
kejadian, bukan accepted-match precision atau pembuktian nol false merge.

Bukti lokal:

- `runtime/reid-active/real-off-60s.json`
- `runtime/reid-active/real-active-consensus-60s.json`
- `runtime/reid-active/recovery-review.png`

Sebagian penolakan benar-benar berasal dari kualitas tampilan: pada contoh
kehilangan singkat, skor per frame turun dari 0,852 menjadi 0,814 dan 0,787 ketika
pose berubah. Maka tiga frame konfirmasi tidak selalu tercapai. Guard kepala
menyentuh batas atas juga diperbaiki agar tidak menyamakan crop tubuh tinggi
dengan keluar kamera; exit yang teramati tetap ditolak.

## Pekerjaan yang belum terbukti

ReID tidak mengembalikan deteksi orang yang tidak dihasilkan detektor. Banyak
fragmen pada semua orang di view tetap ada, terutama saat membungkuk, occlusion,
atau crop kualitas rendah. Identitas orang dengan seragam sama pada lokasi dan
waktu sangat dekat tetap berisiko; threshold ini belum dikalibrasi pada dataset
terpisah. Live RTSP nyata, precision/recall identitas, error durasi terhadap label
manual, re-entry dan lintas kamera belum divalidasi.

Langkah lapangan berikutnya membutuhkan anotasi identitas/durasi per kejadian,
perbandingan detektor yang lebih cocok dengan pose pekerja, serta kalibrasi dan
evaluasi pada kejadian yang terpisah. Menurunkan threshold saja tidak membuktikan
perbaikan dan dapat mencampur timer antarorang.
