// 报告视图共享组件
import {
  TrendingUp,
  TrendingDown,
  Minus,
  ArrowBigUp,
  MessageCircle,
  Clock,
  MessageSquare,
  Archive,
  ArrowUpRight,
  Eye,
  CheckSquare,
  Square,
  AlertTriangle,
} from 'lucide-react';
import FavoriteButton from '../FavoriteButton';
import { intentConfig } from '../../data/intentConfig';
import type { DailyNewPost } from '../../data/dailyReportMock';
import type { ReportAlert, ReportCommunityStatus, ReportActionItem } from '../../data/reportEngine';

// ========== 通用配置 ==========

export const trendConfig = {
  up: { icon: TrendingUp, label: '上升', color: 'text-status-success' },
  down: { icon: TrendingDown, label: '下降', color: 'text-status-error' },
  stable: { icon: Minus, label: '平稳', color: 'text-foreground-muted' },
};

export const sentimentConfig = {
  positive: { label: '正面', color: 'text-status-success', bg: 'bg-status-successBg' },
  negative: { label: '负面', color: 'text-status-error', bg: 'bg-status-errorBg' },
  neutral: { label: '中性', color: 'text-foreground-muted', bg: 'bg-surface-tertiary' },
};

export const levelConfig = {
  critical: { label: '紧急', color: 'text-status-error', bg: 'bg-status-errorBg' },
  warning: { label: '警告', color: 'text-status-warning', bg: 'bg-status-warningBg' },
  info: { label: '信息', color: 'text-status-info', bg: 'bg-status-infoBg' },
};

export const urgencyConfig = {
  high: { label: '紧急', color: 'text-status-error' },
  medium: { label: '中等', color: 'text-status-warning' },
  low: { label: '低', color: 'text-foreground-muted' },
};

export const typeConfig: Record<string, { icon: typeof MessageSquare; label: string }> = {
  reply: { icon: MessageSquare, label: '回复' },
  collect: { icon: Archive, label: '收集' },
  escalate: { icon: ArrowUpRight, label: '升级' },
  monitor: { icon: Eye, label: '监控' },
};

// ========== 共享子组件 ==========

export function SharedNewPostsDiscovery({
  newPosts,
  favoriteIds,
  onToggleFavorite,
  onPostClick,
  showBusinessTag = false,
}: {
  newPosts: DailyNewPost[];
  favoriteIds: string[];
  onToggleFavorite: (id: string) => void;
  onPostClick: (post: DailyNewPost) => void;
  showBusinessTag?: boolean;
}) {
  const businessTagConfig: Record<string, { label: string; color: string; bg: string }> = {
    'high_intent': { label: '高意向', color: 'text-status-info', bg: 'bg-status-infoBg' },
    ugc: { label: 'UGC', color: 'text-status-success', bg: 'bg-status-successBg' },
    competitor: { label: '竞品', color: 'text-status-warning', bg: 'bg-status-warningBg' },
    crisis: { label: '危机', color: 'text-status-error', bg: 'bg-status-errorBg' },
    opportunity: { label: '机会', color: 'text-primary', bg: 'bg-primary-light' },
  };

  return (
    <div className="space-y-3">
      {newPosts.map((post) => {
        const Icon = intentConfig[post.intent].icon;
        return (
          <div
            key={post.id}
            onClick={() => onPostClick(post)}
            className="flex items-start gap-3 p-4 rounded-xl border border-border-divider cursor-pointer hover:shadow-card-hover transition-all duration-200 group"
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onPostClick(post); }}
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h4 className="text-body font-medium text-foreground">{post.title}</h4>
              </div>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium ${intentConfig[post.intent].bg} ${intentConfig[post.intent].color}`}>
                  <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
                  {intentConfig[post.intent].label}
                </span>
                {showBusinessTag && post.businessValueTag && (
                  <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium ${businessTagConfig[post.businessValueTag].bg} ${businessTagConfig[post.businessValueTag].color}`}>
                    {businessTagConfig[post.businessValueTag].label}
                  </span>
                )}
                <span className="text-caption text-foreground-muted">r/{post.subreddit}</span>
                <span className="inline-flex items-center gap-0.5 text-tiny text-foreground-muted">
                  <ArrowBigUp className="w-3.5 h-3.5" strokeWidth={1.5} />
                  {post.upvotes}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-tiny text-foreground-muted">意向分 {post.intentScore}</span>
              <span className={`inline-flex items-center px-2.5 py-1 rounded-badge text-tiny font-medium ${
                post.sentiment === 'positive' ? 'bg-status-successBg text-status-success' :
                post.sentiment === 'negative' ? 'bg-status-errorBg text-status-error' :
                'bg-surface-tertiary text-foreground-muted'
              }`}>
                {post.sentiment === 'positive' ? '正面' : post.sentiment === 'negative' ? '负面' : '中性'}
              </span>
              <FavoriteButton
                postId={post.id}
                favoriteIds={favoriteIds}
                onToggle={onToggleFavorite}
                size="sm"
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function SharedCommunityDynamics({ communityStatus }: { communityStatus: ReportCommunityStatus[] }) {
  return (
    <div className="space-y-2">
      {communityStatus.map((comm) => {
        const TrendIcon = trendConfig[comm.trend].icon;
        return (
          <div key={comm.name} className="flex items-center justify-between p-3 rounded-xl border border-border-divider">
            <div className="flex items-center gap-3">
              <span className="text-body font-medium text-foreground">{comm.displayName}</span>
              <span className="text-caption text-foreground-muted">{comm.newPosts} 新帖</span>
            </div>
            <div className="flex items-center gap-4">
              <span className={`text-body-sm font-medium ${sentimentConfig[comm.sentiment].color}`}>
                {sentimentConfig[comm.sentiment].label}
              </span>
              <span className={`inline-flex items-center gap-1 text-tiny font-medium ${trendConfig[comm.trend].color}`}>
                <TrendIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
                {trendConfig[comm.trend].label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function SharedActionList({ actionItems }: { actionItems: ReportActionItem[] }) {
  return (
    <div className="space-y-2">
      {actionItems.map((item) => {
        const TypeIcon = typeConfig[item.type]?.icon || MessageSquare;
        return (
          <div key={item.id} className={`flex items-center gap-3 p-3 rounded-xl border border-border-divider ${item.completed ? 'bg-surface-tertiary opacity-60' : ''}`}>
            {item.completed ? (
              <CheckSquare className="w-5 h-5 text-status-success shrink-0" strokeWidth={1.5} />
            ) : (
              <Square className="w-5 h-5 text-foreground-muted shrink-0" strokeWidth={1.5} />
            )}
            <div className="flex-1 min-w-0">
              <div className="text-body-sm text-foreground">{item.title}</div>
              <div className="flex items-center gap-2 mt-1 flex-wrap">
                <span className="inline-flex items-center gap-1 text-tiny text-foreground-muted">
                  <TypeIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
                  {typeConfig[item.type]?.label || item.type}
                </span>
                <span className={`text-tiny font-medium ${urgencyConfig[item.urgency].color}`}>
                  {urgencyConfig[item.urgency].label}
                </span>
                <span className="inline-flex items-center gap-1 text-tiny text-foreground-muted">
                  <Clock className="w-3.5 h-3.5" strokeWidth={1.5} />
                  {item.due}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function SharedUrgentAlerts({ alerts }: { alerts: ReportAlert[] }) {
  return (
    <div className="space-y-3">
      {alerts.map((alert) => (
        <div key={alert.id} className="flex items-start gap-4 p-4 rounded-xl border border-border-divider bg-surface-tertiary">
          <div className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium shrink-0 ${levelConfig[alert.level].bg} ${levelConfig[alert.level].color}`}>
            <AlertTriangle className="w-3.5 h-3.5" strokeWidth={1.5} />
            {levelConfig[alert.level].label}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h4 className="text-body font-medium text-foreground">{alert.title}</h4>
              <span className="text-caption text-foreground-muted">r/{alert.subreddit}</span>
            </div>
            <p className="text-caption text-foreground-secondary mt-1">{alert.summary}</p>
            <div className="flex items-center gap-4 mt-2 text-tiny text-foreground-muted flex-wrap">
              <span className="inline-flex items-center gap-1">
                <ArrowBigUp className="w-3.5 h-3.5" strokeWidth={1.5} />
                {alert.upvotes}
              </span>
              <span className="inline-flex items-center gap-1">
                <MessageCircle className="w-3.5 h-3.5" strokeWidth={1.5} />
                {alert.comments}
              </span>
              <span className="inline-flex items-center gap-1 text-status-error">
                <TrendingUp className="w-3.5 h-3.5" strokeWidth={1.5} />
                +{alert.growth}
              </span>
              <span className="inline-flex items-center gap-1">
                <Clock className="w-3.5 h-3.5" strokeWidth={1.5} />
                {alert.time}
              </span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
