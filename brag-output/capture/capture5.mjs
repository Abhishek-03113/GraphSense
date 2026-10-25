import { spawn } from 'node:child_process';
import { mkdirSync, readdirSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from '/home/user/GraphSense/frontend/node_modules/playwright/index.mjs';
import { DATASET_ID, NOT_READY, SAMPLE_IDS, SCHEMA, SUGGESTED_QUESTIONS, SUMMARY, chatError, chatReply, datasetStatus, entities, flowGraph, fullGraph, subgraph } from '/home/user/GraphSense/frontend/e2e/fixtures.mjs';

const OUT = '/home/user/GraphSense/brag-output/footage5';
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
const CURSOR = `(() => { const c = document.createElement('div'); c.style.cssText='position:fixed;z-index:2147483647;width:18px;height:18px;border-radius:50%;border:2px solid rgba(38,38,38,.85);background:rgba(38,38,38,.08);box-shadow:0 1px 4px rgba(0,0,0,.2);pointer-events:none;left:-40px;top:-40px;transform:translate(-50%,-50%);transition:transform .18s'; document.addEventListener('DOMContentLoaded',()=>document.body.appendChild(c)); document.addEventListener('mousemove',e=>{c.style.left=e.clientX+'px';c.style.top=e.clientY+'px'},true); document.addEventListener('mousedown',()=>c.style.transform='translate(-50%,-50%) scale(.75)',true); document.addEventListener('mouseup',()=>c.style.transform='translate(-50%,-50%) scale(1)',true); })();`;

const marks = {};
async function clip(name, fn) {
  const context = await browser.newContext({ viewport: { width: W, height: H }, colorScheme: 'light', recordVideo: { dir: resolve(OUT, '_' + name), size: { width: W, height: H } } });
  await installApi(context);
  await context.addInitScript(CURSOR);
  const page = await context.newPage();
  const t0 = Date.now(); page.mark = () => { marks[name] = (Date.now() - t0) / 1000; };
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


const cyNode = (page, type) => page.evaluate((type) => {
  const el = document.querySelector('[data-testid="graph-canvas"]');
  const holder = [el, ...el.querySelectorAll('*')].find((e) => e._cyreg);
  const cy = holder._cyreg.cy; const r = holder.getBoundingClientRect();
  const n = cy.nodes().filter((x) => x.data('type') === type || String(x.id()).startsWith(type + ':')).sort((a, b) => b.degree() - a.degree())[0];
  const p = n.renderedPosition(); return { x: r.left + p.x, y: r.top + p.y };
}, type);
const W8 = (page, ms) => page.waitForTimeout(ms);

await clip('overview', async (page) => {
  await page.waitForSelector('text=Ask is ready'); await W8(page, 600); page.mark();
  await glide(page, 520, 300, 30); await W8(page, 900);
  await glide(page, 900, 300, 50); await W8(page, 900);
  await glide(page, 1300, 300, 50); await W8(page, 900);
  await glide(page, 1000, 560, 50); await W8(page, 1500);
});
await clip('explore', async (page) => {
  await page.goto(BASE + '/explore'); await settle(page); await W8(page, 1200); page.mark();
  await glide(page, 1100, 450, 60); await W8(page, 2500); await glide(page, 1200, 520, 60); await W8(page, 3000);
});
await clip('details', async (page) => {
  await page.goto(BASE + '/explore'); await settle(page); await W8(page, 3500);
  const c = await cyNode(page, 'Customer'); page.mark();
  await W8(page, 400); await glide(page, c.x, c.y, 45); await W8(page, 400);
  await page.mouse.down(); await page.mouse.up();
  await page.waitForSelector('text=Relationships'); await W8(page, 6000);
});
await clip('layouts', async (page) => {
  await page.goto(BASE + '/explore'); await settle(page); await W8(page, 2500);
  const sel = page.getByRole('combobox', { name: 'Layout' }); page.mark();
  await W8(page, 600);
  for (const v of ['organic', 'circle', 'leftToRight']) { await sel.selectOption(v); await W8(page, 2300); }
});
await clip('ask', async (page) => {
  await page.goto(BASE + '/ask'); await page.waitForSelector('text=What would you like to know?'); await W8(page, 800); page.mark();
  await glide(page, 800, 830, 40); await W8(page, 300);
  await types(page, '#ask-input', 'Which customer has the most sales orders?', 50);
  await W8(page, 500); await page.locator('#ask-input').press('Enter');
  await page.waitForSelector('text=has the most sales orders'); await W8(page, 5000);
});
await clip('trust', async (page) => {
  await page.goto(BASE + '/ask'); await page.waitForSelector('text=What would you like to know?'); await W8(page, 800); page.mark();
  await types(page, '#ask-input', 'Write me a poem about invoices', 50);
  await W8(page, 400); await page.locator('#ask-input').press('Enter');
  await page.waitForSelector('text=outside what I can help with'); await W8(page, 4500);
});
await clip('map', async (page) => {
  await page.goto(BASE + '/ask'); await page.waitForSelector('text=What would you like to know?'); await W8(page, 800); page.mark();
  await types(page, '#ask-input', 'Which sales orders are delivered?', 45);
  await W8(page, 300); await page.locator('#ask-input').press('Enter');
  await page.waitForSelector('text=Showing the first'); await W8(page, 1200);
  const b = page.getByRole('button', { name: /Show all in Explore/ }).first();
  const box = await b.boundingBox(); await glide(page, box.x + box.width / 2, box.y + box.height / 2, 40); await W8(page, 400);
  await b.click(); await W8(page, 5000);
});
await clip('flows', async (page) => {
  await page.goto(BASE + '/flows/full_o2c'); await settle(page); await W8(page, 1500); page.mark();
  await glide(page, 900, 450, 60); await W8(page, 5500);
});
await clip('trace', async (page) => {
  await page.goto(BASE + `/trace?type=Customer&id=${SAMPLE_IDS.customer}`); await settle(page); await page.waitForSelector('text=Starting point'); await W8(page, 800); page.mark();
  await glide(page, 1000, 500, 60); await W8(page, 5500);
});
console.log('MARKS', JSON.stringify(marks));
await browser.close(); preview.kill(); process.exit(0);
