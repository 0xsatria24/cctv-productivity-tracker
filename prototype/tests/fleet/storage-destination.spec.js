import { test, expect } from '@playwright/test';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

const headers={Origin:'http://127.0.0.1:8771'};
const local={enabled:false,kind:'local',folder:'',remote:'',prefix:'CCTV',endpoint:'',bucket:'',region:'us-east-1',provider:'Other',access_key:'',secret_key:'',session_token:''};
const policy={data_enabled:false,data_interval_seconds:60,video_enabled:false,video_segment_seconds:60,max_storage_mb:5120};

test('storage settings copy data and video to a server folder and safely configure cloud destinations',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/#/settings');
  await page.request.post('/pilot/v1/recordings/policy',{headers,data:policy});
  await page.request.post('/pilot/v1/recordings/destination',{headers,data:local});
  await page.reload();
  const folder=path.resolve(process.cwd(),'../runtime/destination-browser-nas');
  const prefix='UI-'+Date.now();
  let session;
  try{
    await expect(page.getByRole('heading',{name:'Tujuan penyimpanan auto-save',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Atur tujuan penyimpanan',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Tujuan penyimpanan auto-save',exact:true})).toBeInViewport();
    await page.getByLabel('Simpan salinan ke',{exact:true}).selectOption('folder');
    await page.getByLabel('Folder tujuan server / NAS',{exact:true}).fill(folder);
    await page.getByLabel('Subfolder / prefix tujuan',{exact:true}).fill(prefix);
    await page.getByRole('button',{name:'Simpan tujuan penyimpanan',exact:true}).click();
    await expect(page.getByTestId('record-destination-saved')).toContainText('Folder pilihan / server lokal / NAS · pengiriman aktif');
    await page.getByRole('button',{name:'Uji koneksi tujuan',exact:true}).click();
    await expect(page.getByRole('status').filter({hasText:'Koneksi berhasil: file uji ditulis'})).toBeVisible();
    const live=await(await page.request.get('/pilot/v1/live')).json();
    if(['STARTING','RUNNING','STOPPING'].includes(live.status)){
      await page.request.post('/pilot/v1/live/stop',{headers,data:{session_id:live.session_id}});
      await expect.poll(async()=>(await(await page.request.get('/pilot/v1/live')).json()).status).toBe('STOPPED');
    }
    const calibrated=await page.request.post('/pilot/v1/live/calibration',{headers,data:{source:'WEBCAM_LIVE',camera_key:'a'.repeat(64),width:320,height:240,
      zones:[{id:'upload-desk',name:'Synthetic upload desk',polygon:[[0,0],[1,0],[1,1],[0,1]],exclusive_group:'workstations'}],rules:{occupied_confirm_seconds:.1,empty_confirm_seconds:.1,max_evidence_gap_seconds:3}}});
    expect(calibrated.ok()).toBeTruthy();
    const started=await page.request.post('/pilot/v1/live/start',{headers,data:{source:'WEBCAM_LIVE',camera_key:'a'.repeat(64)}});
    expect(started.ok()).toBeTruthy();session=(await started.json()).session_id;
    await expect.poll(async()=>(await(await page.request.get('/pilot/v1/live')).json()).status,{timeout:30000}).toBe('RUNNING');
    const before=new Set((await(await page.request.get('/pilot/v1/recordings')).json()).files.map(file=>file.id));
    expect((await page.request.post('/pilot/v1/recordings/policy',{headers,data:{...policy,data_enabled:true,data_interval_seconds:5,video_enabled:true,video_segment_seconds:5}})).ok()).toBeTruthy();
    const image=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=320;canvas.height=240;const ctx=canvas.getContext('2d');ctx.fillStyle='#456050';ctx.fillRect(0,0,320,240);ctx.fillStyle='white';ctx.fillText('SYNTHETIC UPLOAD TEST',10,30);return canvas.toDataURL('image/jpeg').split(',')[1];});
    let sequence=0,files=[];
    await expect.poll(async()=>{
      const response=await page.request.post('/pilot/v1/webcam/frame',{headers:{...headers,'Content-Type':'image/jpeg','X-Live-Session':session,'X-Frame-Sequence':String(++sequence)},data:Buffer.from(image,'base64')});
      expect(response.ok()).toBeTruthy();
      files=(await(await page.request.get('/pilot/v1/recordings')).json()).files.filter(file=>!before.has(file.id));
      return files.some(file=>file.source_id==='webcam'&&file.kind==='video')&&files.some(file=>file.source_id==='primary'&&file.kind==='data');
    },{timeout:25000,intervals:[500]}).toBe(true);
    await page.request.post('/pilot/v1/recordings/policy',{headers,data:policy});
    const video=files.find(file=>file.source_id==='webcam'&&file.kind==='video');
    const data=files.find(file=>file.source_id==='primary'&&file.kind==='data');
    for(const [item,extension]of[[video,'mp4'],[data,'report.json'],[data,'csv']]){
      const destination=path.join(folder,prefix,item.id,`${item.id}.${extension}`);
      await expect.poll(()=>existsSync(destination),{timeout:20000}).toBe(true);
      const format=extension==='report.json'?'json':extension;
      expect(readFileSync(destination)).toEqual(await(await page.request.get(`/pilot/v1/recordings/files/${item.id}/${format}`)).body());
    }
    await expect(page.getByTestId('record-upload-jobs')).toContainText('Terkirim');
    await page.getByLabel('Simpan salinan ke',{exact:true}).selectOption('s3');
    await page.getByLabel('Aktifkan pengiriman ke tujuan',{exact:true}).uncheck();
    await page.getByLabel('Endpoint API S3',{exact:true}).fill('https://fixture.example.invalid');
    await page.getByLabel('Bucket S3',{exact:true}).fill('records');
    await page.getByLabel('Access key S3',{exact:true}).fill('browser-fixture-access');
    await page.getByLabel('Secret key S3',{exact:true}).fill('browser-fixture-secret');
    await page.getByRole('button',{name:'Simpan tujuan penyimpanan',exact:true}).click();
    await expect(page.getByTestId('record-destination-saved')).toContainText('S3 compatible / MinIO · pengiriman nonaktif');
    await expect(page.getByLabel('Secret key S3',{exact:true})).toHaveValue('');
    const cloud=await page.request.get('/pilot/v1/recordings/destination');
    expect(await cloud.text()).not.toContain('browser-fixture-secret');
    await page.reload();
    await expect(page.getByLabel('Endpoint API S3',{exact:true})).toHaveValue('https://fixture.example.invalid');
    await expect(page.getByLabel('Secret key S3',{exact:true})).toHaveValue('');
    for(const width of[1440,760]){
      await page.setViewportSize({width,height:1000});
      await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
      await page.screenshot({path:`verification/screenshots/record-destination-synthetic-${width}.png`,fullPage:true});
    }
    await page.getByLabel('Simpan salinan ke',{exact:true}).selectOption('rclone');
    await page.getByRole('button',{name:'Perbarui daftar cloud',exact:true}).click();
    await expect(page.getByRole('button',{name:'Perbarui daftar cloud',exact:true})).toBeEnabled();
    await expect(page.getByLabel('Nama remote cloud',{exact:true})).toBeEnabled();
    expect(errors).toEqual([]);
  }finally{
    await page.request.post('/pilot/v1/recordings/policy',{headers,data:policy});
    if(session)await page.request.post('/pilot/v1/live/stop',{headers,data:{session_id:session}});
    await page.request.post('/pilot/v1/recordings/destination',{headers,data:local});
  }
});
