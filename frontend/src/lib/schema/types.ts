export const PALETTE_SLOTS = [
  'red',
  'orange',
  'yellow',
  'green',
  'mint',
  'teal',
  'cyan',
  'blue',
  'indigo',
  'purple',
  'pink',
  'brown',
  'gray',
] as const;

export type PaletteSlot = (typeof PALETTE_SLOTS)[number];

export type TypeCategory = 'party' | 'document' | 'item' | 'master' | 'finance' | 'other';

export interface TypeMeta {
  key: string;
  /** Singular, sentence case. */
  label: string;
  plural: string;
  description: string;
  category: TypeCategory;
  accent: PaletteSlot;
  /** Optional lucide icon name from the server. */
  icon: string | null;
  isPrimary: boolean;
  displayProperties: string[];
  /** False when the server did not describe this type and the UI derived everything. */
  described: boolean;
}

export interface EdgeMeta {
  key: string;
  /** Verb phrase, lower case: "placed". */
  label: string;
  source: string | null;
  target: string | null;
  description: string;
}

export interface FlowMeta {
  id: string;
  label: string;
  description: string;
  nodeTypes: string[];
  edgeTypes: string[];
}

export interface DomainMeta {
  id: string;
  name: string;
  description: string;
}

export interface ResolvedSchema {
  domain: DomainMeta;
  nodeTypes: TypeMeta[];
  edgeTypes: EdgeMeta[];
  flows: FlowMeta[];
  /** "api" when /graph/schema answered, "derived" when the UI inferred it from other endpoints. */
  source: 'api' | 'derived';
}

export interface Counts {
  nodes: Record<string, number>;
  edges: Record<string, number>;
}
