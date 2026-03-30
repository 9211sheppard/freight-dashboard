import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import waitOn from 'wait-on';

const healthURL = process.env.K6_HEALTH_URL || 'http://127.0.0.1:4173/health';
const pythonBin = process.platform === 'win32' ? 'python.exe' : 'python3';

function resolveK6Bin() {
  if (process.env.K6_BIN) {
    return process.env.K6_BIN;
  }
  if (process.platform === 'win32') {
    const winDefault = 'C:\\Program Files\\k6\\k6.exe';
    if (fs.existsSync(winDefault)) {
      return winDefault;
    }
    return 'k6.exe';
  }
  return 'k6';
}

const server = spawn(pythonBin, ['scripts/playwright_server.py'], {
  stdio: 'inherit',
});

try {
  await waitOn({
    resources: [healthURL],
    timeout: 120000,
    validateStatus: (status) => status === 200,
  });

  const result = spawnSync(resolveK6Bin(), ['run', path.join('perf', 'k6-smoke.js')], {
    stdio: 'inherit',
  });

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
} finally {
  server.kill();
}
