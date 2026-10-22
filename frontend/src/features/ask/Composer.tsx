import { ArrowUp } from 'lucide-react';
import { useEffect, useRef, type FormEvent, type KeyboardEvent } from 'react';
import { IconButton } from '../../components/ui/Button';
import { useAsk } from '../../store/ask';
import styles from './Ask.module.css';

const MAX_LENGTH = 2000;

/** Question box. Enter sends, Shift+Enter adds a line. The draft lives in the shared store so other screens can prefill it. */
export function Composer({ autoFocus }: { autoFocus?: boolean }) {
  const draft = useAsk((s) => s.draft);
  const setDraft = useAsk((s) => s.setDraft);
  const send = useAsk((s) => s.send);
  const pending = useAsk((s) => s.turns.some((turn) => turn.status === 'pending'));
  const ref = useRef<HTMLTextAreaElement>(null);

  // Grow with the content up to a limit.
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`;
  }, [draft]);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  // A prefilled draft (for example from "Ask about this") should be ready to edit.
  useEffect(() => {
    if (draft && document.activeElement !== ref.current && autoFocus) ref.current?.focus();
  }, [draft, autoFocus]);

  const tooLong = draft.length > MAX_LENGTH;
  const canSend = draft.trim().length > 0 && !pending && !tooLong;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (canSend) void send(draft);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className={styles.composerWrap}>
      <form className={styles.composer} onSubmit={submit}>
        <label htmlFor="ask-input" className="gs-sr-only">
          Your question
        </label>
        <textarea
          id="ask-input"
          ref={ref}
          className={styles.textarea}
          rows={1}
          value={draft}
          placeholder="Ask about your data…"
          aria-describedby="ask-hint"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <IconButton type="submit" variant="primary" size="lg" label={pending ? 'Waiting for an answer' : 'Send question'} icon={<ArrowUp size={18} />} disabled={!canSend} />
      </form>
      <p id="ask-hint" className={styles.composerHint}>
        <span className={styles.hintKeys}>Enter to send · Shift+Enter for a new line</span>
        <span className={tooLong ? styles.overLimit : undefined} aria-live="polite">
          {tooLong ? `${draft.length - MAX_LENGTH} characters over the limit` : 'Answers come from your data. Double-check anything important.'}
        </span>
      </p>
    </div>
  );
}
