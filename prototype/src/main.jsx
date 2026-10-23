import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './Shell';
import { LanguageProvider } from './language';
import { installTheme } from './theme';
import './styles.css';
import './touch-targets.css';
import './workflow.css';

installTheme();
createRoot(document.getElementById('root')).render(<React.StrictMode><LanguageProvider><App /></LanguageProvider></React.StrictMode>);
