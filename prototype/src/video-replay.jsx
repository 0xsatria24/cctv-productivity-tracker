import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, FileVideo, Maximize, Pause, Play, RotateCcw, Trash2 } from 'lucide-react';
import { Button, Field, Panel } from './components';
import './video-replay.css';
import { recentReplaySessions, replayCaptureSize, replayDisplayPacket, storedReplayCalibration } from './replay-domain';
import { ReplayCalibration } from './replay-calibration';

const LIMIT = 16;
const time = value => {
  const seconds = Math.max(0, Math.floor(Number.isFinite(value) ? value : 0));
  return `${Math.floor(seconds / 3600).toString().padStart(2,'0')}:${Math.floor(seconds / 60 % 60).toString().padStart(2,'0')}:${(seconds % 60).toString().padStart(2,'0')}`;
};

/** App-scoped local files. Object URLs are released on removal/unmount. */
export function VideoReplayWorkspace({ visible = true, engineAvailable = false }) {
  const [connected,setConnected]=useState(false);
  const [reidMode,setReidMode]=useState('off');
  useEffect(()=>{
    const abort=new AbortController();let timer;
    async function check() {
      try {
        if(import.meta.env.DEV) {
          const session=await fetch('/engine-session',{credentials:'same-origin',signal:AbortSignal.any([abort.signal,AbortSignal.timeout(3000)])});
          if(!session.ok)throw new Error('Engine unavailable');
        } else if(!engineAvailable) {setConnected(false);return;}
        const response=await fetch('/pilot/v1/replay/status',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.any([abort.signal,AbortSignal.timeout(3000)])});
        const packet=response.ok?await response.json():null;
        if(!abort.signal.aborted){setConnected(Boolean(packet?.available));setReidMode(packet?.reid?.mode || 'off');}
      } catch {if(!abort.signal.aborted)setConnected(false);}
      finally {if(!abort.signal.aborted)timer=setTimeout(check,5000);}
    }
    check();return()=>{abort.abort();clearTimeout(timer);};
  },[engineAvailable]);
  const [files, setFiles] = useState([]), [notice, setNotice] = useState('');
  const [layout, setLayout] = useState(4), [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(files.length/layout));
  useEffect(() => setPage(current => Math.min(current, pages-1)), [pages]);
  const input = useRef(null), owned = useRef(new Map());
  useEffect(() => () => { owned.current.forEach(file => URL.revokeObjectURL(file.url)); owned.current.clear(); }, []);
  function add(selected) {
    let rejected = 0, duplicates = 0;
    const additions = [];
    for (const file of selected) {
      const key = JSON.stringify([file.name, file.size, file.lastModified]);
      if (!file.size || !(/\.(mp4|webm|mov|m4v|ogv|ogg|avi|mkv)$/i.test(file.name) || file.type.startsWith('video/'))) { rejected++; continue; }
      if (owned.current.has(key)) { duplicates++; continue; }
      if (owned.current.size >= LIMIT) { rejected++; continue; }
      const entry = { id: crypto.randomUUID(), key, name: file.name, size: file.size, url: URL.createObjectURL(file) };
      owned.current.set(key, entry); additions.push(entry);
    }
    setFiles(current => [...current, ...additions]);
    if (additions.length) setPage(Math.floor((owned.current.size-additions.length)/layout));
    setNotice(`${additions.length} video ditambahkan.${duplicates ? ` ${duplicates} file sudah ada.` : ''}${rejected ? ` ${rejected} file ditolak. Pilih video tidak kosong, maksimal ${LIMIT} sumber.` : ''}`);
    if (input.current) input.current.value = '';
  }
  function remove(file) {
    owned.current.delete(file.key);
    setFiles(current => current.filter(item => item.id !== file.id));
    URL.revokeObjectURL(file.url);
    setNotice(`${file.name} dikeluarkan dari replay.`);
  }
  return <section hidden={!visible} className="video-replay-workspace" aria-label="Video replay lokal">
    <Panel title="Video replay" caption="Pilih rekaman dari komputer. File tetap lokal dan tidak diunggah sebagai rekaman kamera live.">
      <p role="status" className="caption">{connected?`Engine replay terhubung. ReID ${reidMode === 'active' ? 'aktif (eksperimental); recovery sesi memakai bukti visual.' : reidMode === 'shadow' ? 'shadow tersedia; hanya mengukur usulan kecocokan.' : 'nonaktif pada engine ini.'}`:'Engine replay belum terhubung. Jalankan engine lokal aplikasi.'}</p>
      <div className="replay-body">
      <div className="replay-toolbar">
        <Button icon={FileVideo} variant="primary" onClick={() => input.current?.click()}>Masukkan video replay</Button>
        <input ref={input} type="file" multiple accept="video/*,.mp4,.webm,.mov,.m4v,.avi,.mkv" aria-label="Pilih file video replay" className="replay-file-input" onChange={event => add(Array.from(event.target.files || []))}/>
        <span>{files.length} / {LIMIT} video</span>
        {!!files.length && <Field label="Layout video replay"><select value={layout} onChange={e => { setLayout(Number(e.target.value)); setPage(0); }}>{[1,4,9,16].map(n => <option key={n} value={n}>{n} tampilan</option>)}</select></Field>}
      </div>
      <p className="caption">MP4 H.264 atau WebM disarankan. Dukungan AVI, MKV, dan MOV bergantung codec browser. {connected ? 'Deteksi preview memakai engine lokal; hasilnya tidak masuk laporan durasi atau auto-save.' : 'Mode preview lokal. Deteksi memerlukan dashboard Python yang terhubung.'}</p>
      {notice && <p role="status" className="caption">{notice}</p>}
      {!!files.length && <><div className="replay-grid" data-layout={layout}>{files.map((file, index) => <ReplayTile key={file.id} file={file} shown={visible && Math.floor(index/layout) === page} engineAvailable={connected} onRemove={() => remove(file)}/>)}</div><div className="replay-pagination"><span>Halaman {page+1} / {pages}</span><Button icon={ChevronLeft} aria-label="Halaman replay sebelumnya" disabled={page === 0} onClick={() => setPage(current => current-1)}/><Button icon={ChevronRight} aria-label="Halaman replay berikutnya" disabled={page >= pages-1} onClick={() => setPage(current => current+1)}/></div></>}
      </div>
    </Panel>
  </section>;
}

function ReplayTile({ file, shown, engineAvailable, onRemove }) {
  const video = useRef(null), tile = useRef(null), epoch = useRef(0);
  const timeline = useRef(0), sequence = useRef(0), lastMediaTime = useRef(null);
  const [playing, setPlaying] = useState(false), [position, setPosition] = useState(0), [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1), [loop, setLoop] = useState(false), [error, setError] = useState('');
  const [analysisEnabled, setAnalysisEnabled] = useState(false), [analysis, setAnalysis] = useState(null), [engineError, setEngineError] = useState('');
  const [sessions, setSessions] = useState([]);
  const [workstations,setWorkstations]=useState([]), [calibrationImage,setCalibrationImage]=useState(null);
  const lastWorkstationEvidence=useRef(null);
  const [calibration,setCalibration]=useState(()=>{
    try {const saved=storedReplayCalibration(JSON.parse(localStorage.getItem(`replay-zones-v1:${file.key}`)));if(saved)return saved;} catch { /* Storage can be unavailable in private sessions. */ }
    return {zones:[],association:'bbox_overlap'};
  });
  const calibrationRevision=useRef(0);
  const [calibrated,setCalibrated]=useState(false), [calibrationNotice,setCalibrationNotice]=useState('');
  const [dimensions, setDimensions] = useState({ width:16, height:9 });
  const [frameSize, setFrameSize] = useState({width:640,height:360});
  const ready = duration > 0 && !error;
  const enabled = engineAvailable && analysisEnabled && shown;
  const invalidate = () => { epoch.current++; setAnalysis(null); };
  const newTimeline = () => { timeline.current++; lastMediaTime.current=null; setSessions([]);setWorkstations([]); invalidate(); };
  useEffect(()=>{
    const frame=video.current?.parentElement;
    if(!frame)return;
    const observer=new ResizeObserver(([entry])=>{const {width,height}=entry.contentRect;if(width&&height)setFrameSize({width,height});});
    observer.observe(frame);return()=>observer.disconnect();
  },[]);
  useEffect(()=>{if(!shown){epoch.current++;setAnalysis(null);video.current?.pause();}},[shown]);
  useEffect(() => {
    if (!enabled) { setAnalysis(null); setEngineError(''); return; }
    let cancelled = false, timer, expiry, lastSample = -1;
    const controller = new AbortController(), canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    async function sample() {
      if (cancelled) return;
      const element = video.current;
      if (!element || element.paused || element.seeking || element.ended || element.readyState < 2 || element.currentTime === lastSample) { timer = setTimeout(sample, 200); return; }
      const mediaTime = element.currentTime;
      if (lastMediaTime.current !== null && mediaTime < lastMediaTime.current) newTimeline();
      const requestEpoch = epoch.current, requestTimeline = timeline.current, requestSequence = ++sequence.current, started = performance.now();
      lastMediaTime.current = mediaTime;
      lastSample = mediaTime;
      try {
        const size = replayCaptureSize(element.videoWidth,element.videoHeight);
        canvas.width = size.width; canvas.height = size.height;
        context.drawImage(element, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .9));
        if (cancelled) return;
        if (!blob) throw new Error('Frame replay belum dapat dibaca');
        const response = await fetch('/pilot/v1/replay/frame', {method:'POST', credentials:'same-origin',
          headers:{'Content-Type':'image/jpeg', 'X-Replay-Id':file.id, 'X-Replay-Generation':String(requestTimeline),
            'X-Replay-Sequence':String(requestSequence), 'X-Replay-Time':String(mediaTime), 'X-Replay-Calibration':String(calibrationRevision.current)},
          body:blob, signal:AbortSignal.any([controller.signal, AbortSignal.timeout(10000)])});
        const packet = await response.json();
        if (!response.ok) throw new Error(typeof packet.detail === 'string' ? packet.detail : 'Deteksi replay tidak tersedia');
        if (cancelled || requestEpoch !== epoch.current || element.paused || element.seeking || element.ended) return;
        if (packet.replay_id !== file.id || packet.generation !== requestTimeline || packet.frame_sequence !== requestSequence) throw new Error('Engine replay belum mendukung sesi timer. Mulai ulang aplikasi Python.');
        setEngineError('');
        clearTimeout(expiry);
        if (performance.now()-started > 1000 || Math.abs(element.currentTime-mediaTime) > .5) { setAnalysis(null); return; }
        setSessions(recentReplaySessions(packet.sessions || []));
        setWorkstations(packet.workstations || []);
        lastWorkstationEvidence.current={mediaTime:packet.media_time_seconds,received:performance.now()};
        const display = replayDisplayPacket(packet,element.currentTime,element.playbackRate);
        setAnalysis(display.packet);
        expiry = setTimeout(() => setAnalysis(null), display.lifetime);
      } catch (failure) {
        if (!cancelled && requestEpoch === epoch.current) { setAnalysis(null); setEngineError(failure.name === 'TimeoutError' ? 'Engine melewati batas waktu; mencoba kembali.' : failure.message); }
      } finally { if (!cancelled) timer = setTimeout(sample, Math.max(0, 250-(performance.now()-started))); }
    }
    sample();
    return () => { cancelled = true; controller.abort(); clearTimeout(timer); clearTimeout(expiry); };
  }, [file.url, enabled]);
  async function playPause() {
    const element = video.current;
    if (!element || !ready) return;
    if (!element.paused) { element.pause(); return; }
    if (element.ended) element.currentTime = 0;
    try { await element.play(); } catch { setError('Video belum dapat diputar. Coba pilih MP4 H.264 atau WebM.'); }
  }
  function reset() { video.current.pause(); newTimeline(); video.current.currentTime = 0; setPosition(0); }
  function openCalibration() {
    const element=video.current;
    if(!element || element.readyState<2)return;
    element.pause();invalidate();setEngineError('');
    try {
      const canvas=document.createElement('canvas'),size=replayCaptureSize(element.videoWidth,element.videoHeight);
      canvas.width=size.width;canvas.height=size.height;canvas.getContext('2d').drawImage(element,0,0,size.width,size.height);
      setCalibrationImage({url:canvas.toDataURL('image/jpeg',.9),...size});
    } catch {setEngineError('Frame belum dapat dibaca. Putar video sebentar lalu coba lagi.');}
  }
  async function saveCalibration(value) {
    const url=`/pilot/v1/replay/${file.id}/calibration`;
    const options={credentials:'same-origin',signal:AbortSignal.timeout(10000)};
    const current=await fetch(url,options), state=await current.json();
    if(!current.ok)throw new Error(state.detail || 'Kalibrasi belum dapat dibaca');
    const response=await fetch(url,{...options,method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...value,expected_revision:state.calibration_revision})});
    const packet=await response.json();
    if(!response.ok)throw new Error(packet.detail || 'Kalibrasi ditolak engine');
    calibrationRevision.current=packet.calibration_revision;
    newTimeline();timeline.current=Math.max(timeline.current,packet.minimum_generation);
    sequence.current=Math.max(sequence.current,packet.minimum_sequence-1);
    setCalibration(value);setCalibrated(true);setCalibrationNotice('Zona diterapkan. Pengukuran baru dimulai saat video diputar.');
    try {localStorage.setItem(`replay-zones-v1:${file.key}`,JSON.stringify(value));}
    catch {setCalibrationNotice('Zona diterapkan untuk sesi ini. Browser tidak dapat menyimpan kalibrasi.');}
  }
  async function fullscreen() {
    try { if (document.fullscreenElement === tile.current) await document.exitFullscreen(); else await tile.current.requestFullscreen(); }
    catch { setEngineError('Fullscreen tidak tersedia di browser ini.'); }
  }
  const workstationFresh=lastWorkstationEvidence.current && !engineError
    && performance.now()-lastWorkstationEvidence.current.received<1000
    && Math.abs(position-lastWorkstationEvidence.current.mediaTime)<1;
  return <article hidden={!shown} className="replay-tile" ref={tile} data-testid="video-replay-tile">
    <header><div><span className="replay-badge">REPLAY LOKAL</span><h3 title={file.name}>{file.name}</h3></div><Button icon={Trash2} aria-label={`Hapus replay ${file.name}`} onClick={onRemove}/></header>
    <div className="replay-frame">
      <video ref={video} src={file.url} muted playsInline preload="metadata" loop={loop} aria-label={`Video replay ${file.name}`}
        onLoadedMetadata={event => { const element = event.currentTarget; if (!Number.isFinite(element.duration) || element.duration <= 0) { setError('Durasi video tidak dapat dibaca. Gunakan file MP4 H.264 atau WebM dengan durasi yang valid.'); return; } setDuration(element.duration); setDimensions({width:element.videoWidth,height:element.videoHeight}); }}
        onTimeUpdate={event => setPosition(event.currentTarget.currentTime)} onPlay={() => { setPlaying(true); setError(''); }}
        onPause={() => { setPlaying(false); invalidate(); }} onSeeking={newTimeline} onEnded={() => { setPlaying(false); invalidate(); }}
        onError={() => { setError('Codec video tidak didukung atau file rusak. Coba MP4 H.264 atau WebM.'); setPlaying(false); invalidate(); }}/>
      {enabled && analysis && <svg className="replay-overlay" viewBox={`0 0 ${dimensions.width} ${dimensions.height}`} aria-label="Deteksi orang pada replay">{analysis.display_detections?.map((row, i) => {
        const [x1,y1,x2,y2] = row.box, w=dimensions.width, h=dimensions.height;
        const held=row.measured === false, weak=row.evidence_state === 'WEAK';
        const label = row.session_id ? row.recovery_pending ? 'Mencocokkan sesi...' : `${row.session_id.slice(0,6)}${held ? ' · posisi terakhir' : weak ? ' · bukti lemah' : ''}` : 'Menunggu sesi';
        const font=12*Math.max(w/frameSize.width,h/frameSize.height), labelWidth=Math.min(w, label.length*font*.62+font), labelX=Math.max(0,Math.min(x1*w,w-labelWidth)), labelY=Math.max(0,y1*h-font*1.5);
        return <g key={row.session_id || i}><rect className="replay-person-box" strokeDasharray={held ? '5 4' : undefined} x={x1*w} y={y1*h} width={(x2-x1)*w} height={(y2-y1)*h}><title>{held ? 'Posisi terakhir; belum ada deteksi baru. Timer dibekukan.' : `Orang terdeteksi, confidence ${Math.round(row.confidence*100)}%`}</title></rect><rect className="replay-timer-background" x={labelX} y={labelY} width={labelWidth} height={font*1.5}/><text className="replay-person-timer" x={labelX+font*.4} y={labelY+font*1.08} fontSize={font}>{label}</text></g>;
      })}</svg>}
      {calibrated&&<svg className="replay-overlay replay-zones" viewBox={`0 0 ${dimensions.width} ${dimensions.height}`} aria-label="Zona workstation replay">{calibration.zones.map(zone=><polygon key={zone.id} points={zone.polygon.map(([x,y])=>`${x*dimensions.width},${y*dimensions.height}`).join(' ')}><title>{zone.name}</title></polygon>)}</svg>}
    </div>
    <div className="replay-controls">
      <div className="inline-controls"><Button icon={playing ? Pause : Play} disabled={!ready} onClick={playPause}>{playing ? 'Jeda' : 'Putar'}</Button><Button icon={RotateCcw} disabled={!ready} onClick={reset}>Dari awal</Button><Button icon={Maximize} aria-label={`Fullscreen replay ${file.name}`} onClick={fullscreen}/><span className="replay-time">{time(position)} / {time(duration)}</span></div>
      <input type="range" min="0" max={duration || 0} step="0.1" value={Math.min(position, duration)} disabled={!ready} aria-label={`Posisi replay ${file.name}`} onChange={e => { invalidate(); video.current.currentTime = Number(e.target.value); setPosition(Number(e.target.value)); }}/>
      <div className="inline-controls"><Field label="Kecepatan"><select aria-label={`Kecepatan ${file.name}`} value={speed} disabled={!ready} onChange={e => { const value=Number(e.target.value); setSpeed(value); video.current.playbackRate=value; invalidate(); }}>{[.5,1,1.5,2].map(value => <option key={value} value={value}>{value}x</option>)}</select></Field><label className="check-control"><input type="checkbox" checked={loop} onChange={e => setLoop(e.target.checked)}/>Ulangi</label><label className="check-control"><input type="checkbox" checked={analysisEnabled} disabled={!engineAvailable || !ready} onChange={e => { invalidate(); setAnalysisEnabled(e.target.checked); }}/>Deteksi preview</label></div>
      <p className="caption" data-testid="replay-analysis-status">{!engineAvailable ? 'Preview lokal; engine belum terhubung.' : !analysisEnabled ? 'Deteksi preview nonaktif.' : !playing ? 'Deteksi dijeda bersama video.' : analysis ? `${analysis.count} orang terdeteksi · ${analysis.inference_ms} ms/frame · durasi replay, tidak masuk laporan` : 'Menunggu frame deteksi baru.'}</p>
      <div className="replay-workstations" aria-label="Durasi workstation replay">
        <div className="inline-controls"><strong>Durasi workstation</strong><Button disabled={!engineAvailable || !ready} onClick={openCalibration}>Kalibrasi zona</Button></div>
        {!calibrated?<p className="caption">{calibration.zones.length?'Kalibrasi file ini tersimpan di browser. Buka kalibrasi dan terapkan untuk sesi ini.':'Tandai zona workstation untuk mulai mengukur keterisian area.'}</p>:!calibration.zones.length?<p className="caption">Tidak ada zona aktif.</p>:!workstations.length?<p className="caption">Zona siap. Aktifkan deteksi preview dan putar video untuk mulai mengukur.</p>:<div className="replay-workstation-rows">{workstations.map(row=><div key={row.zone_id} data-zone-id={row.zone_id}>
          <div><strong>{row.name}</strong><span>{!engineAvailable?'Engine terputus':!analysisEnabled?'Deteksi nonaktif':!playing?'Dijeda':!workstationFresh?'Tidak pasti: bukti kedaluwarsa':row.state==='OCCUPIED'?'Terisi':row.state==='EMPTY'?'Tidak terdeteksi setelah konfirmasi':row.reason==='PENDING_CONFIRMATION'?'Tidak pasti: menunggu konfirmasi':'Tidak pasti: bukti ambigu'}</span></div>
          <dl><div><dt>Terisi</dt><dd>{time(row.occupied_us/1e6)}</dd></div><div><dt>Kosong</dt><dd>{time(row.empty_us/1e6)}</dd></div><div><dt>Tidak pasti</dt><dd>{time(row.unknown_us/1e6)}</dd></div><div><dt>Cakupan bukti</dt><dd>{row.coverage===null?'Belum tersedia':`${Math.round(row.coverage*100)}%`}</dd></div></dl>
        </div>)}</div>}
        <p className="caption">Total per zona tidak bergantung ID orang. Bukti lemah dan jeda frame tidak menambah durasi terisi. Seek, putar ulang, atau perubahan zona memulai pengukuran baru. Keterisian bukan produktivitas.</p>
        {calibrationNotice&&<p role="status" className="caption">{calibrationNotice}</p>}
      </div>
      <details className="replay-person-details"><summary>Sesi orang (eksperimental)</summary>
      {analysisEnabled && analysis?.reid && <p className="caption" data-testid="replay-reid-status">{analysis.reid.mode === 'off' ? 'ReID nonaktif pada engine ini.' : `ReID ${analysis.reid.mode === 'active' ? 'aktif (eksperimental)' : 'shadow'} · ${['SHADOW','ACTIVE'].includes(analysis.reid.status) ? `${analysis.reid.gallery_sessions} sesi dalam gallery · ${analysis.reid.mode === 'active' ? `${analysis.session_metrics?.reid_recovered || 0} recovery visual terkonfirmasi` : `${analysis.reid.decisions.filter(row=>row.action==='WOULD_MATCH').length} usulan cocok`}` : ({SAMPLE_INTERVAL:'menunggu sampel berikutnya', PROVIDER_ERROR:'model gagal; periksa konfigurasi dan mulai ulang engine', DISABLED_AFTER_ERROR:'dinonaktifkan setelah error; mulai ulang engine', LATENCY_BUDGET:'melewati anggaran waktu; mulai ulang engine', NO_PIXELS:'frame tidak tersedia'})[analysis.reid.status] || analysis.reid.status}. ${analysis.reid.mode === 'active' ? 'Sesi disambung hanya setelah konfirmasi; waktu selama hilang tidak ditambahkan.' : 'Pencocokan visual belum mengubah timer.'}`}</p>}
      {!!sessions.length && <div className="replay-session-times" aria-label="Durasi sesi replay">{sessions.slice(0,6).map(session=><span key={session.session_id} data-session-id={session.session_id}>{session.session_id.slice(0,6)} · <strong>{session.recovery_pending ? 'Memastikan identitas...' : time(session.accumulated_duration_us/1e6)}</strong> · {session.status==='LOST'?'Hilang sementara':session.evidence_state==='WEAK'?'Bukti lemah; timer dibekukan':'Terlihat'}</span>)}{sessions.length>6&&<span>+{sessions.length-6} sesi lain</span>}</div>}
      {analysisEnabled && <p className="caption">Timer mengikuti bukti pada waktu video dan dibekukan saat bukti lemah atau orang hilang. Box putus-putus menandai posisi terakhir, maksimal 0,4 detik. Identitas yang tidak pasti tetap menjadi sesi terpisah; seek atau putar ulang memulai sesi baru.</p>}
      </details>
      {error && <p className="error-text" role="alert">{error}</p>}{engineError && <p className="error-text" role="alert">{engineError}</p>}
    </div>
    {calibrationImage&&<ReplayCalibration initial={calibration} image={calibrationImage} onClose={()=>setCalibrationImage(null)} onSave={saveCalibration}/>}
  </article>;
}
