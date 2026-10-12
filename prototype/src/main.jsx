import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './Shell';
import { installTheme } from './theme';
import './styles.css';

installTheme();
createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>);
