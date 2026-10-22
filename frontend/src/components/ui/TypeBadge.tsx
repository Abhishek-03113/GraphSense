import { useSchema } from '../../lib/schema';
import { Badge } from './Badge';

/** A record type as a small coloured-dot badge. Label and colour come from the dataset schema. */
export function TypeBadge({ type, plural }: { type: string; plural?: boolean }) {
  const { getTypeMeta, colorForType } = useSchema();
  const meta = getTypeMeta(type);
  return (
    <Badge dotColor={colorForType(type)} title={meta.description || undefined}>
      {plural ? meta.plural : meta.label}
    </Badge>
  );
}

/** Just the swatch, for dense lists where the label sits next to it. */
export function TypeDot({ type, size = 10 }: { type: string; size?: number }) {
  const { colorForType } = useSchema();
  return (
    <span
      aria-hidden="true"
      style={{
        display: 'inline-block',
        flex: 'none',
        width: size,
        height: size,
        borderRadius: '999px',
        background: colorForType(type),
      }}
    />
  );
}
