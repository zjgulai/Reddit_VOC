import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import type { ReactElement } from 'react';
import ErrorBoundary from './components/ErrorBoundary';

// 同步加载首屏页面（Home 和真实数据 Dashboard 为高频入口）
import Home from './pages/Home';
import Dashboard from './pages/SnapshotDashboard';

// 懒加载其他页面，减少首屏 bundle
const Analytics = lazy(() => import('./pages/SnapshotAnalytics'));
const Insights = lazy(() => import('./pages/SnapshotInsights'));
const Reports = lazy(() => import('./pages/SnapshotReports'));
const Search = lazy(() => import('./pages/SnapshotSearch'));
const SnapshotWorkspace = lazy(() => import('./pages/SnapshotWorkspace'));
const CaseGallery = lazy(() => import('./pages/CaseGallery'));
const Features = lazy(() => import('./pages/Features'));
const HowItWorks = lazy(() => import('./pages/HowItWorks'));
const FAQ = lazy(() => import('./pages/FAQ'));
const NotFound = lazy(() => import('./pages/NotFound'));

type PageRouteDefinition = {
  path: string;
  kind: 'page';
  element: ReactElement;
};

type SnapshotWorkspaceRouteDefinition = {
  path: string;
  kind: 'snapshot-workspace';
  workspace: 'content' | 'signals' | 'definitions';
  element: ReactElement;
};

export type ProductionRouteDefinition =
  | PageRouteDefinition
  | SnapshotWorkspaceRouteDefinition;

// oxlint-disable-next-line react/only-export-components -- production route source contract is consumed by App below
export const PRODUCTION_ROUTE_DEFINITIONS = [
  { path: '/', kind: 'page', element: <Home /> },
  { path: '/dashboard', kind: 'page', element: <Dashboard /> },
  { path: '/dashboard/reports', kind: 'page', element: <Reports /> },
  { path: '/dashboard/analytics', kind: 'page', element: <Analytics /> },
  { path: '/dashboard/insights', kind: 'page', element: <Insights /> },
  { path: '/dashboard/search', kind: 'page', element: <Search /> },
  {
    path: '/dashboard/ugc-showcase',
    kind: 'snapshot-workspace',
    workspace: 'content',
    element: <SnapshotWorkspace workspace="content" />,
  },
  {
    path: '/dashboard/messages',
    kind: 'snapshot-workspace',
    workspace: 'signals',
    element: <SnapshotWorkspace workspace="signals" />,
  },
  {
    path: '/dashboard/settings',
    kind: 'snapshot-workspace',
    workspace: 'definitions',
    element: <SnapshotWorkspace workspace="definitions" />,
  },
  { path: '/features', kind: 'page', element: <Features /> },
  { path: '/how-it-works', kind: 'page', element: <HowItWorks /> },
  { path: '/faq', kind: 'page', element: <FAQ /> },
  { path: '/cases', kind: 'page', element: <CaseGallery /> },
] satisfies readonly ProductionRouteDefinition[];

// oxlint-disable-next-line react/only-export-components -- wildcard stays explicit and separate from production paths
export const NOT_FOUND_ROUTE_DEFINITION = {
  path: '*',
  element: <NotFound />,
} as const;

/** 骨架屏 Loading */
function PageSkeleton() {
  return (
    <div className="min-h-screen bg-surface-tertiary flex items-center justify-center">
      <div className="flex items-center gap-3">
        <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <span className="text-body text-foreground-secondary">加载中...</span>
      </div>
    </div>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Suspense fallback={<PageSkeleton />}>
          <Routes>
            {PRODUCTION_ROUTE_DEFINITIONS.map((route) => (
              <Route key={route.path} path={route.path} element={route.element} />
            ))}
            <Route
              path={NOT_FOUND_ROUTE_DEFINITION.path}
              element={NOT_FOUND_ROUTE_DEFINITION.element}
            />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
