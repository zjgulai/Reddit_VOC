import { ChevronRight, Clock3, Target } from 'lucide-react';
import { Link } from 'react-router-dom';
import { buildSnapshotEvidenceHref } from '../../features/redditSnapshot/evidenceLinks';
import type { RiskPriority, RiskTheme } from '../../features/redditSnapshot/types';

const PRIORITY_STYLES: Record<RiskPriority, string> = {
  P0: 'bg-status-errorBg text-status-error',
  P1: 'bg-status-warningBg text-status-warning',
  P2: 'bg-primary-light text-primary',
  P3: 'bg-surface-tertiary text-foreground-secondary',
  insufficient: 'bg-surface-tertiary text-foreground-muted',
};

const PRIORITY_LABELS: Record<RiskPriority, string> = {
  P0: '立即核查',
  P1: '优先复核',
  P2: '持续观察',
  P3: '常规跟踪',
  insufficient: '证据不足',
};

const REASON_LABELS: Record<string, string> = {
  risk_theme_gate_policy_missing: '风险判断规则缺失',
  risk_theme_gate_policy_not_frozen: '风险判断规则尚未确认',
  semantic_tag_not_promoted: '语义标签尚待复核',
  dictionary_default_priority_unsupported: '字典默认优先级不受支持',
  minimum_observed_entities_not_met: '观察实体数未达门槛',
  minimum_distinct_posts_not_met: '独立帖子数未达门槛',
  minimum_communities_not_met: '社区覆盖数未达门槛',
  minimum_brand_binding_rate_not_met: '品牌绑定率未达门槛',
};

function reasonLabel(reasonCode: string): string {
  return REASON_LABELS[reasonCode] ?? `未识别规则：${reasonCode}`;
}

function scopeSummary(theme: RiskTheme): string[] {
  return [
    ...theme.product_scope_ids.category.map((value) => `品类 ${value}`),
    ...theme.product_scope_ids.product_family.map((value) => `产品族 ${value}`),
    ...theme.product_scope_ids.spu_exact.map((value) => `SPU ${value}`),
  ];
}

export default function RiskThemePanel({
  themes,
  title = 'Momcozy 风险主题',
  subtitle = '按影响程度和证据充分度排序；证据不足的主题只列为关注项',
  evidenceContext,
}: {
  themes: RiskTheme[];
  title?: string;
  subtitle?: string;
  evidenceContext?: {
    releaseId: string;
    snapshotId: string;
    source: 'reports' | 'insights';
  };
}) {
  return (
    <section className="card p-5 sm:p-6" aria-labelledby="risk-theme-panel-title">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-primary-light">
            <Target className="h-[18px] w-[18px] text-primary" strokeWidth={1.5} />
          </div>
          <div>
            <h2 id="risk-theme-panel-title" className="text-h3 text-foreground">{title}</h2>
            <p className="mt-0.5 text-caption text-foreground-muted">{subtitle}</p>
          </div>
        </div>
        <span className="rounded-badge bg-surface-tertiary px-2.5 py-1 text-tiny text-foreground-secondary">
          展示 {Math.min(themes.length, 8)}/{themes.length}
        </span>
      </div>

      {themes.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {themes.slice(0, 8).map((theme) => {
            const scopes = scopeSummary(theme);
            return (
              <article key={theme.risk_theme_id} className="rounded-card border border-border-divider p-4 sm:p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-badge px-2.5 py-1 text-tiny font-semibold ${PRIORITY_STYLES[theme.effective_priority]}`}
                        data-business-priority={theme.effective_priority}
                      >
                        {PRIORITY_LABELS[theme.effective_priority]}
                      </span>
                      <span className="font-mono text-tiny text-foreground-muted">{theme.risk_theme_id}</span>
                    </div>
                    <h3 className={`mt-2 text-body font-semibold ${theme.effective_priority === 'P0' || theme.effective_priority === 'P1' ? 'text-status-error' : 'text-foreground'}`}>{theme.name_cn}</h3>
                    <p className="mt-0.5 text-caption text-foreground-muted">{theme.risk_level} · {theme.theme}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-center">
                    <div className="rounded-icon bg-surface-tertiary px-3 py-2">
                      <p className="text-body-sm font-semibold text-foreground">{theme.observed_entities.post}</p>
                      <p className="text-tiny text-foreground-muted">帖子</p>
                    </div>
                    <div className="rounded-icon bg-surface-tertiary px-3 py-2">
                      <p className="text-body-sm font-semibold text-foreground">{theme.observed_entities.comment}</p>
                      <p className="text-tiny text-foreground-muted">评论</p>
                    </div>
                  </div>
                </div>

                {theme.evidence_gate.status === 'insufficient' && (
                  <div className="mt-3 flex items-start gap-2 rounded-icon bg-surface-tertiary px-3 py-2 text-caption text-foreground-secondary">
                    <Clock3 className="mt-0.5 h-4 w-4 shrink-0 text-foreground-muted" strokeWidth={1.5} />
                    <span>仅作关注项：{theme.evidence_gate.reason_codes.map(reasonLabel).join(' · ') || '证据条件尚未满足'}</span>
                  </div>
                )}

                <div className="mt-4 grid gap-2 text-caption sm:grid-cols-3">
                  <div className="rounded-icon bg-surface-tertiary px-3 py-2 text-foreground-secondary">独立帖子 {theme.distinct_posts}</div>
                  <div className="rounded-icon bg-surface-tertiary px-3 py-2 text-foreground-secondary">社区 {theme.communities}</div>
                  <div className="rounded-icon bg-surface-tertiary px-3 py-2 text-foreground-secondary">品牌绑定 {(theme.brand_binding_rate * 100).toFixed(1)}%</div>
                </div>

                {scopes.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {scopes.slice(0, 6).map((scope) => (
                      <span key={scope} className="rounded-badge border border-primary/10 bg-primary-light/50 px-2 py-1 text-tiny text-foreground-secondary">{scope}</span>
                    ))}
                  </div>
                )}

                <div className="mt-4 border-t border-border-divider pt-3">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <p className="text-tiny font-medium text-foreground-secondary">原始证据</p>
                    <p className="text-tiny text-foreground-muted">
                      {theme.evidence_refs.length}/{theme.evidence_ref_count_total}{theme.evidence_refs_truncated ? ' · 已截断' : ''}
                    </p>
                  </div>
                  {theme.evidence_refs.length ? (
                    <div className="flex flex-wrap gap-2">
                      {theme.evidence_refs.slice(0, 4).map((evidence) => (
                        evidenceContext ? (
                          <Link
                            key={`${evidence.entity_type}:${evidence.entity_id}`}
                            to={buildSnapshotEvidenceHref({
                              postId: evidence.post_id,
                              commentId: evidence.entity_type === 'comment' ? evidence.entity_id : null,
                              releaseId: evidenceContext.releaseId,
                              snapshotId: evidenceContext.snapshotId,
                              source: evidenceContext.source,
                            })}
                            className="inline-flex items-center gap-1 rounded-badge border border-border-divider px-2.5 py-1.5 text-tiny font-medium text-primary hover:bg-primary-light"
                          >
                            {evidence.entity_type === 'post' ? '帖子' : '评论'} {evidence.entity_id}
                            <ChevronRight className="h-3.5 w-3.5" strokeWidth={1.5} />
                          </Link>
                        ) : (
                          <span key={`${evidence.entity_type}:${evidence.entity_id}`} className="rounded-badge border border-border-divider px-2.5 py-1.5 text-tiny text-foreground-muted">
                            {evidence.entity_type === 'post' ? '帖子' : '评论'} {evidence.entity_id}
                          </span>
                        )
                      ))}
                    </div>
                  ) : (
                    <p className="text-caption text-foreground-muted">当前公开投影没有可检索的证据 ID。</p>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="rounded-card border border-dashed border-border-divider bg-surface-tertiary p-5 text-caption text-foreground-muted">
          当前窗口没有通过契约的风险主题；这不等于不存在风险。
        </div>
      )}
    </section>
  );
}
