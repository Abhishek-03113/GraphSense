import { Network, Route, Rows3 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Navigate, NavLink, useNavigate, useParams } from 'react-router-dom';
import { Page } from '../../app/Page';
import { LinkButton } from '../../components/ui/Button';
import { EmptyState, ErrorState } from '../../components/ui/EmptyState';
import { SearchInput, Select } from '../../components/ui/Field';
import { Skeleton } from '../../components/ui/Skeleton';
import { DataTable, type Column } from '../../components/ui/Table';
import { TypeDot } from '../../components/ui/TypeBadge';
import { useEntities } from '../../lib/api/queries';
import { formatCompact, formatInteger, humanize, makeRecordId, pluralize } from '../../lib/format';
import { useSchema } from '../../lib/schema';
import { RecordInspector } from '../inspector/RecordInspector';
import { LoadDataEmpty } from '../onboarding/LoadDataEmpty';
import styles from './Records.module.css';

interface Row {
  id: string;
  label: string;
  extra: Record<string, unknown>;
}

const LIMITS = [25, 50, 100];

export default function RecordsPage() {
  const { type: typeParam } = useParams();
  const navigate = useNavigate();
  const { schema, status, isEmpty, countFor, getTypeMeta, headlineTypes, otherTypes } = useSchema();
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(50);
  const [openId, setOpenId] = useState<string | null>(null);

  const type = typeParam ? decodeURIComponent(typeParam) : undefined;
  const entities = useEntities(type, limit);
  const meta = type ? getTypeMeta(type) : null;

  const rows = useMemo<Row[]>(() => {
    const needle = query.trim().toLowerCase();
    return (entities.data?.entities ?? [])
      .map((entity) => {
        const { id, label, ...extra } = entity;
        return { id: String(id ?? ''), label: typeof label === 'string' ? label : '', extra };
      })
      .filter((row) => row.id)
      .filter((row) => !needle || row.id.toLowerCase().includes(needle) || row.label.toLowerCase().includes(needle));
  }, [entities.data, query]);

  const columns = useMemo<Column<Row>[]>(() => {
    const extraKeys = [...new Set(rows.flatMap((row) => Object.keys(row.extra)))];
    return [
      { key: 'id', header: 'ID', value: (row) => row.id, mono: true, sortable: true },
      ...extraKeys.map<Column<Row>>((key) => ({ key, header: humanize(key), value: (row) => row.extra[key], render: (row) => String(row.extra[key] ?? '—'), sortable: true })),
      {
        key: 'actions',
        header: 'Open in',
        value: () => '',
        align: 'right',
        render: (row) => (
          <span className={styles.rowActions} onClick={(event) => event.stopPropagation()}>
            <LinkButton size="sm" variant="ghost" icon={<Route size={14} />} to={`/trace?type=${encodeURIComponent(type ?? '')}&id=${encodeURIComponent(row.id)}`}>
              Trace
            </LinkButton>
            <LinkButton size="sm" variant="ghost" icon={<Network size={14} />} to={`/explore?focus=${encodeURIComponent(makeRecordId(type ?? '', row.id))}`}>
              Explore
            </LinkButton>
          </span>
        ),
      },
    ];
  }, [rows, type]);

  if (isEmpty) {
    return (
      <Page title="Records" subtitle="Browse the records in your data, one type at a time.">
        <LoadDataEmpty />
      </Page>
    );
  }

  // No type chosen: go to the first one that has records.
  if (!type && status === 'ready' && schema.nodeTypes.length > 0) {
    const first = [...headlineTypes, ...otherTypes].find((candidate) => (countFor(candidate.key) ?? 0) > 0) ?? schema.nodeTypes[0];
    return <Navigate to={`/records/${encodeURIComponent(first.key)}`} replace />;
  }

  const total = type ? countFor(type) : undefined;
  const typeLink = (key: string) => {
    const info = getTypeMeta(key);
    const count = countFor(key);
    return (
      <NavLink key={key} to={`/records/${encodeURIComponent(key)}`} className={styles.typeLink} onClick={() => { setOpenId(null); setQuery(''); }}>
        <TypeDot type={key} />
        <span className={styles.typeName}>{info.plural}</span>
        {count !== undefined && <span className={styles.typeCount}>{formatCompact(count)}</span>}
      </NavLink>
    );
  };

  return (
    <Page title="Records" subtitle="Browse the records in your data, one type at a time. Select a row for its details.">
      <div className={styles.layout}>
        <nav className={styles.types} aria-label="Record types">
          {status === 'loading' && Array.from({ length: 7 }, (_, index) => <Skeleton key={index} height={32} />)}
          {status === 'ready' && (
            <>
              {headlineTypes.length > 0 && <div className={styles.groupLabel}>{headlineTypes.some((t) => t.isPrimary) ? 'Main records' : 'Largest'}</div>}
              {headlineTypes.map((info) => typeLink(info.key))}
              {otherTypes.length > 0 && <div className={styles.groupLabel}>Supporting records</div>}
              {otherTypes.map((info) => typeLink(info.key))}
            </>
          )}
        </nav>

        <section className={styles.main} aria-label={meta ? `${meta.plural} table` : 'Records'}>
          <div className={styles.typePicker}>
            <Select label="Record type" value={type ?? ''} onChange={(event) => navigate(`/records/${encodeURIComponent(event.target.value)}`)}>
              {schema.nodeTypes.map((info) => (
                <option key={info.key} value={info.key}>{info.plural}</option>
              ))}
            </Select>
          </div>

          {meta && (
            <div className={styles.mainHeader}>
              <div>
                <h2 className={styles.mainTitle}>
                  <TypeDot type={meta.key} size={12} />
                  {meta.plural}
                  {total !== undefined && <span className={styles.typeCount}>· {formatInteger(total)}</span>}
                </h2>
                {meta.description && <p className={styles.mainDescription}>{meta.description}</p>}
              </div>
              <div className={styles.tools}>
                <div className={styles.search}>
                  <SearchInput label="Filter by ID" hideLabel placeholder="Filter by ID…" value={query} mono onChange={(event) => setQuery(event.target.value)} onClear={() => setQuery('')} />
                </div>
                <Select label="Sample size" hideLabel value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
                  {LIMITS.map((n) => (
                    <option key={n} value={n}>Show {n}</option>
                  ))}
                </Select>
              </div>
            </div>
          )}

          {entities.isPending && Boolean(type) && (
            <div className={styles.skeletonRows} role="status" aria-label="Loading records" aria-busy="true">
              {Array.from({ length: 8 }, (_, index) => <Skeleton key={index} height={20} width={`${92 - index * 4}%`} />)}
            </div>
          )}
          {entities.isError && <ErrorState title="Records didn’t load" error={entities.error} onRetry={() => void entities.refetch()} retrying={entities.isFetching} />}
          {entities.isSuccess && rows.length === 0 && (
            <EmptyState
              icon={<Rows3 size={22} />}
              title={query ? 'No records match that filter' : `No ${meta ? meta.plural.toLowerCase() : 'records'} yet`}
              description={query ? 'Try a shorter ID, or clear the filter. The table only filters the sample shown here. Use search to look up any record by its ID.' : 'There are no records of this type in the loaded data.'}
            />
          )}
          {entities.isSuccess && rows.length > 0 && meta && (
            <>
              <DataTable
                caption={`${meta.plural}, sample of ${rows.length}`}
                columns={columns}
                rows={rows}
                rowKey={(row) => row.id}
                selectedKey={openId}
                onRowClick={(row) => setOpenId(row.id)}
                rowLabel={(row) => `${meta.label} ${row.id}, open details`}
                initialSort={{ key: 'id', direction: 'asc' }}
              />
              <p className={styles.note}>
                Showing {formatInteger(rows.length)} {pluralize(rows.length, 'record')}
                {total !== undefined && total > rows.length ? ` from a sample of the ${formatInteger(total)} in the data` : ''}. To find a specific record, search by its ID with the search shortcut.
              </p>
            </>
          )}
        </section>
      </div>

      {openId && type && (
        <RecordInspector
          key={openId}
          placement="overlay"
          recordId={makeRecordId(type, openId)}
          showExploreAction
          onClose={() => setOpenId(null)}
          onOpenRecord={(recordId) => navigate(`/explore?focus=${encodeURIComponent(recordId)}`)}
          onAsk={(prompt) => navigate(`/ask?q=${encodeURIComponent(prompt)}`)}
        />
      )}
    </Page>
  );
}
