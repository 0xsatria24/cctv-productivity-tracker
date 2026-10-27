import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {LanguageProvider} from '../src/language';
import {installTheme} from '../src/theme';
import {Button} from '../src/components';
import {CalibrationDialog} from '../src/live-engine';
import {WorkstationOverlay} from '../src/workstation-overlay';
import {WorkstationResults} from '../src/workstation-replay';
import {useVideoFullscreen,FullscreenControls} from '../src/video-fullscreen';
import '../src/styles.css';
import '../src/engine.css';
import '../src/video-replay.css';
import '../src/camera-wall.css';

const clock=value=>new Date(value*1000).toISOString().slice(11,19);
const image='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#242b34"/><text x="180" y="230" fill="#eef0f3" font-family="sans-serif" font-size="20">Bidang kamera sintetis</text></svg>');
function Fixture() {
  const [profile,setProfile]=useState({zones:[{id:'desk',name:'Meja depan',polygon:[[.1,.15],[.65,.15],[.65,.85],[.1,.85]]}],position:{mode:'bbox_overlap'},markers:[],analysis_mode:'workstation'});
  const [editing,setEditing]=useState(false),[running,setRunning]=useState(true),[timer,setTimer]=useState(12),[saved,setSaved]=useState('');
  const frame=useRef(null),fullscreen=useVideoFullscreen(frame,running),[size,setSize]=useState({width:800,height:600});
  useEffect(()=>{const observer=new ResizeObserver(([e])=>setSize(e.contentRect));observer.observe(frame.current);return()=>observer.disconnect();},[]);
  useEffect(()=>{if(!running)return;const interval=setInterval(()=>setTimer(v=>v+.5),500);return()=>clearInterval(interval);},[running]);
  const rows=profile.zones.map(zone=>({zone_id:zone.id,name:zone.name,state:'OCCUPIED',count:1,occupied_us:Math.floor(timer)*1e6,empty_us:3e6}));
  return <main style={{maxWidth:1000,margin:'24px auto',padding:16}}>
    <h1>Uji UI sintetis, bukan kamera live</h1><p>Komponen area, timer, fullscreen, dan dialog kalibrasi produk yang sama. Penyimpanan uji berada di memori halaman ini.</p>
    <div className="inline-controls" style={{marginBottom:12}}><Button onClick={()=>fullscreen.toggle()}>Fullscreen kamera uji</Button><Button onClick={()=>setRunning(v=>!v)}>{running?'Putus bukti kamera':'Pulihkan bukti kamera'}</Button></div>
    <div className="camera-frame live-video-frame" ref={frame} style={{aspectRatio:'4/3'}} onPointerMove={fullscreen.wake} onFocusCapture={fullscreen.wake}>
      <img src={image} alt="Bidang kamera sintetis"/><span style={{position:'absolute',right:12,top:12,fontSize:12}}>SINTETIS · UJI UI</span>
      <WorkstationOverlay basis="live" zones={profile.zones} rows={rows} dimensions={{width:640,height:480}} frameSize={size} formatTime={clock} fresh={running} playing={running} enabled={running}/>
      <FullscreenControls controller={fullscreen} name="Kamera uji sintetis"/>
    </div>
    <div className="live-area-results"><WorkstationResults liveMode rows={rows} zones={profile.zones} calibrated fresh={running} playing={running} enabled={running} ready formatTime={clock} onCalibrate={()=>setEditing(true)}/></div>
    <output role="status">{saved}</output>
    {editing&&<CalibrationDialog value={{frame:image,width:640,height:480,camera_key:'a'.repeat(64),source:'WEBCAM_LIVE',profile}} live={{action:async(_path,value)=>{setProfile(value);setSaved(`Tersimpan: mode ${value.analysis_mode}, ${value.zones.length} area, ${value.markers.length} marker`);}}} onClose={()=>setEditing(false)} onSaved={()=>setEditing(false)}/>}
  </main>;
}
installTheme();
const fixtureRoot=createRoot(document.getElementById('root'));
fixtureRoot.render(<LanguageProvider><Fixture/></LanguageProvider>);
if(import.meta.hot)import.meta.hot.dispose(()=>fixtureRoot.unmount());
