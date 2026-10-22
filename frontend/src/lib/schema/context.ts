import { createContext } from 'react';
import type { Counts, PaletteSlot, ResolvedSchema, TypeMeta } from './types';

export interface SchemaContextValue {
  schema: ResolvedSchema;
  /** "loading" until both the schema and the counts have settled. */
  status: 'loading' | 'ready' | 'error';
  error: Error | null;
  counts: Counts;
  totalRecords: number;
  totalRelationships: number;
  /** True once counts have loaded and the dataset holds no records. */
  isEmpty: boolean;
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
