import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test.beforeEach(async ({page})=>{
  page.errors=[];page.external=[];
  page.on('pageerror',error=>page.errors.push(error.message));
  page.on('request',request=>{if(/^https?:/.test(request.url())&&!request.url().startsWith('http://127.0.0.1:5173/'))page.external.push(request.url());});
  await page.goto('/');
  await expect(page.getByRole('heading',{level:1,name:'Ringkasan'})).toBeVisible();
});
test.afterEach(async ({page})=>{expect(page.errors).toEqual([]);expect(page.external).toEqual([]);});

const nav=(page,name)=>page.getByRole('navigation').getByRole('button',{name,exact:true}).click();
async function cameraControls(page){await nav(page,'Pemantauan Live');await page.getByText('Konfigurasi kamera simulasi',{exact:true}).click();}
const close=page=>page.getByRole('button',{name:'Tutup dialog',exact:true}).click();
async function scenario(page,label){await page.getByRole('button',{name:'Skenario',exact:true}).click();await page.getByRole('radio',{name:new RegExp(label)}).check();await page.getByRole('button',{name:'Terapkan skenario',exact:true}).click();}

test('all six pages navigate, hash routes reload and browser history works',async({page})=>{
  for(const name of ['Pemantauan Live','Workstation','Analitik','Laporan','Pengaturan','Ringkasan']){await nav(page,name);await expect(page.getByRole('heading',{level:1,name,exact:true})).toBeVisible();}
  await page.goto('/#/cameras');await expect(page).toHaveURL(/#\/live$/);await page.reload();await expect(page.getByRole('heading',{level:1,name:'Pemantauan Live',exact:true})).toBeVisible();
  await expect(page.getByRole('navigation').getByRole('button',{name:'Kamera',exact:true})).toHaveCount(0);
  await nav(page,'Laporan');await page.goBack();await expect(page.getByRole('heading',{level:1,name:'Pemantauan Live',exact:true})).toBeVisible();
});
test('grid layouts, focused view, overlays and paused preview are functional',async({page})=>{
  await nav(page,'Pemantauan Live');await expect(page.locator('.video-tile')).toHaveCount(4);
  await page.getByRole('button',{name:'3 × 3',exact:true}).click();await expect(page.locator('.video-tile')).toHaveCount(6);
  await page.getByRole('button',{name:'Fokus',exact:true}).click();await expect(page.locator('.video-tile')).toHaveCount(1);
  await page.getByLabel('Deteksi',{exact:true}).check();await expect(page.locator('.detection-box').first()).toBeVisible();
  await page.getByLabel('Track ID',{exact:true}).check();await expect(page.locator('.track-label').first()).toBeVisible();
  await page.getByRole('button',{name:'Jeda preview',exact:true}).click();const before=await page.locator('.video-footer .mono').textContent();
  await page.getByRole('button',{name:'+1 menit',exact:true}).click();await expect(page.locator('.video-footer .mono')).toHaveText(before);
  await expect(page.locator('.simulation-clock')).toContainText('10:43:00');await page.getByRole('button',{name:'Lanjutkan preview',exact:true}).click();await expect(page.locator('.video-footer .mono')).toHaveText('10:43:00');
});
test('offline and inference states keep unknown separate; reconnect recovers',async({page})=>{
  await nav(page,'Pemantauan Live');await scenario(page,'Kamera pertama offline');
  await expect(page.locator('.monitor-inspector .zone-observation .status').first()).toHaveText('Tidak diketahui');
  await page.getByLabel('Simulasi koneksi kamera terpilih').selectOption('RECONNECTING');await page.getByRole('button',{name:'+1 menit',exact:true}).click();
  await expect(page.getByLabel('Simulasi koneksi kamera terpilih')).toHaveValue('ONLINE');
  await scenario(page,'Inference kamera pertama terganggu');await expect(page.locator('.video-tile').first().locator('.sim-scene')).toBeVisible();await expect(page.locator('.monitor-inspector .zone-observation .status').first()).toHaveText('Tidak diketahui');
});
test('manual activity generates events and automatic simulation can pause',async({page})=>{
  await nav(page,'Pemantauan Live');await page.locator('.zone-observation').first().getByRole('button',{name:'Kosong',exact:true}).click();
  await expect(page.locator('.zone-observation').first().locator('.status')).toHaveText('Kosong');await expect(page.locator('.event-list')).toContainText('observasi manual menjadi EMPTY');
  await page.getByRole('button',{name:'Mulai simulasi',exact:true}).click();await expect(page.locator('.simulation-clock')).toContainText('10:43:00',{timeout:6500});await page.getByRole('button',{name:'Jeda simulasi',exact:true}).click();
});
test('camera form saves configuration, does not persist a password, and connection test completes',async({page})=>{
  await cameraControls(page);await page.getByRole('button',{name:'Tambah kamera',exact:true}).click();
  await page.getByLabel('Nama kamera',{exact:true}).fill('Area inspeksi');await page.getByLabel('Password contoh (opsional)',{exact:false}).fill('mock-only-should-not-be-stored');
  await page.getByRole('button',{name:'Simpan kamera',exact:true}).click();
  await expect(page.locator('tbody')).toContainText('Area inspeksi');
  const stored=await page.evaluate(()=>localStorage.getItem('cctv-design-prototype-v1'));expect(stored).not.toContain('mock-only-should-not-be-stored');
  const row=page.locator('tbody tr').filter({hasText:'Area inspeksi'});await row.getByRole('button',{name:'Uji koneksi',exact:true}).click();
  await expect(page.locator('.job-row').first()).toContainText('Selesai');await close(page);await expect(row).toContainText('Terhubung');
});
test('failed connection scenario produces failed job and offline camera',async({page})=>{
  await cameraControls(page);await page.getByRole('button',{name:'Area produksi CAM-01',exact:true}).click();
  await page.getByRole('button',{name:'Simulasi uji gagal',exact:true}).click();await expect(page.locator('.job-row').first()).toContainText('Gagal');await close(page);
  await expect(page.locator('tbody tr').filter({hasText:'Area produksi'})).toContainText('Tidak terhubung');
});
test('workstation search, polygon keyboard editing, undo, revision review and apply work',async({page})=>{
  await nav(page,'Workstation');await page.getByLabel('Cari workstation',{exact:true}).fill('A01');await expect(page.locator('tbody tr')).toHaveCount(1);
  await page.getByRole('button',{name:'Edit polygon',exact:true}).click();await page.getByLabel('Nama workstation',{exact:true}).fill('Meja A01 revisi');
  await page.getByLabel('Koordinat X titik 1',{exact:true}).fill('0.18');await page.getByRole('button',{name:'Undo',exact:true}).click();await expect(page.getByLabel('Koordinat X titik 1',{exact:true})).toHaveValue('0.12');
  await page.getByRole('button',{name:'Review dan simpan',exact:true}).first().click();await page.getByRole('button',{name:'Simpan revisi',exact:true}).click();
  await expect(page.locator('tbody')).toContainText('Meja A01 revisi');await expect(page.locator('tbody')).toContainText('v2');
  await expect(page.locator('tbody')).not.toContainText('pending',{timeout:7000});
});
test('analytics range and resolution filters, chart legend, heatmap and timeline detail work',async({page})=>{
  await nav(page,'Analitik');await page.getByLabel('Periode',{exact:true}).selectOption('YEAR');await page.getByRole('button',{name:'Terapkan filter',exact:true}).click();
  await expect(page.locator('.report-metadata')).toContainText('2026-01-01');await expect(page.getByLabel('Resolusi',{exact:true})).toHaveValue('MONTH');
  await page.getByRole('button',{name:'Coverage observasi',exact:true}).click();await expect(page.locator('path.chart-line.coverage')).toHaveCount(0);
  await page.getByRole('button',{name:'Heatmap 7 hari',exact:true}).click();await page.locator('.heat-cell').filter({hasText:/^\d+$/}).first().click();await expect(page.locator('.selection-detail')).toContainText('Coverage');
  await page.getByRole('button',{name:'Timeline',exact:true}).click();await page.locator('.timeline-segment').first().click();await page.getByRole('button',{name:'Detail sumber',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Fixture/simulasi lokal');
});
test('report sorting, pagination, full-result export and CSV download work',async({page})=>{
  await nav(page,'Laporan');await page.getByRole('button',{name:'Halaman berikutnya',exact:true}).click();await expect(page.locator('.table-pagination')).toContainText('9-16');
  await page.getByRole('button',{name:'Urutkan Terisi (j:m)',exact:true}).click();await expect(page.locator('.table-pagination')).toContainText('1-8');
  await page.getByRole('button',{name:'Ekspor CSV',exact:true}).click();await expect(page.getByRole('button',{name:'Unduh CSV',exact:true})).toBeVisible();
  const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Unduh CSV',exact:true}).click();const download=await downloadPromise;
  const content=await readFile(await download.path(),'utf8');expect(content).toContain('DATA SIMULASI, BUKAN DATA CCTV');expect(content.split('\r\n').length).toBeGreaterThan(16);
});
test('export cancellation and expired snapshot recovery are functional',async({page})=>{
  await nav(page,'Laporan');await page.getByRole('button',{name:'Ekspor CSV',exact:true}).click();await page.getByRole('button',{name:'Batalkan',exact:true}).click();await expect(page.locator('.job-row').first()).toContainText('Dibatalkan');await close(page);
  await scenario(page,'Snapshot laporan kedaluwarsa');await expect(page.getByRole('heading',{name:'Snapshot laporan kedaluwarsa (simulasi)'})).toBeVisible();await page.getByRole('button',{name:'Muat ulang laporan',exact:true}).click();await expect(page.getByTestId('report-table')).toBeVisible();
});
test('backup snapshot restores changed settings and retention blocks old detail explicitly',async({page})=>{
  await nav(page,'Pengaturan');await page.getByRole('button',{name:'Retention dan backup',exact:true}).click();await page.getByRole('button',{name:'Buat backup simulasi',exact:true}).click();
  await expect(page.locator('tbody')).toContainText('Backup 1');
  await page.getByRole('button',{name:'Lokasi dan kalender',exact:true}).click();await page.getByLabel('Nama lokasi',{exact:true}).fill('Lokasi berubah');await page.getByRole('button',{name:'Review perubahan',exact:true}).click();await page.getByRole('button',{name:'Simpan pengaturan',exact:true}).click();await expect(page.locator('.page-header .eyebrow')).toHaveText('Lokasi berubah');
  await page.getByRole('button',{name:'Retention dan backup',exact:true}).click();await page.getByRole('button',{name:'Pulihkan',exact:true}).click();await page.getByRole('button',{name:'Pulihkan snapshot',exact:true}).click();await expect(page.locator('.job-row').first()).toContainText('Selesai');await close(page);await expect(page.locator('.page-header .eyebrow')).toContainText('Pabrik Nusantara');
  await page.getByLabel('Detail interval (hari)',{exact:true}).fill('30');await page.getByRole('button',{name:'Review retention',exact:true}).click();await page.getByRole('button',{name:'Simpan pengaturan',exact:true}).click();
  await nav(page,'Analitik');await page.getByLabel('Periode',{exact:true}).selectOption('YEAR');await page.getByRole('button',{name:'Terapkan filter',exact:true}).click();await expect(page.getByRole('heading',{name:'Detail interval tidak tersedia'})).toBeVisible();await page.getByRole('button',{name:'Gunakan agregat kalender',exact:true}).click();await expect(page.getByTestId('analytics-table')).toBeVisible();
});
test('empty first-run state uses N/A, and reset restores the fixture',async({page})=>{
  await scenario(page,'Belum ada kamera / data');await expect(page.getByRole('heading',{name:'Workspace simulasi masih kosong'})).toBeVisible();
  await nav(page,'Laporan');await expect(page.locator('.metric-strip')).toContainText('N/A');
  await nav(page,'Pengaturan');await page.getByRole('button',{name:'Dataset prototipe',exact:true}).click();await page.getByRole('button',{name:'Reset data simulasi',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'Reset data simulasi',exact:true}).click();
  await cameraControls(page);await expect(page.locator('tbody tr')).toHaveCount(6);
});
test('modal focus, Escape and desktop resize work; actual screenshots are captured',async({page})=>{
  await page.screenshot({path:'verification/screenshots/overview-1440.png',fullPage:true});
  await page.getByRole('button',{name:'Skenario',exact:true}).click();await expect(page.getByRole('dialog')).toBeVisible();await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.getByRole('button',{name:'Skenario',exact:true})).toBeFocused();
  await nav(page,'Pemantauan Live');await page.screenshot({path:'verification/screenshots/live-1440.png',fullPage:true});
  await page.setViewportSize({width:1100,height:720});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);await page.getByRole('button',{name:'Detail kamera',exact:true}).click();await expect(page.locator('.monitor-inspector')).toBeVisible();await page.screenshot({path:'verification/screenshots/live-1100.png',fullPage:true});
  await page.setViewportSize({width:1440,height:1000});await nav(page,'Workstation');await page.getByRole('button',{name:'Edit polygon',exact:true}).first().click();await page.screenshot({path:'verification/screenshots/editor-1440.png',fullPage:true});
});
