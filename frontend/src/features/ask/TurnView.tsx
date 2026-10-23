import {
  AlertTriangle,
  Check,
  Clock,
  Copy,
  DatabaseZap,
  Download,
  Hourglass,
  Info,
  KeyRound,
  Lightbulb,
  Network,
  RotateCw,
  SearchX,
  ServerOff,
  ShieldAlert,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, IconButton } from '../../components/ui/Button';
import { Disclosure } from '../../components/ui/Disclosure';
import { DataTable, type Column } from '../../components/ui/Table';
import { TypeDot } from '../../components/ui/TypeBadge';
import { Skeleton } from '../../components/ui/Skeleton';
import { ValueText } from '../../components/ui/ValueText';
import type { ChatColumn } from '../../lib/api/schemas';
import { currencyFor, downloadText, formatInteger, formatValue, humanize, pluralize, toCsv } from '../../lib/format';
import { recordValue } from '../../lib/graph';
import { useSchema } from '../../lib/schema';
import { useAsk, type RecordRef, type Turn } from '../../store/ask';
import styles from './Ask.module.css';
import { Notice } from './Notice';
import { RichText } from './RichText';

const STAGES = ['Reading your question', 'Finding the right data', 'Running the lookup', 'Writing up the answer'];
const MAX_ROWS = 200;

function PendingReply() {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), 1600);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className={styles.pending} role="status" aria-live="polite">
      <span className={styles.stage}>
        <span className={styles.pulse} aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        {STAGES[stage]}…
      </span>
      <div className={styles.skeletonLines} aria-hidden="true">
        <Skeleton width="92%" />
        <Skeleton width="78%" />
        <Skeleton width="54%" />
      </div>
    </div>
  );
}

interface ResultTableProps {
  rows: Record<string, unknown>[];
  rowCount: number;
  columns: ChatColumn[];
  truncated: boolean;
}

function ResultTable({ rows, rowCount, columns: columnInfo, truncated }: ResultTableProps) {
  const shown = rows.slice(0, MAX_ROWS);
  const columns = useMemo<Column<Record<string, unknown>>[]>(() => {
    const info = new Map(columnInfo.map((column) => [column.name, column]));
    const keys = Object.keys(rows[0] ?? {});
    return keys.map((key) => {
      const details = info.get(key);
      const labels = details?.value_labels ?? undefined;
      const cell = (row: Record<string, unknown>) => formatValue(key, row[key], { currency: currencyFor(key, row), valueLabels: labels });
      const sample = rows.slice(0, 25).map(cell).filter((f) => f.kind !== 'empty');
      const numeric = sample.length > 0 && sample.every((f) => f.numeric);
      const mono = sample.length > 0 && sample.every((f) => f.mono);
      return {
        key,
        header: details?.label?.trim() || humanize(key),
        // Sort by what people read: the label when the value is a code.
        value: (row) => (labels ? (cell(row).label ?? row[key]) : row[key]),
        render: (row) => <ValueText nowrap value={cell(row)} />,
        sortable: true,
        align: numeric ? 'right' : 'left',
        numeric,
        mono,
      };
    });
  }, [rows, columnInfo]);

  const total = rowCount || rows.length;
  const showing = Math.min(shown.length, MAX_ROWS);
  return (
    <div className={styles.block}>
      <div className={styles.blockHeader}>
        <h3 className={styles.blockTitle}>
          Results <span className={styles.muted}>· {truncated ? `first ${formatInteger(rows.length)}` : formatInteger(total)} {pluralize(truncated ? rows.length : total, 'row')}</span>
        </h3>
        <Button size="sm" variant="ghost" icon={<Download size={14} />} onClick={() => downloadText('graphsense-results.csv', toCsv(rows))}>
          Download CSV
        </Button>
      </div>
      <DataTable caption="Query results" columns={columns} rows={shown} rowKey={(row) => JSON.stringify(row)} maxHeight={320} />
      {truncated ? (
        <p className={styles.muted} role="note">
          Showing the first {formatInteger(showing)} rows. More rows match than can be returned at once, so the list is cut off here. Narrow the question to see the rest.
        </p>
      ) : (
        rows.length > MAX_ROWS && <p className={styles.muted}>Showing the first {MAX_ROWS} rows. Download the CSV for all {formatInteger(rows.length)}.</p>
      )}
    </div>
  );
}

function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <Disclosure label="View query">
      <div className={styles.sqlActions}>
        <IconButton size="sm" label={copied ? 'Copied' : 'Copy query'} icon={copied ? <Check size={14} /> : <Copy size={14} />} onClick={copy} />
      </div>
      <pre className={styles.sql}><code>{sql}</code></pre>
    </Disclosure>
  );
}

function RecordChips({ records, onOpen }: { records: RecordRef[]; onOpen: (focus: RecordRef, all: RecordRef[]) => void }) {
  const { typeLabel } = useSchema();
  const shown = records.slice(0, 12);
  return (
    <div className={styles.block}>
      <div className={styles.blockHeader}>
        <h3 className={styles.blockTitle}>
          Records mentioned <span className={styles.muted}>· {records.length}</span>
        </h3>
        {records.length > 1 && (
          <Button size="sm" variant="accentGhost" icon={<Network size={14} />} onClick={() => onOpen(records[0], records)}>
            Show all in Explore
          </Button>
        )}
      </div>
      <ul className={styles.chips} aria-label="Records mentioned">
        {shown.map((record) => (
          <li key={record.id}>
            <button
              type="button"
              className={styles.chip}
              onClick={() => onOpen(record, records)}
              aria-label={`Open ${typeLabel(record.type)} ${recordValue({ id: record.id, type: record.type })} in Explore`}
            >
              <TypeDot type={record.type} />
              <span>{typeLabel(record.type)}</span>
              <span className={styles.chipId}>{recordValue({ id: record.id, type: record.type })}</span>
            </button>
          </li>
        ))}
        {records.length > shown.length && <li className={styles.muted}>+{records.length - shown.length} more</li>}
      </ul>
    </div>
  );
}

/** Whole seconds left until `until` (epoch ms), counting down once a second. */
function useSecondsUntil(until: number | undefined): number {
  const remaining = () => (until === undefined ? 0 : Math.max(0, Math.ceil((until - Date.now()) / 1000)));
  const [seconds, setSeconds] = useState(remaining);
  useEffect(() => {
    setSeconds(remaining());
    if (until === undefined) return undefined;
    const timer = window.setInterval(() => {
      const next = Math.max(0, Math.ceil((until - Date.now()) / 1000));
      setSeconds(next);
      if (next === 0) window.clearInterval(timer);
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `remaining` only reads `until`
  }, [until]);
  return seconds;
}

function formatWait(seconds: number): string {
  if (seconds < 60) return `${seconds} ${pluralize(seconds, 'second')}`;
  const minutes = Math.ceil(seconds / 60);
  return `${minutes} ${pluralize(minutes, 'minute')}`;
}

function RateLimited({ turn }: { turn: Turn }) {
  const retry = useAsk((s) => s.retry);
  const seconds = useSecondsUntil(turn.retryAt);
  const known = turn.retryAt !== undefined;
  const waiting = known && seconds > 0;
  return (
    <Notice
      tone="warn"
      icon={<Clock size={18} />}
      title="You’re asking a little faster than I can answer"
      actions={
        <Button size="sm" icon={<RotateCw size={14} />} disabled={waiting} onClick={() => void retry(turn.id)}>
          Try again
        </Button>
      }
    >
      <p>
        {waiting
          ? `Please wait about ${formatWait(seconds)} and ask again. Your question is saved.`
          : known
            ? 'You can ask again now. Your question is saved.'
            : 'Please wait a moment and ask again. Your question is saved.'}
      </p>
    </Notice>
  );
}

const EXECUTION_HINTS: Record<string, string> = {
  timeout: 'That lookup took too long to finish. Narrowing it down, for example to one customer or a shorter period, usually helps.',
};

function ErrorReply({ turn, fallbackSuggestions, onPick }: { turn: Turn; fallbackSuggestions: string[]; onPick: (prompt: string) => void }) {
  const retry = useAsk((s) => s.retry);
  const code = turn.errorCode ?? '';
  const answer = turn.answer?.trim();
  // The server's own suggestions fit the question best; the screen's starter questions are the fallback.
  const ideas = (turn.suggestions && turn.suggestions.length > 0 ? turn.suggestions : fallbackSuggestions).slice(0, 3);
  const tryThese = ideas.map((prompt) => (
    <Button key={prompt} size="sm" onClick={() => onPick(prompt)}>
      {prompt}
    </Button>
  ));
  const tryAgain = (
    <Button size="sm" icon={<RotateCw size={14} />} onClick={() => void retry(turn.id)}>
      Try again
    </Button>
  );

  if (code === 'guardrail') {
    return (
      <Notice icon={<Info size={18} />} title="That’s outside what I can help with" actions={tryThese.length > 0 ? tryThese : undefined}>
        {answer || 'I can answer questions about the data in this workspace: its records, how they connect and what they add up to.'}
      </Notice>
    );
  }
  if (code === 'not_configured') {
    return (
      <Notice tone="warn" icon={<KeyRound size={18} />} title="Ask isn’t set up on this server yet">
        <p>Your question can’t be answered until your administrator connects a language service. Browsing and tracing records works as usual in the meantime.</p>
        {turn.suggestions && turn.suggestions.length > 0 && (
          <>
            <p className={styles.noticeLead}>Once it’s on, you could ask things like:</p>
            <ul className={styles.noticeList}>
              {turn.suggestions.slice(0, 4).map((idea) => (
                <li key={idea}>{idea}</li>
              ))}
            </ul>
          </>
        )}
      </Notice>
    );
  }
  if (code === 'dataset_not_ready') {
    return (
      <Notice
        tone="warn"
        icon={<DatabaseZap size={18} />}
        title="This data isn’t loaded yet"
        actions={
          <Link to="/" className={styles.noticeLink}>
            See where things stand
          </Link>
        }
      >
        Questions can be answered as soon as the data has been loaded. Your administrator takes care of that, and this screen will work once they have.
      </Notice>
    );
  }
  if (code === 'provider_unavailable') {
    return (
      <Notice tone="warn" icon={<Hourglass size={18} />} title="The answering service isn’t responding" actions={tryAgain}>
        Ask depends on an outside language service, and it isn’t reachable at the moment. Your question is saved, so you can try again in a minute.
      </Notice>
    );
  }
  if (code === 'rate_limited') {
    return <RateLimited turn={turn} />;
  }
  if (code === 'sql_rejected') {
    return (
      <Notice
        tone="warn"
        icon={<ShieldAlert size={18} />}
        title="I can’t run that kind of lookup here"
        actions={tryThese.length > 0 ? tryThese : undefined}
      >
        I can only read and summarise this data: counts, lists, comparisons and trends. I can’t change it or look anything up outside it. Try asking for what you want to see instead.
      </Notice>
    );
  }
  if (code === 'sql_generation_failed') {
    return (
      <Notice tone="warn" icon={<SearchX size={18} />} title="I couldn’t turn that into a lookup" actions={tryThese.length > 0 ? tryThese : undefined}>
        {answer || 'Try naming the kind of record and what you’d like to know about it, for example “how many … are there?”.'}
      </Notice>
    );
  }
  if (code.startsWith('sql_execution_error')) {
    const category = code.replace(/^sql_execution_error:?\s*/, '').trim();
    return (
      <Notice tone="warn" icon={<AlertTriangle size={18} />} title="The lookup didn’t run" actions={tryThese.length > 0 ? tryThese : undefined}>
        {EXECUTION_HINTS[category] ?? 'I understood the question, but the lookup I wrote for it didn’t run. Rephrasing it, or narrowing it down, often helps.'}
      </Notice>
    );
  }
  return (
    <Notice tone="danger" icon={<AlertTriangle size={18} />} title="Something went wrong" actions={tryAgain}>
      {answer || 'The answer couldn’t be completed. Please try again.'}
    </Notice>
  );
}

function ListNotice({ tone, icon, title, items }: { tone?: 'info' | 'warn'; icon: React.ReactNode; title: string; items: string[] }) {
  return (
    <Notice tone={tone} icon={icon} title={title}>
      <ul className={styles.noticeList}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </Notice>
  );
}

interface TurnViewProps {
  turn: Turn;
  suggestions: string[];
  onPickPrompt: (prompt: string) => void;
  onOpenRecord: (focus: RecordRef, all: RecordRef[]) => void;
}

/** One question and its answer. */
export function TurnView({ turn, suggestions, onPickPrompt, onOpenRecord }: TurnViewProps) {
  const retry = useAsk((s) => s.retry);
  const hasRows = Boolean(turn.rows && turn.rows.length > 0);
  const assumptions = turn.assumptions ?? [];
  const warnings = turn.warnings ?? [];
  const followUps = (turn.suggestions ?? []).slice(0, 3);

  return (
    <article className={styles.turn} aria-label={`Question: ${turn.question}`}>
      <p className={styles.question}>{turn.question}</p>
      <div className={styles.reply}>
        {turn.status === 'pending' && <PendingReply />}

        {turn.status === 'failed' && (
          <Notice
            tone="danger"
            icon={<ServerOff size={18} />}
            title={turn.requestError?.offline ? 'Couldn’t reach the server' : 'The question couldn’t be answered'}
            actions={
              <Button size="sm" icon={<RotateCw size={14} />} onClick={() => void retry(turn.id)}>
                Try again
              </Button>
            }
          >
            {turn.requestError?.offline
              ? 'Check that the backend is running and reachable, then try again. Your question is saved.'
              : turn.requestError?.message}
          </Notice>
        )}

        {turn.status === 'done' && turn.errorCode && <ErrorReply turn={turn} fallbackSuggestions={suggestions} onPick={onPickPrompt} />}

        {turn.status === 'done' && !turn.errorCode && (
          <>
            {turn.answer ? <RichText text={turn.answer} /> : <p className={styles.muted}>The lookup finished, but there’s no written answer to show.</p>}
            {assumptions.length > 0 && <ListNotice icon={<Lightbulb size={18} />} title="How I read your question" items={assumptions} />}
            {warnings.length > 0 && <ListNotice tone="warn" icon={<AlertTriangle size={18} />} title="Worth knowing" items={warnings} />}
            {hasRows && (
              <ResultTable
                rows={turn.rows as Record<string, unknown>[]}
                rowCount={turn.rowCount ?? 0}
                columns={turn.columns ?? []}
                truncated={Boolean(turn.truncated)}
              />
            )}
            {turn.rows && turn.rows.length === 0 && <p className={styles.muted}>No rows matched, so there’s nothing to list.</p>}
            {turn.records && turn.records.length > 0 && <RecordChips records={turn.records} onOpen={onOpenRecord} />}
            {turn.sql && <SqlBlock sql={turn.sql} />}
            {followUps.length > 0 && (
              <div className={styles.block}>
                <h3 className={styles.blockTitle}>You could also ask</h3>
                <div className={styles.followUps}>
                  {followUps.map((prompt) => (
                    <Button key={prompt} size="sm" onClick={() => onPickPrompt(prompt)}>
                      {prompt}
                    </Button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </article>
  );
}
