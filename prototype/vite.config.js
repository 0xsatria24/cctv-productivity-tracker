import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/pilot/': {target:process.env.CCTV_ENGINE_URL || 'http://127.0.0.1:8765',changeOrigin:false},
      '/engine-session': {target:process.env.CCTV_ENGINE_URL || 'http://127.0.0.1:8765',changeOrigin:false,rewrite:()=> '/'},
    },
    fs: { allow: [fileURLToPath(new URL('.', import.meta.url)), fileURLToPath(new URL('../docs/ui/design-tokens.json', import.meta.url))] },
  },
  build: { target: 'es2022' },
});
