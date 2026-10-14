import { defineConfig } from '@playwright/test';
import engine from './playwright.engine.config.js';
import { cameraTestVideo } from './tests/webcam/source.mjs';

export default defineConfig({
  ...engine,
  testDir: './tests/webcam',
  use: {
    ...engine.use,
    // Automated tests never open a physical webcam. Chromium supplies its test video source.
    launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', `--use-file-for-fake-video-capture=${cameraTestVideo()}`] },
  },
});
