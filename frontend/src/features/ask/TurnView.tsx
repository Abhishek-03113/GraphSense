import { AlertTriangle, Download, Info, Network, RotateCw, ServerOff, SearchX } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button, IconButton } from '../../components/ui/Button';
import { Disclosure } from '../../components/ui/Disclosure';
import { DataTable, type Column } from '../../components/ui/Table';
import { TypeDot } from '../../components/ui/TypeBadge';
import { Skeleton } from '../../components/ui/Skeleton';
import { downloadText, formatInteger, formatValue, humanize, pluralize, toCsv } from '../../lib/format';
import { recordValue } from '../../lib/graph';
import { useSchema } from '../../lib/schema';
import { useAsk, type RecordRef, type Turn } from '../../store/ask';
import { Copy, Check } from 'lucide-react';
import styles from './Ask.module.css';
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

interface NoticeProps {
  tone?: 'info' | 'warn' | 'danger';
  icon: React.ReactNode;
  title: string;
  children?: React.ReactNode;
  actions?: React.ReactNode;
}

function Notice({ tone = 'info', icon, title, children, actions }: NoticeProps) {
  const toneClass = tone === 'warn' ? styles.noticeWarn : tone === 'danger' ? styles.noticeDanger : '';
  return (
    <div className={[styles.notice, toneClass].filter(Boolean).join(' ')} role={tone === 'danger' ? 'alert' : undefined}>
      <span className={styles.noticeIcon} aria-hidden="true">{icon}</span>
      <div className={styles.noticeBody}>
        <p className={styles.noticeTitle}>{title}</p>
        {children && <div className={styles.noticeText}>{children}</div>}
        {actions && <div className={styles.noticeActions}>{actions}</div>}
      </div>
    </div>
  );
}

function ResultTable({ rows, rowCount }: { rows: Record<string, unknown>[]; rowCount: number }) {
  const shown = rows.slice(0, MAX_ROWS);
  const columns = useMemo<Column<Record<string, unknown>>[]>(() => {
    const keys = Object.keys(rows[0] ?? {});
    return keys.map((key) => {
      const sample = rows.slice(0, 25).map((row) => formatValue(key, row[key])).filter((f) => f.kind !== 'empty');
      const numeric = sample.length > 0 && sample.every((f) => f.numeric);
      const mono = sample.length > 0 && sample.every((f) => f.mono);
      return {
        key,
        header: humanize(key),
        value: (row) => row[key],
        render: (row) => formatValue(key, row[key]).text,
        sortable: true,
        align: numeric ? 'right' : 'left',
        numeric,
        mono,
      };
    });
  }, [rows]);

  const total = rowCount || rows.length;
  return (
    <div className={styles.block}>
      <div className={styles.blockHeader}>
        <h3 className={styles.blockTitle}>
          Results <span className={styles.muted}>· {formatInteger(total)} {pluralize(total, 'row')}</span>
        </h3>
        <Button size="sm" variant="ghost" icon={<Download size={14} />} onClick={() => downloadText('graphsense-results.csv', toCsv(rows))}>
          Download CSV
        </Button>
      </div>
      <DataTable caption="Query results" columns={columns} rows={shown} rowKey={(row) => JSON.stringify(row)} maxHeight={320} />
      {rows.length > MAX_ROWS && (
        <p className={styles.muted}>Showing the first {MAX_ROWS} rows. Download the CSV for all {formatInteger(rows.length)}.</p>
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

function ErrorReply({ turn, suggestions, onPick }: { turn: Turn; suggestions: string[]; onPick: (prompt: string) => void }) {
  const code = turn.errorCode ?? '';
  const answer = turn.answer?.trim();
  const tryThese = suggestions.slice(0, 2).map((prompt) => (
    <Button key={prompt} size="sm" onClick={() => onPick(prompt)}>
      {prompt}
    </Button>
  ));

  if (code === 'guardrail') {
    return (
      <Notice icon={<Info size={18} />} title="That’s outside what I can help with" actions={tryThese.length > 0 ? tryThese : undefined}>
        {answer || 'I can answer questions about the data in this workspace: its records, how they connect and what they add up to.'}
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
    const detail = code.replace(/^sql_execution_error:?\s*/, '');
    return (
      <Notice tone="warn" icon={<AlertTriangle size={18} />} title="The lookup didn’t run" actions={tryThese.length > 0 ? tryThese : undefined}>
        <p>I understood the question, but the data lookup failed. Rephrasing it, or narrowing it down, often helps.</p>
        {detail && (
          <Disclosure label="Technical details">
            <pre className={styles.technical}>{detail}</pre>
          </Disclosure>
        )}
      </Notice>
    );
  }
  return (
    <Notice tone="danger" icon={<AlertTriangle size={18} />} title="Something went wrong">
      {answer || 'The answer couldn’t be completed. Please try again.'}
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

        {turn.status === 'done' && turn.errorCode && <ErrorReply turn={turn} suggestions={suggestions} onPick={onPickPrompt} />}

        {turn.status === 'done' && !turn.errorCode && (
          <>
            {turn.answer ? <RichText text={turn.answer} /> : <p className={styles.muted}>The lookup finished, but there’s no written answer to show.</p>}
            {hasRows && <ResultTable rows={turn.rows as Record<string, unknown>[]} rowCount={turn.rowCount ?? 0} />}
            {turn.rows && turn.rows.length === 0 && <p className={styles.muted}>No rows matched, so there’s nothing to list.</p>}
            {turn.records && turn.records.length > 0 && <RecordChips records={turn.records} onOpen={onOpenRecord} />}
            {turn.sql && <SqlBlock sql={turn.sql} />}
          </>
        )}
      </div>
    </article>
  );
}
