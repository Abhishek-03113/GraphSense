import { Compass } from 'lucide-react';
import { LinkButton } from '../components/ui/Button';
import { EmptyState } from '../components/ui/EmptyState';
import { Page } from './Page';

export function NotFound() {
  return (
    <Page title="Page not found">
      <EmptyState
        icon={<Compass size={22} />}
        title="There’s nothing at this address"
        description="The link may be out of date or mistyped. Head back to the overview to pick up from there."
        actions={<LinkButton variant="primary" to="/">Go to overview</LinkButton>}
      />
    </Page>
  );
}
