import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { lazy, useState } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { ApiError } from '../lib/api/client';
import { SchemaProvider } from '../lib/schema';
import { NotFound } from './NotFound';
import { Shell } from './Shell';

// Pages that draw graphs are split out so the first screen stays light.
const OverviewPage = lazy(() => import('../features/overview/OverviewPage'));
const ExplorePage = lazy(() => import('../features/explore/ExplorePage'));
const AskPage = lazy(() => import('../features/ask/AskPage'));
const FlowsPage = lazy(() => import('../features/flows/FlowsPage'));
const FlowDetailPage = lazy(() => import('../features/flows/FlowDetailPage'));
const TracePage = lazy(() => import('../features/trace/TracePage'));
const RecordsPage = lazy(() => import('../features/records/RecordsPage'));

export function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // A 4xx answer will not change on a second try (a dataset that is not loaded, an unknown record).
            retry: (failureCount, error) =>
              !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failureCount < 1,
            refetchOnWindowFocus: false,
            staleTime: 30_000,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <SchemaProvider>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<OverviewPage />} />
              <Route path="explore" element={<ExplorePage />} />
              <Route path="ask" element={<AskPage />} />
              <Route path="flows" element={<FlowsPage />} />
              <Route path="flows/:flowId" element={<FlowDetailPage />} />
              <Route path="trace" element={<TracePage />} />
              <Route path="records/:type?" element={<RecordsPage />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </SchemaProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
