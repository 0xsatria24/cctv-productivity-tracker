import { useEffect, useRef, useState } from 'react';
import { Maximize2, Minimize2, PanelRight, Plus } from 'lucide-react';
import { usePrototype } from './store';
import { Button, Empty, Field, Status } from './components';
import { CAMERA_LABELS } from './domain';
import { useLanguage } from './language';

export default function Live({ navigate, cameraId }) {
  const {t}=useLanguage();
  const { state, setDialog } = usePrototype();
  const [selected, setSelected] = useState(cameraId || state.cameras[0]?.id), [search,setSearch] = useState(''), [statusFilter,setStatusFilter] = useState('ALL');
  const [layout,setLayout] = useState(4), [focused,setFocused] = useState(false), [inspector,setInspector] = useState(false);
  const [overlay,setOverlay] = useState({zones:true,detection:false,tracks:false});
  const [screenExpanded,setScreenExpanded] = useState(false);
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
  const sorted = [...cameras].sort((a,b) => a.id === camera?.id ? -1 : b.id === camera?.id ? 1 : 0);
  const shown = focused || layout === 1 ? (camera ? [camera] : []) : sorted.slice(0,layout);
  const emptySlots = focused || layout === 1 ? 0 : Math.max(0, layout - shown.length);
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
  return <div className={`monitor-layout ${inspector ? 'inspector-open' : ''}`}>
    <aside className="camera-rail panel"><div className="panel-heading"><h2>{t('Daftar kamera')}</h2><span>{cameras.length}</span></div><div className="rail-controls"><Field label="Cari kamera"><input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={t('Nama kamera')}/></Field><Field label="Status koneksi"><select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="ALL">Semua status</option>{Object.entries(CAMERA_LABELS).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></Field></div>
      <div className="camera-options">{cameras.map(c => <button key={c.id} className={`camera-option ${camera?.id === c.id ? 'selected' : ''}`} onClick={() => setSelected(c.id)} aria-pressed={camera?.id === c.id}><strong>{c.name}</strong><small>{c.id} · {c.area}</small><Status value={c.status}/></button>)}{!cameras.length && <Empty title="Tidak ada hasil"/>}</div>
      <Button icon={Plus} className="rail-add" onClick={() => setDialog({type:'camera'})}>Tambah kamera</Button>
    </aside>
    <div className="monitor-center"><div ref={focusRef} className={`monitor-screen ${screenExpanded ? 'monitor-screen-expanded' : ''}`} data-testid="monitor-screen" role={screenExpanded ? 'dialog' : undefined} aria-modal={screenExpanded || undefined} aria-label={screenExpanded ? 'Pemantauan semua kamera' : undefined} onKeyDown={screenKeys}><div className="monitor-toolbar"><div className="segmented" aria-label="Layout kamera">{[[1,'Fokus'],[4,'2 × 2'],[9,'3 × 3'],[16,'4 × 4']].map(([value,label]) => <button key={value} aria-pressed={layout === value} onClick={() => {setLayout(value); setFocused(false);}}>{label}</button>)}</div><div className="overlay-controls">{[['zones','Zona'],['detection','Deteksi'],['tracks','Track ID']].map(([key,label]) => <label key={key}><input type="checkbox" checked={overlay[key]} onChange={e => setOverlay(previous => ({...previous,[key]:e.target.checked}))}/>{label}</label>)}</div><Button icon={screenExpanded ? Minimize2 : Maximize2} onClick={() => fullscreen(true)}>{screenExpanded ? 'Keluar layar penuh' : 'Layar penuh semua kamera'}</Button><Button icon={PanelRight} className="detail-toggle" onClick={() => setInspector(value => !value)}>Detail kamera</Button></div>
      <div className={`camera-grid layout-${focused ? 1 : layout}`} style={{'--camera-rows':focused || layout === 1 ? 1 : Math.ceil((shown.length + emptySlots) / Math.sqrt(layout)) || 1}} data-testid="camera-grid">{shown.map(c => {
        const unavailable = ['OFFLINE','DISABLED','RECONNECTING'].includes(c.status);
        return <article key={c.id} className={`video-tile ${camera?.id === c.id ? 'selected' : ''}`}><div className="video-heading"><button className="camera-name" onClick={() => setSelected(c.id)}>{c.name}</button><span className="mono">{c.id}</span><button className="icon-button" aria-label={`Fokus ${c.name}`} onClick={() => {setSelected(c.id); setFocused(value => !value);}}>{focused ? <Minimize2 size={14}/> : <Maximize2 size={14}/>}</button></div>
          <div className="video-content" onDoubleClick={() => {setSelected(c.id);setFocused(true);}}>{unavailable&&<div className="stream-placeholder"><strong>{CAMERA_LABELS[c.status]}</strong></div>}</div>
          <div className="video-footer"><Status value={c.status}/></div>
        </article>;
      })}{Array.from({length:emptySlots},(_,index) => <button key={`empty-${index}`} className="video-empty-slot" aria-label={`${t('Tambah kamera')} · Slot ${shown.length + index + 1}`} onClick={addCamera}><Plus size={20} aria-hidden="true"/><strong>Slot {shown.length + index + 1}</strong><span>{t('Tambah kamera')}</span></button>)}</div>
      {!shown.length && (search||statusFilter!=='ALL') && <Empty title="Tidak ada kamera yang cocok" action={<Button onClick={() => {setSearch('');setStatusFilter('ALL');}}>Hapus filter</Button>}/>}
      <div className="video-actions">{focused&&<><Button onClick={()=>fullscreen()}>Layar penuh</Button><Button onClick={()=>setFocused(false)}>Kembali ke grid</Button></>}</div></div>
    </div>
    <aside className="monitor-inspector panel"><div className="panel-heading"><h2>Detail kamera</h2><button className="inspector-close icon-button" onClick={()=>setInspector(false)} aria-label="Tutup detail kamera">×</button></div>{camera&&<div className="inspector-body"><h3>{camera.name}</h3><p className="caption">{camera.area}</p><dl className="detail-list"><dt>Koneksi</dt><dd><Status value={camera.status}/></dd><dt>Target inferensi</dt><dd>{camera.fps} FPS</dd></dl>
      <Button onClick={() => setDialog({type:'camera',camera})}>Edit konfigurasi</Button>
    </div>}</aside>
  </div>;
}
