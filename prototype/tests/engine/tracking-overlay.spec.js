import { test, expect } from '@playwright/test';

test('tracking overlays require the same frame, run and session mapping as their JPEG', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  let mode = 'match';
  let latest = {
    run_id: 'tracking-fixture-run', frame_seq: 7, mapping_version: 5, width: 640, height: 360,
    source: 'RTSP_LIVE', recorded: true, count: 1, inference_ms: 1,
    detections: [{ session_id: 'session-A', track_id: 'reused-id', box: [0.1, 0.2, 0.3, 0.8], confidence: 0.95,
      workstation_times: [{ zone_id: 'desk', name: 'Desk', presence_us: 15_000_000 }] }],
  };
  const requested = [];
  await page.route('**/pilot/v1/live', route => route.fulfill({ json: {
    status: 'RUNNING', source: 'RTSP_LIVE', session_id: 'live-fixture', camera_key: 'a'.repeat(64),
    run_id: latest.run_id, camera_health: 'ONLINE', processed: 20, latest, calibrations: {},
  } }));
  await page.route('**/pilot/v1/camera-wall', route => route.fulfill({ json: { cameras: [] } }));
  await page.route('**/pilot/v1/camera-wall/view', route => route.fulfill({ json: {} }));
  await page.route('**/pilot/v1/live/preview.jpg*', route => {
    const query = new URL(route.request().url()).searchParams;
    requested.push([query.get('frame_seq'), query.get('run_id')]);
    return route.fulfill({ contentType: 'image/svg+xml', headers: {
      'X-Run-Id': latest.run_id,
      'X-Frame-Sequence': String(latest.frame_seq + (mode === 'wrong-frame' ? 1 : 0)),
      'X-Mapping-Version': String(latest.mapping_version + (mode === 'wrong-mapping' ? 1 : 0)),
    }, body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#263634"/></svg>' });
  });
  await page.goto('/#/live');
  await page.getByLabel('Deteksi', { exact: true }).check();
  const tile = page.locator('[data-camera-id="engine-rtsp"]');
  await expect(tile.getByTestId('rtsp-presence-clock')).toContainText('00:00:15');
  await expect(tile.getByTestId('rtsp-person-detection').locator('rect').first()).toHaveAttribute('x', '64');
  mode = 'wrong-frame';
  await expect(tile.getByTestId('rtsp-person-detection')).toHaveCount(0);
  mode = 'match';
  latest = { ...latest, frame_seq: 9, mapping_version: 8,
    detections: [{ session_id: 'session-B', track_id: 'reused-id', box: [0.6, 0.2, 0.8, 0.8], confidence: 0.95,
      workstation_times: [{ zone_id: 'desk', name: 'Desk', presence_us: 2_000_000 }] }],
  };
  await expect(tile.getByTestId('rtsp-presence-clock')).toContainText('00:00:02');
  await expect(tile.getByTestId('rtsp-person-detection').locator('rect').first()).toHaveAttribute('x', '384');
  mode = 'wrong-mapping';
  await expect(tile.getByTestId('rtsp-person-detection')).toHaveCount(0);
  expect(requested.some(([seq, run]) => seq === '9' && run === latest.run_id)).toBe(true);
  expect(errors).toEqual([]);
});
