# Audit perubahan stabilitas replay

Mode after (session override). Cakupan: daftar timer replay, label bukti lemah/
posisi terakhir, visual hold dan kualitas capture. Arah visual mengikuti replay
existing, ENERGY 1 / RHYTHM 1 / MOTION 1; tidak ada komponen dekoratif baru.

- Hard Gate PASS: posisi terakhir memakai garis putus-putus, title dan label
  eksplisit; confidence lama tidak dipresentasikan sebagai deteksi baru. Waktu
  lemah/hold tidak menambah timer. Browser memverifikasi import, putar, deteksi,
  urutan sesi ACTIVE, serta tidak adanya horizontal overflow pada viewport uji.
- Purpose Gate PASS: perubahan garis diperlukan untuk membedakan pengukuran
  sekarang dari posisi lama; warna dan tipografi memakai token existing.
- Liveliness PASS: video nyata tetap menjadi fokus. Status dan urutan timer
  mengikuti observasi terbaru, tanpa animasi atau angka identitas buatan.
- Craftsmanship PASS: 232 tes backend, 19 tes frontend dan build Vite lulus.
  Tes memeriksa weak evidence tidak mengisi timer, stale/seek tidak memakai
  posisi lama, serta expiry memperhitungkan latency dan playback rate.

Tidak ada temuan UI baru dalam cakupan ini. Ini bukan audit ulang semua halaman,
theme atau perangkat. Batas model nyata tetap didokumentasikan, termasuk 27
frame tanpa deteksi pada cuplikan uji dan ReID yang masih shadow.

Bukti: `runtime/reid-stability/replay-after.png` dan
`docs/runtime/REPLAY-STABILITY.md`.
