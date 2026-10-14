import { test, expect } from '@playwright/test';

test('camera layouts, focus, search, fullscreen and navigation keep one webcam capture', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/cameras');
  const grid = page.getByTestId('camera-wall-grid');
  const checkControlsOutsideVideo = async () => {
    expect(await page.locator('[data-camera-id="webcam"]').evaluate(tile => {
      const controls = tile.querySelector('.webcam-wall-actions').getBoundingClientRect();
      const preview = tile.querySelector('.webcam-preview').getBoundingClientRect();
      return controls.bottom <= preview.top + 1 && preview.height > 0;
    })).toBe(true);
  };
  await expect(grid).toHaveAttribute('data-layout', '4');
  await checkControlsOutsideVideo();
  await page.screenshot({ path: 'verification/screenshots/camera-wall-webcam-controls-1440.png', fullPage: true });
  await page.getByRole('button', { name: 'Mulai webcam', exact: true }).click();
  await expect(page.getByTestId('webcam-status')).toContainText('Live');
  await page.locator('video').evaluate(video => { window.wallTrack = video.srcObject.getVideoTracks()[0]; });
  for (const size of [9, 16, 1, 4]) {
    await page.getByRole('button', { name: `Layout ${size} kamera`, exact: true }).click();
    await expect(grid).toHaveAttribute('data-layout', String(size));
    await expect(page.getByTestId('camera-empty-slot')).toHaveCount(size - 1);
    await checkControlsOutsideVideo();
    expect(await page.locator('video').evaluate(video => video.srcObject.getVideoTracks()[0] === window.wallTrack)).toBe(true);
  }
  await page.getByLabel('Cari kamera', { exact: true }).fill('missing camera');
  await expect(page.getByText('Kamera tidak ditemukan.', { exact: true })).toBeVisible();
  await page.getByLabel('Cari kamera', { exact: true }).fill('');
  await page.getByRole('button', { name: 'Daftar kamera', exact: true }).click();
  await expect(page.getByLabel('Daftar sumber kamera', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Daftar kamera', exact: true }).click();
  await page.getByTestId('camera-tile').filter({ has: page.getByRole('heading', { name: 'Webcam lokal', exact: true }) }).dblclick({ position: { x: 110, y: 150 } });
  await expect(grid).toHaveAttribute('data-layout', '1');
  await page.keyboard.press('Escape');
  await expect(grid).toHaveAttribute('data-layout', '4');
  await page.getByRole('button', { name: 'Layar penuh grid', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement?.dataset.testid)).toBe('camera-wall-viewport');
  await page.getByRole('button', { name: 'Keluar layar penuh grid', exact: true }).click();
  await page.getByRole('button', { name: 'Ringkasan', exact: true }).click();
  expect(await page.evaluate(() => window.wallTrack.readyState)).toBe('live');
  await page.getByRole('button', { name: 'Kamera', exact: true }).click();
  expect(await page.locator('video').evaluate(video => video.srcObject.getVideoTracks()[0] === window.wallTrack)).toBe(true);
  for (const width of [1440, 1100, 760]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await checkControlsOutsideVideo();
  }
  await page.getByRole('button', { name: 'Hentikan webcam', exact: true }).click();
  expect(await page.evaluate(() => window.wallTrack.readyState)).toBe('ended');
  expect(errors).toEqual([]);
});

test('RTSP form validates and a failed connection never shows live or writes a report', async ({ page }) => {
  await page.goto('/#/cameras');
  const before = await (await page.request.get('/pilot/v1/status?dataset=live')).json();
  await page.getByRole('button', { name: 'Tambah kamera', exact: true }).click();
  await page.getByLabel('Nama kamera', { exact: true }).fill('Kamera uji tidak tersambung');
  await page.getByLabel('Alamat RTSP', { exact: true }).fill('https://invalid.example');
  await page.getByRole('button', { name: 'Tambahkan ke grid', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Masukkan URL rtsp://');
  await page.getByLabel('Alamat RTSP', { exact: true }).fill('rtsp://test:secret@127.0.0.1:1/unreachable');
  await page.getByRole('button', { name: 'Tambahkan ke grid', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const tile = page.getByTestId('camera-tile').filter({ has: page.getByRole('heading', { name: 'Kamera uji tidak tersambung', exact: true }) });
  await expect(tile).toContainText('Menghubungkan');
  await expect(tile.locator('img')).toHaveCount(0);
  const state = await page.request.get('/pilot/v1/camera-wall');
  expect(await state.text()).not.toContain('secret');
  const after = await (await page.request.get('/pilot/v1/status?dataset=live')).json();
  expect(after.runs.length).toBe(before.runs.length);
  await page.getByRole('button', { name: 'Hapus Kamera uji tidak tersambung', exact: true }).click();
  await page.getByRole('button', { name: 'Hapus kamera', exact: true }).click();
  await expect(tile).toHaveCount(0);
});

test('four independent live displays with actual synthetic RTSP decoders and webcam', async ({ page }) => {
  test.skip(process.env.CCTV_WALL_RTSP_TEST !== '1', 'Optional localhost RTSP rig');
  test.setTimeout(90000);
  const created = [];
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.goto('/#/cameras');
  try {
    await page.getByRole('button', { name: 'Mulai webcam', exact: true }).click();
    await expect(page.getByTestId('webcam-status')).toContainText('Live');
    for (const number of [1, 2, 3]) {
      await page.getByRole('button', { name: 'Tambah kamera', exact: true }).click();
      await page.getByLabel('Nama kamera', { exact: true }).fill(`Kamera sintetis uji ${number}`);
      await page.getByLabel('Alamat RTSP', { exact: true }).fill(`rtsp://127.0.0.1:8854/wall${number}`);
      const response = page.waitForResponse(r => r.url().endsWith('/camera-wall/cameras') && r.request().method() === 'POST');
      await page.getByRole('button', { name: 'Tambahkan ke grid', exact: true }).click();
      created.push((await (await response).json()).id);
      await expect(page.getByRole('dialog')).toHaveCount(0);
    }
    await expect(page.locator('.camera-wall-grid .camera-tile:visible')).toHaveCount(4);
    await expect(page.locator('.camera-wall-grid img')).toHaveCount(3, { timeout: 30000 });
    await expect.poll(async () => (await (await page.request.get('/pilot/v1/camera-wall')).json()).cameras.filter(c => created.includes(c.id) && c.health === 'ONLINE').length, { timeout: 30000 }).toBe(3);
    const hashes = await Promise.all(created.map(async id => (await page.request.get(`/pilot/v1/camera-wall/cameras/${id}/frame.jpg`)).body()));
    expect(hashes[0].equals(hashes[1])).toBe(false); expect(hashes[1].equals(hashes[2])).toBe(false);
    const ids = await page.locator('.camera-wall-grid .camera-tile:visible').evaluateAll(tiles => tiles.map(t => t.dataset.cameraId));
    expect(new Set(ids).size).toBe(4);
    for (const id of created) await expect(page.locator(`[data-camera-id="${id}"] .status`)).toContainText('Live');
    await page.screenshot({ path: 'verification/screenshots/camera-wall-four-synthetic-1440.png', fullPage: true });
    await page.getByRole('button', { name: 'Fokus Kamera sintetis uji 2', exact: true }).click();
    await expect(page.locator('.camera-wall-grid .camera-tile:visible')).toHaveCount(1);
    await expect(page.locator('.camera-wall-grid .camera-tile:visible')).toContainText('Kamera sintetis uji 2');
    await page.getByRole('button', { name: 'Kembali ke grid', exact: true }).click();
    await expect(page.locator('.camera-wall-grid .camera-tile:visible')).toHaveCount(4);
    await page.locator('.camera-session-controls > summary').click();
    await page.getByLabel('Sumber pencatatan', { exact: true }).selectOption('RTSP_LIVE');
    await page.getByLabel('URL RTSP', { exact: true }).fill('rtsp://127.0.0.1:8854/wall1');
    await page.getByRole('button', { name: 'Uji preview RTSP', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/pilot/v1/live')).json()).camera_health, { timeout: 30000 }).toBe('ONLINE');
    await expect(page.locator('.camera-wall-grid .camera-tile:visible')).toHaveCount(4);
    await expect(page.getByRole('heading', { name: 'CCTV sesi engine', exact: true })).toHaveCount(0);
    await expect(page.getByTestId('webcam-engine-status')).toContainText('Preview saja; engine memproses RTSP');
    expect(await page.locator('video').evaluate(video => video.srcObject.getVideoTracks()[0].readyState)).toBe('live');
    await page.getByRole('button', { name: 'Hentikan pencatatan live', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/pilot/v1/live')).json()).status).toBe('STOPPED');
    await page.getByRole('button', { name: 'Hentikan webcam', exact: true }).click();
    expect(errors).toEqual([]);
  } finally {
    const live = await (await page.request.get('/pilot/v1/live')).json();
    if (['STARTING', 'RUNNING', 'STOPPING'].includes(live.status)) await page.request.post('/pilot/v1/live/stop', { headers: { Origin: 'http://127.0.0.1:8766' }, data: { session_id: live.session_id } });
    for (const id of created) await page.request.delete(`/pilot/v1/camera-wall/cameras/${id}`, { headers: { Origin: 'http://127.0.0.1:8766' } });
  }
});
