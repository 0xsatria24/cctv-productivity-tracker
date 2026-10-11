# API Design — Local Engine V1

Versi: 1.0 · 11 Oktober 2026. Kontrak: [OpenAPI 3.1 JSON](api/openapi.json).

## 1. Mengapa API dibutuhkan

GUI dan engine berjalan pada proses berbeda. API menyediakan command/query yang stabil untuk GUI, test tooling, dan future clients. Engine menjadi satu-satunya pemilik database dan runtime CV. GUI tidak membuka SQLite atau mengelola thread inference.

FastAPI/Uvicorn menjalankan satu server worker pada 127.0.0.1 dengan port dinamis yang dipublikasikan melalui per-user instance registry. Tidak ada public listener dalam V1. Local HTTP tetap memakai bearer token random per engine instance; token registry hanya dapat dibaca account pemilik. API tidak membutuhkan internet.

Async route hanya menangani network I/O, queue delegation dan subscriptions. sqlite3/report/inference yang blocking dipindahkan ke worker yang sesuai. Resource initialization/cleanup berada pada lifespan dengan readiness yang eksplisit. [FastAPI concurrency](https://fastapi.tiangolo.com/async/), [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/).

## 2. Konvensi dan batas

Prefix /v1, JSON Content-Type, RFC3339 timestamp wajib offset, interval [start,end), UUID resource/request IDs. POST query tidak memerlukan idempotency karena read-only. Mutation memerlukan Idempotency-Key; update resource memakai If-Match revision.

Request body normal maksimum 64 KiB; JSON unknown keys ditolak. Polygon maksimum 64 points dan wajib simple/nonzero area. Workspace list maksimal 100/query; timeline/page maksimum 500 rows. Nama dan endpoint memiliki length bounds. Jam lokal divalidasi sampai rentang 00:00–23:59 pada application, bukan hanya regex.

Auth token dikirim melalui Authorization header; bukan query parameter. Client native GUI menolak redirect ke host lain. Server tidak mengaktifkan browser CORS, memvalidasi Host dan Origin, dan tidak mengekspos Swagger UI/CDN pada production. Diagnostic OpenAPI tersedia hanya pada authenticated development mode atau artifact lokal.

Pydantic strict validation menghindari coercion yang dapat mengubah makna settings. API error menghapus raw input/credential dari validation output. [Pydantic strict mode](https://pydantic.dev/docs/validation/latest/concepts/strict_mode/).

## 3. Endpoints

| Method/path | Tujuan | Hasil |
|---|---|---|
| GET /v1/system/status | Readiness/provider/durability/degraded reasons | SystemStatus |
| GET /v1/dashboard | Snapshot KPI dan count/presence coverage | Dashboard |
| GET/POST /v1/cameras | List/create kamera | Camera/list |
| GET/PATCH /v1/cameras/{id} | Detail, nama/enabled/FPS | Camera + revision |
| PUT /v1/cameras/{id}/credentials | Simpan username/password pada CredentialStore | Camera; tidak mengembalikan secret |
| POST /v1/cameras/{id}/test-jobs | Connection/decode test | 202 Job |
| GET/POST /v1/workspaces | List/create zona dan config awal | Workspace/list |
| GET/POST /v1/workspaces/{id}/configurations | Riwayat/create revision polygon | Config; pending/applied status |
| GET /v1/workspaces/{id}/timeline | Interval source dengan pagination snapshot | Timeline page |
| GET /v1/rule-sets | Rule preset yang tersedia | ID + settings |
| GET /v1/schedules/current | Kalender aktif | Schedule |
| POST /v1/schedules | Versi jadwal baru | Schedule + revision |
| POST /v1/reports/query | Summary historis dengan precision explicit | ReportPage |
| POST /v1/export-jobs | CSV dari query yang dibatasi | 202 Job |
| POST /v1/rebuild-jobs | Rebuild aggregate dari retained detail | 202 Job |
| POST /v1/backup-jobs | Backup verified | 202 Job |
| GET /v1/backups | Managed backups yang tersedia | Backup/list |
| POST /v1/restore-jobs | Validasi/pre-backup/maintenance restore | 202 Job |
| GET /v1/jobs/{id} | Status pekerjaan panjang | Job |
| POST /v1/jobs/{id}/cancel | Cancellation request bila masih cancellable | Job |
| GET /v1/jobs/{id}/result | Download CSV export selesai | text/csv |

Tidak ada public event ingestion endpoint; observation/event input berasal dari adapter internal. Lifecycle supervisor memakai channel privat karena engine API tidak dapat mengakui final stop setelah dirinya mati. API employee/identity/RBAC ditambahkan pada V1.5 sesuai model akses.

## 4. Mutation, concurrency, dan retries

Idempotency-Key UUID mengidentifikasi satu logical mutation. Receipt + event + domain effect/job creation berkomit dalam transaksi sama. Retry dengan key dan parameters sama mendapatkan response semula; key sama dengan parameters berbeda menghasilkan 409 IDEMPOTENCY_CONFLICT.

Parameter signature untuk request yang berisi secret memakai keyed digest dengan key per installation di CredentialStore, sehingga database tidak menyimpan plaintext atau digest password yang mudah diuji offline. Key rotation membutuhkan receipt epoch policy; jangan mengklaim retry lama tetap bisa diverifikasi setelah key hilang. Receipt default dipertahankan minimal 30 hari; setelah horizon, key yang expired tidak boleh dianggap retry exactly-once tanpa informasi.

If-Match berisi quoted revision. Revision salah menghasilkan 412 REVISION_CONFLICT. Config create mengembalikan committed revision dengan status PENDING_APPLY bila capture/domain belum menerapkannya. Applied hanya setelah coordinator ack; API success tidak menyatakan observasi sudah valid.

GET resource response harus mengirim ETag revision yang dipakai client. Create schedule pertama memakai If-Match "0". Connection test tidak mengubah credential/config tanpa command terpisah.

## 5. Report request/response

Contoh struktur request; UUID berikut hanya ilustrasi:

```json
{
  "workspace_ids": ["00000000-0000-4000-8000-000000000001"],
  "start": "2026-10-11T09:00:00+07:00",
  "end": "2026-10-11T17:00:00+07:00",
  "grain": "DAY",
  "precision": "EXACT",
  "calendar_mode": "HISTORICAL",
  "limit": 100,
  "cursor": null
}
```

EXACT memerlukan source interval retained. ALIGNED_CACHE hanya menerima bucket boundary yang sesuai calendar/timezone dan menyediakan resolution yang tersedia. Data lama tanpa source tidak diprorata untuk memenuhi exact query.

Response menyertakan snapshot_id, source_event_seq, durable_until, detail_available, provisional, rows, next_cursor, expires_at. Setiap row menyatakan config/schedule version, bucket start/end, durations dalam seconds, ratios nullable, count coverage, average count, peak dan session starts. Config partitions dalam bucket sama dijumlahkan client/report service sesuai metadata; tidak menghitung denominator seluruh bucket dua kali.

Count ratio null berarti unavailable. Coverage denominator nol menghasilkan null. Dashboard occupants_observed adalah jumlah observasi pada reporting zones yang tidak overlap dan disertai count coverage; bukan global unique employee count.

Page berasal dari satu materialized snapshot TTL 60 detik. Cursor terikat filters dan snapshot; mismatched filter menghasilkan 409 CURSOR_FILTER_CONFLICT. Expired snapshot/restart menghasilkan 410 SNAPSHOT_EXPIRED. Query melebihi 5000 rows atau memory budget menghasilkan 413 QUERY_TOO_LARGE dengan saran export job.

## 6. Long-running jobs

POST mengembalikan 202 dan Location /v1/jobs/{id}. 202 berarti accepted, bukan pekerjaan selesai. State: QUEUED → RUNNING → COMPLETED/FAILED/CANCELLED; restart dapat menghasilkan INTERRUPTED. Progress null jika belum dapat diukur.

Job parameter disimpan tanpa secret. Camera test mereferensikan credential_ref. Backup/rebuild/export bisa retry menurut job policy, restore tidak diulang otomatis setelah ambiguous crash. Cancel tidak membatalkan transaksi committed dan ditolak pada tahap restore swap yang sudah tidak cancellable.

Export memakai seluruh filter/range; cursor wajib null dan limit hanya pengaturan page query, bukan batas jumlah baris file. Service menolak export dari cursor parsial agar hasil tidak kehilangan baris awal secara diam-diam.

Restore request membawa backup_id, expected_database_id dan expected_engine_run_id. Jika database epoch/engine sudah berubah sebelum maintenance lock, reject 409 RESTORE_STATE_CHANGED. Checkpoint normal tidak membatalkan restore request. GUI menampilkan backup metadata dan dampak sebelum operator memulai restore; pre-restore verified backup dibuat otomatis sesudah pause accounting dan memakai source sequence aktual pada titik pause. Job coordinator/supervisor menyelesaikan swap/restart karena API process sendiri dapat berhenti; client reconnect dan membaca job state pada database hasil restore melalui completion receipt yang dibawa supervisor, lalu dimasukkan ke api_jobs baru. Restore job ID dan outcome tidak boleh hilang hanya karena database diganti.

Supervisor menyimpan restore journal/receipt sanitized di application-data directory di luar file database yang akan diganti. Journal ditulis atomically sebelum pause/swap, memuat backup hash, stage, request ID dan expected epoch tanpa secret. Setelah swap, database mendapat instance_id baru; receipt dan outcome dipersist pada database restored sebelum maintenance lock dilepas. Recovery membaca stage agar tidak melakukan swap dua kali.

Download result hanya mengakses file managed berdasarkan job ID. Pending/wrong job kind menghasilkan 409; expired file 410 RESULT_EXPIRED. CSV escaping menangani newline/quotes, dan text field berawalan formula spreadsheet dinetralkan pada export.

## 7. WebSocket contracts

WebSocket di luar operasi HTTP OpenAPI; auth dan payload validation sama.

| Endpoint | Isi |
|---|---|
| /v1/ws/status | JSON snapshot/status, job update, committed sequence |
| /v1/ws/cameras/{id}/preview | Metadata JSON lalu binary JPEG frame matching frame_seq |

Native GUI memakai Authorization header pada handshake. Origin browser yang tidak terdaftar ditolak. Token tidak di URL. Initial status selalu SNAPSHOT; UPDATE memiliki stream_seq per connection dan engine_run_id. Missing sequence/restart mengharuskan RESYNC_REQUIRED atau reconnect/snapshot; stream bukan event ledger durable.

Status queue per client bounded dan updates dapat dicoalesce. Preview maksimal 2 FPS pada baseline dan hanya kamera yang disubscribe. Setiap preview memuat generation, frame_seq, width/height, observation timestamp, overlay source frame_seq, stale flag dan byte_length. Binary harus sesuai metadata; snapshot berikutnya dapat dibuang ketika client lambat. Accounting tidak bergantung pada acknowledgment GUI.

## 8. Errors

```json
{
  "error": {
    "code": "REVISION_CONFLICT",
    "message": "Konfigurasi sudah berubah; muat revision terbaru.",
    "request_id": "00000000-0000-4000-8000-000000000002",
    "details": {"current_revision": 4}
  }
}
```

401 UNAUTHORIZED, 404 NOT_FOUND, 409 IDEMPOTENCY_CONFLICT/ENGINE_BUSY/RESTORE_STATE_CHANGED, 410 SNAPSHOT_EXPIRED/RESULT_EXPIRED, 412 REVISION_CONFLICT, 413 QUERY_TOO_LARGE, 422 INVALID_REQUEST/RANGE_NOT_RECONSTRUCTABLE, 503 ENGINE_NOT_READY/PERSISTENCE_DEGRADED, 507 STORAGE_FULL.

Logging memakai request_id, operation, duration, result code dan source sequence. Header auth, credential body, stream query secrets, serta raw exception yang memuat URL tidak dicatat.

## 9. Contract verification dan future API

OpenAPI artifact mendefinisikan endpoint, schema, null semantics, auth, concurrency headers dan errors. Implementasi FastAPI harus menghasilkan contract yang cocok melalui snapshot/diff test. Reference validator memeriksa JSON/ref/path/operation consistency; full OpenAPI validator dan actual HTTP/WebSocket tests masuk milestone implementasi.

Remote API V2 membutuhkan deployment/auth/RBAC/access model, TLS dan scope lokasi tersendiri. Mengubah bind dari 127.0.0.1 menjadi 0.0.0.0 tidak dianggap implementasi remote API lengkap.
