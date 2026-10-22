export function monitoringState(camera, live, now = Date.now()) {
  const state = live.state;
  const source = camera.id === 'webcam' ? 'WEBCAM_LIVE' : 'RTSP_LIVE';
  const matches = state?.source === source && (source === 'WEBCAM_LIVE' || camera.camera_key === state.camera_key);
  if (!live.active || !matches) return { label: 'Preview saja', tone: 'DISABLED' };
  if (state.preview_only) {
    if (live.error || state.camera_health !== 'ONLINE') return { label:'Preview belum tersambung', tone:'DEGRADED' };
    const calibrated = state.calibrations?.[source]?.camera_key === state.camera_key;
    return { label: calibrated ? 'Siap monitoring' : 'Perlu zona', tone: calibrated ? 'UNKNOWN' : 'DEGRADED' };
  }
  if (live.error || !live.receivedAt || now - live.receivedAt > 4000 || state.camera_health !== 'ONLINE') {
    return { label: 'Bukti terhenti', tone: 'DEGRADED' };
  }
  return state.latest?.recorded ? { label: 'Monitoring aktif', tone: 'ONLINE' } : { label: state.processed>0?'Bukti terhenti':'Menunggu bukti', tone: 'UNKNOWN' };
}
