import { Button, Field } from './components';

export function ArucoRegistry({markers,onChange,disabled}) {
  const update=(index,values)=>onChange(markers.map((row,i)=>i===index?{...row,...values}:row));
  function add() {
    const marker_id=Array.from({length:50},(_,i)=>i).find(id=>!markers.some(row=>row.marker_id===id));
    if(marker_id!==undefined)onChange([...markers,{marker_id,label:''}]);
  }
  return <fieldset className="aruco-registry" disabled={disabled}>
    <legend>Check-in ArUco (opsional)</legend>
    <p className="caption">Daftarkan nama untuk marker DICT_4X4_50. Tunjukkan marker di depan tubuh, di dalam zona yang terisi satu orang; tiga pembacaan selama minimal 0,4 detik mengonfirmasi check-in. Nama terdaftar tidak berarti orang terus terlihat.</p>
    {markers.map((row,i)=><div className="aruco-registry-row" key={i}>
      <Field label={`ID marker ${i+1}`}><input type="number" min="0" max="49" step="1" value={row.marker_id} onChange={e=>update(i,{marker_id:e.target.value===''?'':Number(e.target.value)})}/></Field>
      <Field label={`Nama pemilik marker ${i+1}`}><input maxLength={80} value={row.label} placeholder="Nama atau kode pekerja" onChange={e=>update(i,{label:e.target.value})}/></Field>
      {Number.isInteger(row.marker_id)&&row.marker_id>=0&&row.marker_id<50&&<a href={`/pilot/v1/aruco/${row.marker_id}.png`} download={`aruco-${row.marker_id}.png`}>Unduh marker {row.marker_id}</a>}
      <Button aria-label={`Hapus marker ${i+1}`} onClick={()=>onChange(markers.filter((_,j)=>j!==i))}>Hapus</Button>
    </div>)}
    <Button disabled={markers.length>=50} onClick={add}>Tambah marker</Button>
    <p className="caption">Cetak dengan tepi putih tetap utuh, permukaan datar dan tidak mengilap. Uji ukuran serta jarak pada kamera asli. Marker di meja hanya mengidentifikasi meja, bukan pekerja.</p>
  </fieldset>;
}
