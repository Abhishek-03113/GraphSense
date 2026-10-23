// Fails when the SCHEMA fixture no longer matches what a running backend serves at /graph/schema,
// so screenshots built on the fixtures keep representing the real product.
//
//   node e2e/check-schema.mjs [http://localhost:8000/api]
//
// Regenerate the fixture's TYPES / EDGES / FLOWS from `curl <api>/graph/schema` when it reports drift.

import { SCHEMA } from './fixtures.mjs';

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

if (problems.length > 0) {
  console.error(`The schema fixture has drifted from ${api}/graph/schema:`);
  for (const problem of problems) console.error(' -', problem);
  process.exit(1);
}
console.log(`Schema fixture matches ${api}/graph/schema (${live.node_types.length} node types, ${live.edge_types.length} edge types, ${live.flows.length} flows).`);
