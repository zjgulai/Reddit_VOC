import { useState } from 'react';
import { ArrowUpRight, CircleUserRound, MessageSquareText, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';

export interface AggregatePersonaCardModel {
  cohortId: string;
  name: string;
  definition: string;
  statusLabel: string;
  avatarAlt: string;
  assignmentCount: number;
  distributionShare: number;
  /** null when the persona snapshot's assignment ids do not cover this cohort,
   *  so the entity split cannot be attributed. Render "—", never 0. */
  postCount: number | null;
  commentCount: number | null;
  threadCount: number | null;
  atomicReferenceCount: number | null;
  referenceTags: string[];
  evidenceHref: string | null;
  momcozyScoped: boolean;
}

export interface AggregatePersonaCardAvatarAsset {
  url: string | null;
  error: string | null;
  isFallback?: boolean;
}

interface AggregatePersonaCardProps {
  cohort: AggregatePersonaCardModel;
  avatarAsset: AggregatePersonaCardAvatarAsset;
}

export default function AggregatePersonaCard({
  cohort,
  avatarAsset,
}: AggregatePersonaCardProps) {
  const [decodeFailed, setDecodeFailed] = useState(false);
  const showAvatar = Boolean(avatarAsset.url) && !decodeFailed;
  const avatarError = decodeFailed ? '浏览器无法解码已校验头像资源' : avatarAsset.error;

  return (
    <article
      className="card flex h-full flex-col p-5 motion-reduce:transition-none motion-reduce:hover:transform-none"
      aria-labelledby={`${cohort.cohortId}-title`}
      data-testid="persona-cohort-card"
    >
      <div className="flex items-start gap-4">
        <div className="shrink-0">
          {showAvatar ? (
            <img
              src={avatarAsset.url ?? undefined}
              alt={cohort.avatarAlt}
              width="80"
              height="80"
              loading="lazy"
              decoding="async"
              onError={() => setDecodeFailed(true)}
              className="h-20 w-20 rounded-full bg-primary-light object-cover ring-4 ring-primary-light"
            />
          ) : (
            <div
              className="flex h-20 w-20 items-center justify-center rounded-full bg-surface-tertiary ring-4 ring-primary-light"
              role="img"
              aria-label={`${cohort.name}头像资源不可用`}
            >
              <CircleUserRound className="h-8 w-8 text-foreground-secondary" strokeWidth={1.5} aria-hidden="true" />
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="mb-2 inline-flex items-center gap-1.5 rounded-badge bg-primary-light px-2.5 py-1 text-tiny font-medium text-foreground-secondary">
            <ShieldCheck className="h-3.5 w-3.5 text-primary-hover" strokeWidth={1.5} aria-hidden="true" />
            合成插画 · 不代表真实 Reddit 用户
          </div>
          <h3 id={`${cohort.cohortId}-title`} className="text-h3 text-foreground">
            {cohort.name}
          </h3>
          <p className="mt-1 text-caption leading-relaxed text-foreground-secondary">{cohort.definition}</p>
          <p className="mt-2 inline-flex rounded-badge bg-surface-tertiary px-2 py-1 text-tiny text-foreground-secondary">
            {cohort.statusLabel}
          </p>
          <p className="ml-2 mt-2 inline-flex rounded-badge bg-primary-light px-2 py-1 text-tiny font-semibold text-primary-hover">
            画像归属占比 {cohort.distributionShare.toFixed(2)}%
          </p>
        </div>
      </div>

      {avatarError && (
        <div className="mt-4 rounded-icon border border-border-divider bg-surface-tertiary px-3 py-2" role="status" data-governance-status="unavailable" aria-label="头像状态：资源不可用，已使用合成占位">
            <p className="text-caption font-medium text-foreground">
              {avatarAsset.isFallback ? '已使用治理合成占位' : '头像资源不可用'}
            </p>
          <p className="mt-0.5 break-words text-tiny text-foreground-secondary">{avatarError}</p>
        </div>
      )}

      <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {[
          ['画像样本', cohort.assignmentCount],
          ['帖子', cohort.postCount ?? '—'],
          ['评论', cohort.commentCount ?? '—'],
          ['证据线程', cohort.threadCount ?? '—'],
          ['画像依据', cohort.atomicReferenceCount ?? '—'],
        ].map(([label, value]) => (
          <div key={label} className="rounded-icon bg-surface-tertiary px-3 py-2.5">
            <p className="text-body-sm font-semibold tabular-nums text-foreground">{value}</p>
            <p className="mt-0.5 text-tiny text-foreground-secondary">{label}</p>
          </div>
        ))}
      </div>

      <div className="mt-4 flex items-start gap-2 rounded-icon border border-border-divider p-3">
        <MessageSquareText className="mt-0.5 h-4 w-4 shrink-0 text-primary-hover" strokeWidth={1.5} aria-hidden="true" />
        <p className="text-caption leading-relaxed text-foreground-secondary">
          {cohort.momcozyScoped
            ? '根据 Momcozy 相关真实帖子与评论中的需求、问题和场景形成；不推断作者身份，也不代表独立用户人口占比。'
            : '根据真实帖子与评论中的需求、问题和场景形成；不推断作者身份，也不代表独立用户人口占比。'}
        </p>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5" aria-label="画像证据维度">
        {cohort.referenceTags.map((tag) => (
          <span key={tag} className="rounded-badge bg-surface-tertiary px-2.5 py-1 text-tiny text-foreground-secondary">
            {tag}
          </span>
        ))}
      </div>

      <div className="mt-auto pt-5">
        {cohort.evidenceHref ? (
          <Link
            to={cohort.evidenceHref}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-button px-3 py-2 text-body-sm font-medium text-foreground-secondary transition-colors hover:bg-primary-light hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-hover focus-visible:ring-offset-2"
          >
            查看证据
            <ArrowUpRight className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
          </Link>
        ) : (
          <span className="inline-flex min-h-11 items-center px-3 py-2 text-body-sm text-foreground-muted">暂无可钻取证据</span>
        )}
      </div>
    </article>
  );
}
