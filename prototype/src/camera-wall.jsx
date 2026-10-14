import { useEffect, useRef, useState } from 'react';
import { Camera, ChevronLeft, ChevronRight, ListVideo, Maximize, Plus, Search, Trash2, X } from 'lucide-react';
import { Button, Field, Modal, Status } from './components';
import { engineRequest } from './engine-client';
import { WebcamPanel } from './webcam';
import './camera-wall.css';

const LAYOUTS = [1, 4, 9, 16];
const HEALTH = { ONLINE: 'Live', CONNECTING: 'Menghubungkan', RECONNECTING: 'Menghubungkan ulang', STALLED: 'Frame terhenti', PAUSED: 'Preview dijeda', OFFLINE: 'Tidak terhubung' };
function preference() {
  try {
    const value = JSON.parse(localStorage.getItem('cctv-camera-wall') || '{}');
    return { layout: LAYOUTS.includes(value.layout) ? value.layout : 4, list: value.list !== false,
      detections: value.detections === true, zones: value.zones !== false };
  } catch { return { layout: 4, list: true, detections: false, zones: true }; }
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
    await engineRequest(`camera-wall/cameras/${id}`, { method: 'DELETE' });
    setCameras(current => current.filter(c => c.id !== id));
  }
  return { cameras, error, add, remove };
}

function RtspTile({ camera, visible, onFocus }) {
  const [frame, setFrame] = useState(null), [size, setSize] = useState(null);
  useEffect(() => {
    setFrame(null); setSize(null);
    if (!visible) return;
    let cancelled = false, timer, object, received = 0;
    const abort = new AbortController();
    async function poll() {
      const request = new AbortController(), cancel = () => request.abort();
      abort.signal.addEventListener('abort', cancel, { once: true });
      const timeout = setTimeout(cancel, 4000);
      try {
        const url = camera.id === 'engine-rtsp' || camera.source === 'RTSP_ENGINE' ? '/pilot/v1/live/preview.jpg' : `/pilot/v1/camera-wall/cameras/${camera.id}/frame.jpg`;
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
        if (!cancelled) timer = setTimeout(poll, 500);
      }
    }
    poll();
    const stale = setInterval(() => { if (received && performance.now() - received > 2500) { setFrame(null); setSize(null); } }, 500);
    return () => { cancelled = true; abort.abort(); clearTimeout(timer); clearInterval(stale); if (object) URL.revokeObjectURL(object); };
  }, [camera.id, camera.source, visible]);
  const health = frame && camera.health === 'ONLINE' ? 'ONLINE' : camera.health === 'ONLINE' ? 'CONNECTING' : camera.health;
  return <section className="rtsp-wall-panel">
    <header className="camera-tile-heading"><h2>{camera.name}</h2><Status value={health === 'PAUSED' ? 'DISABLED' : health === 'STALLED' ? 'DEGRADED' : health} label={HEALTH[health] || health}/><Button icon={Maximize} aria-label={`Fokus ${camera.name}`} onClick={onFocus}/></header>
    <div className="camera-frame">
      {frame ? <img src={frame.url} alt={`Preview ${camera.name}`} aria-label={camera.id === 'engine-rtsp' || camera.source === 'RTSP_ENGINE' ? 'Preview RTSP lokal' : `Preview ${camera.name}`} onLoad={e => setSize(`${e.currentTarget.naturalWidth} × ${e.currentTarget.naturalHeight}`)} onError={() => { setFrame(null); setSize(null); }}/>
        : <div className="camera-no-signal"><Camera size={24} aria-hidden="true"/><strong>{HEALTH[health] || 'Menunggu gambar'}</strong><p>{camera.error || 'Gambar muncul setelah koneksi kamera tersedia.'}</p></div>}
    </div>
    <div className="camera-tile-info"><span>{camera.analysis ? 'Engine deteksi aktif' : 'Preview saja'}</span><span>{size || 'Resolusi belum tersedia'}</span></div>
    <footer className="camera-tile-footer"><span>{camera.analysis ? camera.recorded ? 'Pencatatan live aktif' : 'Pencatatan belum dimulai' : 'Deteksi dan pencatatan belum aktif'}</span><time>{frame?.time ? new Date(Number(frame.time)).toLocaleTimeString('id-ID', { timeZone: camera.timezone }) : 'Waktu frame belum tersedia'}</time></footer>
  </section>;
}

export function CameraWorkspace({ webcam, live, engine, page }) {
  const [prefs, setPrefs] = useState(preference), [search, setSearch] = useState(''), [hidden, setHidden] = useState([]);
  const [selected, setSelected] = useState('webcam'), [focus, setFocus] = useState(null), [gridPage, setGridPage] = useState(0);
  const [dialog, setDialog] = useState(null), [notice, setNotice] = useState(''), [fullscreen, setFullscreen] = useState(false);
  const [documentVisible, setDocumentVisible] = useState(!document.hidden), [subscribed, setSubscribed] = useState([]);
  const viewport = useRef(null), registry = useCameraRegistry(subscribed);
  const visible = page === 'cameras' || page === 'live';
  const engineCameraKey = live.state?.source === 'RTSP_LIVE' ? live.state.camera_key : null;
  const matchingPreview = registry.cameras.find(c => c.camera_key === engineCameraKey);
  const sources = [{ id: 'webcam', name: 'Webcam lokal', source: 'WEBCAM', health: webcam.status === 'LIVE' ? 'ONLINE' : webcam.status === 'ERROR' ? 'OFFLINE' : 'PAUSED' },
    ...(engineCameraKey && !matchingPreview ? [{ id: 'engine-rtsp', name: 'CCTV sesi engine', source: 'RTSP', health: live.active ? live.state.camera_health : 'PAUSED', analysis: live.active && live.state?.camera_health === 'ONLINE', recorded: live.state?.latest?.recorded, error: live.state?.error }] : []),
    ...registry.cameras.map(c => c.id === matchingPreview?.id && live.active ? { ...c, source: 'RTSP_ENGINE', health: live.state.camera_health, analysis: live.state.camera_health === 'ONLINE', recorded: live.state?.latest?.recorded, error: live.state.error } : c)].map(c => ({ ...c, timezone: engine.snapshot?.timezone || 'Asia/Jakarta' }));
  const enabled = sources.filter(c => !hidden.includes(c.id));
  const pages = Math.max(1, Math.ceil(enabled.length / prefs.layout)), currentPage = Math.min(gridPage, pages - 1);
  const displayed = focus ? enabled.filter(c => c.id === focus) : enabled.slice(currentPage * prefs.layout, (currentPage + 1) * prefs.layout);
  const count = focus ? 1 : prefs.layout;
  const selectedCamera = sources.find(c => c.id === selected);
  const slots = Array.from({ length: count }, (_, i) => displayed[i] || null);
  const visibleKey = JSON.stringify(visible && documentVisible ? displayed.filter(c => c.source === 'RTSP_PREVIEW').map(c => c.id) : []);
  useEffect(() => { setSubscribed(JSON.parse(visibleKey)); }, [visibleKey]);
  useEffect(() => { try { localStorage.setItem('cctv-camera-wall', JSON.stringify(prefs)); } catch {} }, [prefs]);
  useEffect(() => {
    const changed = () => setDocumentVisible(!document.hidden);
    document.addEventListener('visibilitychange', changed); return () => document.removeEventListener('visibilitychange', changed);
  }, []);
  useEffect(() => {
    if (focus && !sources.some(c => c.id === focus)) setFocus(null);
    if (!sources.some(c => c.id === selected)) setSelected('webcam');
  }, [registry.cameras, live.state?.source, focus, selected]);
  useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === viewport.current);
    const key = e => { if (e.key === 'Escape' && !document.querySelector('dialog[open]')) setFocus(null); };
    document.addEventListener('fullscreenchange', changed); window.addEventListener('keydown', key);
    return () => { document.removeEventListener('fullscreenchange', changed); window.removeEventListener('keydown', key); };
  }, []);
  useEffect(() => {
    if (!visible && document.fullscreenElement === viewport.current) document.exitFullscreen().catch(() => {});
  }, [visible]);
  function choose(id) {
    setSelected(id); setFocus(null);
    const next = sources.filter(c => c.id === id || !hidden.includes(c.id));
    setHidden(h => h.filter(item => item !== id));
    setGridPage(Math.floor(next.findIndex(c => c.id === id) / prefs.layout));
  }
  function focusCamera(id) { setHidden(h => h.filter(item => item !== id)); setSelected(id); setFocus(id); }
  async function removeCamera(id) {
    try { await registry.remove(id); setDialog(null); setNotice('Kamera dilepas dari sesi preview.'); }
    catch (error) { setNotice(error.message); }
  }
  return <section className={`camera-workspace ${visible ? '' : 'camera-workspace-compact'} ${!visible && !webcam.stream && !['REQUESTING', 'CANCELLING'].includes(webcam.status) ? 'webcam-hidden' : ''}`} data-testid="camera-workspace">
    <div className="camera-wall-toolbar">
      <div className="inline-controls"><Button icon={ListVideo} aria-pressed={prefs.list} onClick={() => setPrefs(p => ({ ...p, list: !p.list }))}>Daftar kamera</Button><div className="camera-layout-buttons" role="group" aria-label="Layout kamera">{LAYOUTS.map(n => <button key={n} aria-label={`Layout ${n} kamera`} aria-pressed={!focus && prefs.layout === n} onClick={() => { setPrefs(p => ({ ...p, layout: n })); setFocus(null); setGridPage(0); }}><span className={`layout-glyph layout-glyph-${Math.sqrt(n)}`} aria-hidden="true">{Array.from({ length: n }, (_, i) => <i key={i}/>)}</span>{n}</button>)}</div></div>
      <div className="inline-controls"><label className="check-control"><input type="checkbox" checked={prefs.zones} onChange={e => setPrefs(p => ({ ...p, zones: e.target.checked }))}/>Zona</label><label className="check-control"><input type="checkbox" checked={prefs.detections} onChange={e => setPrefs(p => ({ ...p, detections: e.target.checked }))}/>Deteksi</label><Button icon={Plus} variant="primary" onClick={() => setDialog({ type: 'add' })}>Tambah kamera</Button></div>
    </div>
    <div className={`camera-wall-body ${prefs.list ? '' : 'camera-list-collapsed'}`}>
      {prefs.list && <aside className="camera-directory" aria-label="Daftar sumber kamera">
        <div className="camera-directory-title"><h2>Kamera</h2><span>{sources.length}</span></div>
        <Field label="Cari kamera"><div className="camera-search"><Search size={14} aria-hidden="true"/><input type="search" placeholder="Nama kamera" value={search} onChange={e => setSearch(e.target.value)}/></div></Field>
        <div className="camera-directory-items">{sources.filter(c => c.name.toLowerCase().includes(search.toLowerCase())).map(c => <div key={c.id} className={`camera-directory-row ${selected === c.id ? 'selected' : ''}`}><button className="camera-directory-select" aria-pressed={selected === c.id} onClick={() => choose(c.id)}><Camera size={15} aria-hidden="true"/><span><strong>{c.name}</strong><small>{hidden.includes(c.id) ? 'Disembunyikan dari grid' : HEALTH[c.health] || c.health}</small></span></button>{(c.source === 'RTSP_PREVIEW' || c.source === 'RTSP_ENGINE') && <button className="icon-button" aria-label={`Hapus ${c.name}`} onClick={() => setDialog({ type: 'remove', camera: c })}><Trash2 size={14}/></button>}</div>)}{!sources.some(c => c.name.toLowerCase().includes(search.toLowerCase())) && <p className="camera-search-empty">Kamera tidak ditemukan.</p>}</div>
        <p className="camera-directory-note">Preview RTSP tersedia selama aplikasi berjalan. URL dan kredensial tidak disimpan.</p>
      </aside>}
      <div className="camera-viewport" ref={viewport} data-testid="camera-wall-viewport">
        <div className="camera-view-heading"><span>{focus ? `Fokus · ${selectedCamera?.name || ''}` : `Tampilan ${Math.sqrt(prefs.layout)} × ${Math.sqrt(prefs.layout)}`}<small>{displayed.length} sumber ditampilkan</small></span><div className="inline-controls">{focus && <Button icon={X} onClick={() => setFocus(null)}>Kembali ke grid</Button>}{document.fullscreenEnabled && <Button icon={Maximize} aria-label={fullscreen ? 'Keluar layar penuh grid' : 'Layar penuh grid'} onClick={() => (fullscreen ? document.exitFullscreen() : viewport.current.requestFullscreen()).catch(() => setNotice('Layar penuh tidak tersedia pada browser ini.'))}>{fullscreen ? 'Keluar layar penuh' : 'Layar penuh'}</Button>}</div></div>
        <div className={`camera-wall-grid camera-grid-${Math.sqrt(count)}`} data-testid="camera-wall-grid" data-layout={count}>
          {sources.map(camera => {
            const shown = displayed.some(c => c.id === camera.id), tileVisible = visible && documentVisible && shown;
            return <div key={camera.id} className={`camera-tile ${shown ? '' : 'camera-tile-hidden'} ${selected === camera.id ? 'camera-tile-selected' : ''}`} data-testid="camera-tile" data-camera-id={camera.id} tabIndex={shown ? 0 : -1} aria-label={`Kamera ${camera.name}`} onClick={() => setSelected(camera.id)} onDoubleClick={e => { if (!e.target.closest('button,select,input')) focusCamera(camera.id); }} onKeyDown={e => { if (e.target === e.currentTarget && e.key === 'Enter') { e.preventDefault(); focusCamera(camera.id); } }}>
              {camera.id === 'webcam' ? <WebcamPanel wall webcam={{ ...webcam, showDetections: prefs.detections, showZones: prefs.zones }} onFocus={() => focusCamera(camera.id)}/>
                : <RtspTile camera={camera} visible={tileVisible} onFocus={() => focusCamera(camera.id)}/>}
            </div>;
          })}
          {slots.filter(c => !c).map((_, i) => <button key={`empty-${i}`} className="camera-empty-tile" data-testid="camera-empty-slot" onClick={() => setDialog({ type: 'add' })}><Plus size={20} aria-hidden="true"/><strong>Tambah kamera</strong><span>Hubungkan sumber RTSP</span></button>)}
        </div>
        <div className="camera-wall-pagination"><span>{sources.filter(c => c.health === 'ONLINE').length} kamera terhubung · Video tidak disimpan</span><div className="inline-controls"><Button icon={ChevronLeft} aria-label="Halaman kamera sebelumnya" disabled={!!focus || currentPage === 0} onClick={() => setGridPage(p => p - 1)}/><span>{currentPage + 1} / {pages}</span><Button icon={ChevronRight} aria-label="Halaman kamera berikutnya" disabled={!!focus || currentPage >= pages - 1} onClick={() => setGridPage(p => p + 1)}/></div></div>
      </div>
    </div>
    <div className="camera-selection-bar"><div><span>KAMERA DIPILIH</span><strong>{selectedCamera?.name || 'Pilih kamera'}</strong></div><p>{selectedCamera?.id === 'webcam' ? 'Deteksi YOLOX tersedia dari webcam. Kalibrasikan zona untuk mencatat durasi.' : selectedCamera?.analysis ? 'Sumber ini sedang diproses oleh engine live.' : 'Sumber ini menayangkan preview. Deteksi dan pencatatan belum diaktifkan untuk kamera ini.'}</p><Button disabled={!selectedCamera} onClick={() => focusCamera(selected)}>Fokus kamera</Button><Button disabled={!selectedCamera || hidden.includes(selected)} onClick={() => { setHidden(h => [...h, selected]); if (focus === selected) setFocus(null); }}>Sembunyikan dari grid</Button></div>
    {(notice || registry.error) && <p className="camera-wall-notice" role="status">{notice || `Daftar RTSP belum tersedia: ${registry.error}`}</p>}
    <p className="camera-analysis-note">Beberapa preview dapat ditampilkan bersamaan. Engine pencatatan saat ini memproses satu sumber aktif; status deteksi ditampilkan per kamera.</p>
    {dialog?.type === 'add' && <AddCameraDialog onClose={() => setDialog(null)} onSave={async (name, url) => { const camera = await registry.add(name, url); setDialog(null); setHidden(h => h.filter(id => id !== camera.id)); setSelected(camera.id); setFocus(null); setGridPage(Math.floor(enabled.length / prefs.layout)); }}/>} 
    {dialog?.type === 'remove' && <Modal title="Hapus kamera preview?" description={`${dialog.camera.name} akan dilepas dari sesi preview. Sesi engine pencatatan tidak berubah.`} onClose={() => setDialog(null)}><div className="modal-actions"><Button onClick={() => setDialog(null)}>Batal</Button><Button variant="danger" onClick={() => removeCamera(dialog.camera.id)}>Hapus kamera</Button></div></Modal>}
  </section>;
}

function AddCameraDialog({ onClose, onSave }) {
  const [name, setName] = useState(''), [url, setUrl] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function save(e) {
    e.preventDefault(); setBusy(true); setError('');
    try { await onSave(name.trim(), url.trim()); }
    catch (failure) { setError(failure.message); setBusy(false); }
  }
  return <Modal title="Tambah kamera RTSP" description="Hubungkan kamera atau substream NVR ke grid. Koneksi diuji setelah kamera ditambahkan." onClose={busy ? () => {} : onClose}><form className="engine-form" onSubmit={save}><Field label="Nama kamera"><input required maxLength={80} placeholder="Contoh: Area produksi 01" value={name} onChange={e => setName(e.target.value)} disabled={busy}/></Field><Field label="Alamat RTSP" hint="Gunakan substream untuk beberapa preview. URL hanya berada dalam memori selama sesi aplikasi."><input type="password" required autoComplete="off" maxLength={2048} placeholder="rtsp://user:password@kamera:554/stream" value={url} onChange={e => setUrl(e.target.value)} disabled={busy}/></Field>{error && <p className="error-text" role="alert">{error}</p>}<div className="modal-actions"><Button type="button" disabled={busy} onClick={onClose}>Batal</Button><Button type="submit" variant="primary" disabled={busy || !name.trim() || !url.trim()}>{busy ? 'Menghubungkan...' : 'Tambahkan ke grid'}</Button></div></form></Modal>;
}
