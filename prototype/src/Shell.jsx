import { useEffect, useState } from 'react';
import { ChartNoAxesCombined, LayoutDashboard, ScanLine, Settings as SettingsIcon, Video } from 'lucide-react';
import { PrototypeProvider, usePrototype } from './store';
import { Status } from './components';
import Overview from './Overview';
import Live from './Live';
import Workspaces from './Workspaces';
import Analytics from './Analytics';
import { Settings } from './Management';
import Dialogs from './Dialogs';
import EngineApp from './EngineApp';
import { readRoute, routeHash } from './navigation.mjs';
import { useLanguage } from './language';
import { VideoReplayWorkspace } from './video-replay';

const sections=[['overview','Ringkasan',LayoutDashboard],['live','Pemantauan Live',Video],['workspaces','Workstation',ScanLine],['analytics','Laporan',ChartNoAxesCombined],['settings','Pengaturan',SettingsIcon]];

function Shell() {
  const {t}=useLanguage();
  const {state,notice,dirtyPage,setDirtyPage,dialog}=usePrototype();
  const [route,setRoute]=useState(()=>readRoute(window.location.hash));
  function navigate(page,context={}) {
    if(page==='cameras')page='live';
    if(page==='reports'){page='analytics';context={...context,tab:'export'};}
    if(dirtyPage&&!window.confirm('Buang draft workstation yang belum disimpan?'))return;
    setDirtyPage(false);setRoute({page,...context});window.location.hash=routeHash(page,context.tab);
  }
  useEffect(()=>{const change=()=>{const next=readRoute(window.location.hash);setRoute(previous=>previous.page===next.page?{...previous,...next}:next);};window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change);},[]);
  const {page}=route;
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">CW</span><div>CCTV Workspace<small>MONITORING</small></div></div>
      <nav aria-label={t('Navigasi utama')}>{sections.map(([id,label,Icon])=><button key={id} className={`nav-item ${page===id?'active':''}`} aria-current={page===id?'page':undefined} onClick={()=>navigate(id)}><Icon size={17} aria-hidden="true"/>{t(label)}</button>)}</nav>
    </aside>
    <div className="main-shell"><header className="page-header"><div>{state.settings.site&&<span className="eyebrow">{state.settings.site}</span>}<h1>{t(sections.find(s=>s[0]===page)?.[1])}</h1></div></header>
      <main id="main-content"><VideoReplayWorkspace visible={page==='live'}/>{page==='overview'&&<Overview navigate={navigate}/>} {page==='live'&&<Live navigate={navigate} cameraId={route.cameraId}/>} {page==='workspaces'&&<Workspaces navigate={navigate} workspaceId={route.workspaceId}/>} {page==='analytics'&&<Analytics workspaceId={route.workspaceId} tab={route.tab} onTabChange={tab=>{setRoute(p=>({...p,tab}));window.location.hash=routeHash('analytics',tab);}}/>} {page==='settings'&&<Settings/>}</main>
      <footer className="status-bar"><span>{t('Mode pengembangan')}</span><span>{state.settings.timezone}</span></footer>
    </div>{notice&&<div className="notification" role="status">{notice}</div>}<Dialogs key={dialog?.type||'none'} navigate={navigate}/>
  </div>;
}
export default function App(){return window.__CCTV_ENGINE__?<EngineApp/>:<PrototypeProvider><Shell/></PrototypeProvider>;}
