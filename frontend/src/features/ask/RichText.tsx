import { Fragment, type ReactNode } from 'react';
import styles from './Ask.module.css';

/** Inline formatting: **bold** and `code`. Everything else is plain text; nothing is injected as HTML. */
function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) return <code key={index} className={styles.inlineCode}>{part.slice(1, -1)}</code>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}

/** Renders an answer: paragraphs, bullet lists and numbered lists. */
export function RichText({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/);
  return (
    <div className={styles.prose}>
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n').filter((line) => line.trim() !== '');
        if (lines.length > 0 && lines.every((line) => /^\s*[-*•]\s+/.test(line))) {
          return (
            <ul key={blockIndex} className={styles.bullets}>
              {lines.map((line, index) => (
                <li key={index}>{inline(line.replace(/^\s*[-*•]\s+/, ''))}</li>
              ))}
            </ul>
          );
        }
        if (lines.length > 0 && lines.every((line) => /^\s*\d+[.)]\s+/.test(line))) {
          return (
            <ol key={blockIndex} className={styles.numbers}>
              {lines.map((line, index) => (
                <li key={index}>{inline(line.replace(/^\s*\d+[.)]\s+/, ''))}</li>
              ))}
            </ol>
          );
        }
        return (
          <p key={blockIndex}>
            {lines.map((line, index) => (
              <Fragment key={index}>
                {index > 0 && <br />}
                {inline(line)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
