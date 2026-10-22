import { useEffect, useId, useRef, useState } from 'react';
import { clock, duration, percent, summarize, atDate, DAY, dateKey } from './domain';
import { Button, Empty, Field, Status } from './components';

function useWidth() {
  const ref = useRef(null), [width, setWidth] = useState(600);
  useEffect(() => { const observer = new ResizeObserver(entries => setWidth(Math.max(280, entries[0].contentRect.width))); observer.observe(ref.current); return () => observer.disconnect(); }, []);
  return [ref, width];
}
export function TrendChart({ rows, onSelect }) {
  const [ref, width] = useWidth();
  const [selected, setSelected] = useState(null), [series, setSeries] = useState({ utilization: true, coverage: true });
  const height = 220, left = 48, right = 24, top = 20, bottom = 44;
  const x = index => left + index * (width - left - right) / Math.max(1, rows.length - 1), y = value => top + (100 - value) / 100 * (height - top - bottom);
  const index = Math.min(selected ?? rows.length - 1, rows.length - 1), row = rows[index];
  function pick(i) { setSelected(i); onSelect?.(rows[i]); }
  return <div className="chart-container" ref={ref}>
    <div className="chart-legend">{[['utilization','Utilization','occupied'], ['coverage','Coverage observasi','accent']].map(([key,label,color]) => <button key={key} aria-pressed={series[key]} className={`legend-control ${series[key] ? '' : 'muted'}`} onClick={() => setSeries(previous => ({ ...previous, [key]: !previous[key] }))}><span className={`legend-swatch ${color}`}/>{label}</button>)}<span className="caption">Satuan: persen (%)</span></div>
    {!rows.length ? <Empty/> : <><svg role="img" aria-label="Tren utilization dan coverage dari data simulasi, sumbu waktu dan persen" width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
      {[0,25,50,75,100].map(value => <g key={value}><line x1={left} x2={width-right} y1={y(value)} y2={y(value)} className="chart-grid"/><text x={left-10} y={y(value)+4} textAnchor="end" className="chart-label">{value}</text></g>)}
      <text x={16} y={12} className="chart-label">%</text>
      {Object.entries(series).filter(([,enabled]) => enabled).map(([key]) => {
        let previousKnown = false;
        const path = rows.map((item,i) => { if (item[key] == null) { previousKnown = false; return ''; } const point = `${previousKnown ? 'L' : 'M'} ${x(i)} ${y(item[key])}`; previousKnown = true; return point; }).join(' ');
        return <g key={key}><path d={path} className={`chart-line ${key}`}/>{rows.map((item,i) => item[key] != null && <circle key={i} cx={x(i)} cy={y(item[key])} r={i === index ? 4 : 2.5} className={`chart-point ${key}`}/>)}</g>;
      })}
      <line x1={x(index)} x2={x(index)} y1={top} y2={height-bottom} className="chart-guide"/>
      {rows.map((item,i) => (i % Math.max(1, Math.ceil(rows.length / Math.max(2, Math.floor(width / 120)))) === 0 || i === rows.length - 1) && <text key={i} x={x(i)} y={height-20} textAnchor={i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle'} className="chart-label">{item.bucket.length === 10 ? item.bucket.slice(5) : item.bucket}</text>)}
      <text x={width-right} y={height-2} textAnchor="end" className="chart-label">Periode (Asia/Jakarta)</text>
      <rect x={left} y={top} width={width-left-right} height={height-top-bottom} fill="transparent" onPointerMove={event => { const rect = event.currentTarget.ownerSVGElement.getBoundingClientRect(); const cursor = (event.clientX-rect.left)*width/rect.width; setSelected(Math.max(0,Math.min(rows.length-1,Math.round((cursor-left)/(width-left-right)*(rows.length-1))))); }} onClick={() => onSelect?.(row)}/>
    </svg><div className="chart-detail"><Field label="Detail periode"><select aria-label="Detail periode grafik" value={index} onChange={event => pick(Number(event.target.value))}>{rows.map((item,i) => <option key={item.bucket} value={i}>{item.bucket}</option>)}</select></Field><span>Utilization <strong>{percent(row?.utilization)}</strong></span><span>Coverage <strong>{percent(row?.coverage)}</strong></span><span className="caption">Gap tidak diisi nol</span></div></>}
  </div>;
}
export function DurationBars({ rows, onSelect, max = 6 }) {
  const descriptionId=useId();
  return <div className="duration-bars"><div className="chart-legend">{[['occupied','Terisi'],['empty','Kosong'],['unknown','Tidak diketahui']].map(([key,label]) => <span key={key}><span className={`legend-swatch ${key}`}/>{label}</span>)}<span className="caption">Satuan: jam-workstation</span></div>
    {!rows.length ? <Empty/> : rows.slice(0,max).map(row => <button className="bar-row" key={row.id} onClick={() => onSelect(row)} aria-label={`Buka analitik ${row.name}`} aria-describedby={`${descriptionId}-${row.id}`}><span>{row.name}</span><span className="stacked-track" aria-hidden="true">{['occupied','empty','unknown'].map(key => row[key] > 0 && <span key={key} className={`stacked-segment ${key}`} style={{width: `${100*row[key]/row.eligible}%`}}/>)}</span><span className="numeric">{percent(row.utilization)}</span><span className="bar-durations" id={`${descriptionId}-${row.id}`}>Terisi {duration(row.occupied,true)} · Kosong {duration(row.empty,true)} · Tidak diketahui {duration(row.unknown,true)} · Keterisian {percent(row.utilization)}</span></button>)}
  </div>;
}
export function Heatmap({ intervals, endDate }) {
  const [selected, setSelected] = useState(null);
  const days = Array.from({length:7},(_,i) => dateKey(atDate(endDate)-(6-i)*DAY));
  const hours = [9,10,11,13,14,15,16];
  return <div className="heatmap"><p className="caption">Utilization per jam (%). Sel unknown/di luar cakupan tetap N/A.</p><div className="heatmap-grid" style={{gridTemplateColumns:`100px repeat(${hours.length},minmax(38px,1fr))`}}><span>Hari / jam</span>{hours.map(hour => <span key={hour}>{String(hour).padStart(2,'0')}:00</span>)}{days.map(day => <div className="heatmap-row" key={day}><span>{day.slice(5)}</span>{hours.map(hour => {
    const records = intervals.filter(item => item.start < atDate(day,hour+1) && item.end > atDate(day,hour)).map(item => ({...item,start:Math.max(item.start,atDate(day,hour)),end:Math.min(item.end,atDate(day,hour+1))}));
    const value = summarize(records);
    return <button key={hour} className={`heat-cell ${selected?.day === day && selected?.hour === hour ? 'selected' : ''}`} style={{background:value.utilization == null ? 'var(--surface-raised)' : `color-mix(in srgb, var(--status-occupied) ${Math.round(value.utilization*.38)}%, var(--surface-video))`}} aria-label={`${day} ${hour}:00, utilization ${percent(value.utilization)}, coverage ${percent(value.coverage)}`} onClick={() => setSelected({day,hour,...value})}>{value.utilization == null ? 'N/A' : Math.round(value.utilization)}</button>;
  })}</div>)}</div><div className="selection-detail">{selected ? <>{selected.day} {selected.hour}:00 · Terisi {duration(selected.occupied,true)} · Coverage {percent(selected.coverage)}</> : 'Pilih sel untuk memeriksa durasi dan coverage.'}</div></div>;
}
export function Timeline({ records, workspaces, start, end, onSelect, selectedId, timezone='Asia/Jakarta', gapDescription='Rentang tanpa segmen: di luar jadwal, bukan kosong.' }) {
  const span = Math.max(1,end-start);
  const ticks = Array.from({length:5},(_,i) => start + i*span/4);
  const label=value=>clock(value,timezone,span<60_000);
  return <div className="timeline"><div className="timeline-axis"><span>Workstation</span><div>{ticks.map(t => <time key={t}>{label(t)}</time>)}</div></div>{workspaces.map(w => <div className="timeline-row" key={w.id}><span>{w.name}</span><div className="timeline-track">{records.filter(i => i.workspaceId === w.id).map(item => <button className={`timeline-segment ${item.state.toLowerCase()} ${selectedId === item.id ? 'selected' : ''}`} key={item.id} style={{left:`${100*(item.start-start)/span}%`,width:`${100*(item.end-item.start)/span}%`}} aria-label={`${w.name}, ${label(item.start)}-${label(item.end)}, ${item.state}`} title={`${label(item.start)}-${label(item.end)} ${item.state}`} onClick={() => onSelect(item)}/>)}</div></div>)}<div className="chart-legend">{['OCCUPIED','EMPTY','UNKNOWN'].map(value => <Status key={value} value={value}/>)}<span className="caption">{gapDescription}</span></div></div>;
}
