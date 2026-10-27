import { test, expect } from '@playwright/test';

test('merged master retains shared workstation editing, per-camera accounting and recording settings', async ({ page }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/live');
  await expect(page.getByTestId('engine-connection')).toContainText('terhubung');
  const origin = new URL(page.url()).origin;
  const headers = { Origin: origin };
  const registry = await (await page.request.get('/pilot/v1/camera-wall')).json();
  for (const camera of registry.cameras) {
    expect((await page.request.delete(`/pilot/v1/camera-wall/cameras/${camera.id}`, { headers })).ok()).toBe(true);
  }
  const created = await page.request.post('/pilot/v1/camera-wall/cameras', {
    headers, data: { name: 'Merge workstation', url: 'rtsp://localhost/merge-workstation' },
  });
  expect(created.status()).toBe(201);
  const camera = await created.json();
  await page.getByRole('button', { name: 'Layout 4 kamera', exact: true }).click();
  const tile = page.getByTestId('camera-tile').filter({ has: page.getByRole('heading', { name: camera.name, exact: true }) });
  await expect(tile.getByRole('img', { name: `Preview ${camera.name}`, exact: true })).toBeVisible();
  await tile.getByRole('button', { name: 'Atur area', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Atur area workstation' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Tambah area', exact: true }).click();
  await dialog.getByLabel('Nama area', { exact: true }).fill('Meja merge');
  await dialog.getByRole('button', { name: 'Buat kotak di tengah', exact: true }).click();
  await dialog.getByRole('button', { name: 'Simpan area', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: 'Mulai analisis kamera', exact: true }).click();
  await expect.poll(async () => {
    const state = await (await page.request.get('/pilot/v1/camera-wall')).json();
    return state.cameras.find(row => row.id === camera.id)?.engine.latest?.workstations?.[0]?.state;
  }).toBe('OCCUPIED');
  await expect(page.getByRole('region', { name: 'Durasi workstation live' })).toContainText('Meja merge');
  await tile.getByRole('button', { name: `Fullscreen ${camera.name}`, exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(true);
  await page.getByRole('button', { name: `Keluar fullscreen ${camera.name}`, exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(false);
  await page.getByRole('button', { name: 'Hentikan analisis kamera', exact: true }).click();
  await page.getByRole('button', { name: 'Pengaturan', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Auto-save data dan video', exact: true })).toBeVisible();
  const backup = page.waitForResponse(response => response.url().endsWith('/pilot/v1/maintenance/backup') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Buat backup sekarang', exact: true }).click();
  expect((await backup).ok()).toBe(true);
  await expect(page.getByRole('button', { name: 'Verifikasi', exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Verifikasi', exact: true }).first().click();
  await expect(page.getByRole('status').filter({ hasText: 'Checksum' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('merged-settings.png'), fullPage: true });
  expect(errors).toEqual([]);
});
