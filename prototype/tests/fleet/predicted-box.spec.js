import { test, expect } from '@playwright/test';

test('predicted box expires without extending detection count or showing an activity claim', async ({page}) => {
  await page.goto('/#/live');
  const headers={Origin:'http://127.0.0.1:8771'};
  const response=await page.request.post('/pilot/v1/camera-wall/cameras',{headers,data:{name:'UJI prediksi sementara',url:'rtsp://localhost/predicted-box'}});
  const camera=await response.json(),base=`/pilot/v1/camera-wall/cameras/${camera.id}`;
  let reads=0,receiving=true;
  try {
    expect((await page.request.post(`${base}/calibration`,{headers,data:{source:'RTSP_LIVE',width:320,height:240,camera_key:camera.camera_key,
      zones:[{id:'zone',name:'Zona sintetis',polygon:[[0,0],[1,0],[1,1],[0,1]]}],rules:{occupied_confirm_seconds:.1,empty_confirm_seconds:.1}}})).ok()).toBeTruthy();
    expect((await page.request.post(`${base}/start`,{headers})).ok()).toBeTruthy();
    await page.getByLabel('Deteksi',{exact:true}).check();
    await page.getByRole('button',{name:'Grid',exact:true}).click();
    const tile=page.getByTestId('camera-tile').filter({has:page.getByRole('heading',{name:camera.name,exact:true})});
    await expect(tile.getByRole('img',{name:`Preview ${camera.name}`,exact:true})).toBeVisible();
    await page.route(`**${base}/observation?metadata_only=true`,async route=>{
      if (!receiving) { await route.abort(); return; }
      reads++;
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({sequence:1,source_age_ms:100,valid_for_ms:1400,
        observation:{count:0,inference_ms:100,detections:[],display_predictions:[{track_id:'camera:0:1',box:[.2,.2,.6,.9],
          evidence:'PREDICTED',valid_for_ms:900,activity:{label:null,tracked_elapsed_us:10_000_000}}]}})});
    });
    const predicted=tile.getByTestId('rtsp-person-prediction');
    await expect(predicted).toHaveCount(1);
    await expect(tile.getByTestId('rtsp-person-detection')).toHaveCount(0);
    await expect(tile.getByTestId('rtsp-detection-status')).toContainText('0 orang terdeteksi');
    await expect(predicted.getByTestId('track-activity-label')).toHaveCount(0);
    await expect(predicted.locator('rect.person-box')).toHaveCSS('stroke-dasharray','4px, 3px');
    receiving=false;
    await expect(predicted).toHaveCount(0,{timeout:2000});
    await expect(tile.getByRole('img',{name:`Preview ${camera.name}`,exact:true})).toBeVisible();
  } finally {
    await page.unroute(`**${base}/observation?metadata_only=true`);
    await page.request.delete(base,{headers});
  }
});
