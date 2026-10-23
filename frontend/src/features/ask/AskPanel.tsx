import { Sheet } from '../../components/ui/Sheet';
import { Conversation } from './Conversation';
import type { RecordRef } from '../../store/ask';

interface AskPanelProps {
  onClose: () => void;
  onOpenRecord: (focus: RecordRef, all: RecordRef[]) => void;
}

/** The conversational analyst as a side panel, for asking while looking at the graph. */
export function AskPanel({ onClose, onOpenRecord }: AskPanelProps) {
  return (
    <Sheet label="Ask a question" title="Ask" subtitle={<span style={{ color: 'var(--gs-color-label-secondary)', fontSize: 'var(--gs-fs-small)' }}>Answers can light up records on the graph.</span>} onClose={onClose} fill>
      <Conversation compact onOpenRecord={onOpenRecord} />
    </Sheet>
  );
}
