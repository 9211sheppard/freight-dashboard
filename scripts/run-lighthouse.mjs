import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from '@playwright/test';
import waitOn from 'wait-on';

const healthURL = process.env.LIGHTHOUSE_HEALTH_URL || 'http://127.0.0.1:4173/health';
const baseURL = process.env.LIGHTHOUSE_URL || 'http://127.0.0.1:4173/login';
const outputDir = path.join(process.cwd(), 'test-results');
const outputPath = path.join(outputDir, 'lighthouse-login.json');
const chromePath = chromium.executablePath();
const pythonBin = process.platform === 'win32' ? 'python.exe' : 'python3';

fs.mkdirSync(outputDir, { recursive: true });

const server = spawn(pythonBin, ['scripts/playwright_server.py'], {
  stdio: 'inherit',
});

try {
  await waitOn({
    resources: [healthURL],
    timeout: 120000,
    validateStatus: (status) => status === 200,
  });

  const result = spawnSync(
    process.execPath,
    [
      path.join('node_modules', 'lighthouse', 'cli', 'index.js'),
      baseURL,
      '--quiet',
      '--chrome-flags=--headless=new --no-sandbox',
      `--chrome-path=${chromePath}`,
      '--only-categories=performance,accessibility,best-practices',
      '--output=json',
      `--output-path=${outputPath}`,
    ],
    { stdio: 'inherit' },
  );

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }

  const report = JSON.parse(fs.readFileSync(outputPath, 'utf8'));
  const categories = report.categories || {};
  const scores = {
    performance: Math.round((categories.performance?.score || 0) * 100),
    accessibility: Math.round((categories.accessibility?.score || 0) * 100),
    bestPractices: Math.round((categories['best-practices']?.score || 0) * 100),
  };

  console.log(JSON.stringify(scores));
} finally {
  server.kill();
}
