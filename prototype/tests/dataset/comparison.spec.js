import { test,expect } from '@playwright/test';

test('comparison filters, error navigation, unsupported thresholds and box toggles work',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('#notice')).toContainText('assistant 2');
  await expect(page.getByRole('combobox',{name:'Confidence',exact:true})).toHaveValue('0.45');
  await expect(page.locator('#position')).toHaveText('1 / 2');
  await expect(page.locator('#viewer rect')).toHaveCount(2);
  await page.getByLabel('Hanya frame bermasalah').check();
  await expect(page.locator('#position')).toHaveText('1 / 1');
  await expect(page.locator('#detail')).toContainText('FN 1');
  await expect(page.getByRole('button',{name:'Berikutnya',exact:true})).toBeDisabled();
  await page.getByLabel('Tampilkan label',{exact:true}).uncheck();
  await expect(page.locator('#viewer rect')).toHaveCount(0);
  await page.getByLabel('Hanya frame bermasalah').uncheck();
  await page.getByLabel('Tampilkan label',{exact:true}).check();
  await page.getByRole('combobox',{name:'Detector',exact:true}).selectOption('Fast fixture');
  await expect(page.locator('#detail')).toContainText('FP 1');
  await page.getByLabel('Tampilkan prediksi',{exact:true}).uncheck();
  await expect(page.locator('#viewer rect')).toHaveCount(1);
  await page.getByLabel('Tampilkan prediksi',{exact:true}).check();
  await page.getByRole('button',{name:'Berikutnya',exact:true}).click();
  await expect(page.locator('#position')).toHaveText('2 / 2');
  await page.getByRole('combobox',{name:'Confidence',exact:true}).selectOption('0.25');
  await expect(page.locator('#metrics')).toContainText('UNAVAILABLE_BELOW_CACHE_FLOOR');
  await expect(page.locator('#detail')).toContainText('Threshold tidak tersedia');
  expect(errors).toEqual([]);
});
