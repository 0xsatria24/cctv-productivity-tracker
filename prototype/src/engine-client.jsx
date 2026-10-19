import { useCallback, useEffect, useRef, useState } from 'react';

export async function engineRequest(path, options={}) {
  const { timeoutMs = 10000, ...fetchOptions } = options;
  const timeout = AbortSignal.timeout(timeoutMs);
  let response;
  try { response=await fetch(`/pilot/v1/${path}`,{credentials:'same-origin',cache:'no-store',...fetchOptions,signal:options.signal?AbortSignal.any([options.signal,timeout]):timeout,
    headers:{...(options.body?{'Content-Type':'application/json'}:{}),...options.headers}}); }
  catch(error){if(options.signal?.aborted)throw error;throw new Error(error.name==='TimeoutError'?'Layanan monitoring melewati batas waktu. Periksa aplikasi; koneksi akan dicoba kembali.':'Layanan monitoring tidak dapat dijangkau. Periksa apakah aplikasi masih berjalan.');}
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw new Error(typeof detail==='string'?detail:response.status===401?'Sesi engine berakhir. Muat ulang halaman untuk terhubung kembali.':`Engine mengembalikan HTTP ${response.status}.`);}
  return response.json();
}

export function queryString(filters,runId) {
  const values=new URLSearchParams();
  if(runId)values.set('run_id',runId);
  if(filters.workspace!=='ALL')values.set('workspace_id',filters.workspace);
  if(filters.start!=null)values.set('start_utc_us',String(filters.start));
  if(filters.end!=null)values.set('end_utc_us',String(filters.end));
  return values.toString();
}

export function useEngine() {
  const [cameraId, updateCameraId] = useState('');
  const [dataset, updateDataset] = useState(() => { try { return localStorage.getItem('cctv-report-source') === 'replay' ? 'replay' : 'live'; } catch { return 'live'; } });
  const [snapshot,setSnapshot]=useState(null),[connectionError,setConnectionError]=useState(''),[report,setReport]=useState(null),[reportError,setReportError]=useState('');
  const [selection,setSelection]=useState('LATEST'),[filters,setFilters]=useState({workspace:'ALL',start:null,end:null}),[refresh,setRefresh]=useState(0),[loading,setLoading]=useState(true),[notice,setNotice]=useState('');
  const [mutating,setMutating]=useState(false),[receivedAt,setReceivedAt]=useState(null),[reportLoading,setReportLoading]=useState(false),[exporting,setExporting]=useState(false);
  const mounted=useRef(true),noticeTimer=useRef();
  const reload=useCallback(()=>setRefresh(v=>v+1),[]);
  const setCameraId=useCallback(value=>{updateCameraId(value);setSnapshot(null);setReport(null);setReportError('');setLoading(true);setSelection('LATEST');setFilters({workspace:'ALL',start:null,end:null});},[]);
  const setDataset=useCallback(value=>{updateDataset(value);try{localStorage.setItem('cctv-report-source',value);}catch{}setSnapshot(null);setReport(null);setReportError('');setLoading(true);setSelection('LATEST');setFilters({workspace:'ALL',start:null,end:null});},[]);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;clearTimeout(noticeTimer.current);};},[]);
  useEffect(()=>{
    const controller=new AbortController();let timer;
    async function poll(){try{const value=await engineRequest(dataset==='live'?`status?dataset=live${cameraId?'&camera_id='+encodeURIComponent(cameraId):''}`:'status',{signal:controller.signal});if(!controller.signal.aborted){setSnapshot(value);setConnectionError('');setReceivedAt(Date.now());}}catch(error){if(error.name!=='AbortError')setConnectionError(error.message||'Engine tidak dapat dijangkau.');}finally{if(!controller.signal.aborted){setLoading(false);timer=setTimeout(poll,1000);}}}
    poll();return()=>{controller.abort();clearTimeout(timer);};
  },[refresh,dataset,cameraId]);
  const runId=selection==='LATEST'?snapshot?.runs[0]?.id:selection==='ALL'?null:selection;
  const query=queryString(filters,runId)+(dataset==='live'?`&dataset=live${cameraId?'&camera_id='+encodeURIComponent(cameraId):''}`:'');
  useEffect(()=>{
    if(!snapshot)return;
    const controller=new AbortController();
    setReportLoading(true);
    engineRequest(`reports?${query}`,{signal:controller.signal}).then(value=>{if(!controller.signal.aborted){setReport(value);setReportError('');}}).catch(error=>{if(!controller.signal.aborted){setReport(null);setReportError(error.message);}}).finally(()=>{if(!controller.signal.aborted)setReportLoading(false);});
    return()=>controller.abort();
  },[snapshot?.committed_event_seq,query,refresh]);
  async function action(path,body){
    setMutating(true);
    try{const result=await engineRequest(path+(dataset==='live'&&['employees','assignments'].includes(path)?`?dataset=live${cameraId?'&camera_id='+encodeURIComponent(cameraId):''}`:''),{method:'POST',...(body?{body:JSON.stringify(body)}:{})});if(path==='replay')setDataset('replay');reload();return result;}
    catch(error){toast(error.message);throw error;}
    finally{if(mounted.current)setMutating(false);}
  }
  function toast(message){setNotice(message);clearTimeout(noticeTimer.current);noticeTimer.current=setTimeout(()=>setNotice(''),5500);}
  async function exportCsv(){
    if(exporting||reportLoading)return;
    setExporting(true);
    try{const response=await fetch(`/pilot/v1/export.csv?${query}`,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});if(!response.ok)throw new Error('Ekspor gagal. Periksa koneksi dan rentang laporan.');const url=URL.createObjectURL(await response.blob());const anchor=document.createElement('a');anchor.href=url;anchor.download='cctv-engine-report.csv';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Laporan CSV berhasil diunduh.');}catch(error){toast(error.name==='TimeoutError'?'Ekspor melewati batas waktu. Periksa koneksi lalu coba lagi.':error.message);}finally{if(mounted.current)setExporting(false);}
  }
  return {cameraId,setCameraId,dataset,setDataset,snapshot,connectionError,report,reportError,reportLoading,selection,setSelection,runId,filters,setFilters,loading,reload,action,exportCsv,exporting,mutating,notice,toast,receivedAt};
}

export function seconds(microseconds){if(microseconds==null)return 'N/A';const value=microseconds/1e6;if(value<60)return `${new Intl.NumberFormat('id-ID',{maximumFractionDigits:1}).format(value)} dtk`;const hours=Math.floor(value/3600),minutes=Math.floor((value%3600)/60),rest=Math.floor(value%60);return `${hours?`${hours}j `:''}${minutes}m ${rest}d`;}
export function durationClock(microseconds){if(microseconds==null)return '--:--:--';const total=Math.max(0,Math.floor(microseconds/1e6));return [Math.floor(total/3600),Math.floor(total%3600/60),total%60].map(value=>String(value).padStart(2,'0')).join(':');}
export function ratio(value){return value==null?'N/A':`${new Intl.NumberFormat('id-ID',{maximumFractionDigits:1}).format(value*100)}%`;}
export function displayTime(value,timezone='Asia/Jakarta'){return value==null?'N/A':new Intl.DateTimeFormat('id-ID',{dateStyle:'medium',timeStyle:'medium',timeZone:timezone}).format(new Date(value/1000));}
export function inputUtc(value){return value==null?'':new Date(value/1000).toISOString().slice(0,19);}
export function parseUtc(value){const result=Date.parse(`${value}Z`);return Number.isFinite(result)?result*1000:null;}
export function totalMetrics(report){const sums=(report?.workstations||[]).reduce((sum,row)=>{for(const key of ['occupied_us','empty_us','unknown_us','eligible_us'])sum[key]+=row[key];return sum;},{occupied_us:0,empty_us:0,unknown_us:0,eligible_us:0});return {...sums,utilization:sums.occupied_us+sums.empty_us?sums.occupied_us/(sums.occupied_us+sums.empty_us):null,coverage:sums.eligible_us?(sums.occupied_us+sums.empty_us)/sums.eligible_us:null};}
