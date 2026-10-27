import { useCallback, useEffect, useRef, useState } from 'react';
import { TrackCaption, PredictedTrack } from './track-caption';
import { Maximize, Play, RefreshCw, Settings, Square, Video } from 'lucide-react';
import { Button, Field, Modal, Panel, Status } from './components';

const PRESETS = {
  '480': { width: 640, height: 480 },
  '720': { width: 1280, height: 720 },
  '1080': { width: 1920, height: 1080 },
};
const LABELS = {
  IDLE: 'Belum dimulai', REQUESTING: 'Menunggu izin kamera', CONNECTING: 'Menunggu frame',
  LIVE: 'Live', MUTED: 'Frame tertunda', STALLED: 'Frame terhenti',
  CANCELLING: 'Menunggu dialog izin selesai', ERROR: 'Tidak terhubung',
};
const COLORS = { LIVE: 'ONLINE', REQUESTING: 'RECONNECTING', CONNECTING: 'RECONNECTING',
  MUTED: 'DEGRADED', STALLED: 'DEGRADED', ERROR: 'OFFLINE' };

function errorMessage(error) {
  switch (error?.name) {
    case 'NotAllowedError': case 'SecurityError':
      return 'Akses kamera ditolak. Izinkan kamera untuk situs ini di browser dan pengaturan privasi Windows, lalu coba lagi. Jika preview Codex membatasi izin, buka URL yang sama langsung di Chrome atau Edge.';
    case 'NotFoundError': return 'Webcam tidak ditemukan. Hubungkan atau aktifkan kamera, lalu perbarui daftar perangkat.';
    case 'NotReadableError': case 'AbortError':
      return 'Webcam tidak dapat dibaca. Tutup aplikasi lain yang memakai kamera, periksa perangkat, lalu coba lagi.';
    case 'OverconstrainedError': return 'Perangkat yang dipilih tidak tersedia atau tidak mendukung pengaturan ini. Perbarui perangkat atau pilih resolusi lain.';
    default: return 'Preview webcam gagal. Periksa izin dan perangkat, lalu coba lagi di Chrome atau Edge.';
  }
}

/** App-scoped capture; sampled JPEGs are sent only to the local Python engine. */
export function useWebcamPreview() {
  const supported = window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;
  const [devices, setDevices] = useState([]), [device, setDevice] = useState('');
  const [resolution, setResolution] = useState('720'), [mirror, setMirror] = useState(true), [fit, setFit] = useState('contain');
  const [state, setState] = useState({ status: 'IDLE', stream: null, error: '', label: '', width: 0, height: 0, fps: null });
  const [deviceNotice, setDeviceNotice] = useState(''), [refreshing, setRefreshing] = useState(false);
  const mounted = useRef(false), streamRef = useRef(null);
  const generation = useRef(0), pending = useRef(false), frameAt = useRef(0), stateRef = useRef(state);
  stateRef.current = state;

  const release = useCallback(() => {
    const current = streamRef.current;
    streamRef.current = null;
    current?.getTracks().forEach(track => track.stop());
    frameAt.current = 0;
  }, []);
  const stop = useCallback(() => {
    ++generation.current;
    release();
    if (mounted.current) setState({ status: pending.current ? 'CANCELLING' : 'IDLE', stream: null, error: '', label: '', width: 0, height: 0, fps: null });
  }, [release]);
  const fail = useCallback((message, expectedStream) => {
    if (expectedStream && streamRef.current !== expectedStream) return;
    ++generation.current;
    release();
    if (mounted.current) setState({ status: 'ERROR', stream: null, error: message, label: '', width: 0, height: 0, fps: null });
  }, [release]);

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    if (mounted.current) setRefreshing(true);
    try {
      const list = (await navigator.mediaDevices.enumerateDevices()).filter(item => item.kind === 'videoinput');
      if (!mounted.current) return;
      setDevices(list);
      setDeviceNotice(list.length ? '' : 'Perangkat belum terdaftar. Klik Mulai webcam untuk meminta izin dan membaca perangkat.');
      if (!streamRef.current) setDevice(current => list.some(item => item.deviceId === current) ? current : '');
    } catch {
      if (mounted.current) setDeviceNotice('Daftar perangkat belum dapat dibaca. Periksa izin kamera di browser.');
    } finally { if (mounted.current) setRefreshing(false); }
  }, []);

  useEffect(() => {
    mounted.current = true;
    refreshDevices();
    navigator.mediaDevices?.addEventListener?.('devicechange', refreshDevices);
    window.addEventListener('pagehide', stop);
    return () => {
      mounted.current = false;
      ++generation.current;
      release();
      navigator.mediaDevices?.removeEventListener?.('devicechange', refreshDevices);
      window.removeEventListener('pagehide', stop);
    };
  }, [refreshDevices, release, stop]);
  useEffect(() => {
    if (!state.stream) return;
    const timer = setInterval(() => {
      if (streamRef.current && frameAt.current && performance.now() - frameAt.current > 3500) {
        setState(current => current.stream ? { ...current, status: 'STALLED', fps: null } : current);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [state.stream]);

  async function start() {
    if (pending.current || streamRef.current) return;
    if (!supported) { fail('Browser ini belum mendukung akses webcam. Buka dashboard langsung melalui http://127.0.0.1:8765/ di Chrome atau Edge.'); return; }
    const requestGeneration = ++generation.current;
    pending.current = true;
    setState(current => ({ ...current, status: 'REQUESTING', error: '' }));
    try {
      const source = await navigator.mediaDevices.getUserMedia({ audio: false, video: {
        ...(device ? { deviceId: { exact: device } } : {}),
        width: { ideal: PRESETS[resolution].width }, height: { ideal: PRESETS[resolution].height }, frameRate: { ideal: 30, max: 30 },
      } });
      if (!mounted.current || generation.current !== requestGeneration) {
        source.getTracks().forEach(track => track.stop());
        return;
      }
      const track = source.getVideoTracks()[0];
      if (!track || track.readyState !== 'live') { source.getTracks().forEach(item => item.stop()); throw new Error('No live video track'); }
      streamRef.current = source;
      frameAt.current = performance.now();
      track.addEventListener('ended', () => fail('Koneksi webcam terputus atau izin dicabut. Periksa kamera lalu mulai kembali.', source), { once: true });
      track.addEventListener('mute', () => { if (streamRef.current === source && mounted.current) setState(current => ({ ...current, status: 'MUTED', fps: null })); });
      track.addEventListener('unmute', () => { if (streamRef.current === source && mounted.current) { frameAt.current = performance.now(); setState(current => ({ ...current, status: 'CONNECTING', fps: null })); } });
      const actual = track.getSettings();
      setState({ status: 'CONNECTING', stream: source, error: '', label: track.label || 'Webcam lokal', width: actual.width || 0, height: actual.height || 0, fps: null });
      await refreshDevices();
    } catch (error) {
      if (mounted.current && generation.current === requestGeneration) fail(errorMessage(error));
    } finally {
      pending.current = false;
      if (mounted.current && generation.current !== requestGeneration) setState(current => current.status === 'CANCELLING' ? { ...current, status: 'IDLE' } : current);
    }
  }

  const frame = useCallback((source, width, height, fps) => {
    if (streamRef.current !== source || !mounted.current) return;
    frameAt.current = performance.now();
    if (source.getVideoTracks()[0]?.muted) return;
    if (stateRef.current.status !== 'LIVE' || fps !== undefined) setState(current => ({ ...current, status: 'LIVE', width, height, ...(fps !== undefined ? { fps } : {}) }));
  }, []);

  return { ...state, supported, devices, device, setDevice, resolution, setResolution, mirror, setMirror,
    fit, setFit, start, stop, fail, frame, refreshing, refreshDevices, deviceNotice };
}

function WebcamVideo({ webcam }) {
  const video = useRef(null), container = useRef(null), [notice, setNotice] = useState('');
  const [fullscreen, setFullscreen] = useState(false);
  const [analysis, setAnalysis] = useState(null), [engineError, setEngineError] = useState('');
  const [fresh, setFresh] = useState(false);
  useEffect(() => {
    setAnalysis(null); setEngineError(''); setFresh(false);
    if (!webcam.stream) return;
    let cancelled = false, timer, lastTime = -1, received = 0, sequence = 0;
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    const abort = new AbortController();
    async function sample() {
      const element = video.current;
      if (cancelled) return;
      if (webcam.inferencePaused || webcam.engineStarting || !element || element.readyState < 2 || element.currentTime === lastTime || webcam.stream.getVideoTracks()[0]?.muted) {
        timer = setTimeout(sample, 500); return;
      }
      lastTime = element.currentTime;
      const scale = Math.min(1, 640 / Math.max(element.videoWidth, element.videoHeight));
      canvas.width = Math.max(1, Math.round(element.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(element.videoHeight * scale));
      const request = new AbortController();
      const stopRequest = () => request.abort();
      abort.signal.addEventListener('abort', stopRequest, { once: true });
      const timeout = setTimeout(stopRequest, 8000);
      const sentAt = performance.now();
      try {
        context.drawImage(element, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.75));
        if (cancelled) return;
        if (!blob) throw new Error('Frame webcam belum dapat dibaca');
        const response = await fetch('/pilot/v1/webcam/frame', { method: 'POST', headers: { 'Content-Type': 'image/jpeg', ...(webcam.liveSession ? { 'X-Live-Session': webcam.liveSession, 'X-Frame-Sequence': String(++sequence) } : {}) }, body: blob, signal: request.signal });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Engine deteksi tidak tersedia');
        if (!cancelled) { received = performance.now(); setAnalysis({...data, roundtrip_ms: Math.round(received - sentAt)}); setEngineError(''); setFresh(true); }
      } catch (error) {
        if (!cancelled) { setFresh(false); setAnalysis(null); setEngineError(error.name === 'AbortError' ? 'Engine melewati batas waktu; mencoba kembali' : error.message); }
      } finally {
        clearTimeout(timeout); abort.signal.removeEventListener('abort', stopRequest);
        if (!cancelled) timer = setTimeout(sample, Math.max(0, 200 - (performance.now() - sentAt)));
      }
    }
    sample();
    const stale = setInterval(() => { if (received && performance.now() - received > 2500) setFresh(false); }, 500);
    return () => { cancelled = true; abort.abort(); clearTimeout(timer); clearInterval(stale); };
  }, [webcam.stream,webcam.liveSession,webcam.engineStarting,webcam.inferencePaused]);
  const showDetections = webcam.status === 'LIVE' && fresh && analysis;
  useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === container.current);
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, []);
  useEffect(() => {
    if (!webcam.stream && document.fullscreenElement === container.current) document.exitFullscreen().catch(() => {});
  }, [webcam.stream]);
  useEffect(() => {
    const element = video.current, source = webcam.stream;
    if (!element || !source) return;
    let cancelled = false, callback, started = performance.now(), count = 0, previousTime = -1;
    const supportsFrameCallback = !!element.requestVideoFrameCallback;
    element.srcObject = source;
    function tick(now) {
      if (cancelled) return;
      if (supportsFrameCallback || (element.readyState >= 2 && element.currentTime !== previousTime)) {
        previousTime = element.currentTime;
        count++;
        const elapsed = now - started;
        const fps = elapsed >= 1000 ? Math.round(count * 1000 / elapsed) : undefined;
        webcam.frame(source, element.videoWidth, element.videoHeight, fps);
        if (elapsed >= 1000) { count = 0; started = now; }
      }
      callback = supportsFrameCallback ? element.requestVideoFrameCallback(tick) : requestAnimationFrame(tick);
    }
    callback = supportsFrameCallback ? element.requestVideoFrameCallback(tick) : requestAnimationFrame(tick);
    element.play().catch(error => { if (!cancelled && error.name !== 'AbortError') webcam.fail('Pemutaran video diblokir. Hentikan lalu mulai webcam kembali dari tombol.', source); });
    return () => {
      cancelled = true;
      if (supportsFrameCallback) element.cancelVideoFrameCallback(callback); else cancelAnimationFrame(callback);
      element.pause(); element.srcObject = null;
    };
  }, [webcam.stream, webcam.frame, webcam.fail]);

  return <><div className="webcam-preview" ref={container} data-testid="webcam-preview">
    {webcam.stream ? <video ref={video} autoPlay muted playsInline aria-label="Preview webcam lokal" style={{ objectFit: webcam.fit, transform: webcam.mirror ? 'scaleX(-1)' : undefined }} />
      : <div className="webcam-placeholder"><Video size={28} aria-hidden="true"/><h3>{webcam.status === 'REQUESTING' ? 'Izinkan kamera di browser' : 'Webcam lokal'}</h3><p>{webcam.status === 'CANCELLING' ? 'Tutup atau selesaikan dialog izin. Jika akses diberikan setelah pembatalan, kameranya langsung dihentikan.' : 'Pilih perangkat, lalu klik Mulai webcam. Tidak ada gambar simulasi pada preview ini.'}</p></div>}
    {showDetections && webcam.showDetections !== false && <svg className="webcam-detections" aria-label="Bounding box deteksi orang" viewBox={`0 0 ${analysis.width} ${analysis.height}`} preserveAspectRatio={webcam.fit === 'cover' ? 'xMidYMid slice' : 'xMidYMid meet'}>{analysis.detections.map((d, i) => {
      const box=d.display_box || d.box;
      const x = (webcam.mirror ? 1 - box[2] : box[0]) * analysis.width, y = box[1] * analysis.height;
      const width = (box[2] - box[0]) * analysis.width, height = (box[3] - box[1]) * analysis.height;
      return <g key={d.track_id || i}><rect x={x} y={y} width={width} height={height} className="person-box"/><TrackCaption row={d} width={analysis.width} height={analysis.height} mirror={webcam.mirror}/></g>;
    })}{analysis.display_predictions?.map(row=><PredictedTrack key={row.track_id} row={row} width={analysis.width} height={analysis.height} mirror={webcam.mirror}/>)}</svg>}
    {webcam.stream && webcam.calibration && webcam.showZones !== false && <svg className="webcam-detections" viewBox={`0 0 ${webcam.width || 640} ${webcam.height || 480}`} preserveAspectRatio={webcam.fit === 'cover' ? 'xMidYMid slice' : 'xMidYMid meet'} aria-label="Zona kalibrasi webcam">{webcam.calibration.zones.map(zone => <polygon key={zone.id} points={zone.polygon.map(([x, y]) => `${(webcam.mirror ? 1 - x : x) * (webcam.width || 640)},${y * (webcam.height || 480)}`).join(' ')} className="zone-overlay"/>)}</svg>}
    {webcam.stream && <div className="webcam-video-tools"><span>{webcam.status === 'LIVE' ? 'WEBCAM LIVE' : LABELS[webcam.status]}</span><div className="inline-controls"><Button icon={Square} aria-label="Hentikan webcam dari preview" onClick={webcam.stop}>Hentikan</Button>{document.fullscreenEnabled && <Button icon={Maximize} aria-label={fullscreen ? 'Keluar layar penuh webcam' : 'Layar penuh webcam'} onClick={() => (fullscreen ? document.exitFullscreen() : container.current.requestFullscreen()).catch(() => setNotice('Layar penuh tidak tersedia dalam browser ini.'))}>{fullscreen ? 'Keluar layar penuh' : 'Layar penuh'}</Button>}</div></div>}
    {notice && <p className="webcam-fullscreen-notice" role="status">{notice}</p>}
  </div>
    <div className="webcam-engine-status" data-testid="webcam-engine-status" role="status">
      <Status value={showDetections ? 'ONLINE' : engineError ? 'OFFLINE' : 'DISABLED'} label={!webcam.stream ? 'Analisis menunggu kamera' : webcam.inferencePaused ? 'Preview saja; analisis memakai kamera RTSP' : engineError ? 'Analisis belum terhubung' : showDetections ? 'Analisis orang aktif' : 'Menunggu hasil frame baru'}/>
      {showDetections && <><strong>{analysis.count} orang terdeteksi</strong><span>{analysis.model} · {analysis.inference_ms} ms inferensi · {analysis.roundtrip_ms} ms respons</span></>}
      {showDetections && <span>{analysis.recorded ? 'Durasi zona tersimpan' : 'Preview deteksi; monitoring belum dimulai'}</span>}
      {engineError && <span className="error-text">{engineError}</span>}
    </div>
  </>;
}

export function WebcamPanel({ webcam, wall = false, onFocus }) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const active = !!webcam.stream, waiting = ['REQUESTING', 'CANCELLING'].includes(webcam.status);
  const controls = <>
    <div className="webcam-controls">
      <Field label="Perangkat webcam" hint="Label perangkat muncul setelah izin diberikan."><select value={webcam.device} disabled={active || waiting} onChange={event => webcam.setDevice(event.target.value)}><option value="">Kamera default sistem</option>{webcam.devices.filter(item => item.deviceId).map((item, index) => <option key={item.deviceId} value={item.deviceId}>{item.label || `Webcam ${index + 1}`}</option>)}</select></Field>
      <Field label="Target resolusi" hint="Resolusi aktual mengikuti kemampuan webcam."><select value={webcam.resolution} disabled={active || waiting} onChange={event => webcam.setResolution(event.target.value)}><option value="480">640 × 480</option><option value="720">1280 × 720</option><option value="1080">1920 × 1080</option></select></Field>
      <div className="webcam-actions"><Button icon={RefreshCw} disabled={!webcam.supported || webcam.refreshing} onClick={webcam.refreshDevices}>Perbarui perangkat</Button>
      {!wall && <><Button icon={Play} variant="primary" disabled={!webcam.supported || active || waiting || webcam.captureBlocked} onClick={webcam.start}>Mulai webcam</Button>
      <Button icon={Square} disabled={!active && webcam.status !== 'REQUESTING'} onClick={webcam.stop}>Hentikan webcam</Button></>}</div>
    </div>
    <div className="webcam-preview-controls"><label className="check-control"><input type="checkbox" checked={webcam.mirror} onChange={event => webcam.setMirror(event.target.checked)}/>Cerminkan preview</label><Field label="Tampilan video"><select value={webcam.fit} onChange={event => webcam.setFit(event.target.value)}><option value="contain">Seluruh frame</option><option value="cover">Isi area preview</option></select></Field></div>
  </>;
  return <Panel title="Webcam lokal" caption={wall ? undefined : 'Webcam dan deteksi orang lokal. Sesi tetap aktif saat berpindah halaman.'} className={`webcam-panel ${wall ? 'webcam-wall-panel' : ''}`} action={<div className="inline-controls"><Status value={COLORS[webcam.status] || 'DISABLED'} label={LABELS[webcam.status]}/>{wall && <><Button icon={Settings} aria-label="Pengaturan webcam" onClick={() => setSettingsOpen(true)}/><Button icon={Maximize} aria-label="Fokus Webcam lokal" onClick={onFocus}/></>}</div>}>
    {!wall && controls}
    {wall && <div className="webcam-wall-actions">{!active && <Button icon={Play} variant="primary" disabled={!webcam.supported || waiting || webcam.captureBlocked} onClick={webcam.start}>Mulai webcam</Button>}{(active || waiting) && <Button icon={Square} disabled={webcam.status === 'CANCELLING'} onClick={webcam.stop}>Hentikan webcam</Button>}</div>}
    {!webcam.supported && <p className="webcam-message error-text" role="alert">Akses webcam tidak tersedia di browser ini. Buka dashboard langsung di Chrome atau Edge pada http://127.0.0.1:8765/.</p>}
    {webcam.error && <p className="webcam-message error-text" role="alert">{webcam.error}</p>}
    {webcam.captureBlocked && <p className="webcam-message caption">Sesi RTSP sedang aktif. Hentikan pencatatan RTSP sebelum memulai webcam.</p>}
    {webcam.deviceNotice && <p className="webcam-message caption">{webcam.deviceNotice}</p>}
    <WebcamVideo webcam={webcam}/>
    <div className="webcam-preview-controls webcam-frame-status"><span data-testid="webcam-status" role="status">{LABELS[webcam.status]} · {webcam.width && webcam.height ? `${webcam.width} × ${webcam.height}` : 'Resolusi N/A'} · {webcam.fps == null ? 'FPS N/A' : `${webcam.fps} FPS preview`}</span></div>
    {!wall && <p className="engine-explanation">Detektor orang dan ByteTrack berjalan di Python lokal. Simpan kalibrasi lalu klik Mulai pencatatan live untuk merekam durasi zona ke SQLite. Frame terlambat atau kamera terputus menjadi UNKNOWN.</p>}
    {settingsOpen && <Modal title="Pengaturan webcam" description="Perangkat dan resolusi dapat diubah setelah webcam dihentikan." onClose={() => setSettingsOpen(false)}>{controls}<div className="modal-actions"><Button onClick={() => setSettingsOpen(false)}>Selesai</Button></div></Modal>}
  </Panel>;
}
