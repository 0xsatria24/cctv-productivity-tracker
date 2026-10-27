import { ArrowUpRight, Plus } from 'lucide-react';
import { usePrototype } from './store';
import { Button, Empty, EventList, Panel, Status } from './components';
import { percent } from './domain';

export default function Overview({navigate}) {
  const {state,observed,setDialog}=usePrototype();
  const desks=observed.filter(w=>w.kind==='desk');
  const known=desks.filter(w=>w.liveState!=='UNKNOWN');
  const countKnown=desks.filter(w=>w.count!=null);
  if(!state.cameras.length)return <Empty title="Workspace simulasi masih kosong" description="Mulai dengan satu kamera contoh, lalu tambahkan polygon workstation." action={<Button variant="primary" icon={Plus} onClick={()=>setDialog({type:'camera'})}>Tambah kamera contoh</Button>}/>;
  return <><div className="overview-intro"><span className="eyebrow">SNAPSHOT LIVE SIMULASI</span><Button icon={ArrowUpRight} onClick={()=>navigate('live')}>Buka monitoring</Button></div><div className="live-strip"><div><span>Workstation terisi</span><strong>{desks.filter(w=>w.liveState==='OCCUPIED').length}<small> / {known.length} valid / {desks.length} total</small></strong></div><div><span>Occupant teramati</span><strong>{countKnown.length?countKnown.reduce((n,w)=>n+w.count,0):'N/A'}<small> pada zona desk</small></strong></div><div><span>Coverage jumlah</span><strong>{percent(desks.length?countKnown.length/desks.length*100:null)}</strong></div><div><span>Zona unknown</span><strong className="unknown">{desks.filter(w=>w.liveState==='UNKNOWN').length}<small> / {desks.length} desk</small></strong></div></div>
    <div className="section-toolbar"><p>Durasi, timeline dan ekspor tersedia dalam satu area laporan.</p><Button onClick={()=>navigate('analytics')}>Buka laporan</Button></div>
    <div className="overview-grid"><Panel title="Kesehatan kamera" caption={`${state.cameras.filter(c=>c.status==='ONLINE').length} dari ${state.cameras.length} kamera terhubung (mock)`}><div className="health-list">{state.cameras.map(camera=><button key={camera.id} onClick={()=>navigate('live',{cameraId:camera.id})}><span><strong>{camera.name}</strong><small>{camera.id}</small></span><Status value={camera.status}/><ArrowUpRight size={14}/></button>)}</div></Panel>
      <Panel title="Event aktivitas terbaru" caption="Event simulasi dari kamera dan observasi zona" action={<Button onClick={()=>setDialog({type:'events'})}>Semua event</Button>}><EventList events={state.events} onSelect={event=>setDialog({type:'event',event})}/></Panel>
    </div><div className="observation-note">Presence di workstation tidak membuktikan hasil kerja. Unknown tidak dihitung sebagai waktu kosong.</div></>;
}
