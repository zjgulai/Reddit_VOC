import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Search,
  BarChart3,
  Zap,
  MessageSquare,
  Archive,
  Settings,
  LogOut,
  ChevronRight,
  ChevronLeft,
  FileText,
  Globe,
  Lightbulb,
} from 'lucide-react';
import { getStorage, setStorage } from '../utils/storage';
import CollectorBackendLink from './CollectorBackendLink';

const menuItems = [
  { path: '/dashboard', icon: LayoutDashboard, label: '概览' },
  { path: '/dashboard/reports', icon: FileText, label: '报告' },
  { path: '/dashboard/search', icon: Search, label: '搜索' },
  { path: '/dashboard/agent-studio', icon: Zap, label: 'Agent 工作室' },
  { path: '/dashboard/analytics', icon: BarChart3, label: '分析' },
  { path: '/dashboard/insights', icon: Lightbulb, label: '洞察' },
  { path: '/cases', icon: Globe, label: '案例广场' },
  { path: '/dashboard/ugc-showcase', icon: Archive, label: '高价值内容' },
  { path: '/dashboard/messages', icon: MessageSquare, label: '舆情信号' },
];

const bottomItems = [
  { path: '/dashboard/settings', icon: Settings, label: '指标口径' },
];

const MOBILE_SIDEBAR_QUERY = '(max-width: 639px)';

function isMobileSidebarViewport(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(MOBILE_SIDEBAR_QUERY).matches;
}

export default function Sidebar() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => {
    return getStorage('sidebar-collapsed', 1, false);
  });
  const [isMobileViewport, setIsMobileViewport] = useState(isMobileSidebarViewport);
  const visuallyCollapsed = isMobileViewport || collapsed;

  useEffect(() => {
    setStorage('sidebar-collapsed', 1, collapsed);
  }, [collapsed]);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;

    const mediaQuery = window.matchMedia(MOBILE_SIDEBAR_QUERY);
    const syncViewport = () => setIsMobileViewport(mediaQuery.matches);
    syncViewport();
    mediaQuery.addEventListener('change', syncViewport);
    return () => mediaQuery.removeEventListener('change', syncViewport);
  }, []);

  const isActive = (itemPath: string) => {
    // 根路径（如 /dashboard）精确匹配，避免 /dashboard/search 误激活
    if (itemPath === '/dashboard') {
      return location.pathname === '/dashboard' || location.pathname === '/dashboard/';
    }
    return location.pathname === itemPath || location.pathname.startsWith(itemPath + '/');
  };

  return (
    <aside
      className={`${
        visuallyCollapsed ? 'w-[64px]' : 'w-[240px]'
      } h-screen shrink-0 overflow-x-hidden bg-surface border-r border-border-divider flex flex-col sticky top-0 transition-all duration-300`}
    >
      {/* Logo */}
      <div
        className={`relative flex items-center ${
          visuallyCollapsed ? 'justify-center px-2' : 'justify-between px-6'
        } py-5 transition-all duration-300`}
      >
        <Link
          to="/"
          aria-label={visuallyCollapsed ? 'Momcozy 首页' : undefined}
          className={`flex items-center ${visuallyCollapsed ? 'justify-center' : 'gap-2.5'}`}
        >
          <div className="w-7 h-7 rounded-icon bg-primary flex items-center justify-center shrink-0">
            <MessageSquare className="w-4 h-4 text-white" strokeWidth={1.5} />
          </div>
          {!visuallyCollapsed && (
            <div className="leading-tight">
              <span className="text-[15px] font-semibold text-foreground tracking-tight block">
                Momcozy
              </span>
              <span className="text-tiny text-foreground-muted">Reddit 舆情工作台</span>
            </div>
          )}
        </Link>
        {!visuallyCollapsed ? (
          <button
            onClick={() => setCollapsed(true)}
            className="p-1 rounded-md text-foreground-muted hover:bg-surface-tertiary hover:text-foreground transition-all duration-300"
            aria-label="收起侧边栏"
          >
            <ChevronLeft className="w-4 h-4" strokeWidth={1.5} />
          </button>
        ) : !isMobileViewport ? (
          <button
            onClick={() => setCollapsed(false)}
            className="absolute right-1 top-1/2 -translate-y-1/2 w-5 h-5 rounded-full bg-primary text-white shadow-md flex items-center justify-center hover:scale-110 transition-all duration-300"
            aria-label="展开侧边栏"
            title="展开侧边栏"
          >
            <ChevronRight className="w-3 h-3" strokeWidth={2} />
          </button>
        ) : null}
      </div>

      {/* Main Menu */}
      <nav className={`flex-1 ${visuallyCollapsed ? 'px-2' : 'px-3'} space-y-0.5 transition-all duration-300`}>
        {!visuallyCollapsed && (
          <p className="px-3 text-tiny font-medium text-foreground-muted uppercase tracking-wider mb-3 mt-2">
            工作台
          </p>
        )}
        {menuItems.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              aria-current={active ? 'page' : undefined}
              aria-label={visuallyCollapsed ? item.label : undefined}
              title={visuallyCollapsed ? item.label : undefined}
              className={`flex items-center ${
                visuallyCollapsed ? 'justify-center px-2' : 'gap-3 px-3'
              } py-2.5 rounded-icon text-body-sm font-medium transition-all duration-300 ${
                active
                  ? 'bg-primary-light text-primary'
                  : 'text-foreground-secondary hover:bg-surface-tertiary hover:text-foreground'
              }`}
            >
              <Icon className="w-[18px] h-[18px] shrink-0" strokeWidth={1.5} />
              {!visuallyCollapsed && <span>{item.label}</span>}
              {!visuallyCollapsed && active && (
                <ChevronRight className="w-4 h-4 ml-auto" strokeWidth={1.5} />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Bottom */}
      <div
        className={`${
          visuallyCollapsed ? 'px-2 py-3' : 'p-3'
        } border-t border-border-divider space-y-0.5 transition-all duration-300`}
      >
        <CollectorBackendLink placement="sidebar" collapsed={visuallyCollapsed} />
        {bottomItems.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              aria-current={active ? 'page' : undefined}
              aria-label={visuallyCollapsed ? item.label : undefined}
              title={visuallyCollapsed ? item.label : undefined}
              className={`flex items-center ${
                visuallyCollapsed ? 'justify-center px-2' : 'gap-3 px-3'
              } py-2.5 rounded-icon text-body-sm font-medium transition-all duration-300 ${
                active
                  ? 'bg-primary-light text-primary'
                  : 'text-foreground-secondary hover:bg-surface-tertiary hover:text-foreground'
              }`}
            >
              <Icon className="w-[18px] h-[18px] shrink-0" strokeWidth={1.5} />
              {!visuallyCollapsed && <span>{item.label}</span>}
            </Link>
          );
        })}
        <Link
          to="/"
          aria-label={visuallyCollapsed ? '返回首页' : undefined}
          title={visuallyCollapsed ? '返回首页' : undefined}
          className={`flex items-center ${
            visuallyCollapsed ? 'justify-center px-2' : 'gap-3 px-3'
          } py-2.5 rounded-icon text-body-sm font-medium text-foreground-secondary hover:bg-surface-tertiary hover:text-foreground transition-all duration-300 w-full`}
        >
          <LogOut className="w-[18px] h-[18px] shrink-0" strokeWidth={1.5} />
          {!visuallyCollapsed && <span>返回首页</span>}
        </Link>

        {/* Collapse / Expand Toggle */}
        {!isMobileViewport && (
          <button
            onClick={() => setCollapsed((c) => !c)}
            className={`flex items-center ${
              visuallyCollapsed ? 'justify-center px-2' : 'gap-3 px-3'
            } py-2.5 rounded-icon text-body-sm font-medium transition-all duration-300 w-full ${
              visuallyCollapsed
                ? 'bg-primary text-white shadow-md hover:bg-primary-hover hover:shadow-lg'
                : 'text-foreground-secondary hover:bg-surface-tertiary hover:text-foreground'
            }`}
            aria-label={visuallyCollapsed ? '展开侧边栏' : '收起侧边栏'}
            title={visuallyCollapsed ? '展开侧边栏' : '收起侧边栏'}
          >
            {visuallyCollapsed ? (
              <ChevronRight className="w-[18px] h-[18px] shrink-0" strokeWidth={1.5} />
            ) : (
              <>
                <ChevronLeft className="w-[18px] h-[18px] shrink-0" strokeWidth={1.5} />
                <span>收起侧边栏</span>
              </>
            )}
          </button>
        )}
      </div>
    </aside>
  );
}
