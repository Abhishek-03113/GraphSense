/**
 * Generic text and value formatting. Nothing here knows about a specific
 * dataset: it works from key shapes ("total_net_amount", "SalesOrderItem")
 * and value shapes (ISO dates, numeric strings).
 */

/** "SalesOrderItem" → "Sales order item", "billing_document" → "Billing document", "HAS_ITEM" → "Has item". */
export function humanize(key: string): string {
  const trimmed = key.trim();
  if (!trimmed) return '';
  const screaming = /^[A-Z0-9_]+$/.test(trimmed);
  const spaced = trimmed
    .replace(/[_\-.]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim();
  const words = spaced.split(' ').map((word, index) => {
    const keepAcronym = !screaming && /^[A-Z]{2,4}$/.test(word);
    if (keepAcronym) return word;
    const lower = word.toLowerCase();
    return index === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
  });
  return words.join(' ');
}

/** Lower-case the first letter unless it starts an acronym ("SAP order" stays). */
export function lowerFirst(text: string): string {
  if (text.length < 2) return text.toLowerCase();
  if (/^[A-Z]{2,}/.test(text)) return text;
  return text.charAt(0).toLowerCase() + text.slice(1);
}

export function pluralize(count: number, singular: string, plural?: string): string {
  if (count === 1) return singular;
  if (plural) return plural;
  if (/(s|x|z|ch|sh)$/i.test(singular)) return `${singular}es`;
  if (/[^aeiou]y$/i.test(singular)) return `${singular.slice(0, -1)}ies`;
  return `${singular}s`;
}

const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const integerFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const compactFormat = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

export const formatNumber = (value: number): string => numberFormat.format(value);
export const formatInteger = (value: number): string => integerFormat.format(value);
export const formatCompact = (value: number): string => (Math.abs(value) >= 10_000 ? compactFormat.format(value) : integerFormat.format(value));

const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/;
const NUMERIC = /^-?\d+(?:\.\d+)?$/;
const AMOUNT_KEY = /(^|_|(?<=[a-z]))(amount|price|cost|value|total|net|gross|tax|balance|quantity|qty|weight|volume|rate|discount)(_|$|(?=[A-Z]))/i;
const IDENTIFIER_KEY = /(^|_|(?<=[a-z]))(id|ids|number|no|document|code|reference|key)(_|$|(?=[A-Z]))/i;

export type ValueKind = 'text' | 'date' | 'number' | 'identifier' | 'boolean' | 'empty';

export interface FormattedValue {
  text: string;
  kind: ValueKind;
  /** Right-align and use tabular numerals. */
  numeric: boolean;
  /** Render in the monospace face. */
  mono: boolean;
}

export function formatValue(key: string, value: unknown): FormattedValue {
  if (value === null || value === undefined || value === '') {
    return { text: '—', kind: 'empty', numeric: false, mono: false };
  }
  if (typeof value === 'boolean') {
    return { text: value ? 'Yes' : 'No', kind: 'boolean', numeric: false, mono: false };
  }
  if (typeof value === 'object') {
    return { text: JSON.stringify(value), kind: 'text', numeric: false, mono: true };
  }
  const raw = String(value).trim();

  if (ISO_DATE.test(raw) && !Number.isNaN(Date.parse(raw))) {
    const hasTime = raw.length > 10;
    const date = new Date(raw);
    return {
      text: hasTime ? dateTimeFormat.format(date) : dateFormat.format(new Date(`${raw}T00:00:00`)),
      kind: 'date',
      numeric: false,
      mono: false,
    };
  }

  const isNumeric = typeof value === 'number' || NUMERIC.test(raw);
  if (isNumeric) {
    const asNumber = Number(raw);
    const amountKey = AMOUNT_KEY.test(key);
    // Whole numbers that arrive as text (and are not named like an amount) are identifiers: keep them verbatim.
    const wholeText = typeof value === 'string' && /^\d+$/.test(raw);
    const identifierKey = IDENTIFIER_KEY.test(key) && !amountKey;
    if (identifierKey || (wholeText && !amountKey)) {
      return { text: raw, kind: 'identifier', numeric: false, mono: true };
    }
    return { text: numberFormat.format(asNumber), kind: 'number', numeric: true, mono: false };
  }

  if (IDENTIFIER_KEY.test(key) && /^[A-Za-z0-9_\-/.]+$/.test(raw) && raw.length <= 40) {
    return { text: raw, kind: 'identifier', numeric: false, mono: true };
  }
  return { text: raw, kind: 'text', numeric: false, mono: false };
}

/** Format a table cell for sorting and display; returns the raw comparable plus display text. */
export function compareValues(a: unknown, b: unknown): number {
  const aEmpty = a === null || a === undefined || a === '';
  const bEmpty = b === null || b === undefined || b === '';
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;
  const an = typeof a === 'number' ? a : NUMERIC.test(String(a)) ? Number(a) : NaN;
  const bn = typeof b === 'number' ? b : NUMERIC.test(String(b)) ? Number(b) : NaN;
  if (!Number.isNaN(an) && !Number.isNaN(bn)) return an - bn;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

/** Node ids look like "Type:value". These helpers keep that convention in one place. */
export function makeRecordId(type: string, value: string): string {
  return `${type}:${value}`;
}

export function parseRecordId(id: string): { type: string; value: string } {
  const index = id.indexOf(':');
  if (index < 0) return { type: '', value: id };
  return { type: id.slice(0, index), value: id.slice(index + 1) };
}

/** Download text as a file in the browser. */
export function downloadText(filename: string, text: string, mime = 'text/csv'): void {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function toCsv(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return '';
  const columns = Object.keys(rows[0]);
  const escape = (value: unknown) => {
    const text = value === null || value === undefined ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [columns.join(','), ...rows.map((row) => columns.map((c) => escape(row[c])).join(','))].join('\n');
}
