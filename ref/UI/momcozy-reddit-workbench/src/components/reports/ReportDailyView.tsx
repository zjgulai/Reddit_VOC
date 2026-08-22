import { useState } from 'react';
import {
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Clock,
  ArrowBigUp,
  CheckSquare,
  Square,
  AlertCircle,
  Minus,
  CheckCircle,
  ArrowRight,
  Activity,
  Eye,
  Thermometer,
  Gauge,
  Timer,
  DollarSign,
  Users,
  Radio,
  ShieldAlert,
  LayoutGrid,
  MessageSquare,
  Archive,
  ArrowUpRight,
  ShoppingCart,
  Heart,
  GitCompare,
  Tag,
} from 'lucide-react';
import SectionCard from '../SectionCard';
import PostDetailDrawer from '../PostDetailDrawer';
import DetailModal from '../DetailModal';
import FavoriteButton from '../FavoriteButton';
import { intentConfig } from '../../data/intentConfig';
import type { DailyNewPost, SentimentLevel, BusinessValueTag } from '../../data/dailyReportMock';
import type { PostIntent } from '../../types';
import type { UnifiedReportData } from '../../data/reportEngine';
import { BarChart, ComposedChart, SentimentTrendChart, WordCloudChart, FunnelChart } from '../charts';
import { BRAND_COLORS } from '../../constants/colors';
import { getEnhancedWordCloudData, sentimentColorMap } from '../../data/enhancedWordCloudMock';
import type { WordCloudItem } from '../charts/WordCloudChart';

// ========== 子组件 ==========

/** 情感温度计 + 舆情水位 */
function SentimentThermometer({
  positiveRate,
  negativeRate,
  neutralRate,
  sentimentLevel,
  sentimentLevelLabel,
  trendChange,
}: {
  positiveRate: number;
  negativeRate: number;
  neutralRate: number;
  sentimentLevel: SentimentLevel;
  sentimentLevelLabel: string;
  trendChange: { positiveChange: number; negativeChange: number };
}) {
  const levelConfig = {
    calm: { color: 'bg-status-success', text: 'text-status-success', bg: 'bg-status-successBg', label: '平稳', icon: CheckCircle },
    watch: { color: 'bg-status-warning', text: 'text-status-warning', bg: 'bg-status-warningBg', label: '关注', icon: AlertCircle },
    alert: { color: 'bg-status-error', text: 'text-status-error', bg: 'bg-status-errorBg', label: '警戒', icon: AlertTriangle },
    crisis: { color: 'bg-foreground', text: 'text-foreground', bg: 'bg-gray-100', label: '危机', icon: ShieldAlert },
  };

  const config = levelConfig[sentimentLevel];
  const LevelIcon = config.icon;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      {/* 情感温度计 */}
      <div className="card p-5 flex flex-col justify-between">
        <div className="flex items-center gap-2 mb-4">
          <Thermometer className="w-5 h-5 text-primary" strokeWidth={1.5} />
          <h4 className="text-body font-medium text-foreground">情感温度计</h4>
        </div>
        <div className="space-y-4">
          <div>
            <div className="flex justify-between text-caption text-foreground-muted mb-1">
              <span>正面</span>
              <span className="text-status-success font-medium">{positiveRate}%</span>
            </div>
            <div className="h-2.5 rounded-full bg-surface-tertiary overflow-hidden">
              <div className="h-full rounded-full bg-status-success transition-all duration-700" style={{ width: `${positiveRate}%` }} />
            </div>
          </div>
          <div>
            <div className="flex justify-between text-caption text-foreground-muted mb-1">
              <span>中性</span>
              <span className="text-status-warning font-medium">{neutralRate}%</span>
            </div>
            <div className="h-2.5 rounded-full bg-surface-tertiary overflow-hidden">
              <div className="h-full rounded-full bg-status-warning transition-all duration-700" style={{ width: `${neutralRate}%` }} />
            </div>
          </div>
          <div>
            <div className="flex justify-between text-caption text-foreground-muted mb-1">
              <span>负面</span>
              <span className="text-status-error font-medium">{negativeRate}%</span>
            </div>
            <div className="h-2.5 rounded-full bg-surface-tertiary overflow-hidden">
              <div className="h-full rounded-full bg-status-error transition-all duration-700" style={{ width: `${negativeRate}%` }} />
            </div>
          </div>
        </div>
        <div className="mt-4 flex items-center gap-3 text-tiny">
          <span className="inline-flex items-center gap-1 text-status-success">
            <TrendingUp className="w-3.5 h-3.5" strokeWidth={1.5} />
            正面 +{trendChange.positiveChange}%
          </span>
          <span className="inline-flex items-center gap-1 text-status-error">
            <TrendingDown className="w-3.5 h-3.5" strokeWidth={1.5} />
            负面 {trendChange.negativeChange}%
          </span>
        </div>
      </div>

      {/* 舆情水位等级 */}
      <div className="card p-5 flex flex-col justify-between">
        <div className="flex items-center gap-2 mb-4">
          <Gauge className="w-5 h-5 text-primary" strokeWidth={1.5} />
          <h4 className="text-body font-medium text-foreground">舆情水位</h4>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center">
          <div className={`w-20 h-20 rounded-full ${config.bg} flex items-center justify-center mb-3`}>
            <LevelIcon className={`w-10 h-10 ${config.text}`} strokeWidth={1.5} />
          </div>
          <div className={`text-h2 font-semibold ${config.text}`}>{sentimentLevelLabel}</div>
          <div className="text-caption text-foreground-muted mt-1">当前舆情态势</div>
        </div>
        <div className="mt-4 grid grid-cols-4 gap-1">
          {(['calm', 'watch', 'alert', 'crisis'] as SentimentLevel[]).map((level) => (
            <div
              key={level}
              className={`h-1.5 rounded-full ${level === sentimentLevel ? levelConfig[level].color : 'bg-surface-tertiary'}`}
            />
          ))}
        </div>
      </div>

      {/* 响应时效指标 */}
      <div className="card p-5">
        <div className="flex items-center gap-2 mb-4">
          <Timer className="w-5 h-5 text-primary" strokeWidth={1.5} />
          <h4 className="text-body font-medium text-foreground">响应时效</h4>
        </div>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-caption text-foreground-muted">平均响应时间</span>
            <span className="text-h4 font-semibold text-foreground">42<span className="text-body-sm font-normal text-foreground-muted ml-1">分钟</span></span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-caption text-foreground-muted">完成率</span>
            <span className="text-h4 font-semibold text-status-success">78%</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-caption text-foreground-muted">紧急处理率</span>
            <span className="text-h4 font-semibold text-status-success">92%</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-caption text-foreground-muted">升级率</span>
            <span className="text-h4 font-semibold text-status-warning">8%</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 紧急响应区 */
function EnhancedUrgentAlerts({ alerts }: { alerts: UnifiedReportData['alerts'] }) {
  const levelConfig = {
    critical: { label: '紧急', color: 'text-status-error', bg: 'bg-status-errorBg', border: 'border-status-error/20' },
    warning: { label: '警告', color: 'text-status-warning', bg: 'bg-status-warningBg', border: 'border-status-warning/20' },
    info: { label: '信息', color: 'text-status-info', bg: 'bg-status-infoBg', border: 'border-status-info/20' },
  };

  return (
    <div className="space-y-3">
      {alerts.map((alert) => (
        <div key={alert.id} className={`flex items-start gap-4 p-4 rounded-xl border ${levelConfig[alert.level].border} bg-white hover:shadow-card-hover transition-all duration-300`}>
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
            {/* 响应时效 + 影响评估 */}
            <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
              <div className="flex items-center gap-1.5 text-tiny text-foreground-muted">
                <Eye className="w-3.5 h-3.5" strokeWidth={1.5} />
                发现: {alert.discoveredAt || alert.time}
              </div>
              <div className="flex items-center gap-1.5 text-tiny text-foreground-muted">
                <Timer className="w-3.5 h-3.5" strokeWidth={1.5} />
                响应: {alert.respondedAt || '待响应'}
              </div>
              <div className="flex items-center gap-1.5 text-tiny text-status-error">
                <DollarSign className="w-3.5 h-3.5" strokeWidth={1.5} />
                潜在损失: ${alert.impactEstimate?.potentialLoss || 0}
              </div>
              <div className="flex items-center gap-1.5 text-tiny text-foreground-muted">
                <Users className="w-3.5 h-3.5" strokeWidth={1.5} />
                影响客户: {alert.impactEstimate?.affectedCustomers || 0}人
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** 本期运营待办 + 优先级矩阵 */
function EnhancedActionList({ actionItems }: { actionItems: UnifiedReportData['actionItems'] }) {
  const typeConfig: Record<string, { icon: typeof MessageSquare; label: string }> = {
    reply: { icon: MessageSquare, label: '回复' },
    collect: { icon: Archive, label: '收集' },
    escalate: { icon: ArrowUpRight, label: '升级' },
    monitor: { icon: Eye, label: '监控' },
  };

  const urgencyConfig = {
    high: { label: '紧急', color: 'text-status-error' },
    medium: { label: '中等', color: 'text-status-warning' },
    low: { label: '低', color: 'text-foreground-muted' },
  };

  // 计算完成率等
  const total = actionItems.length;
  const completed = actionItems.filter((a) => a.completed).length;
  const completionRate = Math.round((completed / total) * 100);
  const highUrgency = actionItems.filter((a) => a.urgency === 'high').length;

  return (
    <div className="space-y-4">
      {/* 效率指标 */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-surface-tertiary rounded-xl p-3 text-center">
          <div className="text-h4 font-semibold text-foreground">{completionRate}%</div>
          <div className="text-tiny text-foreground-muted">完成率</div>
        </div>
        <div className="bg-surface-tertiary rounded-xl p-3 text-center">
          <div className="text-h4 font-semibold text-foreground">{highUrgency}</div>
          <div className="text-tiny text-foreground-muted">紧急事项</div>
        </div>
        <div className="bg-surface-tertiary rounded-xl p-3 text-center">
          <div className="text-h4 font-semibold text-foreground">{total - completed}</div>
          <div className="text-tiny text-foreground-muted">待处理</div>
        </div>
      </div>

      {/* 优先级矩阵 */}
      <div className="bg-surface-tertiary rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <LayoutGrid className="w-4 h-4 text-primary" strokeWidth={1.5} />
          <span className="text-body-sm font-medium text-foreground">优先级矩阵</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-white rounded-lg p-3 border border-status-error/20">
            <div className="text-tiny font-medium text-status-error mb-1">紧急 & 重要</div>
            <div className="text-h4 font-semibold text-foreground">
              {actionItems.filter((a) => a.priorityMatrix === 'urgent_important').length}
            </div>
          </div>
          <div className="bg-white rounded-lg p-3 border border-status-warning/20">
            <div className="text-tiny font-medium text-status-warning mb-1">不紧急 & 重要</div>
            <div className="text-h4 font-semibold text-foreground">
              {actionItems.filter((a) => a.priorityMatrix === 'not_urgent_important').length}
            </div>
          </div>
          <div className="bg-white rounded-lg p-3 border border-status-info/20">
            <div className="text-tiny font-medium text-status-info mb-1">紧急 & 不重要</div>
            <div className="text-h4 font-semibold text-foreground">
              {actionItems.filter((a) => a.priorityMatrix === 'urgent_not_important').length}
            </div>
          </div>
          <div className="bg-white rounded-lg p-3 border border-border-divider">
            <div className="text-tiny font-medium text-foreground-muted mb-1">不紧急 & 不重要</div>
            <div className="text-h4 font-semibold text-foreground">
              {actionItems.filter((a) => a.priorityMatrix === 'not_urgent_not_important').length}
            </div>
          </div>
        </div>
      </div>

      {/* 待办列表 */}
      <div className="space-y-2">
        {actionItems.map((item) => {
          const TypeIcon = typeConfig[item.type]?.icon || MessageSquare;
          return (
            <div key={item.id} className={`flex items-center gap-3 p-3 rounded-xl border border-border-divider ${item.completed ? 'bg-surface-tertiary opacity-60' : 'bg-white'} hover:shadow-card-hover transition-all duration-200`}>
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
    </div>
  );
}

/** 社区活跃度监控 */
function CommunityActivityMonitor({ communityStatus }: { communityStatus: UnifiedReportData['communityStatus'] }) {
  const sentimentConfig = {
    positive: { label: '正面', color: 'text-status-success' },
    negative: { label: '负面', color: 'text-status-error' },
    neutral: { label: '中性', color: 'text-foreground-muted' },
  };

  const trendConfig = {
    up: { icon: TrendingUp, label: '上升', color: 'text-status-success' },
    down: { icon: TrendingDown, label: '下降', color: 'text-status-error' },
    stable: { icon: Minus, label: '平稳', color: 'text-foreground-muted' },
  };

  return (
    <div className="space-y-3">
      {communityStatus.map((comm) => {
        const TrendIcon = trendConfig[comm.trend].icon;
        const activityIndex = comm.activityIndex ?? 50;
        const brandMentionRate = comm.brandMentionRate ?? 0;
        const sentimentChangeSpeed = comm.sentimentChangeSpeed ?? 0;

        return (
          <div key={comm.name} className="flex items-center justify-between p-4 rounded-xl border border-border-divider bg-white hover:shadow-card-hover transition-all duration-200">
            <div className="flex items-center gap-4 flex-1">
              <div>
                <span className="text-body font-medium text-foreground">{comm.displayName}</span>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-caption text-foreground-muted">{comm.newPosts} 新帖</span>
                  <span className={`text-caption font-medium ${sentimentConfig[comm.sentiment].color}`}>
                    {sentimentConfig[comm.sentiment].label}
                  </span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-6 flex-wrap">
              <div className="text-center">
                <div className="text-tiny text-foreground-muted">活跃度</div>
                <div className="text-body-sm font-semibold text-foreground">{activityIndex}</div>
              </div>
              <div className="text-center">
                <div className="text-tiny text-foreground-muted">品牌提及</div>
                <div className="text-body-sm font-semibold text-primary">{brandMentionRate}%</div>
              </div>
              <div className="text-center">
                <div className="text-tiny text-foreground-muted">情感变化</div>
                <div className={`text-body-sm font-semibold ${sentimentChangeSpeed > 1.5 ? 'text-status-error' : 'text-foreground'}`}>
                  {sentimentChangeSpeed > 0 ? '+' : ''}{sentimentChangeSpeed}/h
                </div>
              </div>
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

/** 商业价值标签映射 */
const businessTagConfig: Record<BusinessValueTag, { label: string; color: string; bg: string; icon: typeof ShoppingCart }> = {
  'high_intent': { label: '高意向', color: 'text-status-success', bg: 'bg-status-successBg', icon: ShoppingCart },
  'ugc': { label: 'UGC', color: 'text-primary', bg: 'bg-primary-light', icon: Heart },
  'competitor': { label: '竞品', color: 'text-status-info', bg: 'bg-status-infoBg', icon: GitCompare },
  'crisis': { label: '危机', color: 'text-status-error', bg: 'bg-status-errorBg', icon: ShieldAlert },
  'opportunity': { label: '机会', color: 'text-status-success', bg: 'bg-status-successBg', icon: TrendingUp },
};

/** 新帖发现流 */
function EnhancedNewPostsDiscovery({
  newPosts,
  favoriteIds,
  onToggleFavorite,
  onPostClick,
}: {
  newPosts: UnifiedReportData['newPosts'];
  favoriteIds: string[];
  onToggleFavorite: (id: string) => void;
  onPostClick: (post: DailyNewPost) => void;
}) {
  return (
    <div className="space-y-3">
      {newPosts.map((post) => {
        const postIntent = post.intent as PostIntent;
        const Icon = intentConfig[postIntent].icon;
        const bizTag = post.businessValueTag;
        const BizIcon = bizTag ? businessTagConfig[bizTag].icon : null;

        return (
          <div
            key={post.id}
            onClick={() => onPostClick(post)}
            className="flex items-start gap-3 p-4 rounded-xl border border-border-divider cursor-pointer hover:shadow-card-hover transition-all duration-200 group bg-white"
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onPostClick(post); }}
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h4 className="text-body font-medium text-foreground">{post.title}</h4>
              </div>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium ${intentConfig[postIntent].bg} ${intentConfig[postIntent].color}`}>
                  <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
                  {intentConfig[postIntent].label}
                </span>
                {bizTag && BizIcon && (
                  <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium ${businessTagConfig[bizTag].bg} ${businessTagConfig[bizTag].color}`}>
                    <BizIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
                    {businessTagConfig[bizTag].label}
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
              <button
                onClick={(e) => { e.stopPropagation(); }}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-button text-tiny font-medium text-primary bg-primary-light opacity-0 group-hover:opacity-100 transition-opacity"
              >
                {intentConfig[postIntent].actionLabel}
                <ArrowRight className="w-3.5 h-3.5" strokeWidth={1.5} />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ========== 主视图 ==========

export interface ReportDailyViewProps {
  data: UnifiedReportData;
  favoriteIds: string[];
  onToggleFavorite: (id: string) => void;
}

export default function ReportDailyView({ data, favoriteIds, onToggleFavorite }: ReportDailyViewProps) {
  const [selectedPost, setSelectedPost] = useState<DailyNewPost | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [filteredSubreddit, setFilteredSubreddit] = useState<string | null>(null);
  const [filteredIntent, setFilteredIntent] = useState<PostIntent | null>(null);
  const [filteredKeyword, setFilteredKeyword] = useState<string | null>(null);
  const [showPostsModal, setShowPostsModal] = useState(false);
  const [showAlertsModal, setShowAlertsModal] = useState(false);
  const [showActionsModal, setShowActionsModal] = useState(false);

  const handlePostClick = (post: DailyNewPost) => {
    setSelectedPost(post);
    setDrawerOpen(true);
  };

  const handleCloseDrawer = () => {
    setDrawerOpen(false);
    setTimeout(() => setSelectedPost(null), 300);
  };

  const handleBarClick = (barData: { name: string; value: number }) => {
    // 点击柱状图，过滤对应社区的帖子
    const comm = data.communityStatus.find((c) => c.displayName === barData.name);
    if (comm) {
      setFilteredSubreddit((prev) => (prev === comm.name ? null : comm.name));
    }
  };

  const handleWordClick = (item: WordCloudItem) => {
    setFilteredKeyword((prev) => (prev === item.text ? null : item.text));
  };

  const handleFunnelClick = (funnelData: { name: string; value: number }) => {
    const intentMap: Record<string, PostIntent> = {
      '认知': 'Question',
      '考虑': 'Comparison',
      '购买': 'Purchase Intent',
    };
    const intent = intentMap[funnelData.name];
    if (intent) {
      setFilteredIntent((prev) => (prev === intent ? null : intent));
    }
  };

  const clearAllFilters = () => {
    setFilteredSubreddit(null);
    setFilteredIntent(null);
    setFilteredKeyword(null);
  };

  const hasActiveFilter = filteredSubreddit || filteredIntent || filteredKeyword;

  const filteredNewPosts = data.newPosts.filter((p) => {
    if (filteredSubreddit && p.subreddit !== filteredSubreddit) return false;
    if (filteredIntent && p.intent !== filteredIntent) return false;
    if (filteredKeyword && !p.title.toLowerCase().includes(filteredKeyword.toLowerCase())) return false;
    return true;
  });

  const getFilterTitle = () => {
    if (filteredSubreddit) return `新帖发现流 · r/${filteredSubreddit}`;
    if (filteredIntent) return `新帖发现流 · ${intentConfig[filteredIntent].label}`;
    if (filteredKeyword) return `新帖发现流 · 关键词「${filteredKeyword}」`;
    return '新帖发现流';
  };

  return (
    <>
      <div className="space-y-6 animate-fade-in">
        {/* 舆情水位看板 */}
        <SectionCard title="舆情水位看板" subtitle={`更新于 ${data.overview.updatedAt}`} tag="舆情" icon={<Gauge className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          <SentimentThermometer
            positiveRate={data.overview.positiveRate}
            negativeRate={data.overview.negativeRate}
            neutralRate={data.overview.neutralRate}
            sentimentLevel={data.overview.sentimentLevel as SentimentLevel || 'watch'}
            sentimentLevelLabel={data.overview.sentimentLevelLabel as string || '关注'}
            trendChange={{ positiveChange: 0, negativeChange: 0 }}
          />
          <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
            <SentimentTrendChart
              data={data.sentimentTrend}
              title="24小时情感趋势"
              height={240}
            />
            <ComposedChart
              data={data.sentimentTrend.map((d) => ({ label: d.label, barValue: d.volume ?? 0, lineValue: d.positive }))}
              title="声量与正面率组合"
              height={240}
              barName="帖子数"
              lineName="正面率 (%)"
              barColor={BRAND_COLORS.secondary}
              lineColor={BRAND_COLORS.tertiary}
            />
          </div>
        </SectionCard>

        {/* 紧急响应区 */}
        <SectionCard
          title="紧急响应区"
          subtitle="需要立即关注的负面/高危帖子"
          tag="舆情"
          icon={<ShieldAlert className="w-5 h-5 text-primary" strokeWidth={1.5} />}
          action={data.alerts.length > 3 ? { label: '查看全部', onClick: () => setShowAlertsModal(true) } : undefined}
        >
          <EnhancedUrgentAlerts alerts={data.alerts.slice(0, 3)} />
        </SectionCard>

        {/* 新帖发现流 */}
        <SectionCard
          title={getFilterTitle()}
          subtitle={hasActiveFilter ? '点击清除筛选可查看全部帖子' : '本期发现的高价值帖子 · 点击右侧社区图表可筛选'}
          tag="运营"
          icon={<Radio className="w-5 h-5 text-primary" strokeWidth={1.5} />}
          action={filteredNewPosts.length > 5 ? { label: '查看全部', onClick: () => setShowPostsModal(true) } : undefined}
        >
          {hasActiveFilter && (
            <button
              onClick={clearAllFilters}
              className="mb-3 inline-flex items-center gap-1 px-3 py-1.5 rounded-button text-tiny font-medium text-primary bg-primary-light hover:bg-primary-light/80 transition-all"
            >
              清除筛选
            </button>
          )}
          <EnhancedNewPostsDiscovery
            newPosts={filteredNewPosts.slice(0, 5)}
            favoriteIds={favoriteIds}
            onToggleFavorite={onToggleFavorite}
            onPostClick={handlePostClick}
          />
        </SectionCard>

        {/* 社区活跃度监控 */}
        <SectionCard title="社区活跃度监控" subtitle="各社区本期活跃度和品牌提及情况 · 点击柱状图筛选帖子" tag="品牌" icon={<Activity className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          <CommunityActivityMonitor communityStatus={data.communityStatus} />
          <div className="mt-6">
            <BarChart
              data={data.communityStatus.map((c) => ({ name: c.displayName, value: c.newPosts }))}
              title="社区新帖数对比"
              height={240}
              onDataClick={handleBarClick}
            />
          </div>
        </SectionCard>

        {/* 关键词洞察与用户旅程 */}
        <SectionCard
          title="关键词洞察与用户旅程"
          subtitle="本期高频关键词与购买漏斗转化分析 · 点击图表可筛选帖子"
          tag="品牌"
          icon={<Tag className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        >
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <WordCloudChart
              data={getEnhancedWordCloudData(data.period === 'monthly' ? '30d' : '7d').map((item) => ({
                text: item.text,
                value: item.value,
                color: sentimentColorMap[item.sentiment],
                sourcePostIds: item.sourcePostIds,
                sentimentConfidence: item.sentimentConfidence,
              }))}
              title="本期高频关键词"
              height={280}
              onWordClick={handleWordClick}
            />
            <FunnelChart
              data={[
                {
                  name: '认知',
                  value: data.newPosts.filter((p) => p.intent === 'Question').length,
                  color: BRAND_COLORS.primary,
                },
                {
                  name: '考虑',
                  value: data.newPosts.filter((p) => p.intent === 'Comparison').length,
                  color: BRAND_COLORS.secondary,
                },
                {
                  name: '购买',
                  value: data.newPosts.filter((p) => p.intent === 'Purchase Intent').length,
                  color: BRAND_COLORS.tertiary,
                },
              ]}
              title="用户旅程转化"
              height={280}
              onDataClick={handleFunnelClick}
            />
          </div>
        </SectionCard>

        {/* 本期运营待办 */}
        <SectionCard
          title="本期运营待办"
          subtitle="待办事项与优先级矩阵"
          tag="运营"
          icon={<CheckSquare className="w-5 h-5 text-primary" strokeWidth={1.5} />}
          action={data.actionItems.length > 5 ? { label: '查看全部', onClick: () => setShowActionsModal(true) } : undefined}
        >
          <EnhancedActionList actionItems={data.actionItems.slice(0, 5)} />
        </SectionCard>
      </div>

      {/* 全部新帖弹窗 */}
      <DetailModal
        open={showPostsModal}
        onClose={() => setShowPostsModal(false)}
        title="全部新帖"
        subtitle={`共 ${filteredNewPosts.length} 条帖子`}
      >
        <EnhancedNewPostsDiscovery
          newPosts={filteredNewPosts}
          favoriteIds={favoriteIds}
          onToggleFavorite={onToggleFavorite}
          onPostClick={handlePostClick}
        />
      </DetailModal>

      {/* 全部紧急警报弹窗 */}
      <DetailModal
        open={showAlertsModal}
        onClose={() => setShowAlertsModal(false)}
        title="全部紧急警报"
        subtitle={`共 ${data.alerts.length} 条警报`}
      >
        <EnhancedUrgentAlerts alerts={data.alerts} />
      </DetailModal>

      {/* 全部待办事项弹窗 */}
      <DetailModal
        open={showActionsModal}
        onClose={() => setShowActionsModal(false)}
        title="全部待办事项"
        subtitle={`共 ${data.actionItems.length} 条待办`}
      >
        <EnhancedActionList actionItems={data.actionItems} />
      </DetailModal>

      <PostDetailDrawer
        post={selectedPost}
        open={drawerOpen}
        onClose={handleCloseDrawer}
        favoriteIds={favoriteIds}
        onToggleFavorite={onToggleFavorite}
      />
    </>
  );
}
