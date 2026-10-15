import { useEffect, useState } from 'react';
import { Button, Field, Modal, Panel } from './components';
import { engineRequest } from './engine-client';

export function MaintenancePanel({ engine }) {
  const [data, setData] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false), [restore, setRestore] = useState(null);
  const [days, setDays] = useState('30'), [enabled, setEnabled] = useState(true), [dirty, setDirty] = useState(false);
  useEffect(() => {
    const abort = new AbortController(); let timer;
    async function poll() {
      try { const result = await engineRequest('maintenance', { signal: abort.signal }); if (!abort.signal.aborted) { setData(result); setError(''); } }
      catch (failure) { if (!abort.signal.aborted) setError(failure.message); }
      finally { if (!abort.signal.aborted) timer = setTimeout(poll, 2000); }
    }
    poll(); return () => { abort.abort(); clearTimeout(timer); };
  }, []);
  useEffect(() => { if (data && !dirty) { setEnabled(data.policy.enabled); setDays(String(data.policy.keep_days)); } }, [data, dirty]);
  async function action(path, body) {
    setBusy(true); setError('');
    try { return await engineRequest(`maintenance/${path}`, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(60000) }); }
    catch (failure) { setError(failure.message); throw failure; }
    finally { setBusy(false); }
  }
  function formatTime(value) { return value ? new Date(value * 1000).toLocaleString('id-ID', { timeZone: engine.snapshot?.timezone || 'Asia/Jakarta' }) : 'Belum ada'; }
  return <Panel title="Backup dan pemulihan" caption="Database, kalibrasi, dan konfigurasi kamera dicadangkan di mesin ini. Video tidak disimpan.">
    <p>Backup terakhir: <strong>{formatTime(data?.state.last_success)}</strong>{data?.busy ? ' · Backup sedang berjalan' : ''}</p>
    <div className="inline-controls"><Button variant="primary" disabled={busy || !data || data.busy} onClick={() => action('backup').then(() => engine.toast('Backup dimulai. Hasilnya akan muncul setelah verifikasi selesai.')).catch(() => {})}>Buat backup sekarang</Button>
      <label className="check-control"><input type="checkbox" checked={enabled} onChange={e => { setEnabled(e.target.checked); setDirty(true); }}/>Backup otomatis setiap 24 jam</label>
      <Field label="Simpan backup (hari)"><input type="number" min="1" max="365" value={days} onChange={e => { setDays(e.target.value); setDirty(true); }}/></Field>
      <Button disabled={!dirty || busy || !Number.isInteger(Number(days)) || Number(days) < 1 || Number(days) > 365} onClick={() => action('policy', { enabled, keep_days: Number(days) }).then(result => { setData(result); setDirty(false); engine.toast('Jadwal backup disimpan.'); }).catch(() => {})}>Simpan jadwal backup</Button>
    </div>
    <p className="caption">Jadwal berjalan selama engine aktif. Dua backup terbaru dan backup sebelum restore tetap dipertahankan. Pemulihan kredensial Windows memerlukan akun dan mesin asal.</p>
    {(error || data?.state.last_error) && <p role="alert" className="error-text">{error || data.state.last_error}</p>}
    <div className="table-scroll"><table><thead><tr><th>Waktu</th><th>Ukuran</th><th>Asal</th><th>Tindakan</th></tr></thead><tbody>{data?.backups.map(item => <tr key={item.id}><td>{formatTime(item.created_at)}</td><td>{(item.bytes / 1048576).toFixed(1)} MB</td><td>{item.reason === 'scheduled' ? 'Terjadwal' : item.reason === 'pre-restore' ? 'Sebelum pemulihan' : 'Manual'}</td><td><div className="inline-controls"><Button disabled={busy} onClick={() => action(`backups/${item.id}/verify`).then(() => engine.toast('Checksum, skema, dan integritas database backup valid.')).catch(() => {})}>Verifikasi</Button><Button onClick={() => setRestore(item)}>Panduan restore</Button></div></td></tr>)}</tbody></table></div>
    {data && !data.backups.length && <p>Belum ada backup. Buat backup pertama sebelum menjalankan pilot.</p>}
    {data?.restore_receipt && <p>Pemulihan terakhir selesai: {formatTime(data.restore_receipt.completed_at)}</p>}
    {restore && <Modal title="Pulihkan backup" description="Restore mengganti database dan konfigurasi dengan snapshot yang dipilih. Aplikasi harus berhenti agar tidak ada proses yang menulis saat pemulihan." onClose={() => setRestore(null)}><ol><li>Hentikan aplikasi dan supervisor/service.</li><li>Jalankan perintah berikut di PowerShell dari folder instalasi.</li><li>Setelah hasil verified: true, jalankan aplikasi kembali.</li></ol><pre className="maintenance-command">{`${data.restore_command} --backup-id '${restore.id}'`}</pre><p>Backup pengaman dibuat sebelum perubahan. Jika proses terputus, jalankan perintah yang sama untuk menyelesaikan restore.</p><div className="modal-actions"><Button onClick={() => navigator.clipboard.writeText(`${data.restore_command} --backup-id '${restore.id}'`).then(() => engine.toast('Perintah restore disalin.')).catch(() => engine.toast('Clipboard tidak tersedia. Salin perintah secara manual.'))}>Salin perintah</Button><Button onClick={() => setRestore(null)}>Tutup</Button></div></Modal>}
  </Panel>;
}
