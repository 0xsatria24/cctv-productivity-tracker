import { useId } from 'react';
import { clock } from './domain';

export default function Scene({ camera, workspaces = [], now, overlay = {zones:true,detection:false,tracks:false}, paused = false, editPolygon, selectedVertex, onCanvasClick, onVertexDown }) {
  const id = useId().replaceAll(':','');
  const isWarehouse = camera?.area === 'Gudang';
  return <svg className="sim-scene" viewBox="0 0 960 540" role="img" aria-label="Ilustrasi frame kamera simulasi, bukan rekaman CCTV" onClick={onCanvasClick}>
    <title>Ilustrasi area kerja simulasi {camera?.name}</title>
    <rect width="960" height="540" fill="var(--surface-video)"/>
    <path d="M0 0H960V184H0Z" fill="var(--surface-raised)"/>
    <path d="M0 184H960V540H0Z" fill="var(--surface-panel)"/>
    <path d="M0 184H960M160 184L80 540M380 184L340 540M600 184L650 540M800 184L960 520M0 300H960M0 432H960" className="scene-grid"/>
    <rect x="28" y="40" width="220" height="92" fill="var(--surface-video)" stroke="var(--border-control)"/>
    <rect x="300" y="40" width="220" height="92" fill="var(--surface-video)" stroke="var(--border-control)"/>
    <rect x="758" y="30" width="148" height="154" fill="var(--surface-sidebar)" stroke="var(--border-control)"/>
    <rect x="766" y="36" width="8" height="142" fill="var(--border-subtle)"/>
    <rect x="778" y="10" width="150" height="18" fill="var(--text-muted)"/>
    {[{x:132,y:252},{x:548,y:252}].map((desk,i) => <g key={i}>
      <path d={`M${desk.x} ${desk.y}h240l32 62H${desk.x-28}Z`} fill="var(--surface-raised)" stroke="var(--border-control)"/>
      <path d={`M${desk.x-10} ${desk.y+64}v96M${desk.x+242} ${desk.y+64}v96`} className="scene-leg"/>
      {isWarehouse ? <><rect x={desk.x+14} y={desk.y-64} width="82" height="64" fill="var(--surface-hover)" stroke="var(--border-control)"/><rect x={desk.x+106} y={desk.y-42} width="98" height="42" fill="var(--surface-hover)" stroke="var(--border-control)"/></> : <><rect x={desk.x+74} y={desk.y-52} width="100" height="70" rx="2" fill="var(--surface-video)" stroke="var(--border-control)"/><path d={`M${desk.x+124} ${desk.y+18}v16h-28h56`} className="scene-leg"/><rect x={desk.x+62} y={desk.y+44} width="132" height="12" fill="var(--border-subtle)"/></>}
    </g>)}
    {workspaces.map((w,i) => {
      const personX = 242+i*414+(paused ? 0 : Math.sin(now/60000+i)*7), personY = 380;
      const occupied = w.liveState === 'OCCUPIED';
      return <g key={w.id}>
        {occupied && <g><ellipse cx={personX} cy={440} rx="54" ry="11" fill="var(--surface-video)"/><rect x={personX-28} y={personY-4} width="56" height="94" rx="18" fill="var(--text-disabled)"/><circle cx={personX} cy={personY-30} r="22" fill="var(--text-secondary)"/><path d={`M${personX-24} ${personY+76}l-14 52M${personX+24} ${personY+76}l14 52`} className="scene-person"/></g>}
        {overlay.zones && !editPolygon && <><polygon points={w.polygon.map(([x,y]) => `${x*960},${y*540}`).join(' ')} className="zone-overlay"/><rect x={w.polygon[0][0]*960} y={w.polygon[0][1]*540-26} width="124" height="24" fill="var(--surface-selected)"/><text x={w.polygon[0][0]*960+8} y={w.polygon[0][1]*540-9} className="zone-label">{w.name}</text></>}
        {occupied && camera.status === 'ONLINE' && overlay.detection && <rect x={personX-52} y={personY-64} width="104" height="190" className="detection-box"/>}
        {occupied && camera.status === 'ONLINE' && overlay.tracks && <><rect x={personX-52} y={personY-88} width="136" height="24" fill="var(--surface-sidebar)"/><text x={personX-44} y={personY-71} className="track-label">Anonim {camera.id.slice(-2)}:{i+1}</text></>}
      </g>;
    })}
    {editPolygon && <><polygon points={editPolygon.map(([x,y]) => `${x*960},${y*540}`).join(' ')} className="zone-overlay draft"/>{editPolygon.map(([x,y],i) => <g key={i}><rect x={x*960-6} y={y*540-6} width="12" height="12" className={`vertex-handle ${selectedVertex === i ? 'selected' : ''}`} onPointerDown={event => {event.stopPropagation(); onVertexDown?.(event,i);}}/><text x={x*960+12} y={y*540+20} className="track-label">{i+1}</text></g>)}</>}
    <rect x="0" y="0" width="960" height="26" fill="var(--surface-sidebar)"/>
    <text x="12" y="18" className="scene-caption">FRAME SIMULASI · ILUSTRASI, BUKAN CCTV</text>
    <text x="948" y="18" textAnchor="end" className="scene-caption">{clock(now,'Asia/Jakarta',true)}</text>
    <defs><pattern id={`unknown-${id}`} width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" stroke="var(--status-unknown)" strokeWidth="1"/></pattern></defs>
  </svg>;
}
