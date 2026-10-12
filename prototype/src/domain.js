export const ANCHOR = Date.parse('2026-10-12T10:42:00+07:00');
export const DAY = 86_400_000;
export const MINUTE = 60_000;
export const LABELS = { OCCUPIED: 'Terisi', EMPTY: 'Kosong', UNKNOWN: 'Tidak diketahui' };
export const CAMERA_LABELS = { ONLINE: 'Terhubung', DEGRADED: 'Observasi terganggu', OFFLINE: 'Tidak terhubung', RECONNECTING: 'Menyambungkan', DISABLED: 'Nonaktif' };
export const REASONS = { CAMERA_OFFLINE: 'Kamera tidak terhubung', INFERENCE_TIMEOUT: 'Inference tidak tersedia', STARTUP: 'Menunggu observasi', PENDING_CONFIRMATION: 'Menunggu konfirmasi', QUALITY_LOW: 'Kualitas observasi rendah', PERSISTENCE_GAP: 'Penyimpanan terganggu', DISABLED: 'Kamera nonaktif', NONE: 'Observasi valid' };

export function dateKey(ms) { return new Date(ms + 7 * 3_600_000).toISOString().slice(0, 10); }
export function atDate(date, hours = 0, minutes = 0) { return Date.parse(`${date}T${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:00+07:00`); }
export function clock(ms, timezone = 'Asia/Jakarta', withSeconds = false) {
  return new Intl.DateTimeFormat('id-ID', { timeZone: timezone, hour: '2-digit', minute: '2-digit', ...(withSeconds ? { second: '2-digit' } : {}), hourCycle: 'h23' }).format(ms).replaceAll('.', ':');
}
export function dateLabel(ms, options = {}) { return new Intl.DateTimeFormat('id-ID', { timeZone: 'Asia/Jakarta', day: 'numeric', month: 'short', year: 'numeric', ...options }).format(ms); }
export function duration(ms, compact = false) {
  const seconds = Math.floor(ms / 1000), hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds % 3600 / 60);
  return compact ? `${hours}j ${String(minutes).padStart(2, '0')}m` : `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}
export function percent(value) { return value == null ? 'N/A' : `${value.toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`; }
export function summarize(intervals) {
  const total = { occupied: 0, empty: 0, unknown: 0, eligible: 0, countKnown: 0, countIntegral: 0, peak: null, sessions: 0 };
  let previous;
  for (const item of [...intervals].sort((a, b) => a.workspaceId.localeCompare(b.workspaceId) || a.start - b.start)) {
    const span = Math.max(0, item.end - item.start);
    if (!span) continue;
    total.eligible += span;
    total[item.state === 'OCCUPIED' ? 'occupied' : item.state === 'EMPTY' ? 'empty' : 'unknown'] += span;
    if (item.count != null && item.state !== 'UNKNOWN') {
      total.countKnown += span;
      total.countIntegral += span * item.count;
      total.peak = Math.max(total.peak ?? 0, item.count);
    }
    if (item.state === 'OCCUPIED' && !(previous?.workspaceId === item.workspaceId && previous.state === 'OCCUPIED' && previous.end === item.start && previous.revision === item.revision)) total.sessions += 1;
    previous = item;
  }
  total.coverage = total.eligible ? 100 * (total.occupied + total.empty) / total.eligible : null;
  total.utilization = total.occupied + total.empty ? 100 * total.occupied / (total.occupied + total.empty) : null;
  total.countCoverage = total.eligible ? 100 * total.countKnown / total.eligible : null;
  total.averageCount = total.countKnown ? total.countIntegral / total.countKnown : null;
  return total;
}
export function clipIntervals(intervals, start, end, ids) {
  const scope = ids ? new Set(ids) : null;
  return intervals.filter(i => (!scope || scope.has(i.workspaceId)) && i.start < end && i.end > start)
    .map(i => ({ ...i, start: Math.max(start, i.start), end: Math.min(end, i.end) }));
}
export function rangeFor(period, reference = '2026-10-12') {
  let start = atDate(reference), end = start + DAY;
  if (period === 'WEEK') { start -= 6 * DAY; }
  if (period === 'MONTH') { start = atDate(`${reference.slice(0, 7)}-01`); }
  if (period === 'YEAR') { start = atDate(`${reference.slice(0, 4)}-01-01`); }
  return { start: dateKey(start), end: dateKey(end - 1) };
}
export function bucketKey(ms, grain) {
  const date = dateKey(ms);
  if (grain === 'MONTH') return date.slice(0, 7);
  if (grain === 'YEAR') return date.slice(0, 4);
  if (grain === 'WEEK') {
    const weekday = new Date(atDate(date) + 7 * 3_600_000).getUTCDay();
    return dateKey(atDate(date) - ((weekday + 6) % 7) * DAY);
  }
  return date;
}
export function reportRows(intervals, workspaces, grain = 'DAY') {
  const groups = new Map();
  for (const item of intervals) {
    const key = `${item.workspaceId}|${bucketKey(item.start, grain)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [...groups.entries()].map(([key, records]) => {
    const [workspaceId, bucket] = key.split('|');
    return { id: key, workspaceId, name: workspaces.find(w => w.id === workspaceId)?.name ?? workspaceId, bucket, ...summarize(records) };
  }).sort((a, b) => b.bucket.localeCompare(a.bucket) || a.name.localeCompare(b.name));
}
export function trendRows(intervals, grain = 'DAY') {
  const groups = new Map();
  for (const item of intervals) { const key = bucketKey(item.start, grain); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(item); }
  return [...groups.entries()].map(([bucket, records]) => ({ bucket, ...summarize(records) })).sort((a, b) => a.bucket.localeCompare(b.bucket));
}
export function chartRows(intervals, grain, start, end) {
  if(end<=start)return [];
  if(grain==='DAY'&&dateKey(start)===dateKey(end-1)) {
    const day=dateKey(start), rows=[];
    for(let hour=0;hour<24;hour++) {
      const from=atDate(day,hour),to=from+3_600_000;
      if(from>=end||to<=start)continue;
      const bucket=clipIntervals(intervals,Math.max(from,start),Math.min(to,end));
      if(bucket.length)rows.push({bucket:`${String(hour).padStart(2,'0')}:00`,...summarize(bucket)});
    }
    return rows;
  }
  const values=new Map(trendRows(intervals,grain).map(row=>[row.bucket,row]));
  const keys=new Set();for(let time=atDate(dateKey(start));time<end;time+=DAY)keys.add(bucketKey(time,grain));
  return [...keys].sort().map(bucket=>values.get(bucket)||{bucket,...summarize([])});
}
export function validPolygon(points) {
  if (points.length < 3 || points.length > 64 || points.some(([x, y]) => !Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x > 1 || y > 1)) return false;
  const area = Math.abs(points.reduce((sum, [x, y], i) => { const next = points[(i + 1) % points.length]; return sum + x * next[1] - y * next[0]; }, 0)) / 2;
  if (area < .0001) return false;
  const cross = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  const on = (a, b, p) => Math.abs(cross(a, b, p)) < 1e-9 && p[0] >= Math.min(a[0], b[0]) - 1e-9 && p[0] <= Math.max(a[0], b[0]) + 1e-9 && p[1] >= Math.min(a[1], b[1]) - 1e-9 && p[1] <= Math.max(a[1], b[1]) + 1e-9;
  for (let i = 0; i < points.length; i++) for (let j = i + 1; j < points.length; j++) {
    if (j === i + 1 || (i === 0 && j === points.length - 1)) continue;
    const a = points[i], b = points[(i + 1) % points.length], c = points[j], d = points[(j + 1) % points.length];
    if ((cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0) || on(a, b, c) || on(a, b, d) || on(c, d, a) || on(c, d, b)) return false;
  }
  return true;
}
export function csvCell(value) { const text = String(value ?? ''); return `"${(/^[=+@\-\t\r]/.test(text) ? "'" : '') + text.replaceAll('"', '""')}"`; }
export function makeCsv(rows, metadata) {
  const headers = ['periode', 'workstation', 'terisi_detik', 'kosong_detik', 'unknown_detik', 'utilization_pct', 'coverage_pct', 'sesi'];
  const values = rows.map(r => [r.bucket, r.name, r.occupied / 1000, r.empty / 1000, r.unknown / 1000, r.utilization?.toFixed(4) ?? 'N/A', r.coverage?.toFixed(4) ?? 'N/A', r.sessions]);
  return '\uFEFF' + [['SUMBER', 'DATA SIMULASI, BUKAN DATA CCTV'], ...Object.entries(metadata), headers, ...values].map(row => row.map(csvCell).join(',')).join('\r\n');
}
