# UI/UX Specification

Versi 1.0 · 11 Oktober 2026 · Tahap 3: desain untuk review, belum implementasi aplikasi.

## 1. Basis dan keputusan produk

Dokumen ini menerapkan [PRD v1.3](PRD-CCTV-Productivity-Tracker.md), [Architecture](docs/ARCHITECTURE.md), [Technical Design](docs/TECHNICAL-DESIGN.md), [Database Design](docs/DATABASE-DESIGN.md), dan [API Design](docs/API-DESIGN.md). Skema yang dimaksud oleh prompt sebagai DATABASE.md sudah tersedia dengan nama DATABASE-DESIGN.md; tidak membuat sumber kebenaran kedua.

Prompt pengguna meminta empat dokumen sebelum approval arah desain. Deliverable tahap ini adalah spesifikasi, tokens, inventory, rencana layar, dan preview desain statis. Preview tidak menyatakan bahwa aplikasi PySide6, stream CCTV, atau server API sudah berjalan. Angka analitik dan foto CCTV tidak direkayasa untuk mengisi preview.

Referensi visual pengguna diterjemahkan menjadi desktop gelap, panel rapat, kamera sebagai fokus, daftar perangkat, serta inspector. Hindari rail ikon tambahan, sidebar bertingkat yang menghabiskan ruang, event keamanan, face recognition, efek latar, dan dekorasi dari contoh yang tidak mendukung V1.

**Keputusan:** aplikasi desktop PySide6/Qt Widgets; PyQtGraph untuk grafik. Satu shell konsisten, surface solid charcoal/graphite, aksen teal tertahan, border tipis, radius kecil, tanpa gradient/blur/shadow/glow. Desain bukan frontend React/Tailwind/web.

## 2. Scope yang benar-benar ditampilkan

| Tersedia pada V1 | Ditempatkan pada V1.5/V2 |
|---|---|
| Presence per workstation, occupied/empty/unknown, track anonim | Employees, assignment individu, identity verification |
| Kamera live, polygon, diagnostik, timeline zona | Working/idle classification yang memerlukan validasi tambahan |
| Utilization, coverage, durasi, peak/count bila tersedia | Productivity score, ranking employee, perbandingan departemen |
| CSV, backup, restore, calendar, retention | Excel/PDF, RBAC, correction audit, alert delivery, web dashboard |

Sidebar hanya: Ringkasan, Pemantauan Live, Workstation, Analitik, Laporan, Kamera, Pengaturan. Timeline menjadi tab Analitik dan drill-down Workstation. Tidak menambahkan menu Employees/Alerts yang kosong atau tombol fitur masa depan. Timeline membuka catatan interval, bukan playback video karena raw recording default tidak disimpan.

## 3. Model informasi dan copy

| Sumber | Label UI | Aturan |
|---|---|---|
| OCCUPIED | Terisi | Keberadaan teramati di zona; tidak menyatakan bekerja |
| EMPTY | Kosong | Zona terlihat kosong; tidak menyatakan employee tidak bekerja |
| UNKNOWN | Tidak diketahui | Alasan terlihat, termasuk menunggu konfirmasi, frame lama, offline, gap penyimpanan |
| Nullable occupied count | Jumlah belum tersedia | Presence dapat jelas walaupun jumlah tidak dapat dipercaya |
| Anonymous tracker namespace | Track anonim | ID hanya dalam kamera/generation; tidak menggunakan avatar/nama employee |
| Provisional/current tail | Sementara | Belum seluruhnya didukung commit/akhir periode |
| Durable watermark | Tersimpan sampai {waktu} | Waktu commit evidence; terpisah dari waktu frame dan refresh GUI |
| Null ratio | N/A | Penjelasan denominator nol/tidak tersedia; tidak dikonversi ke 0% |
| No eligible rows | Belum ada data | Tidak membuat occupied/empty/unknown historis sebelum monitoring dimulai |
| Detail expired | Agregat tersedia | Tampilkan resolusi/batas periode; exact drill-down tidak tersedia |

Status transport kamera, kualitas tracking, state zona, dan durabilitas penyimpanan selalu terpisah. Kamera ONLINE dapat memiliki inference bermasalah. Preview lancar tidak membuktikan accounting sehat. Decode/render preview yang dihentikan tidak menghentikan engine.

Copy inti: “Durasi terisi”, “Durasi kosong”, “Durasi tidak diketahui”, “Utilization selama observasi valid”, “Coverage observasi”, “Coverage jumlah occupant”, “Teramati pada zona reporting”. Hindari “jam kerja efektif”, “pegawai malas”, “AI productivity confidence”, dan “jumlah karyawan unik”. Definisi metrik tersedia di dekat label melalui bantuan yang dapat difokuskan.

Bahasa awal UI: Bahasa Indonesia. Tidak mencampur copy tombol bahasa Inggris kecuali nama teknis RTSP/ONNX/CSV. Waktu mengikuti timezone lokasi, bukan timezone OS; nama IANA dan offset ditampilkan pada filter/report. Preview mengosongkan waktu bila belum ada frame. “Live” hanya muncul untuk preview fresh yang betul-betul diterima.

## 4. Shell desktop dan resize

- Window awal 1600 × 1000 logical pixels; nyaman pada 1440 × 900; minimum desain 1100 × 720. Nilai ini usulan desain yang perlu diuji pada Qt/high DPI, bukan hasil runtime.
- Sidebar 176 px, dapat diringkas menjadi 144 px; tetap memakai label, tidak berubah menjadi rail ikon tanpa teks. Title bar OS tetap native untuk move/resize/window controls.
- Header halaman 88 px: baris judul/aksi 48 px dan baris konteks 40 px. Toolbar lokal 44 px; status bar 28 px. Padding utama 16 px, gap panel 12 px.
- QSplitter membagi daftar kamera 208–256 px, canvas fleksibel, inspector 248–320 px. Area video mendapat stretch terbesar. Lebar panel dapat diubah dan disimpan sebagai UI preference lokal.
- Di bawah 1280 px inspector berpindah ke drawer atas canvas, tidak memaksa video menjadi kolom sempit. Daftar kamera dapat ditutup dengan tombol berlabel “Daftar kamera”. Layout grid tetap pilihan pengguna; tawarkan “Fokus” bila area tile kecil, jangan diam-diam mengubah layout saat monitoring.
- Tabel menggunakan scroll pada viewport tabel. Header/filter/status tetap terlihat. Grafik tidak diskalakan sebagai gambar; redrawn dengan ticks lebih sedikit ketika sempit.
- OS scaling 100%, 150%, dan 200% wajib diuji. Font memakai point size; frame video mempertahankan aspect ratio dengan letterbox. Polygon mapping mengacu content rect, bukan seluruh widget.

Global engine banner hanya muncul saat ada informasi yang perlu diketahui: reconnect engine, persistence degraded, maintenance, atau incompatible schema. Status bar selalu memperlihatkan kondisi engine, durable watermark, zona waktu, dan “Video tidak disimpan” sesuai konfigurasi aktual. Runtime tanpa sambungan menampilkan “Monitoring tidak aktif”; tidak memakai titik hijau.

## 5. First-run workflow

1. Shell tetap dapat dibuka saat engine belum ready; tampilkan status startup dan tombol retry registry connection, bukan form login palsu.
2. Ringkasan kosong mengarahkan ke “Tambah kamera”; form endpoint RTSP dan kredensial terpisah.
3. Save camera, simpan secret, jalankan connection test job. Masing-masing tahap memiliki hasil; jangan menyatakan kamera siap hanya karena form committed.
4. Setelah frame fresh tersedia, “Buat workstation” membuka editor polygon dengan kamera utama tersebut.
5. Isi nama, desk/room/area, capacity, exclusive group, rule preset, polygon, reference scene. Review kalender/timezone sebelum monitoring pertama.
6. Save configuration revision, tampilkan “Menunggu diterapkan”, lalu APPLIED setelah ack. Coverage dimulai sejak eligible monitoring lifetime; observasi awal tetap UNKNOWN sampai konfirmasi.

Setup boleh ditinggalkan lalu dilanjutkan. Draft lokal tidak memulai monitoring. Secret tidak disimpan dalam draft. Tidak memaksa wizard untuk kamera kedua dan seterusnya.

## 6. Ringkasan

**Workflow:** operator menilai kondisi saat ini, lalu manager membuka periode yang relevan. **Hierarki:** engine/coverage warning → snapshot live → statistik periode → detail zona → masalah kamera. **Komponen:** status strip, compact metric strip, filter periode, workspace table, chart/table switch, camera-health list. **States:** first run, loading, ready, no eligible data, partial coverage, stale snapshot, engine disconnected, persistence degraded.

Live strip: workstation terisi / valid / total, occupant teramati beserta count coverage, zona unknown, serta snapshot time. Metrik periode: P/A/U, utilization bersama coverage. Live dan period strip diberi heading berbeda supaya nilai tidak dianggap satu snapshot yang sama. P/A/U banyak zona dinyatakan “jam-workstation”, bukan person-hours atau waktu dinding.

Gunakan GET /dashboard untuk snapshot live dan POST /reports/query untuk summary periode. Persentase lokasi dihitung dari penjumlahan numerator/denominator, bukan rata-rata percentages. Default reporting zones harus tidak overlap; room dan desk tidak dijumlah sebagai headcount unik.

Chart trend hanya setelah ada data API. Kosong menampilkan pesan, tidak menggambar kurva dekoratif. Klik workspace membuka Workstation/detail dengan context date/filter. Engine error dan kamera masalah membuka diagnostik, bukan menu Alerts.

## 7. Pemantauan Live

**Workflow:** pilih kamera → pantau video/status → fokus kamera → inspeksi zona atau buka diagnostik. **Hierarki:** video → nama/status/timestamp → overlay opsional → rincian observasi. **Komponen:** camera list, grid selector, video tile, overlay controls, focus view, inspector. **States:** unconfigured, connecting, live fresh, reconnecting, auth missing, decode failed, preview paused, stale, disabled, engine disconnected.

Default grid 2×2; pilihan 1/Fokus, 2×2, 3×3. Subscribe hanya kamera pada viewport. Layout dapat menunjuk kamera yang sama hanya sekali. Daftar menampilkan nama, status teks, dan selected marker; tidak memakai avatar atau ikon warna tanpa label.

Video tile: header 32 px dengan nama/ID singkat, status, “Fokus”; footer 24 px dengan waktu frame lokasi dan age. Endpoint/kredensial tidak tampil di tile. Select click memilih inspector; double-click atau Enter fokus; Esc kembali. UI preference overlay disimpan per user, tanpa mengubah rule engine.

Overlay toggles: Zona, Deteksi, Track ID. Default Zona ON, Deteksi OFF, Track ID OFF. Polygon memakai accent outline dan label kecil; box deteksi warna netral konsisten. Warna box tidak berarti produktif/idle. Track label menyebut anonim; confidence score hanya di mode Diagnostik dengan label “Skor detektor, bukan kepastian identitas/hasil kerja”.

Overlay hanya untuk matching generation/frame_seq. Mismatch disembunyikan dengan “Overlay belum sinkron”. Frame lama boleh dibekukan dengan veil solid bertuliskan “Frame terakhir”, timestamp dan alasan, tetapi tidak mempertahankan badge LIVE. Preview paused menampilkan “Preview dijeda; pencatatan mengikuti status engine” dan label pipeline aktual.

Fullscreen/focus menggunakan kontrol native window, tetap menampilkan status/time dan tindakan keluar. Tidak menyediakan playback, rewind, screenshot save, microphone/PTZ, intrusion alert, atau rekaman tanpa scope PRD baru. Session duration berhenti di evidence watermark; GUI tidak menambah waktu dari local timer ketika data stale.

Inspector: status stream, preview age, tracking availability bila health contract menyediakan, kamera utama, zona terpilih, canonical state/reason, observed count nullable, configuration revision, dan link timeline. Semua diagnostik yang belum tersedia dari API menggunakan “Belum tersedia”, tidak diestimasi oleh GUI.

## 8. Workstation dan editor polygon

**Workflow:** list zona → create/edit draft → validasi → review perubahan → save revision → tunggu applied. **Hierarki:** frame besar → polygon yang dipilih → properties → revision/result. **Komponen:** workspace table, frame canvas, vertex handles, property form, validation list, revision history. **States:** no camera, no fresh frame, draft dirty, valid, invalid geometry, save running, revision conflict, PENDING_APPLY, APPLIED, REVIEW_REQUIRED.

List memuat nama, jenis, capacity, kamera utama, config version, canonical state bila tersedia, dan timeline link. CRUD yang belum memiliki endpoint tidak disamarkan sebagai tombol aktif. Nama/capacity pada pembuatan berasal dari WorkspaceCreate; update metadata/retirement membutuhkan kontrak tambahan yang dicatat pada rencana layar.

Editor memakai freeze frame yang fresh untuk geometry, dengan timestamp sumber dan label “Frame acuan editor”. Freeze untuk editor tidak pause engine. Add vertex dengan click, close dengan click vertex pertama/Enter, drag vertex, Backspace hapus vertex terpilih, Ctrl+Z/Ctrl+Y undo/redo draft, Esc batal tool. Tersedia tabel normalized X/Y untuk editing keyboard, sehingga drag bukan satu-satunya cara.

Validasi minimum 3 dan maksimum 64 points, simple polygon, nonzero area, normalized coordinates 0..1, reference width/height, scene fingerprint, satu primary camera, dan allowed rule preset. Crop/zoom/pan hanya memengaruhi viewport; inverse transform menyimpan koordinat frame asli. Zona desk mencakup volume orang duduk, bukan hanya permukaan meja. Batas ini dijelaskan di helper singkat di editor.

Setiap edit menyimpan revision baru. Review menyebut effective time dan dampak: “Histori sebelumnya memakai konfigurasi lama; observasi menunggu konfirmasi setelah penerapan.” 412 menawarkan muat revision terbaru atau simpan draft lokal untuk dibandingkan; tidak auto-overwrite. Ganti stream/aspect/scene memicu REVIEW_REQUIRED. Exclusion zone yang belum punya schema typed menjadi contract gap, bukan polygon lain yang diam-diam dianggap exclusion.

## 9. Analitik dan timeline

**Workflow:** pilih tanggal/periode/zona → apply → review coverage → pilih baris/bucket → inspect interval. **Hierarki:** filter + metadata precision → durasi + coverage → satu chart bermakna → tabel rinci/timeline. **Komponen:** date filter, DAY/WEEK/MONTH/YEAR selector, metric strip, trend/bar/heatmap, table, timeline canvas, interval inspector. **States:** loading, empty, partial, provisional, stale cache, exact available, aggregate-only, snapshot expired, range unreconstructable.

Default tab “Ringkasan” dan “Timeline”; filter date/workstation dibawa antar tab. Kalender mengikuti historical version dan timezone lokasi; default week Senin. Annual chart x-axis bulan, monthly hari, weekly hari, daily waktu. Heatmap week hanya menggunakan FIVE_MINUTES/detail yang tersedia; jangan membuat heatmap dari satu total daily. Table alternative selalu tersedia.

Utilization P/(P+A) selalu berdampingan dengan coverage (P+A)/T. Unknown gap terlihat sebagai status tersendiri. Count coverage memiliki label berbeda. Chart missing bucket ditampilkan gap; tidak diisi 0 dan tidak dihubungkan garis. Range belum final mendapat label “Periode sementara”. Threshold “coverage rendah” hanya muncul jika threshold policy dikonfigurasi; persentase actual tetap terlihat tanpa penilaian otomatis.

Timeline satu lane per zona, skala waktu yang sama, interval [start,end). OCCUPIED menggunakan band green + label Terisi; EMPTY neutral + Kosong; UNKNOWN gray + pola garis terpisah/stipple + alasan. Noneligible schedule ditampilkan “Di luar jadwal” dengan band tipis terpisah. Tidak menggambar di luar jadwal sebagai EMPTY. Segmen sangat pendek mendapat nearest selection dan tabel detail, bukan label yang bertumpuk.

Click/keyboard memilih interval dan menampilkan start/end, durasi, reason, count nullable, rule/config/schedule revision, durable limit. Unknown tail hasil query diberi source “Gap observasi”; bukan event video. Durasi occupied session dapat meliputi count segments tetapi tidak melintasi unknown/config boundary. Tidak menampilkan identity employee dari track.

Exact mode hanya selama detail tersedia. RANGE_NOT_RECONSTRUCTABLE memberi aksi “Gunakan agregat kalender” dan menampilkan grain/resolution/range yang benar, tanpa silently menggeser filter. Snapshot expired menampilkan reload action dan mempertahankan selection/filter; tidak menyambung halaman dari snapshot baru ke lama.

## 10. Laporan

**Workflow:** pilih periode/scope → preview data → export seluruh hasil → ikuti job → pilih save destination GUI. **Hierarki:** filters + exact/cache indicator → summary coverage → sortable table → job result. **Komponen:** report query form, snapshot table, job tray, save dialog. **States:** no data, loading, snapshot expired, oversized query, queued/running, completed, failed, cancelled, interrupted, result expired.

DAY/WEEK/MONTH/YEAR tersedia; custom exact mengikuti retained intervals. CSV menyertakan filter, timezone, identity source anonymous, metric definition/version, coverage, source seq, precision dan provisional metadata. Tombol “Ekspor CSV” memakai seluruh filter/range dengan cursor null; current visible page bukan batas file. Job accepted tidak memunculkan toast “Ekspor selesai”. Progress indeterminate bila server mengirim null.

Ekspor terlalu besar dipindahkan ke export job, bukan GUI yang fetch tanpa batas. Save dialog lokal hanya setelah managed result siap; cancel dialog tidak menghapus histori. Export gagal tetap menyediakan query preview terakhir dengan label timestamp; retry adalah aksi jelas dengan idempotency logical request yang tepat.

## 11. Kamera

**Workflow:** add/edit config → store credentials → test connection → review runtime status → enable/disable. **Hierarki:** list + status → settings → diagnostics/test result → linked workstations. **Komponen:** QTableView, settings form, credential form, test job panel, linked-zone list. **States:** dirty, invalid URI, secret backend unavailable, saving, test queued/running/failed/success, revision conflict, disabled, scene review required.

Endpoint tidak menerima userinfo/query password; form username/password terpisah. Password menggunakan Password echo mode, tampil sementara hanya selama button held/keyboard explicit action; setelah save field kosong dengan label “Kredensial tersimpan”. Tidak memuat secret lama, menyalin ke clipboard otomatis, atau memasukkan secret ke logs/error. Test connection menggunakan server credential reference.

Enable/disable camera PATCH membutuhkan review dampak zona: nonaktif tidak menjadi empty; waktu eligible berikutnya dapat unknown. Mengubah endpoint memicu calibration review. Test result berisi tahap koneksi/decode dan error tersanitasi. FPS aktual, inference lag, resolution, reconnect count hanya ditampilkan bila API health menyediakan.

## 12. Pengaturan dan maintenance

**Workflow:** pilih calendar/performance/storage → review draft → save versi/policy → jalankan maintenance bila perlu. **Hierarki:** kategori kiri → current effective values → proposed changes → hasil/job. **Komponen:** category list, versioned schedule editor, current-runtime diagnostics, retention form, backup table, restore review dialog. **States:** engine busy, invalid schedule, pending save, version conflict, backup verification failure, maintenance/reconnect, restore outcome, missing credentials.

Calendar menggunakan timezone IANA, weekdays, windows, overnight, breaks/holidays. Perubahan historis tidak diaplikasikan retroaktif. UI menampilkan effective time; current OpenAPI belum mendukung pemilihan report operational-hours vs scheduled-hours yang berbeda, sehingga basis kalender diberi label dan toggle tersebut menunggu kontrak typed.

Retention review memperlihatkan detail horizon dan aggregate horizon serta kehilangan kemampuan exact/drill-down sebelum commit. Data path berasal dari engine, read-only; tidak mengarahkan database aktif ke folder source/OneDrive. Backup list menampilkan verified status, time, size/horizon bila contract tersedia.

Restore memerlukan satu dialog review: backup ID/time/schema, verification, histori yang akan diganti, automatic pre-restore backup, dan kredensial mungkin perlu diisi ulang. Primary “Pulihkan backup”, default focus “Batal”. UI mempertahankan restore job ID saat API reconnect, lalu membaca completion receipt dari database baru. Cancel tersedia hanya jika stage server cancellable. Tidak menunjukkan restore sukses hanya karena engine merespons kembali.

V1 access copy “Akses mengikuti akun OS”; tidak menyediakan login/role dropdown yang memberi kesan RBAC sudah ada. Stop engine terpisah dari close GUI melalui supervisor channel. Menutup jendela tidak meminta approval setiap kali; status awal menjelaskan engine tetap berjalan. Stop action menampilkan dampak pencatatan dan menunggu ack.

## 13. Accessibility dan interaction states

Keyboard Tab mengikuti urutan visual; setiap action/menu/form memakai accessible name dan label buddy Qt. Focus visible dua logical px, tidak mengandalkan hover. Standard Enter/Esc, Ctrl+F page search, F11 focused camera fullscreen. Ctrl+S hanya draft editor/form yang aktif; tidak secara global melakukan mutation yang tidak terlihat. Shortcut table ada pada [Design System](DESIGN_SYSTEM.md).

Dialog mempunyai title/description, focus trap oleh QDialog, default aman, Esc bila cancellable, dan focus kembali ke trigger. Error form berada di dekat field dan summary pertama yang dapat difokuskan; data nonsecret dipertahankan setelah retry. Buttons memiliki hit area minimal 32×32 logical px pada desktop; target touch bukan scope utama.

State text selalu menemani semantic color. Tidak ada flashing alarm, animation bounding boxes, chart looping, atau refresh toast berulang. Loading menggunakan native indeterminate progress + teks; layout metric tetap stabil. Job tray dapat dibuka kembali dari status bar tanpa menghalangi video.

## 14. Preview dan acceptance desain

[Live monitoring preview](docs/ui/previews/live-monitoring-1600.png) dan [workspace editor preview](docs/ui/previews/workspace-editor-1600.png) merupakan desain statis dengan state tanpa stream/draft. Frame pada editor adalah diagram area kerja berlabel ilustrasi, bukan foto CCTV atau hasil detector. Semua KPI belum tersedia tidak diberi angka.

Hasil [visual review](docs/ui/VISUAL_REVIEW.md) membedakan inspeksi PNG proposal dari runtime screenshot Qt. Runtime responsive controls, screen-reader, focus, overlay-frame correctness, API timing dan multi-hour monitoring masih memerlukan implementasi/test.

Acceptance review: tujuh menu sesuai V1; satu accent; no decorative chart; empty/unknown/null tidak tercampur; live/persisted freshness terpisah; video dominan; secrets tertutup; zone editor keyboard alternative; metadata precision jelas; UI-only preferences terpisah dari engine config. Semua visual/component styling berasal dari [tokens](docs/ui/design-tokens.json).
