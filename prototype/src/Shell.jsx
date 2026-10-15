import { useEffect, useState } from 'react';
import { ChartNoAxesCombined, FileText, FlaskConical, LayoutDashboard, ListChecks, Pause, Play, ScanLine, Settings as SettingsIcon, StepForward, Video } from 'lucide-react';
import { PrototypeProvider, usePrototype } from './store';
import { Button, Status } from './components';
import { clock, dateLabel } from './domain';
import Overview from './Overview';
import Live from './Live';
import Workspaces from './Workspaces';
import Analytics, { Reports } from './Analytics';
import { Cameras, Settings } from './Management';
import Dialogs from './Dialogs';
import EngineApp from './EngineApp';

const sections = [['overview','Ringkasan',LayoutDashboard],['live','Pemantauan Live',Video],['workspaces','Workstation',ScanLine],['analytics','Analitik',ChartNoAxesCombined],['reports','Laporan',FileText],['settings','Pengaturan',SettingsIcon]];
const descriptions = {overview:'Kondisi workstation, coverage, dan kesehatan observasi.',live:'Frame simulasi, status transport, dan observasi zona.',workspaces:'Konfigurasi zona dan polygon pada frame acuan.',analytics:'Durasi teramati, timeline, dan kelengkapan data.',reports:'Laporan periodik dari interval simulasi dan ekspor CSV.',settings:'Kalender, retention, backup, dan dataset lokal prototipe.'};
const hashPage = () => {const key=window.location.hash.replace(/^#\/?/,'');return key==='cameras'?'live':sections.some(s=>s[0]===key)?key:'overview';};

function Shell() {
  const {state,playing,setPlaying,advance,setDialog,jobs,notice,dirtyPage,setDirtyPage,dialog}=usePrototype();
  const [route,setRoute]=useState({page:hashPage()}),[cameraControlsOpen,setCameraControlsOpen]=useState(false);
  function navigate(page,context={}) {
    if(page==='cameras')page='live';
    if(dirtyPage&&!window.confirm('Buang draft workstation yang belum disimpan?'))return;
    setDirtyPage(false);setRoute({page,...context});window.location.hash=`/${page}`;
  }
  useEffect(()=>{const change=()=>{if(/^#\/?cameras$/.test(window.location.hash))window.history.replaceState(window.history.state,'',`${window.location.pathname}${window.location.search}#/live`);setRoute(previous=>previous.page===hashPage()?previous:{page:hashPage()});};change();window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change);},[]);
  useEffect(()=>{const search=event=>{if(event.ctrlKey&&event.key.toLowerCase()==='f'){const input=document.querySelector('main input[type=search]');if(input){event.preventDefault();input.focus();}}};window.addEventListener('keydown',search);return()=>window.removeEventListener('keydown',search);},[]);
  const {page}=route;
  const activeJobs=jobs.filter(j=>['QUEUED','RUNNING'].includes(j.status)).length;
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">CW</span><div>CCTV Workspace<small>OPERATIONS CONSOLE</small></div></div><span className="nav-caption">WORKSPACE CONTOH</span>
      <nav aria-label="Navigasi utama">{sections.map(([id,label,Icon])=><button key={id} className={`nav-item ${page===id?'active':''}`} aria-current={page===id?'page':undefined} onClick={()=>navigate(id)}><Icon size={17} aria-hidden="true"/>{label}</button>)}</nav>
      <div className="sidebar-note"><div className="local-access">Akses lokal prototipe</div><p>Presence dan occupancy.<br/>Track anonim.</p><button onClick={()=>setDialog({type:'definitions'})}>Definisi metrik</button></div>
    </aside>
    <div className="main-shell"><div className="prototype-banner"><strong>DATA SIMULASI</strong><span>Prototipe interaktif. Tidak ada CCTV, employee, atau backend nyata yang terhubung.</span></div>
      <header className="page-header"><div><span className="eyebrow">{state.settings.site}</span><h1>{sections.find(s=>s[0]===page)[1]}</h1><p>{descriptions[page]}</p></div><div className="header-actions"><Button icon={FlaskConical} onClick={()=>setDialog({type:'scenario'})}>Skenario</Button><Button icon={ListChecks} onClick={()=>setDialog({type:'jobs'})}>Pekerjaan{activeJobs?` (${activeJobs})`:''}</Button></div></header>
      <div className="simulation-toolbar"><div className="simulation-clock"><span className="caption">Waktu skenario</span><strong className="mono">{dateLabel(state.clock)} · {clock(state.clock,state.settings.timezone,true)}</strong><span className="caption">{state.settings.timezone}</span></div><div className="simulation-actions"><Button icon={playing?Pause:Play} onClick={()=>setPlaying(value=>!value)}>{playing?'Jeda simulasi':'Mulai simulasi'}</Button><Button icon={StepForward} onClick={advance}>+1 menit</Button><span className="caption">1 menit skenario / 4 detik saat berjalan</span></div></div>
      {state.persistence!=='HEALTHY'&&<div className="system-warning" role="status">Persistence simulasi terganggu. Preview tidak membuktikan durabilitas; zona menjadi unknown.</div>}
      <main id="main-content">{page==='overview'&&<Overview navigate={navigate}/>}{page==='live'&&<><Live navigate={navigate} cameraId={route.cameraId}/><details className="operations-diagnostics" open={cameraControlsOpen} onToggle={e=>setCameraControlsOpen(e.currentTarget.open)}><summary>Konfigurasi kamera simulasi</summary>{cameraControlsOpen&&<Cameras navigate={navigate} showAdd={false}/>}</details></>}{page==='workspaces'&&<Workspaces navigate={navigate} workspaceId={route.workspaceId}/>}{page==='analytics'&&<Analytics workspaceId={route.workspaceId} tab={route.tab}/>} {page==='reports'&&<Reports/>}{page==='settings'&&<Settings/>}</main>
      <footer className="status-bar"><Status value={state.persistence==='HEALTHY'?'ONLINE':'DEGRADED'} label="Engine simulasi lokal"/><span>Video tidak disimpan</span><span>Identitas: anonim</span><span>Production tetap Python + PySide6</span></footer>
    </div>{notice&&<div className="notification" role="status">{notice}</div>}<Dialogs key={dialog?.type||'none'} navigate={navigate}/>
  </div>;
}
export default function App() { return window.__CCTV_ENGINE__ ? <EngineApp/> : <PrototypeProvider><Shell/></PrototypeProvider>; }
