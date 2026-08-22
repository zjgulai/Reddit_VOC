import { useEffect, useId, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, CheckCircle2, Clock3, Database, Info, Layers3, X } from 'lucide-react';
import type {
  CoverageEvidenceStatus,
  DataFreshnessEvidence,
  FreshnessEvidenceStatus,
  ReleaseRecencyStatus,
} from './freshness';

function displayTime(value: string | null): string {
  if (!value) return '未提供';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: value.includes('T') ? '2-digit' : undefined,
    minute: value.includes('T') ? '2-digit' : undefined,
    hour12: false,
  }).format(parsed).replaceAll('/', '-');
}

function completenessLabel(evidence: DataFreshnessEvidence): string {
  if (evidence.completenessPercent === null) return '未提供';
  const basis = evidence.completenessBasis === 'data_owner_declaration'
    ? '数据所有者声明'
    : evidence.completenessBasis;
  return `${evidence.completenessPercent}%${basis ? ` · ${basis}` : ''}`;
}

const statusClasses: Record<FreshnessEvidenceStatus, string> = {
  verified: 'border-status-success/20 bg-status-successBg text-status-success',
  provisional: 'border-status-warning/20 bg-status-warningBg text-status-warning',
  unavailable: 'border-border-divider bg-surface-secondary text-foreground-muted',
};

const recencyClasses: Record<ReleaseRecencyStatus, string> = {
  fresh: 'border-status-success/20 bg-status-successBg text-status-success',
  partial: 'border-status-warning/20 bg-status-warningBg text-status-warning',
  awaiting: 'border-primary/20 bg-primary-light text-primary',
  stalled: 'border-status-error/20 bg-status-errorBg text-status-error',
  stale: 'border-status-warning/20 bg-status-warningBg text-status-warning',
  failed: 'border-status-error/20 bg-status-errorBg text-status-error',
  rollback: 'border-status-warning/20 bg-status-warningBg text-status-warning',
  unavailable: 'border-border-divider bg-surface-secondary text-foreground-muted',
};

const coverageClasses: Record<CoverageEvidenceStatus, string> = {
  complete: 'border-status-success/20 bg-status-successBg text-status-success',
  partial: 'border-status-warning/20 bg-status-warningBg text-status-warning',
  'owner-attested': 'border-primary/20 bg-primary-light text-primary',
  unavailable: 'border-border-divider bg-surface-secondary text-foreground-muted',
};

export default function DataFreshnessBar({ evidence }: { evidence: DataFreshnessEvidence }) {
  const [isEvidenceOpen, setEvidenceOpen] = useState(false);
  const titleId = useId();

  useEffect(() => {
    if (!isEvidenceOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setEvidenceOpen(false);
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [isEvidenceOpen]);

  return (
    <section
      className="rounded-card border border-border-divider bg-white px-4 py-3 shadow-card sm:px-5"
      aria-label="数据版本与新鲜度证据"
      data-testid="data-freshness-bar"
      data-evidence-status={evidence.status}
      data-recency-status={evidence.recencyStatus}
      data-coverage-status={evidence.coverageStatus}
    >
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <StateBadge className={statusClasses[evidence.status]} icon={<CheckCircle2 className="h-3.5 w-3.5" strokeWidth={1.75} />}>
            {evidence.statusLabel}
          </StateBadge>
          <StateBadge
            className={recencyClasses[evidence.recencyStatus]}
            icon={evidence.recencyStatus === 'stalled' || evidence.recencyStatus === 'failed'
              ? <AlertTriangle className="h-3.5 w-3.5" strokeWidth={1.75} />
              : <Clock3 className="h-3.5 w-3.5" strokeWidth={1.75} />}
          >
            {evidence.recencyLabel}
          </StateBadge>
          <StateBadge className={coverageClasses[evidence.coverageStatus]} icon={<Layers3 className="h-3.5 w-3.5" strokeWidth={1.75} />}>
            {evidence.coverageLabel}
          </StateBadge>
          <span className="inline-flex min-w-0 items-center gap-2 text-caption text-foreground-secondary">
            <Clock3 className="h-4 w-4 shrink-0 text-primary" strokeWidth={1.5} aria-hidden="true" />
            <strong className="font-medium text-foreground">{evidence.dataAsOfLabel}</strong>
            <time dateTime={evidence.dataAsOf ?? undefined}>{displayTime(evidence.dataAsOf)}</time>
          </span>
          <span className="inline-flex min-w-0 items-center gap-2 text-caption text-foreground-secondary">
            <Clock3 className="h-4 w-4 shrink-0 text-foreground-muted" strokeWidth={1.5} aria-hidden="true" />
            <strong className="font-medium text-foreground">{evidence.currentTimeLabel}</strong>
            <time dateTime={evidence.currentTime}>{displayTime(evidence.currentTime)}</time>
          </span>
          {evidence.projectionAsOfLabel ? (
            <span className="inline-flex min-w-0 items-center gap-2 text-caption text-foreground-secondary">
              <Database className="h-4 w-4 shrink-0 text-primary" strokeWidth={1.5} aria-hidden="true" />
              <strong className="font-medium text-foreground">{evidence.projectionAsOfLabel}</strong>
              <time dateTime={evidence.projectionAsOf ?? undefined}>{displayTime(evidence.projectionAsOf)}</time>
            </span>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => setEvidenceOpen(true)}
          className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-button px-3 text-caption font-medium text-primary hover:bg-primary-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
          aria-haspopup="dialog"
        >
            <Info className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
            查看数据证据
        </button>
      </div>
      {isEvidenceOpen && typeof document !== 'undefined' ? createPortal(
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-foreground/35 p-4 backdrop-blur-[2px] sm:p-6"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setEvidenceOpen(false);
          }}
          data-testid="data-evidence-backdrop"
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            className="flex max-h-[min(760px,calc(100vh-2rem))] w-full max-w-5xl flex-col overflow-hidden rounded-card border border-border-divider bg-white shadow-xl"
          >
            <header className="flex items-start justify-between gap-4 border-b border-border-divider px-5 py-4 sm:px-6">
              <div>
                <div className="flex items-center gap-2 text-primary">
                  <Info className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
                  <h2 id={titleId} className="text-h3 text-foreground">数据证据与口径</h2>
                </div>
                <p className="mt-1 text-caption text-foreground-muted">用于核对数据时间、版本、覆盖范围与结构债务，不改变当前分析结果。</p>
              </div>
              <button
                type="button"
                onClick={() => setEvidenceOpen(false)}
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-button text-foreground-muted hover:bg-surface-secondary hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                aria-label="关闭数据证据"
                autoFocus
              >
                <X className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
              </button>
            </header>
            <div className="overflow-y-auto px-5 py-5 sm:px-6">
              <div className="grid gap-4 text-caption text-foreground-secondary sm:grid-cols-2 lg:grid-cols-3">
                <EvidenceField title="当前北京时间">{displayTime(evidence.currentTime)}</EvidenceField>
                <EvidenceField title="数据时间口径">{evidence.dataAsOfBasis}</EvidenceField>
                <EvidenceField title="新鲜度判定">
                  <span className="block">{evidence.recencyLabel}</span>
                  <span className="mt-1 block">预期周期：{displayTime(evidence.expectedPeriodEnd)}</span>
                  <span className="mt-1 block">SLO 截止：{displayTime(evidence.deadline)}</span>
                </EvidenceField>
                <EvidenceField title="采集血缘">
                  <span className="block break-all">运行：{evidence.collectorRunId ?? '未随当前 release 提供'}</span>
                  <span className="mt-1 block break-all">批次：{evidence.sourceBatchId ?? '未随当前 release 提供'}</span>
                </EvidenceField>
                <EvidenceField title="发布采集窗口">{displayTime(evidence.releaseWindowStart)} 至 {displayTime(evidence.releaseWindowEnd)}</EvidenceField>
                <EvidenceField title="页面投影窗口">{evidence.coverageWindowStart ?? '未提供'} 至 {evidence.coverageWindowEnd ?? '未提供'}</EvidenceField>
                <EvidenceField title="中心与页面投影"><span className="block break-all">中心：{evidence.centerSnapshotId ?? '未提供'}</span><span className="mt-1 block break-all">投影：{evidence.projectionDatasetVersion}</span></EvidenceField>
                <EvidenceField title="发布时间"><span className="block">release pointer：{displayTime(evidence.releaseGeneratedAtUtc)}</span><span className="mt-1 block">页面投影：{displayTime(evidence.projectionGeneratedAtUtc)}</span></EvidenceField>
                <EvidenceField title="页面业务时间">
                  <span className="block">{evidence.projectionAsOfLabel ?? '未提供'}：{displayTime(evidence.projectionAsOf)}</span>
                  <span className="mt-1 block">{evidence.projectionAsOfBasis ?? '未提供独立页面时间口径'}</span>
                </EvidenceField>
                <EvidenceField title="最新观测事件">{displayTime(evidence.observationMax)}</EvidenceField>
                <EvidenceField title="覆盖证据"><span className="block">{completenessLabel(evidence)}</span><span className="mt-1 block">{evidence.evidenceClass === 'owner_attested_not_crawler_proof' ? '数据所有者确认，非 crawler proof' : evidence.evidenceClass ?? '未提供 evidence class'}</span></EvidenceField>
                <EvidenceField title="Release ID" wide><span className="break-all">{evidence.releaseId}</span></EvidenceField>
                {evidence.structuralCoverage ? (
                  <EvidenceField title="结构覆盖与债务" wide>
                    <span className="block leading-relaxed">完整 {evidence.structuralCoverage.full.toLocaleString('zh-CN')} · 部分 {evidence.structuralCoverage.partial.toLocaleString('zh-CN')} · 仅父帖 {evidence.structuralCoverage.postOnly.toLocaleString('zh-CN')} · 来源观察 {evidence.structuralCoverage.sourceObserved.toLocaleString('zh-CN')}</span>
                    <span className="mt-1 block">待父帖关联评论 {evidence.structuralCoverage.unresolvedParentComments.toLocaleString('zh-CN')}</span>
                  </EvidenceField>
                ) : null}
              </div>
            </div>
          </section>
        </div>,
        document.body,
      ) : null}
    </section>
  );
}

function StateBadge({ className, icon, children }: { className: string; icon: ReactNode; children: ReactNode }) {
  return (
    <span className={`inline-flex min-h-8 items-center gap-1.5 rounded-badge border px-2.5 text-tiny font-semibold ${className}`}>
      <span aria-hidden="true">{icon}</span>
      {children}
    </span>
  );
}

function EvidenceField({ title, children, wide = false }: { title: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={`min-w-0 rounded-card border border-border-divider bg-surface-secondary/55 p-4 ${wide ? 'sm:col-span-2 lg:col-span-3' : ''}`}>
      <strong className="block text-body-sm font-semibold text-foreground">{title}</strong>
      <div className="mt-2 leading-relaxed">{children}</div>
    </div>
  );
}
