import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  AlertTriangle,
  Archive,
  BarChart3,
  Database,
  FileText,
  Globe,
  LayoutDashboard,
  Lightbulb,
  LoaderCircle,
  MessageSquare,
  MoreHorizontal,
  Search,
  Settings,
} from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import CollectorBackendLink from '../../components/CollectorBackendLink';
import Sidebar from '../../components/Sidebar';
import DataFreshnessBar from './DataFreshnessBar';
import type { DataFreshnessEvidence } from './freshness';

const mobileNavigation = [
  { path: '/dashboard', label: '概览', icon: LayoutDashboard },
  { path: '/dashboard/reports', label: '报告', icon: FileText },
  { path: '/dashboard/search', label: '搜索', icon: Search },
  { path: '/dashboard/analytics', label: '分析', icon: BarChart3 },
  { path: '/dashboard/insights', label: '洞察', icon: Lightbulb },
];

const mobileMoreNavigation = [
  { path: '/cases', label: '案例广场', icon: Globe },
  { path: '/dashboard/ugc-showcase', label: '高价值内容', icon: Archive },
  { path: '/dashboard/messages', label: '舆情信号', icon: MessageSquare },
  { path: '/dashboard/settings', label: '指标口径', icon: Settings },
];

interface SnapshotPageLayoutProps {
  icon: LucideIcon;
  title: string;
  description: string;
  datasetVersion?: string;
  freshness?: DataFreshnessEvidence;
  captureMode?: boolean;
  children: ReactNode;
}

export function SnapshotPageLayout({
  icon: Icon,
  title,
  description,
  datasetVersion,
  freshness,
  captureMode = false,
  children,
}: SnapshotPageLayoutProps) {
  const location = useLocation();

  if (captureMode) {
    return (
      <div className="min-h-screen bg-white" data-snapshot-capture-layout="poster">
        <main className="w-full">
          <div className="w-full">{children}</div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-surface-tertiary">
      <div className="hidden md:block">
        <Sidebar />
      </div>
      <main className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 border-b border-border-divider/60 bg-white/90 backdrop-blur-xl">
          <div className="mx-auto flex w-full max-w-container flex-wrap items-center justify-between gap-3 px-4 py-3.5 sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-icon bg-primary-light">
                <Icon className="h-[18px] w-[18px] text-primary" strokeWidth={1.5} />
              </div>
              <div className="min-w-0">
                <h1 className="text-body font-semibold text-foreground">{title}</h1>
                <p className="text-tiny text-foreground-muted">{description}</p>
              </div>
            </div>
            <div className="flex max-w-full flex-wrap items-center justify-end gap-2">
              <CollectorBackendLink placement="header" />
              {datasetVersion && (
                <div
                  className="inline-flex max-w-full items-center gap-2 rounded-badge border border-status-success/20 bg-status-successBg px-3 py-1.5 text-tiny font-medium text-status-success"
                  title="当前页面使用的发布版本已通过完整性校验；数据时效请查看下方状态条"
                >
                  <Database className="h-3.5 w-3.5 shrink-0" strokeWidth={1.5} />
                  <span className="truncate">版本完整性 · 已验证</span>
                </div>
              )}
            </div>
          </div>
          <nav aria-label="移动端工作台导航" className="mx-auto grid w-full max-w-container grid-cols-6 gap-1 px-4 pb-3 md:hidden">
            {mobileNavigation.map((item) => {
              const NavIcon = item.icon;
              const active =
                item.path === '/dashboard'
                  ? location.pathname === '/dashboard' || location.pathname === '/dashboard/'
                  : location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);

              return (
                <Link
                  key={item.path}
                  to={item.path}
                  aria-current={active ? 'page' : undefined}
                  className={`flex items-center justify-center gap-1 rounded-icon px-1 py-2 text-caption font-medium transition-colors ${
                    active
                      ? 'bg-primary-light text-primary'
                      : 'text-foreground-secondary hover:bg-surface-tertiary hover:text-foreground'
                  }`}
                >
                  <NavIcon className="h-4 w-4" strokeWidth={1.5} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
            <details className="group relative">
              <summary
                className={`flex h-full cursor-pointer list-none items-center justify-center gap-1 rounded-icon px-1 py-2 text-caption font-medium transition-colors [&::-webkit-details-marker]:hidden ${
                  mobileMoreNavigation.some((item) =>
                    location.pathname === item.path || location.pathname.startsWith(`${item.path}/`),
                  )
                    ? 'bg-primary-light text-primary'
                    : 'text-foreground-secondary hover:bg-surface-tertiary hover:text-foreground'
                }`}
                aria-label="更多工作台入口"
              >
                <MoreHorizontal className="h-4 w-4" strokeWidth={1.5} />
                <span>更多</span>
              </summary>
              <div className="overlay absolute right-0 top-[calc(100%+0.5rem)] z-50 w-48 p-2">
                {mobileMoreNavigation.map((item) => {
                  const MoreIcon = item.icon;
                  const active =
                    location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);
                  return (
                    <Link
                      key={item.path}
                      to={item.path}
                      aria-current={active ? 'page' : undefined}
                      className={`flex min-h-11 items-center gap-3 rounded-icon px-3 text-body-sm font-medium ${
                        active
                          ? 'bg-primary-light text-primary'
                          : 'text-foreground-secondary hover:bg-surface-tertiary hover:text-foreground'
                      }`}
                    >
                      <MoreIcon className="h-4 w-4" strokeWidth={1.5} />
                      <span>{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </details>
          </nav>
        </header>
        <div className="mx-auto w-full max-w-container space-y-6 p-4 sm:p-6">
          {freshness ? <DataFreshnessBar evidence={freshness} /> : null}
          {children}
        </div>
      </main>
    </div>
  );
}

export function SnapshotLoadingPage({ icon, title }: Pick<SnapshotPageLayoutProps, 'icon' | 'title'>) {
  return (
    <SnapshotPageLayout icon={icon} title={title} description="正在校验并加载版本化真实数据快照">
      <div className="card flex min-h-64 flex-col items-center justify-center gap-3 p-8 text-center">
        <LoaderCircle className="h-7 w-7 animate-spin text-primary" strokeWidth={1.5} />
        <div>
          <p className="text-body-sm font-medium text-foreground">加载真实数据</p>
          <p className="mt-1 text-caption text-foreground-muted">不会回退到 Mock 数据</p>
        </div>
      </div>
    </SnapshotPageLayout>
  );
}

export function SnapshotErrorPage({
  icon,
  title,
  error,
}: Pick<SnapshotPageLayoutProps, 'icon' | 'title'> & { error: string }) {
  return (
    <SnapshotPageLayout icon={icon} title={title} description="真实数据激活失败">
      <div className="card border border-status-error/20 p-8" data-ui-severity="error">
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-icon bg-status-errorBg">
            <AlertTriangle className="h-5 w-5 text-status-error" strokeWidth={1.5} />
          </div>
          <div>
            <h2 className="text-h3 text-foreground">真实数据不可用，页面已停止渲染指标</h2>
            <p className="mt-2 text-body-sm text-status-error">{error}</p>
            <p className="mt-3 text-caption text-foreground-muted">
              请检查公开数据目录中的版本化快照及版本清单；系统不会静默展示演示数据。
            </p>
          </div>
        </div>
      </div>
    </SnapshotPageLayout>
  );
}
