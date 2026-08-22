import { useState } from 'react';
import { Target, Calendar, Clock, MapPin, FileText, Lightbulb, Users, Package, Check, Play, Loader2, Circle, SearchX } from 'lucide-react';
import SectionCard from './SectionCard';
import DetailModal from './DetailModal';
import { strategyItems, timeline, bestTiming, type StrategyItem, type ExecutionStatus } from '../data/insightsMock';

const categoryConfig: Record<StrategyItem['category'], { label: string; icon: typeof Lightbulb; color: string; bg: string }> = {
  content: { label: '内容', icon: FileText, color: 'text-status-info', bg: 'bg-status-infoBg' },
  timing: { label: '时机', icon: Clock, color: 'text-status-warning', bg: 'bg-status-warningBg' },
  community: { label: '社区', icon: Users, color: 'text-status-success', bg: 'bg-status-successBg' },
  product: { label: '产品', icon: Package, color: 'text-primary', bg: 'bg-primary-light' },
};

const priorityConfig = {
  high: { label: '高', color: 'text-status-error', bg: 'bg-status-errorBg', border: 'border-status-error' },
  medium: { label: '中', color: 'text-status-warning', bg: 'bg-status-warningBg', border: 'border-status-warning' },
  low: { label: '低', color: 'text-foreground-muted', bg: 'bg-surface-tertiary', border: 'border-border' },
};

const executionConfig: Record<ExecutionStatus, { label: string; color: string; bg: string; icon: typeof Circle }> = {
  pending: { label: '待执行', color: 'text-foreground-muted', bg: 'bg-surface-tertiary', icon: Circle },
  executing: { label: '执行中', color: 'text-status-warning', bg: 'bg-status-warningBg', icon: Loader2 },
  completed: { label: '已完成', color: 'text-status-success', bg: 'bg-status-successBg', icon: Check },
};

/** 空状态组件 */
function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-foreground-muted">
      <SearchX className="w-12 h-12 mb-3 opacity-40" strokeWidth={1.5} />
      <p className="text-body-sm">{message}</p>
    </div>
  );
}

function StrategyCard({ item, onExecute }: { item: StrategyItem; onExecute: (id: string) => void }) {
  const cat = categoryConfig[item.category];
  const pri = priorityConfig[item.priority];
  const exec = executionConfig[item.executionStatus];
  const Icon = cat.icon;
  const ExecIcon = exec.icon;

  return (
    <div className="card p-5 hover:shadow-card-hover transition-all duration-300 group">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-badge text-tiny ${cat.bg} ${cat.color}`}>
            <Icon className="w-3 h-3" strokeWidth={1.5} />
            {cat.label}
          </span>
          <span className={`inline-flex items-center px-2 py-0.5 rounded-badge text-tiny border ${pri.bg} ${pri.color} ${pri.border}`}>
            {pri.label}优先级
          </span>
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-badge text-tiny ${exec.bg} ${exec.color}`}>
            <ExecIcon className={`w-3 h-3 ${item.executionStatus === 'executing' ? 'animate-spin' : ''}`} strokeWidth={1.5} />
            {exec.label}
          </span>
        </div>
      </div>
      <h4 className="text-body font-semibold text-foreground mb-2">{item.title}</h4>
      <p className="text-caption text-foreground-secondary leading-relaxed mb-4">{item.description}</p>
      <div className="flex items-center justify-between pt-3 border-t border-border-divider">
        <span className="text-tiny text-foreground-muted">
          状态: <span className={exec.color}>{exec.label}</span>
        </span>
        <button
          onClick={() => onExecute(item.id)}
          disabled={item.executionStatus === 'executing' || item.executionStatus === 'completed'}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
            item.executionStatus === 'completed'
              ? 'bg-status-successBg text-status-success cursor-default'
              : item.executionStatus === 'executing'
                ? 'bg-status-warningBg text-status-warning cursor-wait'
                : 'bg-primary text-white hover:bg-primary-hover shadow-button'
          }`}
        >
          {item.executionStatus === 'pending' && <><Play className="w-3 h-3" strokeWidth={1.5} /> 执行</>}
          {item.executionStatus === 'executing' && <><Loader2 className="w-3 h-3 animate-spin" strokeWidth={1.5} /> 执行中...</>}
          {item.executionStatus === 'completed' && <><Check className="w-3 h-3" strokeWidth={1.5} /> 已完成</>}
        </button>
      </div>
    </div>
  );
}

function TimingPanel() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Best time */}
      <div className="card p-5">
        <div className="flex items-center gap-2 mb-4">
          <Clock className="w-5 h-5 text-primary" strokeWidth={1.5} />
          <span className="text-body font-semibold text-foreground">最佳发帖时间</span>
        </div>
        <div className="space-y-2">
          {bestTiming.weekdays.map((d) => (
            <div key={d.day} className="flex items-center gap-3">
              <span className="text-caption text-foreground-secondary w-8">{d.day}</span>
              <div className="flex-1 h-2 rounded-full bg-surface-tertiary overflow-hidden">
                <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${d.score}%` }} />
              </div>
              <span className="text-tiny text-foreground-muted w-24 text-right">{d.time}</span>
            </div>
          ))}
        </div>
        <div className="mt-4 p-3 rounded-icon bg-primary-light">
          <span className="text-tiny text-primary">💡 推荐在周二/周四 21:00-23:00 发布内容，此时美国用户晚间活跃度最高</span>
        </div>
      </div>

      {/* Recommended subreddits */}
      <div className="card p-5">
        <div className="flex items-center gap-2 mb-4">
          <MapPin className="w-5 h-5 text-primary" strokeWidth={1.5} />
          <span className="text-body font-semibold text-foreground">推荐社区</span>
        </div>
        <div className="space-y-3">
          {bestTiming.recommendedSubreddits.map((sub) => (
            <div key={sub.name} className="flex items-center justify-between p-3 rounded-icon bg-surface-tertiary">
              <div className="flex items-center gap-3">
                <span className="text-body-sm font-medium text-foreground">r/{sub.name}</span>
                <span className={`px-1.5 py-0.5 rounded-badge text-tiny font-medium ${
                  sub.priority === 'P0' ? 'bg-status-errorBg text-status-error' : sub.priority === 'P1' ? 'bg-status-warningBg text-status-warning' : 'bg-surface-tertiary text-foreground-muted border border-border'
                }`}>
                  {sub.priority}
                </span>
              </div>
              <span className="text-caption text-foreground-muted text-right">{sub.reason}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TimelinePanel() {
  return (
    <div className="card p-5">
      <div className="flex items-center gap-2 mb-5">
        <Calendar className="w-5 h-5 text-primary" strokeWidth={1.5} />
        <span className="text-body font-semibold text-foreground">30 天行动计划</span>
      </div>
      <div className="space-y-4">
        {timeline.map((item, idx) => (
          <div key={idx} className="flex gap-4">
            <div className="flex flex-col items-center">
              <div className="w-8 h-8 rounded-full bg-primary-light flex items-center justify-center flex-shrink-0">
                <span className="text-tiny font-semibold text-primary">{idx + 1}</span>
              </div>
              {idx < timeline.length - 1 && <div className="w-px flex-1 bg-border-divider my-1" />}
            </div>
            <div className="flex-1 pb-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-body-sm font-semibold text-foreground">{item.week}</span>
                <span className="text-tiny text-foreground-muted">{item.title}</span>
              </div>
              <ul className="space-y-1.5">
                {item.tasks.map((task, tidx) => (
                  <li key={tidx} className="flex items-start gap-2">
                    <Check className="w-3.5 h-3.5 text-status-success mt-0.5 flex-shrink-0" strokeWidth={2} />
                    <span className="text-caption text-foreground-secondary">{task}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-2 p-2 rounded-icon bg-surface-warm">
                <span className="text-tiny text-foreground-muted">🎯 目标：{item.goal}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface StrategyPanelProps {
  strategies?: StrategyItem[];
}

export default function StrategyPanel({ strategies: externalStrategies }: StrategyPanelProps) {
  const [activeFilter, setActiveFilter] = useState<'all' | StrategyItem['category']>('all');
  const [showModal, setShowModal] = useState(false);
  const [strategies, setStrategies] = useState<StrategyItem[]>(externalStrategies || strategyItems);

  const handleExecute = (id: string) => {
    setStrategies((prev) =>
      prev.map((s) => {
        if (s.id !== id) return s;
        if (s.executionStatus === 'pending') {
          return { ...s, executionStatus: 'completed' as ExecutionStatus };
        }
        return s;
      })
    );
  };

  const filtered = activeFilter === 'all' ? strategies : strategies.filter((s) => s.category === activeFilter);

  if (!strategies || strategies.length === 0) {
    return (
      <div className="space-y-6">
        <SectionCard
          title="营销策略建议"
          subtitle="基于数据分析自动生成可执行的 Reddit 营销策略"
          icon={<Target className="w-5 h-5 text-primary" strokeWidth={1.5} />}
          action={{ label: '全部策略', onClick: () => setShowModal(true) }}
        >
          <EmptyState message="暂无策略建议数据" />
        </SectionCard>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SectionCard
        title="营销策略建议"
        subtitle="基于数据分析自动生成可执行的 Reddit 营销策略"
        icon={<Target className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={{ label: '全部策略', onClick: () => setShowModal(true) }}
      >
        {/* Filter */}
        <div className="flex items-center gap-2 mb-5">
          {([
            { key: 'all' as const, label: '全部' },
            { key: 'content' as const, label: '内容' },
            { key: 'community' as const, label: '社区' },
            { key: 'timing' as const, label: '时机' },
            { key: 'product' as const, label: '产品' },
          ]).map((f) => (
            <button
              key={f.key}
              onClick={() => setActiveFilter(f.key)}
              className={`px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
                activeFilter === f.key
                  ? 'bg-primary text-white'
                  : 'bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((item) => (
            <StrategyCard key={item.id} item={item} onExecute={handleExecute} />
          ))}
        </div>
      </SectionCard>

      <TimingPanel />

      <TimelinePanel />

      <DetailModal
        open={showModal}
        onClose={() => setShowModal(false)}
        title="全部策略"
        subtitle="基于数据分析自动生成的 Reddit 营销策略完整列表"
      >
        <div className="space-y-4">
          {strategies.map((item) => (
            <StrategyCard key={item.id} item={item} onExecute={handleExecute} />
          ))}
        </div>
      </DetailModal>
    </div>
  );
}
