import { useState } from 'react';
import { MapPin, ThumbsUp, Star, Activity, SearchX } from 'lucide-react';
import SectionCard from './SectionCard';
import DetailModal from './DetailModal';
import { getSubredditProfiles, type SubredditProfile as SubredditProfileType } from '../data/analyticsMock';
import type { TimeRange } from '../types';

interface SubredditProfileProps {
  timeRange?: TimeRange;
}

const vibeConfig: Record<string, { label: string; bg: string; text: string; desc: string }> = {
  '理性讨论型': {
    label: '理性讨论型',
    bg: 'bg-status-infoBg',
    text: 'text-status-info',
    desc: '用户倾向于分享经验、提供建议，讨论质量较高',
  },
  '情绪发泄型': {
    label: '情绪发泄型',
    bg: 'bg-status-errorBg',
    text: 'text-status-error',
    desc: '用户情绪表达强烈，需注意舆情风险',
  },
  '口碑分享型': {
    label: '口碑分享型',
    bg: 'bg-status-successBg',
    text: 'text-status-success',
    desc: '用户热衷分享使用体验和推荐，品牌好感度高',
  },
  '求助咨询型': {
    label: '求助咨询型',
    bg: 'bg-status-warningBg',
    text: 'text-status-warning',
    desc: '用户以提问和求助为主，是品牌介入的好时机',
  },
  '热闹围观型': {
    label: '热闹围观型',
    bg: 'bg-surface-warm',
    text: 'text-foreground-secondary',
    desc: '讨论活跃但品牌相关度一般，适合趋势观察',
  },
};

const qualityStars: Record<string, number> = {
  '高': 3,
  '中': 2,
  '低': 1,
};

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-foreground-muted">
      <SearchX className="w-12 h-12 mb-3 opacity-40" strokeWidth={1.5} />
      <p className="text-body-sm">{message}</p>
    </div>
  );
}

function ProfileCard({ profile }: { profile: SubredditProfileType }) {
  const vibe = vibeConfig[profile.vibe] || vibeConfig['理性讨论型'];
  const total = profile.sentiment.positive + profile.sentiment.neutral + profile.sentiment.negative;
  const posRate = Math.round((profile.sentiment.positive / total) * 100);

  return (
    <div className="card p-5 hover:shadow-card-hover transition-all duration-300 group">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-h4 font-semibold text-foreground">{profile.displayName}</span>
            {profile.worthInvesting && (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-badge bg-status-successBg text-status-success text-tiny">
                <Star className="w-3 h-3" strokeWidth={1.5} />
                推荐
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-caption text-foreground-muted">{profile.subscribers.toLocaleString()} 订阅者</span>
            <span className="text-caption text-foreground-muted">·</span>
            <span className="text-caption text-foreground-muted">{profile.postCount} 相关帖</span>
          </div>
        </div>
        <span className={`px-2.5 py-1 rounded-badge text-tiny font-medium ${vibe.bg} ${vibe.text}`}>
          {vibe.label}
        </span>
      </div>

      <div className="mb-4">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-caption text-foreground-muted">情感倾向</span>
          <span className="text-tiny font-medium text-status-success">{posRate}% 正面</span>
        </div>
        <div className="flex h-2 rounded-full overflow-hidden bg-surface-tertiary">
          <div className="h-full bg-status-success" style={{ width: `${(profile.sentiment.positive / total) * 100}%` }} />
          <div className="h-full bg-status-warning" style={{ width: `${(profile.sentiment.neutral / total) * 100}%` }} />
          <div className="h-full bg-status-error" style={{ width: `${(profile.sentiment.negative / total) * 100}%` }} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="rounded-icon bg-surface-tertiary p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <Activity className="w-3.5 h-3.5 text-foreground-muted" strokeWidth={1.5} />
            <span className="text-tiny text-foreground-muted">平均互动</span>
          </div>
          <span className="text-body font-semibold text-foreground">{profile.engagement}</span>
        </div>
        <div className="rounded-icon bg-surface-tertiary p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <ThumbsUp className="w-3.5 h-3.5 text-foreground-muted" strokeWidth={1.5} />
            <span className="text-tiny text-foreground-muted">Momcozy 提及</span>
          </div>
          <span className="text-body font-semibold text-foreground">{profile.momcozyMentions}</span>
        </div>
      </div>

      <div className="mb-3">
        <span className="text-tiny text-foreground-muted block mb-1.5">热门关键词</span>
        <div className="flex flex-wrap gap-1.5">
          {profile.topKeywords.slice(0, 4).map((k) => (
            <span key={k} className="px-2 py-0.5 rounded-badge bg-surface-tertiary text-caption text-foreground-secondary">
              {k}
            </span>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between pt-3 border-t border-border-divider">
        <div className="flex items-center gap-1">
          <span className="text-tiny text-foreground-muted">讨论质量</span>
          <div className="flex items-center gap-0.5">
            {Array.from({ length: 3 }).map((_, i) => (
              <Star
                key={i}
                className={`w-3 h-3 ${i < qualityStars[profile.quality] ? 'text-status-warning fill-status-warning' : 'text-border-hover'}`}
                strokeWidth={1.5}
              />
            ))}
          </div>
        </div>
        <span className="text-tiny text-foreground-muted">最近活跃 {profile.lastActive}</span>
      </div>
    </div>
  );
}

function ComparisonTable({ profiles }: { profiles: SubredditProfileType[] }) {
  return (
    <div className="overflow-x-auto -mx-6">
      <table className="w-full min-w-[640px]">
        <thead>
          <tr className="border-b border-border-divider">
            <th className="text-left px-6 py-3 text-tiny font-medium text-foreground-muted">社区</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">订阅者</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">相关帖</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">正面率</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">气质</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">质量</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">推荐</th>
          </tr>
        </thead>
        <tbody>
          {profiles.map((p) => {
            const total = p.sentiment.positive + p.sentiment.neutral + p.sentiment.negative;
            const posRate = Math.round((p.sentiment.positive / total) * 100);
            const vibe = vibeConfig[p.vibe] || vibeConfig['理性讨论型'];

            return (
              <tr key={p.name} className="border-b border-border-divider hover:bg-surface-tertiary/50 transition-colors">
                <td className="px-6 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-body-sm font-medium text-foreground">{p.displayName}</span>
                    {p.worthInvesting && <Star className="w-3.5 h-3.5 text-status-warning fill-status-warning" strokeWidth={1.5} />}
                  </div>
                </td>
                <td className="px-4 py-3 text-body-sm text-foreground-secondary">{p.subscribers.toLocaleString()}</td>
                <td className="px-4 py-3 text-body-sm text-foreground-secondary">{p.postCount}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 rounded-full bg-surface-tertiary overflow-hidden">
                      <div className="h-full bg-status-success rounded-full" style={{ width: `${posRate}%` }} />
                    </div>
                    <span className="text-body-sm font-medium text-status-success">{posRate}%</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-flex px-2 py-0.5 rounded-badge text-tiny ${vibe.bg} ${vibe.text}`}>
                    {vibe.label}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-0.5">
                    {Array.from({ length: 3 }).map((_, i) => (
                      <Star
                        key={i}
                        className={`w-3 h-3 ${i < qualityStars[p.quality] ? 'text-status-warning fill-status-warning' : 'text-border-hover'}`}
                        strokeWidth={1.5}
                      />
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3">
                  {p.worthInvesting ? (
                    <span className="inline-flex items-center gap-0.5 text-tiny text-status-success">
                      <ThumbsUp className="w-3 h-3" strokeWidth={1.5} />
                      值得投入
                    </span>
                  ) : (
                    <span className="text-tiny text-foreground-muted">观察</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function SubredditProfile({ timeRange = '7d' }: SubredditProfileProps) {
  const [viewMode, setViewMode] = useState<'card' | 'table'>('card');
  const [showModal, setShowModal] = useState(false);
  const profiles = getSubredditProfiles(timeRange);

  if (!profiles || profiles.length === 0) {
    return (
      <SectionCard
        title="子版块画像"
        subtitle="各 subreddit 的社区气质、讨论质量与投入价值评估"
        icon={<MapPin className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={{ label: '查看详情', onClick: () => setShowModal(true) }}
      >
        <EmptyState message="暂无子版块画像数据" />
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="子版块画像"
      subtitle="各 subreddit 的社区气质、讨论质量与投入价值评估"
      icon={<MapPin className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={{ label: '查看详情', onClick: () => setShowModal(true) }}
    >
      <div className="flex items-center gap-2 mb-5">
        {([
          { key: 'card' as const, label: '卡片视图' },
          { key: 'table' as const, label: '对比表格' },
        ]).map((v) => (
          <button
            key={v.key}
            onClick={() => setViewMode(v.key)}
            className={`px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
              viewMode === v.key
                ? 'bg-primary text-white'
                : 'bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm'
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {viewMode === 'card' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {profiles.map((p) => (
            <ProfileCard key={p.name} profile={p} />
          ))}
        </div>
      ) : (
        <ComparisonTable profiles={profiles} />
      )}

      <DetailModal
        open={showModal}
        onClose={() => setShowModal(false)}
        title="子版块画像详情"
        subtitle="各 subreddit 的社区气质、讨论质量与投入价值评估"
      >
        <ComparisonTable profiles={profiles} />
      </DetailModal>
    </SectionCard>
  );
}
