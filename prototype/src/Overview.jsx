import { usePrototype } from './store';
import { Button, Empty, EventList, Panel, Status } from './components';

export default function Overview({navigate}) {
  const {state,setDialog}=usePrototype();
  if(!state.cameras.length)return <Empty title="Belum ada kamera" action={<Button variant="primary" onClick={()=>setDialog({type:'camera'})}>Tambah kamera</Button>}/>;
  return <div className="overview-grid"><Panel title="Kamera terdaftar" action={<Button onClick={()=>navigate('live')}>Buka monitoring</Button>}><div className="health-list">{state.cameras.map(camera=><button key={camera.id} onClick={()=>navigate('live',{cameraId:camera.id})}><span><strong>{camera.name}</strong><small>{camera.area}</small></span><Status value={camera.status}/></button>)}</div></Panel><Panel title="Aktivitas konfigurasi"><EventList events={state.events} onSelect={event=>setDialog({type:'event',event})}/></Panel></div>;
}
