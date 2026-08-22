import { useState } from 'react';
import { Search, Hash, Plus, ToggleLeft, ToggleRight, Clock, Filter, Trash2, Play, AlertTriangle, Loader2, Inbox, Layers, Tag } from 'lucide-react';
import { usePersistentState } from '../hooks';
import SectionCard from './SectionCard';
import { keywordRules, subredditRules, searchConfig, typeConfig, tierConfig, type SearchConfig, type KeywordRule, type SubredditRule, type KeywordType, type SubredditTier } from '../data/searchMock';

interface KeywordManagerProps {
  keywords: KeywordRule[];
  setKeywords: React.Dispatch<React.SetStateAction<KeywordRule[]>>;
}

function KeywordManager({ keywords, setKeywords }: KeywordManagerProps) {
  const [newKeyword, setNewKeyword] = useState('');
  const [newType, setNewType] = useState<KeywordType>('general');

  const addKeyword = () => {
    if (newKeyword.trim() && !keywords.find((k) => k.label === newKeyword.trim())) {
      setKeywords([
        ...keywords,
        {
          id: `k${Date.now()}`,
          label: newKeyword.trim(),
          type: newType,
          active: true,
          matchCount: 0,
          createdAt: new Date().toISOString().slice(0, 10),
        },
      ]);
      setNewKeyword('');
    }
  };

  const toggleKeyword = (id: string) => {
    setKeywords(keywords.map((k) => (k.id === id ? { ...k, active: !k.active } : k)));
  };

  const removeKeyword = (id: string) => {
    setKeywords(keywords.filter((k) => k.id !== id));
  };

  return (
    <SectionCard
      title="关键词管理"
      subtitle={`已配置 ${keywords.filter((k) => k.active).length}/${keywords.length} 个监测关键词`}
      icon={<Hash className="w-5 h-5 text-primary" strokeWidth={1.5} />}
    >
      {/* Add new */}
      <div className="flex items-center gap-2 mb-5">
        <div className="relative flex-1">
          <input
            type="text"
            value={newKeyword}
            onChange={(e) => setNewKeyword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addKeyword()}
            placeholder="添加新关键词..."
            className="input-field"
          />
        </div>
        <select
          value={newType}
          onChange={(e) => setNewType(e.target.value as KeywordType)}
          className="input-field w-28 text-body-sm"
        >
          <option value="brand">品牌词</option>
          <option value="product">产品词</option>
          <option value="competitor">竞品词</option>
          <option value="general">通用词</option>
        </select>
        <button onClick={addKeyword} className="btn-primary px-4 py-3">
          <Plus className="w-4 h-4" strokeWidth={1.5} />
        </button>
      </div>

      {/* List */}
      {keywords.length > 0 ? (
        <div className="space-y-2">
          {keywords.map((k) => {
            const tc = typeConfig[k.type];
            return (
              <div
                key={k.id}
                className={`flex items-center gap-3 p-3 rounded-icon transition-all ${
                  k.active ? 'bg-white border border-border-divider' : 'bg-surface-tertiary opacity-60'
                }`}
              >
                <button
                  onClick={() => toggleKeyword(k.id)}
                  className={`flex-shrink-0 ${k.active ? 'text-status-success' : 'text-foreground-muted'}`}
                >
                  {k.active ? <ToggleRight className="w-5 h-5" strokeWidth={1.5} /> : <ToggleLeft className="w-5 h-5" strokeWidth={1.5} />}
                </button>

                <span className="text-body-sm font-medium text-foreground w-32 truncate">{k.label}</span>

                <span className={`px-2 py-0.5 rounded-badge text-tiny ${tc.bg} ${tc.color}`}>{tc.label}</span>

                <span className="text-caption text-foreground-muted ml-auto">{k.matchCount} 匹配</span>

                <button
                  onClick={() => removeKeyword(k.id)}
                  className="text-foreground-muted hover:text-status-error transition-colors"
                >
                  <Trash2 className="w-4 h-4" strokeWidth={1.5} />
                </button>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-8 text-foreground-muted">
          <Inbox className="w-10 h-10 mb-3 opacity-40" strokeWidth={1.5} />
          <p className="text-body-sm">暂无关键词</p>
          <p className="text-caption mt-1">添加关键词开始监测</p>
        </div>
      )}
    </SectionCard>
  );
}

interface SubredditManagerProps {
  subs: SubredditRule[];
  setSubs: React.Dispatch<React.SetStateAction<SubredditRule[]>>;
}

function SubredditManager({ subs, setSubs }: SubredditManagerProps) {
  const [newSub, setNewSub] = useState('');
  const [newTier, setNewTier] = useState<SubredditTier>('B');

  const addSubreddit = () => {
    if (newSub.trim() && !subs.find((s) => s.name === newSub.trim())) {
      setSubs([
        ...subs,
        {
          id: `s${Date.now()}`,
          name: newSub.trim(),
          displayName: `r/${newSub.trim()}`,
          subscribers: 0,
          active: true,
          postCount: 0,
          lastFetched: '尚未抓取',
          tier: newTier,
        },
      ]);
      setNewSub('');
    }
  };

  const toggleSub = (id: string) => {
    setSubs(subs.map((s) => (s.id === id ? { ...s, active: !s.active } : s)));
  };

  const changeTier = (id: string, tier: SubredditTier) => {
    setSubs(subs.map((s) => (s.id === id ? { ...s, tier } : s)));
  };

  const removeSub = (id: string) => {
    setSubs(subs.filter((s) => s.id !== id));
  };

  return (
    <SectionCard
      title="社区管理"
      subtitle={`已配置 ${subs.filter((s) => s.active).length}/${subs.length} 个监测 subreddit`}
      icon={<Hash className="w-5 h-5 text-primary" strokeWidth={1.5} />}
    >
      <div className="flex items-center gap-2 mb-5">
        <div className="relative flex-1">
          <input
            type="text"
            value={newSub}
            onChange={(e) => setNewSub(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addSubreddit()}
            placeholder="输入 subreddit 名称..."
            className="input-field pl-10"
          />
          <Hash className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground-muted" strokeWidth={1.5} />
        </div>
        <select
          value={newTier}
          onChange={(e) => setNewTier(e.target.value as SubredditTier)}
          className="input-field w-20 text-body-sm"
        >
          <option value="A">A类</option>
          <option value="B">B类</option>
          <option value="C">C类</option>
        </select>
        <button onClick={addSubreddit} className="btn-primary px-4 py-3">
          <Plus className="w-4 h-4" strokeWidth={1.5} />
        </button>
      </div>

      {subs.length > 0 ? (
        <div className="space-y-2">
          {subs.map((s) => {
            const tier = tierConfig[s.tier];
            return (
              <div
                key={s.id}
                className={`flex items-center gap-3 p-3 rounded-icon transition-all ${
                  s.active ? 'bg-white border border-border-divider' : 'bg-surface-tertiary opacity-60'
                }`}
              >
                <button
                  onClick={() => toggleSub(s.id)}
                  className={`flex-shrink-0 ${s.active ? 'text-status-success' : 'text-foreground-muted'}`}
                >
                  {s.active ? <ToggleRight className="w-5 h-5" strokeWidth={1.5} /> : <ToggleLeft className="w-5 h-5" strokeWidth={1.5} />}
                </button>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-body-sm font-medium text-foreground">{s.displayName}</span>
                    <span className={`px-1.5 py-0.5 rounded-badge text-[11px] font-medium ${tier.bg} ${tier.color} border ${tier.border}`}>
                      {tier.label}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-tiny text-foreground-muted">{s.subscribers.toLocaleString()} 订阅者</span>
                    <span className="text-tiny text-foreground-muted">·</span>
                    <span className="text-tiny text-foreground-muted">{s.postCount} 相关帖</span>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <select
                    value={s.tier}
                    onChange={(e) => changeTier(s.id, e.target.value as SubredditTier)}
                    className="input-field w-16 py-1.5 px-2 text-tiny"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <option value="A">A类</option>
                    <option value="B">B类</option>
                    <option value="C">C类</option>
                  </select>
                  <span className="text-caption text-foreground-muted">{s.lastFetched}</span>
                  <button
                    onClick={() => removeSub(s.id)}
                    className="text-foreground-muted hover:text-status-error transition-colors"
                  >
                    <Trash2 className="w-4 h-4" strokeWidth={1.5} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-8 text-foreground-muted">
          <Inbox className="w-10 h-10 mb-3 opacity-40" strokeWidth={1.5} />
          <p className="text-body-sm">暂无社区</p>
          <p className="text-caption mt-1">添加 subreddit 开始监测</p>
        </div>
      )}
    </SectionCard>
  );
}

interface SearchSettingsProps {
  config: SearchConfig;
  setConfig: React.Dispatch<React.SetStateAction<SearchConfig>>;
}

function SearchSettings({ config, setConfig }: SearchSettingsProps) {
  const toggleKeywordType = (type: KeywordType) => {
    const next = config.keywordTypeFilter.includes(type)
      ? config.keywordTypeFilter.filter((t) => t !== type)
      : [...config.keywordTypeFilter, type];
    setConfig({ ...config, keywordTypeFilter: next });
  };

  const toggleSubredditTier = (tier: SubredditTier) => {
    const next = config.subredditTierFilter.includes(tier)
      ? config.subredditTierFilter.filter((t) => t !== tier)
      : [...config.subredditTierFilter, tier];
    setConfig({ ...config, subredditTierFilter: next });
  };

  return (
    <SectionCard
      title="搜索配置"
      subtitle="调整监测规则与过滤条件"
      icon={<Filter className="w-5 h-5 text-primary" strokeWidth={1.5} />}
    >
      <div className="space-y-5">
        {/* Time Range */}
        <div>
          <label className="text-body-sm font-medium text-foreground block mb-2">时间范围</label>
          <div className="flex items-center gap-2">
            {(['7d', '30d', '90d'] as const).map((r) => (
              <button
                key={r}
                onClick={() => setConfig({ ...config, timeRange: r })}
                className={`px-4 py-2 rounded-button text-body-sm font-medium transition-all ${
                  config.timeRange === r
                    ? 'bg-primary text-white'
                    : 'bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm'
                }`}
              >
                {r === '7d' ? '近7天' : r === '30d' ? '近30天' : '近90天'}
              </button>
            ))}
          </div>
        </div>

        {/* Keyword Type Filter */}
        <div>
          <label className="text-body-sm font-medium text-foreground block mb-2">关键词类型监控</label>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(typeConfig) as KeywordType[]).map((type) => {
              const tc = typeConfig[type];
              const active = config.keywordTypeFilter.includes(type);
              return (
                <button
                  key={type}
                  onClick={() => toggleKeywordType(type)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-tiny font-medium transition-all border ${
                    active
                      ? `${tc.bg} ${tc.color} ${tc.border}`
                      : 'bg-surface-tertiary text-foreground-muted border-transparent hover:text-foreground'
                  }`}
                >
                  <Tag className="w-3.5 h-3.5" strokeWidth={1.5} />
                  {tc.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Subreddit Tier Filter */}
        <div>
          <label className="text-body-sm font-medium text-foreground block mb-2">社区分层监控</label>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(tierConfig) as SubredditTier[]).map((tier) => {
              const tc = tierConfig[tier];
              const active = config.subredditTierFilter.includes(tier);
              return (
                <button
                  key={tier}
                  onClick={() => toggleSubredditTier(tier)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-tiny font-medium transition-all border ${
                    active
                      ? `${tc.bg} ${tc.color} ${tc.border}`
                      : 'bg-surface-tertiary text-foreground-muted border-transparent hover:text-foreground'
                  }`}
                >
                  <Layers className="w-3.5 h-3.5" strokeWidth={1.5} />
                  {tc.label}
                </button>
              );
            })}
          </div>
          <p className="text-tiny text-foreground-muted mt-1.5">
            A类为核心社区（高优先级），B类为重要社区（中优先级），C类为一般社区（低优先级）
          </p>
        </div>

        {/* AI Filter */}
        <div className="flex items-center justify-between p-4 rounded-icon bg-surface-warm">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-icon bg-primary-light flex items-center justify-center">
              <Filter className="w-4 h-4 text-primary" strokeWidth={1.5} />
            </div>
            <div>
              <span className="text-body-sm font-medium text-foreground">AI 智能过滤</span>
              <p className="text-caption text-foreground-muted">自动过滤低质量、不相关的帖子</p>
            </div>
          </div>
          <button
            onClick={() => setConfig({ ...config, aiFilter: !config.aiFilter })}
            className={config.aiFilter ? 'text-status-success' : 'text-foreground-muted'}
          >
            {config.aiFilter ? <ToggleRight className="w-7 h-7" strokeWidth={1.5} /> : <ToggleLeft className="w-7 h-7" strokeWidth={1.5} />}
          </button>
        </div>

        {/* Min Upvotes */}
        <div>
          <label className="text-body-sm font-medium text-foreground block mb-2">
            最小 upvotes 阈值 <span className="text-caption text-foreground-muted font-normal">（过滤低互动帖子）</span>
          </label>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={0}
              max={50}
              value={config.minUpvotes}
              onChange={(e) => setConfig({ ...config, minUpvotes: parseInt(e.target.value) })}
              className="flex-1 accent-primary"
            />
            <span className="text-body font-semibold text-foreground w-12 text-right">{config.minUpvotes}</span>
          </div>
        </div>

        {/* Auto Notify */}
        <div className="flex items-center justify-between p-4 rounded-icon bg-surface-warm">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-icon bg-primary-light flex items-center justify-center">
              <Clock className="w-4 h-4 text-primary" strokeWidth={1.5} />
            </div>
            <div>
              <span className="text-body-sm font-medium text-foreground">自动通知</span>
              <p className="text-caption text-foreground-muted">新帖出现时自动推送通知</p>
            </div>
          </div>
          <button
            onClick={() => setConfig({ ...config, autoNotify: !config.autoNotify })}
            className={config.autoNotify ? 'text-status-success' : 'text-foreground-muted'}
          >
            {config.autoNotify ? <ToggleRight className="w-7 h-7" strokeWidth={1.5} /> : <ToggleLeft className="w-7 h-7" strokeWidth={1.5} />}
          </button>
        </div>
      </div>
    </SectionCard>
  );
}

interface PreviewPanelProps {
  keywords: KeywordRule[];
  subs: SubredditRule[];
  config: SearchConfig;
  isApplying: boolean;
  onApply: () => void;
}

function PreviewPanel({ keywords, subs, config, isApplying, onApply }: PreviewPanelProps) {
  const activeKeywords = keywords.filter((k) => k.active && config.keywordTypeFilter.includes(k.type));
  const activeSubs = subs.filter((s) => s.active && config.subredditTierFilter.includes(s.tier));

  const tierCounts = {
    A: activeSubs.filter((s) => s.tier === 'A').length,
    B: activeSubs.filter((s) => s.tier === 'B').length,
    C: activeSubs.filter((s) => s.tier === 'C').length,
  };

  return (
    <SectionCard
      title="监测规则预览"
      subtitle="当前配置预计抓取范围"
      icon={<AlertTriangle className="w-5 h-5 text-primary" strokeWidth={1.5} />}
    >
      <div className="space-y-4">
        <div className="flex items-center gap-4 p-4 rounded-icon bg-surface-warm">
          <div className="w-12 h-12 rounded-full bg-primary-light flex items-center justify-center flex-shrink-0">
            <Search className="w-5 h-5 text-primary" strokeWidth={1.5} />
          </div>
          <div>
            <p className="text-body font-semibold text-foreground">预计监测范围</p>
            <p className="text-caption text-foreground-secondary">
              {activeKeywords.length} 个关键词 × {activeSubs.length} 个社区 = 每日约抓取 50-80 条帖子
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="p-4 rounded-icon bg-white border border-border-divider">
            <span className="text-tiny text-foreground-muted block mb-1">活跃关键词</span>
            <span className="text-h3 font-semibold text-foreground">{activeKeywords.length}</span>
            <div className="flex flex-wrap gap-1 mt-2">
              {activeKeywords.slice(0, 4).map((k) => (
                <span key={k.id} className="px-2 py-0.5 rounded-badge text-tiny bg-surface-tertiary text-foreground-secondary">
                  {k.label}
                </span>
              ))}
              {activeKeywords.length > 4 && (
                <span className="px-2 py-0.5 rounded-badge text-tiny bg-surface-tertiary text-foreground-muted">
                  +{activeKeywords.length - 4}
                </span>
              )}
            </div>
          </div>

          <div className="p-4 rounded-icon bg-white border border-border-divider">
            <span className="text-tiny text-foreground-muted block mb-1">活跃社区</span>
            <span className="text-h3 font-semibold text-foreground">{activeSubs.length}</span>
            <div className="flex flex-wrap gap-1 mt-2">
              {activeSubs.slice(0, 4).map((s) => (
                <span key={s.id} className="px-2 py-0.5 rounded-badge text-tiny bg-surface-tertiary text-foreground-secondary">
                  {s.name}
                </span>
              ))}
              {activeSubs.length > 4 && (
                <span className="px-2 py-0.5 rounded-badge text-tiny bg-surface-tertiary text-foreground-muted">
                  +{activeSubs.length - 4}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Tier Breakdown */}
        <div className="grid grid-cols-3 gap-3">
          {(Object.entries(tierConfig) as [SubredditTier, typeof tierConfig['A']][]).map(([tier, tc]) => (
            <div key={tier} className={`p-3 rounded-icon border ${tc.bg} ${tc.border} text-center`}>
              <span className={`text-h3 font-semibold ${tc.color}`}>{tierCounts[tier]}</span>
              <span className={`text-tiny block mt-0.5 ${tc.color}`}>{tc.label}社区</span>
            </div>
          ))}
        </div>

        <button
          onClick={onApply}
          disabled={isApplying}
          className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isApplying ? (
            <Loader2 className="w-4 h-4 animate-spin" strokeWidth={1.5} />
          ) : (
            <Play className="w-4 h-4" strokeWidth={1.5} />
          )}
          {isApplying ? '应用中...' : '应用配置并开始监测'}
        </button>
      </div>
    </SectionCard>
  );
}

export default function SearchConfig() {
  const [keywords, setKeywords] = usePersistentState<KeywordRule[]>('momcozy_search_keywords_v1', 1, keywordRules);
  const [subs, setSubs] = usePersistentState<SubredditRule[]>('momcozy_search_subreddits_v1', 1, subredditRules);
  const [config, setConfig] = usePersistentState<SearchConfig>('momcozy_search_config_v1', 1, searchConfig);
  const [isApplying, setIsApplying] = useState(false);

  const handleApply = () => {
    setIsApplying(true);
    setTimeout(() => {
      setIsApplying(false);
    }, 1500);
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <KeywordManager keywords={keywords} setKeywords={setKeywords} />
        <SubredditManager subs={subs} setSubs={setSubs} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SearchSettings config={config} setConfig={setConfig} />
        <PreviewPanel keywords={keywords} subs={subs} config={config} isApplying={isApplying} onApply={handleApply} />
      </div>
    </div>
  );
}
