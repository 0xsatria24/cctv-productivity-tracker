import { replayAreaAt } from './replay-domain';

export function WorkstationOverlay({zones,rows,dimensions,frameSize,formatTime,fresh,playing,enabled,position,basis='replay',fit='contain'}) {
  const w=dimensions.width,h=dimensions.height,font=11*(fit==='cover'?Math.min:Math.max)(w/frameSize.width,h/frameSize.height);
  return <svg className="replay-overlay replay-zones" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio={fit==='cover'?'xMidYMid slice':'xMidYMid meet'} aria-label="Zona dan timer workstation">
    {zones.map(zone=>{
      const row=rows.find(item=>item.zone_id===zone.id);
      const playback=basis==='live'?{occupied_us:row?.occupied_us||0,available:Boolean(row),state:'UNKNOWN'}:replayAreaAt(row,position);
      const evidence=enabled&&playing&&fresh&&row?row.state:playback?.state;
      const state=evidence==='OCCUPIED'?'Terisi':evidence==='EMPTY'?'Kosong':'';
      const height=font*1.6;
      const suffix=` · ${playback?.available?formatTime(playback.occupied_us/1e6):'--:--:--'}${state?' · '+state:''}`;
      const nameLimit=Math.max(2,Math.min(22,Math.floor((w-font*.8)/(font*.62))-suffix.length));
      const name=zone.name.length>nameLimit?zone.name.slice(0,nameLimit-1)+'…':zone.name;
      const label=`${name}${suffix}`;
      const width=Math.min(w,label.length*font*.62+font*.8);
      const x=Math.max(0,Math.min(Math.min(...zone.polygon.map(p=>p[0]))*w,w-width));
      const y=Math.max(0,Math.min(Math.min(...zone.polygon.map(p=>p[1]))*h,h-height));
      return <g key={zone.id} data-testid="workstation-area-timer">
        <title>{zone.name}: {basis==='live'?'durasi terisi yang tersimpan pada sesi live ini.':'durasi terisi sampai posisi video ini, hanya dari interval yang sudah dianalisis.'}</title>
        <polygon points={zone.polygon.map(([px,py])=>`${px*w},${py*h}`).join(' ')}><title>{zone.name}</title></polygon>
        <rect className="replay-label-background" x={x} y={y} width={width} height={height}/>
        <text className="replay-person-timer" x={x+font*.4} y={y+font*1.08} fontSize={font}>{label}</text>
      </g>;
    })}
  </svg>;
}
