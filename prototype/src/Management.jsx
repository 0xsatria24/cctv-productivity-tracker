import { useEffect, useState } from 'react';
import { Button, DataTable, Empty, Field, Panel, Status } from './components';
import { usePrototype } from './store';
import { useLanguage } from './language';
import { SettingsTools } from './settings-tools';

export function Cameras({showAdd=true}) {
  const {state,setDialog}=usePrototype();
  return <Panel title="Kamera" action={showAdd&&<Button onClick={()=>setDialog({type:'camera'})}>Tambah kamera</Button>}><DataTable rows={state.cameras} columns={[{key:'name',label:'Nama kamera'},{key:'area',label:'Area'},{key:'status',label:'Koneksi',render:camera=><Status value={camera.status}/>},{key:'action',label:'Konfigurasi',render:camera=><Button onClick={()=>setDialog({type:'camera',camera})}>Edit kamera</Button>}]} empty={<Empty title="Belum ada kamera"/>}/></Panel>;
}

export function Settings() {
  const {language,setLanguage,t}=useLanguage();
  const {state,setState,notify}=usePrototype();
  const [draft,setDraft]=useState({...state.settings});
  useEffect(()=>setDraft({...state.settings}),[state.settings]);
  function save(event) {
    event.preventDefault();
    setState(previous=>({...previous,settings:{...previous.settings,site:draft.site.trim(),timezone:draft.timezone}}));
    notify(t('Pengaturan lokal disimpan.'));
  }
  return <><Panel title="Lokasi"><form className="form-grid settings-form" onSubmit={save}>
    <Field label="Bahasa"><select value={language} onChange={event=>setLanguage(event.target.value)}><option value="id">Bahasa Indonesia</option><option value="en">English</option></select></Field>
    <Field label="Nama lokasi"><input maxLength={100} value={draft.site} onChange={event=>setDraft(previous=>({...previous,site:event.target.value}))}/></Field>
    <Field label="Zona waktu"><select value={draft.timezone} onChange={event=>setDraft(previous=>({...previous,timezone:event.target.value}))}><option value="Asia/Jakarta">Asia/Jakarta</option><option value="Asia/Bangkok">Asia/Bangkok</option></select></Field>
    <div className="form-actions full-width"><Button type="submit" variant="primary">Simpan pengaturan</Button></div>
    <p className="caption full-width">{t('Koneksi kamera, rekaman, dan pengaturan engine tersedia saat aplikasi terhubung ke layanan Python.')}</p>
  </form></Panel><SettingsTools/></>;
}
