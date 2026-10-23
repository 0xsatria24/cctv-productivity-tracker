import { defineConfig } from '@playwright/test';
import webcam from './playwright.webcam.config.js';

export default defineConfig({
  ...webcam,
  testMatch: 'calibration.spec.js',
  use: { ...webcam.use, baseURL: 'http://127.0.0.1:8877' },
  webServer: {
    ...webcam.webServer,
    command: '..\\.venv\\Scripts\\python.exe -m cctv_tracker --log-dir ..\\runtime\\logs --database ..\\runtime\\calibration-browser-test.sqlite3 dashboard --port 8877',
    url: 'http://127.0.0.1:8877',
    reuseExistingServer: false,
  },
});
