import { Children, cloneElement, isValidElement, useEffect, useId, useMemo, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Info, X } from 'lucide-react';
import { CAMERA_LABELS, LABELS, clock, duration, percent } from './domain';
import { usePrototype } from './store';
import { useLanguage } from './language';

export function Button({ children, variant = 'secondary', icon: Icon, className = '', ...props }) { const {t}=useLanguage();return <button className={`button ${variant} ${className}`} {...props}>{Icon && <Icon size={15} aria-hidden="true"/>}{t(children)}</button>; }
export function Status({ value, label }) { const {t}=useLanguage();return <span className={`status ${value?.toLowerCase()}`}><span className="status-mark" aria-hidden="true"/>{t(label || LABELS[value] || CAMERA_LABELS[value] || value)}</span>; }
export function Panel({ title, caption, action, children, className = '' }) { const {t}=useLanguage();return <section className={`panel ${className}`}><div className="panel-heading"><div><h2>{t(title)}</h2>{caption && <p>{t(caption)}</p>}</div>{action}</div>{children}</section>; }
export function Field({ label, hint, children, className = '' }) {
  const {t}=useLanguage();
  const generatedId=useId();let controlId=generatedId,attached=false;
  function attach(child) {
    if(!isValidElement(child))return t(child);
    if(!attached&&['input','select','textarea'].includes(child.type)) {
      attached=true;controlId=child.props.id||generatedId;
      return cloneElement(child,{id:controlId,...(hint?{'aria-describedby':`${generatedId}-hint`}:{}),...(child.props.children?{children:Children.map(child.props.children,attach)}:{})});
    }
    return child.props.children?cloneElement(child,{children:Children.map(child.props.children,attach)}):child;
  }
  const controls=Children.map(children,attach);
  return <div className={`field ${className}`}><label htmlFor={controlId}>{t(label)}</label>{controls}{hint&&<small id={`${generatedId}-hint`}>{t(hint)}</small>}</div>;
}
export function Empty({ title = 'Belum ada data', description = '', action }) { const {t}=useLanguage();return <div className="empty-state"><h3>{t(title)}</h3>{description&&<p>{t(description)}</p>}{action}</div>; }
export function MetricStrip({ metrics, small = false }) {
  const { setDialog } = usePrototype();
  return <div className={`metric-strip ${small ? 'compact' : ''}`}>
    {[['Durasi terisi', duration(metrics.occupied, true), 'OCCUPIED'], ['Durasi kosong', duration(metrics.empty, true), 'EMPTY'], ['Tidak diketahui', duration(metrics.unknown, true), 'UNKNOWN'], ['Utilization', percent(metrics.utilization), ''], ['Coverage observasi', percent(metrics.coverage), '']].map(([label, value, status]) => <div key={label}><span>{label}</span><strong className={status.toLowerCase()}>{metrics.eligible === 0 && status ? 'N/A' : value}</strong></div>)}
    <button className="metric-help icon-button" aria-label="Definisi metrik" title="Definisi metrik" onClick={() => setDialog({ type: 'definitions' })}><Info size={16}/></button>
  </div>;
}
export function Modal({ title, description, children, onClose, wide = false, footer }) {
  const {t}=useLanguage();
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current, previous = document.activeElement;
    element.showModal();
    return () => { if (element.open) element.close(); if (previous instanceof HTMLElement && document.contains(previous)) previous.focus(); };
  }, []);
  return <dialog className={`modal ${wide ? 'wide' : ''}`} ref={dialog} aria-labelledby="modal-title" aria-describedby={description ? 'modal-description' : undefined} onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="modal-heading"><div><h2 id="modal-title">{t(title)}</h2>{description && <p id="modal-description">{t(description)}</p>}</div><button className="icon-button" aria-label={t('Tutup dialog')} onClick={onClose}><X size={18}/></button></div>
    <div className="modal-body">{children}</div>{footer && <div className="modal-footer">{footer}</div>}
  </dialog>;
}
export function DataTable({ columns, rows, pageSize = 8, resetKey = '', empty, testId }) {
  const [page, setPage] = useState(1), [sort, setSort] = useState(null);
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  useEffect(() => setPage(1), [resetKey]);
  useEffect(() => setPage(previous => Math.min(previous, totalPages)), [totalPages]);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find(item => item.key === sort.key);
    return [...rows].sort((a, b) => { const left = column.accessor ? column.accessor(a) : a[sort.key], right = column.accessor ? column.accessor(b) : b[sort.key]; return (typeof left === 'number' && typeof right === 'number' ? left - right : String(left ?? '').localeCompare(String(right ?? ''), 'id')) * sort.direction; });
  }, [rows, sort, columns]);
  const shown = sorted.slice((page - 1) * pageSize, page * pageSize);
  return <div className="data-table" data-testid={testId}><div className="table-scroll"><table><thead><tr>{columns.map(column => <th key={column.key} className={column.numeric ? 'numeric' : ''}>{column.sortable === false ? column.label : <button className="table-sort" onClick={() => { setSort(previous => ({ key: column.key, direction: previous?.key === column.key ? -previous.direction : 1 })); setPage(1); }} aria-label={`Urutkan ${column.label}`}>{column.label}{sort?.key === column.key && (sort.direction === 1 ? <ArrowUp size={12}/> : <ArrowDown size={12}/>)}</button>}</th>)}</tr></thead><tbody>{shown.map(row => <tr key={row.id}>{columns.map(column => <td className={column.numeric ? 'numeric' : ''} key={column.key}>{column.render ? column.render(row) : row[column.key]}</td>)}</tr>)}</tbody></table></div>{!shown.length && (empty || <Empty/>)}
    <div className="table-pagination"><span>{rows.length ? `${(page - 1) * pageSize + 1}-${Math.min(page * pageSize, rows.length)} dari ${rows.length}` : '0 hasil'}</span><div><Button icon={ChevronLeft} aria-label="Halaman sebelumnya" disabled={page === 1} onClick={() => setPage(p => p - 1)}>Sebelumnya</Button><span>{page} / {totalPages}</span><Button icon={ChevronRight} aria-label="Halaman berikutnya" disabled={page === totalPages} onClick={() => setPage(p => p + 1)}>Berikutnya</Button></div></div>
  </div>;
}
export function EventList({ events, onSelect, limit = 6 }) {
  const { state } = usePrototype();
  return events.length ? <div className="event-list">{events.slice(0, limit).map(event => <button key={event.id} className="event-row" onClick={() => onSelect(event)}><time>{clock(event.time, state.settings.timezone, true)}</time><span><strong>{event.message}</strong><small>{event.type} · {event.cameraId || 'Sistem'}</small></span><ChevronRight size={14}/></button>)}</div> : <Empty title="Belum ada event"/>;
}
