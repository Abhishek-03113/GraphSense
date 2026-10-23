import { Network, Route, Rows3 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Navigate, NavLink, useNavigate, useParams } from 'react-router-dom';
import { Page } from '../../app/Page';
import { IconLinkButton } from '../../components/ui/Button';
import { EmptyState, ErrorState } from '../../components/ui/EmptyState';
import { SearchInput, Select } from '../../components/ui/Field';
import { Skeleton } from '../../components/ui/Skeleton';
import { DataTable, type Column } from '../../components/ui/Table';
import { TypeDot } from '../../components/ui/TypeBadge';
import { useEntities } from '../../lib/api/queries';
import { currencyFor, formatCompact, formatInteger, formatValue, humanize, makeRecordId, pluralize } from '../../lib/format';
import { naturalLabel } from '../../lib/graph';
import { useSchema } from '../../lib/schema';
import { RecordInspector } from '../inspector/RecordInspector';
import { LoadDataEmpty } from '../onboarding/LoadDataEmpty';
import styles from './Records.module.css';

interface Row {
  id: string;
  /** A human name for the record, when the server has one. */
  name: string | null;
  extra: Record<string, unknown>;
}

const isBlank = (value: unknown) => value === null || value === undefined || value === '';

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

  const allRows = useMemo<Row[]>(
    () =>
      (entities.data?.entities ?? [])
        .map((entity) => {
          const { id, label, ...extra } = entity;
          const value = String(id ?? '');
          return { id: value, name: naturalLabel(type ?? '', value, typeof label === 'string' ? label : null), extra };
        })
        .filter((row) => row.id),
    [entities.data, type],
  );

  const rows = useMemo<Row[]>(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return allRows;
    return allRows.filter((row) =>
      [row.id, row.name, ...Object.values(row.extra)].some((part) => !isBlank(part) && typeof part !== 'object' && String(part).toLowerCase().includes(needle)),
    );
  }, [allRows, query]);

  const hasNames = allRows.some((row) => row.name);

  const columns = useMemo<Column<Row>[]>(() => {
    // Columns that have a value in at least one row, in the order the server listed them.
    const extraKeys = [...new Set(allRows.flatMap((row) => Object.keys(row.extra)))].filter((key) => allRows.some((row) => !isBlank(row.extra[key])));
    // A separate name column only when no listed column already carries the same text.
    const nameRepeated = extraKeys.some((key) => allRows.every((row) => !row.name || row.extra[key] === row.name));
    const cell = (key: string, row: Row) => formatValue(key, row.extra[key], { currency: currencyFor(key, row.extra) });
    return [
      { key: 'id', header: 'ID', value: (row) => row.id, mono: true, sortable: true },
      ...(hasNames && !nameRepeated
        ? [{ key: '_name', header: 'Name', value: (row: Row) => row.name ?? '', render: (row: Row) => row.name ?? '—', sortable: true } satisfies Column<Row>]
        : []),
      ...extraKeys.map<Column<Row>>((key) => {
        const shown = allRows.slice(0, 25).map((row) => cell(key, row)).filter((formatted) => formatted.kind !== 'empty');
        const numeric = shown.length > 0 && shown.every((formatted) => formatted.numeric);
        const mono = shown.length > 0 && shown.every((formatted) => formatted.mono);
        return {
          key,
          header: humanize(key),
          value: (row) => row.extra[key],
          render: (row) => cell(key, row).text,
          sortable: true,
          align: numeric ? 'right' : 'left',
          numeric,
          mono,
        };
      }),
      {
        key: 'actions',
        header: 'Open',
        value: () => '',
        align: 'right',
        sticky: 'right',
        render: (row) => (
          <span className={styles.rowActions} onClick={(event) => event.stopPropagation()}>
            <IconLinkButton size="sm" label="Trace lifecycle" icon={<Route size={16} />} to={`/trace?type=${encodeURIComponent(type ?? '')}&id=${encodeURIComponent(row.id)}`} />
            <IconLinkButton size="sm" label="Show in Explore" icon={<Network size={16} />} to={`/explore?focus=${encodeURIComponent(makeRecordId(type ?? '', row.id))}`} />
          </span>
        ),
      },
    ];
  }, [allRows, hasNames, type]);

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
                  <SearchInput label="Filter records" hideLabel placeholder="Filter this sample…" value={query} onChange={(event) => setQuery(event.target.value)} onClear={() => setQuery('')} />
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
              description={query ? 'Try a shorter search, or clear the filter. The table only filters the sample shown here. Use search to look up any record by its ID.' : 'There are no records of this type in the loaded data.'}
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
