import { useMemo } from 'react';
import { lowerFirst } from '../../lib/format';
import { useSuggestedQuestions } from '../../lib/api/queries';
import { useSchema } from '../../lib/schema';

/** Take up to `max` questions, one from each category before a second from any, keeping the author's order. */
export function pickVaried(questions: { text: string; category?: string | null }[], max: number): string[] {
  const seen = new Set<string>();
  const unique = questions.filter((question) => {
    const text = question.text.trim();
    if (!text || seen.has(text)) return false;
    seen.add(text);
    return true;
  });
  const categories = new Set<string>();
  const first: typeof unique = [];
  const rest: typeof unique = [];
  for (const question of unique) {
    const category = question.category ?? '';
    if (category && categories.has(category)) rest.push(question);
    else {
      if (category) categories.add(category);
      first.push(question);
    }
  }
  const chosen = new Set([...first, ...rest].slice(0, max));
  return unique.filter((question) => chosen.has(question)).map((question) => question.text.trim());
}

/**
 * Starter questions: the ones the dataset's author wrote when the server has them, otherwise questions
 * built from generic templates and the dataset's own labels. No record type is named here: every noun
 * comes from the schema.
 */
export function useSuggestedPrompts(max = 6): string[] {
  const { schema, headlineTypes, getTypeMeta, countFor, datasetId, isEmpty } = useSchema();
  const authored = useSuggestedQuestions(datasetId, !isEmpty);
  const authoredQuestions = authored.data?.questions;

  const generated = useMemo(() => {
    const prompts: string[] = [];
    const lower = (text: string) => lowerFirst(text);

    const [first, second, third] = headlineTypes;
    if (first) prompts.push(`How many ${lower(first.plural)} are there?`);

    // Relationship-based questions, using distinct source/target pairs.
    const seen = new Set<string>();
    const relations = schema.edgeTypes.filter((edge) => {
      if (!edge.source || !edge.target || edge.source === edge.target) return false;
      const pair = `${edge.source}>${edge.target}`;
      if (seen.has(pair)) return false;
      seen.add(pair);
      return true;
    });
    const preferred = relations.filter((edge) => headlineTypes.some((t) => t.key === edge.source) && headlineTypes.some((t) => t.key === edge.target));
    const chosen = (preferred.length >= 2 ? preferred : relations).slice(0, 2);
    chosen.forEach((edge, index) => {
      // Relationship direction varies, so treat the type with fewer records as the "parent":
      // "which customer has the most orders" reads naturally, the reverse does not.
      const a = getTypeMeta(edge.source as string);
      const b = getTypeMeta(edge.target as string);
      const aIsParent = (countFor(a.key) ?? 0) <= (countFor(b.key) ?? 0);
      const parent = aIsParent ? a : b;
      const child = aIsParent ? b : a;
      if (index === 0) {
        prompts.push(`Which ${lower(parent.label)} has the most ${lower(child.plural)}?`);
        prompts.push(`Show ${lower(parent.plural)} that don’t have any ${lower(child.plural)}.`);
      } else {
        prompts.push(`How many ${lower(child.plural)} does each ${lower(parent.label)} have on average?`);
      }
    });

    if (second) prompts.push(`Show me a few examples of ${lower(second.plural)}.`);
    if (third) prompts.push(`What are the most recent ${lower(third.plural)}?`);
    const name = schema.domain.name;
    if (name && !schema.domain.isDefault) prompts.push(`Give me an overview of the ${lower(name)} data.`);
    else prompts.push('Give me an overview of this dataset.');

    return [...new Set(prompts)].slice(0, max);
  }, [schema, headlineTypes, getTypeMeta, countFor, max]);

  return useMemo(
    () => (authoredQuestions && authoredQuestions.length > 0 ? pickVaried(authoredQuestions, max) : generated),
    [authoredQuestions, generated, max],
  );
}
