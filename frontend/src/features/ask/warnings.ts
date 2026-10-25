/**
 * Ask warnings arrive as stable codes or as ready-made sentences. Codes become plain language;
 * ones that only describe how the server looked things up are not worth the reader's attention.
 */
const WARNING_TEXT: Record<string, string | null> = {
  answer_unavailable: 'I couldn’t write a full summary just now, so here are the results as they came back. Asking again usually helps.',
  truncated: 'Only part of the results is shown. Narrow the question to see the rest.',
  embeddings_unavailable: null,
  'knowledge store unavailable': null,
};

export function readableWarnings(warnings: readonly string[]): string[] {
  return warnings.flatMap((warning) => {
    const text = Object.hasOwn(WARNING_TEXT, warning) ? WARNING_TEXT[warning] : warning;
    return text ? [text] : [];
  });
}
