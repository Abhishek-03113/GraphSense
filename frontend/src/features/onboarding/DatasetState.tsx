import { AlertTriangle, Check, DatabaseZap, RefreshCw } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { EmptyState } from '../../components/ui/EmptyState';
import { formatDateTime } from '../../lib/format';
import { useSchema } from '../../lib/schema';
import styles from './DatasetState.module.css';

/** The steps of a load as people would describe them, in order, and the server phases each one covers. */
const STEPS = [
  { id: 'read', label: 'Reading the source files', phases: ['plan', 'stage'] },
  { id: 'load', label: 'Loading records', phases: ['load'] },
  { id: 'check', label: 'Checking the data', phases: ['validate'] },
  { id: 'publish', label: 'Making it available', phases: ['pre_swap', 'swap', 'post_swap', 'done'] },
] as const;

function stepIndex(phase: string | null | undefined): number {
  const index = STEPS.findIndex((step) => (step.phases as readonly string[]).includes(phase ?? ''));
  return index;
}

function LoadProgress({ phase }: { phase: string | null | undefined }) {
  const current = stepIndex(phase);
  const known = current >= 0;
  const percent = known ? Math.round(((current + 0.5) / STEPS.length) * 100) : undefined;
  return (
    <div className={styles.progress}>
      <div
        className={[styles.bar, known ? '' : styles.indeterminate].filter(Boolean).join(' ')}
        role="progressbar"
        aria-label="Loading your data"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={known ? `${STEPS[current].label}, step ${current + 1} of ${STEPS.length}` : 'Working'}
      >
        <span className={styles.fill} style={known ? { width: `${percent}%` } : undefined} />
      </div>
      <ol className={styles.steps} aria-label="Steps">
        {STEPS.map((step, index) => {
          const state = !known ? 'todo' : index < current ? 'done' : index === current ? 'now' : 'todo';
          return (
            <li key={step.id} className={styles[state]} aria-current={state === 'now' ? 'step' : undefined}>
              <span className={styles.marker} aria-hidden="true">
                {state === 'done' ? <Check size={12} /> : index + 1}
              </span>
              <span>
                {step.label}
                {state === 'done' && <span className="gs-sr-only"> (done)</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * Shown wherever the data itself is needed but is not there yet: nothing loaded, a load running, a load that
 * did not finish, or a load that produced no records. It only reports; customers do not start loads, their
 * administrator does, and the screen updates by itself when the data arrives.
 */
export function DatasetState() {
  const { dataset, datasetPhase, recheckDataset, isRecheckingDataset } = useSchema();
  const run = dataset?.last_run;
  const attempted = formatDateTime(run?.finished_at ?? run?.started_at);

  const recheck = (
    <Button variant="secondary" size="sm" icon={<RefreshCw size={14} />} loading={isRecheckingDataset} onClick={recheckDataset}>
      Check again
    </Button>
  );

  let body;
  if (datasetPhase === 'loading') {
    body = (
      <EmptyState
        tone="accent"
        icon={<RefreshCw size={24} className={styles.spin} />}
        title="Your data is being loaded"
        description="This can take a few minutes for larger datasets. This page updates by itself as soon as the records are ready."
        detail={<LoadProgress phase={run?.phase} />}
      />
    );
  } else if (datasetPhase === 'failed') {
    body = (
      <EmptyState
        tone="danger"
        icon={<AlertTriangle size={24} />}
        title="The last data load didn’t finish"
        description="Your administrator can see what went wrong and run it again. This page updates by itself once a load completes."
        actions={recheck}
        detail={attempted ? <span>Last attempt: {attempted}</span> : undefined}
      />
    );
  } else if (datasetPhase === 'ready') {
    body = (
      <EmptyState
        icon={<DatabaseZap size={24} />}
        title="The data is loaded, but it has no records"
        description="The load finished without finding any records. Ask your administrator to check the source files."
        actions={recheck}
      />
    );
  } else {
    body = (
      <EmptyState
        tone="accent"
        icon={<DatabaseZap size={24} />}
        title="Your data hasn’t been loaded yet"
        description="Your administrator loads the data for this workspace. Once it’s in, this page fills in with a summary you can explore, question and trace. There’s nothing you need to do."
        actions={recheck}
        detail={<span>We check on it automatically, so you can leave this page open.</span>}
      />
    );
  }

  return (
    <div className={styles.wrap}>
      <Card padded={false} className={styles.card}>
        <div role="status" aria-live="polite">
          {body}
        </div>
      </Card>
    </div>
  );
}
