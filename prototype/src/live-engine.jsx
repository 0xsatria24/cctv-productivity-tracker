import { useEffect, useRef, useState } from 'react';
import { Button, Field, Modal, Panel, Status } from './components';
import { engineRequest, seconds } from './engine-client';
import { validPolygon } from './domain';
import { Check } from 'lucide-react';
import { monitoringText, reasonText } from './operations-domain.mjs';

export function useLiveEngine(webcam, engine) {
  const [state, setState] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false), [receivedAt, setReceivedAt] = useState(null);
  const [ownedSession, setOwnedSession] = useState(null), [cameraKey, setCameraKey] = useState(null);
  const current = useRef(null), owned = useRef(null), previousStream = useRef(null);
  current.current = state; owned.current = ownedSession;
  useEffect(() => {
    const abort = new AbortController(); let timer;
    async function poll() {
      try { const value = await engineRequest('live', { signal: abort.signal }); if (!abort.signal.aborted) { setState(value); setError(''); setReceivedAt(Date.now()); } }
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
    try { const value = await engineRequest(`live/${path}`, { method: 'POST', body: JSON.stringify(body) }); setState(value); setReceivedAt(Date.now()); engine.reload(); return value; }
    catch (failure) { setError(failure.message); throw failure; }
    finally { setBusy(false); }
  }
  async function start(source, url, preview = false, cameraId) {
    const value = await action('start', { source, ...(cameraId ? {camera_id:cameraId} : url ? { url } : {}), preview_only: preview, camera_key: source === 'WEBCAM_LIVE' ? cameraKey : undefined });
    setOwnedSession(value.session_id);
    if (!preview) engine.setDataset('live');
    return value;
  }
  async function stop() {
    if (!state?.session_id) return;
    await action('stop', { session_id: state.session_id }); setOwnedSession(null);
  }
  const active = ['STARTING', 'RUNNING', 'STOPPING'].includes(state?.status);
  return { state, active, error, busy, receivedAt, start, stop, action, cameraKey,
    webcamSession: ownedSession && state?.session_id === ownedSession && state?.source === 'WEBCAM_LIVE' && state?.status === 'RUNNING' ? ownedSession : null,
    webcamStarting: !!ownedSession && state?.source === 'WEBCAM_LIVE' && state?.status === 'STARTING' };
}

export function LiveEnginePanel({ live, webcam, engine, onReports, hidePreview = false, cameras = [], selected = 'webcam', onSelect, onAdd }) {
  const selectedCamera=cameras.find(c=>c.id===selected)||{id:'webcam',name:'Webcam lokal'};
  const camera=live.active?(cameras.find(c=>live.state?.source==='WEBCAM_LIVE'?c.id==='webcam':c.camera_key===live.state?.camera_key)||selectedCamera):selectedCamera;
  const source=camera.id==='webcam'?'WEBCAM_LIVE':'RTSP_LIVE';
  const sourceError=live.state?.source===source&&(source==='WEBCAM_LIVE'||live.state?.camera_key===camera.camera_key)?live.state?.error:null;
  const [step, setStep] = useState(1), [calibration, setCalibration] = useState(null), [notice, setNotice] = useState('');
  const working = live.busy || ['STARTING', 'STOPPING'].includes(live.state?.status);
  const recording = live.active && !live.state?.preview_only;
  const connected = source === 'WEBCAM_LIVE' ? webcam.status === 'LIVE' : live.active && live.state?.source === 'RTSP_LIVE' && live.state.camera_health === 'ONLINE' && camera.camera_key===live.state.camera_key;
  const key = source === 'WEBCAM_LIVE' ? live.cameraKey : camera.camera_key;
  const profile = live.state?.calibrations?.[source];
  const width = source === 'WEBCAM_LIVE' ? webcam.width : live.state?.latest?.width;
  const height = source === 'WEBCAM_LIVE' ? webcam.height : live.state?.latest?.height;
  const validProfile = !!profile && !!key && profile.camera_key === key && (!width || !height || Math.abs(width / height - profile.width / profile.height) <= 0.02);
  useEffect(() => { if(!live.active){setStep(1);setNotice('');} }, [camera.id]);
  useEffect(() => { if (recording) setStep(4); else if (step === 2 && connected) setStep(validProfile ? 4 : 3); }, [recording, connected, validProfile, step]);
  async function stopAndWait() {
    await live.stop();
    const deadline = performance.now() + 12000;
    while (performance.now() < deadline) {
      const value = await engineRequest('live');
      if (value.status === 'FAILED') throw new Error('Sesi berakhir dengan gangguan. Periksa diagnostik dan catatan yang tersimpan.');
      if (!['STARTING', 'RUNNING', 'STOPPING'].includes(value.status)) return;
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    throw new Error('Sesi masih diselesaikan. Tunggu status berhenti sebelum melanjutkan.');
  }
  async function connect() {
    setNotice('');
    try {
      if (source === 'WEBCAM_LIVE') await webcam.start();
      else { await live.start(source, null, true, camera.id); }
    } catch (failure) { setNotice(failure.message); }
  }
  async function calibrate() {
    setNotice('');
    try {
      const element = source === 'WEBCAM_LIVE' ? document.querySelector('video[aria-label="Preview webcam lokal"]') : document.querySelector('img[aria-label="Preview RTSP lokal"]');
      const w = source === 'WEBCAM_LIVE' ? element?.videoWidth : element?.naturalWidth;
      const h = source === 'WEBCAM_LIVE' ? element?.videoHeight : element?.naturalHeight;
      if (!element || !w || !h || !connected || !key) throw new Error('Hubungkan kamera dan tunggu gambar baru sebelum mengatur zona.');
      const canvas = document.createElement('canvas'); canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(element, 0, 0, w, h);
      const frame = canvas.toDataURL('image/jpeg', 0.8);
      if (live.active) await stopAndWait();
      setCalibration({ frame, width: w, height: h, camera_key: key, source, profile: validProfile ? profile : null });
    } catch (failure) { setNotice(failure.message); }
  }
  async function begin() {
    setNotice('');
    try {
      if (!validProfile) throw new Error('Atur dan simpan zona untuk kamera ini terlebih dahulu.');
      if (live.active && live.state?.preview_only) await stopAndWait();
      await live.start(source, null, false, source==='RTSP_LIVE'?camera.id:undefined); engine.toast('Sesi monitoring dimulai. Menunggu konfirmasi observasi zona.');
    } catch (failure) { setNotice(failure.message); }
  }
  const completed = [true, connected, validProfile, recording];
  const steps = ['Pilih kamera', 'Cek koneksi', 'Atur zona', 'Mulai monitoring'];
  return <Panel title="Setup monitoring" caption="Ikuti langkah berikut untuk menghasilkan catatan workstation." className="live-engine-panel setup-panel" action={<Status value={recording && live.state?.camera_health === 'ONLINE' ? 'ONLINE' : live.state?.status === 'FAILED' ? 'OFFLINE' : 'DISABLED'} label={monitoringText(live.state, live.error)}/>}>
    <ol className="setup-progress">{steps.map((label, i) => <li key={label}><button type="button" aria-current={step === i + 1 ? 'step' : undefined} disabled={recording && i < 3} onClick={() => setStep(i + 1)}><span>{completed[i] && i > 0 ? <Check size={14}/> : i + 1}</span><strong>{label}</strong><small>{i === 0 ? source === 'WEBCAM_LIVE' ? 'Webcam lokal' : 'Kamera RTSP' : completed[i] ? 'Selesai' : 'Belum selesai'}</small></button></li>)}</ol>
    <div className="setup-step-content" aria-busy={working}>
      {step === 1 && <><h3>1. Pilih sumber kamera</h3><Field label="Kamera untuk monitoring"><select value={camera.id} disabled={live.active||working} onChange={e=>onSelect(e.target.value)}>{cameras.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field><p>Sumber yang sama digunakan untuk preview, zona, dan pencatatan. Analisis durasi memproses satu kamera aktif.</p>{source==='WEBCAM_LIVE'&&<Field label="Perangkat webcam"><select value={webcam.device} disabled={!!webcam.stream} onChange={e=>webcam.setDevice(e.target.value)}><option value="">Kamera default sistem</option>{webcam.devices.filter(d=>d.deviceId).map((d,i)=><option key={d.deviceId} value={d.deviceId}>{d.label||`Webcam ${i+1}`}</option>)}</select></Field>}<div className="inline-controls"><Button variant="primary" onClick={()=>setStep(2)}>Lanjut ke cek koneksi</Button><Button onClick={onAdd}>Tambah kamera RTSP</Button></div></>}
      {step === 2 && <><h3>2. Pastikan gambar kamera tersedia</h3><p>{camera.name}. {connected?'Kamera terhubung. Lanjutkan untuk menentukan batas workstation.':source==='WEBCAM_LIVE'?'Hubungkan webcam dan izinkan akses kamera di browser. Gambar tampil pada grid di bawah.':'Uji sumber RTSP yang dipilih dari daftar. Tunggu gambar baru dan status terhubung.'}</p><Status value={connected?'ONLINE':'DISABLED'} label={connected?'Gambar kamera tersedia':working?'Menghubungkan dan menyiapkan analisis':'Menunggu koneksi'}/>{!connected&&<Button variant="primary" disabled={working||live.active||['REQUESTING','CANCELLING'].includes(webcam.status)} onClick={connect}>{source==='WEBCAM_LIVE'?'Hubungkan webcam':'Uji preview RTSP'}</Button>}<div className="inline-controls"><Button disabled={!connected} onClick={()=>setStep(validProfile?4:3)}>Lanjut ke zona</Button>{live.state?.preview_only&&<Button disabled={working} onClick={()=>stopAndWait().catch(failure=>setNotice(failure.message))}>Hentikan preview</Button>}</div></>}
      {step === 3 && <><h3>3. Tentukan zona workstation</h3><p>{validProfile ? `${profile.zones.length} zona tersimpan untuk kamera ini. Ubah jika posisi kamera atau workstation berubah.` : profile ? key ? 'Kalibrasi tersimpan belum sesuai dengan kamera atau rasio gambar ini. Atur ulang zona.' : 'Hubungkan kamera untuk memeriksa kalibrasi yang tersimpan.' : 'Gambar batas area orang berada di workstation. Nama setiap zona akan muncul pada laporan.'}</p><Button variant="primary" disabled={working || recording || !connected} onClick={calibrate}>Atur zona</Button>{validProfile && <Button onClick={() => setStep(4)}>Lanjut ke monitoring</Button>}{!connected && <Button onClick={() => setStep(2)}>Kembali ke cek koneksi</Button>}</>}
      {step === 4 && <><h3>{recording ? '4. Monitoring berjalan' : '4. Mulai sesi monitoring'}</h3><p>{camera.name}. {recording ? 'Observasi zona disimpan otomatis. Kamera yang kehilangan bukti akan ditandai tidak diketahui.' : validProfile ? `${profile.zones.length} zona siap. Durasi mulai dicatat setelah sesi berjalan dan bukti kamera dikonfirmasi.` : 'Lengkapi koneksi dan kalibrasi zona sebelum memulai.'}</p><div className="inline-controls"><Button variant="primary" disabled={working || recording || !validProfile || (source === 'WEBCAM_LIVE' && !webcam.stream)} onClick={begin}>{working && live.state?.status === 'STARTING' ? 'Menyiapkan monitoring...' : 'Mulai monitoring'}</Button><Button disabled={!live.active || working} onClick={() => stopAndWait().then(() => engine.toast('Sesi monitoring dihentikan; catatan yang tersimpan tetap tersedia.')).catch(failure => setNotice(failure.message))}>Hentikan monitoring</Button><Button onClick={onReports || (() => engine.setDataset('live'))}>Lihat laporan live</Button></div>{!validProfile && <Button onClick={() => setStep(3)}>Lengkapi zona</Button>}</>}
      {(notice || live.error || sourceError) && <p role="alert" className="error-text">{notice || live.error || sourceError}</p>}
      {live.state?.run_id && <p className="caption">Sesi {live.state.run_id.slice(0, 8)} · {live.state.processed} observasi tersimpan. Video tidak direkam.</p>}
    </div>
    {live.state?.latest?.zones && <div className="live-zone-states">{live.state.latest.zones.map(z => <div key={z.id}><strong>{z.name}</strong><Status value={z.state}/><span>{z.count == null ? 'Jumlah belum dapat dipastikan' : `${z.count} orang teramati`} · {seconds(z.evidence_until_utc_us - z.state_since_utc_us)} pada status ini</span>{z.reason && <small>{reasonText(z.reason)}</small>}</div>)}</div>}
    {calibration && <CalibrationDialog value={calibration} live={live} onSaved={() => { setCalibration(null); setStep(4); engine.toast('Kalibrasi zona berhasil disimpan untuk kamera ini.'); }} onClose={() => setCalibration(null)}/>}
  </Panel>;
}

function CalibrationDialog({ value, live, onClose, onSaved }) {
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
    try { await live.action('calibration', { source: value.source, width: value.width, height: value.height, camera_key: value.camera_key, zones, rules }); (onSaved || onClose)(); }
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
