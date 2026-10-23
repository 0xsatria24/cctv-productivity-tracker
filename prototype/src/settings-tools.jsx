import {useEffect,useRef,useState} from 'react';
import {Button,Empty,Field,Modal,Panel,Status} from './components';
import {engineRequest} from './engine-client';
import {useLanguage} from './language';
import './settings-tools.css';

const sections=[['cameras','Kamera dan pemulihan'],['recordings','Penyimpanan dan rekaman'],['destination','Tujuan penyimpanan tambahan'],['backup','Backup dan pemulihan'],['runtime','Status engine']];
const paths={cameras:'camera-wall',recordings:'recordings',destination:'recordings/destination',backup:'maintenance',runtime:'status?dataset=live'};

function useSettingsResource(path,connected) {
  const [data,setData]=useState(null),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[revision,setRevision]=useState(0);
  const pending=useRef(false),generation=useRef(0);
  const reload=()=>setRevision(value=>value+1);
  useEffect(()=>{
    const abort=new AbortController();const current=++generation.current;
    setData(null);setError('');
    if(connected)engineRequest(path,{signal:abort.signal}).then(value=>{if(!abort.signal.aborted&&generation.current===current)setData(value);}).catch(failure=>{if(!abort.signal.aborted)setError(failure.message);});
    return ()=>abort.abort();
  },[path,connected,revision]);
  async function action(target,body) {
    if(!connected||!data||pending.current)return false;
    pending.current=true;setBusy(true);setError('');setMessage('');
    try {await engineRequest(target,{method:'POST',...(body?{body:JSON.stringify(body)}:{})});setMessage('Perintah diterima oleh engine.');reload();return true;}
    catch(failure){setError(failure.message);return false;}
    finally{pending.current=false;setBusy(false);}
  }
  return {data,error,message,busy,action,reload};
}

export function SettingsTools({engine}) {
  const {t,language,setLanguage}=useLanguage();
  const [section,setSection]=useState('cameras');
  const connected=Boolean(window.__CCTV_ENGINE__);
  return <section className="settings-tools" aria-label={t('Pengaturan engine')}>
    {engine&&<Panel title="Bahasa"><div className="settings-tools-content"><Field label="Bahasa"><select value={language} onChange={event=>setLanguage(event.target.value)}><option value="id">Bahasa Indonesia</option><option value="en">English</option></select></Field></div></Panel>}
    <nav className="settings-tools-nav" aria-label={t('Bagian pengaturan')}>{sections.map(([id,label])=><button key={id} aria-pressed={section===id} onClick={()=>setSection(id)}>{t(label)}</button>)}</nav>
    {!connected&&<p className="settings-connection" role="status">{t('Hubungkan engine untuk mengatur. Jalankan aplikasi terintegrasi melalui run-app.ps1.')}</p>}
    <SettingsSection key={section} section={section} connected={connected} engine={engine}/>
  </section>;
}

function SettingsSection({section,connected,engine}) {
  const resource=useSettingsResource(paths[section],connected);
  const {data,error,message,busy,reload}=resource;
  const {t}=useLanguage();
  return <Panel title={sections.find(([id])=>id===section)[1]} action={<Button disabled={!connected||busy} onClick={reload}>Periksa koneksi</Button>}>
    {error&&<p className="error-text" role="alert">{error}</p>}
    {message&&<p role="status">{t(message)}</p>}
    {connected&&!data&&!error&&<p role="status">{t('Memuat pengaturan...')}</p>}
    {section==='cameras'&&<CameraOptions resource={resource}/>}
    {section==='recordings'&&<RecordingOptions resource={resource}/>}
    {section==='destination'&&<DestinationOptions resource={resource}/>}
    {section==='backup'&&<BackupOptions resource={resource}/>}
    {section==='runtime'&&<RuntimeOptions data={data} engine={engine}/>}
  </Panel>;
}

function CameraOptions({resource}) {
  const {data,busy,action}=resource;
  const {t}=useLanguage();
  return <div className="settings-tools-content">{!data?.cameras?.length?<Empty title={data?'Belum ada kamera':'Daftar kamera belum tersedia'}/>:data.cameras.map(camera=><div key={camera.id} className="settings-camera-row"><div><strong>{camera.name}</strong><Status value={camera.health}/></div><label className="check-control"><input type="checkbox" checked={Boolean(camera.auto_resume)} disabled={busy||!camera.managed} onChange={event=>action(`camera-wall/cameras/${encodeURIComponent(camera.id)}/recovery`,{auto_resume:event.target.checked})}/>{t('Pulihkan otomatis setelah gangguan')}</label></div>)}
    <p className="caption">{t('Pemulihan berlaku per kamera. Zona dan kalibrasi diatur di Pemantauan Live.')}</p>
  </div>;
}

function RecordingOptions({resource}) {
  const {data,busy,action}=resource;const [draft,setDraft]=useState(null);
  const {t}=useLanguage();
  useEffect(()=>{if(data)setDraft({...data.policy});},[data]);
  const change=(key,value)=>setDraft(previous=>({...previous,[key]:value}));
  return <div className="settings-tools-content"><form onSubmit={event=>{event.preventDefault();action('recordings/policy',draft);}}><fieldset disabled={!draft||busy}>
    <div className="settings-tools-grid">{[['data_enabled','Auto-save laporan data'],['video_enabled','Auto-save rekaman video']].map(([key,label])=><label key={key} className="check-control"><input type="checkbox" checked={Boolean(draft?.[key])} onChange={event=>change(key,event.target.checked)}/>{t(label)}</label>)}
    {[['data_interval_seconds','Interval simpan data (detik)',5,3600],['video_segment_seconds','Durasi potongan video (detik)',5,3600],['max_storage_mb','Batas penyimpanan (MB)',512,1048576]].map(([key,label,min,max])=><Field key={key} label={label}><input required type="number" min={min} max={max} step="1" value={draft?.[key]??''} onChange={event=>change(key,event.target.value===''?'':Number(event.target.value))}/></Field>)}
    </div><Button type="submit" variant="primary">Simpan pengaturan rekaman</Button></fieldset></form>
    <Field label="Folder penyimpanan lokal"><input readOnly value={data?.folder||''} disabled={!data}/></Field>
    {data&&<p>{t('File tersimpan')}: {data.files?.length??0} · {((data.storage_bytes||0)/1048576).toFixed(1)} MB</p>}
    {Object.entries(data?.errors||{}).map(([key,value])=><p className="error-text" role="alert" key={key}>{value}</p>)}
  </div>;
}

function DestinationOptions({resource}) {
  const {data,busy,action}=resource;const [draft,setDraft]=useState(null),[kind,setKind]=useState('local');
  const {t}=useLanguage();
  useEffect(()=>{if(data){setDraft({...data.config,access_key:'',secret_key:'',session_token:''});setKind(data.config.kind);}},[data]);
  const change=(key,value)=>setDraft(previous=>({...previous,[key]:value}));
  const common=[['prefix','Subfolder / prefix tujuan']];
  const fields=kind==='folder'?[['folder','Folder server / NAS'],...common]:kind==='rclone'?[['remote','Nama remote rclone'],...common]:kind==='s3'?[['endpoint','Endpoint S3'],['bucket','Bucket S3'],['region','Region S3'],['provider','Provider S3'],...common,['access_key','Access key S3'],['secret_key','Secret key S3'],['session_token','Session token S3']]:[];
  return <div className="settings-tools-content"><Field label="Jenis tujuan"><select value={kind} onChange={event=>{setKind(event.target.value);if(draft)setDraft(previous=>({...previous,kind:event.target.value,access_key:'',secret_key:'',session_token:''}));}}>{[['local','Lokal aplikasi'],['folder','Folder server / NAS'],['rclone','Cloud melalui rclone'],['s3','S3 compatible']].map(([value,label])=><option key={value} value={value}>{t(label)}</option>)}</select></Field>
    <form onSubmit={event=>{event.preventDefault();action('recordings/destination',draft);}}><fieldset disabled={!draft||busy}><label className="check-control"><input type="checkbox" checked={Boolean(draft?.enabled)} disabled={kind==='local'} onChange={event=>change('enabled',event.target.checked)}/>{t('Aktifkan pengiriman tambahan')}</label>
      <div className="settings-tools-grid">{fields.map(([key,label])=><Field key={key} label={label}><input type={key.endsWith('key')||key==='session_token'?'password':'text'} autoComplete="off" value={draft?.[key]??''} onChange={event=>change(key,event.target.value)}/></Field>)}</div>
      <div className="inline-controls"><Button type="submit" variant="primary">Simpan tujuan penyimpanan</Button><Button type="button" onClick={()=>action('recordings/destination/test',draft)}>Uji koneksi tujuan</Button></div>
    </fieldset></form>
    <p className="caption">{t('Kredensial kosong mempertahankan kredensial tersimpan untuk tujuan yang sama. Kredensial baru hanya dikirim ke engine lokal.')}</p>
    {data&&<><p role="status">{data.test?.message}</p><p>{t('Antrean upload')}: {t('Menunggu')} {(data.counts?.PENDING||0)+(data.counts?.RETRY||0)} · {t('Terkirim')} {data.counts?.COMPLETED||0} · {t('Gagal')} {data.counts?.FAILED||0}</p>{['rclone','s3'].includes(kind)&&!data.rclone_available&&<p role="alert">{t('Transport cloud belum tersedia di engine.')}</p>}<Button disabled={busy} onClick={()=>action('recordings/destination/retry')}>Coba ulang upload gagal</Button></>}
  </div>;
}

function BackupOptions({resource}) {
  const {data,busy,action}=resource;const [draft,setDraft]=useState(null),[restore,setRestore]=useState(null);const {t,language}=useLanguage();
  useEffect(()=>{if(data)setDraft({...data.policy});},[data]);
  const time=value=>value?new Date(value*1000).toLocaleString(language==='en'?'en-GB':'id-ID'):t('Belum tersedia');
  return <div className="settings-tools-content"><Button disabled={!data||busy||data?.busy} onClick={()=>action('maintenance/backup')}>Buat backup sekarang</Button>
    <form onSubmit={event=>{event.preventDefault();action('maintenance/policy',{enabled:draft.enabled,keep_days:Number(draft.keep_days)});}}><fieldset disabled={!draft||busy}><label className="check-control"><input type="checkbox" checked={Boolean(draft?.enabled)} onChange={event=>setDraft(previous=>({...previous,enabled:event.target.checked}))}/>{t('Backup otomatis setiap 24 jam')}</label><Field label="Retensi backup (hari)"><input type="number" min="1" max="365" required value={draft?.keep_days??''} onChange={event=>setDraft(previous=>({...previous,keep_days:event.target.value}))}/></Field><Button type="submit">Simpan jadwal backup</Button></fieldset></form>
    {data&&<><p>{t('Backup terakhir')}: {time(data.state?.last_success)}</p>{data.state?.last_error&&<p role="alert" className="error-text">{data.state.last_error}</p>}{data.backups?.length?<ul className="settings-backups">{data.backups.map(backup=><li key={backup.id}><span>{time(backup.created_at)} · {(backup.bytes/1048576).toFixed(1)} MB</span><div className="inline-controls"><Button disabled={busy} onClick={()=>action(`maintenance/backups/${encodeURIComponent(backup.id)}/verify`)}>Verifikasi backup</Button><Button onClick={()=>setRestore(backup)}>Panduan pemulihan</Button></div></li>)}</ul>:<Empty title="Belum ada backup"/>}</>}
    {restore&&<Modal title="Panduan pemulihan" onClose={()=>setRestore(null)}><p>{t('Hentikan aplikasi dan service sebelum memulihkan database. Jalankan perintah ini dari folder instalasi, lalu mulai ulang aplikasi setelah hasil terverifikasi.')}</p><pre className="settings-restore-command">{`${data.restore_command} --backup-id '${restore.id}'`}</pre></Modal>}
  </div>;
}

function RuntimeOptions({data,engine}) {
  const {t}=useLanguage();const snapshot=data||engine?.snapshot;
  const value=entry=>entry??t('Belum tersedia');
  return <dl className="engine-facts settings-tools-content">{[['Layanan monitoring',data?t('Terhubung'):t('Belum tersedia')],['Model detektor',snapshot?.detector?.model],['Perangkat inferensi',snapshot?.detector?.runtime?.device_name||snapshot?.detector?.runtime?.provider],['Zona waktu',snapshot?.timezone],['Versi skema database',snapshot?.schema_version],['Kesalahan terakhir',snapshot?.live?.error||engine?.connectionError||(data?t('Tidak ada error'):null)]].map(([label,entry])=><div key={label} className="settings-runtime-row"><dt>{t(label)}</dt><dd>{value(entry)}</dd></div>)}</dl>;
}
