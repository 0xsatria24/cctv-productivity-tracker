import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './Shell';
import { LanguageProvider } from './language';
import { installTheme } from './theme';
import './styles.css';
import './touch-targets.css';
import './workflow.css';

installTheme();
async function mount() {
  if(import.meta.env.DEV&&window.__CCTV_ENGINE__) {
    try {await fetch('/engine-session',{credentials:'same-origin',signal:AbortSignal.timeout(3000)});} catch {}
  }
  createRoot(document.getElementById('root')).render(<React.StrictMode><LanguageProvider><App /></LanguageProvider></React.StrictMode>);
}
mount();
