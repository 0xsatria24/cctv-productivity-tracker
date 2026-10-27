import { useEffect, useRef, useState } from 'react';
import { ReplayOverlayMotion, replayTrackLabel } from './replay-domain';

export function ReplayOverlay({packet,video,synchronized=false,dimensions,frameSize,formatTime}) {
  const motion=useRef(new ReplayOverlayMotion()), [rows,setRows]=useState([]);
  const active=Boolean(packet);
  useEffect(()=>{
    if(packet)motion.current.accept(packet);
    else {motion.current.clear();setRows([]);}
  },[packet]);
  useEffect(()=>{
    const element=video.current;
    if(!active || !element || synchronized)return;
    let frame,cancelled=false;
    const decodedFrames=typeof element.requestVideoFrameCallback==='function';
    const schedule=()=>decodedFrames ? element.requestVideoFrameCallback(draw) : requestAnimationFrame(draw);
    const draw=(_now,metadata)=>{
      if(cancelled)return;
      setRows(!element.paused && !element.seeking ? motion.current.sample(metadata?.mediaTime ?? element.currentTime) : []);
      frame=schedule();
    };
    frame=schedule();
    return()=>{cancelled=true;if(decodedFrames)element.cancelVideoFrameCallback(frame);else cancelAnimationFrame(frame);};
  },[video,active,synchronized]);
  const w=dimensions.width,h=dimensions.height;
  const font=11*Math.max(w/frameSize.width,h/frameSize.height);
  const visibleRows=synchronized ? packet?.display_detections || [] : rows;
  return <svg className="replay-overlay" viewBox={`0 0 ${w} ${h}`} aria-label="Deteksi orang pada replay">{visibleRows.map((row,i)=>{
    const [x1,y1,x2,y2]=row.box;
    const held=row.measured===false,weak=row.evidence_state==='WEAK',estimated=row.visual_estimate;
    const duration=formatTime(row.accumulated_duration_us/1e6);
    const label=`${replayTrackLabel(row.track_id)}${row.session_id ? ` · S ${row.session_id.slice(0,6)}` : ''}`;
    const timer=row.session_id ? `${duration}${row.recovery_pending?' · cari ID':held?' · terakhir':weak?' · lemah':estimated?' · estimasi':''}` : weak ? 'Bukti lemah · menunggu sesi' : 'Menunggu sesi';
    const caption=`${replayTrackLabel(row.track_id)} · ${timer}`;
    const labelWidth=Math.min(w,caption.length*font*.62+font*.8),labelX=Math.max(0,Math.min(x1*w,w-labelWidth)),labelY=Math.max(0,y1*h-font*1.6);
    return <g key={row.session_id || row.track_id || i} data-testid="replay-person-detection" data-session-id={row.session_id}>
      <title>{label} · {timer}</title>
      <rect className="replay-person-box" strokeDasharray={estimated || weak?'5 4':undefined} x={x1*w} y={y1*h} width={(x2-x1)*w} height={(y2-y1)*h}><title>{held?'Posisi terakhir; timer dibekukan.':weak?'Deteksi lemah; timer dibekukan.':estimated?'Estimasi posisi visual; durasi tetap dari pengukuran engine.':`Posisi deteksi, confidence ${Math.round(row.confidence*100)}%`}</title></rect>
      <rect className="replay-label-background" x={labelX} y={labelY} width={labelWidth} height={font*1.6}/>
      <text className="replay-person-timer" x={labelX+font*.4} y={labelY+font*1.08} fontSize={font} textLength={caption.length*font*.62+font*.8>w?w-font*.8:undefined} lengthAdjust="spacingAndGlyphs">{caption}</text>
    </g>;
  })}</svg>;
}
