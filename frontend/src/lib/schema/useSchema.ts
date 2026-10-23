import { useContext } from 'react';
import { SchemaContext, type SchemaContextValue } from './context';

/** Everything the UI knows about the loaded dataset: types, relationships, flows, counts and helpers. */
export function useSchema(): SchemaContextValue {
  const value = useContext(SchemaContext);
  if (!value) throw new Error('useSchema must be used inside <SchemaProvider>.');
  return value;
}
