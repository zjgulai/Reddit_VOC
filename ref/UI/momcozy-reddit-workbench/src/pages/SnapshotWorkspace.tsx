import { useMemo } from 'react';
import {
  Activity,
  Archive,
  BookOpenCheck,
  CircleHelp,
  Database,
  ExternalLink,
  FileCheck2,
  FileText,
  MessageSquareWarning,
  PackageSearch,
  Scale,
  Search,
  ShieldAlert,
  Tags,
  TrendingUp,
} from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import ExportButton from '../components/ExportButton';
import SectionCard from '../components/SectionCard';
import { BarChart, PieChart } from '../components/charts';
import { SnapshotMetricCard } from '../features/redditSnapshot/SnapshotMetricCard';
import { createBaseDataFreshness } from '../features/redditSnapshot/freshness';
import { buildSnapshotEvidenceHref } from '../features/redditSnapshot/evidenceLinks';
import {
  SnapshotErrorPage,
  SnapshotLoadingPage,
  SnapshotPageLayout,
} from '../features/redditSnapshot/SnapshotPageLayout';
import {
  decodeHtmlEntities,
  formatDateTime,
  formatTopic,
  SENTIMENT_LABELS,
} from '../features/redditSnapshot/format';
import {
  highValueContent,
  isMomcozyPost,
  prioritySignals,
  tagNames,
} from '../features/redditSnapshot/operational';
import type { SnapshotPost, SnapshotSentiment } from '../features/redditSnapshot/types';
import { useRedditSnapshot } from '../features/redditSnapshot/useRedditSnapshot';

export type SnapshotWorkspaceKind = 'content' | 'signals' | 'definitions';

const sentimentStyles: Record<SnapshotSentiment, string> = {
  positive: 'bg-status-successBg text-status-success',
  neutral: 'bg-surface-tertiary text-foreground-secondary',
  negative: 'bg-status-errorBg text-status-error',
};

const severityLabels: Record<string, string> = {
  high: '高严重度',
  medium: '中严重度',
  low: '低严重度',
};

function PostList({
  posts,
  snapshot,
  mode,
}: {
  posts: SnapshotPost[];
  snapshot: NonNullable<ReturnType<typeof useRedditSnapshot>['data']>;
  mode: 'content' | 'signals';
}) {
  return (
    <div className="divide-y divide-border-divider">
      {posts.map((post, index) => {
        const names = tagNames(post, snapshot.tagRulesById, 3);
        const product = post.product_bindings?.[0];
        return (
          <article key={post.post_id} className="py-5 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-tiny text-foreground-muted">
                  <span className="font-semibold text-primary">#{index + 1}</span>
                  <span>r/{post.subreddit || 'unknown'}</span>
                  <span>·</span>
                  <time dateTime={post.created_at_utc}>{formatDateTime(post.created_at_utc)}</time>
                  <span className={`rounded-badge px-2 py-0.5 ${sentimentStyles[post.analysis.sentiment_label]}`}>
                    {SENTIMENT_LABELS[post.analysis.sentiment_label]}
                  </span>
                  <span className={`rounded-badge px-2 py-0.5 ${post.analysis.severity === 'high' ? 'bg-status-errorBg text-status-error' : 'bg-surface-tertiary text-foreground-secondary'}`}>
                    {severityLabels[post.analysis.severity] ?? post.analysis.severity}
                  </span>
                </div>
                <h3 className="mt-2 text-body font-semibold leading-snug text-foreground">{decodeHtmlEntities(post.title)}</h3>
                <p className="mt-2 line-clamp-2 text-body-sm leading-6 text-foreground-secondary">{decodeHtmlEntities(post.content)}</p>
                <div className="mt-3 flex flex-wrap gap-2 text-tiny">
                  <span className="rounded-badge bg-primary-light px-2 py-0.5 text-primary">{formatTopic(post.analysis.topic)}</span>
                  {product && (
                    <span className="rounded-badge bg-[#FFF4EA] px-2 py-0.5 text-[#B65C12]">
                      {product.exact_spu?.spu_name ?? product.product_family?.name_cn ?? product.category.name_cn}
                    </span>
                  )}
                  {names.map((name) => (
                    <span key={name} className="rounded-badge bg-surface-tertiary px-2 py-0.5 text-foreground-secondary">{name}</span>
                  ))}
                </div>
              </div>
              <div className="grid min-w-36 grid-cols-2 gap-2 text-center text-tiny">
                <div className="rounded-icon bg-surface-tertiary px-3 py-2">
                  <p className="text-body-sm font-semibold text-foreground">{post.linked_comment_count}</p>
                  <p className="text-foreground-muted">关联评论</p>
                </div>
                <div className="rounded-icon bg-surface-tertiary px-3 py-2">
                  <p className="text-body-sm font-semibold text-foreground">{post.score}</p>
                  <p className="text-foreground-muted">Score</p>
                </div>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Link
                to={buildSnapshotEvidenceHref({
                  postId: post.post_id,
                  releaseId: snapshot.release.release_id,
                  snapshotId: snapshot.manifest.dataset_version,
                  source: mode,
                })}
                className="text-caption font-medium text-primary hover:underline"
              >
                <Search className="mr-1 inline h-3.5 w-3.5" strokeWidth={1.5} />查看帖子与评论证据
              </Link>
              <a href={post.permalink} target="_blank" rel="noopener noreferrer" className="text-caption text-foreground-muted hover:text-primary">
                <ExternalLink className="mr-1 inline h-3.5 w-3.5" strokeWidth={1.5} />Reddit 原文
              </a>
              <span className="ml-auto text-tiny text-foreground-muted">
                {mode === 'content' ? '仅供内容分析 · 商业复用需另行确认授权' : '观察信号 · 不代表已回复或已处置'}
              </span>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function HighValueContentPage({ snapshot }: { snapshot: NonNullable<ReturnType<typeof useRedditSnapshot>['data']> }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSentiment = searchParams.get('sentiment');
  const sentiment: SnapshotSentiment | 'all' = requestedSentiment === 'positive'
    || requestedSentiment === 'neutral'
    || requestedSentiment === 'negative'
    ? requestedSentiment
    : 'all';
  const setSentiment = (nextSentiment: SnapshotSentiment | 'all') => {
    const next = new URLSearchParams(searchParams);
    if (nextSentiment === 'all') next.delete('sentiment');
    else next.set('sentiment', nextSentiment);
    setSearchParams(next, { replace: true });
  };
  const candidates = useMemo(() => highValueContent(snapshot), [snapshot]);
  const filtered = candidates.filter((post) => sentiment === 'all' || post.analysis.sentiment_label === sentiment);
  const strictCandidates = candidates.filter((post) => (
    post.analysis.severity !== 'low'
    && (post.score >= 10 || post.linked_comment_count >= 10)
  ));
  const productBound = candidates.filter((post) => (post.product_bindings?.length ?? 0) > 0).length;
  const withComments = candidates.filter((post) => post.linked_comment_count > 0).length;
  const topicCounts = Object.entries(candidates.reduce<Record<string, number>>((counts, post) => {
    counts[post.analysis.topic] = (counts[post.analysis.topic] ?? 0) + 1;
    return counts;
  }, {})).sort((left, right) => right[1] - left[1]).slice(0, 8);

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SnapshotMetricCard icon={Archive} value={candidates.length} label="真实内容机会" note="Momcozy 相关、正文非空，且 Score≥5 或关联评论≥5" />
        <SnapshotMetricCard icon={FileCheck2} value={strictCandidates.length} label="优先精选" note="中高严重度，且 Score≥10 或关联评论≥10；用于优先阅读" tone="warning" />
        <SnapshotMetricCard icon={PackageSearch} value={productBound} label="已绑定品类/SPU" note="至少命中品类、产品族或受控 SPU 之一" tone="success" />
        <SnapshotMetricCard icon={MessageSquareWarning} value={withComments} label="带评论上下文" note="至少有 1 条已关联评论，可进入帖子+评论证据核查" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <SectionCard title="内容机会主题构成" subtitle="真实候选帖子按 analysis.topic 聚合" tag="品类" icon={<Tags className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
          <BarChart data={topicCounts.map(([name, value]) => ({ name: formatTopic(name), value }))} height={280} />
        </SectionCard>
        <SectionCard title="内容情感构成" subtitle="仅描述候选内容，不代表授权、转化或商业价值" tag="舆情" icon={<Scale className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
          <PieChart
            data={(['positive', 'neutral', 'negative'] as const).map((value) => ({
              name: SENTIMENT_LABELS[value],
              value: candidates.filter((post) => post.analysis.sentiment_label === value).length,
              color: value === 'positive' ? '#18A874' : value === 'negative' ? '#E85D75' : '#98A2B3',
            }))}
            innerRadius={0.58}
            height={280}
          />
        </SectionCard>
      </div>

      <section className="card p-5 sm:p-6" aria-labelledby="content-opportunity-title">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 id="content-opportunity-title" className="text-h3 text-foreground">高价值内容池</h2>
            <p className="mt-1 text-caption text-foreground-muted">先按关联评论数、再按 Score 确定性排序；展示前 20 条</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label="内容情感筛选" value={sentiment} onChange={(event) => setSentiment(event.target.value as SnapshotSentiment | 'all')} className="input-field min-w-32">
              <option value="all">全部情感</option>
              <option value="positive">正面</option>
              <option value="neutral">中性</option>
              <option value="negative">负面</option>
            </select>
            <ExportButton
              size="sm"
              filename="Momcozy_Reddit_高价值内容池"
              title="Momcozy Reddit 高价值内容池"
              data={filtered.map((post) => ({
                帖子ID: post.post_id,
                标题: post.title,
                社区: post.subreddit,
                情感: SENTIMENT_LABELS[post.analysis.sentiment_label],
                严重度: severityLabels[post.analysis.severity] ?? post.analysis.severity,
                Score: post.score,
                关联评论: post.linked_comment_count,
                Reddit链接: post.permalink,
              }))}
            />
          </div>
        </div>
        <PostList posts={filtered.slice(0, 20)} snapshot={snapshot} mode="content" />
      </section>
    </>
  );
}

function SignalCenterPage({ snapshot }: { snapshot: NonNullable<ReturnType<typeof useRedditSnapshot>['data']> }) {
  const signals = useMemo(() => prioritySignals(snapshot), [snapshot]);
  const highSeverity = signals.filter((post) => post.analysis.severity === 'high').length;
  const negative = signals.filter((post) => post.analysis.sentiment_label === 'negative').length;
  const linkedComments = signals.reduce((sum, post) => sum + post.linked_comment_count, 0);
  const topicCounts = Object.entries(signals.reduce<Record<string, number>>((counts, post) => {
    counts[post.analysis.topic] = (counts[post.analysis.topic] ?? 0) + 1;
    return counts;
  }, {})).sort((left, right) => right[1] - left[1]);

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SnapshotMetricCard icon={ShieldAlert} value={signals.length} label="优先舆情信号" note="Momcozy 相关且为负面或高严重度，并达到最低互动量" tone="warning" />
        <SnapshotMetricCard icon={Activity} value={highSeverity} label="高严重度帖子" note="来自现有 analysis.severity；是观察优先级，不是危机定级" tone="warning" />
        <SnapshotMetricCard icon={MessageSquareWarning} value={negative} label="负面帖子" note="来自现有 analysis.sentiment_label=negative" />
        <SnapshotMetricCard icon={TrendingUp} value={linkedComments} label="关联评论上下文" note="信号帖已关联评论总数，用于核查讨论放大程度" tone="success" />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <SectionCard title="风险主题分布" subtitle="优先队列按帖子主题聚合" tag="舆情" icon={<ShieldAlert className="h-5 w-5 text-primary" strokeWidth={1.5} />} className="xl:col-span-2">
          <BarChart data={topicCounts.slice(0, 8).map(([name, value]) => ({ name: formatTopic(name), value }))} height={280} />
        </SectionCard>
        <section className="card p-6" aria-labelledby="signal-rules-title">
          <div className="flex items-center gap-2">
            <CircleHelp className="h-5 w-5 text-primary" strokeWidth={1.5} />
            <h2 id="signal-rules-title" className="text-h3 text-foreground">行动队列口径</h2>
          </div>
          <ol className="mt-5 space-y-4 text-caption leading-relaxed text-foreground-secondary">
            <li><strong className="text-foreground">1. 先核证据：</strong>查看帖子正文与已关联评论，确认主体和语境。</li>
            <li><strong className="text-foreground">2. 再定优先：</strong>高严重度、负面和高互动优先；不伪造负责人或处置状态。</li>
            <li><strong className="text-foreground">3. 后做行动：</strong>将产品问题、内容规范、客服建议分别流转给对应业务团队。</li>
          </ol>
        </section>
      </div>

      <section className="card p-5 sm:p-6" aria-labelledby="signal-list-title">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 id="signal-list-title" className="text-h3 text-foreground">Momcozy VOC 预警与行动队列</h2>
            <p className="mt-1 text-caption text-foreground-muted">严重度 → 负面 → 关联评论 → Score 排序；展示前 24 条</p>
          </div>
          <ExportButton
            size="sm"
            filename="Momcozy_Reddit_VOC_舆情信号"
            title="Momcozy Reddit VOC 舆情信号"
            data={signals.map((post) => ({
              帖子ID: post.post_id,
              标题: post.title,
              社区: post.subreddit,
              主题: formatTopic(post.analysis.topic),
              情感: SENTIMENT_LABELS[post.analysis.sentiment_label],
              严重度: severityLabels[post.analysis.severity] ?? post.analysis.severity,
              Score: post.score,
              关联评论: post.linked_comment_count,
              Reddit链接: post.permalink,
            }))}
          />
        </div>
        <PostList posts={signals.slice(0, 24)} snapshot={snapshot} mode="signals" />
      </section>

      <section className="rounded-card border border-[#E9A23B]/25 bg-[#FFF9ED] p-5 text-caption leading-relaxed text-foreground-secondary">
        <strong className="text-foreground">数据质量行动：</strong>
        当前完整数据账本另有 {(snapshot.manifest.canonical_counts.unresolved_parent_comments ?? 0).toLocaleString('zh-CN')} 条待关联评论。
        它们已采集并纳入总量，但在父帖关系确认前不进入帖子评论明细；这是一项关系修复任务，不是采集缺失。
      </section>
    </>
  );
}

const metricDefinitions = [
  ['唯一帖子', '按 Reddit 帖子编号去重；同标题但编号不同的转帖分别保留。'],
  ['帖子 VOC', '每条去重帖子作为独立帖子事实，按帖子自身事件时间进入周期。'],
  ['评论上下文 VOC', '评论作为独立评论事实，并通过 Reddit 帖子编号关联父帖语境；帖子不会因评论数被重复计数。'],
  ['Momcozy 相关帖子', '品牌受控绑定为 Momcozy、正文明确提及 Momcozy，或存在 Momcozy 产品绑定。'],
  ['内容机会', 'Momcozy 相关、正文非空，且 Score≥5 或关联评论≥5；只代表分析优先级。'],
  ['舆情信号', 'Momcozy 相关，情感为负面或严重度为高，并达到最低互动量。'],
  ['样本提及份额', '品牌提及帖子数占全部品牌提及次数的比例；不是市场份额、SOV 或销量。'],
  ['环比', '当前完整周期与上一完整同粒度周期比较；基期为 0 时显示 —。'],
  ['同比', '当前完整周期与上年同日、同 ISO 周或同月比较；无基期时显示 —。'],
  ['趋势颜色', '上升使用红线、下降使用绿线、持平使用灰线；仅描述观察值变化。'],
] as const;

function DefinitionsPage({ snapshot }: { snapshot: NonNullable<ReturnType<typeof useRedditSnapshot>['data']> }) {
  const momcozyPosts = snapshot.posts.filter(isMomcozyPost).length;
  const taggedPosts = snapshot.aggregates.headline.posts_with_rule_tags;
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SnapshotMetricCard icon={FileText} value={snapshot.manifest.canonical_counts.posts} label="唯一帖子" note="全来源融合后按 Reddit 帖子编号去重" />
        <SnapshotMetricCard icon={MessageSquareWarning} value={snapshot.manifest.canonical_counts.stored_comments} label="存量评论" note="已关联、待关联和隔离评论的守恒总量" />
        <SnapshotMetricCard icon={Database} value={snapshot.manifest.canonical_counts.linked_comments} label="已关联评论" note="已解析父帖关系，可进入帖子评论明细" tone="success" />
        <SnapshotMetricCard icon={Archive} value={snapshot.manifest.canonical_counts.unresolved_parent_comments ?? 0} label="待关联评论" note="已采集但父帖关系待确认；不等于历史缺失" tone="warning" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <section className="card p-6" aria-labelledby="data-scope-title">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-icon bg-primary-light"><Database className="h-5 w-5 text-primary" strokeWidth={1.5} /></div>
            <div><h2 id="data-scope-title" className="text-h3 text-foreground">当前真实数据范围</h2><p className="text-caption text-foreground-muted">页面值直接绑定 current release</p></div>
          </div>
          <dl className="mt-5 space-y-3 text-caption">
            {[
              ['发布版本', snapshot.release.release_id],
              ['基础数据集', snapshot.manifest.dataset_version],
              ['帖子时间范围', `${formatDateTime(snapshot.aggregates.date_range.posts[0])} 至 ${formatDateTime(snapshot.aggregates.date_range.posts[1])}`],
              ['评论时间范围', `${formatDateTime(snapshot.aggregates.date_range.comments[0])} 至 ${formatDateTime(snapshot.aggregates.date_range.comments[1])}`],
              ['历史采集完整性', snapshot.manifest.comparison_contract_proven
                ? `${snapshot.manifest.completeness_percent}%（数据所有者确认）`
                : '覆盖未获数据所有者完整性证明'],
              ['Momcozy 相关帖子', `${momcozyPosts.toLocaleString('zh-CN')} 条`],
              ['规则标签覆盖帖子', `${taggedPosts.toLocaleString('zh-CN')} 条`],
              ['标签字典', snapshot.tagDictionary.dictionary_version],
            ].map(([label, value]) => (
              <div key={label} className="grid gap-1 rounded-icon bg-surface-tertiary px-4 py-3 sm:grid-cols-[150px_1fr]">
                <dt className="font-medium text-foreground-muted">{label}</dt>
                <dd className="break-all text-foreground-secondary">{value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="card p-6" aria-labelledby="metric-definition-title">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-icon bg-primary-light"><BookOpenCheck className="h-5 w-5 text-primary" strokeWidth={1.5} /></div>
            <div><h2 id="metric-definition-title" className="text-h3 text-foreground">指标口径词典</h2><p className="text-caption text-foreground-muted">展示值优先，低样本写进说明而不是清空</p></div>
          </div>
          <div className="mt-5 divide-y divide-border-divider">
            {metricDefinitions.map(([label, definition]) => (
              <article key={label} className="grid gap-2 py-4 first:pt-0 last:pb-0 sm:grid-cols-[150px_1fr]">
                <h3 className="text-body-sm font-semibold text-foreground">{label}</h3>
                <p className="text-caption leading-relaxed text-foreground-secondary">{definition}</p>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="card p-6" aria-labelledby="grain-title">
        <div className="flex items-center gap-3"><Scale className="h-5 w-5 text-primary" strokeWidth={1.5} /><h2 id="grain-title" className="text-h3 text-foreground">帖子、评论与帖子+评论关系</h2></div>
        <div className="mt-5 grid gap-4 lg:grid-cols-3">
          {[
            ['帖子事实', '1 个 Reddit 帖子编号对应 1 条帖子 VOC。帖子单独分析情感、主题、严重度、品牌、品类和互动量。'],
            ['评论事实', '1 个 Reddit 评论编号对应 1 条评论 VOC。评论按自身事件时间入窗，并保留父帖编号。'],
            ['帖子+评论上下文', '关联用于理解讨论语境和线程放大，不把 1 个帖子与 N 条评论合并成 N+1 个帖子，也不跨粒度重复计数。'],
          ].map(([title, body]) => (
            <article key={title} className="rounded-card border border-border-divider p-4"><h3 className="text-body-sm font-semibold text-foreground">{title}</h3><p className="mt-2 text-caption leading-relaxed text-foreground-secondary">{body}</p></article>
          ))}
        </div>
      </section>
    </>
  );
}

const workspaceCopy = {
  content: {
    icon: Archive,
    title: 'Momcozy 高价值内容',
    description: '真实帖子机会池 · 品类/SPU · 情感 · 互动量 · 案例应用入口',
  },
  signals: {
    icon: MessageSquareWarning,
    title: 'Momcozy 舆情信号',
    description: '真实负面与高严重度帖子 · 评论上下文 · 确定性行动排序',
  },
  definitions: {
    icon: BookOpenCheck,
    title: '数据与指标口径',
    description: '当前发布范围 · 帖子/评论粒度 · 同环比 · 趋势与品牌口径',
  },
} as const;

export default function SnapshotWorkspace({ workspace }: { workspace: SnapshotWorkspaceKind }) {
  const { data: snapshot, error, isLoading } = useRedditSnapshot();
  const copy = workspaceCopy[workspace];
  if (isLoading) return <SnapshotLoadingPage icon={copy.icon} title={copy.title} />;
  if (error || !snapshot) return <SnapshotErrorPage icon={copy.icon} title={copy.title} error={error ?? '未知错误'} />;

  return (
    <SnapshotPageLayout
      icon={copy.icon}
      title={copy.title}
      description={copy.description}
      datasetVersion={snapshot.manifest.dataset_version}
      freshness={createBaseDataFreshness(snapshot)}
    >
      {workspace === 'content' && <HighValueContentPage snapshot={snapshot} />}
      {workspace === 'signals' && <SignalCenterPage snapshot={snapshot} />}
      {workspace === 'definitions' && <DefinitionsPage snapshot={snapshot} />}
    </SnapshotPageLayout>
  );
}
