import { durationClock } from './engine-client';

export function TrackCaption({ row, width, height, fontSize = 9, ageMs = 0, mirror = false }) {
  const box = row.display_box || row.box;
  const label = ['Working','Idle'].includes(row.activity?.label) ? row.activity.label : null;
  const elapsed = row.activity?.tracked_elapsed_us ?? row.workstation_times?.[0]?.presence_us ?? 0;
  const textWidth = fontSize * 5.5, lines = label ? 2 : 1, lineHeight = fontSize + 2;
  const left = (mirror ? 1-box[2] : box[0])*width;
  const x = Math.max(2,Math.min(left+3,width-textWidth-3));
  const y = Math.max(fontSize+3,Math.min(box[1]*height+fontSize+3,height-(lines-1)*lineHeight-4));
  return <g className="track-caption">
    <title>{`Track ${row.track_id?.split(':').at(-1) || 'belum dikonfirmasi'}. Durasi sejak track pertama terlihat, bukan durasi produktif. Working: gerak terlihat. Idle: gerak rendah terkonfirmasi.`}</title>
    <rect x={x-2} y={y-fontSize-1} width={textWidth} height={lines*lineHeight+2} rx="2" fill="#101b18" fillOpacity=".78"/>
    {label && <text x={x} y={y} className={`track-activity-label track-activity-${label.toLowerCase()}`} style={{fontSize}} data-testid="track-activity-label">{label}</text>}
    <text x={x} y={y+(label ? lineHeight : 0)} className="rtsp-presence-clock" style={{fontSize}} data-testid="rtsp-presence-clock">{durationClock(elapsed + Math.max(0,ageMs)*1000)}</text>
  </g>;
}
