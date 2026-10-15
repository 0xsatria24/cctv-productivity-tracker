import { test, expect } from '@playwright/test';

test('two cameras can calibrate, record independently, survive navigation, export and create a verified backup', async ({ page }) => {
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.goto('/#/live');
  const old = await (await page.request.get('/pilot/v1/camera-wall')).json();
  for (const row of old.cameras) expect((await page.request.delete(`/pilot/v1/camera-wall/cameras/${row.id}`, { headers: { Origin: 'http://127.0.0.1:8771' } })).ok()).toBeTruthy();
  await page.reload();
  const cameras = [];
  for (const name of ['North test', 'South test']) {
    await page.getByRole('button', { name: 'Tambah kamera', exact: true }).first().click();
    await page.getByLabel('Nama kamera', { exact: true }).fill(name);
    await page.getByLabel('Alamat RTSP', { exact: true }).fill(`rtsp://synthetic.invalid/${name.split(' ')[0]}`);
    await page.getByRole('button', { name: 'Tambahkan ke grid', exact: true }).click();
    await expect(page.getByRole('heading', { name: `Monitoring ${name}`, exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Atur zona kamera', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Nama zona live', { exact: true }).fill('Desk ' + name);
    for (const [x, y] of [[0,0],[1,0],[1,1],[0,1]]) {
      await dialog.getByLabel('Koordinat X (0 sampai 1)', { exact: true }).fill(String(x));
      await dialog.getByLabel('Koordinat Y (0 sampai 1)', { exact: true }).fill(String(y));
      await dialog.getByRole('button', { name: 'Tambah titik koordinat', exact: true }).click();
    }
    await dialog.getByRole('button', { name: 'Simpan zona', exact: true }).click();
    await dialog.getByRole('button', { name: 'Simpan kalibrasi live', exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await page.getByLabel('Pulihkan otomatis setelah gangguan atau aplikasi dimulai ulang').check();
    await page.getByRole('button', { name: 'Mulai analisis kamera', exact: true }).click();
    const state = await (await page.request.get('/pilot/v1/camera-wall')).json();
    cameras.push(state.cameras.find(c => c.name === name).id);
  }
  await expect.poll(async () => (await (await page.request.get('/pilot/v1/camera-wall')).json()).cameras.map(c => ({status:c.engine.status, zone:c.engine.latest?.zones?.[0]?.state, error:c.engine.error})), { timeout: 45000 }).toEqual([{status:'RUNNING',zone:'OCCUPIED',error:null},{status:'RUNNING',zone:'OCCUPIED',error:null}]);
  await page.getByLabel('Deteksi', { exact: true }).check();
  await expect(page.getByTestId('rtsp-person-detection')).toHaveCount(2);
  await page.getByRole('button', { name: 'Ringkasan', exact: true }).click();
  await expect.poll(async () => (await (await page.request.get('/pilot/v1/camera-wall')).json()).cameras.filter(c => c.engine.status === 'RUNNING').length).toBe(2);
  await page.getByRole('button', { name: 'Laporan', exact: true }).click();
  for (const camera of cameras) {
    await page.getByLabel('Kamera laporan', { exact: true }).selectOption(camera);
    await expect(page.getByTestId('engine-report')).toContainText('Desk');
    const csv = await (await page.request.get(`/pilot/v1/export.csv?dataset=live&camera_id=${camera}`)).text();
    expect(csv).toContain(camera); expect(csv).toContain('RTSP_LIVE');
  }
  await page.getByRole('button', { name: 'Pengaturan', exact: true }).click();
  await page.getByRole('button', { name: 'Buat backup sekarang', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Verifikasi', exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Verifikasi', exact: true }).first().click();
  await expect(page.getByRole('status').filter({ hasText: 'Checksum' })).toBeVisible();
  await page.getByRole('button', { name: 'Panduan restore', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toContainText('cctv_tracker.maintenance');
  await page.getByRole('button', { name: 'Tutup dialog', exact: true }).click();
  for (const width of [1440, 1100, 760]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  await page.screenshot({ path: 'verification/screenshots/maintenance-synthetic-760.png', fullPage: true });
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('button', { name: 'Pemantauan Live', exact: true }).click();
  await page.screenshot({ path: 'verification/screenshots/fleet-synthetic-1440.png', fullPage: true });
  await page.getByRole('button', { name: 'Hapus North test', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Hapus kamera', exact: true }).click();
  await expect.poll(async () => (await (await page.request.get('/pilot/v1/camera-wall')).json()).cameras.length).toBe(1);
  expect((await (await page.request.get(`/pilot/v1/reports?dataset=live&camera_id=${cameras[0]}`)).json()).workstations.length).toBe(1);
  expect(errors).toEqual([]);
});
