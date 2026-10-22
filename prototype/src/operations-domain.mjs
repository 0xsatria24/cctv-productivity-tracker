export const REASON_TEXT = {
  CAMERA_OFFLINE: 'Koneksi kamera terputus', FRAME_STALE: 'Frame terbaru belum diterima',
  ENGINE_INTERRUPTED: 'Sesi monitoring terhenti', ENGINE_STOPPED: 'Monitoring dihentikan',
  STARTUP: 'Menunggu observasi awal', PENDING_CONFIRMATION: 'Menunggu konfirmasi zona',
  ZONE_AMBIGUOUS: 'Posisi orang belum dapat dipastikan', INFERENCE_TIMEOUT: 'Analisis melewati batas waktu',
  QUALITY_LOW: 'Kualitas gambar belum mencukupi', PERSISTENCE_GAP: 'Penyimpanan terganggu',
};
export const reasonText = value => REASON_TEXT[value] || (value ? 'Observasi belum dapat dipastikan' : 'Observasi tersedia');
export function localInput(us, timezone = 'Asia/Jakarta') {
  if (us == null) return '';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(us / 1000).map(p => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
}
export function localToUtc(value, timezone = 'Asia/Jakarta') {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) return null;
  const normalized = value.length === 16 ? `${value}:00` : value, wall = Date.parse(`${normalized}Z`);
  if (!Number.isFinite(wall) || new Date(wall).toISOString().slice(0, 19) !== normalized) return null;
  const offsets = new Set([-36, -12, 0, 12, 36].map(h => {
    const at = wall + h * 3600000;
    return Date.parse(`${localInput(at * 1000, timezone)}Z`) - at;
  }));
  const candidates = [...offsets].map(offset => (wall - offset) * 1000).filter(us => localInput(us, timezone) === normalized);
  // Ambiguous or nonexistent DST wall times need an explicit different time.
  return candidates.length === 1 ? candidates[0] : null;
}
function moveDate(date, days) {
  const at = Date.parse(`${date}T00:00:00Z`);
  if (!Number.isFinite(at) || new Date(at).toISOString().slice(0, 10) !== date) throw new Error('Tanggal tidak valid.');
  return new Date(at + days * 86400000).toISOString().slice(0, 10);
}
export function periodRange(kind, date, timezone, from = '07:00', to = '15:00') {
  const next = moveDate(date, 1);
  let start = `${date}T00:00`, end = `${next}T00:00`;
  if (kind === 'week') start = `${moveDate(date, -6)}T00:00`;
  if (kind === 'shift') {
    if (!/^\d{2}:\d{2}$/.test(from) || !/^\d{2}:\d{2}$/.test(to) || from === to) throw new Error('Pilih jam mulai dan selesai shift yang berbeda.');
    start = `${date}T${from}`; end = `${to < from ? next : date}T${to}`;
  }
  const left = localToUtc(start, timezone), right = localToUtc(end, timezone);
  if (left == null || right == null || right <= left) throw new Error('Waktu tidak valid di zona waktu lokasi. Pilih tanggal atau jam lain.');
  return { start: left, end: right };
}
export function currentObservation(live, receivedAt, now = Date.now(), error = '') {
  const latest = live?.latest;
  const fresh = !error && receivedAt && now >= receivedAt && now - receivedAt < 4000 && live?.status === 'RUNNING' && live?.camera_health === 'ONLINE' && latest;
  const zones = fresh && !live.preview_only ? latest.zones || [] : [];
  return { fresh: !!fresh, zones, count: fresh && !live.preview_only ? latest.count : null,
    occupied: zones.filter(z => z.state === 'OCCUPIED').length,
    empty: zones.filter(z => z.state === 'EMPTY').length,
    unknown: zones.filter(z => z.state === 'UNKNOWN').length };
}
export function monitoringText(live, error = '') {
  if (error) return 'Status belum tersedia';
  if (!live) return 'Memuat status monitoring';
  if (['IDLE', 'STOPPED'].includes(live.status)) return 'Monitoring belum aktif';
  if (live.status === 'STARTING') return live.preview_only ? 'Menghubungkan preview' : 'Menyiapkan analisis';
  if (live.status === 'STOPPING') return 'Menyimpan dan menghentikan';
  if (live.status === 'FAILED') return 'Monitoring perlu diperiksa';
  if (live.camera_health !== 'ONLINE') return 'Menunggu koneksi kamera';
  return live.preview_only ? 'Preview aktif' : 'Monitoring aktif';
}
