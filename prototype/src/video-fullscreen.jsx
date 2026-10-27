import { useEffect, useRef, useState } from 'react';
import { Minimize } from 'lucide-react';
import { Button } from './components';

export function useVideoFullscreen(target, running) {
  const [active,setActive]=useState(false),[visible,setVisible]=useState(true);
  const [error,setError]=useState('');
  const bar=useRef(null),idle=useRef(null);
  function wake() {
    setVisible(true);clearTimeout(idle.current);
    if(active&&running)idle.current=setTimeout(()=>{
      const keyboard=bar.current?.contains(document.activeElement)&&document.activeElement?.matches(':focus-visible');
      if(!keyboard&&!bar.current?.matches(':hover'))setVisible(false);
    },2500);
  }
  useEffect(()=>{
    const changed=()=>setActive(document.fullscreenElement===target.current);
    document.addEventListener('fullscreenchange',changed);
    return()=>{document.removeEventListener('fullscreenchange',changed);clearTimeout(idle.current);};
  },[target]);
  useEffect(()=>{if(active)wake();return()=>clearTimeout(idle.current);},[active,running]);
  async function toggle() {
    setError('');
    try {
      if(document.fullscreenElement===target.current)await document.exitFullscreen();
      else await target.current.requestFullscreen();
    } catch {setError('Fullscreen tidak tersedia di browser ini.');}
  }
  return {active,visible:visible||!running,bar,wake,toggle,error};
}

export function FullscreenControls({controller,name}) {
  return <>{controller.active&&<div className="replay-fullscreen-controls" data-visible={controller.visible} ref={controller.bar}>
    <span className="replay-fullscreen-name">{name}</span><span className="live-fullscreen-label">LIVE</span>
    <Button icon={Minimize} aria-label={`Keluar fullscreen ${name}`} onClick={()=>controller.toggle().catch(()=>{})}/>
  </div>}{controller.error&&<p className="replay-fullscreen-error" role="alert">{controller.error}</p>}</>;
}
