# Timer tracking pada video replay

Replay memakai detektor engine yang terhubung, adapter ByteTrack, dan
`SessionManager` yang sama dengan jalur tracking aplikasi. Setiap file memiliki
registry sesi tersendiri di RAM. Replay tidak menjalankan pipeline database,
kalibrasi zona, atau accounting live.

Timer `HH:MM:SS` pada box menunjukkan akumulasi waktu orang teramati berdasarkan
posisi media, bukan lamanya permintaan inferensi atau jam komputer. Pause tidak
mereset sesi dan perubahan kecepatan tidak mengalikan durasi. Waktu hilang tidak
ditambahkan. UI menyimpan durasi terakhir ketika overlay dibersihkan atau video
dijeda. Label sesi yang sedang dicocokkan ditampilkan sebagai pencocokan, bukan
timer milik orang lama yang belum terbukti.

Pemulihan memakai aturan konservatif `SessionRules`: bawaan menyimpan sesi LOST
selama 10 detik media, dengan jendela pemulihan gerak 3,5 detik dan minimal tiga
observasi konfirmasi. Raw track ID boleh berubah; sesi aplikasi dan durasi lama
dipulihkan jika lintasan cocok secara unik. Orang diam yang hilang, pergantian
orang pada posisi sama, keluar dari tepi frame, crossing ambigu, dan kehilangan
terlalu lama dapat menghasilkan sesi baru. Belum ada appearance ReID pada jalur
ini. Jangan menafsirkan retensi LOST sebagai jaminan mengenali orang yang keluar
dan masuk kamera kembali.

## Envelope frame

`POST /pilot/v1/replay/frame` menerima JPEG dengan autentikasi dan pemeriksaan
Origin yang sama seperti sebelumnya. Klien tracking mengirim semua header:

- `X-Replay-Id`: UUID file pada workspace browser.
- `X-Replay-Generation`: bilangan naik ketika seek, reset, atau loop ke awal.
- `X-Replay-Sequence`: nomor permintaan yang terus naik untuk file tersebut.
- `X-Replay-Time`: posisi frame pada video dalam detik.

Respons mengembalikan envelope, `session_id`, `accumulated_duration_us`, daftar
sesi ACTIVE/LOST, `tracking_supported=true`, dan
`duration_basis=observed_media_time`. Selalu `source=LOCAL_VIDEO_REPLAY`,
`recorded=false`, dan `duration_accounting=false`, termasuk bila permintaan
membawa header sesi live. Klien lama tanpa envelope masih mendapat deteksi
stateless dengan `tracking_supported=false`.

Urutan duplikat, generasi lama, dan waktu mundur pada generasi sama ditolak 409
sebelum inferensi. Envelope rusak ditolak 422. Seek/reset/loop sengaja membuat
sesi baru karena pengamatan pada dua bagian timeline tidak membuktikan
kontinuitas. Klien membersihkan hasil pada pause/hide dan memeriksa envelope
sebelum menggambar hasil; balasan lama tidak boleh menimpa timeline baru.

Registry dibatasi 64 file, masing-masing mengikuti batas sesi/history pada
konfigurasi. Frame paralel pada satu file mendapat 429, tanpa mengganti sesi.
File yang tidak mengirim frame selama 30 menit dibersihkan ketika permintaan
berikutnya tiba. Sesi tidak bertahan setelah engine dimulai ulang, refresh
browser, file dihapus/dimasukkan ulang, atau eviksi idle tersebut. Saat kapasitas
terisi sesi yang masih aktif, server menolak file baru, bukan menghapus timer
file lain secara diam-diam.

## Validasi lokal

`tests/test_replay_tracking.py` memeriksa 15 detik teramati, hilang 3 detik,
pemulihan dengan raw ID baru, dan durasi akhir 15,2 detik. Waktu hilang tidak
dihitung dan waktu kandidat hanya ditambahkan sekali. Fixture juga mencakup
isolasi file, seek, penolakan frame lama, pengganti diam yang tidak mewarisi timer,
batas kapasitas, serta envelope tidak valid.

Tes API pada `tests/test_webcam.py` memastikan sesi berlanjut, konflik ditolak,
dan database accounting tidak dibuat. Hasil fixture tidak merupakan pengukuran
akurasi pemulihan identitas pada rekaman lapangan.
