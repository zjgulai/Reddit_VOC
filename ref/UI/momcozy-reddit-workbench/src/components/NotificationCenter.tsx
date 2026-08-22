import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Bell,
  X,
  Check,
  AlertTriangle,
  CheckSquare,
  Lightbulb,
  Settings,
  ArrowUpRight,
  MessageSquare,
  Clock,
  Inbox,
  Send,
  Loader2,
} from 'lucide-react';
import { useSearch } from '../hooks';
import type { NotificationItem } from '../types';

interface NotificationCenterProps {
  notifications: NotificationItem[];
  onMarkRead?: (id: string) => void;
  onMarkAllRead?: () => void;
  onNavigate?: (url: string) => void;
  onPushWebhook?: (item: NotificationItem) => Promise<void>;
}

const typeIconMap: Record<string, typeof AlertTriangle> = {
  alert: AlertTriangle,
  task: CheckSquare,
  insight: Lightbulb,
  system: Settings,
};

const typeConfig: Record<string, { label: string; color: string; bg: string }> = {
  alert: { label: '警报', color: 'text-status-error', bg: 'bg-status-errorBg' },
  task: { label: '任务', color: 'text-status-warning', bg: 'bg-status-warningBg' },
  insight: { label: '洞察', color: 'text-status-info', bg: 'bg-status-infoBg' },
  system: { label: '系统', color: 'text-foreground-muted', bg: 'bg-surface-tertiary' },
};

const severityConfig: Record<string, { label: string; color: string; bg: string; border: string }> = {
  critical: { label: '严重', color: 'text-status-error', bg: 'bg-status-errorBg', border: 'border-status-error' },
  warning: { label: '警告', color: 'text-status-warning', bg: 'bg-status-warningBg', border: 'border-status-warning' },
  info: { label: '信息', color: 'text-status-info', bg: 'bg-status-infoBg', border: 'border-status-info' },
};

export default function NotificationCenter({
  notifications,
  onMarkRead,
  onMarkAllRead,
  onNavigate,
  onPushWebhook,
}: NotificationCenterProps) {
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [pushingIds, setPushingIds] = useState<Set<string>>(new Set());
  const [pushResults, setPushResults] = useState<Record<string, { success: boolean; message: string }>>({});

  const unreadCount = notifications.filter((n) => !n.read).length;
  const unreadAlerts = notifications.filter((n) => n.type === 'alert' && !n.read).length;

  const { query, setQuery, results } = useSearch(
    notifications.filter((n) => !n.read),
    (item, q) => {
      const n = item as NotificationItem;
      return (
        n.title.toLowerCase().includes(q) ||
        n.description.toLowerCase().includes(q)
      );
    },
    200
  );

  const displayed = query ? results : notifications.filter((n) => !n.read).slice(0, 8);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  useEffect(() => {
    function handleEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    if (open) {
      document.addEventListener('keydown', handleEsc);
    }
    return () => document.removeEventListener('keydown', handleEsc);
  }, [open]);

  const handlePush = useCallback(
    async (item: NotificationItem) => {
      if (!onPushWebhook) return;
      setPushingIds((prev) => new Set(prev).add(item.id));
      setPushResults((prev) => {
        const next = { ...prev };
        delete next[item.id];
        return next;
      });
      try {
        await onPushWebhook(item);
        setPushResults((prev) => ({ ...prev, [item.id]: { success: true, message: '已推送' } }));
      } catch (err) {
        setPushResults((prev) => ({
          ...prev,
          [item.id]: { success: false, message: err instanceof Error ? err.message : '推送失败' },
        }));
      } finally {
        setPushingIds((prev) => {
          const next = new Set(prev);
          next.delete(item.id);
          return next;
        });
      }
    },
    [onPushWebhook]
  );

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        onClick={() => setOpen(!open)}
        className="relative w-9 h-9 rounded-icon flex items-center justify-center text-foreground-secondary hover:bg-surface-tertiary transition-all duration-200"
        aria-expanded={open}
        aria-label={`通知中心，${unreadCount} 条未读`}
      >
        <Bell className="w-[18px] h-[18px]" strokeWidth={1.5} />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 flex items-center justify-center bg-primary text-white text-[10px] font-bold rounded-full">
            {unreadCount}
          </span>
        )}
        {unreadAlerts > 0 && unreadCount === 0 && (
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-primary rounded-full" />
        )}
      </button>

      {open && (
        <div
          ref={panelRef}
          className="absolute right-0 mt-2 w-[400px] max-w-[calc(100vw-2rem)] bg-white rounded-card shadow-elevated border border-border-divider z-50 overflow-hidden animate-fade-in"
          role="dialog"
          aria-label="通知中心"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border-divider">
            <div>
              <h3 className="text-body font-semibold text-foreground">通知中心</h3>
              <p className="text-caption text-foreground-muted mt-0.5">
                {unreadCount > 0 ? `${unreadCount} 条未读通知` : '暂无未读通知'}
              </p>
            </div>
            <div className="flex items-center gap-1">
              {unreadCount > 0 && onMarkAllRead && (
                <button
                  onClick={() => {
                    onMarkAllRead();
                    setQuery('');
                  }}
                  className="inline-flex items-center gap-1 text-tiny text-primary hover:bg-primary-light px-2 py-1 rounded-button transition-all"
                >
                  <Check className="w-3 h-3" strokeWidth={1.5} />
                  全部已读
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="w-7 h-7 rounded-icon flex items-center justify-center text-foreground-muted hover:bg-surface-tertiary transition-all"
                aria-label="关闭"
              >
                <X className="w-4 h-4" strokeWidth={1.5} />
              </button>
            </div>
          </div>

          {/* Search */}
          <div className="px-5 py-3 border-b border-border-divider">
            <div className="relative">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索未读通知..."
                className="w-full px-3 py-2 pl-9 rounded-input text-body-sm bg-surface-tertiary border border-transparent focus:bg-white focus:border-primary outline-none transition-all"
              />
              <Inbox className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground-muted" strokeWidth={1.5} />
            </div>
          </div>

          {/* Notification List */}
          <div className="max-h-[400px] overflow-y-auto">
            {displayed.length === 0 ? (
              <div className="px-5 py-10 text-center">
                <Inbox className="w-10 h-10 text-foreground-muted mx-auto mb-3" strokeWidth={1.5} />
                <p className="text-body-sm text-foreground-muted">
                  {query ? '未找到匹配通知' : '暂无未读通知'}
                </p>
              </div>
            ) : (
              <div className="divide-y divide-border-divider">
                {displayed.map((n) => {
                  const TypeIcon = typeIconMap[n.type] || Settings;
                  const cfg = typeConfig[n.type] || typeConfig.system;
                  const isPushing = pushingIds.has(n.id);
                  const pushResult = pushResults[n.id];
                  const canPush = !!onPushWebhook && (n.type === 'alert' || n.type === 'system') && n.severity && n.severity !== 'info';

                  return (
                    <div
                      key={n.id}
                      className={`px-5 py-3.5 hover:bg-surface-tertiary transition-colors ${
                        !n.read ? 'border-l-[3px] border-l-primary' : ''
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <div className={`w-8 h-8 rounded-icon flex items-center justify-center flex-shrink-0 ${cfg.bg}`}>
                          <TypeIcon className={`w-4 h-4 ${cfg.color}`} strokeWidth={1.5} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1 flex-wrap">
                            <span className={`px-2 py-0.5 rounded-badge text-[11px] font-medium ${cfg.bg} ${cfg.color}`}>
                              {cfg.label}
                            </span>
                            {n.severity && (
                              <span className={`px-2 py-0.5 rounded-badge text-[11px] font-medium border ${severityConfig[n.severity].bg} ${severityConfig[n.severity].color} ${severityConfig[n.severity].border}`}>
                                {severityConfig[n.severity].label}
                              </span>
                            )}
                          </div>
                          <h4 className="text-body-sm font-medium text-foreground leading-snug mb-0.5">
                            {n.title}
                          </h4>
                          <p className="text-caption text-foreground-secondary line-clamp-2 leading-relaxed">
                            {n.description}
                          </p>
                          <div className="flex items-center justify-between mt-2">
                            <div className="flex items-center gap-2">
                              {n.subreddit && (
                                <span className="inline-flex items-center gap-1 text-[11px] text-primary bg-primary-light px-1.5 py-0.5 rounded-badge">
                                  <MessageSquare className="w-3 h-3" strokeWidth={1.5} />
                                  r/{n.subreddit}
                                </span>
                              )}
                              <span className="text-[11px] text-foreground-muted flex items-center gap-1">
                                <Clock className="w-3 h-3" strokeWidth={1.5} />
                                {n.time}
                              </span>
                            </div>
                            <div className="flex items-center gap-2">
                              {!n.read && onMarkRead && (
                                <button
                                  onClick={() => onMarkRead(n.id)}
                                  className="text-[11px] text-primary hover:underline"
                                >
                                  标记已读
                                </button>
                              )}
                              {n.actionUrl && onNavigate && (
                                <button
                                  onClick={() => {
                                    if (n.actionUrl && onNavigate) {
                                      onNavigate(n.actionUrl);
                                      setOpen(false);
                                    }
                                  }}
                                  className="inline-flex items-center gap-0.5 text-[11px] text-primary hover:underline font-medium"
                                >
                                  {n.action || '查看'}
                                  <ArrowUpRight className="w-3 h-3" strokeWidth={1.5} />
                                </button>
                              )}
                            </div>
                          </div>

                          {/* Push result + push button */}
                          <div className="flex items-center gap-2 mt-2">
                            {canPush && (
                              <button
                                onClick={() => handlePush(n)}
                                disabled={isPushing}
                                className="inline-flex items-center gap-1 text-[11px] text-primary hover:bg-primary-light px-2 py-1 rounded-button transition-all"
                              >
                                {isPushing ? (
                                  <>
                                    <Loader2 className="w-3 h-3 animate-spin" strokeWidth={1.5} />
                                    推送中...
                                  </>
                                ) : (
                                  <>
                                    <Send className="w-3 h-3" strokeWidth={1.5} />
                                    推送至机器人
                                  </>
                                )}
                              </button>
                            )}
                            {pushResult && (
                              <span
                                className={`text-[11px] font-medium ${
                                  pushResult.success ? 'text-status-success' : 'text-status-error'
                                }`}
                              >
                                {pushResult.message}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-5 py-3 border-t border-border-divider bg-surface-tertiary/50">
            <button
              onClick={() => {
                setOpen(false);
                onNavigate?.('/dashboard/messages');
              }}
              className="w-full text-center text-body-sm text-primary hover:text-primary-hover transition-colors"
            >
              查看全部消息
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
