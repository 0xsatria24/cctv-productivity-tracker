import { test, expect } from '@playwright/test';

test('box timer survives zone visit gaps and visible status is only Working or Idle', async ({page}) => {
  await page.goto('/#/live');
  const headers = {Origin:'http://127.0.0.1:8771'};
  const created = await page.request.post('/pilot/v1/camera-wall/cameras',{headers,data:{name:'UJI timer aktivitas',url:'rtsp://localhost/activity-caption'}});
  const camera = await created.json(), base = `/pilot/v1/camera-wall/cameras/${camera.id}`;
  let current = {label:'Working',elapsed:10_000_000,confidence:.9};
  try {
    expect((await page.request.post(`${base}/calibration`,{headers,data:{source:'RTSP_LIVE',width:320,height:240,camera_key:camera.camera_key,
      zones:[{id:'zone',name:'Zona sintetis',polygon:[[0,0],[1,0],[1,1],[0,1]]}],rules:{occupied_confirm_seconds:.1,empty_confirm_seconds:.1}}})).ok()).toBeTruthy();
    expect((await page.request.post(`${base}/start`,{headers})).ok()).toBeTruthy();
    await page.route(`**${base}/observation?metadata_only=true`,async route=>{
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({sequence:1,source_age_ms:0,valid_for_ms:1400,
        observation:{count:1,inference_ms:100,detections:[{track_id:'test:1',box:[.2,.2,.6,.9],confidence:current.confidence,workstation_times:[],
          activity:{label:current.label,tracked_elapsed_us:current.elapsed,basis:'visible_motion'}}]}})});
    });
    await page.getByLabel('Deteksi',{exact:true}).check();
    const tile=page.getByTestId('camera-tile').filter({has:page.getByRole('heading',{name:camera.name,exact:true})});
    await expect(tile.getByTestId('track-activity-label')).toHaveText('Working');
    await expect(tile.getByTestId('rtsp-presence-clock')).toHaveText('00:00:10');
    current={label:'Idle',elapsed:11_000_000,confidence:.2};
    await expect(tile.getByTestId('track-activity-label')).toHaveText('Idle');
    await expect(tile.getByTestId('rtsp-presence-clock')).toHaveText('00:00:11');
    current={label:'Working',elapsed:12_000_000,confidence:.8};
    await expect(tile.getByTestId('track-activity-label')).toHaveText('Working');
    await expect(tile.getByTestId('rtsp-presence-clock')).toHaveText('00:00:12');
    expect(await tile.getByTestId('rtsp-person-detection').locator('text').allTextContents()).toEqual(['Working','00:00:12']);
  } finally {
    await page.unroute(`**${base}/observation?metadata_only=true`);
    await page.request.delete(base,{headers});
  }
});
