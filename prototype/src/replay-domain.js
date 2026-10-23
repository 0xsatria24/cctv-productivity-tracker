import { validPolygon } from './domain.js';

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
  return {association:value.association,zones:value.zones.map(({id,name,polygon})=>({id,name,polygon}))};
}

export function recentReplaySessions(sessions) {
  return [...sessions].sort((a,b)=>(a.status === 'ACTIVE' ? 0 : 1)-(b.status === 'ACTIVE' ? 0 : 1)
    || b.last_seen_media_seconds-a.last_seen_media_seconds);
}

export function replayCaptureSize(width,height) {
  const scale=Math.min(1,960/Math.max(width,height),Math.sqrt(1280*720/(width*height)));
  return {width:Math.max(1,Math.round(width*scale)),height:Math.max(1,Math.round(height*scale))};
}

export function replayDisplayPacket(packet,mediaTime,speed) {
  const lag=Math.max(0,mediaTime-packet.media_time_seconds);
  let lifetime=750;
  const rows=(packet.display_detections || packet.detections || []).filter(row=>{
    if(row.measured !== false)return true;
    const remaining=.4-row.prediction_age_seconds-lag;
    if(remaining<=0)return false;
    lifetime=Math.min(lifetime,remaining/Math.max(.1,speed)*1000);
    return true;
  });
  return {packet:{...packet,display_detections:rows},lifetime};
}
