// Fails when the fixtures no longer match what a running backend serves, so screenshots built on
// them keep representing the real product:
//
//   - SCHEMA must equal GET /graph/schema (value for value)
//   - the dataset status, suggested questions and chat fixtures must have the same fields
//     (keys, not values) as GET /datasets/{id}/status, GET /datasets/{id}/suggested-questions
//     and POST /chat
//
//   node e2e/check-schema.mjs [http://localhost:8000/api]
//
// Regenerate the fixture's TYPES / EDGES / FLOWS from `curl <api>/graph/schema` when it reports drift.

import { SCHEMA, SUGGESTED_QUESTIONS, chatReply, datasetStatus } from './fixtures.mjs';

const api = (process.argv[2] ?? process.env.GS_API ?? 'http://localhost:8000/api').replace(/\/$/, '');

let live;
try {
  const response = await fetch(`${api}/graph/schema`);
  if (!response.ok) throw new Error(`responded ${response.status}`);
  live = await response.json();
} catch (error) {
  console.error(`Could not read ${api}/graph/schema: ${error.message}`);
  process.exit(2);
}

const problems = [];
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const compare = (label, fixture, actual) => {
  const keys = [...new Set([...Object.keys(fixture ?? {}), ...Object.keys(actual ?? {})])];
  for (const key of keys) {
    if (!same(fixture?.[key], actual?.[key])) {
      problems.push(`${label}.${key}: fixture ${JSON.stringify(fixture?.[key])} but backend ${JSON.stringify(actual?.[key])}`);
    }
  }
};

compare('domain', SCHEMA.domain, live.domain);

const keyed = (list) => new Map(list.map((item) => [item.key, item]));
const fixtureNodes = keyed(SCHEMA.node_types);
const liveNodes = keyed(live.node_types);
for (const key of new Set([...fixtureNodes.keys(), ...liveNodes.keys()])) {
  if (!fixtureNodes.has(key)) problems.push(`node type ${key}: missing from the fixture`);
  else if (!liveNodes.has(key)) problems.push(`node type ${key}: not served by the backend`);
  else compare(`node_types[${key}]`, fixtureNodes.get(key), liveNodes.get(key));
}
if (!same(SCHEMA.node_types.map((t) => t.key), live.node_types.map((t) => t.key))) problems.push('node type order differs');

const edgeId = (edge) => `${edge.key}:${edge.source}>${edge.target}`;
const fixtureEdges = new Map(SCHEMA.edge_types.map((e) => [edgeId(e), e]));
const liveEdges = new Map(live.edge_types.map((e) => [edgeId(e), e]));
for (const id of new Set([...fixtureEdges.keys(), ...liveEdges.keys()])) {
  if (!fixtureEdges.has(id)) problems.push(`edge type ${id}: missing from the fixture`);
  else if (!liveEdges.has(id)) problems.push(`edge type ${id}: not served by the backend`);
  else compare(`edge_types[${id}]`, fixtureEdges.get(id), liveEdges.get(id));
}

const fixtureFlows = new Map(SCHEMA.flows.map((f) => [f.id, f]));
const liveFlows = new Map(live.flows.map((f) => [f.id, f]));
for (const id of new Set([...fixtureFlows.keys(), ...liveFlows.keys()])) {
  if (!fixtureFlows.has(id)) problems.push(`flow ${id}: missing from the fixture`);
  else if (!liveFlows.has(id)) problems.push(`flow ${id}: not served by the backend`);
  else compare(`flows[${id}]`, fixtureFlows.get(id), liveFlows.get(id));
}

// ── Response shapes ───────────────────────────────────────
// Compares the nested key sets of objects. Arrays are compared by their first element when both
// sides have one, and values never are.
const shapeOf = (value) => {
  if (Array.isArray(value)) return value.length > 0 ? [shapeOf(value[0])] : [];
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map((key) => [key, shapeOf(value[key])]));
  return null;
};
const compareShape = (label, fixture, actual, path = '') => {
  const fixtureIsObject = fixture && typeof fixture === 'object' && !Array.isArray(fixture);
  const actualIsObject = actual && typeof actual === 'object' && !Array.isArray(actual);
  if (fixtureIsObject && actualIsObject) {
    for (const key of new Set([...Object.keys(fixture), ...Object.keys(actual)])) {
      if (!(key in fixture)) problems.push(`${label}${path}.${key}: served by the backend but missing from the fixture`);
      else if (!(key in actual)) problems.push(`${label}${path}.${key}: in the fixture but not served by the backend`);
      else compareShape(label, fixture[key], actual[key], `${path}.${key}`);
    }
  } else if (Array.isArray(fixture) && Array.isArray(actual) && fixture.length > 0 && actual.length > 0) {
    compareShape(label, fixture[0], actual[0], `${path}[]`);
  }
};

const tryJson = async (path, init) => {
  try {
    const response = await fetch(`${api}${path}`, init);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
};

const datasetId = live.domain?.id;
const status = datasetId ? await tryJson(`/datasets/${encodeURIComponent(datasetId)}/status`) : null;
if (status) {
  // A dataset that has not run yet has no last run; compare the run fields only when there is one.
  const fixture = datasetStatus(status.status === 'empty' ? 'empty' : 'ready', 'full');
  const comparable = status.last_run ? fixture : { ...fixture, last_run: null };
  const served = status.last_run ? status : { ...status, last_run: null };
  if (served.record_counts == null) delete comparable.record_counts;
  if (comparable.record_counts == null && served.record_counts) delete served.record_counts;
  compareShape('status', { ...comparable, record_counts: undefined, last_run: comparable.last_run ? { ...comparable.last_run, summary: {} } : null },
    { ...served, record_counts: undefined, last_run: served.last_run ? { ...served.last_run, summary: {} } : null });
  compareShape('status.ai', datasetStatus('ready', 'full').ai, status.ai);
} else {
  console.warn(`Skipped the status check: ${api}/datasets/${datasetId}/status is not served.`);
}

const suggestions = datasetId ? await tryJson(`/datasets/${encodeURIComponent(datasetId)}/suggested-questions`) : null;
if (suggestions) compareShape('suggested-questions', SUGGESTED_QUESTIONS, suggestions);
else console.warn('Skipped the suggested questions check: the endpoint is not served.');

// Any answer has the same fields. A refusal is enough to see them (no model key is needed).
const chat = await tryJson('/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: 'How many records are there?' }) });
if (chat) compareShape('chat', chatReply('Which customer has the most orders?'), chat);
else console.warn('Skipped the chat check: POST /chat did not answer.');

if (problems.length > 0) {
  console.error(`The schema fixture has drifted from ${api}/graph/schema:`);
  for (const problem of problems) console.error(' -', problem);
  process.exit(1);
}
console.log(`Schema fixture matches ${api}/graph/schema (${live.node_types.length} node types, ${live.edge_types.length} edge types, ${live.flows.length} flows).`);
