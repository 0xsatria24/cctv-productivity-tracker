import { test, expect } from '@playwright/test';

test('dashboard calls Python, shows committed golden metrics, filters, timeline and downloads real CSV',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  await expect(page.getByText('ENGINE TERINTEGRASI',{exact:true})).toBeVisible();
  await expect(page.getByTestId('engine-connection')).toContainText('terhubung');
  const start=page.waitForResponse(r=>r.url().endsWith('/pilot/v1/replay')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Jalankan replay',exact:true}).click();
  expect((await start).status()).toBe(202);
  await expect(page.getByText('Status:',{exact:false}).filter({hasText:'COMPLETED'})).toBeVisible({timeout:30000});
  await page.getByRole('button',{name:'Ringkasan',exact:true}).click();
  await expect(page.getByTestId('engine-metrics')).toContainText('4 dtk');
  await page.getByRole('button',{name:'Laporan',exact:true}).click();
  await expect(page.getByTestId('engine-report')).toContainText('11,2 dtk');
  await page.getByLabel('Workstation',{exact:true}).selectOption({label:'Meja A01'});
  await page.getByRole('button',{name:'Terapkan filter',exact:true}).click();
  await expect(page.getByTestId('engine-report').locator('tbody tr')).toHaveCount(1);
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'Ekspor CSV engine',exact:true}).click();
  const download=await downloadPromise;expect(download.suggestedFilename()).toBe('cctv-engine-report.csv');
  const csv=await page.request.get('/pilot/v1/export.csv?run_id='+await page.getByLabel('Run',{exact:true}).evaluate(el=>el.value==='LATEST'?'':el.value));
  expect(csv.status()).toBe(200);expect(await csv.text()).toContain('SYNTHETIC_REPLAY');
  await page.getByRole('button',{name:'Analitik',exact:true}).click();
  await page.getByRole('button',{name:'Timeline',exact:true}).click();
  await expect(page.getByTestId('engine-intervals')).toContainText('CAMERA_OFFLINE');
  await expect(page.locator('.timeline-segment')).not.toHaveCount(0);
  await page.locator('.timeline-segment').first().click();
  await expect(page.getByRole('dialog')).toContainText('Detail interval');
  await page.getByRole('button',{name:'Tutup dialog',exact:true}).click();
  await page.screenshot({path:'verification/screenshots/engine-analytics-1440.png',fullPage:true});
  expect(errors).toEqual([]);
});

test('employee and assignment forms persist through API and reload without claiming observed identity',async({page})=>{
  await page.goto('/#/workspaces');
  const employeeName='Karyawan UI '+Date.now();
  await page.getByRole('button',{name:'Tambah karyawan',exact:true}).click();
  await page.getByLabel('Nama karyawan',{exact:true}).fill(employeeName);
  await page.getByRole('button',{name:'Simpan ke engine',exact:true}).click();
  await expect(page.getByTestId('engine-employees')).toContainText(employeeName);
  await page.getByRole('button',{name:'Tambah assignment',exact:true}).click();
  await page.getByLabel('Karyawan',{exact:true}).selectOption({label:employeeName});
  // Distinct future interval avoids conflicts with retained runs from previous test executions.
  const state=await (await page.request.get('/pilot/v1/status')).json();
  const unique=Math.ceil(Math.max(Date.now()+3600000,...state.assignments.map(a=>a.effective_to_utc_us/1000+1000))/1000)*1000;
  const start=new Date(unique).toISOString().slice(0,19),end=new Date(unique+3600000).toISOString().slice(0,19);
  await page.getByLabel('Mulai assignment (UTC)',{exact:true}).fill(start);
  await page.getByLabel('Sampai assignment (UTC)',{exact:true}).fill(end);
  await page.getByRole('button',{name:'Simpan ke engine',exact:true}).click();
  await expect(page.getByTestId('engine-assignments')).toContainText(employeeName);
  await page.reload();
  await expect(page.getByTestId('engine-employees')).toContainText(employeeName);
  const report=await page.request.get('/pilot/v1/reports');
  const data=await report.json();expect(data.workstations.every(r=>r.observed_employee_id===null&&r.assignment_is_observed_identity===false)).toBe(true);
  await page.getByRole('button',{name:'Lihat polygon',exact:true}).first().click();
  await expect(page.getByRole('dialog')).toContainText('bukan frame CCTV');
  await page.keyboard.press('Escape');
  await page.screenshot({path:'verification/screenshots/engine-workstations-1440.png',fullPage:true});
});

test('all seven pages navigate; engine outage is explicit and never falls back to mock metrics',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  for(const name of ['Ringkasan','Pemantauan Live','Workstation','Analitik','Laporan','Kamera','Pengaturan']){
    await page.getByRole('button',{name,exact:true}).click();await expect(page.getByRole('heading',{name,exact:true,level:1})).toBeVisible();
  }
  await page.getByRole('button',{name:'Ringkasan',exact:true}).click();
  await page.screenshot({path:'verification/screenshots/engine-overview-1440.png',fullPage:true});
  await page.setViewportSize({width:1100,height:720});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.route('**/pilot/v1/status',route=>route.abort());
  await page.getByRole('button',{name:'Refresh engine',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Engine tidak terhubung');
  await expect(page.getByTestId('engine-connection')).toContainText('terputus');
  await expect(page.getByRole('button',{name:'Jalankan replay',exact:true})).toBeDisabled();
  await expect(page.getByText('DATA SIMULASI',{exact:true})).toHaveCount(0);
  await page.unroute('**/pilot/v1/status');
  await page.getByRole('button',{name:'Refresh engine',exact:true}).click();
  await expect(page.getByTestId('engine-connection')).toContainText('terhubung');
  expect(errors).toEqual([]);
});
