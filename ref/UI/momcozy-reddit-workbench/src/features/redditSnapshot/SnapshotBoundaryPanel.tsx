import { CheckCircle2, Database, ShieldCheck, Tag, TriangleAlert, XCircle } from 'lucide-react';
import type { RedditSnapshotCore } from './types';

export function SnapshotBoundaryPanel({ snapshot }: { snapshot: RedditSnapshotCore }) {
  const { manifest, aggregates } = snapshot;
  const titleCounts = new Map<string, number>();
  for (const post of snapshot.posts) {
    titleCounts.set(post.title, (titleCounts.get(post.title) ?? 0) + 1);
  }
  const duplicateTitleGroups = [...titleCounts.values()].filter((count) => count > 1).length;
  const supportedChecks = [
    `上游校验 ${manifest.all_checks_passed ? '通过' : '未通过'}`,
    `帖子分析覆盖 ${aggregates.headline.analysis_covered_posts}/${aggregates.headline.unique_posts}`,
    `评论分析覆盖 ${aggregates.headline.analysis_covered_comments}/${aggregates.headline.linked_comments}`,
    `作者信息：${manifest.privacy.author_display === 'suppressed' ? '已隐藏' : manifest.privacy.author_display}`,
  ];
  const unsupported = [
    ['市场份额', manifest.semantic_boundaries.market_share_supported],
    ['ROI', manifest.semantic_boundaries.roi_supported],
    ['响应时长', manifest.semantic_boundaries.response_time_supported],
  ] as const;

  return (
    <section className="card p-6" aria-labelledby="data-quality-title">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-status-successBg">
            <ShieldCheck className="h-[18px] w-[18px] text-status-success" strokeWidth={1.5} />
          </div>
          <div>
            <h2 id="data-quality-title" className="text-h3 text-foreground">数据质量与语义边界</h2>
            <p className="mt-0.5 text-caption text-foreground-muted">
              页面只展示当前快照能够证明的指标，缺失能力不做推算
            </p>
          </div>
        </div>
        <span className="rounded-badge bg-status-successBg px-2.5 py-1 text-tiny font-medium text-status-success">
          仅展示已验证数据
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-card border border-border-divider p-4">
          <div className="mb-3 flex items-center gap-2 text-body-sm font-medium text-foreground">
            <CheckCircle2 className="h-4 w-4 text-status-success" strokeWidth={1.5} />
            已验证
          </div>
          <ul className="space-y-2 text-caption text-foreground-secondary">
            {supportedChecks.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-status-success" />
                {item}
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-card border border-border-divider p-4">
          <div className="mb-3 flex items-center gap-2 text-body-sm font-medium text-foreground">
            <Database className="h-4 w-4 text-primary" strokeWidth={1.5} />
            覆盖与隔离
          </div>
          <dl className="space-y-2 text-caption">
            <div className="flex justify-between gap-3"><dt className="text-foreground-muted">结构完整</dt><dd className="font-medium text-foreground">{aggregates.coverage_grade.full ?? 0}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-foreground-muted">结构部分</dt><dd className="font-medium text-foreground">{aggregates.coverage_grade.partial ?? 0}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-foreground-muted">VOC 指标评论</dt><dd className="font-medium text-foreground">{aggregates.headline.comments_in_voc_metrics.toLocaleString('zh-CN')}</dd></div>
            {manifest.schema_version === 'reddit_voc_site_snapshot_manifest_v3' ? (
              <div className="flex justify-between gap-3"><dt className="text-foreground-muted">待关联评论</dt><dd className="font-medium text-status-warning">{(manifest.canonical_counts.unresolved_parent_comments ?? 0).toLocaleString('zh-CN')}</dd></div>
            ) : null}
            <div className="flex justify-between gap-3"><dt className="text-foreground-muted">隔离评论</dt><dd className="font-medium text-status-warning">{aggregates.headline.quarantined_comments}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-foreground-muted">同标题多 ID 组</dt><dd className="font-medium text-status-warning">{duplicateTitleGroups}</dd></div>
          </dl>
        </div>

        <div className="rounded-card border border-border-divider p-4">
          <div className="mb-3 flex items-center gap-2 text-body-sm font-medium text-foreground">
            <XCircle className="h-4 w-4 text-status-error" strokeWidth={1.5} />
            当前不支持
          </div>
          <ul className="space-y-2 text-caption text-foreground-secondary">
            {unsupported.map(([label, supported]) => (
              <li key={label} className="flex items-center justify-between gap-3">
                <span>{label}</span>
                <span className={supported ? 'text-status-success' : 'text-status-error'}>
                  {supported ? '支持' : '不展示'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="flex items-start gap-3 rounded-card bg-status-warningBg p-4">
          <Tag className="mt-0.5 h-4 w-4 shrink-0 text-status-warning" strokeWidth={1.5} />
          <div>
            <p className="text-body-sm font-medium text-foreground">规则标签 · 待语义复核</p>
            <p className="mt-1 text-caption leading-relaxed text-foreground-secondary">
              使用 {manifest.tagging.dictionary_version} 词典的词法规则结果；标签情感不覆盖帖子或评论的实体情感。
            </p>
          </div>
        </div>
        <div className="flex items-start gap-3 rounded-card bg-surface-tertiary p-4">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-foreground-muted" strokeWidth={1.5} />
          <div>
            <p className="text-body-sm font-medium text-foreground">运行边界</p>
            <p className="mt-1 text-caption leading-relaxed text-foreground-secondary">
              未变更线上环境、未调用外部分析服务、未触发对外发送；按 Reddit 帖子编号去重，跨帖或转帖的同标题内容不做自动合并。
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
