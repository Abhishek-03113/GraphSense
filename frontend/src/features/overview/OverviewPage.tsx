import { ArrowRight, MessageSquareText, Route, Workflow } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Page } from '../../app/Page';
import { Card, LinkCard } from '../../components/ui/Card';
import { ErrorState } from '../../components/ui/EmptyState';
import { Skeleton } from '../../components/ui/Skeleton';
import { TypeDot } from '../../components/ui/TypeBadge';
import { formatInteger } from '../../lib/format';
import { useSchema } from '../../lib/schema';
import { FlowStepsLine } from '../flows/FlowStepsLine';
import { DatasetState } from '../onboarding/DatasetState';
import styles from './Overview.module.css';

function OverviewSkeleton() {
  return (
    <div className={styles.stack} role="status" aria-busy="true" aria-label="Loading overview">
      <div className={styles.hero}>
        <Skeleton width={320} height={38} />
        <Skeleton width="60%" height={22} />
      </div>
      <div className={styles.tiles}>
        {Array.from({ length: 4 }, (_, index) => (
          <Card key={index}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <Skeleton width="50%" />
              <Skeleton width="40%" height={36} />
              <Skeleton width="80%" />
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

export default function OverviewPage() {
  const { schema, status, error, refetch, isEmpty, counts, headlineTypes, otherTypes, totalRecords, totalRelationships, getTypeMeta, edgeLabel, typeLabel } = useSchema();
  const name = schema.domain.name;
  const hasName = status === 'ready' && !schema.domain.isDefault;

  const relationships = Object.entries(counts.edges)
    .map(([key, count]) => {
      const meta = schema.edgeTypes.find((edge) => edge.key === key);
      const label =
        meta?.source && meta?.target
          ? `${typeLabel(meta.source)} ${edgeLabel(key, meta.source, meta.target)} ${typeLabel(meta.target).toLowerCase()}`
          : (meta?.label ?? key).replace(/^./, (c) => c.toUpperCase());
      return { key, count, label };
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);
  const maxRelationship = Math.max(1, ...relationships.map((item) => item.count));

  return (
    <Page title="Overview" subtitle={hasName ? `A snapshot of ${name.toLowerCase()}.` : 'A snapshot of your data.'}>
      {status === 'loading' && <OverviewSkeleton />}
      {status === 'error' && <ErrorState title="The overview didn’t load" error={error} onRetry={refetch} />}

      {status === 'ready' && isEmpty && (
        <div className={styles.stack}>
          <div className={styles.hero}>
            <h2 className={styles.heroTitle}>{hasName ? name : 'Welcome to GraphSense'}</h2>
            <p className={styles.heroText}>{schema.domain.description || 'Explore your data as connected records, ask questions in plain language, and follow any record from start to finish.'}</p>
          </div>
          <DatasetState />
        </div>
      )}

      {status === 'ready' && !isEmpty && (
        <div className={styles.stack}>
          <div className={styles.hero}>
            {hasName && <span className={styles.eyebrow}>Your dataset</span>}
            <h2 className={styles.heroTitle}>{hasName ? name : 'Your data at a glance'}</h2>
            {schema.domain.description && <p className={styles.heroText}>{schema.domain.description}</p>}
          </div>

          <section className={styles.section} aria-label="Main record types">
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>What’s in your data</h2>
              <span className={styles.sectionHint}>{formatInteger(totalRecords)} records in total</span>
            </div>
            <ul className={styles.tiles}>
              {headlineTypes.map((type) => (
                <li key={type.key}>
                  <LinkCard to={`/records/${encodeURIComponent(type.key)}`} className={styles.tile} aria-label={`${type.plural}: ${formatInteger(counts.nodes[type.key] ?? 0)}. Browse records.`}>
                    <span className={styles.tileLabel}>
                      <TypeDot type={type.key} />
                      {type.plural}
                    </span>
                    <span className={styles.tileValue}>{formatInteger(counts.nodes[type.key] ?? 0)}</span>
                    {type.description && <span className={styles.tileText}>{type.description}</span>}
                    <span className={styles.tileLink}>
                      Browse <ArrowRight size={14} aria-hidden="true" />
                    </span>
                  </LinkCard>
                </li>
              ))}
            </ul>
          </section>

          <section className={styles.section} aria-label="Quick actions">
            <h2 className={styles.sectionTitle}>Start here</h2>
            <ul className={styles.actions}>
              <li>
                <LinkCard to="/ask" className={styles.action}>
                  <span className={styles.actionIcon}><MessageSquareText size={18} aria-hidden="true" /></span>
                  <span>
                    <span className={styles.actionTitle}>Ask a question</span>
                    <p className={styles.actionText}>Get answers in plain language, with the rows behind them.</p>
                  </span>
                </LinkCard>
              </li>
              <li>
                <LinkCard to="/trace" className={styles.action}>
                  <span className={styles.actionIcon}><Route size={18} aria-hidden="true" /></span>
                  <span>
                    <span className={styles.actionTitle}>Trace a record</span>
                    <p className={styles.actionText}>Follow one record through every step it touches.</p>
                  </span>
                </LinkCard>
              </li>
              <li>
                <LinkCard to="/flows" className={styles.action}>
                  <span className={styles.actionIcon}><Workflow size={18} aria-hidden="true" /></span>
                  <span>
                    <span className={styles.actionTitle}>Explore a flow</span>
                    <p className={styles.actionText}>See how work moves from one step to the next.</p>
                  </span>
                </LinkCard>
              </li>
            </ul>
          </section>

          <div className={styles.duo}>
            <Card>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>Relationships</h2>
                <Link to="/explore">See the map</Link>
              </div>
              <p className={styles.bigNumber}>{formatInteger(totalRelationships)}</p>
              <p className={styles.sectionHint}>connections between records</p>
              {relationships.length > 0 && (
                <ul className={styles.bars} aria-label="Most common connections">
                  {relationships.map((item) => (
                    <li key={item.key} className={styles.bar}>
                      <div className={styles.barHeader}>
                        <span>{item.label}</span>
                        <span className={styles.barValue}>{formatInteger(item.count)}</span>
                      </div>
                      <div className={styles.track} aria-hidden="true">
                        <div className={styles.fill} style={{ width: `${Math.max(2, (item.count / maxRelationship) * 100)}%` }} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {otherTypes.length > 0 && (
              <Card>
                <div className={styles.sectionHeader}>
                  <h2 className={styles.sectionTitle}>Supporting records</h2>
                  <span className={styles.sectionHint}>{otherTypes.length} types</span>
                </div>
                <ul className={styles.plainList}>
                  {otherTypes.map((type) => (
                    <li key={type.key}>
                      <Link to={`/records/${encodeURIComponent(type.key)}`} className={styles.plainRow} title={getTypeMeta(type.key).description || undefined}>
                        <TypeDot type={type.key} />
                        <span className={styles.plainName}>{type.plural}</span>
                        <span className={styles.plainCount}>{formatInteger(counts.nodes[type.key] ?? 0)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>

          {schema.flows.length > 0 && (
            <section className={styles.section} aria-label="Flows">
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>Flows</h2>
                <Link to="/flows">See all flows</Link>
              </div>
              <ul className={styles.flowGrid}>
                {schema.flows.slice(0, 6).map((flow) => (
                  <li key={flow.id}>
                    <LinkCard to={`/flows/${encodeURIComponent(flow.id)}`} aria-label={`${flow.label}. ${flow.description}`} style={{ height: '100%' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gs-space-2)', height: '100%' }}>
                        <span className={styles.actionTitle}>{flow.label}</span>
                        {flow.description && <p className={styles.actionText}>{flow.description}</p>}
                        <FlowStepsLine flow={flow} />
                      </div>
                    </LinkCard>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </Page>
  );
}
