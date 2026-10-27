import { useEffect, useRef, useState } from 'react';
import { Maximize2, Minimize2, PanelRight, Plus, Search, VideoOff } from 'lucide-react';
import { usePrototype } from './store';
import { Button, Empty, EventList, Field, Panel, Status } from './components';
import { CAMERA_LABELS, REASONS, clock } from './domain';

export default function Live({ navigate, cameraId }) {
  const { state, observed, cameraStatus, observe, playing, setDialog } = usePrototype();
  const [selected, setSelected] = useState(cameraId || state.cameras[0]?.id), [search,setSearch] = useState(''), [statusFilter,setStatusFilter] = useState('ALL');
  const [layout,setLayout] = useState(4), [focused,setFocused] = useState(false), [inspector,setInspector] = useState(false), [paused,setPaused] = useState(false);
  const [overlay,setOverlay] = useState({zones:true,detection:false,tracks:false});
  const [screenExpanded,setScreenExpanded] = useState(false);
  const pausedSnapshot = useRef(null);
  const focusRef = useRef(null);
  useEffect(() => { if (cameraId) setSelected(cameraId); }, [cameraId]);
  useEffect(() => {
    const handler = event => { if (event.key === 'Escape') { setFocused(false); setInspector(false); setScreenExpanded(false); } };
    const changed = () => setScreenExpanded(document.fullscreenElement === focusRef.current);
    window.addEventListener('keydown',handler); document.addEventListener('fullscreenchange',changed);
    return () => { window.removeEventListener('keydown',handler); document.removeEventListener('fullscreenchange',changed); };
  },[]);
  useEffect(() => {
    if (!screenExpanded) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    focusRef.current?.querySelector('button')?.focus();
    return () => { document.body.style.overflow = previous; };
  },[screenExpanded]);
  function screenKeys(event) {
    if (!screenExpanded || event.key !== 'Tab') return;
    const controls = [...focusRef.current.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),[href]')].filter(element => element.getClientRects().length);
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
  const cameras = state.cameras.filter(c => c.name.toLowerCase().includes(search.toLowerCase()) && (statusFilter === 'ALL' || c.status === statusFilter));
  const camera = state.cameras.find(c => c.id === selected) || cameras[0];
  const zones = observed.filter(w => w.cameraId === camera?.id);
  const sorted = [...cameras].sort((a,b) => a.id === camera?.id ? -1 : b.id === camera?.id ? 1 : 0);
  const shown = focused || layout === 1 ? (camera ? [camera] : []) : sorted.slice(0,layout);
  const emptySlots = focused || layout === 1 || !cameras.length ? 0 : Math.max(0, layout - shown.length);
  async function leaveFullscreen() {
    if (document.fullscreenElement === focusRef.current) await document.exitFullscreen().catch(() => {});
    setScreenExpanded(false);
  }
  async function fullscreen(allCameras = false) {
    if (screenExpanded) { await leaveFullscreen(); return; }
    if (allCameras) { setFocused(false); if (layout === 1) setLayout(4); }
    setScreenExpanded(true);
    try { await focusRef.current?.requestFullscreen?.(); } catch { /* Keep the viewport overlay when native fullscreen is unavailable. */ }
  }
  async function addCamera() {
    await leaveFullscreen();
    setDialog({type:'camera'});
  }
  if (!state.cameras.length) return <Empty title="Belum ada kamera" description="Tambahkan kamera contoh untuk mencoba monitoring tanpa membuka stream RTSP." action={<Button variant="primary" icon={Plus} onClick={() => setDialog({type:'camera'})}>Tambah kamera</Button>}/>;
  return <div className={`monitor-layout ${inspector ? 'inspector-open' : ''}`}>
    <aside className="camera-rail panel"><div className="panel-heading"><h2>Daftar kamera</h2><span>{cameras.length}</span></div><div className="rail-controls"><Field label="Cari kamera"><input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Nama kamera"/></Field><Field label="Status koneksi"><select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="ALL">Semua status</option>{Object.entries(CAMERA_LABELS).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></Field></div>
      <div className="camera-options">{cameras.map(c => <button key={c.id} className={`camera-option ${camera?.id === c.id ? 'selected' : ''}`} onClick={() => setSelected(c.id)} aria-pressed={camera?.id === c.id}><strong>{c.name}</strong><small>{c.id} · {c.area}</small><Status value={c.status}/></button>)}{!cameras.length && <Empty title="Tidak ada hasil"/>}</div>
      <Button icon={Plus} className="rail-add" onClick={() => setDialog({type:'camera'})}>Tambah kamera</Button>
    </aside>
    <div className="monitor-center"><div ref={focusRef} className={`monitor-screen ${screenExpanded ? 'monitor-screen-expanded' : ''}`} data-testid="monitor-screen" role={screenExpanded ? 'dialog' : undefined} aria-modal={screenExpanded || undefined} aria-label={screenExpanded ? 'Pemantauan semua kamera' : undefined} onKeyDown={screenKeys}><div className="monitor-toolbar"><div className="segmented" aria-label="Layout kamera">{[[1,'Fokus'],[4,'2 × 2'],[9,'3 × 3'],[16,'4 × 4']].map(([value,label]) => <button key={value} aria-pressed={layout === value} onClick={() => {setLayout(value); setFocused(false);}}>{label}</button>)}</div><div className="overlay-controls">{[['zones','Zona'],['detection','Deteksi'],['tracks','Track ID']].map(([key,label]) => <label key={key}><input type="checkbox" checked={overlay[key]} onChange={e => setOverlay(previous => ({...previous,[key]:e.target.checked}))}/>{label}</label>)}</div><Button icon={screenExpanded ? Minimize2 : Maximize2} onClick={() => fullscreen(true)}>{screenExpanded ? 'Keluar layar penuh' : 'Layar penuh semua kamera'}</Button><Button icon={PanelRight} className="detail-toggle" onClick={() => setInspector(value => !value)}>Detail kamera</Button></div>
      <div className={`camera-grid layout-${focused ? 1 : layout}`} style={{'--camera-rows':focused || layout === 1 ? 1 : Math.ceil((shown.length + emptySlots) / Math.sqrt(layout)) || 1}} data-testid="camera-grid">{shown.map(c => {
        const unavailable = ['OFFLINE','DISABLED','RECONNECTING'].includes(c.status);
        return <article key={c.id} className={`video-tile ${camera?.id === c.id ? 'selected' : ''}`}><div className="video-heading"><button className="camera-name" onClick={() => setSelected(c.id)}>{c.name}</button><span className="mono">{c.id}</span><button className="icon-button" aria-label={`Fokus ${c.name}`} onClick={() => {setSelected(c.id); setFocused(value => !value);}}>{focused ? <Minimize2 size={14}/> : <Maximize2 size={14}/>}</button></div>
          <div className="video-content" onDoubleClick={() => {setSelected(c.id);setFocused(true);}}>{unavailable ? <div className="stream-placeholder"><VideoOff size={26} aria-hidden="true"/><strong>{CAMERA_LABELS[c.status]}</strong><p>{c.status === 'DISABLED' ? 'Preview nonaktif; histori tetap tersedia.' : c.status === 'RECONNECTING' ? 'Uji koneksi atau langkah simulasi akan menyelesaikan reconnect.' : 'Observasi zona menjadi unknown, bukan kosong.'}</p><Button onClick={() => cameraStatus(c.id,c.status === 'DISABLED' ? 'ONLINE' : 'RECONNECTING')}>{c.status === 'DISABLED' ? 'Aktifkan simulasi' : 'Coba sambungkan'}</Button></div> : paused && <div className="preview-paused">Preview dijeda. Simulasi accounting tetap terpisah.</div>}</div>
          <div className="video-footer"><Status value={c.status} label={c.status === 'ONLINE' ? 'Status simulasi' : undefined}/><span className="mono">{unavailable ? 'Frame: N/A' : clock(paused?pausedSnapshot.current.clock:state.clock,state.settings.timezone,true)}</span></div>
        </article>;
      })}{Array.from({length:emptySlots},(_,index) => <button key={`empty-${index}`} className="video-empty-slot" aria-label={`Tambah kamera ke slot ${shown.length + index + 1}`} onClick={addCamera}><Plus size={20} aria-hidden="true"/><strong>Slot {shown.length + index + 1}</strong><span>Tambah kamera</span></button>)}</div>
      {!shown.length && <Empty title="Tidak ada kamera yang cocok" action={<Button onClick={() => {setSearch('');setStatusFilter('ALL');}}>Hapus filter</Button>}/>}
      <div className="video-actions"><span className="caption">Belum ada video kamera terhubung. Status berasal dari simulasi.</span><Button onClick={() => {if(!paused)pausedSnapshot.current={clock:state.clock,observed:structuredClone(observed)};setPaused(value=>!value);}}>{paused ? 'Lanjutkan preview' : 'Jeda preview'}</Button>{focused && <><Button onClick={() => fullscreen()}>Layar penuh</Button><Button onClick={() => setFocused(false)}>Kembali ke grid</Button></>}</div></div>
      <Panel title="Event aktivitas simulasi" caption="Observasi zona, bukan klasifikasi hasil kerja" action={<Button onClick={() => navigate('analytics',{workspaceId:zones[0]?.id})}>Buka timeline</Button>}><EventList events={state.events.filter(e => !camera || e.cameraId === camera.id || e.cameraId == null)} limit={3} onSelect={event => setDialog({type:'event',event})}/></Panel>
    </div>
    <aside className="monitor-inspector panel"><div className="panel-heading"><h2>Detail kamera</h2><button className="inspector-close icon-button" onClick={() => setInspector(false)} aria-label="Tutup detail kamera">×</button></div>{camera && <div className="inspector-body"><h3>{camera.name}</h3><p className="caption mono">{camera.id} · {camera.area}</p><dl className="detail-list"><dt>Transport simulasi</dt><dd><Status value={camera.status}/></dd><dt>Tracking</dt><dd>{camera.status === 'ONLINE' ? 'Tersedia (mock)' : 'Tidak tersedia'}</dd><dt>Target inference</dt><dd>{camera.fps} FPS (konfigurasi mock)</dd><dt>Penyimpanan</dt><dd>{state.persistence === 'HEALTHY' ? 'Sehat (mock)' : 'Terganggu (mock)'}</dd></dl>
      <Field label="Simulasi koneksi"><select aria-label="Simulasi koneksi kamera terpilih" value={camera.status} onChange={e => cameraStatus(camera.id,e.target.value)}>{Object.entries(CAMERA_LABELS).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
      <div className="inspector-zones"><h3>Observasi workstation</h3>{zones.map(w => <div className="zone-observation" key={w.id}><button className="text-button" onClick={() => navigate('workspaces',{workspaceId:w.id})}>{w.name}</button><Status value={w.liveState}/><span className="caption">Jumlah: {w.count ?? 'N/A'} · {REASONS[w.reason]}</span><div className="segmented mini">{[['OCCUPIED','Terisi'],['EMPTY','Kosong'],['UNKNOWN','Unknown']].map(([value,label]) => <button key={value} disabled={camera.status !== 'ONLINE' || state.persistence !== 'HEALTHY'} aria-pressed={w.liveState === value} onClick={() => observe(w.id,value,value === 'OCCUPIED' ? 1 : null)}>{label}</button>)}</div></div>)}{!zones.length && <p>Belum ada zona. Buat workstation untuk kamera ini.</p>}</div>
      <Button onClick={() => setDialog({type:'camera',camera})}>Edit konfigurasi</Button><p className="caption">Tombol state mensimulasikan observasi. Kamera terganggu tidak menghasilkan away time.</p>
    </div>}</aside>
  </div>;
}
