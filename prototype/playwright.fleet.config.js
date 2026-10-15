import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  testDir: './tests/fleet', outputDir: './test-results/fleet', timeout: 120000, expect: { timeout: 15000 }, workers: 1, reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:8771', browserName: 'chromium', channel: 'msedge', viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: { command: '..\\.venv\\Scripts\\python.exe ../scripts/run_fleet_fixture.py', url: 'http://127.0.0.1:8771/health', reuseExistingServer: false, timeout: 45000,
    env: { PYTHONPATH: fileURLToPath(new URL('../src', import.meta.url)) } },
});
