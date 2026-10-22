// Visual check against a real, running backend (no mocked API except the optional Ask screenshot).
//
//   GS_API=http://localhost:8000/api PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node e2e/live.mjs [outDir]
//
// Builds the app with VITE_API_BASE_URL pointing at the backend, serves the build,
// picks sample records from the live data, and captures the main screens in light and dark.
// Load data first (for example with backend/scripts/seed_demo_data.py).

import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { chatReply } from './fixtures.mjs';

const API = (process.env.GS_API ?? 'http://localhost:8000/api').replace(/\/$/, '');
const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const outDir = resolve(process.argv[2] ?? resolve(root, 'e2e/screens-live'));
const distDir = resolve(outDir, '..', '.gs-live-dist');
const PORT = 4181;
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(outDir, { recursive: true });

const get = async (path) => {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(`${path} responded ${response.status}`);
  return response.json();
};

// ── Sample records from the live data ─────────────────────
const summary = await get('/graph/summary');
if (Object.values(summary.nodes).every((n) => n === 0)) {
  console.error('The backend has no data. Load some first (backend/scripts/seed_demo_data.py).');
  process.exit(2);
}
const first = async (type) => (await get(`/graph/entities/${type}?limit=1`)).entities[0]?.id;
const sample = {
  customer: await first('Customer'),
  salesOrder: await first('SalesOrder'),
  invoice: await first('Invoice'),
};
console.log('sample records', sample);

// ── Build and serve ───────────────────────────────────────
if (!process.env.SKIP_BUILD) {
  const build = spawnSync('npx', ['vite', 'build', '--outDir', distDir, '--emptyOutDir'], {
    cwd: root,
    env: { ...process.env, VITE_API_BASE_URL: API },
    stdio: 'inherit',
  });
  if (build.status !== 0) process.exit(build.status ?? 1);
}
const preview = spawn('npx', ['vite', 'preview', '--outDir', distDir, '--port', String(PORT), '--strictPort', '--host', '127.0.0.1'], { cwd: root, stdio: 'ignore' });
process.on('exit', () => preview.kill());
for (let attempt = 0; attempt < 60; attempt += 1) {
  try {
    if ((await fetch(BASE)).ok) break;
  } catch {
    /* not up yet */
  }
  await new Promise((r) => setTimeout(r, 250));
}

const browser = await chromium.launch({ args: ['--no-sandbox'] }).catch(() => chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] }));
const shots = [];
const problems = [];

async function settleGraph(page) {
  await page.waitForFunction(() => {
    const canvas = document.querySelector('[data-testid="graph-canvas"]');
    return canvas && Number(canvas.getAttribute('data-records')) > 0;
  });
  await page.waitForTimeout(1400);
}

async function shot(page, name) {
  const file = resolve(outDir, `${name}.png`);
  await page.screenshot({ path: file });
  shots.push(file);
  console.log('saved', file);
}

async function open(page, path) {
  await page.goto(`${BASE}${path}`);
  await page.waitForLoadState('networkidle');
}

for (const scheme of ['light', 'dark']) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: scheme, reducedMotion: 'reduce', deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.on('pageerror', (error) => problems.push(`[${scheme}] pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error' && !/Failed to load resource|net::ERR/.test(message.text())) problems.push(`[${scheme}] console: ${message.text()}`);
  });
  page.on('response', (response) => {
    if (response.url().startsWith(API) && response.status() >= 400 && !response.url().endsWith('/chat')) problems.push(`[${scheme}] ${response.status()} ${response.url()}`);
  });
  const name = (base) => `${base}-${scheme}`;

  await open(page, '/');
  await page.waitForSelector('text=What’s in your data');
  await shot(page, name('overview'));

  await open(page, '/explore');
  await settleGraph(page);
  await shot(page, name('explore'));

  await open(page, `/explore?focus=${encodeURIComponent(`SalesOrder:${sample.salesOrder}`)}`);
  await settleGraph(page);
  await page.waitForSelector('text=Relationships');
  await page.waitForTimeout(500);
  await shot(page, name('explore-inspector'));

  await open(page, `/explore?focus=${encodeURIComponent(`Customer:${sample.customer}`)}`);
  await settleGraph(page);
  await page.waitForSelector('text=Relationships');
  await page.waitForTimeout(500);
  await shot(page, name('explore-inspector-customer'));

  await open(page, '/records/SalesOrder');
  await page.waitForSelector('role=table');
  await shot(page, name('records'));
  await page.getByRole('row', { name: /Sales order .* open details/ }).first().click();
  await page.waitForSelector('text=Relationships');
  await page.waitForTimeout(500);
  await shot(page, name('records-inspector'));

  await open(page, '/records/Product');
  await page.waitForSelector('role=table');
  await shot(page, name('records-products'));

  await open(page, '/flows/full_o2c');
  await settleGraph(page);
  await shot(page, name('flow'));

  await open(page, `/trace?type=Invoice&id=${sample.invoice}`);
  await settleGraph(page);
  await page.waitForSelector('text=Starting point');
  await shot(page, name('trace'));

  // The real chat endpoint, which cannot answer without a model key: the message must be clear.
  await open(page, '/ask');
  await page.waitForSelector('text=What would you like to know?');
  await page.locator('#ask-input').fill('Which customer has the most sales orders?');
  await page.locator('#ask-input').press('Enter');
  await page.waitForSelector('[role="status"][aria-live="polite"]', { state: 'detached', timeout: 15000 });
  await page.waitForTimeout(600);
  await shot(page, name('ask-live'));

  // Mocked chat for a populated Ask screenshot.
  await page.route('**/api/chat', async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}');
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(chatReply(body.message ?? '')) });
  });
  await open(page, '/ask');
  await page.locator('#ask-input').fill('Which customer has the most sales orders?');
  await page.locator('#ask-input').press('Enter');
  await page.waitForSelector('text=has the most sales orders');
  await page.waitForTimeout(400);
  await shot(page, name('ask-mocked'));

  await context.close();
}

await browser.close();
preview.kill();

console.log(`\n${shots.length} screenshots written to ${outDir}`);
if (problems.length > 0) {
  console.log('\nProblems:');
  for (const problem of problems) console.log(' -', problem);
  process.exitCode = 1;
}
