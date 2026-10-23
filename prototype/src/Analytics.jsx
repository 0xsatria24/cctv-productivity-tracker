import { useMemo, useState, useEffect } from 'react';
import { Download, RefreshCw } from 'lucide-react';
import { usePrototype } from './store';
import { Button, DataTable, Empty, Field, MetricStrip, Panel, Status } from './components';
import { DAY, REASONS, atDate, clipIntervals, clock, dateKey, duration, makeCsv, percent, rangeFor, reportRows, summarize, trendRows } from './domain';
import { Heatmap, Timeline, TrendChart } from './charts';
import { useLanguage } from './language';

export function useReport(workspaceId, initialPeriod='WEEK') {
  const {state,records}=usePrototype();
  const [filters,setFilters]=useState({period:initialPeriod,...rangeFor(initialPeriod),workspaceId:workspaceId||'ALL',grain:initialPeriod==='YEAR'?'MONTH':'DAY',precision:'EXACT'});
  const [applied,setApplied]=useState(filters),[error,setError]=useState('');
  useEffect(()=>{if(workspaceId){setFilters(previous=>({...previous,workspaceId}));setApplied(previous=>({...previous,workspaceId}));}},[workspaceId]);
  function period(value){const next={...filters,period:value,...(value==='CUSTOM'?{}:rangeFor(value)),grain:value==='YEAR'?'MONTH':'DAY'};setFilters(next);}
  function apply(){if(!filters.start||!filters.end||filters.start>filters.end){setError('Tanggal mulai harus sebelum atau sama dengan tanggal akhir.');return;}setError('');setApplied({...filters});}
  const scope=state.workspaces.filter(w=>applied.workspaceId==='ALL'?w.kind==='desk':w.id===applied.workspaceId);
  const start=atDate(applied.start),end=Math.min(atDate(applied.end)+DAY,state.clock);
  const expired=start<state.clock-state.settings.detailDays*DAY;
  const blocked=expired&&applied.precision==='EXACT';
  const clipped=useMemo(()=>clipIntervals(records,start,end,scope.map(w=>w.id)),[records,start,end,applied.workspaceId,state.workspaces]);
  const metrics=useMemo(()=>summarize(clipped),[clipped]);
  const rows=useMemo(()=>reportRows(clipped,state.workspaces,applied.grain),[clipped,state.workspaces,applied.grain]);
  return {state,filters,setFilters,applied,setApplied,error,setError,apply,period,scope,start,end,expired,blocked,clipped,metrics,rows};
}
export function ReportFilters({model}) {
  const {t}=useLanguage();
  const [open,setOpen]=useState(()=>!window.matchMedia('(max-width:760px)').matches);
  return <details className="report-filter-panel report-filter-controls" open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary>{t('Ubah periode dan workstation')}</summary><ReportFilterFields model={model}/></details>;
}
function ReportFilterFields({model}) {
  const {state,filters,setFilters,period,apply,error}=model;
  return <><div className="filter-toolbar report-filters"><Field label="Periode"><select value={filters.period} onChange={e=>period(e.target.value)}><option value="DAY">Harian</option><option value="WEEK">7 hari terakhir</option><option value="MONTH">Bulanan</option><option value="YEAR">Tahunan</option><option value="CUSTOM">Rentang tanggal</option></select></Field><Field label="Mulai"><input type="date" value={filters.start} max={dateKey(state.clock)} onChange={e=>setFilters(previous=>({...previous,period:'CUSTOM',start:e.target.value}))}/></Field><Field label="Sampai"><input type="date" value={filters.end} max={dateKey(state.clock)} onChange={e=>setFilters(previous=>({...previous,period:'CUSTOM',end:e.target.value}))}/></Field><Field label="Workstation"><select value={filters.workspaceId} onChange={e=>setFilters(previous=>({...previous,workspaceId:e.target.value}))}><option value="ALL">Semua desk</option>{state.workspaces.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></Field><Field label="Resolusi"><select value={filters.grain} onChange={e=>setFilters(previous=>({...previous,grain:e.target.value}))}><option value="DAY">Harian</option><option value="WEEK">Mingguan</option><option value="MONTH">Bulanan</option><option value="YEAR">Tahunan</option></select></Field><Field label="Sumber"><select value={filters.precision} onChange={e=>setFilters(previous=>({...previous,precision:e.target.value}))}><option value="EXACT">Interval detail</option><option value="ALIGNED_CACHE">Agregat kalender</option></select></Field><Button variant="primary" onClick={apply}>Terapkan filter</Button></div>{error&&<p className="error-text" role="alert">{error}</p>}</>;
}
function PrecisionNotice({model}) {
  return <div className="report-metadata"><span>{model.applied.start} s.d. {model.applied.end}</span><span>{model.state.settings.timezone}</span></div>;
}
function BlockedRange({model}) {return <Empty title="Detail interval tidak tersedia" description={`Rentang melewati retention detail ${model.state.settings.detailDays} hari. Gunakan agregat kalender untuk laporan; timeline rinci tidak tersedia.`} action={<Button onClick={()=>{model.setFilters(previous=>({...previous,precision:'ALIGNED_CACHE'}));model.setApplied(previous=>({...previous,precision:'ALIGNED_CACHE'}));}}>Gunakan agregat kalender</Button>}/>;}
export const reportColumns = [
  {key:'bucket',label:'Periode'}, {key:'name',label:'Workstation'}, {key:'occupied',label:'Terisi (j:m)',numeric:true,render:r=>duration(r.occupied,true)}, {key:'empty',label:'Kosong (j:m)',numeric:true,render:r=>duration(r.empty,true)}, {key:'unknown',label:'Unknown (j:m)',numeric:true,render:r=>duration(r.unknown,true)}, {key:'utilization',label:'Utilization',numeric:true,render:r=>percent(r.utilization)}, {key:'coverage',label:'Coverage',numeric:true,render:r=>percent(r.coverage)}, {key:'sessions',label:'Sesi',numeric:true},
];
export default function Analytics({workspaceId,tab:initialTab,onTabChange}) {
  const {t}=useLanguage();
  const model=useReport(workspaceId),{setDialog}=usePrototype();
  const [tab,updateTab]=useState(initialTab||'summary'),[visual,setVisual]=useState('trend'),[timelineDay,setTimelineDay]=useState(()=>dateKey(Date.now())),[interval,setInterval]=useState(null);
  function setTab(value){updateTab(value);onTabChange?.(value);}
  useEffect(()=>{if(initialTab)setTab(initialTab);},[initialTab]);
  const timelineStart=atDate(timelineDay,9),timelineEnd=Math.min(atDate(timelineDay,17),model.state.clock);
  const timelineRecords=useMemo(()=>clipIntervals(model.clipped,timelineStart,timelineEnd,model.scope.map(w=>w.id)),[model.clipped,timelineStart,timelineEnd]);
  const intervalColumns=[{key:'workspaceId',label:'Workstation',render:r=>model.state.workspaces.find(w=>w.id===r.workspaceId)?.name},{key:'start',label:'Mulai',render:r=>clock(r.start)},{key:'end',label:'Akhir',render:r=>clock(r.end)},{key:'state',label:'Observasi',render:r=><Status value={r.state}/>},{key:'reason',label:'Alasan',render:r=>REASONS[r.reason]},{key:'detail',label:'Detail',sortable:false,render:r=><Button onClick={()=>setInterval(r)}>Periksa</Button>}];
  if(!model.clipped.length)return <><ReportFilters model={model}/><PrecisionNotice model={model}/><div className="tab-bar">{[['summary','Ringkasan'],['daily','Harian'],['timeline','Timeline'],['export','Ekspor']].map(([value,label])=><button key={value} aria-pressed={tab===value} onClick={()=>setTab(value)}>{t(label)}</button>)}</div><Empty title="Belum ada data observasi"/></>;
  return <><ReportFilters model={model}/><PrecisionNotice model={model}/><div className="tab-bar">{[['summary','Ringkasan'],['daily','Harian'],['timeline','Timeline'],['export','Ekspor']].map(([value,label])=><button key={value} aria-pressed={tab===value} onClick={()=>setTab(value)}>{label}</button>)}</div>{model.blocked?<BlockedRange model={model}/>:tab==='export'?<ReportExport model={model}/>:<><MetricStrip metrics={model.metrics}/>{tab==='daily'?<Panel title="Rekap harian simulasi" caption="Durasi per workstation, dikelompokkan per hari"><DataTable columns={reportColumns} rows={reportRows(model.clipped,model.state.workspaces,'DAY')} testId="daily-table"/></Panel>:tab==='summary'?<><Panel title="Tren dan kelengkapan observasi" caption="Rasio memakai total durasi valid, tidak merata-ratakan persentase zona" action={<div className="segmented"><button aria-pressed={visual==='trend'} onClick={()=>setVisual('trend')}>Tren</button><button aria-pressed={visual==='heatmap'} onClick={()=>setVisual('heatmap')}>Heatmap 7 hari</button></div>}>{visual==='trend'?<TrendChart rows={trendRows(model.clipped,model.applied.grain)} onSelect={row=>setDialog({type:'bucket',row})}/>:<Heatmap intervals={model.clipped} endDate={model.applied.end}/>}</Panel><Panel className="section-gap" title="Record periodik" caption="Durasi banyak zona dalam jam-workstation; bukan person-hours"><DataTable columns={reportColumns} rows={model.rows} resetKey={JSON.stringify(model.applied)} testId="analytics-table"/></Panel></>:model.expired?<Empty title="Timeline detail sudah melewati retention" description="Agregat tetap dapat dibaca di tab Ringkasan." action={<Button onClick={()=>setTab('summary')}>Buka ringkasan</Button>}/>:<><div className="filter-toolbar"><Field label="Hari timeline"><input type="date" min={model.applied.start} max={model.applied.end} value={timelineDay} onChange={e=>{setTimelineDay(e.target.value);setInterval(null);}}/></Field><span className="caption">Pilih segmen atau gunakan tabel detail. Tidak ada playback rekaman.</span></div><Panel title="Timeline observasi zona" caption="Terisi, kosong, unknown, dan waktu di luar jadwal dipisahkan"><Timeline records={timelineRecords} workspaces={model.scope} start={timelineStart} end={Math.max(timelineEnd,timelineStart+60_000)} selectedId={interval?.id} onSelect={setInterval}/></Panel>{interval&&<div className="interval-detail"><Status value={interval.state}/><span>{clock(interval.start)}-{clock(interval.end)}</span><span>Durasi {duration(interval.end-interval.start)}</span><span>Jumlah: {interval.count??'N/A'}</span><span>{REASONS[interval.reason]}</span><span>Konfigurasi v{interval.revision}</span><Button onClick={()=>setDialog({type:'interval',interval})}>Detail sumber</Button></div>}<Panel className="section-gap" title="Detail interval" caption="Event/interval simulasi tanpa bukti video"><DataTable columns={intervalColumns} rows={timelineRecords} resetKey={timelineDay+JSON.stringify(model.applied)} pageSize={8}/></Panel></>}</>}</>;
}
export function Reports() {
  const model=useReport();
  return <><ReportFilters model={model}/><PrecisionNotice model={model}/><ReportExport model={model}/></>;
}
function ReportExport({model}) {
  const {state,setState,runJob,setDialog,jobs}=usePrototype();
  const [search,setSearch]=useState('');
  const rows=model.rows.filter(row=>row.name.toLowerCase().includes(search.toLowerCase()));
  function exportCsv(){const text=makeCsv(rows,{timezone:state.settings.timezone,start:model.applied.start,end:model.applied.end,grain:model.applied.grain,precision:model.applied.precision,identity_source:'anonymous_mock',coverage_pct:model.metrics.coverage??'N/A'});runJob({type:'export',label:'Ekspor CSV data simulasi',result:text,filename:`cctv-mock-${model.applied.start}-${model.applied.end}.csv`});setDialog({type:'jobs'});}
  return <>{state.reportExpired?<Empty title="Snapshot laporan kedaluwarsa (simulasi)" description="Filter dipertahankan. Muat ulang untuk mengambil snapshot baru." action={<Button icon={RefreshCw} onClick={()=>setState(previous=>({...previous,reportExpired:false}))}>Muat ulang laporan</Button>}/>:model.blocked?<BlockedRange model={model}/>:<><MetricStrip metrics={model.metrics}/><Panel title="Preview laporan" caption="Ekspor seluruh hasil filter, bukan hanya halaman yang terlihat" action={<Button variant="primary" icon={Download} disabled={!rows.length} onClick={exportCsv}>Ekspor CSV</Button>}><div className="table-filter"><Field label="Cari workstation pada laporan"><input type="search" placeholder="Nama workstation" value={search} onChange={e=>setSearch(e.target.value)}/></Field><span className="caption">{rows.length} record simulasi · hasil dapat diurutkan</span></div><DataTable columns={reportColumns} rows={rows} resetKey={search+JSON.stringify(model.applied)} testId="report-table"/></Panel><div className="report-footer"><span>CSV mencakup P/A/U, coverage, timezone dan label data mock.</span><Button onClick={()=>setDialog({type:'jobs'})}>Pekerjaan ekspor ({jobs.filter(j=>j.type==='export').length})</Button></div></>}</>;
}
