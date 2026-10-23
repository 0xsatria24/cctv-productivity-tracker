import { spawn } from 'node:child_process';
import { existsSync, readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const prototype = fileURLToPath(new URL('..', import.meta.url));
const root = path.resolve(prototype, '..');
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const manifest = path.join(root, 'models/reid/person-reidentification-retail-0287/manifest.json');
if (!existsSync(python) || !existsSync(manifest)) {
  console.error('Siapkan .venv dan jalankan .venv/Scripts/python.exe scripts/setup_reid_model.py dari root project.');
  process.exit(1);
}
const output = path.join(root, 'runtime/reid-demo');
const enginePort = '8770', uiPort = '5174';
mkdirSync(output, { recursive: true });
const config = JSON.parse(readFileSync(path.join(root, 'config/pilot.example.json'), 'utf8'));
config.database = path.join(output, 'dashboard.sqlite3');
config.sessions.recovery_confirmation_window_seconds = 2;
config.reid = { mode: 'active', recovery_policy: 'short_occlusion', manifest_path: manifest, device: 'CPU',
  sample_interval_seconds: .2, confirm_seconds: .4, min_confidence: .55, max_gap_seconds: 2, max_extra_latency_ms: 5000 };
const configPath = path.join(output, 'settings.json');
writeFileSync(configPath, JSON.stringify(config, null, 2));
const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill();
  process.exitCode = code;
}
function launch(command, args, cwd, env = process.env) {
  const child = spawn(command, args, { cwd, env, stdio: 'inherit', windowsHide: true });
  children.push(child);
  child.on('error', error => { console.error(error.message); stop(1); });
  child.on('exit', code => { if (!stopping) stop(code ?? 1); });
  return child;
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
console.log(`ReID aktif (eksperimental): http://localhost:${uiPort}/ · database terpisah di runtime/reid-demo`);
launch(python, ['-m', 'cctv_tracker', '--config', configPath, '--log-dir', path.join(output, 'logs'),
  'dashboard', '--port', enginePort, '--detector', 'yolox-openvino', '--openvino-device', 'GPU'], root);
launch(process.execPath, [path.join(prototype, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', uiPort, '--strictPort'], prototype,
  { ...process.env, CCTV_ENGINE_URL: `http://127.0.0.1:${enginePort}` });
