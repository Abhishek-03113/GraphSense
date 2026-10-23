import { RotateCcw } from 'lucide-react';
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Page } from '../../app/Page';
import { Button } from '../../components/ui/Button';
import { useSchema } from '../../lib/schema';
import { useAsk } from '../../store/ask';
import { Conversation } from './Conversation';

export default function AskPage() {
  const { schema, status } = useSchema();
  const turns = useAsk((s) => s.turns);
  const reset = useAsk((s) => s.reset);
  const setDraft = useAsk((s) => s.setDraft);
  const [params, setParams] = useSearchParams();

  // Arrive with a prefilled question, e.g. from "Ask about this".
  const prefill = params.get('q');
  useEffect(() => {
    if (prefill) {
      setDraft(prefill);
      setParams({}, { replace: true });
    }
  }, [prefill, setDraft, setParams]);

  const subject = status === 'ready' && !schema.domain.isDefault ? schema.domain.name.toLowerCase() : 'your data';

  return (
    <Page
      title="Ask"
      subtitle={`Ask questions about ${subject} in plain language.`}
      flush
      actions={
        <Button icon={<RotateCcw size={16} />} disabled={turns.length === 0} onClick={reset}>
          New conversation
        </Button>
      }
    >
      <Conversation />
    </Page>
  );
}
