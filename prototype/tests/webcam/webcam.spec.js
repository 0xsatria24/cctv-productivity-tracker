import { test, expect } from '@playwright/test';

const start = page => page.getByRole('button', { name: 'Mulai webcam', exact: true });
const stop = page => page.getByRole('button', { name: 'Hentikan webcam', exact: true });
const status = page => page.getByTestId('webcam-status');

test('detection overlay mirrors and stale or failed inference never shows an old count', async ({ page }) => {
  // Explicit transport fixture checks overlay geometry, not detector accuracy.
  let failing = false;
  await page.route('**/pilot/v1/webcam/frame', async route => {
    if (failing) return route.fulfill({ status: 503, json: { detail: 'Test: model unavailable' } });
    return route.fulfill({ json: { model: 'TEST FIXTURE', count: 1, width: 640, height: 480, inference_ms: 50, detections: [{ box: [0.1, 0.2, 0.4, 0.8], confidence: 0.91 }] } });
  });
  await page.goto('/#/cameras');
  await page.getByLabel('Deteksi', { exact: true }).check();
  await start(page).click();
  const engine = page.getByTestId('webcam-engine-status');
  await expect(engine).toContainText('1 orang terdeteksi');
  await expect(page.locator('.person-box')).toHaveAttribute('x', '384');
  await page.getByRole('button', { name: 'Pengaturan webcam', exact: true }).click();
  await page.getByLabel('Cerminkan preview').uncheck();
  await page.getByRole('button', { name: 'Selesai', exact: true }).click();
  await expect(page.locator('.person-box')).toHaveAttribute('x', '64');
  failing = true;
  await expect(engine).toContainText('Analisis belum terhubung');
  await expect(page.locator('.person-box')).toHaveCount(0);
  await expect(engine).not.toContainText('1 orang');
  await expect(status(page)).toContainText('Live');
  failing = false;
  await expect(engine).toContainText('1 orang terdeteksi');
  await stop(page).click();
  await expect(engine).toContainText('Analisis menunggu kamera');
  await expect(page.locator('.person-box')).toHaveCount(0);
});

test('browser camera renders moving video, controls work, and no webcam observations enter replay reports', async ({ page }) => {
  const errors = [], mutations = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') mutations.push(request.url()); });
  await page.goto('/#/cameras');
  const before = await (await page.request.get('/pilot/v1/status')).json();
  await expect(page.locator('video')).toHaveCount(0);
  await page.getByRole('button', { name: 'Pengaturan webcam', exact: true }).click();
  await page.getByRole('button', { name: 'Perbarui perangkat' }).click();
  await page.getByLabel('Target resolusi', { exact: true }).selectOption('480');
  await page.getByRole('button', { name: 'Selesai', exact: true }).click();
  await start(page).click();
  await expect(status(page)).toContainText('Live');
  const video = page.getByLabel('Preview webcam lokal', { exact: true });
  await expect.poll(() => video.evaluate(element => element.videoWidth)).toBeGreaterThan(0);
  await expect.poll(() => video.evaluate(element => element.currentTime)).toBeGreaterThan(1);
  expect(await video.evaluate(element => element.srcObject.getAudioTracks().length)).toBe(0);
  await expect(status(page)).toContainText('FPS preview');
  await page.getByRole('button', { name: 'Pengaturan webcam', exact: true }).click();
  await expect(page.getByLabel('Perangkat webcam', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('Target resolusi', { exact: true })).toBeDisabled();
  await page.getByLabel('Cerminkan preview').uncheck();
  expect(await video.evaluate(element => element.style.transform)).toBe('');
  await page.getByLabel('Tampilan video', { exact: true }).selectOption('cover');
  expect(await video.evaluate(element => element.style.objectFit)).toBe('cover');
  await page.getByRole('button', { name: 'Selesai', exact: true }).click();
  await page.getByRole('button', { name: 'Layar penuh grid', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement?.dataset.testid)).toBe('camera-wall-viewport');
  await page.getByRole('button', { name: 'Keluar layar penuh grid', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement)).toBe(null);
  const after = await (await page.request.get('/pilot/v1/status')).json();
  expect(after.committed_event_seq).toBe(before.committed_event_seq);
  expect(after.runs.length).toBe(before.runs.length);
  expect(mutations.length).toBeGreaterThan(0);
  expect(mutations.every(url => url.endsWith('/pilot/v1/webcam/frame') || url.endsWith('/pilot/v1/camera-wall/view'))).toBe(true);
  await expect(page.getByTestId('webcam-engine-status')).toContainText('Analisis orang aktif');
  await page.screenshot({ path: 'verification/screenshots/webcam-test-source-1440.png', fullPage: true });
  await page.setViewportSize({ width: 1100, height: 720 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await video.evaluate(element => { window.testTrack = element.srcObject.getVideoTracks()[0]; });
  await stop(page).click();
  await expect(status(page)).toContainText('Belum dimulai');
  expect(await page.evaluate(() => window.testTrack.readyState)).toBe('ended');
  await expect(page.locator('video')).toHaveCount(0);
  await expect(start(page)).toBeEnabled();
  // A named device can be selected before a new capture request.
  await page.getByRole('button', { name: 'Pengaturan webcam', exact: true }).click();
  const device = await page.getByLabel('Perangkat webcam', { exact: true }).locator('option').last().getAttribute('value');
  await page.getByLabel('Perangkat webcam', { exact: true }).selectOption(device);
  await page.getByRole('button', { name: 'Selesai', exact: true }).click();
  await start(page).click();
  await expect(status(page)).toContainText('Live');
  await stop(page).click();
  expect(errors).toEqual([]);
});

test('camera and inference survive navigation; explicit stop releases the track', async ({ page }) => {
  await page.goto('/#/cameras');
  await start(page).click();
  await expect(status(page)).toContainText('Live');
  await page.locator('video').evaluate(element => { window.testTrack = element.srcObject.getVideoTracks()[0]; });
  await page.getByRole('button', { name: 'Pemantauan Live', exact: true }).click();
  await expect(status(page)).toContainText('Live');
  expect(await page.locator('video').evaluate(element => element.srcObject.getVideoTracks()[0] === window.testTrack)).toBe(true);
  await page.getByRole('button', { name: 'Ringkasan', exact: true }).click();
  expect(await page.evaluate(() => window.testTrack.readyState)).toBe('live');
  await expect(page.getByTestId('webcam-engine-status')).toContainText('Analisis orang aktif');
  for (const name of ['Laporan', 'Pemantauan Live']) {
    await page.getByRole('button', { name, exact: true }).click();
    expect(await page.locator('video').evaluate(element => element.srcObject.getVideoTracks()[0] === window.testTrack)).toBe(true);
  }
  await stop(page).click();
  await expect(status(page)).toContainText('Belum dimulai');
  expect(await page.evaluate(() => window.testTrack.readyState)).toBe('ended');
});

test('cancelled permission request releases a stream granted after cancellation', async ({ page }) => {
  await page.addInitScript(() => {
    const native = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = constraints => new Promise(resolve => {
      window.resolvePermission = async () => { window.lateStream = await native(constraints); resolve(window.lateStream); };
    });
  });
  await page.goto('/#/cameras');
  await start(page).click();
  await expect(status(page)).toContainText('Menunggu izin');
  await stop(page).click();
  await expect(start(page)).toBeDisabled();
  await page.evaluate(() => window.resolvePermission());
  await expect(status(page)).toContainText('Belum dimulai');
  expect(await page.evaluate(() => window.lateStream.getVideoTracks()[0].readyState)).toBe('ended');
  await expect(page.locator('video')).toHaveCount(0);
});

test('permission denial has actionable feedback and supports a subsequent successful retry', async ({ page }) => {
  await page.addInitScript(() => {
    const native = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    let first = true;
    navigator.mediaDevices.getUserMedia = constraints => {
      if (first) { first = false; return Promise.reject(new DOMException('Test denial', 'NotAllowedError')); }
      return native(constraints);
    };
  });
  await page.goto('/#/cameras');
  await start(page).click();
  await expect(page.getByRole('alert')).toContainText('Akses kamera ditolak');
  await expect(page.locator('video')).toHaveCount(0);
  await start(page).click();
  await expect(status(page)).toContainText('Live');
  await stop(page).click();
});

for (const [name, message] of [['NotFoundError', 'Webcam tidak ditemukan'], ['NotReadableError', 'Webcam tidak dapat dibaca'], ['OverconstrainedError', 'Perangkat yang dipilih tidak tersedia']]) {
  test(`${name} never produces a fake online state`, async ({ page }) => {
    await page.addInitScript(errorName => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Test camera failure', errorName)); }, name);
    await page.goto('/#/cameras');
    await start(page).click();
    await expect(page.getByRole('alert')).toContainText(message);
    await expect(status(page)).toContainText('Tidak terhubung');
    await expect(page.locator('video')).toHaveCount(0);
    await expect(start(page)).toBeEnabled();
  });
}

test('webcam preview remains available when engine status API is offline from initial load', async ({ page }) => {
  await page.route('**/pilot/v1/status*', route => route.abort());
  await page.goto('/#/cameras');
  await expect(page.getByRole('alert')).toContainText('Layanan monitoring tidak terhubung');
  await start(page).click();
  await expect(status(page)).toContainText('Live');
  await page.getByRole('button', { name: 'Ringkasan', exact: true }).click();
  await expect(page.getByTestId('engine-connection')).toContainText('terputus');
  await page.getByRole('button', { name: 'Pemantauan Live', exact: true }).click();
  await stop(page).click();
});

test('device ended event stops preview and allows a new connection', async ({ page }) => {
  await page.goto('/#/cameras');
  await start(page).click();
  await expect(status(page)).toContainText('Live');
  await page.locator('video').evaluate(element => { window.testTrack = element.srcObject.getVideoTracks()[0]; window.testTrack.dispatchEvent(new Event('ended')); });
  await expect(page.getByRole('alert')).toContainText('Koneksi webcam terputus');
  expect(await page.evaluate(() => window.testTrack.readyState)).toBe('ended');
  await expect(page.locator('video')).toHaveCount(0);
  await start(page).click();
  await expect(status(page)).toContainText('Live');
  await stop(page).click();
});
