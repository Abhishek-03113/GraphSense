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
import { DATASET_ID, NOT_READY, SAMPLE_IDS, SCHEMA, SUGGESTED_QUESTIONS, SUMMARY, chatError, chatReply, datasetStatus, entities, flowGraph, fullGraph, subgraph } from './fixtures.mjs';

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
// dataset: ready | empty | loading | failed. ai: full | degraded | disabled | missing.
// chatError: a backend error code (or 'rate_limited') the next /chat calls answer with instead of a reply.
const defaults = { dataset: 'ready', ai: 'full', offline: false, noSchema: false, noStatus: false, chatError: null };
const state = { ...defaults };
const resetState = () => Object.assign(state, defaults);

async function installApi(context) {
  // The chat socket: same frames as the server's /api/chat/ws, with a short streamed answer.
  await context.routeWebSocket('**/api/chat/ws', (ws) => {
    if (state.offline) return ws.close({ code: 1011 });
    ws.onMessage(async (raw) => {
      const frame = JSON.parse(String(raw));
      if (frame.type === 'ping') return ws.send(JSON.stringify({ type: 'pong' }));
      if (frame.type !== 'ask') return;
      const send = (body) => ws.send(JSON.stringify({ id: frame.id, ...body }));
      const pause = (ms) => new Promise((r) => setTimeout(r, ms));
      if (state.chatError === 'rate_limited') {
        const reply = chatError('rate_limited', { answer: "You're asking questions faster than they can be answered. Please wait a moment and try again.", suggestions: [] });
        return send({ type: 'result', result: reply, retry_after: 30 });
      }
      if (state.chatError) return send({ type: 'result', result: chatError(state.chatError, { answer: '' }) });
      for (const stage of ['retrieving', 'writing_query', 'running_query', 'answering']) {
        send({ type: 'status', stage });
        await pause(110);
      }
      const reply = chatReply(frame.message ?? '');
      for (const word of String(reply.answer ?? '').split(/(?<= )/)) send({ type: 'delta', text: word });
      send({ type: 'result', result: reply });
    });
  });
  await context.route('**/api/**', async (route) => {
    if (state.offline) return route.abort('connectionrefused');
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^.*\/api/, '');
    const q = url.searchParams;
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

    if (path === '/health') return json({ status: 'ok' });
    const notReady = state.dataset !== 'ready';
    if (path === '/graph/summary') return notReady ? json(NOT_READY, 409) : json(SUMMARY);
    if (path === '/graph/schema') return state.noSchema ? json({ detail: 'Not Found' }, 404) : json(SCHEMA);
    if (path === '/graph/flows') return json({ flows: SCHEMA.flows });
    if (path.startsWith('/graph/') && notReady) return json(NOT_READY, 409);
    if (path === '/graph/samples') return json(fullGraph(Number(q.get('node_limit') ?? 12)));
    if (path === '/graph/subgraphs') return json(subgraph(q.get('root_type'), q.get('root_id'), Number(q.get('depth') ?? 1)));
    if (path === '/graph/traces') return json(subgraph(q.get('doc_type'), q.get('doc_id'), Number(q.get('depth') ?? 4)));
    const flowMatch = path.match(/^\/graph\/flows\/([^/]+)\/subgraph$/);
    if (flowMatch) {
      const graph = flowGraph(decodeURIComponent(flowMatch[1]));
      return graph ? json(graph) : json({ detail: 'Unknown flow' }, 404);
    }
    const entityMatch = path.match(/^\/graph\/node-types\/([^/]+)\/entities$/);
    if (entityMatch) return json(entities(decodeURIComponent(entityMatch[1]), Number(q.get('limit') ?? 50)));
    if (path === `/datasets/${DATASET_ID}/status`) return state.noStatus ? json({ detail: 'Not Found', code: 'not_found' }, 404) : json(datasetStatus(state.dataset, state.ai));
    if (path === `/datasets/${DATASET_ID}/suggested-questions`) return state.noStatus ? json({ detail: 'Not Found', code: 'not_found' }, 404) : json(SUGGESTED_QUESTIONS);
    if (path === '/chat/messages') {
      const body = JSON.parse(request.postData() ?? '{}');
      await new Promise((r) => setTimeout(r, 450));
      if (state.chatError === 'rate_limited') {
        const reply = chatError('rate_limited', { answer: "You're asking questions faster than they can be answered. Please wait a moment and try again.", suggestions: [] });
        return route.fulfill({
          status: 429,
          contentType: 'application/json',
          headers: { 'Retry-After': '30' },
          body: JSON.stringify({ ...reply, detail: reply.answer, code: 'rate_limited', request_id: 'req-1' }),
        });
      }
      if (state.chatError) return json(chatError(state.chatError, { answer: '' }));
      return json(chatReply(body.message ?? ''));
    }
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
    resetState();

    await open(page, '/');
    await page.waitForSelector('text=What’s in your data');
    await page.waitForSelector('text=Ask is ready');
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
    await page.waitForSelector('text=Completely delivered');
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

    // Data that is not loaded: nothing to click that would start a load.
    state.dataset = 'empty';
    await open(page, '/');
    await page.waitForSelector('text=Your data hasn’t been loaded yet');
    if ((await page.getByRole('button', { name: /load data/i }).count()) > 0) problems.push('a customer-facing load button is back');
    await shot(page, name('empty'));
    await open(page, '/explore');
    await page.waitForSelector('text=Your data hasn’t been loaded yet');
    await open(page, '/flows/full_o2c');
    await page.waitForSelector('text=Your data hasn’t been loaded yet');

    state.dataset = 'loading';
    await open(page, '/');
    await page.waitForSelector('text=Your data is being loaded');
    await shot(page, name('loading'));

    state.dataset = 'failed';
    await open(page, '/records');
    await page.waitForSelector('text=The last data load didn’t finish');
    await shot(page, name('load-failed'));

    // A server that cannot say how the load is going still gets the plain state.
    state.dataset = 'empty';
    state.noStatus = true;
    await open(page, '/trace');
    await page.waitForSelector('text=Your data hasn’t been loaded yet');
    state.noStatus = false;

    // The data arrives while the page is open: it fills in without a reload.
    state.dataset = 'loading';
    await open(page, '/');
    await page.waitForSelector('text=Your data is being loaded');
    state.dataset = 'ready';
    await page.waitForSelector('text=What’s in your data', { timeout: 15000 });
    await shot(page, name('loaded-by-itself'));
    state.dataset = 'ready';

    // Ask: how it reads when the AI layer is off, limited or still being prepared.
    state.ai = 'disabled';
    await open(page, '/ask');
    await page.waitForSelector('text=Ask isn’t switched on for this workspace');
    await shot(page, name('ask-disabled'));
    state.chatError = 'not_configured';
    await page.locator('#ask-input').fill('Which customer has the most sales orders?');
    await page.locator('#ask-input').press('Enter');
    await page.waitForSelector('text=Ask isn’t set up on this server yet');
    await page.waitForTimeout(300);
    await shot(page, name('ask-not-configured'));
    state.chatError = null;
    state.ai = 'degraded';
    await open(page, '/ask');
    await page.waitForSelector('text=Ask is running in a simpler mode');
    await shot(page, name('ask-degraded'));
    state.ai = 'full';

    // Ask: values with a code show their meaning, and long results say they were cut off.
    await open(page, '/ask');
    await page.locator('#ask-input').fill('Which sales orders are delivered, with their status?');
    await page.locator('#ask-input').press('Enter');
    await page.waitForSelector('text=Showing the first');
    await page.waitForTimeout(300);
    await shot(page, name('ask-labels-truncated'));

    // Ask: every other way an answer can fail has calm wording and a way forward.
    for (const [code, expected] of [
      ['sql_rejected', 'I can’t run that kind of lookup here'],
      ['provider_unavailable', 'The answering service isn’t responding'],
      ['dataset_not_ready', 'This data isn’t loaded yet'],
      ['rate_limited', 'You’re asking a little faster than I can answer'],
      ['sql_execution_error: timeout', 'The lookup didn’t run'],
    ]) {
      state.chatError = code;
      await open(page, '/ask');
      await page.locator('#ask-input').fill('Show me everything');
      await page.locator('#ask-input').press('Enter');
      await page.waitForSelector(`text=${expected}`);
      await page.waitForTimeout(250);
      await shot(page, name(`ask-error-${code.split(':')[0].replaceAll('_', '-')}`));
    }
    state.chatError = null;

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
    state.noStatus = false;
  });

  await run(scheme, mobile, 'mobile', async (page, name) => {
    resetState();
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
