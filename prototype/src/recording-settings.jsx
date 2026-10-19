import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, DataTable, Field, Panel, Status } from './components';
import { engineRequest } from './engine-client';

export function useRecordings() {
  const [data, setData] = useState(null), [readError, setReadError] = useState(''), [saveError, setSaveError] = useState(''), [busy, setBusy] = useState(false);
  const revision = useRef(0), saving = useRef(false);
  useEffect(() => {
    const abort = new AbortController(); let timer;
    async function poll() {
      const before = revision.current;
      try { const result = await engineRequest('recordings', { signal: abort.signal }); if (!abort.signal.aborted && before === revision.current && !saving.current) { setData(result); setReadError(''); } }
      catch (failure) { if (!abort.signal.aborted) setReadError(failure.message); }
      finally { if (!abort.signal.aborted) timer = setTimeout(poll, 2000); }
    }
    poll(); return () => { abort.abort(); clearTimeout(timer); };
  }, []);
  const save = useCallback(async policy => {
    if (saving.current) throw new Error('Pengaturan sedang disimpan. Tunggu sampai selesai.');
    revision.current++; saving.current = true; setBusy(true); setSaveError('');
    try { const result = await engineRequest('recordings/policy', { method: 'POST', body: JSON.stringify(policy) }); revision.current++; setData(result); setReadError(''); return result; }
    catch (failure) { setSaveError(failure.message); throw failure; }
    finally { saving.current = false; setBusy(false); }
  }, []);
  return { data, readError, error: saveError || readError, busy, save };
}

export function recordingLabel(recordings) {
  if (recordings.readError || !recordings.data) return 'Status rekaman belum tersedia';
  const value = recordings.data;
  if (!value.policy.video_enabled) return 'Rekaman video nonaktif';
  if (Object.keys(value.errors).length) return 'Auto-save perlu diperiksa';
  return value.active_videos.length ? `Merekam ${value.active_videos.length} kamera` : 'Rekaman aktif, menunggu frame';
}

function IntervalField({ label, value, onChange, disabled }) {
  const [unit, setUnit] = useState(value >= 60 && value % 60 === 0 ? 60 : 1);
  return <div className="recording-interval"><Field label={label}><input type="number" min={unit === 60 ? 1 : 5} max={unit === 60 ? 60 : 3600} step="1" value={value === '' ? '' : value / unit} disabled={disabled} onChange={e => onChange(e.target.value === '' ? '' : Number(e.target.value) * unit)}/></Field>
    <Field label={`Satuan ${label.toLowerCase()}`}><select value={unit} disabled={disabled} onChange={e => { const next = Number(e.target.value); setUnit(next); if (value !== '') onChange(next === 60 ? Math.max(60, Math.round(value / 60) * 60) : value); }}><option value="1">Detik</option><option value="60">Menit</option></select></Field></div>;
}

export function RecordingSettings({ engine }) {
  const { data, error, busy, save } = engine.recordings;
  const [draft, setDraft] = useState(null), [dirty, setDirty] = useState(false), [filter, setFilter] = useState('ALL');
  useEffect(() => { if (data && !dirty) setDraft({ ...data.policy }); }, [data, dirty]);
  function change(key, value) { setDraft(previous => ({ ...previous, [key]: value })); setDirty(true); }
  const valid = draft && ['data_interval_seconds', 'video_segment_seconds'].every(k => Number.isInteger(draft[k]) && draft[k] >= 5 && draft[k] <= 3600) && Number.isInteger(draft.max_storage_mb) && draft.max_storage_mb >= 512 && draft.max_storage_mb <= 1048576;
  const formatTime = value => new Date(value * 1000).toLocaleString('id-ID', { timeZone: engine.snapshot?.timezone || 'Asia/Jakarta' });
  return <Panel title="Auto-save data dan video" caption="Simpan laporan berkala dan potongan video secara terpisah. Perubahan berlaku setelah disimpan." className="recording-settings" action={<Button onClick={()=>document.querySelector('.recording-destination')?.scrollIntoView({behavior:'smooth',block:'start'})}>Atur tujuan penyimpanan</Button>}>
    {draft ? <form onSubmit={e => { e.preventDefault(); if (valid && !busy) save(draft).then(() => { setDirty(false); engine.toast('Pengaturan auto-save disimpan.'); }).catch(() => {}); }}>
      <div className="recording-options"><fieldset><legend>Laporan data</legend><label className="check-control recording-toggle"><input type="checkbox" aria-label="Auto-save laporan data" checked={draft.data_enabled} disabled={busy} onChange={e => change('data_enabled', e.target.checked)}/><span>Auto-save laporan data<small aria-hidden="true">{draft.data_enabled ? 'Aktif' : 'Nonaktif'}{draft.data_enabled !== data.policy.data_enabled ? ' · belum disimpan' : ''}</small></span></label><IntervalField label="Interval simpan data" value={draft.data_interval_seconds} disabled={busy} onChange={value => change('data_interval_seconds', value)}/><p className="caption">File JSON dan CSV berisi ringkasan sesi terbaru per kamera, durasi zona, dan kelengkapan observasi. Salinan baru dibuat jika data berubah.</p></fieldset>
      <fieldset><legend>Rekaman video</legend><label className="check-control recording-toggle"><input type="checkbox" aria-label="Auto-save rekaman video" checked={draft.video_enabled} disabled={busy} onChange={e => change('video_enabled', e.target.checked)}/><span>Auto-save rekaman video<small aria-hidden="true">{draft.video_enabled ? 'Aktif' : 'Nonaktif'}{draft.video_enabled !== data.policy.video_enabled ? ' · belum disimpan' : ''}</small></span></label><IntervalField label="Durasi potongan video" value={draft.video_segment_seconds} disabled={busy} onChange={value => change('video_segment_seconds', value)}/><p className="caption">MP4 tanpa audio, sekitar 4–5 FPS dari frame preview, sisi terpanjang hingga 640 px. Interval menentukan panjang setiap potongan. Video webcam tersimpan selama browser mengirim frame.</p></fieldset></div>
      <p className="caption">Interval tetap bisa diatur saat nonaktif. Centang opsi untuk mengaktifkan, lalu klik Simpan pengaturan auto-save untuk menerapkan perubahan.</p>
      <div className="inline-controls"><Field label="Batas folder record (MB)" hint="512–1048576 MB. Penyimpanan berhenti saat batas tercapai; file lama tetap ada."><input type="number" min="512" max="1048576" step="1" value={draft.max_storage_mb} disabled={busy} onChange={e => change('max_storage_mb', e.target.value === '' ? '' : Number(e.target.value))}/></Field><Button type="submit" variant="primary" disabled={busy || !valid}>{busy ? 'Menyimpan...' : 'Simpan pengaturan auto-save'}</Button></div>
      {!valid && <p role="alert">Gunakan interval 5–3600 detik atau 1–60 menit dan batas penyimpanan yang valid.</p>}
      {dirty && <p className="caption">Ada perubahan yang belum disimpan.</p>}
      <p className="caption" data-testid="recording-saved-policy">Pengaturan tersimpan: laporan {data.policy.data_enabled ? 'aktif' : 'nonaktif'} setiap {data.policy.data_interval_seconds} detik; video {data.policy.video_enabled ? 'aktif' : 'nonaktif'}, potongan {data.policy.video_segment_seconds} detik.</p>
    </form> : <p>Memuat pengaturan auto-save...</p>}
    {error && <p role="alert" className="error-text">{error}</p>}
    {data && <><div className="recording-summary"><Status value={data.active_videos.length ? 'ONLINE' : 'PAUSED'} label={recordingLabel(engine.recordings)}/><span>Laporan terakhir: {data.last_data_at ? formatTime(data.last_data_at) : 'Belum ada'}</span><span>{(data.storage_bytes / 1048576).toFixed(1)} MB tersimpan</span></div>
      <p className="caption">Pencatatan durasi di database tetap berjalan saat auto-save file dimatikan. Rekaman RTSP berlaku untuk kamera yang terdaftar di grid dan dapat berlanjut saat browser ditutup. Mematikan rekaman menyelesaikan potongan yang sedang berjalan.</p>
      <div className="recording-folder"><span>Folder penyimpanan</span><code>{data.folder}</code><Button onClick={() => navigator.clipboard.writeText(data.folder).then(() => engine.toast('Lokasi folder record disalin.')).catch(() => engine.toast('Clipboard tidak tersedia. Salin lokasi folder secara manual.'))}>Salin lokasi folder</Button></div>
      {Object.entries(data.errors).map(([key, message]) => <p key={key} role="alert" className="error-text">{message}</p>)}
      {data.unfinished_files > 0 && <p role="alert">Ada {data.unfinished_files} potongan yang belum selesai dari sesi terputus. File .partial.mp4 tersimpan di folder record.</p>}
      <div className="recording-file-heading"><h3>File tersimpan</h3><Field label="Jenis file record"><select value={filter} onChange={e => setFilter(e.target.value)}><option value="ALL">Semua file</option><option value="data">Laporan data</option><option value="video">Video</option></select></Field></div>
      <DataTable testId="recording-files" resetKey={filter} rows={data.files.filter(f => filter === 'ALL' || f.kind === filter)} pageSize={5} columns={[
        {key:'created_at',label:'Waktu',render:r=>formatTime(r.created_at)}, {key:'camera_name',label:'Kamera'}, {key:'kind',label:'Jenis',render:r=>r.kind==='video'?`Video · ${r.frames} frame`:'Laporan JSON / CSV'}, {key:'bytes',label:'Ukuran',numeric:true,render:r=>`${(r.bytes/1024).toFixed(1)} KB`},
        {key:'download',label:'Unduh',sortable:false,render:r=><div className="inline-controls">{(r.kind==='video'?['mp4']:['json','csv']).map(format=><a key={format} className="button secondary" href={`/pilot/v1/recordings/files/${r.id}/${format}`} download>{format.toUpperCase()}</a>)}</div>}
      ]}/><p className="caption">Menampilkan 50 file terbaru. File sebelumnya tersedia di folder penyimpanan. Batas penyimpanan tidak menghapus file otomatis.</p>
    </>}
  </Panel>;
}
