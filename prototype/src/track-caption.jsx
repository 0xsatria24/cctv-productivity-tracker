import { useEffect, useState } from 'react';
import { durationClock } from './engine-client';

export function TrackCaption({ row, width, height, fontSize = 9, ageMs = 0, mirror = false }) {
  if (!row.track_id) return null;
  const box = row.display_box || row.box;
  const label = ['Working','Idle'].includes(row.activity?.label) ? row.activity.label : null;
  const elapsed = row.activity?.tracked_elapsed_us ?? row.workstation_times?.[0]?.presence_us ?? 0;
  const textWidth = fontSize * 5.5, lines = label ? 2 : 1, lineHeight = fontSize + 2;
  const left = (mirror ? 1-box[2] : box[0])*width;
  const x = Math.max(2,Math.min(left+3,width-textWidth-3));
  const y = Math.max(fontSize+3,Math.min(box[1]*height+fontSize+3,height-(lines-1)*lineHeight-4));
  return <g className="track-caption">
    <title>{`${row.evidence === 'PREDICTED' ? 'Posisi perkiraan singkat, bukan deteksi baru atau bukti pencatatan. ' : ''}Track ${row.track_id.split(':').at(-1)}. Durasi sejak track pertama terlihat, bukan durasi produktif. Working: gerak terlihat. Idle: gerak rendah terkonfirmasi.`}</title>
    <rect x={x-2} y={y-fontSize-1} width={textWidth} height={lines*lineHeight+2} rx="2" fill="#101b18" fillOpacity=".78"/>
    {label && <text x={x} y={y} className={`track-activity-label track-activity-${label.toLowerCase()}`} style={{fontSize}} data-testid="track-activity-label">{label}</text>}
    <text x={x} y={y+(label ? lineHeight : 0)} className="rtsp-presence-clock" style={{fontSize}} data-testid="rtsp-presence-clock">{durationClock(elapsed + Math.max(0,ageMs)*1000)}</text>
  </g>;
}

export function PredictedTrack({ row, width, height, fontSize = 9, mirror = false, ageMs = 0 }) {
  const [expired,setExpired] = useState(false);
  useEffect(() => {
    setExpired(false);
    const timer=setTimeout(()=>setExpired(true),Math.max(0,row.valid_for_ms));
    return ()=>clearTimeout(timer);
  },[row]);
  if (expired || row.valid_for_ms<=0) return null;
  const box=row.display_box || row.box;
  const left=mirror ? 1-box[2] : box[0];
  return <g data-testid="rtsp-person-prediction" data-evidence="PREDICTED" opacity=".6">
    <title>Posisi perkiraan singkat. Tidak dihitung sebagai deteksi atau bukti pencatatan.</title>
    <rect x={left*width} y={box[1]*height} width={(box[2]-box[0])*width} height={(box[3]-box[1])*height} className="person-box" style={{strokeDasharray:'4 3'}}/>
    <TrackCaption row={row} width={width} height={height} fontSize={fontSize} mirror={mirror} ageMs={ageMs}/>
  </g>;
}
