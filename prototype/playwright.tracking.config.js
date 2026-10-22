import engine from './playwright.engine.config.js';

export default {
  ...engine,
  testMatch: 'tracking-overlay.spec.js',
  use: { ...engine.use, baseURL: 'http://127.0.0.1:8778' },
  webServer: {
    ...engine.webServer,
    command: '..\\.venv\\Scripts\\python.exe -m cctv_tracker --log-dir ..\\runtime\\logs --database ..\\runtime\\tracking-browser.sqlite3 dashboard --port 8778',
    url: 'http://127.0.0.1:8778',
    reuseExistingServer: false,
  },
};
