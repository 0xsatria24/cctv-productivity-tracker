import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ReplayOverlay } from '../src/replay-overlay';
import { installTheme } from '../src/theme';
import '../src/styles.css';
import '../src/video-replay.css';

const formatTime=value=>new Date(Math.max(0,value)*1000).toISOString().slice(11,19);
const box=at=>[.12+.12*Math.sin(at*.8),.26,.28+.12*Math.sin(at*.8),.86];
const person=(id,position,at)=>({session_id:id,track_id:`fixture:0:1:${id==='first-person'?1:2}`,box:position,confidence:.95,measured:true,accumulated_duration_us:Math.floor(at/ .2)*200000});

function Fixture() {
  const video=useRef({currentTime:0,paused:true,seeking:false}),generation=useRef(0),lastSample=useRef(-1),lastSecond=useRef(0);
  const viewport=useRef(null),[frameSize,setFrameSize]=useState({width:960,height:540});
  const options=useRef({speed:1,online:true,second:true});
  const [packet,setPacket]=useState(null),[playing,setPlaying]=useState(false),[time,setTime]=useState(0),[online,setOnline]=useState(true),[second,setSecond]=useState(true);
  useEffect(()=>{
    const observer=new ResizeObserver(([entry])=>setFrameSize(entry.contentRect));
    observer.observe(viewport.current);return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    let frame,last=performance.now();
    const tick=now=>{
      const clock=video.current;
      if(!clock.paused) {
        clock.currentTime+=(now-last)/1000*options.current.speed;
        if(options.current.online && clock.currentTime-lastSample.current>=.2) {
          const at=clock.currentTime;
          const rows=[person('first-person',box(at),at)];
          if(options.current.second) {lastSecond.current=at;rows.push(person('second-person',[.65,.26,.81,.86],at));}
          else if(at-lastSecond.current<.4)rows.push({...person('second-person',[.65,.26,.81,.86],lastSecond.current),measured:false,prediction_age_seconds:at-lastSecond.current});
          setPacket({media_time_seconds:at,generation:generation.current,display_detections:rows});
          lastSample.current=at;
        }
        setTime(clock.currentTime);
      }
      last=now;frame=requestAnimationFrame(tick);
    };
    frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame);
  },[]);
  function playPause() {video.current.paused=!video.current.paused;setPlaying(!video.current.paused);if(video.current.paused)setPacket(null);}
  function reset() {video.current.currentTime=0;generation.current++;lastSample.current=-1;lastSecond.current=0;setPacket(null);setTime(0);}
  return <main style={{maxWidth:1000,margin:'24px auto',padding:16}}>
    <h1>Uji renderer replay</h1>
    <p>Fixture sintetis. Menguji tampilan box, durasi dan batas waktu; tidak menguji detektor atau akurasi identitas.</p>
    <div className="replay-controls" style={{padding:'12px 0'}}>
      <div className="inline-controls"><button onClick={playPause}>{playing?'Jeda':'Putar'}</button><button onClick={reset}>Seek awal</button><label>Kecepatan <select aria-label="Kecepatan fixture" onChange={e=>{options.current.speed=Number(e.target.value);}} defaultValue="1"><option value="0.5">0.5x</option><option value="1">1x</option><option value="2">2x</option></select></label></div>
      <div className="inline-controls"><button onClick={()=>{options.current.online=!online;setOnline(!online);}}>{online?'Putuskan bukti':'Pulihkan bukti'}</button><button onClick={()=>{options.current.second=!second;setSecond(!second);}}>{second?'Hilangkan orang kedua':'Kembalikan orang kedua'}</button></div>
    </div>
    <p role="status">Waktu media {formatTime(time)} · {playing?'Berjalan':'Dijeda'} · Bukti {online?'tersedia':'terputus'}</p>
    <div className="replay-frame" style={{width:'100%'}} ref={viewport}>
      <svg viewBox="0 0 960 540" width="100%" height="100%" aria-label="Objek sumber sintetis">
        <rect x={box(time)[0]*960} y="140.4" width="153.6" height="324" fill="var(--surface-raised)"/>
        {second&&<rect x="624" y="140.4" width="153.6" height="324" fill="var(--surface-raised)"/>}
      </svg>
      <ReplayOverlay packet={packet} video={video} dimensions={{width:960,height:540}} frameSize={frameSize} formatTime={formatTime}/>
    </div>
    <p>Garis putus-putus: estimasi posisi atau bukti lama. Nilai durasi hanya berubah pada paket fixture. Bukti berhenti: box habis dalam 0,4 detik waktu media.</p>
  </main>;
}
installTheme();
const root=createRoot(document.getElementById('root'));
root.render(<Fixture/>);
if(import.meta.hot)import.meta.hot.dispose(()=>root.unmount());
