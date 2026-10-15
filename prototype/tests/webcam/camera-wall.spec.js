import { test, expect } from '@playwright/test';

test('camera layouts, focus, search, fullscreen and navigation keep one webcam capture', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/cameras');
  await expect(page).toHaveURL(/#\/live$/);
  const navigation=page.getByRole('navigation',{name:'Navigasi utama'});
  await expect(navigation.getByRole('button')).toHaveCount(6);
  await expect(navigation.getByRole('button',{name:'Kamera',exact:true})).toHaveCount(0);
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
  const modes = page.getByRole('group', { name: 'Mode tampilan kamera' });
  for (const [label, mode] of [['Video wall', 'wall'], ['Fokus', 'focus'], ['Grid', 'grid']]) {
    await modes.getByRole('button', { name: label, exact: true }).click();
    await expect(grid).toHaveAttribute('data-mode', mode);
    await checkControlsOutsideVideo();
    expect(await page.locator('video').evaluate(video => video.srcObject.getVideoTracks()[0] === window.wallTrack)).toBe(true);
    expect(await page.evaluate(() => window.wallTrack.readyState)).toBe('live');
  }
  await page.getByLabel('Cari kamera', { exact: true }).fill('missing camera');
  await expect(page.getByText('Kamera tidak ditemukan.', { exact: true })).toBeVisible();
  await page.getByLabel('Cari kamera', { exact: true }).fill('');
  await page.getByRole('button', { name: 'Daftar kamera', exact: true }).click();
  await expect(page.getByLabel('Daftar sumber kamera', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Daftar kamera', exact: true }).click();
  await page.getByTestId('camera-tile').filter({ has: page.getByRole('heading', { name: 'Webcam lokal', exact: true }) }).dblclick({ position: { x: 110, y: 150 } });
  await expect(grid).toHaveAttribute('data-mode', 'focus');
  await expect(grid).toHaveAttribute('data-layout', '6');
  await expect(page.locator('[data-camera-id="webcam"]')).toHaveAttribute('data-primary', 'true');
  await page.keyboard.press('Escape');
  await expect(grid).toHaveAttribute('data-layout', '4');
  await page.getByRole('button', { name: 'Layar penuh grid', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement?.dataset.testid)).toBe('camera-wall-viewport');
  await page.getByRole('button', { name: 'Keluar layar penuh grid', exact: true }).click();
  await page.getByRole('button', { name: 'Ringkasan', exact: true }).click();
  expect(await page.evaluate(() => window.wallTrack.readyState)).toBe('live');
  await page.getByRole('button', { name: 'Pemantauan Live', exact: true }).click();
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

test('shared modes preserve selection, overlays and density with paged focus companions', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  // Explicit UI fixtures exercise layout/demand only; no physical camera or RTSP decoder is opened.
  const cameras = Array.from({ length: 16 }, (_, i) => ({ id: `mode-camera-${i + 1}`, name: `Kamera uji mode ${String(i + 1).padStart(2, '0')}`, source: 'RTSP_PREVIEW', health: 'ONLINE' }));
  let demand = [];
  await page.route('**/pilot/v1/camera-wall', route => route.fulfill({ json: { cameras } }));
  await page.route('**/pilot/v1/camera-wall/view', route => { demand = route.request().postDataJSON().camera_ids; return route.fulfill({ json: {} }); });
  await page.route('**/pilot/v1/camera-wall/cameras/mode-camera-*/frame.jpg', route => route.fulfill({
    contentType: 'image/svg+xml', headers: { 'X-Frame-Time': String(Date.now()) },
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#28343b"/><path d="M0 360 260 100h120L640 360M0 80h640" fill="none" stroke="#71878b" stroke-width="2"/><text x="320" y="205" text-anchor="middle" fill="#d9e3e5" font-size="24">SIMULASI UJI MODE</text></svg>',
  }));
  await page.goto('/#/live');
  const workspace = page.getByTestId('camera-workspace'), grid = page.getByTestId('camera-wall-grid');
  const modes = page.getByRole('group', { name: 'Mode tampilan kamera' });
  const primary = page.locator('.camera-tile-primary');
  await expect(page.getByLabel('Daftar sumber kamera').getByText('Kamera uji mode 12', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Layout 9 kamera', exact: true }).click();
  await page.getByLabel('Zona', { exact: true }).uncheck();
  await page.getByLabel('Deteksi', { exact: true }).check();
  await page.getByLabel('Daftar sumber kamera').getByRole('button', { name: /^Kamera uji mode 12/ }).click();
  await expect(page.locator('[data-camera-id="mode-camera-12"]')).toHaveClass(/camera-tile-selected/);
  await modes.getByRole('button', { name: 'Fokus', exact: true }).click();
  await expect(grid).toHaveAttribute('data-layout', '6');
  await expect(primary).toHaveAttribute('data-camera-id', 'mode-camera-12');
  await expect(grid.locator('.camera-tile:visible')).toHaveCount(6);
  await expect(primary.locator('img')).toBeVisible();
  // Selecting a companion promotes the same mounted source to primary.
  await page.locator('[data-camera-id="mode-camera-2"] h2').click();
  await expect(primary).toHaveAttribute('data-camera-id', 'mode-camera-2');
  await page.getByRole('button', { name: 'Halaman kamera berikutnya', exact: true }).click();
  await expect(primary).toHaveAttribute('data-camera-id', 'mode-camera-2');
  const visibleIds = () => grid.locator('.camera-tile:visible').evaluateAll(tiles => tiles.map(tile => tile.dataset.cameraId));
  const ids = await visibleIds();
  expect(new Set(ids).size).toBe(6);
  await expect.poll(() => [...demand].sort()).toEqual(ids.filter(id => id !== 'webcam').sort());
  await page.getByRole('button', { name: 'Sembunyikan dari grid', exact: true }).click();
  await expect(primary).toHaveAttribute('data-camera-id', 'webcam');
  await page.getByLabel('Daftar sumber kamera').getByRole('button', { name: /^Kamera uji mode 02/ }).click();
  await expect(primary).toHaveAttribute('data-camera-id', 'mode-camera-2');
  for (const [label, mode] of [['Video wall', 'wall'], ['Grid', 'grid'], ['Fokus', 'focus']]) {
    await modes.getByRole('button', { name: label, exact: true }).click();
    await expect(workspace).toHaveAttribute('data-mode', mode);
    await expect(page.locator('[data-camera-id="mode-camera-2"]')).toHaveClass(/camera-tile-selected/);
    await expect(page.getByLabel('Zona', { exact: true })).not.toBeChecked();
    await expect(page.getByLabel('Deteksi', { exact: true })).toBeChecked();
    if (mode !== 'focus') await expect(grid).toHaveAttribute('data-layout', '9');
    if (mode === 'wall') await expect(page.getByLabel('Daftar sumber kamera')).toHaveCount(0);
    for (const width of [1440, 1100, 760]) {
      await page.setViewportSize({ width, height: 1000 });
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      if (width === 1440) await page.screenshot({ path: `verification/screenshots/camera-mode-${mode}-1440.png`, fullPage: true });
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await modes.getByRole('button', { name: 'Video wall', exact: true }).click();
  await page.getByRole('button', { name: 'Layar penuh grid', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement?.dataset.testid)).toBe('camera-wall-viewport');
  await modes.getByRole('button', { name: 'Fokus', exact: true }).click();
  await expect(primary).toHaveAttribute('data-camera-id', 'mode-camera-2');
  await page.getByRole('button', { name: 'Keluar layar penuh grid', exact: true }).click();
  await modes.getByRole('button', { name: 'Video wall', exact: true }).click();
  await page.getByRole('button', { name: 'Layout 16 kamera', exact: true }).click();
  await expect(grid.locator('.camera-tile:visible')).toHaveCount(16);
  await page.reload();
  await expect(workspace).toHaveAttribute('data-mode', 'wall');
  await expect(grid).toHaveAttribute('data-layout', '16');
  await expect(page.getByLabel('Deteksi', { exact: true })).toBeChecked();
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
    await expect(page.locator('.camera-wall-grid .camera-tile:visible')).toHaveCount(4);
    await expect(page.locator('.camera-wall-grid .camera-tile-primary')).toContainText('Kamera sintetis uji 2');
    await page.getByRole('button', { name: 'Kembali ke grid', exact: true }).click();
    await expect(page.locator('.camera-wall-grid .camera-tile:visible')).toHaveCount(4);
    await page.locator('.camera-session-controls > summary').click();
    await page.locator('.setup-progress button').nth(0).click();
    await page.getByLabel('Sumber pencatatan', { exact: true }).selectOption('RTSP_LIVE');
    await page.getByLabel('URL RTSP', { exact: true }).fill('rtsp://127.0.0.1:8854/wall1');
    await page.getByRole('button', { name: 'Lanjut ke cek koneksi', exact: true }).click();
    await page.getByRole('button', { name: 'Uji preview RTSP', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/pilot/v1/live')).json()).camera_health, { timeout: 30000 }).toBe('ONLINE');
    await expect(page.locator('.camera-wall-grid .camera-tile:visible')).toHaveCount(4);
    await expect(page.getByRole('heading', { name: 'CCTV sesi engine', exact: true })).toHaveCount(0);
    await expect(page.getByTestId('webcam-engine-status')).toContainText('Preview saja; analisis memakai kamera RTSP');
    expect(await page.locator('video').evaluate(video => video.srcObject.getVideoTracks()[0].readyState)).toBe('live');
    await page.locator('.setup-progress button').nth(3).click();
    await page.getByRole('button', { name: 'Hentikan monitoring', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get('/pilot/v1/live')).json()).status).toBe('STOPPED');
    await page.getByRole('button', { name: 'Hentikan webcam', exact: true }).click();
    expect(errors).toEqual([]);
  } finally {
    const live = await (await page.request.get('/pilot/v1/live')).json();
    if (['STARTING', 'RUNNING', 'STOPPING'].includes(live.status)) await page.request.post('/pilot/v1/live/stop', { headers: { Origin: 'http://127.0.0.1:8766' }, data: { session_id: live.session_id } });
    for (const id of created) await page.request.delete(`/pilot/v1/camera-wall/cameras/${id}`, { headers: { Origin: 'http://127.0.0.1:8766' } });
  }
});
