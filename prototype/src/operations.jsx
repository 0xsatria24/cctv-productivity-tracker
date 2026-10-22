import { useEffect, useId, useRef, useState } from 'react';
import { ArrowRight, Camera, Check, CheckCircle2, CircleHelp, Download, Radio, Settings, ShieldCheck } from 'lucide-react';
import { Button, DataTable, Empty, Field, Modal, Panel, Status } from './components';
import { displayTime, ratio, seconds, totalMetrics } from './engine-client';
import { currentObservation, localInput, localToUtc, monitoringText, periodRange, reasonText } from './operations-domain.mjs';
import './operations.css';

const stateLabel = value => ({ ONLINE: 'Terhubung', PAUSED: 'Belum dimulai', CONNECTING: 'Menghubungkan', RECONNECTING: 'Menghubungkan ulang', STALLED: 'Frame terhenti', OFFLINE: 'Tidak terhubung', UNKNOWN: 'Status belum tersedia' }[value] || 'Perlu diperiksa');
export function UnknownHelp({ onClose }) {
  return <Modal title="Memahami durasi tidak diketahui" onClose={onClose}><div className="help-copy"><p>Durasi tidak diketahui muncul ketika bukti kamera belum cukup untuk menentukan apakah workstation terisi atau kosong.</p><ul><li>Kamera terputus atau frame terlambat.</li><li>Analisis terhenti atau posisi orang masih ambigu.</li><li>Zona masih menunggu konfirmasi setelah monitoring dimulai.</li></ul><p>Durasi ini dihitung dalam kelengkapan observasi. Persentase keterisian dihitung dari durasi terisi dibagi total durasi terisi dan kosong.</p><p>Durasi beberapa workstation dijumlahkan sebagai waktu workstation, bukan durasi kerja seseorang. Kehadiran di zona belum membuktikan hasil kerja.</p><Button onClick={onClose}>Mengerti</Button></div></Modal>;
}

export function PeriodMetrics({ report, loading = false }) {
  const [help, setHelp] = useState(false), m = totalMetrics(report);
  return <><div className={`metric-strip operations-metrics ${loading ? 'data-pending' : ''}`} data-testid="engine-metrics" aria-busy={loading}>
    {[['Durasi terisi', m.eligible_us ? seconds(m.occupied_us) : 'Belum ada data', 'occupied'], ['Durasi kosong', m.eligible_us ? seconds(m.empty_us) : 'Belum ada data', 'empty'], ['Tidak diketahui', m.eligible_us ? seconds(m.unknown_us) : 'Belum ada data', 'unknown'], ['Keterisian', ratio(m.utilization), ''], ['Kelengkapan observasi', ratio(m.coverage), '']].map(([label, value, tone]) => <div key={label}><span>{label}</span><strong className={tone}>{loading ? 'Memuat...' : value}</strong></div>)}
  </div><div className="metrics-explanation"><span>Akumulasi durasi seluruh workstation dalam periode yang dipilih.</span><button className="text-button" onClick={() => setHelp(true)}><CircleHelp size={14}/>Cara membaca metrik</button></div>{help && <UnknownHelp onClose={() => setHelp(false)}/>}</>;
}

export function ReportFilters({ engine }) {
  const [filtersOpen,setFiltersOpen]=useState(()=>!window.matchMedia('(max-width:760px)').matches);
  const timezone = engine.snapshot?.timezone || 'Asia/Jakarta';
  const [kind, setKind] = useState('session'), [date, setDate] = useState(() => localInput(Date.now() * 1000, timezone).slice(0, 10));
  const [shift, setShift] = useState({ from: '07:00', to: '15:00' });
  const [draft, setDraft] = useState({ workspace: engine.filters.workspace, start: '', end: '' }), [error, setError] = useState(''), [periodNotice, setPeriodNotice] = useState('');
  const dirty = useRef(false);
  useEffect(() => { dirty.current = false; setError(''); setKind('session'); }, [engine.dataset, engine.cameraId]);
  useEffect(() => {
    if (!dirty.current) {
      setDraft({ workspace: engine.filters.workspace, start: localInput(engine.filters.start ?? engine.report?.start_utc_us, timezone), end: localInput(engine.filters.end ?? engine.report?.end_utc_us, timezone) });
      setKind(engine.filters.period || (engine.filters.start != null ? 'custom' : 'session'));
      if(engine.filters.start!=null)setDate(localInput(engine.filters.start,timezone).slice(0,10));
    }
  }, [engine.selection, engine.dataset, engine.filters, engine.report?.start_utc_us, engine.report?.end_utc_us, timezone]);
  function apply(e) {
    e.preventDefault(); setError(''); setPeriodNotice('');
    try {
      let range;
      if (kind === 'session') range = { start: null, end: null };
      else if (kind === 'custom') {
        const start = localToUtc(draft.start, timezone), end = localToUtc(draft.end, timezone);
        if (start == null || end == null || end <= start) throw new Error('Pilih waktu selesai setelah waktu mulai. Waktu harus valid di zona waktu lokasi.');
        range = { start, end };
      } else range = periodRange(kind, date, timezone, shift.from, shift.to);
      if (range.start != null) {
        const now = Date.now() * 1000;
        if (range.start >= now) throw new Error('Periode ini belum dimulai. Pilih tanggal atau jam yang sudah berlangsung.');
        if (range.end > now) { range.end = now; setPeriodNotice('Periode masih berjalan. Laporan dibatasi sampai waktu filter diterapkan.'); }
      }
      // A dated report covers all sessions in that range, never just the most recent one.
      if (kind !== 'session' && engine.selection !== 'ALL') engine.setSelection('ALL');
      engine.setFilters({ workspace: draft.workspace, ...range, period:kind }); dirty.current = false;
    } catch (failure) { setError(failure.message); }
  }
  function reset() { dirty.current = false; setKind('session'); setError(''); setPeriodNotice(''); engine.setFilters({ workspace: 'ALL', start: null, end: null }); }
  return <section className="report-filter-panel" aria-label="Filter periode laporan"><details className="report-filter-controls" open={filtersOpen} onToggle={e=>setFiltersOpen(e.currentTarget.open)}><summary>Ubah periode dan workstation</summary><form className="filter-toolbar engine-filters" onSubmit={apply}>
    <Field label="Sesi monitoring"><select value={engine.selection} onChange={e => { dirty.current = false; setKind('session'); engine.setSelection(e.target.value); engine.setFilters({ workspace: 'ALL', start: null, end: null }); }}><option value="LATEST">Sesi terbaru</option><option value="ALL">Semua sesi tersimpan</option>{engine.snapshot?.runs.map(run => <option key={run.id} value={run.id}>{displayTime(run.started_utc_us, timezone)} · {run.id.slice(0, 8)}</option>)}</select></Field>
    <Field label="Workstation"><select value={draft.workspace} onChange={e => { dirty.current = true; setDraft(p => ({ ...p, workspace: e.target.value })); }}><option value="ALL">Semua workstation</option>{engine.snapshot?.workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
    <Field label="Periode laporan"><select value={kind} onChange={e => { dirty.current = true; setKind(e.target.value); setError(''); }}><option value="session">Rentang sesi tersimpan</option><option value="day">Satu hari</option><option value="week">7 hari sampai tanggal</option><option value="shift">Rentang shift</option><option value="custom">Waktu khusus</option></select></Field>
    {['day', 'week', 'shift'].includes(kind) && <Field label="Tanggal laporan"><input required type="date" value={date} onChange={e => setDate(e.target.value)}/></Field>}
    {kind === 'shift' && <><Field label="Jam mulai shift"><input required type="time" value={shift.from} onChange={e => setShift(s => ({ ...s, from: e.target.value }))}/></Field><Field label="Jam selesai shift"><input required type="time" value={shift.to} onChange={e => setShift(s => ({ ...s, to: e.target.value }))}/></Field></>}
    {kind === 'custom' && <><Field label="Mulai (waktu lokasi)"><input required type="datetime-local" step="1" value={draft.start} onChange={e => setDraft(d => ({ ...d, start: e.target.value }))}/></Field><Field label="Sampai (waktu lokasi)"><input required type="datetime-local" step="1" value={draft.end} onChange={e => setDraft(d => ({ ...d, end: e.target.value }))}/></Field></>}
    <Button type="submit" variant="primary" disabled={engine.reportLoading}>Terapkan filter</Button><Button type="button" onClick={reset}>Reset rentang</Button>
  </form></details><div className="report-range-summary"><span>Zona waktu: <strong>{timezone}</strong></span><span>{engine.reportLoading ? 'Menyiapkan laporan...' : engine.report?.start_utc_us != null && engine.report?.end_utc_us != null ? `${displayTime(engine.report.start_utc_us, timezone)} sampai ${displayTime(engine.report.end_utc_us, timezone)}` : 'Pilih sesi yang sudah memiliki observasi.'}</span></div>{kind === 'shift' && <p className="caption">Rentang shift adalah filter jam untuk tanggal ini. Jam selesai yang lebih awal berakhir pada hari berikutnya. Kalender kerja otomatis belum diterapkan.</p>}{periodNotice && <p className="caption" role="status">{periodNotice}</p>}{error && <p className="error-text" role="alert">{error}</p>}</section>;
}

export function DurationBreakdown({ report, onSelect }) {
  const descriptionId=useId();
  return <div className="engine-breakdown">
    <div className="chart-legend">{[['occupied', 'Terisi'], ['empty', 'Kosong'], ['unknown', 'Tidak diketahui']].map(([tone, label]) => <span key={tone}><i className={`legend-swatch ${tone}`} aria-hidden="true"/>{label}</span>)}</div>
    {report?.workstations.some(w => w.eligible_us > 0) ? report.workstations.map(row => <button className="bar-row" key={row.workspace_id} aria-label={`Timeline ${row.workspace}`} aria-describedby={`${descriptionId}-${row.workspace_id}`} onClick={() => onSelect(row.workspace_id)}>
      <span>{row.workspace}</span><span className="stacked-track" aria-hidden="true">{[['occupied_us', 'occupied'], ['empty_us', 'empty'], ['unknown_us', 'unknown']].map(([key, tone]) => row[key] > 0 && <span key={key} className={`stacked-segment ${tone}`} style={{ width: `${row[key] / row.eligible_us * 100}%` }}/>)}</span>
      <span className="breakdown-coverage">{ratio(row.coverage)}<small>lengkap</small></span>
      <span className="bar-durations" id={`${descriptionId}-${row.workspace_id}`}>Terisi {seconds(row.occupied_us)} · Kosong {seconds(row.empty_us)} · Tidak diketahui {seconds(row.unknown_us)} · Kelengkapan {ratio(row.coverage)}</span>
    </button>) : <Empty title="Belum ada observasi pada periode ini" description="Pilih periode lain atau mulai monitoring dari halaman Pemantauan Live."/>}
  </div>;
}

export function OperationalOverview({ engine, live, cameras, navigate, onSetup, onTimeline, setModal }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const observation = currentObservation(live.state, live.receivedAt, now, live.error);
  const monitoring = live.active && !live.state?.preview_only;
  const health = cameras.filter(c => c.health === 'ONLINE').length;
  const problems = cameras.filter(c => ['OFFLINE', 'RECONNECTING', 'STALLED', 'UNKNOWN'].includes(c.health));
  const lastSaved = engine.snapshot?.runs[0]?.durable_until_utc_us;
  const events = engine.snapshot?.events || [];
  const transitions = events.filter(e => e.event_type !== 'CHECKPOINT');
  const recentEvents = (transitions.length ? transitions : events.slice(0,1)).slice(0,6);
  return <>
    <section className="operations-intro"><div><span className="section-kicker">KONDISI SAAT INI</span><h2>{monitoringText(live.state, live.error)}</h2><p>{monitoring ? observation.fresh ? 'Kamera mengirim observasi terbaru dari zona yang dikalibrasi.' : 'Menunggu bukti kamera baru. Durasi tanpa bukti akan tercatat tidak diketahui.' : 'Hubungkan kamera, atur zona, lalu mulai sesi monitoring.'}</p></div><Button icon={monitoring ? Camera : ArrowRight} variant="primary" onClick={monitoring ? () => navigate('live') : onSetup}>{monitoring ? 'Buka kamera' : 'Siapkan monitoring'}</Button></section>
    <div className="operations-live-metrics" data-testid="operational-live-metrics">
      <div><Camera size={18}/><span>Kamera terhubung</span><strong>{health}<small> / {cameras.length}</small></strong><p>{health ? 'Preview tersedia' : 'Belum ada kamera live'}</p></div>
      <div><Radio size={18}/><span>Workstation terisi</span><strong>{observation.zones.length ? `${observation.occupied} / ${observation.zones.length}` : 'Belum tersedia'}</strong><p>{observation.zones.length ? `${observation.empty} kosong · ${observation.unknown} belum diketahui` : 'Mulai monitoring untuk observasi zona'}</p></div>
      <div><ShieldCheck size={18}/><span>Orang terdeteksi</span><strong>{observation.count ?? 'Belum tersedia'}</strong><p>Sumber aktif saja; identitas anonim</p></div>
      <div><CheckCircle2 size={18}/><span>Terakhir tersimpan</span><strong className="saved-time">{lastSaved ? displayTime(lastSaved, engine.snapshot?.timezone) : 'Belum ada catatan'}</strong><p>{engine.dataset === 'live' ? 'Catatan kamera live' : 'Catatan replay simulasi'}</p></div>
    </div>
    <div className="operations-overview-grid"><Panel title="Kondisi kamera" caption="Koneksi video dan analisis ditampilkan terpisah" action={<Button onClick={() => navigate('live')}>Kelola kamera</Button>}><div className="operations-camera-list">{cameras.map(c => <button key={c.id} onClick={() => navigate('live')}><Camera size={16}/><span><strong>{c.name}</strong><small>{c.id === 'webcam' ? 'Webcam lokal' : c.analysis ? 'Analisis aktif' : 'Preview saja'}</small></span><Status value={c.health === 'PAUSED' ? 'DISABLED' : c.health === 'STALLED' ? 'DEGRADED' : c.health} label={stateLabel(c.health)}/></button>)}{!cameras.length && <Empty title="Belum ada sumber kamera" description="Tambahkan webcam atau kamera RTSP untuk mulai memantau." action={<Button onClick={onSetup}>Siapkan kamera</Button>}/>}</div></Panel>
      <Panel title="Perlu diperhatikan" caption="Langkah berikutnya untuk menjaga observasi tetap lengkap"><div className="attention-list">{engine.connectionError ? <><p className="error-text">Koneksi layanan analisis terputus. Periksa aplikasi dan koneksi lokal.</p><Button onClick={()=>navigate('settings')}>Periksa koneksi</Button></> : problems.length ? problems.map(c => <button key={c.id} onClick={() => navigate('live')}><span><strong>{c.name}</strong><small>{stateLabel(c.health)}</small></span><ArrowRight size={15}/></button>) : !monitoring ? <><p>Monitoring belum dimulai. Ikuti empat langkah setup untuk menghasilkan catatan workstation.</p><Button onClick={onSetup}>Lanjutkan setup</Button></> : !observation.fresh ? <p>Belum ada observasi baru. Periksa koneksi dan posisi kamera.</p> : <p><Check size={16}/>Tidak ada masalah koneksi yang dilaporkan.</p>}<p className="caption">Kondisi kamera diperbarui otomatis. Buka Laporan untuk memeriksa durasi yang tersimpan.</p></div></Panel></div>
    <div className="section-toolbar"><p>Durasi, rekap harian, timeline dan ekspor tersedia dalam satu area laporan.</p><Button onClick={() => navigate('analytics')}>Buka laporan</Button></div>
    <Panel className="section-gap" title="Aktivitas terbaru" caption="Catatan yang sudah tersimpan"><div className="operations-events">{recentEvents.map(event => <button key={event.event_id} onClick={() => setModal({ type: 'event', value: event })}><time>{displayTime(event.observed_utc_us, engine.snapshot.timezone)}</time><span>{({ ENTER: 'Zona mulai terisi', EXIT: 'Orang meninggalkan zona', EMPTY_CONFIRMED: 'Zona kosong terkonfirmasi', CHECKPOINT: 'Observasi workstation tersimpan' })[event.event_type] || 'Perubahan observasi tersimpan'}</span><ArrowRight size={14}/></button>)}{!engine.snapshot?.events.length && <Empty title="Belum ada aktivitas tersimpan" description="Catatan akan muncul setelah sesi monitoring menghasilkan observasi."/>}</div></Panel>
  </>;
}

export function OperationalReports({ engine, onTimeline, showMetrics=true }) {
  const [search, setSearch] = useState(''), [help, setHelp] = useState(false);
  const rows = (engine.report?.workstations || []).filter(r => r.workspace.toLowerCase().includes(search.toLowerCase())).map(r => ({ ...r, id: r.workspace_id }));
  const columns = [{ key: 'workspace', label: 'Workstation' }, ...[['occupied_us', 'Terisi'], ['empty_us', 'Kosong'], ['unknown_us', 'Tidak diketahui']].map(([key, label]) => ({ key, label, numeric: true, render: r => seconds(r[key]) })), { key: 'utilization', label: 'Keterisian', numeric: true, render: r => ratio(r.utilization) }, { key: 'coverage', label: 'Kelengkapan', numeric: true, render: r => ratio(r.coverage) }, { key: 'detail', label: 'Detail', sortable: false, render: r => <Button onClick={() => onTimeline(r.workspace_id)}>Lihat timeline</Button> }];
  const unknown = (engine.report?.intervals || []).filter(i => i.state === 'UNKNOWN').reduce((all, i) => { const key = reasonText(i.reason); all[key] = (all[key] || 0) + (i.end - i.start) * 1000; return all; }, {});
  return <>{showMetrics&&<PeriodMetrics report={engine.report} loading={engine.reportLoading}/>}<div className="operations-report-grid"><Panel title="Komposisi durasi" caption="Terisi, kosong dan tidak diketahui dalam periode terpilih"><DurationBreakdown report={engine.report} onSelect={onTimeline}/></Panel><Panel title="Kelengkapan data" action={<Button icon={CircleHelp} aria-label="Penjelasan durasi tidak diketahui" onClick={() => setHelp(true)}/>}><div className="coverage-explanation"><p>Waktu tanpa bukti kamera tetap tercatat sebagai tidak diketahui.</p>{Object.entries(unknown).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([reason, us]) => <div key={reason}><span>{reason}</span><strong>{seconds(us)}</strong></div>)}{!Object.keys(unknown).length && <p className="caption">Belum ada interval tidak diketahui dalam hasil ini. Periksa periode dan kelengkapan pada tabel.</p>}</div></Panel></div>
    <Panel className="section-gap" title="Rincian workstation" caption="Ekspor mencakup seluruh hasil filter periode dan workstation" action={<Button icon={Download} variant="primary" disabled={engine.exporting || engine.reportLoading || !engine.report?.workstations.length || !!engine.connectionError} onClick={engine.exportCsv}>{engine.exporting ? 'Menyiapkan CSV...' : 'Ekspor CSV'}</Button>}><div className="table-filter"><Field label="Cari pada tabel"><input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Nama workstation"/></Field><span className="caption">Pencarian hanya membatasi tabel. Gunakan filter workstation untuk membatasi ekspor.</span></div><DataTable testId="engine-report" columns={columns} rows={rows} resetKey={search + JSON.stringify(engine.filters)} empty={<Empty title="Tidak ada workstation untuk hasil ini" description="Periksa pencarian atau pilih periode lain."/>}/></Panel>{help && <UnknownHelp onClose={() => setHelp(false)}/>}</>;
}
