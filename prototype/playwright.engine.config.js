import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir:'./tests/engine',timeout:45000,expect:{timeout:12000},workers:1,
  reporter:[['list']],
  use:{baseURL:'http://127.0.0.1:8766',browserName:'chromium',channel:process.env.PROTOTYPE_BROWSER_CHANNEL||'msedge',viewport:{width:1440,height:1000},screenshot:'only-on-failure',trace:'retain-on-failure'},
  webServer:{command:'..\\.venv\\Scripts\\python.exe -m cctv_tracker --log-dir ..\\runtime\\logs --database ..\\runtime\\dashboard-browser-test.sqlite3 dashboard --port 8766',url:'http://127.0.0.1:8766',reuseExistingServer:true,timeout:45000,env:{MPLCONFIGDIR:process.env.MPLCONFIGDIR||'../runtime/matplotlib'}},
});
