export default function Scene({editPolygon=[],selectedVertex,onCanvasClick,onVertexDown}) {
  return <svg className="sim-scene" viewBox="0 0 960 540" role="img" aria-label="Zona workstation" onClick={onCanvasClick}>
    <rect width="960" height="540" fill="var(--surface-video)"/>
    <polygon points={editPolygon.map(([x,y])=>`${x*960},${y*540}`).join(' ')} className="zone-overlay draft"/>
    {editPolygon.map(([x,y],index)=><g key={index}><rect x={x*960-6} y={y*540-6} width="12" height="12" className={`vertex-handle ${selectedVertex===index?'selected':''}`} onPointerDown={event=>{event.stopPropagation();onVertexDown?.(event,index);}}/><text x={x*960+12} y={y*540+20} className="track-label">{index+1}</text></g>)}
  </svg>;
}
