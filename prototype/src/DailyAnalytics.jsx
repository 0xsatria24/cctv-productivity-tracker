import { Download } from 'lucide-react';
import { Button, DataTable, Empty, Panel } from './components';
import { displayTime, durationClock, ratio } from './engine-client';
import { localInput, periodRange } from './operations-domain.mjs';

export function selectToday(engine) {
  const timezone = engine.snapshot?.timezone || 'Asia/Jakarta';
  const now = Date.now() * 1000;
  const date = localInput(now, timezone).slice(0, 10);
  const range = periodRange('day', date, timezone);
  engine.setSelection('ALL');
  engine.setFilters(previous => ({ ...previous, start: range.start, end: Math.min(now, range.end), period:'day' }));
}

export default function DailyAnalytics({ engine, onTimeline }) {
  const rows = engine.report?.daily || [];
  const timezone = engine.snapshot?.timezone || 'Asia/Jakarta';
  const columns = [
    { key: 'date', label: 'Tanggal' },
    { key: 'workspace', label: 'Area / workstation' },
    ...[['occupied_us', 'Terisi'], ['empty_us', 'Kosong'], ['unknown_us', 'Tidak teramati']].map(([key, label]) => ({ key, label, numeric: true, render: row => durationClock(row[key]) })),
    { key: 'coverage', label: 'Coverage', numeric: true, render: row => ratio(row.coverage) },
    { key: 'first_seen_utc_us', label: 'Pertama terisi', render: row => row.first_seen_utc_us == null ? 'Belum teramati' : displayTime(row.first_seen_utc_us, timezone) },
    { key: 'last_seen_utc_us', label: 'Terakhir terisi', render: row => row.last_seen_utc_us == null ? 'Belum teramati' : displayTime(row.last_seen_utc_us, timezone) },
    { key: 'status', label: 'Status', sortable: false, render: row => row.provisional ? 'Sementara' : row.partial_day ? 'Rentang parsial' : 'Satu hari penuh' },
    { key: 'detail', label: 'Detail', sortable: false, render: row => <Button disabled={engine.reportLoading} onClick={() => onTimeline(row)}>Lihat timeline</Button> },
  ];
  return <Panel title="Rekap kehadiran area harian" caption={`Durasi HH:MM:SS · ${timezone} · berdasarkan interval yang tersimpan`} action={<div className="header-actions"><Button disabled={engine.reportLoading} onClick={() => selectToday(engine)}>Hari ini</Button><Button icon={Download} disabled={engine.exporting || engine.reportLoading || !rows.length || !!engine.connectionError} onClick={() => engine.exportCsv('daily')}>Ekspor rekap harian</Button></div>}>
    <div className="daily-analytics-notes"><p className="caption">Satu baris untuk setiap zona per hari. Durasi menunjukkan keterisian zona, bukan jam kerja individu atau hasil kerja.</p>
    <p className="caption">Gunakan filter shift untuk membatasi jam; istirahat belum dipotong otomatis. Rekap hari ini bersifat sementara sampai waktu filter diterapkan.</p></div>
    <div aria-busy={engine.reportLoading}>{engine.reportLoading ? <p role="status">Memuat rekap harian...</p> : <DataTable testId="engine-daily-analytics" columns={columns} rows={rows} resetKey={JSON.stringify(engine.filters) + engine.selection} empty={<Empty title="Belum ada rekap harian" description="Pilih periode yang memiliki observasi tersimpan. Identitas worker tetap anonim."/>}/>}</div>
  </Panel>;
}
