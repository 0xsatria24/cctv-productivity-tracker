import { useEffect, useRef, useState } from 'react';
import { Button, Panel, Status } from './components';
import { CalibrationDialog } from './live-engine';
import { engineRequest } from './engine-client';

export function ManagedCameraControls({ camera, engine, areaRequest=0 }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [calibration, setCalibration] = useState(null);
  const [autoResume, setAutoResume] = useState(camera.auto_resume || false);
  const recoveryPending = useRef(false);
  useEffect(() => { if (!recoveryPending.current) setAutoResume(camera.auto_resume || false); }, [camera.id, camera.auto_resume]);
  async function changeRecovery(enabled) {
    recoveryPending.current = true;
    const previous = autoResume;
    setAutoResume(enabled);
    try { await action('recovery', { auto_resume: enabled }); }
    catch { setAutoResume(previous); }
    finally { recoveryPending.current = false; }
  }
  const active = ['STARTING', 'RUNNING', 'STOPPING'].includes(camera.engine?.status);
  const profile = camera.engine?.calibrations?.RTSP_LIVE;
  useEffect(() => {
    if (!areaRequest) return;
    calibrate();
  }, [areaRequest]);
  async function action(path, body) {
    setBusy(true); setError('');
    try {
      const result = await engineRequest(`camera-wall/cameras/${camera.id}/${path}`, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) });
      engine.reload(); return result;
    } catch (failure) { setError(failure.message); throw failure; }
    finally { setBusy(false); }
  }
  async function calibrate() {
    setBusy(true); setError('');
    try {
      if (active) {
        await action('stop');
        setBusy(true);
        const deadline = Date.now() + 10000;
        while (true) {
          const registry = await engineRequest('camera-wall');
          const current = registry.cameras.find(row => row.id === camera.id);
          if (!current) throw new Error('Kamera tidak lagi tersedia.');
          if (!['STARTING', 'RUNNING', 'STOPPING'].includes(current.engine?.status)) break;
          if (Date.now() >= deadline) throw new Error('Kamera masih berhenti. Coba Atur area lagi setelah sesi selesai.');
          await new Promise(resolve => setTimeout(resolve, 200));
        }
      }
      const response = await fetch(`/pilot/v1/camera-wall/cameras/${camera.id}/frame.jpg`, { cache: 'no-store', signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error('Tampilkan kamera pada grid dan tunggu frame baru sebelum kalibrasi.');
      const blob = await response.blob(), bitmap = await createImageBitmap(blob);
      const width = bitmap.width, height = bitmap.height; bitmap.close();
      const frame = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob); });
      setCalibration({ frame, width, height, camera_key: camera.camera_key, source: 'RTSP_LIVE', profile });
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  return <Panel title={`Monitoring ${camera.name}`} caption="Kalibrasi dan histori tersimpan untuk kamera ini. Kamera lain dapat dianalisis bersamaan.">
    <div className="inline-controls"><Status value={camera.health} label={active ? 'Analisis kamera aktif' : profile ? 'Zona tersimpan' : 'Kalibrasi diperlukan'}/>
      <Button disabled={busy || camera.health !== 'ONLINE'} onClick={calibrate}>Atur zona kamera</Button>
      <Button variant="primary" disabled={busy || active || !profile} onClick={() => action('start').then(() => engine.toast('Analisis kamera dimulai. Menunggu observasi zona.')).catch(() => {})}>Mulai analisis kamera</Button>
      <Button disabled={busy || !active || camera.engine?.status === 'STOPPING'} onClick={() => action('stop').then(() => engine.toast('Penghentian kamera diminta. Tunggu status berhenti.')).catch(() => {})}>Hentikan analisis kamera</Button>
      <Button onClick={() => { engine.setDataset('live'); engine.setCameraId(camera.id); window.location.hash = '/reports'; }}>Laporan kamera ini</Button>
    </div>
    <label className="check-control section-gap"><input type="checkbox" checked={autoResume} disabled={busy} onChange={event => changeRecovery(event.target.checked)}/>Pulihkan otomatis setelah gangguan atau aplikasi dimulai ulang</label>
    <p className="caption">Kamera yang dihentikan manual tetap berhenti. Pemulihan otomatis mencoba maksimal lima kali saat engine gagal. Rekaman video diatur terpisah di Pengaturan.</p>
    {camera.recovery_exhausted && <p role="alert">Pemulihan otomatis dihentikan setelah lima percobaan. Periksa perangkat, model, dan disk, lalu mulai analisis kembali.</p>}
    {(error || camera.engine?.error) && <p role="alert" className="error-text">{error || camera.engine.error}</p>}
    {camera.engine?.latest?.zones && <div className="live-zone-states">{camera.engine.latest.zones.map(zone => <div key={zone.id}><strong>{zone.name}</strong><Status value={zone.state}/><span>{zone.count == null ? 'Jumlah belum tersedia' : `${zone.count} orang teramati`}</span></div>)}</div>}
    {calibration && <CalibrationDialog value={calibration} live={{ action, busy, active }} onClose={() => setCalibration(null)} onSaved={() => { setCalibration(null); engine.toast('Kalibrasi kamera disimpan.'); }}/>} 
  </Panel>;
}
