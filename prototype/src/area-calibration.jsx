import { useRef, useState } from 'react';
import { Button, Field, Modal } from './components';
import { ArucoRegistry } from './aruco-registry';
import { validPolygon } from './domain';
import { rectangleZone } from './replay-domain';

export function AreaCalibration({initial,image,onClose,onSave,liveMode=false}) {
  const [zones,setZones]=useState(()=>structuredClone(initial.zones));
  const [association,setAssociation]=useState(initial.association),[markers,setMarkers]=useState(()=>structuredClone(initial.markers||[]));
  const [selected,setSelected]=useState(0),[drawing,setDrawing]=useState(false),[undo,setUndo]=useState([]);
  const [error,setError]=useState(''),[saving,setSaving]=useState(false);
  const surface=useRef(null),action=useRef(null),zone=zones[selected];
  const valid=row=>row.name.trim()&&validPolygon(row.polygon);
  const badMarkers=markers.some(row=>!Number.isInteger(row.marker_id)||row.marker_id<0||row.marker_id>49||!row.label.trim())||new Set(markers.map(row=>row.marker_id)).size!==markers.length;
  const changed=association!==initial.association||initial.zones.some(old=>{const next=zones.find(row=>row.id===old.id);return !next||JSON.stringify(next.polygon)!==JSON.stringify(old.polygon);});
  function point(event) {const box=surface.current.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))];}
  function update(polygon) {setZones(rows=>rows.map((row,i)=>i===selected?{...row,polygon}:row));setError('');}
  function remember() {setUndo(items=>[...items.slice(-29),structuredClone(zones)]);}
  function add() {remember();setZones([...zones,{id:crypto.randomUUID(),name:`Area ${zones.length+1}`,polygon:[]}]);setSelected(zones.length);setDrawing(true);setError('');}
  function start(event,index=null) {
    if(saving||!zone||event.button!==0||(index===null&&!drawing))return;
    event.stopPropagation();surface.current.setPointerCapture(event.pointerId);action.current={index,start:point(event),before:structuredClone(zones)};
  }
  function move(event) {
    if(!action.current)return;
    const p=point(event);update(action.current.index===null?rectangleZone(action.current.start,p):zone.polygon.map((old,i)=>i===action.current.index?p:old));
  }
  function finish(event) {
    if(!action.current)return;
    const before=action.current.before;
    setUndo(items=>[...items.slice(-29),before]);action.current=null;setDrawing(false);
    if(surface.current.hasPointerCapture(event.pointerId))surface.current.releasePointerCapture(event.pointerId);
    if(!validPolygon(zone.polygon))setError('Area belum terbentuk. Tarik kotak lebih lebar, atau geser sudut agar garis tidak bersilangan.');
  }
  function nudge(event,index) {
    const step={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
    if(!step||saving)return;event.preventDefault();remember();
    update(zone.polygon.map((p,i)=>i===index?p.map((v,axis)=>Math.max(0,Math.min(1,v+step[axis]*(event.shiftKey ? .001 : .01)))):p));
  }
  async function save() {
    setSaving(true);setError('');
    try {await onSave({zones,association,markers});onClose();} catch(failure) {setError(failure.name==='TimeoutError'?'Penyimpanan terlalu lama. Coba lagi.':failure.message);} finally {setSaving(false);}
  }
  return <Modal title="Atur area workstation" description="Beri nama area, lalu tarik kotak di gambar. Geser sudutnya agar mengikuti batas tempat kerja." wide onClose={()=>{if(!saving)onClose();}}
    footer={<><Button disabled={saving} onClick={onClose}>Batal</Button><Button variant="primary" disabled={saving||(liveMode&&!zones.length)||zones.some(row=>!valid(row))||badMarkers||Boolean(action.current)} onClick={save}>{saving?'Menyimpan…':'Simpan area'}</Button></>}>
    <div className="area-editor"><div className="area-editor-main">
      <div className="area-editor-instruction" role="status">{!zones.length?'Klik Tambah area, lalu tarik kotak pada gambar.':drawing?'Tarik dari satu sudut ke sudut seberangnya pada gambar.':'Geser bulatan untuk merapikan batas. Pilih area lain lewat daftar atau klik bentuknya.'}</div>
      <div className="replay-calibration-image" style={{aspectRatio:image.width/image.height,maxWidth:`calc(46vh * ${image.width/image.height})`,marginInline:'auto',width:'100%'}}>
        <img src={image.url} draggable="false" alt="Gambar video untuk menandai area kerja"/>
        <svg ref={surface} viewBox={`0 0 ${image.width} ${image.height}`} role="group" aria-label="Editor area pada video" className={drawing?'drawing':''} onPointerDown={event=>start(event)} onPointerMove={move} onPointerUp={finish} onPointerCancel={()=>{if(action.current)setZones(action.current.before);action.current=null;}}>
          {zones.map((row,i)=><g key={row.id}><polygon points={row.polygon.map(([x,y])=>`${x*image.width},${y*image.height}`).join(' ')} className={i===selected?'selected':''} onPointerDown={event=>{if(!drawing){event.stopPropagation();setSelected(i);}}}><title>{row.name}</title></polygon>
            {!!row.polygon.length&&<text x={Math.min(...row.polygon.map(p=>p[0]))*image.width+6} y={Math.min(...row.polygon.map(p=>p[1]))*image.height+20} className="area-editor-label">{row.name}</text>}</g>)}
          {!drawing&&zone?.polygon.map(([x,y],i)=><circle key={i} cx={x*image.width} cy={y*image.height} r={image.width*.012} stroke="transparent" strokeWidth="20" vectorEffect="non-scaling-stroke" role="button" tabIndex={saving?-1:0} aria-label={`Sudut ${i+1} ${zone.name}`} onPointerDown={event=>start(event,i)} onKeyDown={event=>nudge(event,i)}/>)}
        </svg>
      </div>
      <div className="inline-controls area-editor-tools"><Button disabled={saving||zones.length>=16} onClick={add}>Tambah area</Button>
        <Button disabled={saving||!undo.length} onClick={()=>{const previous=undo.at(-1);setZones(previous);setSelected(Math.max(0,Math.min(selected,previous.length-1)));setUndo(undo.slice(0,-1));setDrawing(false);setError('');}}>Urungkan</Button>
        {zone&&<Button disabled={saving} onClick={()=>{remember();update(rectangleZone([.25,.25],[.75,.75]));setDrawing(false);}}>Buat kotak di tengah</Button>}</div>
      <p className="caption">Batasi ke tempat kerja, hindari lorong orang lewat dan jangan tumpuk dua area.</p>
    </div><aside className="area-editor-sidebar" aria-label="Daftar area kerja"><strong>{zones.length?`${zones.length} area kerja`:'Belum ada area'}</strong>
      <div className="area-editor-list">{zones.map((row,i)=><button className="area-editor-item" key={row.id} disabled={saving} aria-pressed={i===selected} onClick={()=>{setSelected(i);setDrawing(false);setError('');}}><span>{row.name||`Area ${i+1}`}</span><small>{valid(row)?'Siap':'Belum selesai'}</small></button>)}</div>
      {zone?<><Field label="Nama area"><input maxLength={80} value={zone.name} disabled={saving} onChange={event=>setZones(rows=>rows.map((row,i)=>i===selected?{...row,name:event.target.value}:row))}/></Field>
        <Button disabled={saving} onClick={()=>{remember();update([]);setDrawing(true);}}>Gambar ulang area</Button>
        <Button disabled={saving} onClick={()=>{remember();setZones(zones.filter((_,i)=>i!==selected));setSelected(0);setDrawing(false);}}>Hapus area</Button></>:<p className="caption">Klik Tambah area, lalu tarik kotak pada tempat kerja yang ingin dihitung.</p>}
    </aside></div>
    {changed&&<p className="area-editor-change">{liveMode?'Batas ini digunakan pada sesi monitoring berikutnya. Catatan sesi sebelumnya tetap tersimpan di laporan.':'Batas area diubah. Hasil versi sebelumnya tetap tersedia di Riwayat area. Mengubah nama saja tidak mengosongkan timer.'}</p>}
    <details className="area-editor-extra"><summary>Kenali pekerja dengan marker (opsional)</summary><ArucoRegistry markers={markers} onChange={setMarkers} disabled={saving}/></details>
    <details className="area-editor-extra"><summary>Pengaturan lanjutan</summary><p className="caption">Sudut bisa digeser dengan tombol panah; Shift + panah untuk langkah kecil. Koordinat angka di bawah bersifat opsional.</p><Field label="Jenis area"><select disabled={saving} value={association} onChange={event=>setAssociation(event.target.value)}><option value="bbox_overlap">Tempat kerja / meja — gunakan posisi tubuh</option><option value="footpoint">Lantai — gunakan posisi kaki yang terlihat</option></select></Field>
      {zone&&<div className="replay-points">{zone.polygon.map(([x,y],index)=><div className="replay-point" key={index}><span>Sudut {index+1}</span>{[['X',x],['Y',y]].map(([axis,value],coord)=><Field key={axis} label={`${axis} sudut ${index+1} (%)`}><input type="number" min="0" max="100" step="0.1" value={Number((value*100).toFixed(2))} disabled={saving} onChange={event=>update(zone.polygon.map((p,i)=>i===index?p.map((v,j)=>j===coord?Number(event.target.value)/100:v):p))}/></Field>)}</div>)}</div>}</details>
    {badMarkers&&<p className="error-text" role="alert">Setiap marker perlu ID unik 0–49 dan nama pemilik. Lengkapi bagian marker sebelum menyimpan.</p>}
    {error&&<p className="error-text" role="alert">{error}</p>}
  </Modal>;
}
