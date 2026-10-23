import { CheckCircle2, DatabaseZap, AlertTriangle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Disclosure } from '../../components/ui/Disclosure';
import { EmptyState } from '../../components/ui/EmptyState';
import { Input } from '../../components/ui/Field';
import { describeError } from '../../lib/api/client';
import { useIngest, useSummary } from '../../lib/api/queries';
import styles from './LoadDataEmpty.module.css';

/**
 * First-run state when the dataset has no records yet. Starts the server-side
 * load and, once started, watches the record count until data arrives.
 */
export function LoadDataEmpty() {
  const ingest = useIngest();
  const summary = useSummary();
  const [dataDir, setDataDir] = useState('');
  const started = ingest.isSuccess;

  // While a load is running, check for new records every few seconds.
  const { refetch } = summary;
  useEffect(() => {
    if (!started) return undefined;
    const timer = window.setInterval(() => void refetch(), 4000);
    return () => window.clearInterval(timer);
  }, [started, refetch]);

  return (
    <div className={styles.wrap}>
      <Card padded={false} className={styles.card}>
        <EmptyState
          tone="accent"
          icon={<DatabaseZap size={24} />}
          title="Load your data to get started"
          description="GraphSense turns your source files into records and the relationships between them. Once the data is loaded, this space fills in with a summary you can explore, question and trace."
          actions={
            <Button variant="primary" size="lg" loading={ingest.isPending} disabled={started} onClick={() => ingest.mutate(dataDir.trim() || undefined)}>
              {started ? 'Loading started' : 'Load data'}
            </Button>
          }
          detail={
            <ol className={styles.steps}>
              <li>The server reads the data files from its configured folder.</li>
              <li>Records and relationships are created. This can take a few minutes for large datasets.</li>
              <li>This page updates by itself as soon as the first records appear.</li>
            </ol>
          }
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gs-space-3)', padding: '0 var(--gs-space-4) var(--gs-space-4)' }}>
          {started && (
            <div className={`${styles.status} ${styles.ok}`} role="status">
              <CheckCircle2 size={16} aria-hidden="true" />
              <span>Loading has started. We’re checking for new records every few seconds. You can leave this page open or come back later.</span>
            </div>
          )}
          {ingest.isError && (
            <div className={`${styles.status} ${styles.bad}`} role="alert">
              <AlertTriangle size={16} aria-hidden="true" />
              <span>
                {describeError(ingest.error)} If the data folder is in a different place on the server, enter its path under “Use a different folder”.
              </span>
            </div>
          )}
          <div className={styles.advanced}>
            <Disclosure label="Use a different folder">
              <Input
                label="Data folder on the server"
                hint="Leave blank to use the folder the server is already set up with."
                value={dataDir}
                mono
                placeholder="/path/to/data"
                onChange={(event) => setDataDir(event.target.value)}
              />
            </Disclosure>
          </div>
        </div>
      </Card>
    </div>
  );
}
