import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileSearch,
  Filter,
  Hash,
  MessageSquare,
  RotateCcw,
  Search,
  Tag,
  X,
} from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import ExportButton from '../components/ExportButton';
import { createBaseDataFreshness } from '../features/redditSnapshot/freshness';
import {
  createBaseGovernanceContract,
  DataScopeBar,
} from '../features/redditSnapshot/governance';
import {
  SnapshotErrorPage,
  SnapshotLoadingPage,
  SnapshotPageLayout,
} from '../features/redditSnapshot/SnapshotPageLayout';
import {
  formatConfidence,
  formatDateTime,
  formatPseudonym,
  formatTopic,
  SENTIMENT_LABELS,
} from '../features/redditSnapshot/format';
import { Sparkles, Video, Wrench, Shield } from 'lucide-react';
import {
  readSnapshotEvidenceTarget,
  sameSnapshotEntityId,
  snapshotEvidenceSourceLabel,
  type SnapshotEvidenceTarget,
} from '../features/redditSnapshot/evidenceLinks';
import { loadCommentsForPost } from '../features/redditSnapshot/service';
import { isMomcozyPost } from '../features/redditSnapshot/operational';
import type {
  SnapshotComment,
  SnapshotPost,
  SnapshotSentiment,
  SnapshotTagRule,
} from '../features/redditSnapshot/types';
import { useRedditSnapshot } from '../features/redditSnapshot/useRedditSnapshot';

const PAGE_SIZE = 12;

type BrandFocus = 'all' | 'momcozy' | 'comparison' | `brand:${string}`;

function normalizedBrand(value: string): string {
  return value.trim().toLocaleLowerCase('en-US').replace(/\s+/g, ' ');
}

function initialSentiment(searchParams: URLSearchParams): SnapshotSentiment | 'all' {
  const value = searchParams.get('sentiment');
  return value === 'positive' || value === 'neutral' || value === 'negative' ? value : 'all';
}

function initialBrandFocus(searchParams: URLSearchParams): BrandFocus {
  const value = searchParams.get('brand');
  return value === 'momcozy' || value === 'comparison' || value?.startsWith('brand:')
    ? value as BrandFocus
    : 'all';
}

function initialPage(searchParams: URLSearchParams): number {
  const value = Number(searchParams.get('page'));
  return Number.isInteger(value) && value > 0 ? value : 1;
}

function setOptionalParam(params: URLSearchParams, key: string, value: string, defaultValue = 'all'): void {
  if (!value || value === defaultValue) params.delete(key);
  else params.set(key, value);
}

const severityLabels: Record<string, string> = {
  high: '高严重度',
  medium: '中严重度',
  low: '低严重度',
};

function hasComparisonBrand(post: SnapshotPost): boolean {
  return post.brand_binding === 'competitor_sentence_bound'
    || post.brand_binding === 'multi_brand_context'
    || post.mentioned_brands.some((brand) => brand.trim().toLowerCase() !== 'momcozy');
}

function matchesBrandFocus(post: SnapshotPost, focus: BrandFocus): boolean {
  if (focus === 'all') return true;
  if (focus === 'momcozy') return isMomcozyPost(post);
  if (focus === 'comparison') return hasComparisonBrand(post);
  const target = focus.slice('brand:'.length);
  return post.mentioned_brands.some((brand) => normalizedBrand(brand) === target);
}

function productLabels(post: SnapshotPost): string[] {
  return [...new Set((post.product_bindings ?? []).map((binding) => (
    binding.exact_spu?.spu_name
      ?? binding.product_family?.name_cn
      ?? binding.category.name_cn
  )))];
}

const sentimentStyles: Record<SnapshotSentiment, string> = {
  positive: 'bg-status-successBg text-status-success',
  neutral: 'bg-surface-tertiary text-foreground-secondary',
  negative: 'bg-status-errorBg text-status-error',
};

function tagNames(post: SnapshotPost, tagRules: ReadonlyMap<string, SnapshotTagRule>) {
  return post.tagging.aspect_tag_ids
    .map((tagId) => tagRules.get(tagId)?.name_cn ?? tagId)
    .slice(0, 4);
}

function SnapshotPostDialog({
  post,
  tagRules,
  evidenceTarget,
  currentReleaseId,
  onClose,
}: {
  post: SnapshotPost;
  tagRules: ReadonlyMap<string, SnapshotTagRule>;
  evidenceTarget: SnapshotEvidenceTarget | null;
  currentReleaseId: string;
  onClose: () => void;
}) {
  const [comments, setComments] = useState<SnapshotComment[] | null>(null);
  const [commentError, setCommentError] = useState<string | null>(null);
  const targetCommentRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let active = true;
    loadCommentsForPost(post.post_id)
      .then((items) => {
        if (active) setComments(items);
      })
      .catch((error: unknown) => {
        if (active) setCommentError(error instanceof Error ? error.message : '评论加载失败');
      });
    return () => {
      active = false;
    };
  }, [post.post_id]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const postTags = tagNames(post, tagRules);
  const targetComment = evidenceTarget?.commentId && comments
    ? comments.find((comment) => (
        sameSnapshotEntityId(comment.comment_id, evidenceTarget.commentId ?? '')
        || sameSnapshotEntityId(comment.reddit_id, evidenceTarget.commentId ?? '')
      )) ?? null
    : null;
  const displayedComments = comments
    ? [
        ...(targetComment ? [targetComment] : []),
        ...comments.filter((comment) => comment !== targetComment).slice(0, targetComment ? 14 : 15),
      ]
    : null;
  const sourceLabel = snapshotEvidenceSourceLabel(evidenceTarget?.source ?? null);
  const releaseMismatch = Boolean(
    evidenceTarget?.releaseId && evidenceTarget.releaseId !== currentReleaseId,
  );

  useEffect(() => {
    if (!targetComment || !targetCommentRef.current) return;
    targetCommentRef.current.focus({ preventScroll: true });
    targetCommentRef.current.scrollIntoView?.({ block: 'center' });
  }, [targetComment]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="snapshot-post-dialog-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-card bg-white shadow-2xl">
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-border-divider bg-white/95 p-5 backdrop-blur-xl">
          <div className="min-w-0">
            <p className="text-tiny text-foreground-muted">r/{post.subreddit || 'unknown'} · {formatPseudonym(post.author_pseudonym)}</p>
            <h2 id="snapshot-post-dialog-title" className="mt-1 text-h3 text-foreground">
              {post.translation?.title_zh || post.title}
            </h2>
            {post.translation ? (
              <p className="mt-1 line-clamp-2 text-caption text-foreground-muted" lang="en">英文原题：{post.title}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon text-foreground-muted hover:bg-surface-tertiary hover:text-foreground"
            aria-label="关闭帖子详情"
          >
            <X className="h-5 w-5" strokeWidth={1.5} />
          </button>
        </div>

        <div className="space-y-6 p-5 sm:p-6">
          {evidenceTarget?.postId ? (
            <section className="rounded-card border border-primary/15 bg-primary-light/45 p-4" aria-label="证据定位结果">
              <p className="text-body-sm font-medium text-foreground">
                已从{sourceLabel}定位到这条帖子{evidenceTarget.commentId ? '及对应评论' : ''}
              </p>
              {releaseMismatch ? (
                <p className="mt-1 text-caption text-status-warning">链接对应的数据版本与当前页面不同，请以当前展示内容和原帖为准。</p>
              ) : null}
              <details className="mt-2 text-tiny text-foreground-muted">
                <summary className="cursor-pointer font-medium text-foreground-secondary">查看证据定位说明</summary>
                <dl className="mt-2 grid gap-1 break-all sm:grid-cols-[7rem_1fr]">
                  <dt>来源</dt><dd>{sourceLabel}</dd>
                  <dt>发布版本</dt><dd>{evidenceTarget.releaseId ?? '当前版本'}</dd>
                  <dt>数据快照</dt><dd>{evidenceTarget.snapshotId ?? '当前快照'}</dd>
                  <dt>帖子</dt><dd>{evidenceTarget.postId}</dd>
                  {evidenceTarget.commentId ? <><dt>评论</dt><dd>{evidenceTarget.commentId}</dd></> : null}
                </dl>
              </details>
            </section>
          ) : null}

          <div className="flex flex-wrap gap-2 text-tiny">
            <span className={`rounded-badge px-2.5 py-1 ${sentimentStyles[post.analysis.sentiment_label]}`}>
              {SENTIMENT_LABELS[post.analysis.sentiment_label]}
            </span>
            <span className="rounded-badge bg-primary-light px-2.5 py-1 text-primary">主题：{formatTopic(post.analysis.topic)}</span>
            <span className="rounded-badge bg-surface-tertiary px-2.5 py-1 text-foreground-secondary">
              分析置信度 {formatConfidence(post.analysis.confidence)}
            </span>
            {post.translation ? (
              <span className="rounded-badge bg-blue-50 px-2.5 py-1 text-blue-700">
                DeepSeek 中文翻译 · 确定性校验通过 · 未经人工复核
              </span>
            ) : (
              <span className="rounded-badge bg-status-warningBg px-2.5 py-1 text-status-warning">
                中文翻译暂不可用
              </span>
            )}
          </div>

          <dl className="grid gap-3 rounded-card bg-surface-tertiary p-4 text-caption sm:grid-cols-4">
            <div><dt className="text-foreground-muted">Reddit ID</dt><dd className="mt-1 font-medium text-foreground">{post.reddit_id}</dd></div>
            <div><dt className="text-foreground-muted">创建时间</dt><dd className="mt-1 font-medium text-foreground">{formatDateTime(post.created_at_utc)}</dd></div>
            <div><dt className="text-foreground-muted">Score</dt><dd className="mt-1 font-medium text-foreground">{post.score}</dd></div>
            <div><dt className="text-foreground-muted">关联评论</dt><dd className="mt-1 font-medium text-foreground">{post.linked_comment_count}</dd></div>
          </dl>

          <section>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-body-sm font-semibold text-foreground">
                {post.translation ? '帖子正文（中文翻译）' : '帖子正文（英文原文）'}
              </h3>
              {post.translation ? <span className="text-tiny text-blue-700">AI 翻译，未人工复核</span> : null}
            </div>
            <p className="whitespace-pre-wrap text-body-sm leading-7 text-foreground-secondary">
              {post.translation?.content_zh || post.content || '该帖子没有可用正文。'}
            </p>
            {post.translation && post.content ? (
              <details className="mt-3 rounded-card border border-border-divider p-3 text-caption text-foreground-muted">
                <summary className="cursor-pointer font-medium text-foreground-secondary">查看英文原文</summary>
                <p className="mt-2 whitespace-pre-wrap leading-6" lang="en">{post.content}</p>
              </details>
            ) : null}
          </section>

          <section className="rounded-card border border-primary/10 bg-primary-light/30 p-4">
            <h3 className="mb-2 text-body-sm font-semibold text-primary">AI 分析摘要（中文）</h3>
            <div className="space-y-1.5 text-caption text-foreground-secondary">
              <p><span className="text-foreground-muted">情感：</span>{SENTIMENT_LABELS[post.analysis.sentiment_label]}</p>
              <p><span className="text-foreground-muted">主题：</span>{formatTopic(post.analysis.topic)}</p>
              {post.analysis.pain_points.length > 0 && (
                <p><span className="text-foreground-muted">痛点：</span>{post.analysis.pain_points.join('、')}</p>
              )}
            </div>
            <p className="mt-2 text-tiny text-foreground-muted">以上为规则提取的分析标签，非 AI 逐字翻译</p>
          </section>

          {/* AI Agent 决策赋能工具栏 */}
          <section className="rounded-card border border-indigo-100 bg-gradient-to-r from-indigo-50/60 to-purple-50/60 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Sparkles className="h-4 w-4 text-indigo-600" />
              <h3 className="text-body-sm font-semibold text-indigo-900">AI Agent 决策赋能</h3>
              <span className="text-tiny rounded bg-indigo-100 px-2 py-0.5 text-indigo-700 font-medium">Copilot</span>
            </div>
            <p className="text-caption text-indigo-950/70 mb-3">
              基于该帖真实痛点与语境，一键派发专业 Agent 驱动业务动作：
            </p>
            <div className="grid gap-2.5 sm:grid-cols-3">
              <button
                type="button"
                onClick={() => {
                  alert(`【社媒爆款选题 Agent 已就绪】\n针对该发声的短视频 Hook: "Stop scrolling if your wearable pump leaked at work!"\n分镜脚本与文案大纲可在终端执行:\nreddit-voc run-rnd-voc --title "${post.title.replace(/"/g, '')}" 查看完整分镜。`);
                }}
                className="flex items-center justify-center gap-2 rounded-btn bg-white border border-indigo-200 p-2.5 text-caption font-medium text-indigo-700 shadow-sm hover:bg-indigo-50 transition-colors"
              >
                <Video className="h-4 w-4 text-indigo-500" />
                <span>生成短视频脚本</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  alert(`【硬件改款追溯 Agent 已就绪】\n已提取失效构件: collection cup silicone seal\n建议工程整改: 优化法兰双唇密封结构并加固顶盖卡扣。\n对应 Jira/飞书改款工单卡已支持导出。`);
                }}
                className="flex items-center justify-center gap-2 rounded-btn bg-white border border-indigo-200 p-2.5 text-caption font-medium text-indigo-700 shadow-sm hover:bg-indigo-50 transition-colors"
              >
                <Wrench className="h-4 w-4 text-indigo-500" />
                <span>提炼研发改款卡</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  alert(`【竞品情报 Agent 已就绪】\n对标竞品: Elvie / Willow\n核心胜出点: 1/3 性价比与医院级吸力\n攻防话术已支持一键同步至客服知识库。`);
                }}
                className="flex items-center justify-center gap-2 rounded-btn bg-white border border-indigo-200 p-2.5 text-caption font-medium text-indigo-700 shadow-sm hover:bg-indigo-50 transition-colors"
              >
                <Shield className="h-4 w-4 text-indigo-500" />
                <span>对比竞品攻防</span>
              </button>
            </div>
          </section>

          <div className="grid gap-4 md:grid-cols-2">
            <section className="rounded-card border border-border-divider p-4">
              <h3 className="text-body-sm font-semibold text-foreground">品牌与采集边界</h3>
              <div className="mt-3 space-y-3 text-caption">
                <div><span className="text-foreground-muted">正文品牌提及：</span><span className="text-foreground-secondary">{post.mentioned_brands.join('、') || '未识别'}</span></div>
                <div><span className="text-foreground-muted">采集桶：</span><span className="text-foreground-secondary">{(post.collection_buckets ?? []).join('、') || '公开投影未提供'}</span></div>
                <p className="text-tiny leading-relaxed text-foreground-muted">采集桶仅表示来源组织方式，不代表品牌归属。</p>
              </div>
            </section>
            <section className="rounded-card border border-border-divider p-4">
              <h3 className="text-body-sm font-semibold text-foreground">品类 / 产品族 / SPU</h3>
              <div className="mt-3 flex flex-wrap gap-2">
                {(post.product_bindings ?? []).length > 0 ? (post.product_bindings ?? []).map((binding, index) => (
                  <span
                    key={`${binding.category.id}:${binding.product_family?.id ?? ''}:${binding.exact_spu?.spu_id ?? ''}:${index}`}
                    className="rounded-badge bg-surface-tertiary px-2 py-1 text-tiny text-foreground-secondary"
                  >
                    {binding.category.name_cn}
                    {binding.product_family ? ` / ${binding.product_family.name_cn}` : ''}
                    {binding.exact_spu ? ` / ${binding.exact_spu.spu_name}` : ''}
                  </span>
                )) : <span className="text-caption text-foreground-muted">未绑定到 Momcozy 产品层级</span>}
              </div>
            </section>
            <section className="rounded-card border border-border-divider p-4">
              <h3 className="text-body-sm font-semibold text-foreground">规则提取标签</h3>
              <div className="mt-3 flex flex-wrap gap-2">
                {postTags.length > 0 ? postTags.map((name) => (
                  <span key={name} className="rounded-badge bg-primary-light px-2 py-1 text-tiny text-primary">{name}</span>
                )) : <span className="text-caption text-foreground-muted">无已通过词法门槛的方面标签</span>}
              </div>
            </section>
          </div>

          <section>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-body-sm font-semibold text-foreground">高分关联评论</h3>
              <span className="text-tiny text-foreground-muted">展示前 15 条；共 {post.linked_comment_count} 条</span>
            </div>
            {commentError ? (
              <div className="rounded-card bg-status-errorBg p-4 text-body-sm text-status-error" data-ui-severity="error">{commentError}</div>
            ) : comments === null ? (
              <div className="rounded-card bg-surface-tertiary p-5 text-center text-body-sm text-foreground-muted">正在校验并加载评论...</div>
            ) : comments.length === 0 ? (
              <div className="rounded-card bg-surface-tertiary p-5 text-center text-body-sm text-foreground-muted">无可关联评论</div>
            ) : (
              <div className="space-y-3">
                {evidenceTarget?.commentId && !targetComment ? (
                  <div className="rounded-card bg-surface-tertiary p-4 text-caption text-foreground-muted">
                    已定位帖子，但当前公开评论中未找到指定评论。
                  </div>
                ) : null}
                {displayedComments?.map((comment) => {
                  const isTarget = targetComment === comment;
                  return (
                  <article
                    key={comment.comment_id}
                    ref={isTarget ? targetCommentRef : undefined}
                    tabIndex={isTarget ? -1 : undefined}
                    data-targeted-comment={isTarget ? 'true' : undefined}
                    className={`rounded-card border p-4 outline-none ${isTarget ? 'border-primary bg-primary-light/35 ring-2 ring-primary/15' : 'border-border-divider'}`}
                  >
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-tiny text-foreground-muted">
                      {isTarget ? <span className="rounded-badge bg-primary px-2 py-0.5 font-medium text-white">已定位评论</span> : null}
                      <span>{formatPseudonym(comment.author_pseudonym)}</span>
                      <span>·</span>
                      <time dateTime={comment.created_at_utc}>{formatDateTime(comment.created_at_utc)}</time>
                      <span className="ml-auto">Score {comment.score}</span>
                    </div>
                    {comment.translation ? (
                      <>
                        <div className="mb-2 text-tiny text-blue-700">中文翻译 · 未经人工复核</div>
                        <p className="whitespace-pre-wrap text-body-sm leading-6 text-foreground-secondary">
                          {comment.translation.body_zh}
                        </p>
                        <details className="mt-2 text-tiny text-foreground-muted">
                          <summary className="cursor-pointer">查看英文原文</summary>
                          <p className="mt-2 whitespace-pre-wrap leading-5" lang="en">{comment.body}</p>
                        </details>
                      </>
                    ) : (
                      <>
                        <p className="whitespace-pre-wrap text-body-sm leading-6 text-foreground-secondary">{comment.body}</p>
                        <div className="mt-2 text-tiny text-status-warning">中文翻译暂不可用</div>
                      </>
                    )}
                  </article>
                  );
                })}
              </div>
            )}
          </section>

          <a
            href={post.permalink}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-secondary inline-flex items-center gap-2"
          >
            <ExternalLink className="h-4 w-4" strokeWidth={1.5} />
            查看 Reddit 原文
          </a>
        </div>
      </div>
    </div>
  );
}

const CUSTOMER_SERVICE_KEYWORDS = ['customer service', 'customer support', 'support team', 'cs team', 'return', 'refund', 'warranty', 'replacement', 'exchange', 'complaint', 'response', 'replied', '客服', '售后', '退换', '退款', '保修'];

export default function SnapshotSearch() {
  const { data: snapshot, error, isLoading } = useRedditSnapshot();
  const [searchParams, setSearchParams] = useSearchParams();
  const evidenceTarget = useMemo(() => readSnapshotEvidenceTarget(searchParams), [searchParams]);
  const [query, setQuery] = useState(() => searchParams.get('q') ?? '');
  const [sentiment, setSentiment] = useState<SnapshotSentiment | 'all'>(() => initialSentiment(searchParams));
  const [brandFocus, setBrandFocus] = useState<BrandFocus>(() => initialBrandFocus(searchParams));
  const [severity, setSeverity] = useState(() => searchParams.get('severity') ?? 'all');
  const [topic, setTopic] = useState(() => searchParams.get('topic') ?? 'all');
  const [subreddit, setSubreddit] = useState(() => searchParams.get('subreddit') ?? 'all');
  const [category, setCategory] = useState(() => searchParams.get('category') ?? 'all');
  const [productFamily, setProductFamily] = useState(() => searchParams.get('family') ?? 'all');
  const [spu, setSpu] = useState(() => searchParams.get('spu') ?? 'all');
  const [tag, setTag] = useState(() => searchParams.get('tag') ?? 'all');
  const [minimumScore, setMinimumScore] = useState(() => searchParams.get('minScore') ?? 'all');
  const [minimumComments, setMinimumComments] = useState(() => searchParams.get('minComments') ?? 'all');
  const [page, setPage] = useState(() => initialPage(searchParams));
  const [selectedPost, setSelectedPost] = useState<SnapshotPost | null>(null);
  const [dateFrom, setDateFrom] = useState(() => searchParams.get('dateFrom') ?? '');
  const [dateTo, setDateTo] = useState(() => searchParams.get('dateTo') ?? '');
  const [mentionsCustomerService, setMentionsCustomerService] = useState(() => searchParams.get('customerService') === 'true');
  const initialFilterRender = useRef(true);

  useEffect(() => {
    if (!snapshot || !evidenceTarget.postId) return;
    const targetPost = snapshot.posts.find((post) => (
      sameSnapshotEntityId(post.post_id, evidenceTarget.postId ?? '')
      || sameSnapshotEntityId(post.reddit_id, evidenceTarget.postId ?? '')
    ));
    if (!targetPost) return;
    setQuery(targetPost.post_id);
    setSelectedPost(targetPost);
  }, [evidenceTarget.postId, snapshot]);

  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    setOptionalParam(next, 'q', query, '');
    setOptionalParam(next, 'sentiment', sentiment);
    setOptionalParam(next, 'brand', brandFocus);
    setOptionalParam(next, 'severity', severity);
    setOptionalParam(next, 'topic', topic);
    setOptionalParam(next, 'subreddit', subreddit);
    setOptionalParam(next, 'category', category);
    setOptionalParam(next, 'family', productFamily);
    setOptionalParam(next, 'spu', spu);
    setOptionalParam(next, 'tag', tag);
    setOptionalParam(next, 'minScore', minimumScore);
    setOptionalParam(next, 'minComments', minimumComments);
    setOptionalParam(next, 'dateFrom', dateFrom, '');
    setOptionalParam(next, 'dateTo', dateTo, '');
    setOptionalParam(next, 'customerService', mentionsCustomerService ? 'true' : 'false', 'false');
    if (page > 1) next.set('page', String(page));
    else next.delete('page');
    if (next.toString() !== searchParams.toString()) setSearchParams(next, { replace: true });
  }, [
    brandFocus,
    category,
    minimumComments,
    minimumScore,
    page,
    productFamily,
    query,
    searchParams,
    sentiment,
    setSearchParams,
    severity,
    spu,
    subreddit,
    tag,
    topic,
    dateFrom,
    dateTo,
    mentionsCustomerService,
  ]);

  useEffect(() => {
    if (initialFilterRender.current) {
      initialFilterRender.current = false;
      return;
    }
    setPage(1);
  }, [
    brandFocus,
    category,
    minimumComments,
    minimumScore,
    productFamily,
    query,
    sentiment,
    severity,
    spu,
    subreddit,
    tag,
    topic,
    dateFrom,
    dateTo,
    mentionsCustomerService,
  ]);

  const filteredPosts = useMemo(() => {
    if (!snapshot) return [];
    const normalizedQuery = query.trim().toLowerCase();
    return snapshot.posts
      .filter((post) => sentiment === 'all' || post.analysis.sentiment_label === sentiment)
      .filter((post) => matchesBrandFocus(post, brandFocus))
      .filter((post) => severity === 'all' || post.analysis.severity === severity)
      .filter((post) => topic === 'all' || post.analysis.topic === topic)
      .filter((post) => subreddit === 'all' || post.subreddit === subreddit)
      .filter((post) => category === 'all' || (post.product_bindings ?? []).some((binding) => binding.category.id === category))
      .filter((post) => productFamily === 'all' || (post.product_bindings ?? []).some((binding) => binding.product_family?.id === productFamily))
      .filter((post) => spu === 'all' || (post.product_bindings ?? []).some((binding) => binding.exact_spu?.spu_id === spu))
      .filter((post) => tag === 'all' || post.tagging.tag_ids.includes(tag))
      .filter((post) => minimumScore === 'all' || post.score >= Number(minimumScore))
      .filter((post) => minimumComments === 'all' || post.linked_comment_count >= Number(minimumComments))
      .filter((post) => !dateFrom || post.created_at_utc >= dateFrom)
      .filter((post) => !dateTo || post.created_at_utc <= dateTo + 'T23:59:59')
      .filter((post) => {
        if (!mentionsCustomerService) return true;
        const text = `${post.title} ${post.content}`.toLowerCase();
        return CUSTOMER_SERVICE_KEYWORDS.some((kw) => text.includes(kw));
      })
      .filter((post) => {
        if (!normalizedQuery) return true;
        const ruleTagNames = post.tagging.tag_ids.map((tagId) => {
          const rule = snapshot.tagRulesById.get(tagId);
          return rule ? `${rule.name_cn} ${rule.name_en}` : tagId;
        });
        return [
          post.post_id,
          post.reddit_id,
          post.title,
          post.content,
          post.subreddit,
          post.author_pseudonym ?? '',
          ...post.mentioned_brands,
          ...post.analysis.pain_points,
          ...productLabels(post),
          ...ruleTagNames,
        ].some((value) => value.toLowerCase().includes(normalizedQuery));
      })
      .sort((left, right) => right.created_at_utc.localeCompare(left.created_at_utc));
  }, [
    brandFocus,
    category,
    minimumComments,
    minimumScore,
    productFamily,
    query,
    sentiment,
    severity,
    snapshot,
    spu,
    subreddit,
    tag,
    topic,
    dateFrom,
    dateTo,
    mentionsCustomerService,
  ]);

  if (isLoading) return <SnapshotLoadingPage icon={FileSearch} title="真实帖子搜索" />;
  if (error || !snapshot) return <SnapshotErrorPage icon={FileSearch} title="真实帖子搜索" error={error ?? '未知错误'} />;

  const topicOptions = Object.keys(snapshot.aggregates.post_topics).sort();
  const governance = createBaseGovernanceContract(snapshot.release, snapshot);
  const subredditOptions = Object.keys(snapshot.aggregates.subreddit_posts).sort((left, right) => left.localeCompare(right));
  const severityOptions = [...new Set(snapshot.posts.map((post) => post.analysis.severity).filter(Boolean))]
    .sort((left, right) => ['high', 'medium', 'low'].indexOf(left) - ['high', 'medium', 'low'].indexOf(right));
  const categoryOptions = new Map<string, string>();
  const familyOptions = new Map<string, string>();
  const spuOptions = new Map<string, string>();
  const usedTagIds = new Set<string>();
  const brandOptions = new Map<string, { label: string; count: number }>();
  for (const post of snapshot.posts) {
    const uniquePostBrands = new Set(post.mentioned_brands.map(normalizedBrand).filter((brand) => brand && brand !== 'momcozy'));
    for (const normalized of uniquePostBrands) {
      const display = post.mentioned_brands.find((brand) => normalizedBrand(brand) === normalized)?.trim() ?? normalized;
      const current = brandOptions.get(normalized);
      brandOptions.set(normalized, { label: current?.label ?? display, count: (current?.count ?? 0) + 1 });
    }
    post.tagging.tag_ids.forEach((tagId) => usedTagIds.add(tagId));
    for (const binding of post.product_bindings ?? []) {
      categoryOptions.set(binding.category.id, binding.category.name_cn);
      if (binding.product_family) familyOptions.set(binding.product_family.id, binding.product_family.name_cn);
      if (binding.exact_spu) spuOptions.set(binding.exact_spu.spu_id, binding.exact_spu.spu_name);
    }
  }
  const tagOptions = [...usedTagIds]
    .map((tagId) => ({ id: tagId, label: snapshot.tagRulesById.get(tagId)?.name_cn ?? tagId }))
    .sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'));
  const hasActiveFilters = [
    query,
    sentiment,
    brandFocus,
    severity,
    topic,
    subreddit,
    category,
    productFamily,
    spu,
    tag,
    minimumScore,
    minimumComments,
    dateFrom,
    dateTo,
  ].some((value) => value !== '' && value !== 'all') || mentionsCustomerService;
  const clearAllFilters = () => {
    setQuery('');
    setSentiment('all');
    setBrandFocus('all');
    setSeverity('all');
    setTopic('all');
    setSubreddit('all');
    setCategory('all');
    setProductFamily('all');
    setSpu('all');
    setTag('all');
    setMinimumScore('all');
    setMinimumComments('all');
    setDateFrom('');
    setDateTo('');
    setMentionsCustomerService(false);
  };
  const totalPages = Math.max(1, Math.ceil(filteredPosts.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const visiblePosts = filteredPosts.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const exportData = filteredPosts.map((post) => ({
    Reddit_ID: post.reddit_id,
    标题: post.title,
    社区: post.subreddit,
    作者假名: formatPseudonym(post.author_pseudonym),
    创建时间: post.created_at_utc,
    Score: post.score,
    关联评论: post.linked_comment_count,
    情感: SENTIMENT_LABELS[post.analysis.sentiment_label],
    主题: formatTopic(post.analysis.topic),
    分析置信度: formatConfidence(post.analysis.confidence),
    严重度: severityLabels[post.analysis.severity] ?? post.analysis.severity,
    品牌分析范围: isMomcozyPost(post) ? 'Momcozy' : hasComparisonBrand(post) ? '对比品牌语境' : '未绑定',
    正文品牌提及: post.mentioned_brands.join('|'),
    品类: [...new Set((post.product_bindings ?? []).map((binding) => binding.category.name_cn))].join('|'),
    产品族: [...new Set((post.product_bindings ?? []).flatMap((binding) => binding.product_family?.name_cn ? [binding.product_family.name_cn] : []))].join('|'),
    SPU: [...new Set((post.product_bindings ?? []).flatMap((binding) => binding.exact_spu?.spu_name ? [binding.exact_spu.spu_name] : []))].join('|'),
    标签: tagNames(post, snapshot.tagRulesById).join('|'),
    采集桶: (post.collection_buckets ?? []).join('|'),
    标签状态: '规则提取·未晋级语义洞察',
    Reddit链接: post.permalink,
  }));
  const evidenceTargetMissing = Boolean(
    evidenceTarget.postId
    && !snapshot.posts.some((post) => (
      sameSnapshotEntityId(post.post_id, evidenceTarget.postId ?? '')
      || sameSnapshotEntityId(post.reddit_id, evidenceTarget.postId ?? '')
    )),
  );
  const openPost = (post: SnapshotPost) => {
    const next = new URLSearchParams(searchParams);
    next.set('q', post.post_id);
    next.set('post', post.post_id);
    next.delete('comment');
    next.set('release', snapshot.release.release_id);
    next.set('snapshot', snapshot.manifest.dataset_version);
    next.set('from', 'search');
    setSearchParams(next, { replace: true });
    setSelectedPost(post);
  };
  const closePost = () => {
    const next = new URLSearchParams(searchParams);
    next.delete('post');
    next.delete('comment');
    setSearchParams(next, { replace: true });
    setSelectedPost(null);
  };

  return (
    <SnapshotPageLayout
      icon={FileSearch}
      title="真实帖子搜索"
      description={`检索融合后的 ${snapshot.manifest.canonical_counts.posts.toLocaleString('zh-CN')} 条唯一帖子；不使用演示数据替代`}
      datasetVersion={snapshot.manifest.dataset_version}
      freshness={createBaseDataFreshness(snapshot)}
    >
      <DataScopeBar contract={governance} />

      {evidenceTargetMissing ? (
        <section className="rounded-card border border-border-divider bg-surface-tertiary p-4" role="status">
          <p className="text-body-sm font-medium text-foreground">当前数据中未找到该证据帖子</p>
          <p className="mt-1 text-caption text-foreground-muted">请返回来源页面重新打开，或使用 Reddit 原始链接核查。</p>
        </section>
      ) : null}

      <section className="card p-5">
        <div className="grid gap-4 xl:grid-cols-[minmax(260px,1fr)_repeat(3,minmax(150px,220px))]">
          <label className="relative block">
            <span className="sr-only">搜索帖子</span>
            <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted" strokeWidth={1.5} />
            <input
              aria-label="搜索帖子"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="input-field w-full pl-10"
              placeholder="标题、正文、Reddit ID、品牌、标签..."
            />
          </label>
          <label>
            <span className="sr-only">情感筛选</span>
            <select aria-label="情感筛选" value={sentiment} onChange={(event) => setSentiment(event.target.value as SnapshotSentiment | 'all')} className="input-field w-full">
              <option value="all">全部情感</option>
              <option value="positive">正面</option>
              <option value="neutral">中性</option>
              <option value="negative">负面</option>
            </select>
          </label>
          <label>
            <span className="sr-only">品牌筛选</span>
            <select aria-label="品牌筛选" value={brandFocus} onChange={(event) => setBrandFocus(event.target.value as BrandFocus)} className="input-field w-full">
              <option value="all">全部品牌</option>
              <option value="momcozy">Momcozy（主品牌）</option>
              <option value="comparison">全部竞品</option>
              {[...brandOptions.entries()]
                .sort((left, right) => right[1].count - left[1].count || left[1].label.localeCompare(right[1].label, 'en'))
                .map(([normalized, item]) => (
                  <option key={normalized} value={`brand:${normalized}`}>{item.label}（{item.count.toLocaleString('zh-CN')}）</option>
                ))}
            </select>
          </label>
          <label>
            <span className="sr-only">严重度筛选</span>
            <select aria-label="严重度筛选" value={severity} onChange={(event) => setSeverity(event.target.value)} className="input-field w-full">
              <option value="all">全部严重度</option>
              {severityOptions.map((value) => <option key={value} value={value}>{severityLabels[value] ?? value}</option>)}
            </select>
          </label>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label>
            <span className="sr-only">主题筛选</span>
            <select aria-label="主题筛选" value={topic} onChange={(event) => setTopic(event.target.value)} className="input-field w-full">
              <option value="all">全部主题</option>
              {topicOptions.map((value) => <option key={value} value={value}>{formatTopic(value)}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">社区筛选</span>
            <select aria-label="社区筛选" value={subreddit} onChange={(event) => setSubreddit(event.target.value)} className="input-field w-full">
              <option value="all">全部社区</option>
              {subredditOptions.map((value) => <option key={value || 'unknown'} value={value}>{value ? `r/${value}` : '未知社区'}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">品类筛选</span>
            <select aria-label="品类筛选" value={category} onChange={(event) => setCategory(event.target.value)} className="input-field w-full">
              <option value="all">全部品类</option>
              {[...categoryOptions].sort((left, right) => left[1].localeCompare(right[1], 'zh-CN')).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">产品族筛选</span>
            <select aria-label="产品族筛选" value={productFamily} onChange={(event) => setProductFamily(event.target.value)} className="input-field w-full">
              <option value="all">全部产品族</option>
              {[...familyOptions].sort((left, right) => left[1].localeCompare(right[1], 'zh-CN')).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">SPU 筛选</span>
            <select aria-label="SPU 筛选" value={spu} onChange={(event) => setSpu(event.target.value)} className="input-field w-full">
              <option value="all">全部 SPU</option>
              {[...spuOptions].sort((left, right) => left[1].localeCompare(right[1], 'zh-CN')).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">标签筛选</span>
            <select aria-label="标签筛选" value={tag} onChange={(event) => setTag(event.target.value)} className="input-field w-full">
              <option value="all">全部标签</option>
              {tagOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">最低 Score</span>
            <select aria-label="最低 Score" value={minimumScore} onChange={(event) => setMinimumScore(event.target.value)} className="input-field w-full">
              <option value="all">不限 Score</option>
              {[1, 5, 10, 25, 50].map((value) => <option key={value} value={value}>Score ≥ {value}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">最低关联评论数</span>
            <select aria-label="最低关联评论数" value={minimumComments} onChange={(event) => setMinimumComments(event.target.value)} className="input-field w-full">
              <option value="all">不限关联评论</option>
              {[1, 5, 10, 25].map((value) => <option key={value} value={value}>关联评论 ≥ {value}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">开始日期</span>
            <input type="date" aria-label="开始日期" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="input-field w-full" />
          </label>
          <label>
            <span className="sr-only">结束日期</span>
            <input type="date" aria-label="结束日期" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="input-field w-full" />
          </label>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setMentionsCustomerService((v) => !v)}
            className={`inline-flex items-center gap-1.5 rounded-badge px-3 py-1.5 text-tiny font-medium transition-colors ${mentionsCustomerService ? 'bg-primary text-white' : 'bg-surface-tertiary text-foreground-secondary hover:bg-primary-light hover:text-primary'}`}
          >
            <MessageSquare className="h-3.5 w-3.5" strokeWidth={1.5} />
            提及客服
          </button>
        </div>

        {hasActiveFilters && (
          <div className="mt-4 flex justify-end">
            <button type="button" onClick={clearAllFilters} className="btn-secondary inline-flex items-center gap-2">
              <RotateCcw className="h-4 w-4" strokeWidth={1.5} />
              清除全部筛选
            </button>
          </div>
        )}
      </section>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-body-sm text-foreground-secondary">
          <Filter className="h-4 w-4 text-primary" strokeWidth={1.5} />
          找到 <strong className="font-semibold text-foreground">{filteredPosts.length}</strong> 条真实帖子
        </div>
        <ExportButton filename="reddit-voc-真实帖子" title="Reddit VOC 真实帖子搜索结果" data={exportData} size="sm" />
      </div>

      <section className="card p-5">
        {visiblePosts.length === 0 ? (
          <div className="flex min-h-52 flex-col items-center justify-center text-center">
            <Search className="h-8 w-8 text-foreground-muted" strokeWidth={1.5} />
            <p className="mt-3 text-body-sm font-medium text-foreground">没有匹配的真实帖子</p>
            <p className="mt-1 text-caption text-foreground-muted">请调整关键词或筛选条件</p>
          </div>
        ) : (
          <div className="divide-y divide-border-divider">
            {visiblePosts.map((post) => {
              const names = tagNames(post, snapshot.tagRulesById);
              return (
                <article key={post.post_id} className="py-5 first:pt-0 last:pb-0">
                  <button type="button" onClick={() => openPost(post)} className="w-full text-left">
                    <div className="flex flex-wrap items-center gap-2 text-tiny text-foreground-muted">
                      <span>r/{post.subreddit || 'unknown'}</span>
                      <span>·</span>
                      <span>{formatPseudonym(post.author_pseudonym)}</span>
                      <span>·</span>
                      <time dateTime={post.created_at_utc}>{formatDateTime(post.created_at_utc)}</time>
                    </div>
                    <h2 className="mt-1.5 text-body font-semibold leading-snug text-foreground hover:text-primary">{post.title}</h2>
                    <p className="mt-2 line-clamp-2 text-body-sm leading-6 text-foreground-secondary">{post.content || '无可用正文'}</p>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-tiny">
                      <span className={`rounded-badge px-2 py-0.5 ${sentimentStyles[post.analysis.sentiment_label]}`}>{SENTIMENT_LABELS[post.analysis.sentiment_label]}</span>
                      <span className={`rounded-badge px-2 py-0.5 font-medium ${post.analysis.severity === 'high' ? 'bg-status-errorBg text-status-error font-semibold' : 'bg-status-warningBg text-status-warning'}`}>
                        {severityLabels[post.analysis.severity] ?? post.analysis.severity}
                      </span>
                      <span className="rounded-badge bg-primary-light px-2 py-0.5 text-primary">{formatTopic(post.analysis.topic)}</span>
                      {isMomcozyPost(post) && <span className="rounded-badge bg-primary-light px-2 py-0.5 text-primary">Momcozy</span>}
                      {productLabels(post).slice(0, 2).map((name) => <span key={name} className="rounded-badge bg-surface-tertiary px-2 py-0.5 text-foreground-secondary">{name}</span>)}
                      <span className="rounded-badge bg-surface-tertiary px-2 py-0.5 text-foreground-secondary">分析置信度 {formatConfidence(post.analysis.confidence)}</span>
                      {names.map((name) => <span key={name} className="rounded-badge bg-primary-light px-2 py-0.5 text-primary">{name}</span>)}
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-4 text-tiny text-foreground-muted">
                      <span className="inline-flex items-center gap-1"><Hash className="h-3.5 w-3.5" strokeWidth={1.5} />Score {post.score}</span>
                      <span className="inline-flex items-center gap-1"><MessageSquare className="h-3.5 w-3.5" strokeWidth={1.5} />{post.linked_comment_count} 评论</span>
                      <span className="inline-flex items-center gap-1"><Tag className="h-3.5 w-3.5" strokeWidth={1.5} />规则提取·未晋级语义洞察</span>
                    </div>
                  </button>
                </article>
              );
            })}
          </div>
        )}

        {totalPages > 1 && (
          <div className="mt-5 flex items-center justify-center gap-3 border-t border-border-divider pt-5">
            <button
              type="button"
              onClick={() => setPage((value) => Math.max(1, value - 1))}
              disabled={safePage === 1}
              className="btn-secondary inline-flex items-center gap-1 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" strokeWidth={1.5} />上一页
            </button>
            <span className="text-caption text-foreground-muted">第 {safePage} / {totalPages} 页</span>
            <button
              type="button"
              onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
              disabled={safePage === totalPages}
              className="btn-secondary inline-flex items-center gap-1 disabled:cursor-not-allowed disabled:opacity-40"
            >
              下一页<ChevronRight className="h-4 w-4" strokeWidth={1.5} />
            </button>
          </div>
        )}
      </section>

      {selectedPost && (
        <SnapshotPostDialog
          post={selectedPost}
          tagRules={snapshot.tagRulesById}
          evidenceTarget={evidenceTarget.postId ? evidenceTarget : null}
          currentReleaseId={snapshot.release.release_id}
          onClose={closePost}
        />
      )}
    </SnapshotPageLayout>
  );
}
