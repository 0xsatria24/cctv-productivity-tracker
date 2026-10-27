import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  plugins: [react(),{
    name:'local-engine-dashboard',
    transformIndexHtml(html) {
      return process.env.CCTV_ENGINE_URL?{html,tags:[{tag:'script',children:'window.__CCTV_ENGINE__=true;',injectTo:'head'}]}:html;
    },
  }],
  server: {
    proxy: {
      '/pilot/': {target:process.env.CCTV_ENGINE_URL || 'http://127.0.0.1:8765',changeOrigin:false},
      '/engine-session': {target:process.env.CCTV_ENGINE_URL || 'http://127.0.0.1:8765',changeOrigin:false,rewrite:()=> '/'},
    },
    fs: { allow: [fileURLToPath(new URL('.', import.meta.url)), fileURLToPath(new URL('../docs/ui/design-tokens.json', import.meta.url))] },
  },
  build: { target: 'es2022' },
});
