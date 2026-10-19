import { useEffect, useRef, useState } from 'react';
import { Button, DataTable, Field, Panel, Status } from './components';
import { engineRequest } from './engine-client';

const EMPTY = {enabled:false,kind:'local',folder:'',remote:'',prefix:'CCTV',endpoint:'',bucket:'',region:'us-east-1',provider:'Other',access_key:'',secret_key:'',session_token:''};
const KINDS = {local:'Lokal aplikasi',folder:'Folder pilihan / server lokal / NAS',rclone:'Cloud / SFTP / WebDAV via rclone',s3:'S3 compatible / MinIO'};
const STATES = {PENDING:'Menunggu',UPLOADING:'Mengunggah',RETRY:'Menunggu coba ulang',COMPLETED:'Terkirim',FAILED:'Gagal'};

export function RecordingDestination({engine}) {
  const [data,setData]=useState(null),[draft,setDraft]=useState(null),[dirty,setDirty]=useState(false),[busy,setBusy]=useState(false);
  const [readError,setReadError]=useState(''),[actionError,setActionError]=useState(''),[remotes,setRemotes]=useState(null);
  const generation=useRef(0), saving=useRef(false);
  useEffect(()=>{
    const abort=new AbortController();let timer;
    async function poll(){
      const before=generation.current;
      try{const value=await engineRequest('recordings/destination',{signal:abort.signal});if(!abort.signal.aborted&&before===generation.current&&!saving.current){setData(value);setReadError('');}}
      catch(failure){if(!abort.signal.aborted)setReadError(failure.message);}
      finally{if(!abort.signal.aborted)timer=setTimeout(poll,2000);}
    }
    poll();return()=>{abort.abort();clearTimeout(timer);};
  },[]);
  useEffect(()=>{if(data&&!dirty)setDraft({...EMPTY,...data.config});},[data,dirty]);
  function change(key,value){setDraft(previous=>({...previous,[key]:value,...(key==='kind'?{enabled:value!=='local',access_key:'',secret_key:'',session_token:''}:{})}));setDirty(true);}
  async function action(path,body,method='POST'){
    generation.current++;saving.current=true;setBusy(true);setActionError('');
    try{return await engineRequest(`recordings/destination${path}`,{method,...(body?{body:JSON.stringify(body)}:{})});}
    catch(failure){setActionError(failure.message);throw failure;}
    finally{generation.current++;saving.current=false;setBusy(false);}
  }
  function save(){action('',draft).then(value=>{setData(value);setDirty(false);engine.toast('Tujuan penyimpanan auto-save disimpan.');}).catch(()=>{});}
  const pending=(data?.counts.PENDING||0)+(data?.counts.RETRY||0), completed=data?.counts.COMPLETED||0;
  return <Panel title="Tujuan penyimpanan auto-save" caption="File disimpan lokal terlebih dahulu, lalu disalin ke tujuan yang dipilih. Laporan dan video memakai tujuan yang sama." className="recording-destination">
    {draft?<><form onSubmit={event=>{event.preventDefault();save();}}><div className="form-grid settings-form">
      <Field label="Simpan salinan ke"><select value={draft.kind} disabled={busy} onChange={event=>change('kind',event.target.value)}>{Object.entries(KINDS).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></Field>
      {draft.kind!=='local'&&<label className="check-control recording-toggle"><input type="checkbox" aria-label="Aktifkan pengiriman ke tujuan" checked={draft.enabled} disabled={busy} onChange={event=>change('enabled',event.target.checked)}/><span>Kirim file otomatis<small aria-hidden="true">{draft.enabled?'Aktif':'Nonaktif'}</small></span></label>}
      {draft.kind==='folder'&&<Field className="full-width" label="Folder tujuan server / NAS" hint="Gunakan path absolut atau share yang sudah bisa diakses akun Windows yang menjalankan aplikasi."><input value={draft.folder} placeholder={'D:\\CCTV-Archive atau \\\\NAS\\CCTV'} disabled={busy} onChange={event=>change('folder',event.target.value)}/></Field>}
      {draft.kind==='rclone'&&<><Field label="Nama remote cloud" hint="Nama koneksi yang dibuat melalui rclone config."><input list="record-cloud-remotes" value={draft.remote} placeholder="drive-kantor" disabled={busy} onChange={event=>change('remote',event.target.value)}/><datalist id="record-cloud-remotes">{remotes?.remotes.map(remote=><option key={remote.name} value={remote.name}>{remote.type}</option>)}</datalist></Field><div className="inline-controls"><Button type="button" disabled={busy} onClick={()=>action('/remotes',null,'GET').then(setRemotes).catch(()=>{})}>Perbarui daftar cloud</Button><Button type="button" onClick={()=>navigator.clipboard.writeText(data.setup_command).then(()=>engine.toast('Perintah setup cloud disalin. Jalankan di terminal, lalu login ke provider.')).catch(()=>engine.toast('Clipboard tidak tersedia. Salin perintah di bawah secara manual.'))}>Salin perintah setup cloud</Button></div><div className="full-width"><p className="caption">Google Drive, OneDrive, Dropbox, Azure, Google Cloud, SFTP, WebDAV, dan backend lain yang didukung rclone. Login atau kredensial provider diperlukan satu kali melalui terminal, lalu pilih nama remote di sini.</p><pre className="maintenance-command">{data.setup_command}</pre><a href="https://rclone.org/overview/" target="_blank" rel="noreferrer">Lihat daftar provider dan kemampuan yang didukung</a>{remotes&&!remotes.remotes.length&&<p>Belum ada remote cloud. Jalankan perintah setup di atas dengan akun sistem operasi yang sama.</p>}</div></>}
      {draft.kind==='s3'&&<><Field label="Provider S3"><select value={draft.provider} disabled={busy} onChange={event=>change('provider',event.target.value)}>{['AWS','Other','Minio','Cloudflare','Wasabi','DigitalOcean'].map(value=><option key={value}>{value}</option>)}</select></Field><Field label="Endpoint API S3" hint="Untuk AWS boleh kosong. Gunakan HTTPS untuk cloud atau alamat server MinIO/NAS."><input value={draft.endpoint} placeholder="https://s3.example.com" disabled={busy} onChange={event=>change('endpoint',event.target.value)}/></Field><Field label="Bucket S3"><input value={draft.bucket} disabled={busy} onChange={event=>change('bucket',event.target.value)}/></Field><Field label="Region S3"><input value={draft.region} disabled={busy} onChange={event=>change('region',event.target.value)}/></Field>{[['access_key','Access key S3'],['secret_key','Secret key S3'],['session_token','Session token S3 (opsional)']].map(([key,label])=><Field key={key} label={label} hint={data.secrets_configured[key]?'Kredensial tersimpan. Kosongkan untuk mempertahankan jika koneksi sama.':undefined}><input type="password" autoComplete="new-password" value={draft[key]} disabled={busy} onChange={event=>change(key,event.target.value)}/></Field>)}<p className="caption full-width">Kredensial disimpan terenkripsi di backend dan tidak dikembalikan ke browser. Jika endpoint, bucket, provider, atau region berubah, isi kredensial kembali.</p></>}
      {draft.kind!=='local'&&<Field label="Subfolder / prefix tujuan"><input value={draft.prefix} placeholder="CCTV" disabled={busy} onChange={event=>change('prefix',event.target.value)}/></Field>}
      <div className="inline-controls full-width"><Button type="submit" variant="primary" disabled={busy}>{busy?'Memproses...':'Simpan tujuan penyimpanan'}</Button><Button type="button" disabled={busy||data.test.state==='RUNNING'} onClick={()=>action('/test',draft).then(result=>{setData(previous=>({...previous,test:result}));engine.toast('Uji tujuan dimulai. Hasil akan muncul di bawah.');}).catch(()=>{})}>{data.test.state==='RUNNING'?'Uji koneksi berjalan...':'Uji koneksi tujuan'}</Button></div>
      {dirty&&<p className="caption full-width">Perubahan tujuan belum disimpan. Uji koneksi memakai isian saat ini dan membuat lalu menghapus satu file uji.</p>}
      {draft.kind==='local'&&<p className="caption full-width">File tetap berada di folder lokal aplikasi; tidak ada pengiriman tambahan.</p>}
    </div></form>
    <p className="caption" data-testid="record-destination-saved">Tujuan tersimpan: {KINDS[data.config.kind]} · {data.config.enabled?'pengiriman aktif':'pengiriman nonaktif'}.</p>
    {(draft.kind==='rclone'||draft.kind==='s3')&&!data.rclone_available&&<p role="alert">Transport cloud belum terpasang. Jalankan python scripts/setup_storage_transport.py, lalu perbarui daftar cloud.</p>}
    <div className="recording-summary"><span>{pending} file menunggu</span><span>{data.counts.UPLOADING||0} sedang dikirim</span><span>{completed} terkirim</span><span>{data.counts.FAILED||0} gagal</span></div>
    <p role={data.test.state==='FAILED'?'alert':'status'}>{data.test.message||'Uji koneksi sedang berjalan.'}</p>
    <div className="inline-controls"><Button disabled={busy} onClick={()=>action('/retry').then(setData).catch(()=>{})}>Coba ulang upload gagal</Button><Button disabled={busy} onClick={()=>action('/enqueue-recent').then(value=>engine.toast(`${value.queued_files} file dari ${value.records_checked} record terbaru masuk antrean.`)).catch(()=>{})}>Antrekan 50 file terbaru</Button></div>
    <p className="caption">Pengiriman berlaku untuk file baru setelah tujuan disimpan dan diaktifkan. File lokal tetap ada. Jaringan putus akan dicoba ulang hingga delapan kali; setelah itu gunakan Coba ulang. Satu upload yang sudah berjalan dapat selesai saat pengiriman dimatikan.</p>
    {data.paused_other_destination>0&&<p role="status">{data.paused_other_destination} file belum selesai untuk tujuan sebelumnya. Antrean tersebut tidak otomatis dialihkan ke tujuan baru.</p>}
    {!!data.recent.length&&<DataTable rows={data.recent} testId="record-upload-jobs" pageSize={5} columns={[{key:'filename',label:'File',render:row=><span className="upload-filename">{row.filename}</span>},{key:'state',label:'Pengiriman',render:row=><Status value={row.state} label={STATES[row.state]||row.state}/>},{key:'attempts',label:'Percobaan',numeric:true},{key:'error',label:'Keterangan',sortable:false,render:row=>row.error||'Tidak ada error'}]}/>}</>:<p>Memuat tujuan penyimpanan...</p>}
    {(actionError||readError)&&<p role="alert" className="error-text">{actionError||readError}</p>}
  </Panel>;
}
