import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { advanceState, dataset, effectiveWorkspace, initialState } from './fixtures';

const STORAGE_KEY = 'cctv-workspace-v2';
const Context = createContext(null);
const uid = () => crypto.randomUUID();

function load() {
  try {
    localStorage.removeItem('cctv-design-prototype-v1');
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (value?.version === 2 && Array.isArray(value.cameras) && Array.isArray(value.workspaces) && value.settings && Array.isArray(value.liveIntervals) && Number.isFinite(value.clock)) return value;
  } catch { /* Unavailable or invalid browser storage starts an empty workspace. */ }
  return initialState();
}
const addEvent = (state, message, type = 'CONFIG_CHANGE', extra = {}) => ({ ...state, events: [{ id: uid(), time: state.clock, cameraId: null, workspaceId: null, message, type, ...extra }, ...state.events].slice(0, 100) });

export function PrototypeProvider({ children }) {
  const [state, setState] = useState(load);
  const [playing, setPlaying] = useState(false);
  const [dialog, setDialog] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [notice, setNotice] = useState('');
  const [dirtyPage, setDirtyPage] = useState(false);
  const pending = useRef(new Map());
  const noticeTimer = useRef(null);

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
    catch { /* Private mode/quota: the current session still works in memory. */ }
  }, [state]);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setState(previous => advanceState(previous)), 4000);
    return () => window.clearInterval(timer);
  }, [playing]);
  useEffect(() => () => { pending.current.forEach(timers => timers.forEach(window.clearTimeout)); window.clearTimeout(noticeTimer.current); }, []);

  function notify(message) { setNotice(message); window.clearTimeout(noticeTimer.current); noticeTimer.current = window.setTimeout(() => setNotice(''), 4500); }
  function runJob({ type, label, complete, result = null, filename = null, cancellable = true, failure = null, delay = 1800 }) {
    const id = uid();
    setJobs(previous => [{ id, type, label, status: 'QUEUED', progress: null, result, filename, cancellable }, ...previous].slice(0, 30));
    const started = window.setTimeout(() => setJobs(previous => previous.map(job => job.id === id ? { ...job, status: 'RUNNING' } : job)), 120);
    const done = window.setTimeout(() => {
      pending.current.delete(id);
      if (complete) setState(previous => complete(previous));
      setJobs(previous => previous.map(job => job.id === id ? { ...job, status: failure ? 'FAILED' : 'COMPLETED', error: failure, progress: failure ? null : 100 } : job));
      notify(`${label} ${failure ? 'gagal' : 'selesai'} (simulasi).`);
    }, delay);
    pending.current.set(id, [started, done]);
    return id;
  }
  function cancelJob(id) {
    const timers = pending.current.get(id);
    if (!timers) return;
    timers.forEach(window.clearTimeout); pending.current.delete(id);
    setJobs(previous => previous.map(job => job.id === id ? { ...job, status: 'CANCELLED', progress: null } : job));
    notify('Pekerjaan simulasi dibatalkan.');
  }
  function cameraStatus(id, status) {
    setState(previous => addEvent({ ...previous, cameras: previous.cameras.map(c => c.id === id ? { ...c, status, enabled: status !== 'DISABLED', changedAt: previous.clock, reconnects: c.reconnects + (status === 'RECONNECTING' ? 1 : 0) } : c) }, `${id}: status koneksi menjadi ${status}`, status === 'OFFLINE' ? 'CAMERA_LOST' : 'CAMERA_STATE', { cameraId: id }));
  }
  function saveCamera(draft) {
    const isNew = !draft.id;
    setState(previous => {
      const id = draft.id || `CAM-${String(Math.max(0, ...previous.cameras.map(c => Number(c.id.slice(4)))) + 1).padStart(2, '0')}`;
      const camera = { ...draft, id, revision: (draft.revision ?? 0) + 1, reconnects: draft.reconnects ?? 0, status: draft.enabled ? 'OFFLINE' : 'DISABLED', changedAt: previous.clock };
      return addEvent({ ...previous, cameras: isNew ? [...previous.cameras, camera] : previous.cameras.map(c => c.id === id ? camera : c) }, `${camera.name}: konfigurasi disimpan`, 'CONFIG_CHANGE', { cameraId: id });
    });
    notify('Konfigurasi kamera disimpan lokal.');
  }
  function testCamera(id, succeeds = true) {
    const valid = succeeds && state.cameras.find(c => c.id === id)?.credentialConfigured;
    cameraStatus(id, 'RECONNECTING');
    return runJob({ type: 'test', label: `Uji koneksi ${id}`, failure: valid ? null : 'Koneksi mock gagal atau kredensial contoh belum tersedia.', complete: previous => addEvent({ ...previous, cameras: previous.cameras.map(c => c.id === id ? { ...c, status: valid ? 'ONLINE' : 'OFFLINE', changedAt: previous.clock } : c) }, `${id}: ${valid ? 'uji koneksi simulasi selesai' : 'uji koneksi gagal pada skenario demo'}`, 'CAMERA_TEST', { cameraId: id }), cancellable: false });
  }
  function saveWorkspace(draft) {
    const id = draft.id || `WS-${String(Math.max(0, ...state.workspaces.map(w => Number(w.id.slice(3)))) + 1).padStart(2, '0')}`;
    setState(previous => {
      const camera = previous.cameras.find(c => c.id === draft.cameraId);
      const next = { ...draft, id, revision: (draft.revision ?? 0) + 1, area: camera.area, liveState: 'UNKNOWN', count: null, monitorFrom: draft.monitorFrom ?? previous.clock, applyStatus: 'PENDING_APPLY' };
      return addEvent({ ...previous, workspaces: draft.id ? previous.workspaces.map(w => w.id === id ? next : w) : [...previous.workspaces, next] }, `${next.name}: revisi ${next.revision} menunggu diterapkan`, 'CONFIG_CHANGE', { workspaceId: id, cameraId: next.cameraId });
    });
    runJob({ type: 'configuration', label: 'Penerapan konfigurasi zona', cancellable: false, complete: previous => addEvent({ ...previous, workspaces: previous.workspaces.map(w => w.id === id ? { ...w, applyStatus: 'APPLIED', liveState: 'EMPTY', count: 0 } : w) }, `${draft.name}: konfigurasi simulasi diterapkan`, 'CONFIG_APPLIED', { workspaceId: id }) });
    setDirtyPage(false); notify('Revisi disimpan. Menunggu penerapan simulasi.');
  }
  function observe(id, value, count = null) {
    setState(previous => addEvent({ ...previous, workspaces: previous.workspaces.map(w => w.id === id ? { ...w, liveState: value, count: value === 'EMPTY' ? 0 : value === 'UNKNOWN' ? null : count } : w) }, `${state.workspaces.find(w => w.id === id)?.name}: observasi manual menjadi ${value}`, value === 'OCCUPIED' ? 'ENTER' : value === 'EMPTY' ? 'EXIT' : 'OBSERVATION_LOST', { workspaceId: id, cameraId: state.workspaces.find(w => w.id === id)?.cameraId }));
  }
  function scenario(value) {
    setState(previous => {
      if (value === 'EMPTY') return { ...initialState(), cameras: [], workspaces: [], events: [], liveIntervals: [], emptyHistory: true, settings: previous.settings };
      if (value === 'EXPIRED') return { ...previous, reportExpired: true };
      if (value === 'STORAGE') return addEvent({ ...previous, persistence: 'DEGRADED' }, 'Penyimpanan simulasi terganggu; semua zona unknown', 'PERSISTENCE_GAP');
      const cameras = previous.cameras.map((camera, i) => ({ ...camera, status: value === 'OFFLINE' && i === 0 ? 'OFFLINE' : value === 'INFERENCE' && i === 0 ? 'DEGRADED' : camera.enabled ? 'ONLINE' : 'DISABLED', changedAt: previous.clock }));
      return addEvent({ ...previous, cameras, persistence: 'HEALTHY', workspaces: previous.workspaces.map(w => ({ ...w, liveState: w.liveState === 'UNKNOWN' ? 'OCCUPIED' : w.liveState, count: w.liveState === 'EMPTY' ? 0 : 1 })) }, `Skenario simulasi: ${value}`, 'SCENARIO_CHANGED');
    });
    notify('Skenario simulasi diterapkan.');
  }
  function backup() {
    const snapshot = structuredClone({ ...state, backups: [] });
    runJob({ type: 'backup', label: 'Snapshot backup lokal', complete: previous => ({ ...previous, backups: [{ id: uid(), time: snapshot.clock, name: `Backup ${previous.backups.length + 1}`, bytes: new Blob([JSON.stringify(snapshot)]).size, snapshot }, ...previous.backups].slice(0, 8) }) });
  }
  function restore(id) {
    const backup = state.backups.find(item => item.id === id);
    if (!backup) return;
    setPlaying(false);
    runJob({ type: 'restore', label: 'Pemulihan snapshot simulasi', cancellable: false, complete: previous => addEvent({ ...structuredClone(backup.snapshot), backups: previous.backups }, `Snapshot ${backup.name} dipulihkan lokal`, 'RESTORE_COMPLETED') });
  }
  function reset() {
    setPlaying(false); pending.current.forEach(timers => timers.forEach(window.clearTimeout)); pending.current.clear();
    setJobs([]); setState(initialState()); setDirtyPage(false); setDialog(null); notify('Data lokal dikosongkan.');
  }
  const records = useMemo(() => dataset(state), [state.workspaces, state.liveIntervals, state.emptyHistory]);
  const observed = useMemo(() => state.workspaces.map(w => effectiveWorkspace(w, state)), [state.workspaces, state.cameras, state.persistence]);
  const value = { state, setState, records, observed, playing, setPlaying, dialog, setDialog, jobs, notice, dirtyPage, setDirtyPage, notify, runJob, cancelJob, cameraStatus, saveCamera, testCamera, saveWorkspace, observe, scenario, backup, restore, reset, advance: () => setState(previous => advanceState(previous)) };
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function usePrototype() { return useContext(Context); }
export function downloadText(text, filename, type = 'text/csv;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a'); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 3000);
}
