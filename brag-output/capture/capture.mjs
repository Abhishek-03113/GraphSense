import { spawn } from 'node:child_process';
import { mkdirSync, readdirSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from '/home/user/GraphSense/frontend/node_modules/playwright/index.mjs';
import { DATASET_ID, NOT_READY, SAMPLE_IDS, SCHEMA, SUGGESTED_QUESTIONS, SUMMARY, chatError, chatReply, datasetStatus, entities, flowGraph, fullGraph, subgraph } from '/home/user/GraphSense/frontend/e2e/fixtures.mjs';

const OUT = '/home/user/GraphSense/brag-output/footage';
const DIST = '/home/user/GraphSense/brag-output/.dist';
const PORT = 4181;
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(OUT, { recursive: true });
const preview = spawn('npx', ['vite', 'preview', '--outDir', DIST, '--port', String(PORT), '--strictPort', '--host', '127.0.0.1'], { cwd: '/home/user/GraphSense/frontend', stdio: 'ignore' });
process.on('exit', () => preview.kill());
for (let i = 0; i < 60; i++) { try { if ((await fetch(BASE)).ok) break; } catch {} await new Promise((r) => setTimeout(r, 250)); }
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


const browser = await chromium.launch({ args: ['--no-sandbox'] }).catch(() => chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] }));
const W = 1600, H = 900;

// Visible cursor so the footage shows real interaction.
const CURSOR = `(() => { const c = document.createElement('div'); c.id='__cur'; c.style.cssText='position:fixed;z-index:2147483647;width:22px;height:22px;border-radius:50%;background:rgba(255,80,60,.85);box-shadow:0 0 0 4px rgba(255,80,60,.3);pointer-events:none;left:-40px;top:-40px;transform:translate(-50%,-50%);transition:transform .12s'; document.addEventListener('DOMContentLoaded',()=>document.body.appendChild(c)); document.addEventListener('mousemove',e=>{c.style.left=e.clientX+'px';c.style.top=e.clientY+'px'},true); document.addEventListener('mousedown',()=>c.style.transform='translate(-50%,-50%) scale(.6)',true); document.addEventListener('mouseup',()=>c.style.transform='translate(-50%,-50%) scale(1)',true); })();`;

async function clip(name, fn) {
  const context = await browser.newContext({ viewport: { width: W, height: H }, colorScheme: 'dark', recordVideo: { dir: resolve(OUT, '_' + name), size: { width: W, height: H } } });
  await installApi(context);
  await context.addInitScript(CURSOR);
  const page = await context.newPage();
  await page.goto(BASE + '/');
  await page.waitForSelector('text=What’s in your data');
  await fn(page);
  await page.close();
  await context.close();
  const dir = resolve(OUT, '_' + name);
  const f = readdirSync(dir).find((x) => x.endsWith('.webm'));
  renameSync(resolve(dir, f), resolve(OUT, name + '.webm'));
  console.log('clip', name);
}
const settle = async (page) => {
  await page.waitForFunction(() => { const c = document.querySelector('[data-testid="graph-canvas"]'); return c && Number(c.getAttribute('data-records')) > 0; });
};
const glide = async (page, x, y, steps = 25) => { await page.mouse.move(x, y, { steps }); };
const types = async (page, sel, text, delay = 55) => { await page.locator(sel).click(); await page.locator(sel).pressSequentially(text, { delay }); };

await clip('overview', async (page) => {
  await page.waitForSelector('text=Ask is ready');
  await glide(page, 700, 400); await page.waitForTimeout(1200);
  await glide(page, 1100, 520); await page.waitForTimeout(1500);
  await page.mouse.wheel(0, 500); await page.waitForTimeout(1500);
});

await clip('explore', async (page) => {
  await page.goto(BASE + '/explore'); await settle(page); await page.waitForTimeout(2500);
  await glide(page, 800, 450, 40); await page.waitForTimeout(800);
  await page.mouse.wheel(0, -300); await page.waitForTimeout(1200);
  await page.goto(BASE + `/explore?focus=${encodeURIComponent('Customer:' + SAMPLE_IDS.customer)}`);
  await settle(page); await page.waitForSelector('text=Relationships'); await page.waitForTimeout(3500);
});

await clip('ask', async (page) => {
  await page.goto(BASE + '/ask'); await page.waitForSelector('text=What would you like to know?'); await page.waitForTimeout(1200);
  await types(page, '#ask-input', 'Which customer has the most sales orders?', 60);
  await page.waitForTimeout(500); await page.locator('#ask-input').press('Enter');
  await page.waitForSelector('text=has the most sales orders'); await page.waitForTimeout(1500);
  await page.getByRole('button', { name: 'View query' }).click(); await page.waitForTimeout(3000);
});

await clip('flows', async (page) => {
  await page.goto(BASE + '/flows'); await page.waitForSelector('text=Sales flow'); await page.waitForTimeout(1500);
  await page.goto(BASE + '/flows/full_o2c'); await settle(page); await page.waitForTimeout(4500);
});

await clip('trace', async (page) => {
  await page.goto(BASE + `/trace?type=Customer&id=${SAMPLE_IDS.customer}`); await settle(page); await page.waitForSelector('text=Starting point'); await page.waitForTimeout(4500);
});

await clip('palette', async (page) => {
  await page.keyboard.press('Control+k'); await page.waitForTimeout(500);
  await page.getByRole('combobox', { name: 'Search' }).pressSequentially('sales', { delay: 120 });
  await page.waitForTimeout(2500);
});

await browser.close();
preview.kill();
process.exit(0);
