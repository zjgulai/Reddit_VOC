import { CheckCircle2, CircleMinus, CircleX, Clock3 } from 'lucide-react';

export type GovernanceStatus = 'verified' | 'provisional' | 'unavailable' | 'failed';

export interface GovernanceState {
  status: GovernanceStatus;
  label: string;
  detail: string;
}

export interface ArtifactBuildState extends GovernanceState {
  release_id: string;
  evidence_source: string | null;
  side_effect_boundaries: {
    production_unchanged: boolean;
    provider_call: boolean;
    database_write: boolean;
    live_send: boolean;
  };
}

export interface SiteDeploymentState extends GovernanceState {
  served_release_id: string;
  independent_deployment_source: string | null;
  promotion_state: GovernanceState;
  acceptance_state: GovernanceState;
}

export interface UiGovernanceContract {
  artifact_build_state: ArtifactBuildState;
  site_deployment_state: SiteDeploymentState;
  data_scope: GovernanceState;
  comparison_scope: GovernanceState;
  tag_maturity: GovernanceState;
}

const statusMeta = {
  verified: {
    text: '已验证',
    Icon: CheckCircle2,
    className: 'border-status-success/20 bg-status-successBg text-status-success',
  },
  provisional: {
    text: '仅观察',
    Icon: Clock3,
    className: 'border-primary/20 bg-primary/10 text-primary-dark',
  },
  unavailable: {
    text: '不可用',
    Icon: CircleMinus,
    className: 'border-border-divider bg-surface-tertiary text-foreground-secondary',
  },
  failed: {
    text: '失败',
    Icon: CircleX,
    className: 'border-status-error/20 bg-status-errorBg text-status-error',
  },
} satisfies Record<GovernanceStatus, {
  text: string;
  Icon: typeof CheckCircle2;
  className: string;
}>;

export interface GovernanceStatusBadgeProps {
  status: GovernanceStatus;
  label?: string;
  displayText?: string;
  className?: string;
}

export function GovernanceStatusBadge({
  status,
  label,
  displayText,
  className = '',
}: GovernanceStatusBadgeProps) {
  const { Icon, className: statusClassName, text } = statusMeta[status];
  const visibleText = displayText ?? (label && label !== text ? `${label} · ${text}` : text);

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-badge border px-2.5 py-1 text-tiny font-medium ${statusClassName} ${className}`.trim()}
      data-governance-status={status}
      data-ui-severity={status === 'failed' ? 'error' : undefined}
      aria-label={`${label ?? '治理状态'}：${displayText ?? text}`}
    >
      <Icon
        className="h-3.5 w-3.5 shrink-0"
        strokeWidth={1.5}
        aria-hidden="true"
        data-governance-glyph={status === 'failed' ? 'error' : undefined}
      />
      <span>{visibleText}</span>
    </span>
  );
}
