import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  testDir: './tests/dataset', testMatch:'annotation.spec.js', outputDir: './test-results/dataset', workers: 1, timeout: 45000,
  use: {baseURL: 'http://127.0.0.1:8782', browserName: 'chromium', channel: 'msedge', viewport: {width:1440,height:1000}},
  webServer: {command:'..\\.venv\\Scripts\\python.exe ../scripts/run_dataset_fixture.py',
    url:'http://127.0.0.1:8782',reuseExistingServer:false,timeout:30000,
    env:{PYTHONPATH:fileURLToPath(new URL('../src',import.meta.url))}},
});
