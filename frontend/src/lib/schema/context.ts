import { createContext } from 'react';
import type { DatasetStatus } from '../api/schemas';
import type { Counts, PaletteSlot, ResolvedSchema, TypeMeta } from './types';

/** What the Ask layer can do for the dataset right now, simplified for display. */
export interface AiState {
  /** "unknown" until the status endpoint has answered (or when the server does not have one). */
  mode: 'full' | 'degraded' | 'disabled' | 'unknown';
  knowledge: 'ready' | 'stale' | 'missing' | 'unknown';
}

/** Where the dataset is in its life: nothing loaded, loading, ready or failed. "unknown" when the server does not say. */
export type DatasetPhase = 'empty' | 'loading' | 'ready' | 'failed' | 'unknown';

export interface SchemaContextValue {
  schema: ResolvedSchema;
  /** "loading" until both the schema and the counts have settled. */
  status: 'loading' | 'ready' | 'error';
  error: Error | null;
  counts: Counts;
  totalRecords: number;
  totalRelationships: number;
  /** True once the dataset is known to hold no usable records: it has none, or its data is not loaded yet. */
  isEmpty: boolean;
  /** True when the server answered `dataset_not_ready` (409): the dataset's tables do not exist yet. */
  notReady: boolean;
  /** Id of the dataset this app shows, from the schema endpoint. Undefined on servers without one. */
  datasetId: string | undefined;
  /** Load status and AI state from `/datasets/{id}/status`. Undefined while loading or on older servers. */
  dataset: DatasetStatus | undefined;
  datasetPhase: DatasetPhase;
  ai: AiState;
  /** Check the dataset status again now. */
  recheckDataset: () => void;
  isRecheckingDataset: boolean;
  /** True when the schema endpoint was unavailable and types were derived. */
  isDerived: boolean;
  /** Primary types, or the largest types when the server marks none as primary. */
  headlineTypes: TypeMeta[];
  otherTypes: TypeMeta[];
  getTypeMeta: (key: string) => TypeMeta;
  /** CSS colour reference for a type, e.g. `var(--gs-hue-blue)`. */
  colorForType: (key: string) => string;
  slotForType: (key: string) => PaletteSlot;
  /** "Sales order" / "Sales orders". */
  typeLabel: (key: string, count?: number) => string;
  /** Verb phrase for a relationship, e.g. "placed". */
  edgeLabel: (key: string, sourceType?: string, targetType?: string) => string;
  /** Sentence form, e.g. "Customer placed Sales order". */
  describeEdge: (key: string, sourceType: string, targetType: string) => string;
  countFor: (key: string) => number | undefined;
  refetch: () => void;
}

export const SchemaContext = createContext<SchemaContextValue | null>(null);
