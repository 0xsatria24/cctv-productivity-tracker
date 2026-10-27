import { useEffect, useState } from 'react';
import { ArrowLeft, Pencil, Plus, RotateCcw, RotateCw, Save, Trash2 } from 'lucide-react';
import { usePrototype } from './store';
import { Button, DataTable, Empty, Field, Panel, Status } from './components';
import { validPolygon } from './domain';
import Scene from './Scene';

const defaultPolygon = [[.12,.33],[.43,.33],[.43,.78],[.12,.78]];
export default function Workspaces({ navigate, workspaceId }) {
  const { state, observed, setDialog, saveWorkspace, setDirtyPage } = usePrototype();
  const [search,setSearch] = useState(''), [status,setStatus] = useState('ALL'), [area,setArea] = useState('ALL'), [selected,setSelected] = useState(workspaceId || state.workspaces[0]?.id);
  const [draft,setDraft] = useState(null), [history,setHistory] = useState([]), [position,setPosition] = useState(0), [vertex,setVertex] = useState(0), [adding,setAdding] = useState(false);
  useEffect(() => { if (workspaceId) setSelected(workspaceId); },[workspaceId]);
  useEffect(() => () => setDirtyPage(false),[setDirtyPage]);
  const rows = observed.filter(w => w.name.toLowerCase().includes(search.toLowerCase()) && (status === 'ALL' || w.liveState === status) && (area === 'ALL' || w.area === area));
  const current = observed.find(w => w.id === selected);
  function edit(workspace = null) {
    const value = structuredClone(workspace ? { ...workspace, rulePreset: workspace.rulePreset || 'Desk standard' } : {name:'',cameraId:state.cameras.find(c => c.status === 'ONLINE')?.id || state.cameras[0]?.id,kind:'desk',capacity:1,rulePreset:'Desk standard',polygon:defaultPolygon});
    setDraft(value);setHistory([value.polygon]);setPosition(0);setVertex(0);setAdding(false);setDirtyPage(false);
  }
  function change(value) { setDraft(previous => ({...previous,...value}));setDirtyPage(true); }
  function points(value) {
    change({polygon:value}); const next=[...history.slice(0,position+1),structuredClone(value)].slice(-40);setHistory(next);setPosition(next.length-1);setVertex(v => Math.min(v,value.length-1));
  }
  function undo(delta) { const next=position+delta;if(next<0||next>=history.length)return;setPosition(next);change({polygon:structuredClone(history[next])});setVertex(v => Math.min(v,history[next].length-1)); }
  function exit() { if (draft && JSON.stringify(draft.polygon)!==JSON.stringify(history[0]) && !window.confirm('Buang perubahan geometri yang belum disimpan?')) return;setDraft(null);setDirtyPage(false); }
  function drag(event,index) {
    const svg=event.currentTarget.ownerSVGElement, rect=svg.getBoundingClientRect();
    setVertex(index);
    let latest=draft.polygon;
    const move=pointer => { latest=draft.polygon.map((point,i) => i === index ? [Math.max(0,Math.min(1,(pointer.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(pointer.clientY-rect.top)/rect.height))] : point);change({polygon:latest}); };
    const finish=() => {window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);points(latest);};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish,{once:true});
  }
  if (!state.cameras.length) return <Empty title="Tambahkan kamera terlebih dahulu" description="Editor membutuhkan frame acuan simulasi dan satu kamera utama." action={<Button onClick={() => setDialog({type:'camera'})}>Tambah kamera</Button>}/>;
  if (draft) {
    const camera=state.cameras.find(c => c.id===draft.cameraId);
    const valid=validPolygon(draft.polygon) && !!draft.name.trim() && Number.isInteger(Number(draft.capacity)) && draft.capacity>=1 && draft.capacity<=10000;
    const fresh=camera && ['ONLINE','DEGRADED'].includes(camera.status);
    const save=() => {if(!valid||!fresh)return;setDialog({type:'revision',draft:structuredClone(draft),onConfirm:() => {saveWorkspace(draft);setDraft(null);}});};
    return <div className="editor-workflow"><div className="workflow-toolbar"><Button icon={ArrowLeft} onClick={exit}>Kembali ke workstation</Button><span className="caption">Draft lokal · histori tidak diubah</span><Button variant="primary" icon={Save} disabled={!valid||!fresh} onClick={save}>Review dan simpan</Button></div>
      <div className="editor-layout"><Panel title="Frame acuan editor" caption={`${camera?.name} · ilustrasi simulasi`} action={<span className="tag">5 FPS (mock)</span>}><div className="editor-tools"><Button variant={adding ? 'primary':'secondary'} icon={Plus} disabled={draft.polygon.length>=64} onClick={() => setAdding(value => !value)}>{adding ? 'Klik frame untuk tambah titik':'Tambah titik'}</Button><Button icon={RotateCcw} disabled={position===0} onClick={() => undo(-1)}>Undo</Button><Button icon={RotateCw} disabled={position===history.length-1} onClick={() => undo(1)}>Redo</Button><Button icon={Trash2} disabled={draft.polygon.length<=3} onClick={() => points(draft.polygon.filter((_,i) => i!==vertex))}>Hapus titik</Button></div>
        <div className="polygon-frame"><Scene camera={camera} now={state.clock} editPolygon={draft.polygon} selectedVertex={vertex} onVertexDown={drag} onCanvasClick={event => {if(!adding)return;const rect=event.currentTarget.getBoundingClientRect();points([...draft.polygon,[(event.clientX-rect.left)/rect.width,(event.clientY-rect.top)/rect.height]]);}}/></div>
        <div className="vertex-heading"><h3>Koordinat vertex</h3><span className="caption">Normalized 0..1. Drag atau edit dengan keyboard.</span></div><div className="table-scroll"><table className="vertex-table"><thead><tr><th>Titik</th><th>X</th><th>Y</th><th>Validasi</th></tr></thead><tbody>{draft.polygon.map(([x,y],i) => <tr key={i} className={vertex===i?'selected-row':''}><td><button className="text-button" aria-label={`Pilih titik ${i+1}`} aria-pressed={vertex===i} onClick={() => setVertex(i)}>{i+1}</button></td><td><input type="number" step="0.01" min="0" max="1" aria-label={`Koordinat X titik ${i+1}`} value={Math.round(x*1000)/1000} onChange={e => points(draft.polygon.map((p,j) => j===i?[Number(e.target.value),p[1]]:p))}/></td><td><input type="number" step="0.01" min="0" max="1" aria-label={`Koordinat Y titik ${i+1}`} value={Math.round(y*1000)/1000} onChange={e => points(draft.polygon.map((p,j) => j===i?[p[0],Number(e.target.value)]:p))}/></td><td className="caption">{x>=0&&x<=1&&y>=0&&y<=1?'Dalam frame':'Di luar frame'}</td></tr>)}</tbody></table></div>
      </Panel><Panel title="Properti zona"><div className="form-stack"><Field label="Nama workstation"><input value={draft.name} maxLength={100} onChange={e => change({name:e.target.value})} placeholder="Contoh: Meja A03"/></Field><Field label="Jenis zona"><select value={draft.kind} onChange={e => change({kind:e.target.value})}><option value="desk">Desk</option><option value="room">Room (tidak masuk total desk)</option><option value="area">Area (tidak masuk total desk)</option></select></Field><Field label="Kapasitas"><input type="number" min="1" max="10000" value={draft.capacity} onChange={e => change({capacity:Number(e.target.value)})}/></Field><Field label="Kamera utama"><select value={draft.cameraId} onChange={e => change({cameraId:e.target.value})}>{state.cameras.map(c => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}</select></Field><Field label="Rule preset simulasi"><select value={draft.rulePreset} onChange={e => change({rulePreset:e.target.value})}><option>Desk standard</option><option>Konfirmasi konservatif</option><option>Room standard</option></select></Field>
        <div className={`inline-message ${validPolygon(draft.polygon)?'neutral':'error'}`} role={validPolygon(draft.polygon)?undefined:'alert'}>{validPolygon(draft.polygon) ? `Geometri valid, ${draft.polygon.length} titik.` : 'Polygon tidak valid: perlu 3-64 titik, area positif, tanpa self-intersection.'}</div>{!fresh&&<p className="error-text">Kamera belum menyediakan frame simulasi. Sambungkan kamera sebelum menyimpan.</p>}<p className="caption">Revisi saat ini: {draft.revision??'Draft baru'}. Perubahan berlaku untuk observasi berikutnya. Histori menggunakan konfigurasi asal.</p><Button variant="primary" disabled={!valid||!fresh} onClick={save}>Review dan simpan</Button><Button onClick={exit}>Batalkan draft</Button>
      </div></Panel></div>
    </div>;
  }
  return <><div className="filter-toolbar"><Field label="Cari workstation"><input type="search" placeholder="Nama workstation" value={search} onChange={e => setSearch(e.target.value)}/></Field><Field label="Area"><select value={area} onChange={e => setArea(e.target.value)}><option value="ALL">Semua area</option>{[...new Set(state.workspaces.map(w=>w.area))].map(a=><option key={a}>{a}</option>)}</select></Field><Field label="Status observasi"><select value={status} onChange={e=>setStatus(e.target.value)}><option value="ALL">Semua status</option><option value="OCCUPIED">Terisi</option><option value="EMPTY">Kosong</option><option value="UNKNOWN">Tidak diketahui</option></select></Field><Button variant="primary" icon={Plus} onClick={()=>edit()}>Tambah workstation</Button></div>
    <Panel title="Daftar workstation" caption="Data konfigurasi dan observasi simulasi; track bukan employee ID"><DataTable rows={rows} resetKey={`${search}|${area}|${status}`} columns={[
      {key:'name',label:'Workstation',render:w=><button className="text-button" onClick={()=>setSelected(w.id)}>{w.name}</button>}, {key:'area',label:'Area'}, {key:'cameraId',label:'Kamera utama'}, {key:'capacity',label:'Kapasitas',numeric:true}, {key:'revision',label:'Revisi',render:w=><span className="mono">v{w.revision}{w.applyStatus==='PENDING_APPLY'?' · pending':''}</span>}, {key:'liveState',label:'Observasi',render:w=><Status value={w.liveState}/>}, {key:'action',label:'Aksi',sortable:false,render:w=><Button icon={Pencil} onClick={()=>edit(w)}>Edit polygon</Button>}
    ]}/></Panel>{current&&<Panel className="workspace-detail" title={`${current.name} / ${current.id}`} action={<Button onClick={()=>navigate('analytics',{workspaceId:current.id,tab:'timeline'})}>Lihat timeline</Button>}><div className="detail-horizontal"><Status value={current.liveState}/><span>Jumlah teramati: {current.count??'N/A'}</span><span>Jenis: {current.kind}</span><span>Kapasitas: {current.capacity}</span><span>Konfigurasi v{current.revision}</span><Button onClick={()=>edit(current)}>Edit konfigurasi</Button></div></Panel>}</>;
}
