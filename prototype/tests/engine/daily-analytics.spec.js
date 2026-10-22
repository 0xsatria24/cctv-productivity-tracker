import { test, expect } from '@playwright/test';

test('daily analytics uses stored observations, exports filtered CSV and opens the selected day timeline', async ({ page }) => {
  test.setTimeout(150000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/analytics');
  await page.getByLabel('Sumber data laporan', { exact: true }).selectOption('replay');
  await expect(page.getByTestId('engine-connection')).toContainText('terhubung');
  const status = await page.request.post('/pilot/v1/replay', { headers: { Origin: 'http://127.0.0.1:8766' } });
  expect([202, 409]).toContain(status.status());
  await expect.poll(async () => (await (await page.request.get('/pilot/v1/status')).json()).controller.status, { timeout: 120000 }).toBe('COMPLETED');
  await page.getByRole('button', { name: 'Perbarui status', exact: true }).click();
  await page.getByRole('button', { name: 'Rekap Harian', exact: true }).click();
  // The default daily view is today; inspect the stored replay period explicitly.
  await page.getByRole('button', { name: 'Reset rentang', exact: true }).click();
  await page.getByLabel('Sesi monitoring', { exact: true }).selectOption('LATEST');
  const table = page.getByTestId('engine-daily-analytics');
  await expect(table.locator('tbody tr')).toHaveCount(2);
  await expect(table).toContainText('00:00:04');
  await expect(table).toContainText('Rentang parsial');
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Ekspor rekap harian', exact: true }).click();
  expect((await downloaded).suggestedFilename()).toBe('cctv-daily-report.csv');
  for (const width of [1440, 1100, 760]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: 'verification/screenshots/daily-analytics-1440.png', fullPage: true });
  await table.getByRole('button', { name: 'Lihat timeline', exact: true }).first().click();
  await expect(page.getByRole('button', { name: 'Timeline', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('engine-intervals').locator('tbody tr')).not.toHaveCount(0);
  expect(errors).toEqual([]);
});
