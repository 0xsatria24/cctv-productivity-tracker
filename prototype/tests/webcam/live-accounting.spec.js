import { test, expect } from '@playwright/test';

test('calibration, actual live frame ingestion, SQLite report, navigation, export and stop', async ({ page }) => {
  test.setTimeout(90000);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/#/cameras');
  await page.getByRole('button', { name: 'Mulai webcam', exact: true }).click();
  await expect(page.getByTestId('webcam-status')).toContainText('Live');
  await page.locator('.camera-session-controls > summary').click();
  await page.getByRole('button', { name: 'Kalibrasi zona live', exact: true }).click();
  const modal = page.getByRole('dialog');
  await expect(modal).toBeVisible();
  // Use accessible numeric input to draw a full-frame test zone on the synthetic video.
  await modal.getByLabel('Nama zona live', { exact: true }).fill('Zona kamera sintetis uji');
  for (const [x, y] of [[0, 0], [1, 0], [1, 1], [0, 1]]) {
    await modal.getByLabel('Koordinat X (0 sampai 1)').fill(String(x));
    await modal.getByLabel('Koordinat Y (0 sampai 1)').fill(String(y));
    await modal.getByRole('button', { name: 'Tambah titik koordinat', exact: true }).click();
  }
  await modal.getByRole('button', { name: 'Simpan zona', exact: true }).click();
  await modal.getByLabel('Konfirmasi terisi (detik)', { exact: true }).fill('0.2');
  await modal.getByLabel('Konfirmasi kosong (detik)', { exact: true }).fill('0.2');
  await modal.getByLabel('Batas gap frame (detik)', { exact: true }).fill('5');
  await modal.getByRole('button', { name: 'Simpan kalibrasi live', exact: true }).click();
  await expect(modal).not.toBeVisible();
  await page.getByRole('button', { name: 'Mulai pencatatan live', exact: true }).click();
  await expect(page.getByLabel('Sumber data laporan', { exact: true })).toHaveValue('live');
  await expect(page.getByTestId('webcam-engine-status')).toContainText('Tracking dan checkpoint SQLite aktif', { timeout: 25000 });
  await expect.poll(async () => (await (await page.request.get('/pilot/v1/reports?dataset=live')).json()).workstations.some(w => w.empty_us > 0), { timeout: 25000 }).toBe(true);
  const live = await (await page.request.get('/pilot/v1/live')).json();
  const runtime = (await (await page.request.get('/pilot/v1/status?dataset=live')).json()).detector;
  expect(runtime.ready).toBe(true);
  if (runtime.runtime.provider === 'OpenVINO') {
    expect(runtime.model).toContain('YOLOX-S');
    expect(runtime.runtime.precision).toBe('f32');
    expect(runtime.runtime.execution_devices[0]).toContain(runtime.runtime.requested_device);
  }
  expect(live.latest.recorded).toBe(true);
  expect(live.latest.count).toBe(0); // Synthetic moving rectangle is not a person.
  await page.locator('video').evaluate(video => { window.testLiveTrack = video.srcObject.getVideoTracks()[0]; });
  await page.getByRole('button', { name: 'Ringkasan', exact: true }).click();
  expect(await page.evaluate(() => window.testLiveTrack.readyState)).toBe('live');
  await expect(page.getByTestId('engine-metrics')).not.toContainText('N/A');
  await page.getByRole('button', { name: 'Laporan', exact: true }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Ekspor CSV engine', exact: true }).click();
  expect((await download).suggestedFilename()).toBe('cctv-engine-report.csv');
  await page.screenshot({ path: 'verification/screenshots/live-accounting-test-source-1440.png', fullPage: true });
  await page.getByRole('button', { name: 'Hentikan pencatatan live', exact: true }).click();
  await expect.poll(async () => (await (await page.request.get('/pilot/v1/live')).json()).status).toBe('STOPPED');
  expect(await page.evaluate(() => window.testLiveTrack.readyState)).toBe('live');
  await page.getByRole('button', { name: 'Kamera', exact: true }).click();
  await page.getByRole('button', { name: 'Hentikan webcam', exact: true }).click();
  await page.getByRole('button', { name: 'Laporan', exact: true }).click();
  await page.getByLabel('Sumber data laporan', { exact: true }).selectOption('replay');
  const replay = await (await page.request.get('/pilot/v1/status')).json();
  expect(replay.runs.every(run => run.data_source === 'SYNTHETIC_REPLAY')).toBe(true);
  expect(errors).toEqual([]);
});
