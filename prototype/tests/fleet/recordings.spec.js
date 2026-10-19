import { test, expect } from '@playwright/test';

test('auto-save data and video persists, rotates files, downloads and stops through settings', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/settings');
  const headers = { Origin: 'http://127.0.0.1:8771' };
  const policy = { data_enabled:false, data_interval_seconds:60, video_enabled:false, video_segment_seconds:60, max_storage_mb:5120 };
  expect((await page.request.post('/pilot/v1/recordings/policy', { headers, data:policy })).ok()).toBeTruthy();
  const added = await page.request.post('/pilot/v1/camera-wall/cameras', { headers, data:{name:'Record browser fixture',url:`rtsp://synthetic.invalid/record-${Date.now()}`} });
  expect(added.ok()).toBeTruthy();
  const camera = await added.json();
  try {
    const calibrated = await page.request.post(`/pilot/v1/camera-wall/cameras/${camera.id}/calibration`, { headers, data:{ source:'RTSP_LIVE', camera_key:camera.camera_key, width:320,height:240,
      zones:[{id:'record-desk',name:'Record test desk',polygon:[[0,0],[1,0],[1,1],[0,1]],exclusive_group:'workstations'}],rules:{occupied_confirm_seconds:.1,empty_confirm_seconds:.1,max_evidence_gap_seconds:3,association_overlap:.25,ambiguity_margin:.1,strong_confidence:.5}} });
    expect(calibrated.ok()).toBeTruthy();
    expect((await page.request.post(`/pilot/v1/camera-wall/cameras/${camera.id}/start`, { headers })).ok()).toBeTruthy();
    await page.reload();
    await expect(page.getByRole('heading',{name:'Auto-save data dan video',exact:true})).toBeVisible();
    await page.getByLabel('Auto-save laporan data',{exact:true}).check();
    await page.getByLabel('Satuan interval simpan data',{exact:true}).selectOption('1');
    await page.getByLabel('Interval simpan data',{exact:true}).fill('5');
    await page.getByLabel('Auto-save rekaman video',{exact:true}).check();
    await page.getByLabel('Satuan durasi potongan video',{exact:true}).selectOption('1');
    await page.getByLabel('Durasi potongan video',{exact:true}).fill('5');
    await page.getByRole('button',{name:'Simpan pengaturan auto-save',exact:true}).click();
    await expect(page.getByTestId('recording-saved-policy')).toContainText('laporan aktif setiap 5 detik; video aktif, potongan 5 detik');
    await expect.poll(async()=>{
      const value = await (await page.request.get('/pilot/v1/recordings')).json();
      return ['data','video'].every(kind=>value.files.some(f=>f.source_id===camera.id&&f.kind===kind));
    },{timeout:45000}).toBe(true);
    const stored = await (await page.request.get('/pilot/v1/recordings')).json();
    expect(stored.errors).toEqual({});
    const data = stored.files.find(f=>f.source_id===camera.id&&f.kind==='data');
    const video = stored.files.find(f=>f.source_id===camera.id&&f.kind==='video');
    const report = await (await page.request.get(`/pilot/v1/recordings/files/${data.id}/json`)).json();
    expect(report.report.workstations[0].workspace).toBe('Record test desk');
    const mp4 = await (await page.request.get(`/pilot/v1/recordings/files/${video.id}/mp4`)).body();
    expect(mp4.subarray(4,8).toString()).toBe('ftyp');
    await page.getByLabel('Jenis file record',{exact:true}).selectOption('data');
    const downloadPromise = page.waitForEvent('download');
    await page.getByTestId('recording-files').getByRole('link',{name:'CSV',exact:true}).first().click();
    expect((await downloadPromise).suggestedFilename()).toMatch(/\.csv$/);
    for (const width of [1440,760]) {
      await page.setViewportSize({width,height:1000});
      await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
      await page.screenshot({path:`verification/screenshots/recording-settings-synthetic-${width}.png`,fullPage:true});
    }
    await page.getByRole('button',{name:'Ringkasan',exact:true}).click();
    await expect.poll(async()=>(await (await page.request.get('/pilot/v1/recordings')).json()).active_videos.some(v=>v.source_id===camera.id)).toBe(true);
    await page.getByRole('button',{name:'Pengaturan',exact:true}).click();
    await expect(page.getByLabel('Auto-save rekaman video',{exact:true})).toBeChecked();
    await page.getByLabel('Auto-save laporan data',{exact:true}).uncheck();
    await page.getByLabel('Auto-save rekaman video',{exact:true}).uncheck();
    await page.getByRole('button',{name:'Simpan pengaturan auto-save',exact:true}).click();
    await expect.poll(async()=>(await (await page.request.get('/pilot/v1/recordings')).json()).active_videos.length).toBe(0);
    await page.reload();
    await expect(page.getByLabel('Auto-save rekaman video',{exact:true})).not.toBeChecked();
    await expect(page.getByLabel('Auto-save laporan data',{exact:true})).not.toBeChecked();
    expect(errors).toEqual([]);
  } finally {
    await page.request.post('/pilot/v1/recordings/policy',{headers,data:policy});
    await page.request.delete(`/pilot/v1/camera-wall/cameras/${camera.id}`,{headers});
  }
});
