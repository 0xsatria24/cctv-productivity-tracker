import { useEffect, useRef, useState } from 'react';
import { Camera, ChevronLeft, ChevronRight, ListVideo, Maximize, Plus, Search, Trash2, X } from 'lucide-react';
import { Button, Field, Modal, Status } from './components';
import { engineRequest, durationClock } from './engine-client';
import { WebcamPanel } from './webcam';
import { CAMERA_MODES, cameraView } from './camera-layout.mjs';
import { monitoringState } from './camera-status.mjs';
import './camera-wall.css';

const LAYOUTS = [1, 4, 9, 16];
const HEALTH = { ONLINE: 'Live', CONNECTING: 'Menghubungkan', RECONNECTING: 'Menghubungkan ulang', STALLED: 'Frame terhenti', PAUSED: 'Preview dijeda', OFFLINE: 'Tidak terhubung' };
function preference() {
  try {
    const value = JSON.parse(localStorage.getItem('cctv-camera-wall') || '{}');
    return { layout: LAYOUTS.includes(value.layout) ? value.layout : 4, layoutChosen: value.layoutChosen ?? LAYOUTS.includes(value.layout), mode: CAMERA_MODES.some(mode => mode.value === value.mode) ? value.mode : 'grid', list: value.list !== false,
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
    await engineRequest(`camera-wall/cameras/${id}`, { method: 'DELETE' });
    setCameras(current => current.filter(c => c.id !== id));
  }
  return { cameras, error, add, remove };
}

function RtspTile({ camera, visible, onFocus, latest, zones = [], showDetections, showZones }) {
  const latestRef = useRef(latest); latestRef.current = latest;
  const [frame, setFrame] = useState(null), [size, setSize] = useState(null), [dimensions, setDimensions] = useState(null), [bounds, setBounds] = useState(null);
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
      const request = new AbortController(), cancel = () => request.abort();
      abort.signal.addEventListener('abort', cancel, { once: true });
      const timeout = setTimeout(cancel, 4000);
      try {
        const analysis = latestRef.current;
        const engineCamera = camera.id === 'engine-rtsp' || camera.source === 'RTSP_ENGINE';
        const frameQuery = engineCamera && analysis?.run_id && analysis?.frame_seq
          ? `?frame_seq=${analysis.frame_seq}&run_id=${encodeURIComponent(analysis.run_id)}` : '';
        const url = engineCamera ? `/pilot/v1/live/preview.jpg${frameQuery}` : `/pilot/v1/camera-wall/cameras/${camera.id}/frame.jpg`;
        const response = await fetch(url, { cache: 'no-store', signal: request.signal });
        if (!response.ok) throw new Error('No fresh frame');
        const next = URL.createObjectURL(await response.blob());
        if (cancelled) { URL.revokeObjectURL(next); return; }
        if (object) URL.revokeObjectURL(object);
        object = next; received = performance.now();
        setFrame({ url: next, time: response.headers.get('X-Frame-Time'), sequence: response.headers.get('X-Frame-Sequence'),
          runId: response.headers.get('X-Run-Id'), mappingVersion: response.headers.get('X-Mapping-Version'), analysis });
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
  const frameAnalysis = frame?.runId ? frame.analysis : latest;
  const frameMatches = !frame?.runId || (frame.runId === frameAnalysis?.run_id && frame.sequence === String(frameAnalysis?.frame_seq)
    && frame.mappingVersion === String(frameAnalysis?.mapping_version));
  const detection = frame && frameMatches && visible && camera.analysis && health === 'ONLINE' ? frameAnalysis : null;
  return <section className="rtsp-wall-panel">
    <header className="camera-tile-heading"><h2>{camera.name}</h2><Status value={health === 'PAUSED' ? 'DISABLED' : health === 'STALLED' ? 'DEGRADED' : health} label={HEALTH[health] || health}/><Button icon={Maximize} aria-label={`Fokus ${camera.name}`} onClick={onFocus}/></header>
    <div className="camera-frame" ref={frameArea}>
      {frame ? <><img src={frame.url} alt={`Preview ${camera.name}`} aria-label={camera.id === 'engine-rtsp' || camera.source === 'RTSP_ENGINE' ? 'Preview RTSP lokal' : `Preview ${camera.name}`} onLoad={e => { const width = e.currentTarget.naturalWidth, height = e.currentTarget.naturalHeight; setSize(`${width} × ${height}`); setDimensions(current => current?.width === width && current?.height === height ? current : { width, height }); }} onError={() => { setFrame(null); setSize(null); }}/>
        {bounds && <svg className="rtsp-camera-overlays" style={bounds} viewBox={`0 0 ${dimensions.width} ${dimensions.height}`} preserveAspectRatio="none" aria-label={detection ? `${detection.count} orang terdeteksi` : 'Overlay kamera'}>
          {showZones && camera.analysis && zones.map(zone => <polygon key={zone.id} points={zone.polygon.map(([x, y]) => `${x * dimensions.width},${y * dimensions.height}`).join(' ')} className="rtsp-zone-outline"/>)}
          {showDetections && detection?.detections.map((row, i) => <g key={row.session_id || row.track_lifecycle || row.track_id || i} data-testid="rtsp-person-detection">
            <rect x={row.box[0] * dimensions.width} y={row.box[1] * dimensions.height} width={(row.box[2] - row.box[0]) * dimensions.width} height={(row.box[3] - row.box[1]) * dimensions.height} className="person-box"/>
            <text x={row.box[0] * dimensions.width + 4} y={Math.max(14, row.box[1] * dimensions.height - 5)}>Orang {Math.round(row.confidence * 100)}%</text>
            {row.workstation_times?.map((visit, j) => {
              const font = Math.max(12, 11 * dimensions.width / Math.max(1, bounds.width));
              const x = Math.max(0, Math.min(row.box[0] * dimensions.width + 4, dimensions.width - font * 11));
              const y = row.box[1] * dimensions.height + font + 4 + j * (font + 8);
              return <g key={visit.zone_id}>
                <rect x={x - 2} y={y - font} width={font * 10.5} height={font + 5} fill="#101b18" fillOpacity="0.9" rx="3"/>
                <text className="rtsp-presence-clock" data-testid="rtsp-presence-clock" style={{ fontSize: font }} x={x} y={y}>
                  <title>{visit.name} · akumulasi durasi sesi orang ini</title>
                  Di meja {durationClock(visit.presence_us)}
                </text>
              </g>;
            })}
          </g>)}
        </svg>}</>
        : <div className="camera-no-signal"><Camera size={24} aria-hidden="true"/><strong>{HEALTH[health] || 'Menunggu gambar'}</strong><p>{camera.error || 'Gambar muncul setelah koneksi kamera tersedia.'}</p></div>}
    </div>
    <div className="camera-tile-info"><span data-testid="rtsp-detection-status">{camera.analysis ? detection ? `${detection.count} orang terdeteksi · ${detection.inference_ms} ms` : 'Menunggu hasil deteksi' : 'Preview saja'}</span><span>{size || 'Resolusi belum tersedia'}</span></div>
    <footer className="camera-tile-footer"><span>{camera.analysis ? camera.recorded ? 'Pencatatan live aktif' : 'Pencatatan belum dimulai' : 'Deteksi dan pencatatan belum aktif'}</span><time>{frame?.time ? new Date(Number(frame.time)).toLocaleTimeString('id-ID', { timeZone: camera.timezone }) : 'Waktu frame belum tersedia'}</time></footer>
  </section>;
}

export function CameraWorkspace({ webcam, live, engine, page, onHealthChange, selected = 'webcam', onSelect, onConfigure, addRequest = 0 }) {
  const [prefs, setPrefs] = useState(preference), [search, setSearch] = useState(''), [hidden, setHidden] = useState([]);
  const setSelected = onSelect;
  const [gridPage, setGridPage] = useState(0), [focusPage, setFocusPage] = useState(0);
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width:760px)').matches);
  const [dialog, setDialog] = useState(null), [notice, setNotice] = useState(''), [fullscreen, setFullscreen] = useState(false);
  const [documentVisible, setDocumentVisible] = useState(!document.hidden), [subscribed, setSubscribed] = useState([]);
  const viewport = useRef(null), registry = useCameraRegistry(subscribed);
  const visible = page === 'live';
  const engineCameraKey = live.state?.source === 'RTSP_LIVE' ? live.state.camera_key : null;
  const matchingPreview = registry.cameras.find(c => c.camera_key === engineCameraKey);
  const sources = [{ id: 'webcam', name: 'Webcam lokal', source: 'WEBCAM', health: webcam.status === 'LIVE' ? 'ONLINE' : webcam.status === 'ERROR' ? 'OFFLINE' : 'PAUSED' },
    ...(engineCameraKey && !matchingPreview ? [{ id: 'engine-rtsp', name: 'CCTV sesi engine', source: 'RTSP', camera_key:engineCameraKey, health: live.active ? live.state.camera_health : 'PAUSED', analysis: live.active && live.state?.camera_health === 'ONLINE', recorded: live.state?.latest?.recorded, error: live.state?.error }] : []),
    ...registry.cameras.map(c => c.id === matchingPreview?.id && live.active ? { ...c, source: 'RTSP_ENGINE', health: live.state.camera_health, analysis: live.state.camera_health === 'ONLINE', recorded: live.state?.latest?.recorded, error: live.state.error } : c)].map(c => ({ ...c, timezone: engine.snapshot?.timezone || 'Asia/Jakarta' }));
  const healthKey = JSON.stringify(sources.map(c => ({ id: c.id, name: c.name, source: c.source, camera_key: c.camera_key, health: engine.connectionError && c.id !== 'webcam' ? 'UNKNOWN' : c.health, analysis: monitoringState(c,live).label === 'Monitoring aktif' })));
  useEffect(() => { onHealthChange?.(JSON.parse(healthKey)); }, [healthKey, onHealthChange]);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 5500); return () => clearTimeout(timer); }, [notice]);
  const enabled = sources.filter(c => !hidden.includes(c.id));
  const layout = !prefs.layoutChosen && enabled.length <= 1 ? 1 : prefs.layout;
  const { displayed, primaryId, capacity: count, pages, currentPage } = cameraView(narrow ? enabled.filter(c=>c.id===(enabled.some(c=>c.id===selected)?selected:enabled[0]?.id)) : enabled, { mode: narrow ? 'grid' : prefs.mode, layout: narrow ? 1 : layout, selected, page: narrow ? 0 : prefs.mode === 'focus' ? focusPage : gridPage });
  const selectedCamera = sources.find(c => c.id === selected);
  const selectedMonitoring = selectedCamera ? monitoringState(selectedCamera,live) : null;
  const switchingBlocked = live.active && !live.state?.preview_only && (selected === 'webcam' ? live.state.source !== 'WEBCAM_LIVE' : selectedCamera?.camera_key !== live.state.camera_key);
  const showList = prefs.list && prefs.mode !== 'wall';
  const enabledKey = JSON.stringify(enabled.map(c => c.id));
  const slots = Array.from({ length: count }, (_, i) => displayed[i] || null);
  useEffect(() => {
    const media = window.matchMedia('(max-width:760px)'), changed = () => setNarrow(media.matches);
    media.addEventListener('change', changed); return () => media.removeEventListener('change', changed);
  }, []);
  useEffect(() => { if (addRequest) setDialog({ type:'add' }); }, [addRequest]);
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
    try { await registry.remove(id); setDialog(null); setNotice('Kamera dilepas dari sesi preview.'); }
    catch (error) { setNotice(error.message); }
  }
  return <section className={`camera-workspace ${visible && prefs.mode === 'wall' ? 'camera-workspace-wall' : ''} ${visible ? '' : 'camera-workspace-compact'} ${!visible && !webcam.stream && !['REQUESTING', 'CANCELLING'].includes(webcam.status) ? 'webcam-hidden' : ''}`} data-testid="camera-workspace" data-mode={prefs.mode}>
    <div className="camera-wall-toolbar">
      <div className="inline-controls desktop-camera-controls">{prefs.mode !== 'wall' && <Button icon={ListVideo} aria-pressed={prefs.list} onClick={() => setPrefs(p => ({ ...p, list: !p.list }))}>Daftar kamera</Button>}{prefs.mode !== 'focus' && <div className="camera-layout-buttons" role="group" aria-label="Layout kamera">{LAYOUTS.map(n => <button key={n} aria-label={`Layout ${n} kamera`} aria-pressed={layout === n} onClick={() => { setPrefs(p => ({ ...p, layout: n, layoutChosen:true })); setGridPage(Math.max(0, Math.floor(enabled.findIndex(c => c.id === selected) / n))); }}><span className={`layout-glyph layout-glyph-${Math.sqrt(n)}`} aria-hidden="true">{Array.from({ length: n }, (_, i) => <i key={i}/>)}</span>{n}</button>)}</div>}</div>
      <Field className="mobile-camera-picker" label="Kamera ditampilkan"><select value={selected||''} onChange={e=>choose(e.target.value)}>{sources.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
      <div className="inline-controls"><label className="check-control"><input type="checkbox" checked={prefs.zones} onChange={e => setPrefs(p => ({ ...p, zones: e.target.checked }))}/>Zona</label><label className="check-control"><input type="checkbox" checked={prefs.detections} onChange={e => setPrefs(p => ({ ...p, detections: e.target.checked }))}/>Deteksi</label><Button icon={Plus} variant="primary" onClick={() => setDialog({ type: 'add' })}>Tambah kamera</Button></div>
    </div>
    <div className={`camera-wall-body ${showList ? '' : 'camera-list-collapsed'}`}>
      {showList && <aside className="camera-directory" aria-label="Daftar sumber kamera">
        <div className="camera-directory-title"><h2>Kamera</h2><span>{sources.length}</span></div>
        <Field label="Cari kamera"><div className="camera-search"><Search size={14} aria-hidden="true"/><input type="search" placeholder="Nama kamera" value={search} onChange={e => setSearch(e.target.value)}/></div></Field>
        <div className="camera-directory-items">{sources.filter(c => c.name.toLowerCase().includes(search.toLowerCase())).map(c => <div key={c.id} className={`camera-directory-row ${selected === c.id ? 'selected' : ''}`}><button className="camera-directory-select" aria-pressed={selected === c.id} onClick={() => choose(c.id)}><Camera size={15} aria-hidden="true"/><span><strong>{c.name}</strong><small>{hidden.includes(c.id) ? 'Disembunyikan dari grid' : HEALTH[c.health] || c.health}</small></span></button>{(c.source === 'RTSP_PREVIEW' || c.source === 'RTSP_ENGINE') && <button className="icon-button" aria-label={`Hapus ${c.name}`} onClick={() => setDialog({ type: 'remove', camera: c })}><Trash2 size={14}/></button>}</div>)}{!sources.some(c => c.name.toLowerCase().includes(search.toLowerCase())) && <p className="camera-search-empty">Kamera tidak ditemukan.</p>}</div>
        <p className="camera-directory-note">Preview RTSP tersedia selama aplikasi berjalan. URL dan kredensial tidak disimpan.</p>
      </aside>}
      <div className="camera-viewport" ref={viewport} data-testid="camera-wall-viewport">
        <div className="camera-mode-toolbar"><div className="camera-mode-buttons" role="group" aria-label="Mode tampilan kamera">{CAMERA_MODES.map(mode => <button key={mode.value} type="button" aria-pressed={prefs.mode === mode.value} onClick={() => changeMode(mode.value)}>{mode.label}</button>)}</div><span className="camera-mode-description">{prefs.mode === 'focus' ? 'Satu kamera utama + lima pendamping' : prefs.mode === 'wall' ? 'Tampilan ringkas untuk monitor besar' : 'Semua kamera dengan ukuran seimbang'}</span></div>
        <div className="camera-view-heading"><span>{narrow?selectedCamera?.name||'Pilih kamera':prefs.mode === 'focus' ? `Fokus · ${selectedCamera?.name || 'Pilih kamera'}` : `${prefs.mode === 'wall' ? 'Video wall' : 'Grid'} ${Math.sqrt(count)} × ${Math.sqrt(count)}`}<small>{displayed.length} sumber ditampilkan</small></span><div className="inline-controls">{!narrow&&prefs.mode === 'focus' && <Button icon={X} onClick={() => changeMode('grid')}>Kembali ke grid</Button>}{document.fullscreenEnabled && <Button icon={Maximize} aria-label={fullscreen ? 'Keluar layar penuh grid' : 'Layar penuh grid'} onClick={() => (fullscreen ? document.exitFullscreen() : viewport.current.requestFullscreen()).catch(() => setNotice('Layar penuh tidak tersedia pada browser ini.'))}>{fullscreen ? 'Keluar layar penuh' : 'Layar penuh'}</Button>}</div></div>
        <div className={`camera-wall-grid ${prefs.mode === 'focus' ? 'camera-grid-focus' : `camera-grid-${Math.sqrt(count)}`}`} data-testid="camera-wall-grid" data-layout={count} data-mode={prefs.mode}>
          {sources.map(camera => {
            const shown = displayed.some(c => c.id === camera.id), tileVisible = visible && documentVisible && shown;
            return <div key={camera.id} className={`camera-tile ${shown ? '' : 'camera-tile-hidden'} ${selected === camera.id ? 'camera-tile-selected' : ''} ${primaryId === camera.id ? 'camera-tile-primary' : ''}`} style={{ order: displayed.findIndex(c => c.id === camera.id) }} data-testid="camera-tile" data-camera-id={camera.id} data-primary={primaryId === camera.id ? 'true' : undefined} tabIndex={shown ? 0 : -1} aria-label={`Kamera ${camera.name}`} onClick={() => choose(camera.id)} onDoubleClick={e => { if (!e.target.closest('button,select,input')) focusCamera(camera.id); }} onKeyDown={e => { if (e.target === e.currentTarget && e.key === 'Enter') { e.preventDefault(); focusCamera(camera.id); } }}>
              <div className="camera-monitoring-state"><Status value={monitoringState(camera,live).tone} label={monitoringState(camera,live).label}/></div>
              {camera.id === 'webcam' ? <WebcamPanel wall webcam={{ ...webcam, showDetections: prefs.detections, showZones: prefs.zones }} onFocus={() => focusCamera(camera.id)}/>
                : <RtspTile camera={camera} visible={tileVisible} latest={camera.analysis ? live.state?.latest : null} zones={camera.analysis ? live.state?.calibrations?.RTSP_LIVE?.zones : undefined} showDetections={prefs.detections} showZones={prefs.zones} onFocus={() => focusCamera(camera.id)}/>}
            </div>;
          })}
          {slots.filter(c => !c).map((_, i) => <button key={`empty-${i}`} className="camera-empty-tile" style={{ order: displayed.length + i }} data-testid="camera-empty-slot" onClick={() => setDialog({ type: 'add' })}><Plus size={20} aria-hidden="true"/><strong>Tambah kamera</strong><span>Hubungkan sumber RTSP</span></button>)}
        </div>
        <div className="camera-wall-pagination"><span>{sources.filter(c => c.health === 'ONLINE').length} kamera terhubung · Video tidak disimpan</span><div className="inline-controls">{prefs.mode === 'focus' && <span>Kamera pendamping</span>}<Button icon={ChevronLeft} aria-label="Halaman kamera sebelumnya" disabled={currentPage === 0} onClick={() => changePage(-1)}/><span>{currentPage + 1} / {pages}</span><Button icon={ChevronRight} aria-label="Halaman kamera berikutnya" disabled={currentPage >= pages - 1} onClick={() => changePage(1)}/></div></div>
      </div>
    </div>
    <div className="camera-selection-bar"><div><span>KAMERA DIPILIH</span><strong>{selectedCamera?.name || 'Pilih kamera'}</strong></div><p>{selectedMonitoring?.label}. {switchingBlocked?'Satu kamera sedang dianalisis. Hentikan sesi aktif sebelum mengganti sumber pencatatan.':'Atur zona dan mulai monitoring untuk mencatat durasi kamera ini.'}</p><Button disabled={!selectedCamera||switchingBlocked} onClick={()=>onConfigure(selectedCamera)}>{selectedMonitoring?.label==='Monitoring aktif'?'Lihat monitoring':'Atur monitoring'}</Button><Button disabled={!selectedCamera} onClick={() => focusCamera(selected)}>Fokus kamera</Button><Button disabled={!selectedCamera || hidden.includes(selected)} onClick={() => setHidden(h => [...h, selected])}>Sembunyikan dari grid</Button></div>
    {(notice || registry.error) && <p className="camera-wall-notice" role="status">{notice || `Daftar RTSP belum tersedia: ${registry.error}`}</p>}
    <p className="camera-analysis-note">Beberapa preview dapat ditampilkan bersamaan. Analisis durasi saat ini memproses satu kamera aktif; status deteksi ditampilkan per kamera.</p>
    {dialog?.type === 'add' && <AddCameraDialog onClose={() => setDialog(null)} onSave={async (name, url) => { const camera = await registry.add(name, url); setDialog(null); setHidden(h => h.filter(id => id !== camera.id)); setSelected(camera.id); setFocusPage(0); setGridPage(Math.floor(enabled.length / prefs.layout)); if(!live.active)onConfigure(camera); }}/>}
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
