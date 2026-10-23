import { BrainCircuit, PowerOff } from 'lucide-react';
import { useSchema } from '../../lib/schema';
import { Notice } from './Notice';

/**
 * What the dataset's AI state means for asking questions, said once at the top of the conversation.
 * Nothing is shown when everything works or when the server does not report a state.
 */
export function AiNotice() {
  const { ai, datasetPhase } = useSchema();
  if (ai.mode === 'disabled') {
    return (
      <Notice tone="warn" icon={<PowerOff size={18} />} title="Ask isn’t switched on for this workspace">
        Answering questions needs a language service that hasn’t been connected to this server. Your administrator can set it up. Everything else (records, relationships, flows and trace) works as usual.
      </Notice>
    );
  }
  if (ai.mode === 'degraded') {
    return (
      <Notice icon={<BrainCircuit size={18} />} title="Ask is running in a simpler mode">
        Smart matching of your question to the data isn’t available right now, so answers may be less precise. Checking important figures against the rows shown is a good habit.
      </Notice>
    );
  }
  if (ai.mode === 'full' && ai.knowledge === 'missing' && datasetPhase === 'ready') {
    return (
      <Notice icon={<BrainCircuit size={18} />} title="Ask is still getting to know this data">
        The notes Ask uses to understand your data haven’t been prepared yet, so answers may be less accurate for now. Your administrator can refresh them.
      </Notice>
    );
  }
  return null;
}
