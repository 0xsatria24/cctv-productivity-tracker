import { useEffect, useState } from 'react';
import { ChartNoAxesCombined, FlaskConical, LayoutDashboard, ListChecks, Pause, Play, ScanLine, Settings as SettingsIcon, StepForward, Video } from 'lucide-react';
import { PrototypeProvider, usePrototype } from './store';
import { Button, Status } from './components';
import { clock, dateLabel } from './domain';
import Overview from './Overview';
import Live from './Live';
import Workspaces from './Workspaces';
import Analytics from './Analytics';
import { Cameras, Settings } from './Management';
import Dialogs from './Dialogs';
import EngineApp from './EngineApp';
import { readRoute, routeHash } from './navigation.mjs';

const sections = [['overview','Ringkasan',LayoutDashboard],['live','Pemantauan Live',Video],['workspaces','Workstation',ScanLine],['analytics','Laporan',ChartNoAxesCombined],['settings','Pengaturan',SettingsIcon]];
const descriptions = {overview:'Kondisi workstation, coverage, dan kesehatan observasi.',live:'Frame simulasi, status transport, dan observasi zona.',workspaces:'Konfigurasi zona dan polygon pada frame acuan.',analytics:'Durasi teramati, timeline, dan kelengkapan data.',reports:'Laporan periodik dari interval simulasi dan ekspor CSV.',settings:'Kalender, retention, backup, dan dataset lokal prototipe.'};

function Shell() {
  const {state,playing,setPlaying,advance,setDialog,jobs,notice,dirtyPage,setDirtyPage,dialog}=usePrototype();
  const [route,setRoute]=useState(()=>readRoute(window.location.hash)),[cameraControlsOpen,setCameraControlsOpen]=useState(false);
  function navigate(page,context={}) {
    if(page==='cameras')page='live';
    if(page==='reports'){page='analytics';context={...context,tab:'export'};}
    if(dirtyPage&&!window.confirm('Buang draft workstation yang belum disimpan?'))return;
    setDirtyPage(false);setRoute({page,...context});window.location.hash=routeHash(page,context.tab);
  }
  useEffect(()=>{const change=()=>{const next=readRoute(window.location.hash);setRoute(previous=>previous.page===next.page?{...previous,...next}:next);};change();window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change);},[]);
  useEffect(()=>{const search=event=>{if(event.ctrlKey&&event.key.toLowerCase()==='f'){const input=document.querySelector('main input[type=search]');if(input){event.preventDefault();input.focus();}}};window.addEventListener('keydown',search);return()=>window.removeEventListener('keydown',search);},[]);
  const {page}=route;
  const activeJobs=jobs.filter(j=>['QUEUED','RUNNING'].includes(j.status)).length;
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">CW</span><div>CCTV Workspace<small>OPERATIONS CONSOLE</small></div></div><span className="nav-caption">WORKSPACE CONTOH</span>
      <nav aria-label="Navigasi utama">{sections.map(([id,label,Icon])=><button key={id} className={`nav-item ${page===id?'active':''}`} aria-current={page===id?'page':undefined} onClick={()=>navigate(id)}><Icon size={17} aria-hidden="true"/>{label}</button>)}</nav>
      <div className="sidebar-note"><div className="local-access">Akses lokal prototipe</div><p>Presence dan occupancy.<br/>Track anonim.</p><button onClick={()=>setDialog({type:'definitions'})}>Definisi metrik</button></div>
    </aside>
    <div className="main-shell"><div className="prototype-banner"><strong>DATA SIMULASI</strong><span>Prototipe interaktif. Tidak ada CCTV, employee, atau backend nyata yang terhubung.</span></div>
      {state.persistence!=='HEALTHY'&&<div className="system-warning" role="status">Persistence simulasi terganggu. Preview tidak membuktikan durabilitas; zona menjadi unknown.</div>}
      <header className="page-header"><div><span className="eyebrow">{state.settings.site}</span><h1>{sections.find(s=>s[0]===page)[1]}</h1><p>{descriptions[page]}</p></div></header>
      <main id="main-content">{page==='overview'&&<Overview navigate={navigate}/>}{page==='live'&&<><Live navigate={navigate} cameraId={route.cameraId}/><details className="operations-diagnostics" open={cameraControlsOpen} onToggle={e=>setCameraControlsOpen(e.currentTarget.open)}><summary>Konfigurasi kamera simulasi</summary>{cameraControlsOpen&&<Cameras navigate={navigate} showAdd={false}/>}</details></>}{page==='workspaces'&&<Workspaces navigate={navigate} workspaceId={route.workspaceId}/>}{page==='analytics'&&<Analytics workspaceId={route.workspaceId} tab={route.tab} onTabChange={tab=>{setRoute(p=>({...p,tab}));window.location.hash=routeHash('analytics',tab);}}/>}{page==='settings'&&<><Settings/><details className="prototype-diagnostics"><summary>Kontrol simulasi dan diagnostik</summary><div className="simulation-toolbar"><div className="simulation-clock"><span className="caption">Waktu skenario</span><strong>{dateLabel(state.clock)} · {clock(state.clock,state.settings.timezone,true)}</strong></div><div className="simulation-actions"><Button icon={playing?Pause:Play} onClick={()=>setPlaying(v=>!v)}>{playing?'Jeda simulasi':'Mulai simulasi'}</Button><Button icon={StepForward} onClick={advance}>+1 menit</Button></div></div><div className="inline-controls"><Button icon={FlaskConical} onClick={()=>setDialog({type:'scenario'})}>Skenario</Button><Button icon={ListChecks} onClick={()=>setDialog({type:'jobs'})}>Pekerjaan{activeJobs?` (${activeJobs})`:''}</Button></div></details></>}</main>
      <footer className="status-bar"><Status value={state.persistence==='HEALTHY'?'ONLINE':'DEGRADED'} label="Engine simulasi lokal"/><span>Video tidak disimpan</span><span>Identitas: anonim</span><span>Production tetap Python + PySide6</span></footer>
    </div>{notice&&<div className="notification" role="status">{notice}</div>}<Dialogs key={dialog?.type||'none'} navigate={navigate}/>
  </div>;
}
export default function App() { return window.__CCTV_ENGINE__ ? <EngineApp/> : <PrototypeProvider><Shell/></PrototypeProvider>; }
