import { test, expect } from '@playwright/test';
import { localInput, periodRange } from '../../src/operations-domain.mjs';

test('overview defaults to real-camera reports, separates current observations and keeps runtime details in settings', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByLabel('Sumber data laporan', { exact: true })).toHaveValue('live');
  const current = page.getByTestId('operational-live-metrics');
  await expect(current).toContainText('Kamera terhubung');
  await expect(current).toContainText('Orang terdeteksi');
  await expect(current).toContainText('Belum tersedia');
  await expect(page.getByRole('heading', { name: 'Kondisi kamera', exact: true })).toBeVisible();
  await page.screenshot({ path: 'verification/screenshots/operations-overview-1440.png', fullPage: true });
  await page.getByRole('button', { name: 'Siapkan monitoring', exact: true }).click();
  await expect(page).toHaveURL(/#\/live$/);
  await expect(page.getByRole('heading', { name: '1. Pilih sumber kamera', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Pengaturan', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Runtime lokal', exact: true })).not.toBeVisible();
  await page.getByText('Diagnostik teknis', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Runtime lokal', exact: true })).toBeVisible();
  for (const width of [1440, 1100, 760]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
});

test('overnight shift filters reach the API with exact location bounds, explain unknown, export and drill into timeline', async ({ page }) => {
  await page.goto('/#/reports');
  await page.getByLabel('Sumber data laporan', { exact: true }).selectOption('replay');
  const state = await (await page.request.get('/pilot/v1/status')).json();
  expect(state.runs.length).toBeGreaterThan(0);
  const date = localInput(state.runs[0].started_utc_us, state.timezone).slice(0, 10);
  const expected = periodRange('shift', date, state.timezone, '23:00', '07:00');
  await page.getByLabel('Periode laporan', { exact: true }).selectOption('shift');
  await page.getByLabel('Tanggal laporan', { exact: true }).fill(date);
  await page.getByLabel('Jam mulai shift', { exact: true }).fill('23:00');
  await page.getByLabel('Jam selesai shift', { exact: true }).fill('07:00');
  const response = page.waitForResponse(r => { const u = new URL(r.url()); return u.pathname === '/pilot/v1/reports' && u.searchParams.get('start_utc_us') === String(expected.start) && u.searchParams.get('end_utc_us') === String(expected.end); });
  await page.getByRole('button', { name: 'Terapkan filter', exact: true }).click();
  const data = await (await response).json();
  expect(data.start_utc_us).toBe(expected.start); expect(data.end_utc_us).toBe(expected.end);
  expect(data.schedule_applied).toBe(false);
  await expect(page.getByLabel('Sesi monitoring', { exact: true })).toHaveValue('ALL');
  await expect(page.getByText(/Kalender kerja otomatis belum diterapkan/)).toBeVisible();
  await page.getByRole('button', { name: 'Penjelasan durasi tidak diketahui', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Persentase keterisian');
  await page.getByRole('button', { name: 'Mengerti', exact: true }).click();
  await page.getByRole('button', { name: 'Reset rentang', exact: true }).click();
  await page.getByLabel('Sesi monitoring', { exact: true }).selectOption('LATEST');
  await expect(page.getByRole('button', { name: 'Ekspor CSV', exact: true })).toBeEnabled();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Ekspor CSV', exact: true }).click();
  expect((await download).suggestedFilename()).toBe('cctv-engine-report.csv');
  await page.screenshot({ path: 'verification/screenshots/operations-reports-1440.png', fullPage: true });
  await page.getByRole('button', { name: 'Lihat timeline', exact: true }).first().click();
  await expect(page).toHaveURL(/#\/analytics$/);
  await expect(page.getByTestId('engine-intervals')).toBeVisible();
  await page.locator('.timeline-segment').first().click();
  await expect(page.getByRole('dialog')).toContainText('Detail interval');
});

test('invalid and future reporting ranges show actionable errors without applying them', async ({ page }) => {
  await page.goto('/#/reports');
  await expect(page.getByLabel('Periode laporan', { exact: true })).toBeVisible();
  await page.getByLabel('Periode laporan', { exact: true }).selectOption('shift');
  await page.getByLabel('Jam mulai shift', { exact: true }).fill('07:00');
  await page.getByLabel('Jam selesai shift', { exact: true }).fill('07:00');
  await page.getByRole('button', { name: 'Terapkan filter', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('berbeda');
  await page.getByLabel('Periode laporan', { exact: true }).selectOption('day');
  await page.getByLabel('Tanggal laporan', { exact: true }).fill('2099-01-01');
  await page.getByRole('button', { name: 'Terapkan filter', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('belum dimulai');
});
