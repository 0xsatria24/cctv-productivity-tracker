import { useState } from 'react';
import { Button, Field, Modal } from './components';
import { ArucoRegistry } from './aruco-registry';

export function ReplayCalibration({ initial, image, onClose, onSave }) {
  const [zones,setZones]=useState(()=>structuredClone(initial.zones));
  const [association,setAssociation]=useState(initial.association);
  const [markers,setMarkers]=useState(()=>structuredClone(initial.markers || []));
  const [selected,setSelected]=useState(0), [error,setError]=useState(''), [saving,setSaving]=useState(false);
  const zone=zones[selected];
  function update(change) {setZones(rows=>rows.map((row,i)=>i===selected?{...row,...change}:row));setError('');}
  function addPoint(event) {
    if(!zone || zone.polygon.length>=32 || saving)return;
    const rect=event.currentTarget.getBoundingClientRect();
    update({polygon:[...zone.polygon,[Math.min(1,Math.max(0,(event.clientX-rect.left)/rect.width)),Math.min(1,Math.max(0,(event.clientY-rect.top)/rect.height))]]});
  }
  async function save() {
    setSaving(true);setError('');
    try {await onSave({zones,association,markers});onClose();} catch(failure) {setError(failure.name==='TimeoutError'?'Engine melewati batas waktu. Coba terapkan kembali.':failure.message);} finally {setSaving(false);}
  }
  return <Modal title="Kalibrasi workstation replay" description="Tandai area setiap workstation pada frame ini. Perubahan zona memulai pengukuran baru dari posisi video sekarang." onClose={()=>{if(!saving)onClose();}} wide
    footer={<><Button disabled={saving} onClick={onClose}>Batal</Button><Button variant="primary" disabled={saving || zones.some(row=>!row.name.trim() || row.polygon.length<3)} onClick={save}>{saving?'Menyimpan...':'Terapkan zona'}</Button></>}>
    <div className="replay-calibration">
      <Field label="Cara mengaitkan orang"><select disabled={saving} value={association} onChange={e=>setAssociation(e.target.value)}><option value="bbox_overlap">Overlap tubuh (area kerja)</option><option value="footpoint">Titik kaki (area lantai)</option></select></Field>
      <p className="caption">Overlap tubuh cocok untuk area kerja yang terlihat; titik kaki memerlukan kaki yang terlihat. Zona bertumpuk dapat menghasilkan status tidak pasti. Klik gambar untuk menambah sudut, atau isi koordinat persen dengan keyboard.</p>
      <div className="replay-calibration-image" style={{aspectRatio:image.width/image.height}}>
        <img src={image.url} alt="Frame video untuk kalibrasi zona"/>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Poligon workstation" onClick={addPoint}>
          {zones.map((row,i)=><polygon key={row.id} points={row.polygon.map(p=>p.map(v=>v*100).join(',')).join(' ')} className={i===selected?'selected':''}/>)}
          {zone?.polygon.map(([x,y],i)=><circle key={i} cx={x*100} cy={y*100} r=".8"/>)}
        </svg>
      </div>
      <div className="inline-controls"><Button disabled={saving || zones.length>=16} onClick={()=>{setZones(rows=>[...rows,{id:crypto.randomUUID(),name:`Workstation ${rows.length+1}`,polygon:[]}]);setSelected(zones.length);}}>Tambah workstation</Button>
        {!!zones.length&&<Field label="Workstation"><select disabled={saving} value={selected} onChange={e=>setSelected(Number(e.target.value))}>{zones.map((row,i)=><option key={row.id} value={i}>{row.name || `Zona ${i+1}`}</option>)}</select></Field>}
      </div>
      {zone?<>
        <Field label="Nama workstation"><input value={zone.name} maxLength={80} disabled={saving} onChange={e=>update({name:e.target.value})}/></Field>
        <div className="replay-points">{zone.polygon.map(([x,y],index)=><div key={index} className="replay-point"><span>Titik {index+1}</span>{[['X',x],['Y',y]].map(([axis,value],coord)=><Field key={axis} label={`${axis} titik ${index+1} (%)`}><input type="number" min="0" max="100" step="0.1" value={Number((value*100).toFixed(2))} disabled={saving} onChange={e=>update({polygon:zone.polygon.map((p,i)=>i===index?p.map((v,j)=>j===coord?Number(e.target.value)/100:v):p)})}/></Field>)}<Button disabled={saving} aria-label={`Hapus titik ${index+1}`} onClick={()=>update({polygon:zone.polygon.filter((_,i)=>i!==index)})}>Hapus titik</Button></div>)}</div>
        <div className="inline-controls"><Button disabled={saving || zone.polygon.length>=32} onClick={()=>update({polygon:[...zone.polygon,[.5,.5]]})}>Tambah titik</Button><Button disabled={saving || !zone.polygon.length} onClick={()=>update({polygon:zone.polygon.slice(0,-1)})}>Urungkan titik</Button><Button disabled={saving} onClick={()=>{setZones(rows=>rows.filter((_,i)=>i!==selected));setSelected(0);}}>Hapus workstation</Button></div>
      </>:<p className="caption">Belum ada zona. Tambahkan workstation, lalu tandai minimal tiga sudut. Tanpa zona, timer workstation tidak tersedia.</p>}
      <ArucoRegistry markers={markers} onChange={setMarkers} disabled={saving}/>
      <p className="caption">Zona dan daftar marker disimpan di browser untuk file ini. Timer mengukur keterisian area. Check-in mencatat pemilik marker yang terakhir terkonfirmasi.</p>
      {error&&<p className="error-text" role="alert">{error}</p>}
    </div>
  </Modal>;
}
