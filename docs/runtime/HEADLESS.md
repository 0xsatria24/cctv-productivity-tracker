# CCTV Headless Engine

Edisi tambahan untuk integrasi VMS/NVR tanpa ketergantungan Node.js, browser, Qt atau server UI terpisah. Halaman bantuan koneksi opsional disajikan langsung oleh API; engine tetap berjalan tanpa browser. Dashboard Enterprise tetap memakai alur lama. Kedua edisi memanggil `cctv_tracker.engine`: detector ONNX/OpenVINO, `LiveController`, RTSP capture, ByteTrack, pipeline occupancy dan SQLite yang sama. Headless memiliki controller/detector per kamera agar inferensi dan state tracking tidak saling berebut. Kapasitas nyata bergantung RAM, CPU/GPU dan model; jumlah pada lisensi bukan jaminan throughput.

## Cara paling mudah untuk client

Administrator memasang Python/runtime sekali dengan `install.ps1` dari ZIP, mengisi lokasi model di `config.json`, dan menyediakan `license.json` serta `vendor-public.pem` di samping launcher. File tersebut diperlukan sebelum client menjalankan aplikasi; launcher tidak menerbitkan lisensi sendiri.

1. Klik dua kali **Start Headless.cmd**. Launcher membaca konfigurasi dan token yang tersedia; jika belum ada, membuat token acak pada `token.txt`. Jika engine sudah aktif dengan token tersebut, launcher memakai proses yang ada.
2. Buka **http://127.0.0.1:8766/**. Halaman ini sekarang menampilkan petunjuk, bukan error Not Found.
3. Klik **Pilih file token**, pilih `token.txt` yang lokasinya ditampilkan launcher. Status langsung diperiksa tanpa mengetik PowerShell.
4. Daftarkan kamera atau gunakan panel **Coba API** untuk mencoba endpoint. **Unduh OpenAPI** menyediakan kontrak untuk integrator.

Pada workspace pengembangan ini, launcher otomatis memakai `runtime/headless-local/` jika konfigurasi lokal tersedia. Token lokal ada di `runtime/headless-local/token.txt`. Token hanya berada di memori halaman, tidak disimpan di localStorage/cookie dan tidak dimasukkan ke URL. Refresh halaman memerlukan autentikasi ulang. Halaman bantuan publik tidak mengungkap status kamera, lisensi atau token; semua data API tetap memerlukan autentikasi. Semua aset halaman disertakan lokal, tanpa CDN/internet.

## Menjalankan

Python 3.12 diperlukan. Gunakan virtual environment terpisah dari Enterprise. Dari ZIP rilis, jalankan `./install.ps1`, isi `config.json`, lalu:

```powershell
$env:CCTV_HEADLESS_TOKEN = '<token acak minimal 32 karakter>'
./run.ps1 -License C:/ProgramData/CCTV/license.json -PublicKey C:/ProgramData/CCTV/vendor-public.pem
```

Dari source repository, pasang `requirements.headless.lock.txt` dengan `pip install --no-deps -r requirements.headless.lock.txt`, lalu `pip install --no-deps -e .`. Jalankan:

```powershell
./run-headless.ps1 -License C:/ProgramData/CCTV/license.json -PublicKey C:/ProgramData/CCTV/vendor-public.pem
# Atau:
python -m editions.headless --config config/headless.example.json --license license.json --public-key vendor-public.pem
# Enterprise tetap dapat dijalankan:
python -m editions.enterprise --detector yolox
```

Default API: `http://127.0.0.1:8766`, satu worker. Reverse proxy TLS diperlukan untuk integrasi dari mesin lain. Token hanya lewat header `Authorization: Bearer ...`; tidak melalui query string atau cookie. Proses berjalan di foreground tanpa GUI dan dapat dikelola service supervisor. Pada Windows, gunakan service wrapper yang menangani stop dengan graceful shutdown; menambahkan scheduled task saja bukan implementasi Windows Service SCM. Pada Linux gunakan supervisor/systemd dengan direktori kerja, environment token, dan `ExecStart=.../python -m editions.headless ...`; lock runtime disediakan untuk Windows, dependency lock rilis ini ditujukan ke Windows/Python 3.12.

Tidak ada model yang diunduh otomatis. Isi `model_path` dengan lokasi absolut model YOLOX/NanoDet yang cocok dengan checksum adapter. `detector`: `yolox`, `nanodet`, atau `yolox-openvino`; `device`: `CPU`/`GPU` untuk OpenVINO. Paket baseline memakai ONNX CPU. OpenVINO opsional dipasang terpisah dari versi yang digunakan Enterprise (`openvino==2026.4.1`, `openvino-telemetry==2025.2.0`). Gunakan script benchmark yang ada sebelum memilih perangkat; tidak ada fallback perangkat diam-diam.

Data default: `%LOCALAPPDATA%/CCTVTracker/headless`. Gunakan `data_dir` absolut pada disk lokal untuk service account. Satu proses memiliki lock direktori data. Tiap camera ID memakai database terpisah; kalibrasi dan event bertahan setelah restart. URL kamera dari API hanya disimpan di memori: untuk registrasi setelah restart, masukkan kamera ke konfigurasi atau registrasikan kembali dari integrator. Jangan mengubah camera ID jika ingin melanjutkan histori yang sama. Penghapusan registrasi tidak menghapus histori. Lindungi konfigurasi karena URL RTSP dapat memuat kredensial.

Contoh konfigurasi kamera setelah kalibrasi tersimpan:

```json
{"detector":"yolox","model_path":"C:/CCTV/models/webcam-yolox.onnx","port":8766,
 "cameras":[{"camera_id":"lobby","url":"rtsp://camera.local/stream","autostart":true}]}
```

## Integrasi

Semua REST endpoint berada di `/api/v1`. OpenAPI terautentikasi tersedia pada `/api/v1/openapi.json`; salinan statis ada di `docs/runtime/headless-openapi.json` atau `openapi.json` pada ZIP.

| Metode/path | Fungsi |
|---|---|
| GET `/status` | Edisi, batas kamera, state dan capability |
| GET/POST `/cameras` | Daftar / registrasi `{camera_id,url}` |
| GET/DELETE `/cameras/{id}` | State / hentikan lalu hapus registrasi |
| PUT `/cameras/{id}/analytics` | Simpan kalibrasi saat sesi berhenti |
| POST `/cameras/{id}/start` | Mulai inference + pencatatan |
| POST `/cameras/{id}/start?preview_only=true` | Inference tanpa pencatatan, untuk inspeksi awal |
| POST `/cameras/{id}/stop` | Stop asinkron; poll status sampai STOPPED |
| GET `/cameras/{id}/events?after=0&limit=100` | Event committed dengan cursor per kamera |
| WebSocket `/stream` | Snapshot metadata kamera/deteksi terbaru, maksimal 5 Hz |

Camera ID: huruf kecil di awal, diikuti huruf kecil/angka/underscore/hyphen, maksimal 40 karakter. Respons registrasi menyediakan `camera_key` untuk mengikat kalibrasi ke stream. Kalibrasi:

```json
{"width":640,"height":480,"camera_key":"<hash dari respons registrasi>",
 "zones":[{"id":"desk1","name":"Desk 1","polygon":[[0,0],[1,0],[1,1],[0,1]],"exclusive_group":"desks"}],
 "rules":{"occupied_confirm_seconds":2,"empty_confirm_seconds":5,"max_evidence_gap_seconds":3}}
```

Lebar/tinggi harus sesuai rasio frame; koordinat polygon dinormalisasi 0–1. Jalankan preview dulu bila diperlukan. GET events mengembalikan `items` dan `next_cursor`; `payload_json` mengikuti payload event engine. Deduplicasi memakai `event_id`. WebSocket merupakan snapshot best-effort; gunakan REST cursor untuk pemulihan event setelah disconnect. Python SDK stdlib tersedia di `sdk/python/headless_client.py`:

```python
import os
from headless_client import HeadlessClient
client = HeadlessClient(os.environ['CCTV_HEADLESS_TOKEN'])
camera = client.add_camera('lobby', 'rtsp://camera.local/stream')
print(camera['camera_key'])
# client.calibrate('lobby', profile)
# client.start('lobby')
print(client.events('lobby', after=0))
```

Webhook opsional: set `webhook_url` HTTPS di konfigurasi dan `CCTV_WEBHOOK_SECRET` minimal 32 karakter pada environment. Setiap event committed dikirim sebagai JSON. Verifikasi HMAC-SHA256 atas byte body terhadap header `X-CCTV-Signature: sha256=...`. Header `X-CCTV-Event-ID` dipakai untuk deduplikasi. Tidak mengikuti redirect. Cursor tersimpan setelah respons 2xx; gagal/timeout dicoba kembali setiap siklus (2 detik, timeout 5 detik). At-least-once, bukan exactly-once. Satu tujuan webhook per proses; tujuan lambat menunda pengiriman berikutnya, tidak memblokir inference. Untuk mengganti tujuan, tentukan apakah cursor lama dilanjutkan atau reset secara administratif.

## Lisensi offline

Startup wajib memverifikasi signature Ed25519. Format envelope:

```json
{"payload":"<base64 dari byte JSON payload>","signature":"<base64 signature Ed25519 atas byte payload>"}
```

Payload ditandatangani penerbit, contoh: `{"edition":"headless","api_enabled":true,"max_cameras":16,"expires_at":"2027-10-14T00:00:00Z"}`. Public key PEM milik vendor dipasang oleh administrator, dengan ACL yang mencegah service account/pengguna mengubah key, executable atau konfigurasi peluncuran. Private key tidak disertakan. Tidak ada mode bypass/dev license pada CLI. JSON konfigurasi kamera tidak mengubah entitlement. Signature diperiksa saat startup; expiry diperiksa pada request dan background monitor yang menghentikan kamera ketika kedaluwarsa. Perubahan file lisensi memerlukan restart. Ini verifikasi offline, bukan perlindungan terhadap administrator yang memodifikasi program atau memundurkan jam sistem. Lisensi Enterprise lama tidak diubah oleh penambahan edisi ini.

## Paket dan batas validasi

`python scripts/build_editions.py` menghasilkan ZIP Enterprise dan Headless terpisah di `dist/editions/`. Keduanya dibangun dari sumber engine yang sama. Headless wheel mengecualikan modul dashboard/API UI/CLI lama/camera wall dan tidak membawa frontend. Enterprise ZIP membawa hasil build `prototype/dist` yang tersedia; build ulang frontend sebelum membuat rilis produksi. Model dan lisensi tidak disertakan dalam kedua ZIP.

`supervision==0.26.1` mendeklarasikan `opencv-python` walaupun tracking dapat berjalan memakai `opencv-python-headless`. Karena keduanya menyediakan modul `cv2`, installer headless memakai lock runtime eksplisit dan `--no-deps`, mengganti OpenCV dengan varian headless. Jangan memasang extra `vision` atau menjalankan resolver biasa untuk supervision pada environment ini: itu akan menarik OpenCV GUI. `pip check` dapat melaporkan kebutuhan metadata `opencv-python` dari supervision; jangan memperbaikinya dengan memasang kedua varian cv2. Matplotlib (dependensi supervision) memakai backend `Agg` pada entry point headless.

ONVIF discovery dan RTSP output terproses belum diimplementasikan; capability API menyatakan false. Tidak ada uji kamera fisik atau jaminan kapasitas 16 kamera. Pengujian multi-kamera memakai transport/detector sintetis dengan pipeline tracking/accounting nyata; pengujian model yang tersedia tetap dijalankan oleh suite existing. Kesiapan produksi, installer service OS native, hardening lisensi Enterprise, dan acceptance perangkat target memerlukan validasi lanjutan.
