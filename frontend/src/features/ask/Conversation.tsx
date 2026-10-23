import { Sparkles } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { makeRecordId } from '../../lib/format';
import { useSchema } from '../../lib/schema';
import { useAsk, type RecordRef } from '../../store/ask';
import { useWorkspace } from '../../store/workspace';
import styles from './Ask.module.css';
import { AiNotice } from './AiNotice';
import { Composer } from './Composer';
import { useSuggestedPrompts } from './prompts';
import { TurnView } from './TurnView';

interface ConversationProps {
  compact?: boolean;
  /** Override what happens when a record chip is chosen (Explore handles it in place). */
  onOpenRecord?: (focus: RecordRef, all: RecordRef[]) => void;
}

/** The thread of questions and answers plus the composer. Used full-page on Ask and as a panel in Explore. */
export function Conversation({ compact, onOpenRecord }: ConversationProps) {
  const turns = useAsk((s) => s.turns);
  const send = useAsk((s) => s.send);
  const navigate = useNavigate();
  const setHighlightedIds = useWorkspace((s) => s.setHighlightedIds);
  const { schema, status } = useSchema();
  const suggestions = useSuggestedPrompts(compact ? 4 : 6);
  const endRef = useRef<HTMLDivElement>(null);

  // Keep the newest answer in view.
  const lastStatus = turns.at(-1)?.status;
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end', behavior: 'smooth' });
  }, [turns.length, lastStatus]);

  const openInExplore = (focus: RecordRef, all: RecordRef[]) => {
    if (onOpenRecord) {
      onOpenRecord(focus, all);
      return;
    }
    setHighlightedIds(all.map((record) => record.id));
    navigate(`/explore?focus=${encodeURIComponent(focus.id || makeRecordId(focus.type, focus.label))}`);
  };

  return (
    <div className={[styles.layout, compact ? styles.compact : ''].filter(Boolean).join(' ')}>
      <div className={styles.scroller}>
        <div className={styles.thread}>
          <AiNotice />
          {turns.length === 0 && (
            <section className={styles.welcome} aria-label="Getting started">
              <div>
                <h2 className={styles.welcomeTitle}>What would you like to know?</h2>
                <p className={styles.welcomeText}>
                  Ask a question about {status === 'ready' && !schema.domain.isDefault ? `the ${schema.domain.name.toLowerCase()} data` : 'your data'} in everyday language. You’ll get an answer, the rows behind it, and the records involved.
                </p>
              </div>
              {suggestions.length > 0 && (
                <div>
                  <h3 className={styles.suggestionsTitle}>Try asking</h3>
                  <div className={styles.suggestions}>
                    {suggestions.map((prompt) => (
                      <button key={prompt} type="button" className={styles.suggestion} onClick={() => void send(prompt)}>
                        <Sparkles size={16} aria-hidden="true" />
                        <span>{prompt}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}
          {turns.map((turn) => (
            <TurnView key={turn.id} turn={turn} suggestions={suggestions} onPickPrompt={(prompt) => void send(prompt)} onOpenRecord={openInExplore} />
          ))}
          <div ref={endRef} />
        </div>
      </div>
      <Composer autoFocus />
    </div>
  );
}
