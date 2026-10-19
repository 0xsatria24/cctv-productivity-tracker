import { test, expect } from '@playwright/test';

test('video refresh is independent of measured tracking and expired boxes disappear', async ({page}) => {
  await page.goto('/#/live');
  const headers = {Origin:'http://127.0.0.1:8771'};
  const created = await page.request.post('/pilot/v1/camera-wall/cameras',{headers,data:{name:'UJI tracking lambat',url:'rtsp://localhost/slow-overlay'}});
  const camera = await created.json(), base = `/pilot/v1/camera-wall/cameras/${camera.id}`;
  let release;
  const blocked = new Promise(resolve=>{release=resolve;});
  let observationReads=0, imageReads=0;
  try {
    expect((await page.request.post(`${base}/calibration`,{headers,data:{source:'RTSP_LIVE',width:320,height:240,camera_key:camera.camera_key,
      zones:[{id:'test-zone',name:'Zona sintetis',polygon:[[0,0],[1,0],[1,1],[0,1]]}],rules:{occupied_confirm_seconds:.1,empty_confirm_seconds:.1}}})).ok()).toBeTruthy();
    expect((await page.request.post(`${base}/start`,{headers})).ok()).toBeTruthy();
    await expect.poll(async()=>{
      const wall=await (await page.request.get('/pilot/v1/camera-wall')).json();
      return wall.cameras.find(c=>c.id===camera.id)?.engine.processed || 0;
    }).toBeGreaterThan(2);
    await page.route(`**${base}/frame.jpg*`,async route=>{imageReads++;await route.continue();});
    await page.route(`**${base}/observation?metadata_only=true`,async route=>{
      observationReads++;
      if(observationReads===1) {
        await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({sequence:1,utc_ms:Date.now(),source_age_ms:900,result_age_ms:50,valid_for_ms:1300,
          observation:{count:1,inference_ms:850,detections:[{box:[.2,.2,.6,.9],confidence:.6,track_id:'test:1',activity:{label:'Working',tracked_elapsed_us:123000000}}]}})});
      } else {
        await blocked;
        await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({sequence:2,valid_for_ms:1400,observation:{count:0,inference_ms:100,detections:[]}})});
      }
    });
    await page.getByLabel('Deteksi',{exact:true}).check();
    await page.getByRole('button',{name:'Grid',exact:true}).click();
    const tile=page.getByTestId('camera-tile').filter({has:page.getByRole('heading',{name:camera.name,exact:true})});
    const boxes=tile.getByTestId('rtsp-person-detection');
    await expect(boxes).toHaveCount(1);
    await expect(boxes.getByTestId('track-activity-label')).toHaveText('Working');
    await expect(boxes.getByTestId('rtsp-presence-clock')).toHaveText('00:02:03');
    const imagesBefore=imageReads;
    await expect.poll(()=>imageReads,{timeout:1200}).toBeGreaterThan(imagesBefore+4);
    expect(observationReads).toBeLessThan(imageReads);
    // No result or network keepalive can make the old box live indefinitely.
    await expect(boxes).toHaveCount(0,{timeout:2500});
    await expect(tile.getByRole('img',{name:`Preview ${camera.name}`,exact:true})).toBeVisible();
    release();
    await expect(tile.getByTestId('rtsp-detection-status')).toContainText('0 orang terdeteksi');
  } finally {
    release();
    await page.unroute(`**${base}/observation?metadata_only=true`);
    await page.unroute(`**${base}/frame.jpg*`);
    await page.request.delete(base,{headers});
  }
});
