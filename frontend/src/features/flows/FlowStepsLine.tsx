import { ArrowRight } from 'lucide-react';
import { TypeDot } from '../../components/ui/TypeBadge';
import { useSchema, type FlowMeta } from '../../lib/schema';
import styles from './Flows.module.css';

export function FlowStepsLine({ flow }: { flow: FlowMeta }) {
  const { typeLabel } = useSchema();
  const order = flow.nodeTypes;
  return (
    <div className={styles.steps} aria-label={`Steps: ${order.map((t) => typeLabel(t)).join(', then ')}`}>
      {order.map((type, index) => (
        <span key={type} className={styles.step}>
          {index > 0 && <ArrowRight size={12} className={styles.arrow} aria-hidden="true" />}
          <TypeDot type={type} size={8} />
          {typeLabel(type)}
        </span>
      ))}
    </div>
  );
}
