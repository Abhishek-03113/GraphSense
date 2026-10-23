import { humanize, lowerFirst, pluralize } from '../format';
import type { FlowPayload, SchemaPayload, Summary } from '../api/schemas';
import {
  PALETTE_SLOTS,
  type Counts,
  type EdgeMeta,
  type FlowMeta,
  type PaletteSlot,
  type ResolvedSchema,
  type TypeCategory,
  type TypeMeta,
} from './types';

/** Slots handed out automatically. Gray is kept for types the server calls out explicitly. */
const AUTO_SLOTS: PaletteSlot[] = [
  'blue',
  'orange',
  'green',
  'purple',
  'teal',
  'pink',
  'indigo',
  'yellow',
  'cyan',
  'mint',
  'red',
  'brown',
];

const CATEGORIES: TypeCategory[] = ['party', 'document', 'item', 'master', 'finance', 'other'];

/** Shown when the server gives the dataset no name of its own. */
export const DEFAULT_DATASET_NAME = 'Your dataset';

/** Stable string hash (FNV-1a). */
export function hashString(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function hashSlot(key: string): PaletteSlot {
  return AUTO_SLOTS[hashString(key) % AUTO_SLOTS.length];
}

export function isPaletteSlot(value: string | null | undefined): value is PaletteSlot {
  return Boolean(value) && (PALETTE_SLOTS as readonly string[]).includes(value as string);
}

/** Metadata for a type the server did not describe. */
export function fallbackTypeMeta(key: string): TypeMeta {
  const label = humanize(key) || key;
  return {
    key,
    label,
    plural: pluralize(2, label),
    description: '',
    category: 'other',
    accent: hashSlot(key),
    icon: null,
    isPrimary: false,
    displayProperties: [],
    valueLabels: {},
    described: false,
  };
}

export function emptySchema(): ResolvedSchema {
  return {
    domain: { id: 'dataset', name: DEFAULT_DATASET_NAME, description: '', version: '', isDefault: true },
    nodeTypes: [],
    edgeTypes: [],
    flows: [],
    source: 'derived',
  };
}

function toFlow(flow: FlowPayload): FlowMeta {
  return {
    id: flow.id,
    label: flow.label,
    description: flow.description ?? '',
    nodeTypes: flow.node_types,
    edgeTypes: flow.edge_types,
  };
}

/** Give every type a distinct palette slot where possible, deterministically. */
function assignAccents(types: TypeMeta[], explicit: Map<string, PaletteSlot>): void {
  const used = new Set<PaletteSlot>(explicit.values());
  const pending = types.filter((type) => !explicit.has(type.key)).sort((a, b) => a.key.localeCompare(b.key));
  for (const type of pending) {
    const start = AUTO_SLOTS.indexOf(hashSlot(type.key));
    let chosen: PaletteSlot = AUTO_SLOTS[start];
    for (let offset = 0; offset < AUTO_SLOTS.length; offset += 1) {
      const candidate = AUTO_SLOTS[(start + offset) % AUTO_SLOTS.length];
      if (!used.has(candidate)) {
        chosen = candidate;
        break;
      }
    }
    used.add(chosen);
    type.accent = chosen;
  }
}

interface ResolveInput {
  payload: SchemaPayload | undefined;
  summary: Summary | undefined;
  flows: FlowPayload[] | undefined;
}

/**
 * Merge whatever the server told us into one schema the UI can rely on.
 * With a full payload the server wins. Without one (older server, request
 * failed) types, relationships and flows are derived from other endpoints.
 */
export function resolveSchema({ payload, summary, flows }: ResolveInput): ResolvedSchema {
  const fromApi = Boolean(payload && payload.node_types.length > 0);
  const flowList: FlowMeta[] = (payload?.flows.length ? payload.flows : (flows ?? [])).map(toFlow);

  const described = new Map<string, TypeMeta>();
  const explicit = new Map<string, PaletteSlot>();

  for (const raw of payload?.node_types ?? []) {
    const base = fallbackTypeMeta(raw.key);
    const label = raw.label?.trim() || base.label;
    const accent = isPaletteSlot(raw.accent) ? raw.accent : null;
    if (accent) explicit.set(raw.key, accent);
    described.set(raw.key, {
      key: raw.key,
      label,
      plural: raw.plural?.trim() || pluralize(2, label),
      description: raw.description?.trim() ?? '',
      category: CATEGORIES.includes(raw.category as TypeCategory) ? (raw.category as TypeCategory) : 'other',
      accent: accent ?? base.accent,
      icon: raw.icon ?? null,
      isPrimary: Boolean(raw.is_primary),
      displayProperties: raw.display_properties ?? [],
      valueLabels: raw.value_labels ?? {},
      described: true,
    });
  }

  // Types the server did not list but that exist in the data or in a flow.
  const ordered: string[] = [...described.keys()];
  const seen = new Set(ordered);
  const extraKeys: string[] = [];
  const widestFlow = [...flowList].sort((a, b) => b.nodeTypes.length - a.nodeTypes.length)[0];
  for (const key of widestFlow?.nodeTypes ?? []) extraKeys.push(key);
  for (const flow of flowList) extraKeys.push(...flow.nodeTypes);
  const byCount = Object.entries(summary?.nodes ?? {})
    .sort((a, b) => b[1] - a[1])
    .map(([key]) => key);
  extraKeys.push(...byCount);
  for (const key of extraKeys) {
    if (!seen.has(key)) {
      seen.add(key);
      ordered.push(key);
      described.set(key, fallbackTypeMeta(key));
    }
  }

  const nodeTypes = ordered.map((key) => described.get(key) as TypeMeta);
  assignAccents(nodeTypes, explicit);

  // Primary types first when the server said which they are, otherwise keep derived order.
  const primaryFirst = fromApi
    ? [...nodeTypes.filter((type) => type.isPrimary), ...nodeTypes.filter((type) => !type.isPrimary)]
    : nodeTypes;

  const edgeTypes: EdgeMeta[] = (payload?.edge_types ?? []).map((edge) => ({
    key: edge.key,
    label: edge.label?.trim() ? lowerFirst(edge.label.trim()) : lowerFirst(humanize(edge.key)),
    source: edge.source ?? null,
    target: edge.target ?? null,
    description: edge.description?.trim() ?? '',
  }));
  const knownEdgeKeys = new Set(edgeTypes.map((edge) => edge.key));
  const derivedEdgeKeys = [...Object.keys(summary?.edges ?? {}), ...flowList.flatMap((flow) => flow.edgeTypes)];
  for (const key of derivedEdgeKeys) {
    if (!knownEdgeKeys.has(key)) {
      knownEdgeKeys.add(key);
      edgeTypes.push({ key, label: lowerFirst(humanize(key)), source: null, target: null, description: '' });
    }
  }

  const domainName = payload?.domain?.name?.trim();
  return {
    domain: {
      id: payload?.domain?.id?.trim() || 'dataset',
      name: domainName || DEFAULT_DATASET_NAME,
      description: payload?.domain?.description?.trim() ?? '',
      version: payload?.domain?.version?.trim() ?? '',
      isDefault: Boolean(payload?.domain?.is_default) || !domainName,
    },
    nodeTypes: primaryFirst,
    edgeTypes,
    flows: flowList,
    source: fromApi ? 'api' : 'derived',
  };
}

export function toCounts(summary: Summary | undefined): Counts {
  return { nodes: summary?.nodes ?? {}, edges: summary?.edges ?? {} };
}
