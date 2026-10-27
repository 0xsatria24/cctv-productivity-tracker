import { useEffect, useRef, useState } from 'react';
import { ChartNoAxesCombined, Download, LayoutDashboard, Play, RefreshCw, ScanLine, Settings, Square, Video } from 'lucide-react';
import { Button, DataTable, Empty, Field, Modal, Panel, Status } from './components';
import { Timeline as BaseTimeline } from './charts';
import { displayTime, inputUtc, parseUtc, ratio, seconds, totalMetrics, useEngine } from './engine-client';
import { useWebcamPreview } from './webcam';
import { LiveEnginePanel, useLiveEngine } from './live-engine';
import { CameraWorkspace } from './camera-wall';
import './engine.css';
import { OperationalOverview, OperationalReports, ReportFilters, PeriodMetrics, DurationBreakdown } from './operations';
import { reasonText, monitoringText } from './operations-domain.mjs';
import DailyAnalytics from './DailyAnalytics';
import { readRoute, routeHash } from './navigation.mjs';
import { RecordingDestination } from './recording-destination';
import { RecordingSettings, recordingLabel, useRecordings } from './recording-settings';
import { MaintenancePanel } from './maintenance-panel';
import { ManagedCameraControls } from './managed-camera';
import { SettingsTools } from './settings-tools';
import { VideoReplayWorkspace } from './video-replay';

const sections=[['overview','Ringkasan',LayoutDashboard],['live','Pemantauan Live',Video],['workspaces','Workstation',ScanLine],['analytics','Laporan',ChartNoAxesCombined],['settings','Pengaturan',Settings]];
const pageFromHash=()=>readRoute(window.location.hash).page;
const reportColumns=[{key:'workspace',label:'Workstation'},{key:'occupied_us',label:'Terisi',numeric:true,render:r=>seconds(r.occupied_us)},{key:'empty_us',label:'Kosong',numeric:true,render:r=>seconds(r.empty_us)},{key:'unknown_us',label:'Tidak diketahui',numeric:true,render:r=>seconds(r.unknown_us)},{key:'utilization',label:'Keterisian',numeric:true,render:r=>ratio(r.utilization)},{key:'coverage',label:'Kelengkapan',numeric:true,render:r=>ratio(r.coverage)}];
const asRows=report=>(report?.workstations||[]).map(r=>({...r,id:r.workspace_id}));
function Timeline(props){return <BaseTimeline {...props} gapDescription="Tidak diketahui berarti bukti kamera belum mencukupi."/>;}
const reportDescriptions={overview:'Kondisi kamera saat ini dan hal yang perlu ditindaklanjuti.',live:'Pantau beberapa kamera dan periksa observasi zona.',workspaces:'Zona tersimpan, data karyawan, dan assignment administratif.',analytics:'Durasi, rekap harian, timeline dan ekspor dalam satu periode.',settings:'Koneksi aplikasi lokal dan kemampuan runtime pilot.'};

function EventTable({engine,onInspect}){return <DataTable testId="engine-events" rows={(engine.snapshot?.events||[]).map(row=>({...row,id:row.event_id}))} columns={[{key:'seq',label:'No. catatan',numeric:true},{key:'event_type',label:'Event'},{key:'observed_utc_us',label:'Waktu observasi',render:r=>displayTime(r.observed_utc_us,engine.snapshot?.timezone)},{key:'frame_seq',label:'Frame',numeric:true},{key:'zone_states',label:'Observasi zona',render:r=>Object.entries(r.zone_states).map(([id,state])=>`${id}: ${state}`).join(' · ')},{key:'details',label:'Detail',sortable:false,render:r=><Button onClick={()=>onInspect({type:'event',value:r})}>Periksa</Button>}]}/>;}

function Live({engine,setModal}) {
  const [diagnosticsOpen,setDiagnosticsOpen]=useState(false);
  const running=['QUEUED','RUNNING'].includes(engine.snapshot?.controller?.status);
  useEffect(()=>{if(running)setDiagnosticsOpen(true);},[running]);
  return <details className="operations-diagnostics" open={diagnosticsOpen} onToggle={e=>setDiagnosticsOpen(e.currentTarget.open)}><summary>Simulasi dan rincian observasi</summary>
    <Panel title="Kontrol replay" caption="Input deteksi sintetis; ByteTrack, aturan zona, dan SQLite dijalankan oleh Python">
      <div className="engine-replay-controls"><span>Status simulasi: <strong>{engine.snapshot?.controller?.status||'IDLE'}</strong></span><span>{engine.snapshot?.controller?.processed||0} / {engine.snapshot?.controller?.total||0} frame</span>
        <Button icon={Play} variant="primary" disabled={running||engine.mutating||!!engine.connectionError} onClick={()=>engine.action('replay').then(()=>engine.toast('Replay dimulai di engine.')).catch(()=>{})}>Mulai replay</Button>
        <Button icon={Square} disabled={!running||engine.mutating||!!engine.connectionError} onClick={()=>engine.action('replay/stop').catch(()=>{})}>Hentikan replay</Button>
      </div>
      {engine.snapshot?.controller?.error && <p className="error-text" role="alert">{engine.snapshot.controller.error}</p>}
    </Panel>
    <div className="engine-observations section-gap">{engine.snapshot?.workspaces.map(w => <Panel key={w.id} title={w.name} caption="Observasi terakhir yang tersimpan"><div className="engine-state"><Status value={w.last_observation?.state||'UNKNOWN'}/><span>Jumlah teramati: {w.last_observation?.observed_count??'N/A'}</span><span>{displayTime(w.last_observation?.evidence_until_utc_us,engine.snapshot.timezone)}</span><span className="caption">{engine.dataset==='live'?'Checkpoint kamera live; periksa waktu bukti terakhir.':'Snapshot replay simulasi.'}</span></div></Panel>)}</div>
    <Panel className="section-gap" title="Catatan observasi" caption="Perubahan yang sudah tersimpan"><EventTable engine={engine} onInspect={setModal}/></Panel>
  </details>;
}

function Analytics({engine,setModal,tab,setTab}) {
  const selected=engine.snapshot?.workspaces.filter(w=>engine.filters.workspace==='ALL'||w.id===engine.filters.workspace)||[];
  function openTimeline(workspace) {
    engine.setFilters(previous=>({...previous,workspace}));
    setTab('timeline');
  }
  return <>
    <PeriodMetrics report={engine.report} loading={engine.reportLoading}/>
    <div className="tab-bar">
      <button aria-pressed={tab==='summary'} onClick={()=>setTab('summary')}>Ringkasan</button>
      <button aria-pressed={tab==='daily'} onClick={()=>setTab('daily')}>Rekap Harian</button>
      <button aria-pressed={tab==='timeline'} onClick={()=>setTab('timeline')}>Timeline</button>
      <button aria-pressed={tab==='export'} onClick={()=>setTab('export')}>Ekspor</button>
    </div>
    {tab==='export'?<OperationalReports engine={engine} showMetrics={false} onTimeline={openTimeline}/>:tab==='daily'?<DailyAnalytics engine={engine} onTimeline={row=>{engine.setFilters({workspace:row.workspace_id,start:row.start_utc_us,end:row.end_utc_us});setTab('timeline');}}/>:tab==='summary'?<>
      <Panel title="Durasi dan kelengkapan observasi" caption="Rasio dihitung dari total durasi"><DurationBreakdown report={engine.report} onSelect={openTimeline}/></Panel>
      <Panel className="section-gap" title="Rincian workstation"><DataTable columns={reportColumns} rows={asRows(engine.report)} testId="engine-analytics" empty={<Empty title="Belum ada observasi pada periode ini" description={engine.dataset==='live'?'Pilih periode lain atau mulai monitoring dari Pemantauan Live.':'Pilih sesi simulasi yang memiliki observasi atau jalankan replay.'}/>}/></Panel>
    </>:engine.report?.intervals.length?<>
      <Panel title="Timeline observasi" caption="Waktu tanpa bukti kamera ditampilkan sebagai tidak diketahui"><Timeline timezone={engine.snapshot.timezone} records={engine.report.intervals} workspaces={selected} start={engine.report.start_utc_us/1000} end={engine.report.end_utc_us/1000} onSelect={value=>setModal({type:'interval',value})}/></Panel>
      <Panel className="section-gap" title="Detail interval"><DataTable testId="engine-intervals" rows={engine.report.intervals} columns={[{key:'workspaceId',label:'Workstation',render:r=>selected.find(w=>w.id===r.workspaceId)?.name||r.workspaceId},{key:'start',label:'Mulai',render:r=>displayTime(r.start*1000,engine.snapshot.timezone)},{key:'end',label:'Akhir',render:r=>displayTime(r.end*1000,engine.snapshot.timezone)},{key:'state',label:'Observasi',render:r=><Status value={r.state}/>},{key:'reason',label:'Alasan',render:r=>reasonText(r.reason)},{key:'detail',label:'Detail',sortable:false,render:r=><Button onClick={()=>setModal({type:'interval',value:r})}>Periksa</Button>}]}/></Panel>
    </>:<Empty title="Belum ada interval untuk rentang ini" description={engine.dataset==='live'?'Pilih periode lain atau mulai monitoring dari Pemantauan Live.':'Pilih sesi simulasi yang memiliki observasi atau jalankan replay.'}/>}
  </>;
}

function Workstations({engine,setModal,onSetup}) {
  const hasZones=!!engine.snapshot?.workspaces.length,hasEmployees=!!engine.snapshot?.employees.length;
  return <>
    <section className="report-source" aria-label="Sumber konfigurasi workstation"><Field label="Sumber konfigurasi"><select value={engine.dataset} onChange={e=>engine.setDataset(e.target.value)}><option value="live">Kamera live</option><option value="replay">Replay simulasi</option></select></Field><p>{engine.dataset==='replay'?'Zona dan assignment berikut milik replay simulasi.':'Zona dan assignment untuk monitoring kamera live.'}</p></section>
    <Panel title="Zona workstation" caption="Konfigurasi yang tersimpan di SQLite"><DataTable testId="engine-workspaces" rows={engine.snapshot?.workspaces||[]} columns={[{key:'name',label:'Workstation'},{key:'kind',label:'Jenis'},{key:'revision',label:'Revisi',numeric:true},{key:'exclusive_group',label:'Kelompok eksklusif'},{key:'polygon',label:'Zona',sortable:false,render:r=><Button onClick={()=>setModal({type:'zone',value:r})}>Lihat polygon</Button>}]} empty={<Empty title="Belum ada zona tersimpan" description="Atur batas workstation dari kamera yang akan dipantau." action={<Button onClick={onSetup}>Atur zona kamera</Button>}/>}/></Panel>
    <Panel className="section-gap" title="Data karyawan" caption="Registrasi administratif; tidak memakai biometrik" action={<Button disabled={!!engine.connectionError} onClick={()=>setModal({type:'employee'})}>Tambah karyawan</Button>}><DataTable testId="engine-employees" rows={engine.snapshot?.employees||[]} columns={[{key:'display_name',label:'Nama'},{key:'active',label:'Status',render:r=>r.active?'Aktif':'Nonaktif'},{key:'id',label:'ID'}]} empty={<Empty title="Belum ada karyawan terdaftar" description="Tambahkan karyawan untuk membuat assignment administratif. Identitas orang teramati tetap anonim."/>}/></Panel>
    <Panel className="section-gap" title="Assignment workstation" caption="Assignment tidak membuktikan identitas orang teramati" action={<Button disabled={!hasEmployees||!hasZones||!!engine.connectionError} onClick={()=>setModal({type:'assignment'})}>Tambah assignment</Button>}><DataTable testId="engine-assignments" rows={engine.snapshot?.assignments||[]} columns={[{key:'workspace_name',label:'Workstation'},{key:'display_name',label:'Karyawan'},{key:'effective_from_utc_us',label:'Mulai',render:r=>displayTime(r.effective_from_utc_us,engine.snapshot.timezone)},{key:'effective_to_utc_us',label:'Sampai',render:r=>displayTime(r.effective_to_utc_us,engine.snapshot.timezone)},{key:'source',label:'Sumber'}]} empty={<Empty title="Belum ada assignment workstation" description={!hasZones?'Simpan zona workstation dan tambahkan karyawan sebelum membuat assignment.':!hasEmployees?'Tambahkan karyawan sebelum membuat assignment ke workstation.':'Gunakan Tambah assignment untuk mengatur penempatan administratif karyawan.'}/>}/></Panel>
  </>;
}

function ReportSource({engine}) {
  const running=['QUEUED','RUNNING'].includes(engine.snapshot?.controller?.status);
  return <section className="report-source" aria-label="Sumber laporan"><Field label="Sumber data laporan"><select value={engine.dataset} onChange={e=>engine.setDataset(e.target.value)}><option value="live">Kamera live</option><option value="replay">Replay simulasi</option></select></Field>{engine.dataset==='live'&&<CameraReportSource engine={engine}/>}<p>{engine.dataset==='live'?'Data kamera live. Kehadiran di zona belum membuktikan hasil kerja.':'Data replay sintetis untuk menguji alur; bukan observasi kamera nyata.'}</p>{engine.dataset==='replay'&&<Button icon={Play} disabled={running||engine.mutating||!!engine.connectionError} onClick={()=>engine.action('replay').catch(()=>{})}>{running?'Replay berjalan':'Jalankan replay'}</Button>}</section>;
}

function CameraReportSource({engine}) {
  return <Field label="Kamera laporan"><select value={engine.cameraId} onChange={e=>engine.setCameraId(e.target.value)}><option value="">Webcam / sesi RTSP utama</option>{engine.snapshot?.camera_catalog?.map(c=><option key={c.id} value={c.id}>{c.name}{c.archived?' (arsip)':''}</option>)}</select></Field>;
}

function EngineSettings({engine}) {
  return <><RecordingSettings engine={engine}/><RecordingDestination engine={engine}/><MaintenancePanel engine={engine}/>
    <Panel title="Status aplikasi" caption="Koneksi, penyimpanan dan waktu tampilan"><dl className="engine-facts">
      <dt>Layanan monitoring</dt><dd>{engine.connectionError?'Tidak terhubung':'Terhubung'}</dd><dt>Zona waktu lokasi</dt><dd>{engine.snapshot?.timezone}</dd>
      <dt>Data observasi</dt><dd>Tersimpan secara lokal</dd><dt>Rekaman video</dt><dd>{recordingLabel(engine.recordings)}</dd><dt>Audio</dt><dd>Tidak direkam</dd>
      <dt>Identitas orang</dt><dd>Anonim; pengenalan wajah tidak digunakan</dd><dt>Terakhir diperbarui</dt><dd>{engine.receivedAt?new Intl.DateTimeFormat('id-ID',{timeZone:engine.snapshot.timezone,timeStyle:'medium'}).format(engine.receivedAt):'Belum tersedia'}</dd>
    </dl><div className="engine-replay-controls"><Button icon={RefreshCw} onClick={engine.reload}>Periksa koneksi</Button><Button icon={Download} disabled={engine.reportLoading||!engine.report?.workstations.length||!!engine.connectionError} onClick={engine.exportCsv}>Unduh laporan saat ini</Button></div></Panel>
    <details className="operations-diagnostics"><summary>Diagnostik teknis</summary><Panel title="Runtime lokal" caption="Informasi dari layanan analisis"><dl className="engine-facts">
      <dt>Detektor aktif</dt><dd>{engine.snapshot?.detector?.model||'Belum tersedia'}</dd><dt>Perangkat inferensi</dt><dd>{engine.snapshot?.detector?.runtime?.device_name||engine.snapshot?.detector?.runtime?.provider||'Belum tersedia'}</dd>
      <dt>Presisi</dt><dd>{engine.snapshot?.detector?.runtime?.precision||'Belum tersedia'}</dd><dt>Model siap</dt><dd>{engine.snapshot?.detector?.ready?'Siap':'Belum dikonfirmasi'}</dd>
      <dt>Skema database</dt><dd>{engine.snapshot?.schema_version??'Belum tersedia'}</dd><dt>Catatan tersimpan</dt><dd>{engine.snapshot?.committed_event_seq??0}</dd><dt>API</dt><dd>Same-origin, loopback</dd><dt>Kalender kerja</dt><dd>Belum diterapkan; Laporan menyediakan filter tanggal dan jam shift</dd>
    </dl></Panel></details></>;
}

function EngineModal({modal,onClose,engine}){
  const [name,setName]=useState(''),[assignment,setAssignment]=useState({employee_id:engine.snapshot?.employees[0]?.id||'',workspace_id:engine.snapshot?.workspaces[0]?.id||'',start:inputUtc(engine.report?.start_utc_us),end:inputUtc((engine.report?.start_utc_us||0)+8*3600*1e6)}),[error,setError]=useState('');
  async function save(event){event.preventDefault();try{if(modal.type==='employee'){await engine.action('employees',{display_name:name.trim()});engine.toast('Karyawan disimpan ke database.');}else{const start=parseUtc(assignment.start),end=parseUtc(assignment.end);if(start==null||end==null||end<=start){setError('Akhir assignment harus setelah mulai.');return;}await engine.action('assignments',{employee_id:assignment.employee_id,workspace_id:assignment.workspace_id,start_utc_us:start,end_utc_us:end});engine.toast('Assignment tersimpan. Identitas orang teramati tetap anonim.');}onClose();}catch(failure){setError(failure.message);}}
  if(modal.type==='employee'||modal.type==='assignment')return <Modal title={modal.type==='employee'?'Tambah karyawan':'Tambah assignment workstation'} description="Data administratif terpisah dari hasil observasi kamera." onClose={onClose}><form onSubmit={save} className="engine-form">{modal.type==='employee'?<Field label="Nama karyawan"><input required maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></Field>:<><Field label="Karyawan"><select value={assignment.employee_id} onChange={e=>setAssignment(p=>({...p,employee_id:e.target.value}))}>{engine.snapshot.employees.map(e=><option key={e.id} value={e.id}>{e.display_name}</option>)}</select></Field><Field label="Workstation assignment"><select value={assignment.workspace_id} onChange={e=>setAssignment(p=>({...p,workspace_id:e.target.value}))}>{engine.snapshot.workspaces.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></Field><Field label="Mulai assignment (UTC)"><input required type="datetime-local" step="1" value={assignment.start} onChange={e=>setAssignment(p=>({...p,start:e.target.value}))}/></Field><Field label="Sampai assignment (UTC)"><input required type="datetime-local" step="1" value={assignment.end} onChange={e=>setAssignment(p=>({...p,end:e.target.value}))}/></Field></>}{error&&<p className="error-text" role="alert">{error}</p>}<div className="modal-actions"><Button type="button" onClick={onClose}>Batal</Button><Button type="submit" variant="primary" disabled={engine.mutating||(modal.type==='employee'&&!name.trim())}>Simpan ke engine</Button></div></form></Modal>;
  return <Modal title={modal.type==='zone'?modal.value.name:modal.type==='interval'?'Detail interval':'Detail checkpoint'} onClose={onClose}>{modal.type==='zone'?<><svg className="engine-zone-map" viewBox="0 0 400 240" role="img" aria-label="Polygon normalized dari database"><rect x="0" y="0" width="400" height="240" className="zone-map-background"/><polygon points={modal.value.polygon.map(([x,y])=>`${x*400},${y*240}`).join(' ')} className="zone-overlay"/></svg><p>Koordinat zona tersimpan, bukan frame CCTV. Revisi {modal.value.revision}.</p></>:modal.type==='interval'?<dl className="engine-facts"><dt>Observasi</dt><dd><Status value={modal.value.state}/></dd><dt>Durasi</dt><dd>{seconds((modal.value.end-modal.value.start)*1000)}</dd><dt>Jumlah teramati</dt><dd>{modal.value.count??'N/A'}</dd><dt>Alasan</dt><dd>{modal.value.reason||'Observasi valid'}</dd><dt>Revisi</dt><dd>{modal.value.revision??'Gap tanpa konfigurasi observasi'}</dd><dt>Identitas</dt><dd>Anonim</dd></dl>:<dl className="engine-facts"><dt>Checkpoint</dt><dd>{modal.value.seq}</dd><dt>Run</dt><dd className="break-word">{modal.value.engine_run_id}</dd><dt>Frame</dt><dd>{modal.value.frame_seq}</dd><dt>Observasi</dt><dd>{Object.entries(modal.value.zone_states).map(([name,state])=>`${name}: ${state}`).join(' · ')}</dd></dl>}</Modal>;
}

export default function EngineApp(){
  const baseEngine=useEngine(),recordings=useRecordings(),engine={...baseEngine,recordings},[page,setPage]=useState(pageFromHash),[modal,setModal]=useState(null),[cameraHealth,setCameraHealth]=useState([]),[setupOpen,setSetupOpen]=useState(true),[analyticsTab,setAnalyticsTab]=useState(()=>readRoute(window.location.hash).tab);
  const [selectedCamera,setSelectedCamera]=useState('webcam'),[addRequest,setAddRequest]=useState(0);
  const [areaRequest,setAreaRequest]=useState(0);
  const synchronizedSession=useRef(null);
  const webcam=useWebcamPreview();
  const live=useLiveEngine(webcam,engine);
  const managedCamera=cameraHealth.find(c=>c.id===selectedCamera&&c.managed);
  useEffect(()=>{const changed=()=>{const route=readRoute(window.location.hash);setPage(route.page);if(route.page==='analytics')setAnalyticsTab(route.tab);};changed();window.addEventListener('hashchange',changed);return()=>window.removeEventListener('hashchange',changed);},[]);
  useEffect(()=>{
    const active=cameraHealth.find(c=>live.state?.source==='WEBCAM_LIVE'?c.id==='webcam':c.id!=='engine-rtsp'&&c.camera_key===live.state?.camera_key);
    if(live.active&&active&&synchronizedSession.current!==live.state?.session_id){setSelectedCamera(active.id);synchronizedSession.current=live.state.session_id;}
  },[cameraHealth,live.active,live.state?.session_id]);
  function navigate(value){const route=readRoute(routeHash(value));setPage(route.page);if(value==='reports')setAnalyticsTab('export');window.location.hash=routeHash(route.page,value==='reports'?'export':analyticsTab);}
  function reportTab(value){setAnalyticsTab(value);window.location.hash=routeHash('analytics',value);}
  useEffect(()=>{if(live.active&&!live.state?.preview_only)setSetupOpen(false);},[live.state?.session_id,live.active]);
  const showFilters=page==='analytics';
  function openTimeline(id){engine.setFilters(p=>({...p,workspace:id}));setPage('analytics');reportTab('timeline');}
  function openSetup(){setSetupOpen(true);navigate('live');requestAnimationFrame(()=>document.querySelector('.camera-session-controls')?.scrollIntoView({block:'start',behavior:'smooth'}));}
  return <div className={`app-shell engine-app ${page==='live'?'camera-monitoring-page':''}`}>
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">CW</span><div>CCTV Workspace<small>MONITORING LOKAL</small></div></div>
      <span className="nav-caption">RUANG KERJA</span>
      <nav aria-label="Navigasi utama">{sections.map(([id,label,Icon]) => <button key={id} className={`nav-item ${page===id?'active':''}`} aria-current={page===id?'page':undefined} onClick={()=>navigate(id)}><Icon size={17} aria-hidden="true"/>{label}</button>)}</nav>
      <div className="sidebar-note"><p>Observasi workstation.<br/>Identitas orang tetap anonim.</p><span>{recordingLabel(engine.recordings)}</span></div>
    </aside>
    <div className="main-shell">
      <header className="page-header">
        <div><span className="eyebrow">CCTV WORKSPACE</span><h1>{sections.find(s=>s[0]===page)[1]}</h1><p>{reportDescriptions[page]}</p></div>
        <div className="header-actions">{page==='overview'&&<Button onClick={openSetup}>Setup monitoring</Button>}</div>
      </header>
      {engine.connectionError && <div className="system-warning" role="alert">Layanan monitoring tidak terhubung: {engine.connectionError} Data terakhir tetap tersimpan. Periksa koneksi aplikasi lalu perbarui status. Preview webcam dapat tetap digunakan.</div>}
      {live.active && <div className="operations-monitoring-ribbon" role="status"><span>{monitoringText(live.state,live.error||(Date.now()-live.receivedAt>4000?'stale':''))} · {live.state.source==='WEBCAM_LIVE'?'Webcam lokal':'Kamera RTSP'}</span><Button onClick={()=>navigate('live')}>Buka kamera aktif</Button></div>}
      <main id="main-content"><VideoReplayWorkspace visible={page==='live'} engineAvailable={Boolean(engine.snapshot&&!engine.connectionError)}/>
        <details className={`camera-session-controls live-engine-section ${page==='live'?'':'webcam-hidden'}`} open={setupOpen} onToggle={e=>setSetupOpen(e.currentTarget.open)}><summary>Setup dan monitoring <span>{managedCamera?managedCamera.name:monitoringText(live.state,live.error)}</span></summary>{managedCamera?<ManagedCameraControls key={managedCamera.id} areaRequest={areaRequest} camera={managedCamera} engine={engine}/>:<LiveEnginePanel areaRequest={areaRequest} cameras={cameraHealth} selected={selectedCamera} onSelect={setSelectedCamera} onAdd={()=>setAddRequest(v=>v+1)} onReports={()=>{engine.setDataset('live');engine.setCameraId('');navigate('reports');}} hidePreview live={live} webcam={webcam} engine={engine}/>}</details>
        <CameraWorkspace selected={selectedCamera} onSelect={setSelectedCamera} onConfigure={(camera,editArea=false)=>{setSelectedCamera(camera.id);openSetup();if(editArea)setAreaRequest(v=>v+1);}} addRequest={addRequest} onHealthChange={setCameraHealth} page={page} engine={engine} live={live} webcam={{...webcam,liveSession:live.webcamSession,engineStarting:live.webcamStarting,inferencePaused:live.active&&live.state?.source==='RTSP_LIVE',analysisMode:live.state?.analysis_mode,calibration:live.state?.calibrations?.WEBCAM_LIVE?.camera_key===live.cameraKey?live.state.calibrations.WEBCAM_LIVE:null,
          workstationFps:live.state?.workstation_policy?.sample_fps,workstations:live.state?.source==='WEBCAM_LIVE'?live.state?.workstations||[]:[],aruco:live.state?.source==='WEBCAM_LIVE'?live.state?.latest?.aruco:null,onCalibrate:()=>{setSelectedCamera('webcam');openSetup();setAreaRequest(v=>v+1);}}}/>
        {engine.loading ? <Empty title="Menghubungkan layanan monitoring" description="Menunggu status kamera dan catatan tersimpan. Model dapat memerlukan waktu saat aplikasi baru dimulai."/>
          : !engine.snapshot ? <Empty title="Engine belum dapat dibaca" description="Refresh koneksi atau muat ulang halaman setelah engine berjalan." action={<Button onClick={engine.reload}>Coba lagi</Button>}/>
          : <>
            {showFilters && <><ReportSource engine={engine}/><ReportFilters engine={engine}/></>}
            {showFilters && engine.reportError ? <Empty title="Laporan gagal dibaca" description={engine.reportError} action={<Button onClick={engine.reload}>Muat ulang laporan</Button>}/>
              : <>
                {page==='overview' && <OperationalOverview engine={engine} live={live} cameras={cameraHealth} navigate={navigate} onSetup={openSetup} onTimeline={openTimeline} setModal={setModal}/>}
                {page==='workspaces' && <Workstations engine={engine} setModal={setModal} onSetup={openSetup}/>}
                {page==='analytics' && <Analytics engine={engine} setModal={setModal} tab={analyticsTab} setTab={reportTab}/>}
                {page==='settings' && <><EngineSettings engine={engine}/><SettingsTools engine={engine}/><details className="operations-diagnostics"><summary>Simulasi dan diagnostik observasi</summary><ReportSource engine={engine}/><Live engine={engine} setModal={setModal}/></details></>}
              </>}
          </>}
      </main>
      <footer className="status-bar"><span data-testid="engine-connection">Layanan monitoring · {engine.connectionError?'koneksi terputus':engine.snapshot?'terhubung':'menghubungkan'}</span><span>Identitas: anonim</span><span>{recordingLabel(engine.recordings)}</span><span>{engine.snapshot?.timezone||'Zona waktu lokasi'}</span></footer>
    </div>
    {modal && <EngineModal key={modal.type} modal={modal} onClose={()=>setModal(null)} engine={engine}/>}
    {engine.notice && <div className="notification" role="status">{engine.notice}</div>}
  </div>;
}
