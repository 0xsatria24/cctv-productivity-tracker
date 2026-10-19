import { test, expect } from '@playwright/test';

test('synthetic browser webcam records preview MP4 across navigation and releases on stop', async ({page}) => {
  await page.goto('/#/live');
  const headers = {Origin:'http://127.0.0.1:8766'};
  const original = (await (await page.request.get('/pilot/v1/recordings')).json()).policy;
  const before = new Set((await (await page.request.get('/pilot/v1/recordings')).json()).files.map(f=>f.id));
  try {
    expect((await page.request.post('/pilot/v1/recordings/policy',{headers,data:{...original,video_enabled:true,video_segment_seconds:5,data_enabled:false}})).ok()).toBeTruthy();
    await page.getByRole('button',{name:'Mulai webcam',exact:true}).click();
    await expect(page.getByLabel('Preview webcam lokal',{exact:true})).toBeVisible();
    await expect.poll(async()=>(await (await page.request.get('/pilot/v1/recordings')).json()).active_videos.some(v=>v.source_id==='webcam'),{timeout:20000}).toBe(true);
    await page.getByRole('button',{name:'Ringkasan',exact:true}).click();
    await expect.poll(async()=>(await (await page.request.get('/pilot/v1/recordings')).json()).files.some(f=>f.kind==='video'&&f.source_id==='webcam'&&!before.has(f.id)),{timeout:20000}).toBe(true);
    const record = (await (await page.request.get('/pilot/v1/recordings')).json()).files.find(f=>f.kind==='video'&&f.source_id==='webcam'&&!before.has(f.id));
    expect(record.frames).toBeGreaterThan(1);
    const video = await page.request.get(`/pilot/v1/recordings/files/${record.id}/mp4`);
    expect(video.headers()['content-type']).toBe('video/mp4');
    expect((await video.body()).subarray(4,8).toString()).toBe('ftyp');
    expect((await page.request.post('/pilot/v1/recordings/policy',{headers,data:{...original,video_enabled:false}})).ok()).toBeTruthy();
    await expect.poll(async()=>(await (await page.request.get('/pilot/v1/recordings')).json()).active_videos.length).toBe(0);
    await page.getByRole('button',{name:'Pemantauan Live',exact:true}).click();
    await page.getByRole('button',{name:'Hentikan webcam',exact:true}).click();
  } finally {
    await page.request.post('/pilot/v1/recordings/policy',{headers,data:original});
  }
});
