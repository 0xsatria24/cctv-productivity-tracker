import { useState } from 'react';
import { Button, Field, Modal } from './components';
import { usePrototype } from './store';

function CameraForm({camera,onClose}) {
  const {saveCamera}=usePrototype();
  const [draft,setDraft]=useState(camera?{...camera}:{name:'',area:'',endpoint:'',fps:5,enabled:true,credentialConfigured:false});
  const [error,setError]=useState('');
  function change(key,value){setDraft(previous=>({...previous,[key]:value}));}
  function submit(event) {
    event.preventDefault();
    try {
      const url=new URL(draft.endpoint);
      if(!['rtsp:','rtsps:'].includes(url.protocol)||!url.hostname||url.username||url.password||/[?&](password|token|secret)=/i.test(url.search))throw new Error();
      if(!draft.name.trim()||!draft.area.trim()||draft.fps<.1||draft.fps>30)throw new Error();
      saveCamera({...draft,name:draft.name.trim(),area:draft.area.trim()});onClose();
    } catch {setError('Isi nama, area, alamat RTSP tanpa kredensial, dan FPS 0,1–30.');}
  }
  return <Modal title={camera?'Edit kamera':'Tambah kamera'} onClose={onClose}><form onSubmit={submit} className="form-grid">
    <Field label="Nama kamera"><input autoFocus required maxLength={100} value={draft.name} onChange={event=>change('name',event.target.value)}/></Field>
    <Field label="Area"><input required maxLength={100} value={draft.area} onChange={event=>change('area',event.target.value)}/></Field>
    <Field label="Alamat RTSP" className="full-width"><input required maxLength={2048} value={draft.endpoint} onChange={event=>change('endpoint',event.target.value)}/></Field>
    <Field label="Target inferensi (FPS)"><input type="number" min="0.1" max="30" step="0.1" value={draft.fps} onChange={event=>change('fps',Number(event.target.value))}/></Field>
    <p className="caption full-width">Konfigurasi disimpan di browser. Hubungkan layanan Python untuk membuka stream kamera.</p>
    {error&&<p className="error-text full-width" role="alert">{error}</p>}
    <div className="form-actions full-width"><Button type="button" onClick={onClose}>Batal</Button><Button type="submit" variant="primary">Simpan kamera</Button></div>
  </form></Modal>;
}

export default function Dialogs() {
  const {dialog,setDialog}=usePrototype();
  if(!dialog)return null;
  const close=()=>setDialog(null);
  if(dialog.type==='camera')return <CameraForm camera={dialog.camera} onClose={close}/>;
  if(dialog.type==='discard')return <Modal title="Buang perubahan?" onClose={close} footer={<><Button onClick={close}>Batal</Button><Button variant="danger" onClick={()=>{dialog.onConfirm();close();}}>Buang perubahan</Button></>}/>;
  if(dialog.type==='revision')return <Modal title="Simpan zona?" onClose={close} footer={<><Button onClick={close}>Batal</Button><Button onClick={()=>{dialog.onConfirm();close();}}>Simpan zona</Button></>}/>;
  return <Modal title="Detail" onClose={close}><p>{dialog.event?.message||'Belum ada catatan observasi.'}</p></Modal>;
}
