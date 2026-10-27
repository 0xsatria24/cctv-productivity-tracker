import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, FileVideo, Maximize, Minimize, Pause, Play, RotateCcw, Trash2 } from 'lucide-react';
import { Button, Field, Panel } from './components';
import './video-replay.css';
import { recentReplaySessions, replayCaptureSize, replayDisplayPacket, storedReplayCalibration, replaySessionId, replayCalibrationState } from './replay-domain';
import { ReplayCalibration } from './replay-calibration';
import { ReplayOverlay } from './replay-overlay';
import { WorkstationResults } from './workstation-replay';
import { WorkstationOverlay } from './workstation-overlay';
import { AreaCalibration } from './area-calibration';
import { workstationIntervalMs, ANALYSIS_JPEG_QUALITY } from './workstation-engine';

const LIMIT = 16;
const time = value => {
  const seconds = Math.max(0, Math.floor(Number.isFinite(value) ? value : 0));
  return `${Math.floor(seconds / 3600).toString().padStart(2,'0')}:${Math.floor(seconds / 60 % 60).toString().padStart(2,'0')}:${(seconds % 60).toString().padStart(2,'0')}`;
};

/** App-scoped local files. Object URLs are released on removal/unmount. */
export function VideoReplayWorkspace({ visible = true, engineAvailable = false }) {
  const [connected,setConnected]=useState(false);
  const [reidMode,setReidMode]=useState('off');
  const [workstationFps,setWorkstationFps]=useState(2);
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
        if(!abort.signal.aborted){setConnected(Boolean(packet?.available));setReidMode(packet?.reid?.mode || 'off');setWorkstationFps(packet?.workstation_policy?.sample_fps);}
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
      let id;
      try {id=replaySessionId(key,localStorage);} catch {id=crypto.randomUUID();}
      const entry = { id, key, name: file.name, size: file.size, url: URL.createObjectURL(file) };
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
      <p role="status" className="caption">{connected?`Engine replay terhubung. Mode workstation memakai timer area tanpa ReID. Mode orang: ReID ${reidMode}.`:'Engine replay belum terhubung. Jalankan engine lokal aplikasi.'}</p>
      <div className="replay-body">
      <div className="replay-toolbar">
        <Button icon={FileVideo} variant="primary" onClick={() => input.current?.click()}>Masukkan video replay</Button>
        <input ref={input} type="file" multiple accept="video/*,.mp4,.webm,.mov,.m4v,.avi,.mkv" aria-label="Pilih file video replay" className="replay-file-input" onChange={event => add(Array.from(event.target.files || []))}/>
        <span>{files.length} / {LIMIT} video</span>
        {!!files.length && <Field label="Layout video replay"><select value={layout} onChange={e => { setLayout(Number(e.target.value)); setPage(0); }}>{[1,4,9,16].map(n => <option key={n} value={n}>{n} tampilan</option>)}</select></Field>}
      </div>
      <p className="caption">MP4 H.264 atau WebM disarankan. Dukungan AVI, MKV, dan MOV bergantung codec browser. {connected ? 'Deteksi preview memakai engine lokal; hasilnya tidak masuk laporan durasi atau auto-save.' : 'Mode preview lokal. Deteksi memerlukan dashboard Python yang terhubung.'}</p>
      {notice && <p role="status" className="caption">{notice}</p>}
      {!!files.length && <><div className="replay-grid" data-layout={layout}>{files.map((file, index) => <ReplayTile key={file.id} file={file} workstationFps={workstationFps} shown={visible && Math.floor(index/layout) === page} engineAvailable={connected} onRemove={() => remove(file)}/>)}</div><div className="replay-pagination"><span>Halaman {page+1} / {pages}</span><Button icon={ChevronLeft} aria-label="Halaman replay sebelumnya" disabled={page === 0} onClick={() => setPage(current => current-1)}/><Button icon={ChevronRight} aria-label="Halaman replay berikutnya" disabled={page >= pages-1} onClick={() => setPage(current => current+1)}/></div></>}
      </div>
    </Panel>
  </section>;
}

function ReplayTile({ file, shown, engineAvailable, onRemove,workstationFps }) {
  const video = useRef(null), preview = useRef(null), tile = useRef(null), epoch = useRef(0);
  const timeline = useRef(0), sequence = useRef(0), lastMediaTime = useRef(null);
  const [playing, setPlaying] = useState(false), [position, setPosition] = useState(0), [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1), [loop, setLoop] = useState(false), [error, setError] = useState('');
  const [analysisEnabled, setAnalysisEnabled] = useState(false), [analysis, setAnalysis] = useState(null), [engineError, setEngineError] = useState('');
  const [analysisMode,setAnalysisMode]=useState('workstation');
  const [isFullscreen,setIsFullscreen]=useState(false),[showFullscreenControls,setShowFullscreenControls]=useState(true);
  const fullscreenControls=useRef(null),fullscreenIdle=useRef(null);
  const [sessions, setSessions] = useState([]);
  const [workstations,setWorkstations]=useState([]), [calibrationImage,setCalibrationImage]=useState(null);
  const [areaHistory,setAreaHistory]=useState([]),[syncing,setSyncing]=useState(true);
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
  const enabled = engineAvailable && analysisEnabled && shown && !syncing;
  const invalidate = () => { epoch.current++; setAnalysis(null); };
  const newTimeline = () => { timeline.current++; lastMediaTime.current=null; lastWorkstationEvidence.current=null;setSessions([]);invalidate(); };
  function wakeFullscreenControls() {
    setShowFullscreenControls(true);clearTimeout(fullscreenIdle.current);
    if(isFullscreen&&playing)fullscreenIdle.current=setTimeout(()=>{
      const keyboardFocus=fullscreenControls.current?.contains(document.activeElement)&&document.activeElement?.matches(':focus-visible');
      if(!keyboardFocus&&!fullscreenControls.current?.matches(':hover'))setShowFullscreenControls(false);
    },2500);
  }
  useEffect(()=>{
    const changed=()=>setIsFullscreen(document.fullscreenElement===tile.current);
    document.addEventListener('fullscreenchange',changed);
    return()=>{document.removeEventListener('fullscreenchange',changed);clearTimeout(fullscreenIdle.current);};
  },[]);
  useEffect(()=>{if(isFullscreen)wakeFullscreenControls();return()=>clearTimeout(fullscreenIdle.current);},[isFullscreen,playing]);
  useEffect(()=>{try {localStorage.setItem(`replay-session-v2:${file.key}`,file.id);} catch {}},[file.id,file.key]);
  async function checkpoint(report=false) {
    if(analysisMode!=='workstation'||(!report&&!lastWorkstationEvidence.current))return;
    try {
      for(let attempt=0;attempt<3;attempt++) {
        const response=await fetch(`/pilot/v1/replay/${file.id}/checkpoint`,{method:'POST',credentials:'same-origin',keepalive:true});
        if(response.status!==429) {
          if(report&&response.ok) {const packet=await response.json();if(packet.save_error)setCalibrationNotice(packet.save_error);}
          break;
        }
        await new Promise(resolve=>setTimeout(resolve,150));
      }
    } catch { /* The next successful analysis also writes a checkpoint. */ }
  }
  useEffect(()=>{
    if(!engineAvailable)return;
    let cancelled=false;setSyncing(true);setEngineError('');
    async function restore() {
      try {
        const packet=await replayCalibrationState(`/pilot/v1/replay/${file.id}/calibration`,{signal:AbortSignal.timeout(10000)});
        if(cancelled)return;
        if(packet.calibration_revision===0&&calibration.zones.length)await saveCalibration(calibration);
        else {
          const saved=storedReplayCalibration(packet);
          if(!saved)throw new Error('Data area tersimpan tidak valid. Buka pengaturan area untuk memeriksa.');
          setCalibration(saved);setCalibrated(packet.calibration_revision>0);
          calibrationRevision.current=packet.calibration_revision;
          timeline.current=Math.max(timeline.current,packet.minimum_generation);
          sequence.current=Math.max(sequence.current,packet.minimum_sequence-1);
          setWorkstations(packet.workstations||[]);setAreaHistory(packet.workstation_history||[]);
          if(packet.save_error)setCalibrationNotice(packet.save_error);
        }
      } catch(failure) {if(!cancelled)setEngineError(failure.message);}
      finally {if(!cancelled)setSyncing(false);}
    }
    restore();return()=>{cancelled=true;checkpoint();};
  },[engineAvailable,file.id,analysisMode]);
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
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', ANALYSIS_JPEG_QUALITY));
        if (cancelled) return;
        if (!blob) throw new Error('Frame replay belum dapat dibaca');
        const response = await fetch('/pilot/v1/replay/frame', {method:'POST', credentials:'same-origin',
          headers:{'Content-Type':'image/jpeg', 'X-Replay-Id':file.id, 'X-Replay-Generation':String(requestTimeline),
            'X-Replay-Sequence':String(requestSequence), 'X-Replay-Time':String(mediaTime), 'X-Replay-Calibration':String(calibrationRevision.current), 'X-Replay-Analysis':analysisMode},
          body:blob, signal:AbortSignal.any([controller.signal, AbortSignal.timeout(10000)])});
        const packet = await response.json();
        if (!response.ok) throw new Error(typeof packet.detail === 'string' ? packet.detail : 'Deteksi replay tidak tersedia');
        if (cancelled || requestEpoch !== epoch.current || element.paused || element.seeking || element.ended) return;
        if (packet.replay_id !== file.id || packet.generation !== requestTimeline || packet.frame_sequence !== requestSequence) throw new Error('Engine replay belum mendukung sesi timer. Mulai ulang aplikasi Python.');
        if (analysisMode==='workstation' && packet.analysis_mode!=='workstation') throw new Error('Mulai ulang engine untuk memakai analisis workstation dan ArUco.');
        setEngineError('');
        clearTimeout(expiry);
        if (performance.now()-started > 1500) { setAnalysis(null); setEngineError('Frame terlambat; menunggu hasil terbaru.'); return; }
        setSessions(recentReplaySessions(packet.sessions || []));
        setWorkstations(packet.workstations || []);
        setAreaHistory(packet.workstation_history||[]);
        if(packet.save_error)setCalibrationNotice(packet.save_error);
        lastWorkstationEvidence.current={mediaTime:packet.media_time_seconds,received:performance.now()};
        if (analysisMode==='workstation') {setAnalysis(packet);return;}
        const display = replayDisplayPacket(packet,mediaTime,element.playbackRate);
        const surface = preview.current;
        if (!surface) return;
        surface.width = canvas.width; surface.height = canvas.height;
        surface.getContext('2d').drawImage(canvas,0,0);
        setAnalysis(display.packet);
        expiry = setTimeout(() => {
          if (!cancelled && requestEpoch === epoch.current) { setAnalysis(null); setEngineError('Menunggu frame deteksi terbaru.'); }
        }, 1500);
      } catch (failure) {
        if (!cancelled && requestEpoch === epoch.current) { setAnalysis(null); setEngineError(failure.name === 'TimeoutError' ? 'Engine melewati batas waktu; mencoba kembali.' : failure.message); }
      } finally { if (!cancelled) timer = setTimeout(sample, Math.max(0, (analysisMode==='workstation'?workstationIntervalMs(workstationFps):200)/Math.max(.5,element.playbackRate)-(performance.now()-started))); }
    }
    sample();
    return () => { cancelled = true; controller.abort(); clearTimeout(timer); clearTimeout(expiry); };
  }, [file.url, enabled, analysisMode,workstationFps]);
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
    const state=await replayCalibrationState(url,{signal:options.signal});
    const response=await fetch(url,{...options,method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...value,expected_revision:state.calibration_revision})});
    const packet=await response.json();
    if(!response.ok)throw new Error(packet.detail || 'Kalibrasi ditolak engine');
    calibrationRevision.current=packet.calibration_revision;
    if(packet.changed){newTimeline();timeline.current=Math.max(timeline.current,packet.minimum_generation);}
    sequence.current=Math.max(sequence.current,packet.minimum_sequence-1);
    setWorkstations(packet.workstations||[]);setAreaHistory(packet.workstation_history||[]);
    setCalibration(value);setCalibrated(true);setCalibrationNotice(packet.save_error||'Area disimpan. Hasil area yang tidak berubah tetap dipertahankan.');
    try {localStorage.setItem(`replay-zones-v1:${file.key}`,JSON.stringify(value));}
    catch {setCalibrationNotice('Zona diterapkan untuk sesi ini. Browser tidak dapat menyimpan kalibrasi.');}
  }
  async function fullscreen() {
    try { if (document.fullscreenElement === tile.current) await document.exitFullscreen(); else await tile.current.requestFullscreen(); }
    catch { setEngineError('Fullscreen tidak tersedia di browser ini.'); }
  }
  const workstationFresh=lastWorkstationEvidence.current && !engineError
    && performance.now()-lastWorkstationEvidence.current.received<Math.max(1500,1500/speed)
    && Math.abs(position-lastWorkstationEvidence.current.mediaTime)<1;
  const mediaScale=Math.min(frameSize.width/dimensions.width,frameSize.height/dimensions.height);
  const mediaInset={x:Math.max(0,(frameSize.width-dimensions.width*mediaScale)/2),y:Math.max(0,(frameSize.height-dimensions.height*mediaScale)/2)};
  function seek(value) {invalidate();video.current.currentTime=Number(value);setPosition(Number(value));}
  return <article hidden={!shown} className="replay-tile" ref={tile} data-testid="video-replay-tile" onPointerMove={()=>{if(isFullscreen)wakeFullscreenControls();}} onFocusCapture={()=>{if(isFullscreen)wakeFullscreenControls();}}>
    <header><div><span className="replay-badge">REPLAY LOKAL</span><h3 title={file.name}>{file.name}</h3></div><Button icon={Trash2} aria-label={`Hapus replay ${file.name}`} onClick={onRemove}/></header>
    <div className="replay-frame" onDoubleClick={fullscreen}>
      <video ref={video} src={file.url} muted playsInline preload="metadata" loop={loop} aria-label={`Video replay ${file.name}`}
        onLoadedMetadata={event => { const element = event.currentTarget; if (!Number.isFinite(element.duration) || element.duration <= 0) { setError('Durasi video tidak dapat dibaca. Gunakan file MP4 H.264 atau WebM dengan durasi yang valid.'); return; } setDuration(element.duration); setDimensions({width:element.videoWidth,height:element.videoHeight}); }}
        onTimeUpdate={event => setPosition(event.currentTarget.currentTime)} onPlay={() => { setPlaying(true); setError(''); }}
        onPause={() => { setPlaying(false); invalidate();checkpoint(true); }} onSeeking={newTimeline} onEnded={() => { setPlaying(false); invalidate();checkpoint(true); }}
        onError={() => { setError('Codec video tidak didukung atau file rusak. Coba MP4 H.264 atau WebM.'); setPlaying(false); invalidate(); }}/>
      <canvas ref={preview} className="replay-detection-frame" hidden={analysisMode==='workstation' || !enabled || !playing || !analysis} aria-label="Frame video yang dianalisis"/>
      {enabled && playing && analysisMode==='person' && <ReplayOverlay packet={analysis} video={video} synchronized dimensions={dimensions} frameSize={frameSize} formatTime={time}/>}
      {calibrated&&<WorkstationOverlay zones={calibration.zones} rows={workstations} dimensions={dimensions} frameSize={frameSize} formatTime={time} fresh={workstationFresh} playing={playing} enabled={enabled} position={position}/>}
      {ready && <span className="replay-frame-time" style={{right:mediaInset.x+6,bottom:mediaInset.y+(isFullscreen&&showFullscreenControls?58:6)}} data-testid="replay-frame-time">{!isFullscreen&&'Video '}{time(analysisMode==='person' && enabled && playing && analysis ? analysis.media_time_seconds : position)}{!playing&&!isFullscreen?' · Dijeda':analysisMode==='person' && enabled && analysis&&!isFullscreen?' · Frame deteksi':''}</span>}
    </div>
    <div className="replay-controls">
      <Field label="Mode analisis"><select value={analysisMode} onChange={e=>{newTimeline();setAnalysisMode(e.target.value);}}><option value="workstation">Workstation + check-in ArUco</option><option value="person">Tracking orang (eksperimental)</option></select></Field>
      <div className="inline-controls"><Button icon={playing ? Pause : Play} disabled={!ready} onClick={playPause}>{playing ? 'Jeda' : 'Putar'}</Button><Button icon={RotateCcw} disabled={!ready} onClick={reset}>Dari awal</Button><Button icon={Maximize} aria-label={`Fullscreen replay ${file.name}`} onClick={fullscreen}/><span className="replay-time">{time(position)} / {time(duration)}</span></div>
      <input type="range" min="0" max={duration || 0} step="0.1" value={Math.min(position, duration)} disabled={!ready} aria-label={`Posisi replay ${file.name}`} onChange={e=>seek(e.target.value)}/>
      <div className="inline-controls"><Field label="Kecepatan"><select aria-label={`Kecepatan ${file.name}`} value={speed} disabled={!ready} onChange={e => { const value=Number(e.target.value); setSpeed(value); video.current.playbackRate=value; invalidate(); }}>{[.5,1,1.5,2].map(value => <option key={value} value={value}>{value}x</option>)}</select></Field><label className="check-control"><input type="checkbox" checked={loop} onChange={e => setLoop(e.target.checked)}/>Ulangi</label><label className="check-control"><input type="checkbox" checked={analysisEnabled} disabled={!engineAvailable || !ready} onChange={e => { invalidate(); setAnalysisEnabled(e.target.checked); }}/>Deteksi preview</label></div>
      <p className="caption" data-testid="replay-analysis-status">{!engineAvailable ? 'Preview lokal; engine belum terhubung.' : !analysisEnabled ? 'Deteksi preview nonaktif.' : !playing ? 'Deteksi dijeda bersama video.' : analysis ? `${analysis.count} orang terdeteksi · ${analysis.inference_ms} ms/frame · durasi replay, tidak masuk laporan` : 'Menunggu frame deteksi baru.'}</p>
      {analysisEnabled && <p className="caption">{analysisMode==='workstation'?'Video diputar pada kecepatan sumber. Analisis area mengambil maksimal dua sampel per detik video; timer hanya bertambah dari bukti engine.':'Gambar dan box diperbarui bersama mengikuti kecepatan deteksi. T: track sementara. S: sesi timer. Bukti lemah tidak menambah durasi.'}</p>}
      {analysisMode==='workstation'&&<WorkstationResults rows={workstations} history={areaHistory} notice={calibrationNotice} formatTime={time} fresh={workstationFresh} playing={playing} enabled={enabled} onCalibrate={openCalibration} ready={engineAvailable&&ready&&!syncing} calibrated={calibrated} zones={calibration.zones} aruco={analysis?.aruco}/>}
      {analysisMode==='person'&&<div className="replay-workstations" aria-label="Durasi workstation replay">
        <div className="inline-controls"><strong>Durasi workstation</strong><Button disabled={!engineAvailable || !ready} onClick={openCalibration}>Kalibrasi zona</Button></div>
        {!calibrated?<p className="caption">{calibration.zones.length?'Kalibrasi file ini tersimpan di browser. Buka kalibrasi dan terapkan untuk sesi ini.':'Tandai zona workstation untuk mulai mengukur keterisian area.'}</p>:!calibration.zones.length?<p className="caption">Tidak ada zona aktif.</p>:!workstations.length?<p className="caption">Zona siap. Aktifkan deteksi preview dan putar video untuk mulai mengukur.</p>:<div className="replay-workstation-rows">{workstations.map(row=><div key={row.zone_id} data-zone-id={row.zone_id}>
          <div><strong>{row.name}</strong>{engineAvailable&&analysisEnabled&&playing&&workstationFresh&&['OCCUPIED','EMPTY'].includes(row.state)&&<span>{row.state==='OCCUPIED'?'Terisi':'Kosong'}</span>}</div>
          <dl><div><dt>Terisi</dt><dd>{time(row.occupied_us/1e6)}</dd></div><div><dt>Kosong</dt><dd>{time(row.empty_us/1e6)}</dd></div></dl>
        </div>)}</div>}
        <p className="caption">Total per zona tidak bergantung ID orang. Bukti lemah dan jeda frame tidak menambah durasi terisi. Seek, putar ulang, atau perubahan zona memulai pengukuran baru. Keterisian bukan produktivitas.</p>
        {calibrationNotice&&<p role="status" className="caption">{calibrationNotice}</p>}
      </div>}
      {analysisMode==='person'&&<details className="replay-person-details"><summary>Sesi orang (eksperimental)</summary>
      {analysisEnabled && analysis?.reid && <p className="caption" data-testid="replay-reid-status">{analysis.reid.mode === 'off' ? 'ReID nonaktif pada engine ini.' : `ReID ${analysis.reid.mode === 'active' ? 'aktif (eksperimental)' : 'shadow'} · ${['SHADOW','ACTIVE'].includes(analysis.reid.status) ? `${analysis.reid.gallery_sessions} sesi dalam gallery · ${analysis.reid.mode === 'active' ? `${analysis.session_metrics?.reid_recovered || 0} recovery visual terkonfirmasi` : `${analysis.reid.decisions.filter(row=>row.action==='WOULD_MATCH').length} usulan cocok`}` : ({SAMPLE_INTERVAL:'menunggu sampel berikutnya', PROVIDER_ERROR:'model gagal; periksa konfigurasi dan mulai ulang engine', DISABLED_AFTER_ERROR:'dinonaktifkan setelah error; mulai ulang engine', LATENCY_BUDGET:'melewati anggaran waktu; mulai ulang engine', NO_PIXELS:'frame tidak tersedia'})[analysis.reid.status] || analysis.reid.status}. ${analysis.reid.mode === 'active' ? 'Sesi disambung hanya setelah konfirmasi; waktu selama hilang tidak ditambahkan.' : 'Pencocokan visual belum mengubah timer.'}`}</p>}
      {!!sessions.length && <div className="replay-session-times" aria-label="Durasi sesi replay">{sessions.slice(0,6).map(session=><span key={session.session_id} data-session-id={session.session_id}>{session.session_id.slice(0,6)} · <strong>{session.recovery_pending ? 'Memastikan identitas...' : time(session.accumulated_duration_us/1e6)}</strong> · {session.status==='LOST'?'Hilang sementara':session.evidence_state==='WEAK'?'Bukti lemah; timer dibekukan':'Terlihat'}</span>)}{sessions.length>6&&<span>+{sessions.length-6} sesi lain</span>}</div>}
      {analysisEnabled && <p className="caption">T adalah track sementara; S adalah sesi timer, bukan identitas karyawan. Timer dibekukan saat bukti lemah atau orang hilang. Gambar mengikuti frame deteksi; posisi terakhir hanya dibawa maksimal 0,4 detik waktu video. Seek atau putar ulang memulai sesi baru.</p>}
      </details>}
      {error && <p className="error-text" role="alert">{error}</p>}{engineError && <p className="error-text" role="alert">{engineError}</p>}
    </div>
    {isFullscreen&&<div className="replay-fullscreen-controls" ref={fullscreenControls} data-visible={showFullscreenControls||!playing} aria-label="Kontrol video fullscreen">
      <Button icon={playing?Pause:Play} disabled={!ready} aria-label={playing?'Jeda video fullscreen':'Putar video fullscreen'} onClick={playPause}/>
      <span className="replay-fullscreen-name" title={file.name}>{file.name}</span>
      <input type="range" min="0" max={duration||0} step="0.1" value={Math.min(position,duration)} disabled={!ready} aria-label={`Posisi video fullscreen ${file.name}`} onChange={e=>seek(e.target.value)}/>
      <span className="replay-fullscreen-time">{time(position)} / {time(duration)}</span>
      <Button icon={Minimize} aria-label="Keluar fullscreen" onClick={fullscreen}/>
    </div>}
    {isFullscreen&&(error||engineError)&&<p className="replay-fullscreen-error" role="alert">{error||engineError}</p>}
    {calibrationImage&&(analysisMode==='workstation'?<AreaCalibration initial={calibration} image={calibrationImage} onClose={()=>setCalibrationImage(null)} onSave={saveCalibration}/>:<ReplayCalibration initial={calibration} image={calibrationImage} onClose={()=>setCalibrationImage(null)} onSave={saveCalibration}/>)}
  </article>;
}
