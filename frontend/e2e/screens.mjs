// Visual check: builds the app against mocked API routes and captures every page
// in light and dark. Run with `npm run e2e:screens` (see package.json).
//
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node e2e/screens.mjs [outDir]
//
// Nothing here ships in the bundle: fixtures live next to this file.

import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { EMPTY_SUMMARY, SAMPLE_IDS, SCHEMA, SUMMARY, chatReply, entities, flowGraph, fullGraph, subgraph } from './fixtures.mjs';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const outDir = resolve(process.argv[2] ?? resolve(root, 'e2e/screens'));
const distDir = resolve(outDir, '..', '.gs-e2e-dist');
const PORT = 4179;
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(outDir, { recursive: true });

// ── Build and serve ───────────────────────────────────────
if (!process.env.SKIP_BUILD) {
  const build = spawnSync('npx', ['vite', 'build', '--outDir', distDir, '--emptyOutDir'], {
    cwd: root,
    env: { ...process.env, VITE_API_BASE_URL: '/api' },
    stdio: 'inherit',
  });
  if (build.status !== 0) process.exit(build.status ?? 1);
}
const preview = spawn('npx', ['vite', 'preview', '--outDir', distDir, '--port', String(PORT), '--strictPort', '--host', '127.0.0.1'], { cwd: root, stdio: 'ignore' });
process.on('exit', () => preview.kill());

for (let attempt = 0; attempt < 60; attempt += 1) {
  try {
    const response = await fetch(BASE);
    if (response.ok) break;
  } catch {
    /* not up yet */
  }
  await new Promise((r) => setTimeout(r, 250));
}

// ── Mocked API ────────────────────────────────────────────
const state = { empty: false, offline: false, noSchema: false };

async function installApi(context) {
  await context.route('**/api/**', async (route) => {
    if (state.offline) return route.abort('connectionrefused');
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^.*\/api/, '');
    const q = url.searchParams;
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

    if (path === '/health') return json({ status: 'ok' });
    if (path === '/graph/summary') return json(state.empty ? EMPTY_SUMMARY : SUMMARY);
    if (path === '/graph/schema') return state.noSchema ? json({ detail: 'Not Found' }, 404) : json(SCHEMA);
    if (path === '/graph/flows') return json({ flows: SCHEMA.flows });
    if (path === '/graph/full') return json(fullGraph(Number(q.get('node_limit') ?? 12)));
    if (path === '/graph/subgraph') return json(subgraph(q.get('root_type'), q.get('root_id'), Number(q.get('depth') ?? 1)));
    if (path === '/graph/trace') return json(subgraph(q.get('doc_type'), q.get('doc_id'), Number(q.get('depth') ?? 4)));
    if (path === '/graph/flow') {
      const graph = flowGraph(q.get('flow_id'));
      return graph ? json(graph) : json({ detail: 'Unknown flow' }, 404);
    }
    if (path.startsWith('/graph/entities/')) return json(entities(decodeURIComponent(path.split('/').pop()), Number(q.get('limit') ?? 50)));
    if (path === '/chat') {
      const body = JSON.parse(request.postData() ?? '{}');
      await new Promise((r) => setTimeout(r, 450));
      return json(chatReply(body.message ?? ''));
    }
    if (path === '/ingest') return json({ message: 'Ingestion started in background' });
    return json({ detail: 'Not mocked' }, 404);
  });
}

// ── Helpers ───────────────────────────────────────────────
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

async function shot(page, name, options = {}) {
  const file = resolve(outDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: options.fullPage ?? false });
  shots.push(file);
  console.log('saved', file);
}

async function open(page, path) {
  await page.goto(`${BASE}${path}`);
  await page.waitForLoadState('networkidle');
}

async function run(scheme, viewport, tag, scenarios) {
  const context = await browser.newContext({ viewport, colorScheme: scheme, reducedMotion: 'reduce', deviceScaleFactor: 1 });
  await installApi(context);
  const page = await context.newPage();
  page.on('pageerror', (error) => problems.push(`[${tag}-${scheme}] pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error' && !/Failed to load resource|net::ERR/.test(message.text())) problems.push(`[${tag}-${scheme}] console: ${message.text()}`);
  });
  await scenarios(page, (name) => (tag ? `${name}-${tag}-${scheme}` : `${name}-${scheme}`));
  await context.close();
}

const desktop = { width: 1440, height: 900 };
const mobile = { width: 390, height: 844 };

for (const scheme of ['light', 'dark']) {
  await run(scheme, desktop, '', async (page, name) => {
    state.empty = false;
    state.offline = false;
    state.noSchema = false;

    await open(page, '/');
    await page.waitForSelector('text=What’s in your data');
    await shot(page, name('overview'));

    await open(page, `/explore?focus=${encodeURIComponent(`Customer:${SAMPLE_IDS.customer}`)}`);
    await settleGraph(page);
    await page.waitForSelector('text=Relationships');
    await page.waitForTimeout(400);
    await shot(page, name('explore-inspector'));

    await open(page, '/explore');
    await settleGraph(page);
    await shot(page, name('explore'));

    // Ask panel inside Explore
    await page.getByRole('button', { name: 'Ask', exact: true }).click();
    await page.waitForTimeout(300);
    await shot(page, name('explore-ask-panel'));

    await open(page, '/ask');
    await page.waitForSelector('text=What would you like to know?');
    await shot(page, name('ask-welcome'));
    await page.locator('#ask-input').fill('Which customer has the most sales orders?');
    await page.locator('#ask-input').press('Enter');
    await page.waitForSelector('text=has the most sales orders');
    await page.getByRole('button', { name: 'View query' }).click();
    await page.waitForTimeout(300);
    await shot(page, name('ask'));

    await page.locator('#ask-input').fill('Write me a poem about invoices');
    await page.locator('#ask-input').press('Enter');
    await page.waitForSelector('text=outside what I can help with');
    await page.waitForTimeout(300);
    await shot(page, name('ask-guardrail'));

    await open(page, '/flows');
    await page.waitForSelector('text=Sales flow');
    await shot(page, name('flows'));

    await open(page, '/flows/full_o2c');
    await settleGraph(page);
    await shot(page, name('flow'));

    await open(page, `/trace?type=Customer&id=${SAMPLE_IDS.customer}`);
    await settleGraph(page);
    await page.waitForSelector('text=Starting point');
    await shot(page, name('trace'));

    await open(page, '/trace');
    await page.waitForSelector('text=Pick a record to trace');
    await shot(page, name('trace-empty'));

    await open(page, '/records/SalesOrder');
    await page.waitForSelector('role=table');
    await shot(page, name('records'));
    await page.getByRole('row', { name: /Sales order .* open details/ }).first().click();
    await page.waitForSelector('text=Relationships');
    await page.waitForTimeout(400);
    await shot(page, name('records-inspector'));

    await open(page, '/');
    await page.waitForSelector('text=What’s in your data');
    await page.keyboard.press('Control+k');
    await page.getByRole('combobox', { name: 'Search' }).fill('sales');
    await page.waitForTimeout(700);
    await shot(page, name('palette'));
    await page.getByRole('combobox', { name: 'Search' }).fill(SAMPLE_IDS.customer);
    await page.waitForTimeout(1000);
    await shot(page, name('palette-record'));
    await page.keyboard.press('Escape');

    // Collapsed sidebar
    await page.getByRole('button', { name: 'Collapse sidebar' }).click();
    await page.waitForTimeout(300);
    await shot(page, name('overview-collapsed'));
    await page.getByRole('button', { name: 'Expand sidebar' }).click();

    // Empty dataset
    state.empty = true;
    await open(page, '/');
    await page.waitForSelector('text=Load your data to get started');
    await shot(page, name('empty'));
    await page.getByRole('button', { name: 'Load data' }).click();
    await page.waitForSelector('text=Loading has started');
    await shot(page, name('empty-started'));
    state.empty = false;

    // Server unreachable
    state.offline = true;
    await open(page, '/');
    await page.waitForSelector('text=The overview didn’t load', { timeout: 15000 });
    await shot(page, name('error'));
    state.offline = false;

    // Older server without the schema endpoint: types are derived and still render.
    state.noSchema = true;
    await open(page, '/');
    await page.waitForSelector('text=What’s in your data');
    await shot(page, name('overview-derived'));
    state.noSchema = false;
  });

  await run(scheme, mobile, 'mobile', async (page, name) => {
    state.empty = false;
    state.offline = false;
    state.noSchema = false;
    await open(page, '/');
    await page.waitForSelector('text=What’s in your data');
    await shot(page, name('overview'));
    await shot(page, name('overview-full'), { fullPage: true });

    await open(page, '/explore');
    await settleGraph(page);
    await shot(page, name('explore'));

    await open(page, `/explore?focus=${encodeURIComponent(`Customer:${SAMPLE_IDS.customer}`)}`);
    await settleGraph(page);
    await page.waitForSelector('text=Relationships');
    await page.waitForTimeout(400);
    await shot(page, name('explore-inspector'));

    await open(page, '/ask');
    await page.waitForSelector('text=What would you like to know?');
    await shot(page, name('ask'));

    await open(page, '/records/Customer');
    await page.waitForSelector('role=table');
    await shot(page, name('records'));
  });
}

await browser.close();
preview.kill();

console.log(`\n${shots.length} screenshots written to ${outDir}`);
if (problems.length > 0) {
  console.log('\nBrowser problems:');
  for (const problem of problems) console.log(' -', problem);
  process.exitCode = 1;
}
