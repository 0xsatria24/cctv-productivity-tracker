import { Button } from './components';

const checkinState={VERIFIED_MARKER:'Marker terkonfirmasi',CONFIRMING:'Menunggu konfirmasi marker',
  AMBIGUOUS:'Check-in ambigu',UNLISTED_MARKER:'Marker belum terdaftar',UNASSOCIATED:'Marker tidak dapat dikaitkan ke satu orang',UNREGISTERED:'Marker tidak terverifikasi'};

export function WorkstationResults({rows,history=[],notice,formatTime,fresh,playing,enabled,onCalibrate,ready,calibrated,zones,aruco,liveMode=false}) {
  function download() {
    const cell=value=>`"${String(value??'').replace(/^[=+\-@\t\r]/,"'$&").replaceAll('"','""')}"`;
    const records=[['workstation','versi_area','terisi_detik','kosong_detik','nama_checkin_terakhir','marker_id',liveMode?'checkin_sesi_detik':'checkin_video_detik'],
      ...[...history.map(row=>({...row,version:'Riwayat'})),...rows.map(row=>({...row,version:'Saat ini'}))].map(row=>[row.name,row.version,row.occupied_us/1e6,row.empty_us/1e6,
        row.checkin?.registered?.label,row.checkin?.registered?.marker_id,row.checkin?.registered?.checked_in_media_seconds])];
    const url=URL.createObjectURL(new Blob(['\uFEFF'+records.map(row=>row.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download=liveMode?'durasi-workstation-live.csv':'durasi-workstation.csv';anchor.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <section className="replay-workstations" aria-label={liveMode?'Durasi workstation live':'Durasi workstation replay'}>
    <div className="inline-controls"><strong>Timer utama workstation</strong><Button disabled={!ready} onClick={onCalibrate}>Atur area</Button><Button disabled={!rows.length&&!history.length} onClick={download}>Unduh durasi CSV</Button></div>
    {!calibrated?<p className="caption">{zones.length?'Area tersimpan sedang disiapkan.':'Klik Atur area untuk menandai tempat kerja.'}</p>:!zones.length?<p className="caption">Belum ada area aktif.</p>:!rows.length?<p className="caption">{liveMode?'Area siap. Mulai monitoring untuk mengukur durasi.':'Area siap. Aktifkan Deteksi preview dan putar video untuk mulai mengukur.'}</p>:<div className="replay-workstation-rows">{rows.map(row=><div key={row.zone_id} data-zone-id={row.zone_id}>
      <div><strong>{row.name}</strong>{enabled&&playing&&fresh&&['OCCUPIED','EMPTY'].includes(row.state)&&<span>{row.state==='OCCUPIED'?'Terisi':'Kosong'}</span>}</div>
      <dl><div><dt>Terisi</dt><dd>{formatTime(row.occupied_us/1e6)}</dd></div><div><dt>Kosong</dt><dd>{formatTime(row.empty_us/1e6)}</dd></div></dl>
      {row.checkin&&<p className="caption" data-testid="workstation-checkin">{row.checkin.registered?`Terdaftar: ${row.checkin.registered.label} · marker ${row.checkin.registered.marker_id} · terakhir dibaca ${formatTime(row.checkin.registered.last_seen_media_seconds)}. `:'Belum ada pemilik marker terdaftar. '}{fresh&&playing&&enabled?checkinState[row.checkin.state]:'Verifikasi dijeda'}</p>}
    </div>)}</div>}
    {aruco?.status==='UNAVAILABLE'&&<p role="alert" className="error-text">ArUco tidak tersedia: {aruco.message}</p>}
    {aruco?.status==='READY'&&<p className="caption" data-testid="aruco-status">ArUco: {aruco.markers.length} marker terbaca pada sampel terakhir{aruco.markers.length?` (ID ${aruco.markers.map(row=>row.marker_id).join(', ')})`:''}. Pusat marker harus berada di dalam deteksi tubuh pada satu zona yang terisi satu orang.</p>}
    {!!history.length&&<details><summary>Riwayat area ({history.length})</summary><p className="caption">Hasil sebelum batas area diubah. Data ini ikut disertakan pada CSV.</p>{history.map((row,i)=><p className="caption" key={i}>{row.name} · Terisi {formatTime(row.occupied_us/1e6)} · Kosong {formatTime(row.empty_us/1e6)}</p>)}</details>}
    {notice&&<p className="caption" role="status">{notice}</p>}
    <p className="caption">{liveMode?'Timer mengikuti area selama sesi monitoring. Saat bukti kamera terputus, durasi terisi berhenti bertambah. Atur area menghentikan sesi aktif; catatan sesi sebelumnya tetap tersimpan di laporan. Nama check-in tidak membuktikan kehadiran terus-menerus.':'Timer di box menunjukkan durasi terisi sampai posisi video. Geser maju atau mundur untuk melihatnya pada posisi tersebut; bagian yang dilewati tidak menambah durasi. Tabel dan CSV menyimpan total seluruh analisis tanpa menghitung ulang bagian yang sama. Hasil dimuat lagi saat file yang sama dipilih. Perubahan batas area menyimpan hasil lama di Riwayat. Nama check-in tidak membuktikan kehadiran terus-menerus.'}</p>
    {rows.some(row=>row.media_intervals_complete===false)&&<p className="caption">Total lama tetap tersimpan. Rincian timer per posisi untuk data lama tersedia setelah bagian videonya diputar dan dianalisis lagi.</p>}
  </section>;
}
