import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Search, Bell, MessageSquare, AlertTriangle, CheckSquare, Lightbulb, Settings,
  Check, Clock, ToggleLeft, ToggleRight, Mail, Smartphone, Send,
  Inbox, FileText, ArrowUpRight, Flame, Shield, ChevronLeft, ChevronRight, Loader2,
  BarChart3, Tag,
} from 'lucide-react';
import Sidebar from '../components/Sidebar';
import SectionCard from '../components/SectionCard';
import PostDetailDrawer from '../components/PostDetailDrawer';
import ExportButton from '../components/ExportButton';
import { SankeyChart, WordCloudChart } from '../components/charts';
import { usePagination, useSearch, useUrlParams, useFavorites } from '../hooks';
import { useNotificationStore } from '../stores';
import { getNotifications, getNotificationRules, typeConfig, severityConfig, getPostFromNotification, messageSankeyNodes, messageSankeyLinks, messageWordCloudData } from '../services/messageService';
import type { Notification, NotificationRule } from '../services/messageService';
import type { DailyNewPost } from '../data/dailyReportMock';
import type { NotificationItem } from '../types';

const NOTIFICATION_RULES_KEY = 'momcozy_notification_rules';

function loadNotificationRules(defaultRules: NotificationRule[]): NotificationRule[] {
  try {
    const raw = localStorage.getItem(NOTIFICATION_RULES_KEY);
    if (!raw) return defaultRules;
    const parsed = JSON.parse(raw) as NotificationRule[];
    if (!Array.isArray(parsed) || parsed.length === 0) return defaultRules;
    const storedMap = new Map(parsed.map((r) => [r.id, r]));
    return defaultRules.map((r) => ({
      ...r,
      enabled: storedMap.has(r.id) ? storedMap.get(r.id)!.enabled : r.enabled,
    }));
  } catch {
    return defaultRules;
  }
}

function saveNotificationRules(rules: NotificationRule[]) {
  localStorage.setItem(NOTIFICATION_RULES_KEY, JSON.stringify(rules));
}

type FilterType = 'all' | 'alert' | 'task' | 'insight' | 'system' | 'unread';

const filterLabels: Record<FilterType, string> = {
  all: '全部',
  alert: '警报',
  task: '任务',
  insight: '洞察',
  system: '系统',
  unread: '未读',
};

const channelIcons: Record<string, typeof Mail> = {
  app: Smartphone,
  email: Mail,
  feishu: Send,
};

export default function Messages() {
  const { getParam, setParam } = useUrlParams();
  const now = new Date();
  const [lastUpdated] = useState(now);
  const formatRelativeTime = (date: Date) => {
    const diff = Math.floor((Date.now() - date.getTime()) / 60000);
    if (diff < 1) return '刚刚';
    if (diff < 60) return `${diff} 分钟前`;
    return `${Math.floor(diff / 60)} 小时前`;
  };

  const { favoriteIds, toggleFavorite } = useFavorites();

  // Zustand store
  const items = useNotificationStore((state) => state.items);
  const setItems = useNotificationStore((state) => state.setItems);
  const filter = useNotificationStore((state) => state.filter);
  const setFilter = useNotificationStore((state) => state.setFilter);
  const storeMarkRead = useNotificationStore((state) => state.markRead);
  const storeMarkAllRead = useNotificationStore((state) => state.markAllRead);

  // 从 URL 初始化状态
  const [activeTab, setActiveTab] = useState<'notifications' | 'rules'>(
    (getParam('tab') as 'notifications' | 'rules') || 'notifications'
  );
  const [rules, setRules] = useState<NotificationRule[]>([]);
  const [selectedPost, setSelectedPost] = useState<DailyNewPost | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 初始化：从 URL 读取筛选参数并同步到 store
  useEffect(() => {
    const initialFilter = (getParam('filter') as FilterType) || 'all';
    setFilter(initialFilter);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load notifications and rules from service
  useEffect(() => {
    getNotifications().then((data) => setItems(data as NotificationItem[]));
    getNotificationRules().then((defaultRules) => setRules(loadNotificationRules(defaultRules)));
  }, []);

  // 使用 useSearch 替代简单搜索，自带 300ms 防抖
  const { query, setQuery, results, isSearching } = useSearch(
    items,
    (item, q) => {
      const n = item as NotificationItem;
      return (
        n.title.toLowerCase().includes(q) ||
        n.description.toLowerCase().includes(q) ||
        (!!n.subreddit && n.subreddit.toLowerCase().includes(q))
      );
    },
    300
  );

  // 初始化：从 URL 读取搜索参数并设置到 useSearch
  useEffect(() => {
    const initialSearch = getParam('search') || '';
    if (initialSearch) {
      setQuery(initialSearch);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 同步状态到 URL
  useEffect(() => {
    setParam('filter', filter === 'all' ? null : filter);
  }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setParam('search', query || null);
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setParam('tab', activeTab === 'notifications' ? null : activeTab);
  }, [activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

  // 先搜索，再按类型过滤
  const filtered = results.filter((n) => {
    if (filter === 'unread') return !n.read;
    if (filter === 'all') return true;
    return n.type === filter;
  });

  // 分页：每页 10 条
  const {
    page,
    totalPages,
    paginated,
    hasMore,
    hasPrev,
    nextPage,
    prevPage,
    setPage,
  } = usePagination(filtered, 10);

  // 当筛选/搜索变化时重置页码
  useEffect(() => {
    setPage(1);
  }, [filter, query, setPage]);

  const unreadCount = items.filter((n) => !n.read).length;
  const alertCount = items.filter((n) => n.type === 'alert' && !n.read).length;
  const taskCount = items.filter((n) => n.type === 'task' && !n.read).length;
  const insightCount = items.filter((n) => n.type === 'insight' && !n.read).length;

  // 调用 store 方法
  const markAllRead = () => storeMarkAllRead();
  const markRead = (id: string) => storeMarkRead(id);

  const toggleRule = (id: string) => {
    setRules((prev) => {
      const next = prev.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r));
      saveNotificationRules(next);
      return next;
    });
  };

  const handleOpenPostDetail = (notification: NotificationItem) => {
    const post = getPostFromNotification(notification as Notification);
    if (post) {
      setSelectedPost(post);
      setDrawerOpen(true);
    }
  };

  const handleCloseDrawer = () => {
    setDrawerOpen(false);
    setTimeout(() => setSelectedPost(null), 300);
  };

  const typeIconMap: Record<string, typeof AlertTriangle> = {
    alert: AlertTriangle,
    task: CheckSquare,
    insight: Lightbulb,
    system: Settings,
  };

  return (
    <div className="flex min-h-screen bg-surface-tertiary">
      <Sidebar />

      <main className="flex-1 min-w-0">
        {/* Top Bar */}
        <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-xl border-b border-border-divider/60">
          <div className="flex items-center justify-between px-6 py-3.5">
            <div className="flex items-center gap-4">
              <div className="relative w-72">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="搜索通知、帖子或关键词..."
                  className="input-field pl-10 bg-surface-tertiary border-transparent focus:bg-white"
                />
                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground-muted" strokeWidth={1.5} />
                {isSearching && (
                  <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground-muted animate-spin" />
                )}
              </div>
            </div>

            <div className="flex items-center gap-3">
              <Link to="/dashboard/messages" className="relative w-9 h-9 rounded-icon flex items-center justify-center text-foreground-secondary hover:bg-surface-tertiary transition-all duration-200" aria-label="消息中心">
                <Bell className="w-[18px] h-[18px]" strokeWidth={1.5} />
                <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 flex items-center justify-center bg-primary text-white text-[10px] font-bold rounded-full">
                  {unreadCount}
                </span>
              </Link>
              <div className="w-9 h-9 rounded-full bg-primary-light flex items-center justify-center">
                <span className="text-sm font-medium text-primary">M</span>
              </div>
            </div>
          </div>
        </header>

        <div className="p-6 space-y-6">
          {/* Page Header + Stats */}
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <Inbox className="w-5 h-5 text-primary" strokeWidth={1.5} />
                <h1 className="text-h1 text-foreground">消息中心</h1>
              </div>
              <p className="text-body text-foreground-secondary">
                舆情警报、任务提醒与洞察通知的统一管理
              </p>
            </div>
            <div className="flex items-center gap-2 text-caption text-foreground-muted">
              <Clock className="w-4 h-4" strokeWidth={1.5} />
              数据更新于 {formatRelativeTime(lastUpdated)}
            </div>
          </div>

          {/* Quick Stats Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: '未读消息', count: unreadCount, icon: Inbox, color: 'text-primary', bg: 'bg-primary-light', border: 'border-primary/10' },
              { label: '待处理警报', count: alertCount, icon: Shield, color: 'text-status-error', bg: 'bg-status-errorBg', border: 'border-status-error/10' },
              { label: '待办任务', count: taskCount, icon: CheckSquare, color: 'text-status-warning', bg: 'bg-status-warningBg', border: 'border-status-warning/10' },
              { label: '新洞察', count: insightCount, icon: Flame, color: 'text-status-info', bg: 'bg-status-infoBg', border: 'border-status-info/10' },
            ].map((stat) => {
              const Icon = stat.icon;
              return (
                <div
                  key={stat.label}
                  className={`card p-4 flex items-center gap-3 border ${stat.border}`}
                >
                  <div className={`w-10 h-10 rounded-icon flex items-center justify-center flex-shrink-0 ${stat.bg}`}>
                    <Icon className={`w-5 h-5 ${stat.color}`} strokeWidth={1.5} />
                  </div>
                  <div>
                    <p className="text-h2 font-semibold text-foreground">{stat.count}</p>
                    <p className="text-caption text-foreground-muted">{stat.label}</p>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Tab Switch */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1 bg-surface-tertiary rounded-card p-1.5">
              <button
                onClick={() => setActiveTab('notifications')}
                className={`px-5 py-2 rounded-button text-body-sm font-medium transition-all ${
                  activeTab === 'notifications'
                    ? 'bg-white text-foreground shadow-sm'
                    : 'text-foreground-muted hover:text-foreground'
                }`}
              >
                通知列表
                {unreadCount > 0 && (
                  <span className="ml-2 px-1.5 py-0.5 rounded-badge bg-primary text-white text-tiny">{unreadCount}</span>
                )}
              </button>
              <button
                onClick={() => setActiveTab('rules')}
                className={`px-5 py-2 rounded-button text-body-sm font-medium transition-all ${
                  activeTab === 'rules'
                    ? 'bg-white text-foreground shadow-sm'
                    : 'text-foreground-muted hover:text-foreground'
                }`}
              >
                通知规则
              </button>
            </div>

            {activeTab === 'notifications' && (
              <div className="flex items-center gap-2">
                <ExportButton
                  filename="消息通知"
                  title="消息通知列表"
                  data={filtered.map((n) => ({
                    类型: n.type,
                    标题: n.title,
                    描述: n.description,
                    社区: n.subreddit || '',
                    时间: n.time,
                    状态: n.read ? '已读' : '未读',
                    严重度: n.severity || '',
                  }))}
                  size="sm"
                />
                {unreadCount > 0 && (
                  <button
                    onClick={markAllRead}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-button text-body-sm font-medium text-primary hover:bg-primary-light transition-all"
                  >
                    <Check className="w-4 h-4" strokeWidth={1.5} />
                    全部已读
                  </button>
                )}
              </div>
            )}
          </div>

          {activeTab === 'notifications' ? (
            <div className="space-y-6">
              {/* Filters */}
              <div className="flex items-center gap-2">
                {(Object.keys(filterLabels) as FilterType[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
                      filter === f
                        ? 'bg-primary text-white'
                        : 'bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm'
                    }`}
                  >
                    {filterLabels[f]}
                    {f === 'unread' && unreadCount > 0 && (
                      <span className="ml-1">({unreadCount})</span>
                    )}
                  </button>
                ))}
              </div>

              {/* Notifications List */}
              <div className="space-y-3">
                {isSearching ? (
                  <div className="card p-16 text-center">
                    <Loader2 className="w-8 h-8 text-primary mx-auto mb-3 animate-spin" />
                    <p className="text-body text-foreground-muted">搜索中...</p>
                  </div>
                ) : paginated.length === 0 ? (
                  <div className="card p-16 text-center">
                    <Inbox className="w-12 h-12 text-foreground-muted mx-auto mb-4" strokeWidth={1.5} />
                    <p className="text-body font-medium text-foreground mb-1">
                      {query ? '未找到匹配的通知' : '暂无通知'}
                    </p>
                    <p className="text-caption text-foreground-muted">
                      {query ? '尝试更换关键词或清除筛选条件' : '当有新通知时会在此显示'}
                    </p>
                    {query && (
                      <button
                        onClick={() => { setQuery(''); setFilter('all'); }}
                        className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 rounded-button text-body-sm font-medium text-primary hover:bg-primary-light transition-all"
                      >
                        <Check className="w-4 h-4" strokeWidth={1.5} />
                        清除筛选
                      </button>
                    )}
                  </div>
                ) : (
                  <>
                    {paginated.map((n) => {
                      const typeCfg = typeConfig[n.type];
                      const Icon = typeIconMap[n.type] || Settings;
                      const hasPost = !!n.postTitle;

                      return (
                        <div
                          key={n.id}
                          onClick={() => {
                            if (hasPost) handleOpenPostDetail(n);
                          }}
                          className={`group card transition-all duration-200 hover:shadow-card-hover ${
                            !n.read ? 'border-l-[3px] border-l-primary' : ''
                          } ${hasPost ? 'cursor-pointer' : ''}`}
                          role={hasPost ? 'button' : undefined}
                          tabIndex={hasPost ? 0 : undefined}
                          onKeyDown={(e) => {
                            if (hasPost && (e.key === 'Enter' || e.key === ' ')) {
                              e.preventDefault();
                              handleOpenPostDetail(n);
                            }
                          }}
                        >
                          <div className="p-5">
                            <div className="flex items-start gap-4">
                              <div className={`w-10 h-10 rounded-icon flex items-center justify-center flex-shrink-0 ${typeCfg.bg}`}>
                                <Icon className={`w-5 h-5 ${typeCfg.color}`} strokeWidth={1.5} />
                              </div>

                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-1 flex-wrap">
                                  <span className={`px-2 py-0.5 rounded-badge text-tiny font-medium ${typeCfg.bg} ${typeCfg.color}`}>
                                    {typeCfg.label}
                                  </span>
                                  {n.severity && (
                                    <span className={`px-2 py-0.5 rounded-badge text-tiny border ${severityConfig[n.severity].bg} ${severityConfig[n.severity].color} ${severityConfig[n.severity].border}`}>
                                      {severityConfig[n.severity].label}
                                    </span>
                                  )}
                                  {!n.read && <span className="w-2 h-2 bg-primary rounded-full" />}
                                </div>

                                <h4 className={`text-body font-medium mb-1 ${!n.read ? 'text-foreground' : 'text-foreground-secondary'}`}>
                                  {n.title}
                                </h4>
                                <p className="text-caption text-foreground-secondary leading-relaxed mb-2">{n.description}</p>

                                {n.postTitle && (
                                  <div className="flex items-start gap-2 mb-3 p-2.5 rounded-icon bg-surface-tertiary">
                                    <FileText className="w-3.5 h-3.5 text-foreground-muted mt-0.5 flex-shrink-0" strokeWidth={1.5} />
                                    <p className="text-tiny text-foreground-muted">
                                      帖子：「{n.postTitle}」
                                    </p>
                                  </div>
                                )}

                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-3">
                                    {n.subreddit && (
                                      <span className="inline-flex items-center gap-1 text-tiny text-primary bg-primary-light px-2 py-0.5 rounded-badge">
                                        <MessageSquare className="w-3 h-3" strokeWidth={1.5} />
                                        r/{n.subreddit}
                                      </span>
                                    )}
                                    <span className="text-tiny text-foreground-muted">{n.time}</span>
                                  </div>

                                  <div className="flex items-center gap-2">
                                    {!n.read && (
                                      <button
                                        onClick={(e) => { e.stopPropagation(); markRead(n.id); }}
                                        className="inline-flex items-center gap-1 text-tiny text-primary hover:bg-primary-light px-2 py-1 rounded-button transition-all"
                                      >
                                        <Check className="w-3 h-3" strokeWidth={1.5} />
                                        标记已读
                                      </button>
                                    )}
                                    {n.action && (
                                      <a
                                        href={n.actionUrl || '#'}
                                        onClick={(e) => { e.stopPropagation(); }}
                                        className="inline-flex items-center gap-1 text-tiny text-primary hover:underline font-medium"
                                      >
                                        {n.action}
                                        <ArrowUpRight className="w-3 h-3" strokeWidth={1.5} />
                                      </a>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}

                    {/* Pagination */}
                    {totalPages > 1 && (
                      <div className="flex items-center justify-center gap-2 pt-4">
                        <button
                          onClick={prevPage}
                          disabled={!hasPrev}
                          className="inline-flex items-center gap-1 px-3 py-2 rounded-button text-body-sm font-medium text-foreground-secondary hover:bg-surface-tertiary disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                        >
                          <ChevronLeft className="w-4 h-4" strokeWidth={1.5} />
                          上一页
                        </button>
                        <span className="text-caption text-foreground-muted px-2">
                          第 {page} / {totalPages} 页
                        </span>
                        <button
                          onClick={nextPage}
                          disabled={!hasMore}
                          className="inline-flex items-center gap-1 px-3 py-2 rounded-button text-body-sm font-medium text-foreground-secondary hover:bg-surface-tertiary disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                        >
                          下一页
                          <ChevronRight className="w-4 h-4" strokeWidth={1.5} />
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              <SectionCard
                title="通知规则"
                subtitle="自定义触发条件和通知渠道，确保不错过关键信息"
                icon={<Settings className="w-5 h-5 text-primary" strokeWidth={1.5} />}
              >
                <div className="space-y-3">
                  {rules.map((rule) => (
                    <div
                      key={rule.id}
                      className={`flex items-center gap-4 p-4 rounded-icon transition-all ${
                        rule.enabled ? 'bg-white border border-border-divider' : 'bg-surface-tertiary opacity-60'
                      }`}
                    >
                      <button
                        onClick={() => toggleRule(rule.id)}
                        className={`flex-shrink-0 ${rule.enabled ? 'text-status-success' : 'text-foreground-muted'}`}
                      >
                        {rule.enabled ? (
                          <ToggleRight className="w-6 h-6" strokeWidth={1.5} />
                        ) : (
                          <ToggleLeft className="w-6 h-6" strokeWidth={1.5} />
                        )}
                      </button>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-body-sm font-medium text-foreground">{rule.name}</span>
                          <span className="px-2 py-0.5 rounded-badge text-tiny bg-surface-tertiary text-foreground-muted">
                            {rule.frequency === 'immediate' ? '即时' : rule.frequency === 'hourly' ? '每小时' : '每日'}
                          </span>
                        </div>
                        <p className="text-caption text-foreground-secondary">{rule.description}</p>
                        {rule.threshold && (
                          <p className="text-tiny text-foreground-muted mt-1">阈值：{rule.threshold}</p>
                        )}
                      </div>

                      <div className="flex items-center gap-2 flex-shrink-0">
                        {rule.channels.map((ch) => {
                          const ChIcon = channelIcons[ch] || Mail;
                          return (
                            <span
                              key={ch}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-badge text-tiny bg-surface-tertiary text-foreground-muted"
                            >
                              <ChIcon className="w-3 h-3" strokeWidth={1.5} />
                              {ch === 'app' ? '应用' : ch === 'email' ? '邮件' : '飞书'}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </SectionCard>
            </div>
          )}

          {/* 舆情流向与关键词分析 */}
          {activeTab === 'notifications' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-4 animate-fade-in">
              <SectionCard
                title="舆情流向分析"
                subtitle="情感 → 意图 → 社区的关联分布"
                icon={<BarChart3 className="w-5 h-5 text-primary" strokeWidth={1.5} />}
              >
                <SankeyChart
                  nodes={messageSankeyNodes}
                  links={messageSankeyLinks}
                  height={320}
                  nodeWidth={18}
                  nodePadding={14}
                />
              </SectionCard>

              <SectionCard
                title="关键词云"
                subtitle="消息中心高频提及词分布"
                icon={<Tag className="w-5 h-5 text-primary" strokeWidth={1.5} />}
              >
                <WordCloudChart
                  data={messageWordCloudData}
                  height={320}
                />
              </SectionCard>
            </div>
          )}
        </div>
      </main>

      <PostDetailDrawer
        post={selectedPost}
        open={drawerOpen}
        onClose={handleCloseDrawer}
        favoriteIds={favoriteIds}
        onToggleFavorite={toggleFavorite}
      />
    </div>
  );
}
