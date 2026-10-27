import { validPolygon } from './domain.js';

export function rectangleZone(a,b) {
  const limit=v=>Math.round(Math.max(0,Math.min(1,v))*10000)/10000;
  const left=limit(Math.min(a[0],b[0])),right=limit(Math.max(a[0],b[0]));
  const top=limit(Math.min(a[1],b[1])),bottom=limit(Math.max(a[1],b[1]));
  return [[left,top],[right,top],[right,bottom],[left,bottom]];
}

export function replaySessionId(key,storage) {
  const saved=storage?.getItem(`replay-session-v2:${key}`);
  if(saved && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(saved))return saved;
  const id=crypto.randomUUID();storage?.setItem(`replay-session-v2:${key}`,id);return id;
}

export async function replayCalibrationState(url,{signal,fetcher=fetch,pause=ms=>new Promise(resolve=>setTimeout(resolve,ms))}={}) {
  for(let attempt=0;attempt<6;attempt++) {
    const response=await fetcher(url,{credentials:'same-origin',cache:'no-store',signal});
    const packet=await response.json();
    if([429,503].includes(response.status)&&attempt<5) {await pause(150*(attempt+1));continue;}
    if(!response.ok)throw new Error(typeof packet.detail==='string'?packet.detail:'Hasil area belum dapat dimuat.');
    return packet;
  }
}

export function storedReplayCalibration(value) {
  if(!value || !Array.isArray(value.zones) || value.zones.length>16 || !['bbox_overlap','footpoint'].includes(value.association))return null;
  const ids=new Set();
  for(const row of value.zones) {
    if(!row || typeof row.id!=='string' || !row.id.trim() || row.id.length>80 || ids.has(row.id)
      || typeof row.name!=='string' || !row.name.trim() || row.name.length>80
      || !Array.isArray(row.polygon) || row.polygon.length>32
      || row.polygon.some(p=>!Array.isArray(p) || p.length!==2) || !validPolygon(row.polygon))return null;
    ids.add(row.id);
  }
  if(value.markers!==undefined && (!Array.isArray(value.markers) || value.markers.length>50
    || value.markers.some(row=>!row || !Number.isInteger(row.marker_id) || row.marker_id<0 || row.marker_id>49
      || typeof row.label!=='string' || !row.label.trim() || row.label.length>80)
    || new Set(value.markers.map(row=>row.marker_id)).size!==value.markers.length))return null;
  return {association:value.association,zones:value.zones.map(({id,name,polygon})=>({id,name,polygon})),
    ...(value.markers!==undefined?{markers:value.markers.map(({marker_id,label})=>({marker_id,label}))}:{})};
}

export function recentReplaySessions(sessions) {
  return [...sessions].sort((a,b)=>(a.status === 'ACTIVE' ? 0 : 1)-(b.status === 'ACTIVE' ? 0 : 1)
    || b.last_seen_media_seconds-a.last_seen_media_seconds);
}

export function replayAreaAt(row, mediaSeconds) {
  if(!Array.isArray(row?.media_intervals))return null;
  const at=Math.round(Math.max(0,Number.isFinite(mediaSeconds)?mediaSeconds:0)*1e6);
  const result={occupied_us:0,empty_us:0,state:'UNKNOWN',available:at===0||row.media_intervals.length>0};
  for(const [start,end,state] of row.media_intervals) {
    if(start>at)break;
    const duration=Math.max(0,Math.min(at,end)-start);
    if(state==='OCCUPIED')result.occupied_us+=duration;
    if(state==='EMPTY')result.empty_us+=duration;
    if(start<=at&&at<end)result.state=state;
  }
  return result;
}

export { analysisCaptureSize as replayCaptureSize } from './workstation-engine.js';

export function replayTrackLabel(trackId) {
  const parts=typeof trackId==='string' ? trackId.split(':') : [];
  const epoch=parts.at(-2),track=parts.at(-1);
  return parts.length>=4 && /^\d+$/.test(epoch) && /^\d+$/.test(track) ? `T${epoch}.${track}` : 'Track belum pasti';
}

const predictionLifetime = packet => Number.isFinite(packet.display_prediction_seconds)
  ? Math.max(0,Math.min(1,packet.display_prediction_seconds)) : .4;

export function replayDisplayPacket(packet,mediaTime,speed) {
  const lag=Math.max(0,mediaTime-packet.media_time_seconds);
  let lifetime=0;
  const rows=(packet.display_detections || packet.detections || []).filter(row=>{
    const remaining=predictionLifetime(packet)-(row.measured === false ? row.prediction_age_seconds : 0)-lag;
    if(remaining<=0)return false;
    lifetime=Math.max(lifetime,remaining/Math.max(.1,speed)*1000);
    return true;
  });
  return {packet:{...packet,display_detections:rows},lifetime};
}

const overlap = (a,b) => {
  const area=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0]))*Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]));
  return area/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area || 1);
};

/** Display geometry only. Duration and identity always come from the server. */
export class ReplayOverlayMotion {
  constructor() { this.clear(); }
  clear() { this.tracks=new Map();this.packet=null;this.lastTime=null; }
  accept(packet) {
    const at=packet.media_time_seconds;
    if(this.packet && (this.packet.generation!==packet.generation || at<=this.packet.media_time_seconds))this.clear();
    const next=new Map();
    const rows=packet.display_detections || packet.detections || [];
    for(const row of rows) {
      const key=row.session_id || row.track_id;
      const old=key && this.tracks.get(key), dt=old ? at-old.seen : 0;
      const continuous=old && dt>0 && dt<=.5 && overlap(old.row.box,row.box)>.15;
      let velocity=[0,0];
      if(continuous && row.measured!==false && old.row.measured!==false) {
        velocity=[0,1].map(axis=>{
          const change=(row.box[axis]+row.box[axis+2]-old.row.box[axis]-old.row.box[axis+2])/2/dt;
          const limit=(row.box[axis+2]-row.box[axis])*.8;
          return Math.max(-limit,Math.min(limit,change));
        });
        if(rows.some(peer=>peer!==row && overlap(row.box,peer.box)>.05))velocity=[0,0];
      }
      next.set(key || row,{row,seen:at,velocity,box:continuous ? old.box : [...row.box]});
    }
    this.tracks=next;this.packet=packet;
  }
  sample(mediaTime) {
    if(!this.packet)return [];
    if(this.lastTime!==null && mediaTime<this.lastTime) {this.clear();return [];}
    const dt=this.lastTime===null ? 0 : Math.min(.1,mediaTime-this.lastTime);
    this.lastTime=mediaTime;
    const lag=mediaTime-this.packet.media_time_seconds;
    if(lag<0)return [];
    const rows=[];
    for(const track of this.tracks.values()) {
      const {row,velocity}=track;
      const age=lag+(row.measured===false ? row.prediction_age_seconds : 0);
      if(age>=predictionLifetime(this.packet))continue;
      const horizon=row.measured===false ? 0 : Math.min(.15,lag);
      const shift=velocity.map((v,axis)=>Math.max(-row.box[axis],Math.min(1-row.box[axis+2],v*horizon)));
      const target=row.box.map((v,i)=>v+shift[i%2]);
      const alpha=1-Math.exp(-dt/.055);
      track.box=track.box.map((v,i)=>v+(target[i]-v)*alpha);
      rows.push({...row,box:[...track.box],visual_estimate:row.measured===false || lag>.22 || (horizon>0 && velocity.some(v=>Math.abs(v)>1e-5))});
    }
    return rows;
  }
}
