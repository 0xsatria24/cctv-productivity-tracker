import { test, expect } from '@playwright/test';

const initial = {data_enabled:false,data_interval_seconds:60,video_enabled:false,video_segment_seconds:60,max_storage_mb:5120};
const headers = {Origin:'http://127.0.0.1:8771'};

async function reset(page) {
  await page.goto('/#/settings');
  expect((await page.request.post('/pilot/v1/recordings/policy',{headers,data:initial})).ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByLabel('Auto-save laporan data',{exact:true})).not.toBeChecked();
}

test('settings are editable and saveable from the default off state', async ({page}) => {
  await reset(page);
  try {
    const save = page.getByRole('button',{name:'Simpan pengaturan auto-save',exact:true});
    await expect(save).toBeEnabled();
    await expect(page.getByLabel('Interval simpan data',{exact:true})).toBeEnabled();
    await expect(page.getByLabel('Durasi potongan video',{exact:true})).toBeEnabled();
    await expect(page.getByLabel('Satuan interval simpan data',{exact:true})).toBeEnabled();
    await expect(page.getByLabel('Satuan durasi potongan video',{exact:true})).toBeEnabled();
    await page.getByLabel('Satuan interval simpan data',{exact:true}).selectOption('1');
    await page.getByLabel('Interval simpan data',{exact:true}).fill('30');
    await page.getByLabel('Satuan durasi potongan video',{exact:true}).selectOption('1');
    await page.getByLabel('Durasi potongan video',{exact:true}).fill('10');
    const response = page.waitForResponse(r=>r.url().endsWith('/recordings/policy')&&r.request().method()==='POST');
    await save.click();
    expect((await response).status()).toBe(200);
    await expect(page.getByTestId('recording-saved-policy')).toContainText('laporan nonaktif setiap 30 detik; video nonaktif, potongan 10 detik');
    await expect(save).toBeEnabled();
    await page.reload();
    await expect(page.getByLabel('Interval simpan data',{exact:true})).toHaveValue('30');
    await expect(page.getByLabel('Durasi potongan video',{exact:true})).toHaveValue('10');
    await expect(page.getByLabel('Auto-save rekaman video',{exact:true})).not.toBeChecked();
    // Both mouse and keyboard operate the actual checkbox without force-clicking.
    await page.getByLabel('Auto-save laporan data',{exact:true}).check();
    await expect(page.getByLabel('Auto-save laporan data',{exact:true})).toBeChecked();
    await page.getByLabel('Auto-save laporan data',{exact:true}).press('Space');
    await expect(page.getByLabel('Auto-save laporan data',{exact:true})).not.toBeChecked();
    await page.screenshot({path:'verification/screenshots/recording-controls-off-1440.png',fullPage:true});
  } finally { await page.request.post('/pilot/v1/recordings/policy',{headers,data:initial}); }
});

test('save failures remain visible while status polling works and users can retry', async ({page}) => {
  await reset(page);
  let reads = 0;
  page.on('response',response=>{if(response.url().endsWith('/recordings')&&response.status()===200) reads++;});
  try {
    await page.route('**/pilot/v1/recordings/policy', route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'UJI: penyimpanan pengaturan terganggu; coba lagi.'})}));
    await page.getByLabel('Auto-save laporan data',{exact:true}).check();
    const save = page.getByRole('button',{name:'Simpan pengaturan auto-save',exact:true});
    await save.click();
    await expect(page.getByRole('alert').filter({hasText:'UJI: penyimpanan pengaturan terganggu'})).toBeVisible();
    const before = reads;
    await expect.poll(()=>reads).toBeGreaterThanOrEqual(before+2);
    await expect(page.getByRole('alert').filter({hasText:'UJI: penyimpanan pengaturan terganggu'})).toBeVisible();
    await expect(page.getByTestId('recording-saved-policy')).toContainText('laporan nonaktif');
    await expect(save).toBeEnabled();
    await page.unroute('**/pilot/v1/recordings/policy');
    await save.click();
    await expect(page.getByTestId('recording-saved-policy')).toContainText('laporan aktif');
    await expect(page.getByRole('alert').filter({hasText:'UJI: penyimpanan pengaturan terganggu'})).toHaveCount(0);
  } finally {
    await page.unroute('**/pilot/v1/recordings/policy');
    await page.request.post('/pilot/v1/recordings/policy',{headers,data:initial});
  }
});
