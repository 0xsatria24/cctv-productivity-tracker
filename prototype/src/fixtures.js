import { ANCHOR, DAY, MINUTE, atDate, dateKey } from './domain.js';

export function initialState() {
  const cameras = [
    ['Area produksi', 'Produksi', 'ONLINE'], ['Area perakitan', 'Perakitan', 'ONLINE'],
    ['Area pengemasan', 'Pengemasan', 'DEGRADED'], ['Gudang utara', 'Gudang', 'OFFLINE'],
    ['Ruang desain', 'Desain', 'ONLINE'], ['Gudang selatan', 'Gudang', 'DISABLED'],
  ].map(([name, area, status], i) => ({ id: `CAM-${String(i + 1).padStart(2, '0')}`, name, area, status, enabled: status !== 'DISABLED', endpoint: `rtsp://demo.invalid/stream/${i + 1}`, fps: 5, revision: 1, credentialConfigured: true, reconnects: i === 3 ? 3 : 0, changedAt: ANCHOR }));
  const current = ['OCCUPIED', 'EMPTY', 'OCCUPIED', 'OCCUPIED', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'OCCUPIED', 'EMPTY', 'UNKNOWN', 'UNKNOWN'];
  const workspaces = Array.from({ length: 12 }, (_, i) => ({
    id: `WS-${String(i + 1).padStart(2, '0')}`, name: `Meja ${String.fromCharCode(65 + Math.floor(i / 2))}${String(i % 2 + 1).padStart(2, '0')}`,
    area: cameras[Math.floor(i / 2)].area, cameraId: cameras[Math.floor(i / 2)].id, kind: 'desk', capacity: 1, revision: 1,
    liveState: current[i], count: current[i] === 'OCCUPIED' ? 1 : current[i] === 'EMPTY' ? 0 : null,
    polygon: i % 2 === 0 ? [[.12, .33], [.43, .33], [.43, .78], [.12, .78]] : [[.56, .33], [.88, .33], [.88, .78], [.56, .78]],
    monitorFrom: ANCHOR - 370 * DAY,
  }));
  return { version: 1, clock: ANCHOR, cameras, workspaces, settings: { site: 'Pabrik Nusantara (contoh)', timezone: 'Asia/Jakarta', start: '09:00', end: '17:00', breakStart: '12:00', breakEnd: '13:00', calendarRevision: 1, detailDays: 365, aggregateYears: 3, backupDays: 30 }, events: [
    { id: 'seed-1', time: ANCHOR - 2 * MINUTE, cameraId: 'CAM-04', workspaceId: null, type: 'CAMERA_LOST', message: 'Gudang utara kehilangan koneksi simulasi' },
    { id: 'seed-2', time: ANCHOR - 5 * MINUTE, cameraId: 'CAM-03', workspaceId: 'WS-05', type: 'OBSERVATION_LOST', message: 'Observasi pengemasan tidak tersedia; zona unknown' },
    { id: 'seed-3', time: ANCHOR - 7 * MINUTE, cameraId: 'CAM-01', workspaceId: 'WS-01', type: 'ENTER', message: 'Occupant anonim teramati di Meja A01' },
  ], liveIntervals: [], backups: [], emptyHistory: false, persistence: 'HEALTHY', step: 0 };
}

function generatedDay(key, workspaces, until = Infinity, today = false) {
  if ([0, 6].includes(new Date(atDate(key) + 7 * 3_600_000).getUTCDay())) return [];
  const dayNumber = Math.floor(atDate(key) / DAY);
  const records = [];
  for (const [index, w] of workspaces.entries()) for (const hour of [9, 10, 11, 13, 14, 15, 16]) for (const half of [0, 30]) {
    const start = atDate(key, hour, half), end = Math.min(start + 30 * MINUTE, until);
    if (start >= end || start < w.monitorFrom) continue;
    const pattern = (dayNumber * 7 + index * 11 + hour * 3 + half) % 23;
    let state = pattern < 2 ? 'UNKNOWN' : pattern < 6 ? 'EMPTY' : 'OCCUPIED';
    if (today && end === until) state = w.liveState;
    const count = state === 'UNKNOWN' ? null : state === 'EMPTY' ? 0 : (pattern === 10 && index === 2 ? 2 : 1);
    records.push({ id: `${w.id}-${start}`, workspaceId: w.id, cameraId: w.cameraId, start, end, state, count, revision: 1, reason: state === 'UNKNOWN' ? 'QUALITY_LOW' : 'NONE' });
  }
  return records;
}

const seedWorkspaces = initialState().workspaces;
export const HISTORY = Array.from({ length: 366 }, (_, i) => generatedDay(dateKey(ANCHOR - (366 - i) * DAY), seedWorkspaces)).flat();
export const TODAY = generatedDay(dateKey(ANCHOR), seedWorkspaces, ANCHOR, true);

export function effectiveWorkspace(w, state) {
  const camera = state.cameras.find(c => c.id === w.cameraId);
  if (w.applyStatus === 'PENDING_APPLY') return { ...w, liveState: 'UNKNOWN', count: null, reason: 'PENDING_CONFIRMATION' };
  if (state.persistence !== 'HEALTHY') return { ...w, liveState: 'UNKNOWN', count: null, reason: 'PERSISTENCE_GAP' };
  if (!camera || camera.status !== 'ONLINE') return { ...w, liveState: 'UNKNOWN', count: null, reason: camera?.status === 'DEGRADED' ? 'INFERENCE_TIMEOUT' : camera?.status === 'DISABLED' ? 'DISABLED' : 'CAMERA_OFFLINE' };
  return { ...w, reason: w.liveState === 'UNKNOWN' ? 'PENDING_CONFIRMATION' : 'NONE' };
}
export function eligibleMinute(time, settings) {
  const local = new Date(time + 7 * 3_600_000);
  const weekday = local.getUTCDay();
  const minutes = local.getUTCHours() * 60 + local.getUTCMinutes();
  const convert = value => { const [h, m] = value.split(':').map(Number); return h * 60 + m; };
  return weekday !== 0 && weekday !== 6 && minutes >= convert(settings.start) && minutes < convert(settings.end) && !(minutes >= convert(settings.breakStart) && minutes < convert(settings.breakEnd));
}
export function advanceState(state, minutes = 1) {
  let next = state;
  for (let i = 0; i < minutes; i++) {
    const newClock = next.clock + MINUTE;
    const rows = eligibleMinute(next.clock, next.settings) ? next.workspaces.filter(w => w.monitorFrom <= next.clock).map(w => {
      const observed = effectiveWorkspace(w, next);
      return { id: `${w.id}-${next.clock}`, workspaceId: w.id, cameraId: w.cameraId, start: next.clock, end: newClock, state: observed.liveState, count: observed.count, revision: w.revision, reason: observed.reason };
    }) : [];
    const cameras = next.cameras.map(c => c.status === 'RECONNECTING' && newClock - c.changedAt >= MINUTE ? { ...c, status: c.credentialConfigured ? 'ONLINE' : 'OFFLINE', changedAt: newClock } : c);
    const candidates=next.workspaces.filter(w=>w.applyStatus!=='PENDING_APPLY'&&cameras.find(c=>c.id===w.cameraId)?.status==='ONLINE');
    const target=next.persistence==='HEALTHY'?candidates[(next.step+1)%Math.max(1,candidates.length)]:undefined;
    let events = next.events;
    const workspaces = next.workspaces.map(w => {
      if (!target || w.id !== target.id) return w;
      const liveState = w.liveState === 'OCCUPIED' ? 'EMPTY' : 'OCCUPIED';
      events = [{ id: `event-${newClock}-${w.id}`, time: newClock, cameraId: w.cameraId, workspaceId: w.id, type: liveState === 'OCCUPIED' ? 'ENTER' : 'EXIT', message: `${w.name}: ${liveState === 'OCCUPIED' ? 'occupant anonim masuk' : 'zona teramati kosong'}` }, ...events].slice(0, 100);
      return { ...w, liveState, count: liveState === 'OCCUPIED' ? 1 : 0 };
    });
    next = { ...next, clock: newClock, cameras, workspaces, events, liveIntervals: [...next.liveIntervals, ...rows], step: next.step + 1 };
  }
  return next;
}
export function dataset(state) {
  if (state.emptyHistory) return state.liveIntervals;
  const ids = new Set(state.workspaces.map(w => w.id));
  return [...HISTORY.filter(r => ids.has(r.workspaceId)), ...TODAY.filter(r => ids.has(r.workspaceId)), ...state.liveIntervals];
}
