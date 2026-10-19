import { test, expect } from '@playwright/test';

test('archive active camera shows progress, inline failure, retry and retained reports', async ({page}) => {
  await page.goto('/#/live');
  const headers = {Origin:'http://127.0.0.1:8771'};
  const created = await page.request.post('/pilot/v1/camera-wall/cameras', {headers,data:{name:'UJI hapus kamera aktif',url:'rtsp://localhost/archive-ui'}});
  expect(created.ok()).toBeTruthy();
  const camera = await created.json();
  const base = `/pilot/v1/camera-wall/cameras/${camera.id}`;
  let archived = false;
  try {
    expect((await page.request.post(`${base}/calibration`,{headers,data:{source:'RTSP_LIVE',width:320,height:240,camera_key:camera.camera_key,
      zones:[{id:'test-zone',name:'Zona sintetis',polygon:[[0,0],[1,0],[1,1],[0,1]]}],rules:{occupied_confirm_seconds:.1,empty_confirm_seconds:.1}}})).ok()).toBeTruthy();
    expect((await page.request.post(`${base}/start`,{headers})).ok()).toBeTruthy();
    await expect.poll(async()=>{
      const wall = await (await page.request.get('/pilot/v1/camera-wall')).json();
      return wall.cameras.find(c=>c.id===camera.id)?.engine.processed || 0;
    }, {timeout:45000}).toBeGreaterThan(3);
    await page.getByRole('button',{name:`Hapus ${camera.name}`,exact:true}).click();
    const dialog = page.getByRole('dialog',{name:'Arsipkan kamera?'});
    let release;
    const blocked = new Promise(resolve=>{release=resolve;});
    let deletes=0;
    await page.route(`**${base}`,async route=>{
      if(route.request().method()!=='DELETE') return route.continue();
      deletes++;
      await blocked;
      await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'UJI: kamera belum selesai dihentikan'})});
    });
    await dialog.getByRole('button',{name:'Hapus kamera',exact:true}).click();
    await expect(dialog.getByRole('button',{name:'Mengarsipkan...'})).toBeDisabled();
    await expect(dialog.getByRole('button',{name:'Batal',exact:true})).toBeDisabled();
    await expect(dialog.getByRole('status')).toContainText('menyimpan catatan terakhir');
    expect(deletes).toBe(1);
    release();
    await expect(dialog.getByRole('alert')).toHaveText('UJI: kamera belum selesai dihentikan');
    await expect(dialog.getByRole('button',{name:'Hapus kamera',exact:true})).toBeEnabled();
    await page.unroute(`**${base}`);
    const removed = page.waitForResponse(r=>r.url().endsWith(base)&&r.request().method()==='DELETE');
    await dialog.getByRole('button',{name:'Hapus kamera',exact:true}).click();
    expect((await removed).status()).toBe(200);
    archived=true;
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole('button',{name:`Hapus ${camera.name}`,exact:true})).toHaveCount(0);
    await expect(page.getByTestId('camera-wall-grid').getByText(camera.name,{exact:true})).toHaveCount(0);
    const report = await page.request.get(`/pilot/v1/reports?dataset=live&camera_id=${camera.id}`);
    expect(report.ok()).toBeTruthy();
    expect((await report.json()).workstations.length).toBeGreaterThan(0);
  } finally {
    await page.unroute(`**${base}`);
    if(!archived) await page.request.delete(base,{headers});
  }
});
