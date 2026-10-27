# Perbaikan kalibrasi area dan timer replay

## Sumber masalah yang ditemukan

1. Frontend `newTimeline()` mengosongkan tabel timer pada setiap event seek, loop dan simpan kalibrasi.
2. Backend mengganti `WorkstationTimeline` saat generation berubah dan setiap configure, termasuk kiriman tanpa perubahan.
3. Hasil hanya disimpan dalam memori, sedangkan file yang dipilih ulang mendapat UUID baru. Restart dan impor ulang memulai hasil kosong.
4. Editor lama menampilkan pilihan teknis dan koordinat untuk setiap titik sekaligus. Belum ada drag sudut atau cara sederhana menggambar kotak.

## Perilaku sekarang

- Editor area menyediakan tarik kotak, drag sudut, tombol panah, urungkan, daftar area dan nama. ArUco dan koordinat angka dilipat sebagai opsi.
- Gambar dan editor memakai rasio serta koordinat sumber yang sama. Koordinat dibatasi pada gambar. Save ditolak jika bentuk tidak valid.
- Total area bertahan melewati seek dan loop. Ledger interval media menghindari penghitungan ganda; interval yang dilompati tidak dibebankan sebagai waktu terisi.
- Mengirim kalibrasi identik tidak menaikkan revisi atau membuang hasil. Rename mempertahankan hasil. Batas berubah mengarsipkan versi sebelumnya; area lain tetap utuh.
- UUID replay disimpan untuk metadata file pada browser. Checkpoint area ditulis atomik di `replay-state`, terpisah dari accounting produksi. Restore memvalidasi total terhadap cakupan interval. Check-in identitas selalu perlu dikonfirmasi ulang setelah seek/restart.
- Hasil lama yang belum pernah masuk checkpoint tidak dipulihkan secara fiktif. Cakupan deteksi yang lemah tetap dapat membuat timer terisi berhenti sementara; itu dibedakan dari reset total.

## Verifikasi

- 339 tes backend lulus, termasuk replay interval yang sama, seek ke depan, kirim ulang konfigurasi, rename, pengarsipan bentuk lama, restart, checkpoint rusak, dan disk penuh. Laporan: `runtime/area-consistency-tests.xml`.
- 31 tes frontend lulus, termasuk retry pemulihan saat checkpoint sedang memegang lock. Build produksi dan pemeriksaan whitespace lulus.
- Browser: tambah area dengan drag kotak, drag sudut, keyboard, undo, hapus area sementara, dan simpan tanpa perubahan. UI diperiksa pada viewport sekitar 970 x 600. Screenshot: `runtime/area-consistency/editor.png`.
- Browser pada rekaman asli: total terisi 00:00:34 bertahan saat pause, seek mundur, simpan tanpa perubahan, dan reload lalu pilih ulang file yang sama. Bukti: `runtime/area-consistency/browser-timer-check.json`. Durasi tersimpan server pada uji tersebut adalah 34.602.500 mikrodetik.

Data lapangan belum berlabel; tidak ada klaim peningkatan akurasi okupansi dari perubahan UI dan penyimpanan ini.
