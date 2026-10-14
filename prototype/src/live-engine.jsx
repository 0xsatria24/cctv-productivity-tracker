import { useEffect, useRef, useState } from 'react';
import { Button, Field, Modal, Panel, Status } from './components';
import { engineRequest, seconds } from './engine-client';
import { validPolygon } from './domain';

export function useLiveEngine(webcam, engine) {
  const [state, setState] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [ownedSession, setOwnedSession] = useState(null), [cameraKey, setCameraKey] = useState(null);
  const current = useRef(null), owned = useRef(null), previousStream = useRef(null);
  current.current = state; owned.current = ownedSession;
  useEffect(() => {
    const abort = new AbortController(); let timer;
    async function poll() {
      try { const value = await engineRequest('live', { signal: abort.signal }); if (!abort.signal.aborted) { setState(value); setError(''); } }
      catch (failure) { if (!abort.signal.aborted) setError(failure.message); }
      finally { if (!abort.signal.aborted) timer = setTimeout(poll, 750); }
    }
    poll(); return () => { abort.abort(); clearTimeout(timer); };
  }, []);
  useEffect(() => {
    let cancelled = false;
    setCameraKey(null);
    if (webcam.stream) {
      const id = webcam.stream.getVideoTracks()[0]?.getSettings().deviceId;
      if (id) crypto.subtle.digest('SHA-256', new TextEncoder().encode(id)).then(buffer => {
        if (!cancelled) setCameraKey(Array.from(new Uint8Array(buffer), b => b.toString(16).padStart(2, '0')).join(''));
      });
    }
    if (previousStream.current && !webcam.stream && owned.current && current.current?.source === 'WEBCAM_LIVE') {
      engineRequest('live/stop', { method: 'POST', body: JSON.stringify({ session_id: owned.current }) }).catch(() => {});
      setOwnedSession(null);
    }
    previousStream.current = webcam.stream;
    return () => { cancelled = true; };
  }, [webcam.stream]);
  async function action(path, body) {
    setBusy(true); setError('');
    try { const value = await engineRequest(`live/${path}`, { method: 'POST', body: JSON.stringify(body) }); setState(value); engine.reload(); return value; }
    catch (failure) { setError(failure.message); throw failure; }
    finally { setBusy(false); }
  }
  async function start(source, url, preview = false) {
    const value = await action('start', { source, ...(url ? { url } : {}), preview_only: preview, camera_key: source === 'WEBCAM_LIVE' ? cameraKey : undefined });
    setOwnedSession(value.session_id);
    if (!preview) engine.setDataset('live');
    return value;
  }
  async function stop() {
    if (!state?.session_id) return;
    await action('stop', { session_id: state.session_id }); setOwnedSession(null);
  }
  const active = ['STARTING', 'RUNNING', 'STOPPING'].includes(state?.status);
  return { state, active, error, busy, start, stop, action, cameraKey,
    webcamSession: ownedSession && state?.session_id === ownedSession && state?.source === 'WEBCAM_LIVE' && state?.status === 'RUNNING' ? ownedSession : null,
    webcamStarting: !!ownedSession && state?.source === 'WEBCAM_LIVE' && state?.status === 'STARTING' };
}

export function LiveEnginePanel({ live, webcam, engine, hidePreview = false }) {
  const [source, setSource] = useState('WEBCAM_LIVE'), [url, setUrl] = useState('');
  const [calibration, setCalibration] = useState(null), [notice, setNotice] = useState('');
  const [rtspImage, setRtspImage] = useState(null), [rtspMeta, setRtspMeta] = useState(null);
  const rtsp = live.state?.source === 'RTSP_LIVE' && live.active;
  useEffect(() => { if (live.active && live.state?.source) setSource(live.state.source); }, [live.active, live.state?.source]);
  useEffect(() => {
    if (!rtsp || hidePreview) { setRtspImage(null); setRtspMeta(null); return; }
    let cancelled = false, timer, previous;
    const abort = new AbortController();
    async function preview() {
      try {
        const response = await fetch('/pilot/v1/live/preview.jpg', { cache: 'no-store', signal: abort.signal });
        if (!response.ok) throw new Error('stale');
        const object = URL.createObjectURL(await response.blob());
        if (cancelled) { URL.revokeObjectURL(object); return; }
        if (previous) URL.revokeObjectURL(previous);
        previous = object; setRtspImage(object);
      } catch { if (!cancelled) { setRtspImage(null); setRtspMeta(null); } }
      finally { if (!cancelled) timer = setTimeout(preview, 750); }
    }
    preview(); return () => { cancelled = true; abort.abort(); clearTimeout(timer); if (previous) URL.revokeObjectURL(previous); };
  }, [rtsp, hidePreview]);
  const profile = live.state?.calibrations?.[source];
  async function calibrate() {
    setNotice('');
    try {
      const video = document.querySelector('video[aria-label="Preview webcam lokal"]');
      const image = document.querySelector('img[aria-label="Preview RTSP lokal"]');
      const element = source === 'WEBCAM_LIVE' ? video : image;
      const width = source === 'WEBCAM_LIVE' ? element?.videoWidth : element?.naturalWidth;
      const height = source === 'WEBCAM_LIVE' ? element?.videoHeight : element?.naturalHeight;
      if (!element || !width || !height || (source === 'WEBCAM_LIVE' && webcam.status !== 'LIVE')) throw new Error('Mulai preview sumber yang dipilih, lalu tunggu frame sebelum kalibrasi.');
      const key = source === 'WEBCAM_LIVE' ? live.cameraKey : live.state?.camera_key;
      if (!key) throw new Error('Identitas kamera belum tersedia; coba kembali setelah frame tampil.');
      const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
      canvas.getContext('2d').drawImage(element, 0, 0, width, height);
      const frame = canvas.toDataURL('image/jpeg', 0.8);
      if (live.active) await live.stop();
      setCalibration({ frame, width, height, camera_key: key, source, profile });
    } catch (failure) { setNotice(failure.message); }
  }
  async function begin(preview) {
    setNotice('');
    if (source === 'WEBCAM_LIVE' && !webcam.stream) { setNotice('Klik Mulai webcam terlebih dahulu.'); return; }
    try { await live.start(source, url, preview); }
    catch {}
  }
  const latest = live.state?.latest;
  return <Panel title="Pencatatan kamera live" caption="Kalibrasikan zona, lalu mulai sesi untuk menyimpan durasi workstation." action={<Status value={live.state?.camera_health || 'OFFLINE'} label={`${live.state?.status || 'IDLE'} · ${live.state?.camera_health || 'OFFLINE'}`}/>} className="live-engine-panel">
    <div className="live-engine-controls">
      <Field label="Sumber pencatatan"><select value={source} disabled={live.active || live.busy} onChange={e => setSource(e.target.value)}><option value="WEBCAM_LIVE">Webcam browser</option><option value="RTSP_LIVE">CCTV RTSP</option></select></Field>
      {source === 'RTSP_LIVE' && <Field label="URL RTSP" hint="URL dan kredensial hanya digunakan selama sesi, tidak disimpan ke laporan."><input type="password" autoComplete="off" placeholder="rtsp://user:password@kamera:554/stream" value={url} disabled={live.active} onChange={e => setUrl(e.target.value)}/></Field>}
      <div className="inline-controls">
        {source === 'RTSP_LIVE' && <Button disabled={live.active || live.busy || !url} onClick={() => begin(true)}>Uji preview RTSP</Button>}
        <Button disabled={live.busy || live.state?.status === 'STOPPING' || (source === 'WEBCAM_LIVE' && !webcam.stream)} onClick={calibrate}>Kalibrasi zona live</Button>
        <Button variant="primary" disabled={live.active || live.busy || !profile || (source === 'WEBCAM_LIVE' && !webcam.stream) || (source === 'RTSP_LIVE' && !url)} onClick={() => begin(false)}>Mulai pencatatan live</Button>
        <Button disabled={!live.active || live.busy || live.state?.status === 'STOPPING'} onClick={() => live.stop().catch(() => {})}>Hentikan pencatatan live</Button>
        <Button onClick={() => engine.setDataset('live')}>Lihat laporan live</Button>
      </div>
      <p className="caption">{profile ? `${profile.zones.length} zona · revisi ${profile.revision} · konfirmasi terisi ${profile.rules.occupied_confirm_seconds} dtk / kosong ${profile.rules.empty_confirm_seconds} dtk` : 'Belum ada kalibrasi untuk sumber ini.'} · Identitas occupant anonim.</p>
      {(notice || live.error || live.state?.error) && <p role="alert" className="error-text">{notice || live.error || live.state?.error}</p>}
      {live.state?.run_id && <p className="caption">Run {live.state.run_id.slice(0, 8)} · {live.state.processed} frame committed. Gambar tidak direkam.</p>}
    </div>
    {rtsp && !hidePreview && <div className="rtsp-live-preview">
      {rtspImage ? <div className="rtsp-frame" style={{ aspectRatio: rtspMeta ? `${rtspMeta.width}/${rtspMeta.height}` : '16/9' }}><img src={rtspImage} aria-label="Preview RTSP lokal" onLoad={event => setRtspMeta({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}/>{latest && <svg viewBox={`0 0 ${latest.width} ${latest.height}`} preserveAspectRatio="none" className="webcam-detections">{latest.detections.map((d, i) => <rect key={i} x={d.box[0] * latest.width} y={d.box[1] * latest.height} width={(d.box[2] - d.box[0]) * latest.width} height={(d.box[3] - d.box[1]) * latest.height} className="person-box"/>)}</svg>}</div> : <p className="empty-state">Menunggu frame RTSP. Engine mencoba ulang koneksi saat terputus.</p>}
      <p className="caption">{live.state.preview_only ? 'Preview deteksi saja; durasi belum dicatat.' : 'Tracking dan durasi live aktif.'} RTSP tetap berjalan saat halaman/browser ditutup selama proses Python berjalan.</p>
    </div>}
    {latest?.zones && <div className="live-zone-states">{latest.zones.map(zone => <div key={zone.id}><strong>{zone.name}</strong><Status value={zone.state}/><span>{zone.count ?? 'N/A'} occupant · {seconds(zone.evidence_until_utc_us - zone.state_since_utc_us)} pada state ini</span>{zone.reason && <small>{zone.reason}</small>}</div>)}</div>}
    {calibration && <CalibrationDialog value={calibration} live={live} onClose={() => setCalibration(null)}/>}
  </Panel>;
}

function CalibrationDialog({ value, live, onClose }) {
  const [zones, setZones] = useState(value.profile?.zones || []), [points, setPoints] = useState([]), [name, setName] = useState(''), [editing, setEditing] = useState(null);
  const [rules, setRules] = useState(value.profile?.rules || { occupied_confirm_seconds: 2, empty_confirm_seconds: 5, max_evidence_gap_seconds: 3, association_overlap: 0.25, ambiguity_margin: 0.1, strong_confidence: 0.5 });
  const [error, setError] = useState(''), [coordinate, setCoordinate] = useState({ x: '0.5', y: '0.5' });
  function addPoint(point) { if (points.length >= 64) { setError('Maksimal 64 titik per zona.'); return; } setPoints(p => [...p, point]); setError(''); }
  function storeZone() {
    if (!name.trim() || !validPolygon(points)) { setError('Nama dan polygon sederhana minimal 3 titik diperlukan; garis tidak boleh berpotongan.'); return; }
    const zone = { id: editing || crypto.randomUUID(), name: name.trim(), polygon: points, exclusive_group: 'workstations' };
    setZones(z => editing ? z.map(item => item.id === editing ? zone : item) : [...z, zone]); setPoints([]); setName(''); setEditing(null); setError('');
  }
  async function save() {
    if (points.length || name.trim()) { setError('Simpan atau batalkan zona yang sedang digambar sebelum menyimpan kalibrasi.'); return; }
    try { await live.action('calibration', { source: value.source, width: value.width, height: value.height, camera_key: value.camera_key, zones, rules }); onClose(); }
    catch (failure) { setError(failure.message); }
  }
  return <Modal title="Kalibrasi zona live" description="Frame dibekukan tanpa mirror. Klik titik batas workstation berurutan, simpan zona, lalu simpan kalibrasi. Kalibrasikan ulang jika kamera atau posisinya berubah." wide onClose={onClose}>
    <div className="calibration-frame" style={{ aspectRatio: `${value.width}/${value.height}` }} onClick={event => { const rect = event.currentTarget.getBoundingClientRect(); addPoint([Number(((event.clientX - rect.left) / rect.width).toFixed(4)), Number(((event.clientY - rect.top) / rect.height).toFixed(4))]); }}>
      <img src={value.frame} alt="Frame kalibrasi kamera tanpa mirror"/>
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="none">{zones.map(z => <polygon key={z.id} points={z.polygon.map(([x, y]) => `${x * 1000},${y * 1000}`).join(' ')} className="zone-overlay"/>)}<polyline points={points.map(([x, y]) => `${x * 1000},${y * 1000}`).join(' ')} className="calibration-draft"/>{points.map(([x, y], i) => <circle key={i} cx={x * 1000} cy={y * 1000} r="6"/>)}</svg>
    </div>
    <div className="engine-form section-gap"><Field label="Nama zona live"><input maxLength={80} value={name} onChange={e => setName(e.target.value)}/></Field>
      <div className="calibration-coordinates"><Field label="Koordinat X (0 sampai 1)"><input type="number" min="0" max="1" step="0.01" value={coordinate.x} onChange={e => setCoordinate(c => ({ ...c, x: e.target.value }))}/></Field><Field label="Koordinat Y (0 sampai 1)"><input type="number" min="0" max="1" step="0.01" value={coordinate.y} onChange={e => setCoordinate(c => ({ ...c, y: e.target.value }))}/></Field><Button onClick={() => { const x = Number(coordinate.x), y = Number(coordinate.y); if (coordinate.x === '' || coordinate.y === '' || !Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > 1 || y < 0 || y > 1) setError('Koordinat harus antara 0 dan 1.'); else addPoint([x, y]); }}>Tambah titik koordinat</Button></div>
      <div className="inline-controls"><span>{points.length} titik</span><Button disabled={!points.length} onClick={() => setPoints(p => p.slice(0, -1))}>Urungkan titik</Button><Button onClick={() => { setPoints([]); setName(''); setEditing(null); }}>Batalkan zona</Button><Button disabled={zones.length >= 16 && !editing} onClick={storeZone}>Simpan zona</Button></div>
      {zones.map(z => <div key={z.id} className="calibration-zone-row"><strong>{z.name}</strong><span>{z.polygon.length} titik</span><Button disabled={!!points.length} onClick={() => { setEditing(z.id); setName(z.name); setPoints(z.polygon); }}>Edit zona</Button><Button onClick={() => { setZones(all => all.filter(item => item.id !== z.id)); if (editing === z.id) { setEditing(null); setPoints([]); setName(''); } }}>Hapus zona</Button></div>)}
      <div className="calibration-rules">{[['occupied_confirm_seconds', 'Konfirmasi terisi (detik)', 0.1, 60], ['empty_confirm_seconds', 'Konfirmasi kosong (detik)', 0.1, 120], ['max_evidence_gap_seconds', 'Batas gap frame (detik)', 0.5, 10]].map(([key, label, min, max]) => <Field key={key} label={label}><input type="number" min={min} max={max} step="0.1" value={rules[key]} onChange={e => setRules(r => ({ ...r, [key]: e.target.value === '' ? '' : Number(e.target.value) }))}/></Field>)}</div>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="modal-actions"><Button onClick={onClose}>Batal</Button><Button variant="primary" disabled={!zones.length || live.busy || live.active} onClick={save}>Simpan kalibrasi live</Button></div>
    </div>
  </Modal>;
}
