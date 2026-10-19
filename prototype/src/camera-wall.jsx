import { useEffect, useRef, useState } from 'react';
import { Camera, ChevronLeft, ChevronRight, ListVideo, Maximize, Plus, Search, Trash2, X } from 'lucide-react';
import { Button, Field, Modal, Status } from './components';
import { engineRequest } from './engine-client';
import { WebcamPanel } from './webcam';
import { CAMERA_MODES, cameraView } from './camera-layout.mjs';
import './camera-wall.css';
import { ManagedCameraControls } from './managed-camera';
import { TrackCaption } from './track-caption';

const LAYOUTS = [1, 4, 9, 16];
const HEALTH = { ONLINE: 'Live', CONNECTING: 'Menghubungkan', RECONNECTING: 'Menghubungkan ulang', STALLED: 'Frame terhenti', PAUSED: 'Preview dijeda', OFFLINE: 'Tidak terhubung' };
function preference() {
  try {
    const value = JSON.parse(localStorage.getItem('cctv-camera-wall') || '{}');
    return { layout: LAYOUTS.includes(value.layout) ? value.layout : 4, mode: CAMERA_MODES.some(mode => mode.value === value.mode) ? value.mode : 'grid', list: value.list !== false,
      detections: value.detections === true, zones: value.zones !== false };
  } catch { return { layout: 4, mode: 'grid', list: true, detections: false, zones: true }; }
}

function useCameraRegistry(visibleIds) {
  const [cameras, setCameras] = useState([]), [error, setError] = useState('');
  const viewer = useRef(crypto.randomUUID());
  useEffect(() => {
    const abort = new AbortController(); let timer;
    async function poll() {
      try { const value = await engineRequest('camera-wall', { signal: abort.signal }); if (!abort.signal.aborted) { setCameras(value.cameras); setError(''); } }
      catch (failure) { if (!abort.signal.aborted) setError(failure.message); }
      finally { if (!abort.signal.aborted) timer = setTimeout(poll, 1000); }
    }
    poll(); return () => { abort.abort(); clearTimeout(timer); };
  }, []);
  const subscription = JSON.stringify(visibleIds);
  useEffect(() => {
    const abort = new AbortController(); let timer;
    async function heartbeat() {
      try { await engineRequest('camera-wall/view', { method: 'POST', signal: abort.signal, body: JSON.stringify({ viewer_id: viewer.current, camera_ids: JSON.parse(subscription) }) }); }
      catch (failure) { if (!abort.signal.aborted) setError(failure.message); }
      finally { if (!abort.signal.aborted && JSON.parse(subscription).length) timer = setTimeout(heartbeat, 4000); }
    }
    heartbeat(); return () => { abort.abort(); clearTimeout(timer); };
  }, [subscription]);
  useEffect(() => () => {
    fetch('/pilot/v1/camera-wall/view', { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ viewer_id: viewer.current, camera_ids: [] }) }).catch(() => {});
  }, []);
  async function add(name, url) {
    const value = await engineRequest('camera-wall/cameras', { method: 'POST', body: JSON.stringify({ name, url }) });
    setCameras(current => [...current.filter(c => c.id !== value.id), value]); return value;
  }
  async function remove(id) {
    await engineRequest(`camera-wall/cameras/${id}`, { method: 'DELETE', timeoutMs: 30000 });
    setCameras(current => current.filter(c => c.id !== id));
  }
  return { cameras, error, add, remove };
}

function RtspTile({ camera, visible, onFocus, latest, zones = [], showDetections, showZones }) {
  const [frame, setFrame] = useState(null), [size, setSize] = useState(null), [dimensions, setDimensions] = useState(null), [bounds, setBounds] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const frameArea = useRef(null);
  useEffect(() => {
    if (!dimensions || !frameArea.current || !visible) { setBounds(null); return; }
    const area = frameArea.current;
    const measure = () => {
      const scale = Math.min(area.clientWidth / dimensions.width, area.clientHeight / dimensions.height);
      const width = dimensions.width * scale, height = dimensions.height * scale;
      setBounds({ left: (area.clientWidth - width) / 2, top: (area.clientHeight - height) / 2, width, height });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(area); measure();
    return () => observer.disconnect();
  }, [dimensions, visible]);
  useEffect(() => {
    setFrame(null); setSize(null);
    if (!visible) return;
    let cancelled = false, timer, object, received = 0;
    const abort = new AbortController();
    async function poll() {
      const started = performance.now();
      const request = new AbortController(), cancel = () => request.abort();
      abort.signal.addEventListener('abort', cancel, { once: true });
      const timeout = setTimeout(cancel, 4000);
      try {
        const url = camera.id === 'engine-rtsp' || camera.source === 'RTSP_ENGINE' && !camera.managed ? '/pilot/v1/live/preview.jpg' : `/pilot/v1/camera-wall/cameras/${camera.id}/frame.jpg?smooth=true`;
        const response = await fetch(url, { cache: 'no-store', signal: request.signal });
        if (!response.ok) throw new Error('No fresh frame');
        const next = URL.createObjectURL(await response.blob());
        if (cancelled) { URL.revokeObjectURL(next); return; }
        if (object) URL.revokeObjectURL(object);
        object = next; received = performance.now();
        setFrame({ url: next, time: response.headers.get('X-Frame-Time') });
      } catch { if (!cancelled) { setFrame(null); setSize(null); } }
      finally {
        clearTimeout(timeout); abort.signal.removeEventListener('abort', cancel);
        if (!cancelled) timer = setTimeout(poll, Math.max(0, 1000 / 24 - (performance.now() - started)));
      }
    }
    poll();
    const stale = setInterval(() => { if (received && performance.now() - received > 2500) { setFrame(null); setSize(null); } }, 500);
    return () => { cancelled = true; abort.abort(); clearTimeout(timer); clearInterval(stale); if (object) URL.revokeObjectURL(object); };
  }, [camera.id, camera.source, camera.analysis, visible]);
  useEffect(() => {
    setAnalysis(null);
    if (!visible || !camera.managed || !camera.analysis) return;
    const abort = new AbortController();
    let timer, expiry;
    async function poll() {
      const started = performance.now();
      try {
        const packet = await engineRequest(`camera-wall/cameras/${camera.id}/observation?metadata_only=true`, {signal: abort.signal, timeoutMs: 2000});
        if (abort.signal.aborted) return;
        clearTimeout(expiry);
        // Subtract the full request time conservatively; never renew an old
        // result indefinitely just because the HTTP endpoint still responds.
        const remaining = packet.valid_for_ms - (performance.now() - started);
        setAnalysis(remaining > 0 && packet.observation ? {...packet.observation,presentation_age_ms:packet.source_age_ms || 0} : null);
        if (remaining > 0) expiry = setTimeout(() => setAnalysis(null), remaining);
      } catch { /* Keep the previous measured result only until its expiry. */ }
      finally { if (!abort.signal.aborted) timer = setTimeout(poll, Math.max(0, 200 - (performance.now() - started))); }
    }
    poll();
    return () => { abort.abort(); clearTimeout(timer); clearTimeout(expiry); };
  }, [camera.id, camera.managed, camera.analysis, visible]);
  const health = frame && camera.health === 'ONLINE' ? 'ONLINE' : camera.health === 'ONLINE' ? 'CONNECTING' : camera.health;
  const detection = frame && visible && camera.analysis && health === 'ONLINE' ? (camera.managed ? analysis : latest) : null;
  return <section className="rtsp-wall-panel">
    <header className="camera-tile-heading"><h2>{camera.name}</h2><Status value={health === 'PAUSED' ? 'DISABLED' : health === 'STALLED' ? 'DEGRADED' : health} label={HEALTH[health] || health}/><Button icon={Maximize} aria-label={`Fokus ${camera.name}`} onClick={onFocus}/></header>
    <div className="camera-frame" ref={frameArea}>
      {frame ? <><img src={frame.url} alt={`Preview ${camera.name}`} aria-label={camera.id === 'engine-rtsp' || camera.source === 'RTSP_ENGINE' ? 'Preview RTSP lokal' : `Preview ${camera.name}`} onLoad={e => { const width = e.currentTarget.naturalWidth, height = e.currentTarget.naturalHeight; setSize(`${width} × ${height}`); setDimensions(current => current?.width === width && current?.height === height ? current : { width, height }); }} onError={() => { setFrame(null); setSize(null); }}/>
        {bounds && <svg className="rtsp-camera-overlays" style={bounds} viewBox={`0 0 ${dimensions.width} ${dimensions.height}`} preserveAspectRatio="none" aria-label={detection ? `${detection.count} orang terdeteksi` : 'Overlay kamera'}>
          {showZones && camera.analysis && zones.map(zone => <polygon key={zone.id} points={zone.polygon.map(([x, y]) => `${x * dimensions.width},${y * dimensions.height}`).join(' ')} className="rtsp-zone-outline"/>)}
          {showDetections && detection?.detections.map((row, i) => {
            const box = row.display_box || row.box;
            return <g key={row.track_id || i} data-testid="rtsp-person-detection">
              <rect x={box[0]*dimensions.width} y={box[1]*dimensions.height} width={(box[2]-box[0])*dimensions.width} height={(box[3]-box[1])*dimensions.height} className="person-box"/>
              <TrackCaption row={row} width={dimensions.width} height={dimensions.height} fontSize={Math.max(8,8*dimensions.width/Math.max(1,bounds.width))} ageMs={detection.presentation_age_ms}/>
            </g>;
          })}
        </svg>}</>
        : <div className="camera-no-signal"><Camera size={24} aria-hidden="true"/><strong>{HEALTH[health] || 'Menunggu gambar'}</strong><p>{camera.error || 'Gambar muncul setelah koneksi kamera tersedia.'}</p></div>}
    </div>
    <div className="camera-tile-info"><span data-testid="rtsp-detection-status">{camera.analysis ? detection ? `${detection.count} orang terdeteksi · ${detection.inference_ms} ms` : 'Menunggu hasil deteksi' : 'Preview saja'}</span><span>{size || 'Resolusi belum tersedia'}</span></div>
    <footer className="camera-tile-footer"><span>{camera.analysis ? camera.recorded ? 'Pencatatan live aktif' : 'Pencatatan belum dimulai' : 'Deteksi dan pencatatan belum aktif'}</span><time>{frame?.time ? new Date(Number(frame.time)).toLocaleTimeString('id-ID', { timeZone: camera.timezone }) : 'Waktu frame belum tersedia'}</time></footer>
  </section>;
}

export function CameraWorkspace({ webcam, live, engine, page, onHealthChange }) {
  const [prefs, setPrefs] = useState(preference), [search, setSearch] = useState(''), [hidden, setHidden] = useState([]);
  const [selected, setSelected] = useState('webcam'), [gridPage, setGridPage] = useState(0), [focusPage, setFocusPage] = useState(0);
  const [dialog, setDialog] = useState(null), [notice, setNotice] = useState(''), [fullscreen, setFullscreen] = useState(false);
  const [documentVisible, setDocumentVisible] = useState(!document.hidden), [subscribed, setSubscribed] = useState([]);
  const viewport = useRef(null), registry = useCameraRegistry(subscribed);
  const visible = page === 'live';
  const engineCameraKey = live.state?.source === 'RTSP_LIVE' ? live.state.camera_key : null;
  const matchingPreview = registry.cameras.find(c => c.camera_key === engineCameraKey);
  const sources = [{ id: 'webcam', name: 'Webcam lokal', source: 'WEBCAM', health: webcam.status === 'LIVE' ? 'ONLINE' : webcam.status === 'ERROR' ? 'OFFLINE' : 'PAUSED' },
    ...(engineCameraKey && !matchingPreview ? [{ id: 'engine-rtsp', name: 'CCTV sesi engine', source: 'RTSP', health: live.active ? live.state.camera_health : 'PAUSED', analysis: live.active && live.state?.camera_health === 'ONLINE', recorded: live.state?.latest?.recorded, error: live.state?.error }] : []),
    ...registry.cameras.map(c => c.id === matchingPreview?.id && live.active ? { ...c, managed: false, source: 'RTSP_ENGINE', health: live.state.camera_health, analysis: live.state.camera_health === 'ONLINE', recorded: live.state?.latest?.recorded, error: live.state.error } : c)].map(c => ({ ...c, timezone: engine.snapshot?.timezone || 'Asia/Jakarta' }));
  const healthKey = JSON.stringify(sources.map(c => ({ id: c.id, name: c.name, health: engine.connectionError && c.id !== 'webcam' ? 'UNKNOWN' : c.health, analysis: c.analysis || false })));
  useEffect(() => { onHealthChange?.(JSON.parse(healthKey)); }, [healthKey, onHealthChange]);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 5500); return () => clearTimeout(timer); }, [notice]);
  const enabled = sources.filter(c => !hidden.includes(c.id));
  const { displayed, primaryId, capacity: count, pages, currentPage } = cameraView(enabled, { mode: prefs.mode, layout: prefs.layout, selected, page: prefs.mode === 'focus' ? focusPage : gridPage });
  const selectedCamera = sources.find(c => c.id === selected);
  const showList = prefs.list && prefs.mode !== 'wall';
  const enabledKey = JSON.stringify(enabled.map(c => c.id));
  const slots = Array.from({ length: count }, (_, i) => displayed[i] || null);
  const visibleKey = JSON.stringify(visible && documentVisible ? displayed.filter(c => c.source === 'RTSP_PREVIEW').map(c => c.id) : []);
  useEffect(() => { setSubscribed(JSON.parse(visibleKey)); }, [visibleKey]);
  useEffect(() => { try { localStorage.setItem('cctv-camera-wall', JSON.stringify(prefs)); } catch {} }, [prefs]);
  useEffect(() => {
    const changed = () => setDocumentVisible(!document.hidden);
    document.addEventListener('visibilitychange', changed); return () => document.removeEventListener('visibilitychange', changed);
  }, []);
  useEffect(() => {
    const ids = JSON.parse(enabledKey);
    if (!ids.includes(selected)) setSelected(ids[0] || null);
  }, [enabledKey, selected]);
  useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === viewport.current);
    const key = e => { if (e.key === 'Escape' && !document.querySelector('dialog[open]') && !e.target.closest('input,select,textarea')) setPrefs(p => p.mode === 'focus' ? { ...p, mode: 'grid' } : p); };
    document.addEventListener('fullscreenchange', changed); window.addEventListener('keydown', key);
    return () => { document.removeEventListener('fullscreenchange', changed); window.removeEventListener('keydown', key); };
  }, []);
  useEffect(() => {
    if (!visible && document.fullscreenElement === viewport.current) document.exitFullscreen().catch(() => {});
  }, [visible]);
  function choose(id) {
    setSelected(id);
    const next = sources.filter(c => c.id === id || !hidden.includes(c.id));
    setHidden(h => h.filter(item => item !== id));
    setGridPage(Math.floor(next.findIndex(c => c.id === id) / prefs.layout));
  }
  function focusCamera(id) { choose(id); setPrefs(p => ({ ...p, mode: 'focus' })); }
  function changeMode(mode) {
    if (mode !== 'focus' && prefs.mode === 'focus') {
      const index = enabled.findIndex(c => c.id === selected);
      if (index >= 0) setGridPage(Math.floor(index / prefs.layout));
    }
    setPrefs(p => ({ ...p, mode }));
  }
  function changePage(delta) {
    (prefs.mode === 'focus' ? setFocusPage : setGridPage)(Math.max(0, Math.min(currentPage + delta, pages - 1)));
  }
  async function removeCamera(id) {
    await registry.remove(id);
    setDialog(null); setNotice('Kamera diarsipkan. Analisis dihentikan; histori tetap tersedia di laporan.');
  }
  return <section className={`camera-workspace ${visible && prefs.mode === 'wall' ? 'camera-workspace-wall' : ''} ${visible ? '' : 'camera-workspace-compact'} ${!visible && !webcam.stream && !['REQUESTING', 'CANCELLING'].includes(webcam.status) ? 'webcam-hidden' : ''}`} data-testid="camera-workspace" data-mode={prefs.mode}>
    <div className="camera-wall-toolbar">
      <div className="inline-controls">{prefs.mode !== 'wall' && <Button icon={ListVideo} aria-pressed={prefs.list} onClick={() => setPrefs(p => ({ ...p, list: !p.list }))}>Daftar kamera</Button>}{prefs.mode !== 'focus' && <div className="camera-layout-buttons" role="group" aria-label="Layout kamera">{LAYOUTS.map(n => <button key={n} aria-label={`Layout ${n} kamera`} aria-pressed={prefs.layout === n} onClick={() => { setPrefs(p => ({ ...p, layout: n })); setGridPage(Math.max(0, Math.floor(enabled.findIndex(c => c.id === selected) / n))); }}><span className={`layout-glyph layout-glyph-${Math.sqrt(n)}`} aria-hidden="true">{Array.from({ length: n }, (_, i) => <i key={i}/>)}</span>{n}</button>)}</div>}</div>
      <div className="inline-controls"><label className="check-control"><input type="checkbox" checked={prefs.zones} onChange={e => setPrefs(p => ({ ...p, zones: e.target.checked }))}/>Zona</label><label className="check-control"><input type="checkbox" checked={prefs.detections} onChange={e => setPrefs(p => ({ ...p, detections: e.target.checked }))}/>Deteksi</label><Button icon={Plus} variant="primary" onClick={() => setDialog({ type: 'add' })}>Tambah kamera</Button></div>
    </div>
    <div className={`camera-wall-body ${showList ? '' : 'camera-list-collapsed'}`}>
      {showList && <aside className="camera-directory" aria-label="Daftar sumber kamera">
        <div className="camera-directory-title"><h2>Kamera</h2><span>{sources.length}</span></div>
        <Field label="Cari kamera"><div className="camera-search"><Search size={14} aria-hidden="true"/><input type="search" placeholder="Nama kamera" value={search} onChange={e => setSearch(e.target.value)}/></div></Field>
        <div className="camera-directory-items">{sources.filter(c => c.name.toLowerCase().includes(search.toLowerCase())).map(c => <div key={c.id} className={`camera-directory-row ${selected === c.id ? 'selected' : ''}`}><button className="camera-directory-select" aria-pressed={selected === c.id} onClick={() => choose(c.id)}><Camera size={15} aria-hidden="true"/><span><strong>{c.name}</strong><small>{hidden.includes(c.id) ? 'Disembunyikan dari grid' : HEALTH[c.health] || c.health}</small></span></button>{(c.source === 'RTSP_PREVIEW' || c.source === 'RTSP_ENGINE') && <button className="icon-button" aria-label={`Hapus ${c.name}`} onClick={() => setDialog({ type: 'remove', camera: c })}><Trash2 size={14}/></button>}</div>)}{!sources.some(c => c.name.toLowerCase().includes(search.toLowerCase())) && <p className="camera-search-empty">Kamera tidak ditemukan.</p>}</div>
        <p className="camera-directory-note">Konfigurasi tersimpan di mesin ini. Kredensial kamera dilindungi akun sistem operasi.</p>
      </aside>}
      <div className="camera-viewport" ref={viewport} data-testid="camera-wall-viewport">
        <div className="camera-mode-toolbar"><div className="camera-mode-buttons" role="group" aria-label="Mode tampilan kamera">{CAMERA_MODES.map(mode => <button key={mode.value} type="button" aria-pressed={prefs.mode === mode.value} onClick={() => changeMode(mode.value)}>{mode.label}</button>)}</div><span className="camera-mode-description">{prefs.mode === 'focus' ? 'Satu kamera utama + lima pendamping' : prefs.mode === 'wall' ? 'Tampilan ringkas untuk monitor besar' : 'Semua kamera dengan ukuran seimbang'}</span></div>
        <div className="camera-view-heading"><span>{prefs.mode === 'focus' ? `Fokus · ${selectedCamera?.name || 'Pilih kamera'}` : `${prefs.mode === 'wall' ? 'Video wall' : 'Grid'} ${Math.sqrt(prefs.layout)} × ${Math.sqrt(prefs.layout)}`}<small>{displayed.length} sumber ditampilkan</small></span><div className="inline-controls">{prefs.mode === 'focus' && <Button icon={X} onClick={() => changeMode('grid')}>Kembali ke grid</Button>}{document.fullscreenEnabled && <Button icon={Maximize} aria-label={fullscreen ? 'Keluar layar penuh grid' : 'Layar penuh grid'} onClick={() => (fullscreen ? document.exitFullscreen() : viewport.current.requestFullscreen()).catch(() => setNotice('Layar penuh tidak tersedia pada browser ini.'))}>{fullscreen ? 'Keluar layar penuh' : 'Layar penuh'}</Button>}</div></div>
        <div className={`camera-wall-grid ${prefs.mode === 'focus' ? 'camera-grid-focus' : `camera-grid-${Math.sqrt(count)}`}`} data-testid="camera-wall-grid" data-layout={count} data-mode={prefs.mode}>
          {sources.map(camera => {
            const shown = displayed.some(c => c.id === camera.id), tileVisible = visible && documentVisible && shown;
            return <div key={camera.id} className={`camera-tile ${shown ? '' : 'camera-tile-hidden'} ${selected === camera.id ? 'camera-tile-selected' : ''} ${primaryId === camera.id ? 'camera-tile-primary' : ''}`} style={{ order: displayed.findIndex(c => c.id === camera.id) }} data-testid="camera-tile" data-camera-id={camera.id} data-primary={primaryId === camera.id ? 'true' : undefined} tabIndex={shown ? 0 : -1} aria-label={`Kamera ${camera.name}`} onClick={() => choose(camera.id)} onDoubleClick={e => { if (!e.target.closest('button,select,input')) focusCamera(camera.id); }} onKeyDown={e => { if (e.target === e.currentTarget && e.key === 'Enter') { e.preventDefault(); focusCamera(camera.id); } }}>
              {camera.id === 'webcam' ? <WebcamPanel wall webcam={{ ...webcam, showDetections: prefs.detections, showZones: prefs.zones }} onFocus={() => focusCamera(camera.id)}/>
                : <RtspTile camera={camera} visible={tileVisible} latest={camera.analysis ? live.state?.latest : null} zones={camera.managed ? camera.engine?.calibrations?.RTSP_LIVE?.zones : camera.analysis ? live.state?.calibrations?.RTSP_LIVE?.zones : undefined} showDetections={prefs.detections} showZones={prefs.zones} onFocus={() => focusCamera(camera.id)}/>}
            </div>;
          })}
          {slots.filter(c => !c).map((_, i) => <button key={`empty-${i}`} className="camera-empty-tile" style={{ order: displayed.length + i }} data-testid="camera-empty-slot" onClick={() => setDialog({ type: 'add' })}><Plus size={20} aria-hidden="true"/><strong>Tambah kamera</strong><span>Hubungkan sumber RTSP</span></button>)}
        </div>
        <div className="camera-wall-pagination"><span>{sources.filter(c => c.health === 'ONLINE').length} kamera terhubung · {engine.recordings?.data?.policy.video_enabled ? 'Rekaman video aktif' : 'Rekaman video nonaktif'}</span><div className="inline-controls">{prefs.mode === 'focus' && <span>Kamera pendamping</span>}<Button icon={ChevronLeft} aria-label="Halaman kamera sebelumnya" disabled={currentPage === 0} onClick={() => changePage(-1)}/><span>{currentPage + 1} / {pages}</span><Button icon={ChevronRight} aria-label="Halaman kamera berikutnya" disabled={currentPage >= pages - 1} onClick={() => changePage(1)}/></div></div>
      </div>
    </div>
    <div className="camera-selection-bar"><div><span>KAMERA DIPILIH</span><strong>{selectedCamera?.name || 'Pilih kamera'}</strong></div><p>{selectedCamera?.id === 'webcam' ? 'Analisis orang tersedia dari webcam. Kalibrasikan zona untuk mencatat durasi.' : selectedCamera?.analysis ? 'Sumber ini sedang diproses oleh engine live.' : 'Sumber ini menayangkan preview. Deteksi dan pencatatan belum diaktifkan untuk kamera ini.'}</p><Button disabled={!selectedCamera} onClick={() => focusCamera(selected)}>Fokus kamera</Button><Button disabled={!selectedCamera || hidden.includes(selected)} onClick={() => setHidden(h => [...h, selected])}>Sembunyikan dari grid</Button></div>
    {(notice || registry.error) && <p className="camera-wall-notice" role="status">{notice || `Daftar RTSP belum tersedia: ${registry.error}`}</p>}
    {selectedCamera?.managed && <ManagedCameraControls key={selectedCamera.id} camera={selectedCamera} engine={engine}/>}
    <p className="camera-analysis-note">Working / Idle adalah indikator gerak visual; diam belum membuktikan istirahat. Durasi pada box adalah usia track, bukan durasi produktif. Pilih kamera untuk mengatur zona dan memulai analisis. Analisis RTSP tetap berjalan saat pindah halaman; kapasitas bergantung pada perangkat dan kelengkapan observasi.</p>
    {dialog?.type === 'add' && <AddCameraDialog onClose={() => setDialog(null)} onSave={async (name, url) => { const camera = await registry.add(name, url); setDialog(null); setHidden(h => h.filter(id => id !== camera.id)); setSelected(camera.id); setFocusPage(0); setGridPage(Math.floor(enabled.length / prefs.layout)); }}/>}
    {dialog?.type === 'remove' && <RemoveCameraDialog camera={dialog.camera} onClose={() => setDialog(null)} onRemove={() => removeCamera(dialog.camera.id)}/>}
  </section>;
}

function RemoveCameraDialog({ camera, onClose, onRemove }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const pending = useRef(false);
  async function remove() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError('');
    try { await onRemove(); }
    catch (failure) { setError(failure.message); }
    finally { pending.current = false; setBusy(false); }
  }
  return <Modal title="Arsipkan kamera?" description={`${camera.name} akan dihentikan dan dikeluarkan dari grid. Histori laporan tetap tersimpan.`} onClose={busy ? () => {} : onClose}>
    {busy && <p role="status">Menghentikan kamera dan menyimpan catatan terakhir...</p>}
    {error && <p role="alert" className="error-text">{error}</p>}
    <div className="modal-actions"><Button disabled={busy} onClick={onClose}>Batal</Button><Button variant="danger" disabled={busy} aria-busy={busy} onClick={remove}>{busy ? 'Mengarsipkan...' : 'Hapus kamera'}</Button></div>
  </Modal>;
}

function AddCameraDialog({ onClose, onSave }) {
  const [name, setName] = useState(''), [url, setUrl] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function save(e) {
    e.preventDefault(); setBusy(true); setError('');
    try { await onSave(name.trim(), url.trim()); }
    catch (failure) { setError(failure.message); setBusy(false); }
  }
  return <Modal title="Tambah kamera RTSP" description="Hubungkan kamera atau substream NVR ke grid. Koneksi diuji setelah kamera ditambahkan." onClose={busy ? () => {} : onClose}><form className="engine-form" onSubmit={save}><Field label="Nama kamera"><input required maxLength={80} placeholder="Contoh: Area produksi 01" value={name} onChange={e => setName(e.target.value)} disabled={busy}/></Field><Field label="Alamat RTSP" hint="Gunakan stream dengan detail orang yang memadai. URL disimpan terenkripsi di mesin ini."><input type="password" required autoComplete="off" maxLength={2048} placeholder="rtsp://user:password@kamera:554/stream" value={url} onChange={e => setUrl(e.target.value)} disabled={busy}/></Field>{error && <p className="error-text" role="alert">{error}</p>}<div className="modal-actions"><Button type="button" disabled={busy} onClick={onClose}>Batal</Button><Button type="submit" variant="primary" disabled={busy || !name.trim() || !url.trim()}>{busy ? 'Menghubungkan...' : 'Tambahkan ke grid'}</Button></div></form></Modal>;
}
