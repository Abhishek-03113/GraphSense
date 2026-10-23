import { ArrowUpRight, Workflow } from 'lucide-react';
import { Page } from '../../app/Page';
import { LinkCard } from '../../components/ui/Card';
import { EmptyState, ErrorState } from '../../components/ui/EmptyState';
import { Skeleton } from '../../components/ui/Skeleton';
import { useSchema } from '../../lib/schema';
import styles from './Flows.module.css';
import { FlowStepsLine } from './FlowStepsLine';

export default function FlowsPage() {
  const { schema, status, error, refetch } = useSchema();

  return (
    <Page title="Flows" subtitle="Follow how work moves from one step to the next. Pick a flow to see real records laid out in order.">
      {status === 'loading' && (
        <div className={styles.grid} aria-busy="true" role="status" aria-label="Loading flows">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className={styles.card} style={{ padding: 20, background: 'var(--gs-surface-1)', borderRadius: 'var(--gs-radius-lg)' }}>
              <Skeleton width="55%" height={18} />
              <Skeleton />
              <Skeleton width="80%" />
              <Skeleton width="70%" height={14} />
            </div>
          ))}
        </div>
      )}
      {status === 'error' && <ErrorState title="Flows didn’t load" error={error} onRetry={refetch} />}
      {status === 'ready' && schema.flows.length === 0 && (
        <EmptyState
          icon={<Workflow size={22} />}
          title="No flows yet"
          description="Flows describe a business process step by step. None are defined for this dataset, but you can still explore its records and relationships."
        />
      )}
      {status === 'ready' && schema.flows.length > 0 && (
        <ul className={styles.grid}>
          {schema.flows.map((flow) => (
            <li key={flow.id}>
              <LinkCard to={`/flows/${encodeURIComponent(flow.id)}`} className={styles.cardLink} aria-label={`${flow.label}. ${flow.description}`}>
                <div className={styles.card}>
                  <h2 className={styles.cardTitle}>
                    {flow.label}
                    <ArrowUpRight size={18} aria-hidden="true" />
                  </h2>
                  {flow.description && <p className={styles.description}>{flow.description}</p>}
                  <FlowStepsLine flow={flow} />
                </div>
              </LinkCard>
            </li>
          ))}
        </ul>
      )}
    </Page>
  );
}
