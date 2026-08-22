import { Box, ChevronDown, Fingerprint, ShieldCheck } from 'lucide-react';
import {
  GovernanceStatusBadge,
  type GovernanceState,
  type GovernanceStatus,
  type UiGovernanceContract,
} from './GovernanceStatusBadge';

export interface ReleaseEvidenceCardProps {
  contract: Pick<UiGovernanceContract, 'artifact_build_state' | 'site_deployment_state'>;
  className?: string;
}

function unavailableWithoutDeploymentSource(state: GovernanceState): GovernanceState {
  return {
    ...state,
    status: 'unavailable',
    detail: '缺少独立部署证据源，不能声明生产提升或生产验收完成。',
  };
}

const severityOrder: Record<GovernanceStatus, number> = {
  verified: 0,
  provisional: 1,
  unavailable: 2,
  failed: 3,
};

function aggregateStatus(statuses: readonly GovernanceStatus[]): GovernanceStatus {
  return statuses.reduce<GovernanceStatus>((current, candidate) => (
    severityOrder[candidate] > severityOrder[current] ? candidate : current
  ), 'verified');
}

function boundaryText(
  key: keyof UiGovernanceContract['artifact_build_state']['side_effect_boundaries'],
  value: boolean,
): string {
  const labels: Record<
    keyof UiGovernanceContract['artifact_build_state']['side_effect_boundaries'],
    [string, string]
  > = {
    production_unchanged: ['未变更线上环境', '线上环境已变更'],
    provider_call: ['已调用外部分析服务', '未调用外部分析服务'],
    database_write: ['已写入业务数据库', '未写入业务数据库'],
    live_send: ['已触发对外发送', '未触发对外发送'],
  };
  const [active, inactive] = labels[key];
  return value ? active : inactive;
}

export function ReleaseEvidenceCard({ contract, className = '' }: ReleaseEvidenceCardProps) {
  const artifact = contract.artifact_build_state;
  const deployment = contract.site_deployment_state;
  const hasIndependentDeploymentSource = Boolean(deployment.independent_deployment_source?.trim());
  const promotion = hasIndependentDeploymentSource
    ? deployment.promotion_state
    : unavailableWithoutDeploymentSource(deployment.promotion_state);
  const acceptance = hasIndependentDeploymentSource
    ? deployment.acceptance_state
    : unavailableWithoutDeploymentSource(deployment.acceptance_state);
  const status = aggregateStatus([
    deployment.status,
    promotion.status,
    acceptance.status,
  ]);

  return (
    <section
      className={`card overflow-hidden ${className}`.trim()}
      role="region"
      aria-label="发布证据"
      data-governance-component="release-evidence-card"
      data-governance-status={status}
      data-ui-severity={status === 'failed' ? 'error' : undefined}
    >
      <div className="flex flex-wrap items-start justify-between gap-4 p-5">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-surface-tertiary text-foreground-secondary">
            <Fingerprint className="h-[18px] w-[18px]" strokeWidth={1.5} aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="text-tiny font-medium uppercase tracking-[0.12em] text-foreground-muted">
              当前服务版本
            </p>
            <p className="mt-1 break-all font-mono text-body-sm font-semibold text-foreground">
              {deployment.served_release_id}
            </p>
            <p className="mt-1 text-caption leading-relaxed text-foreground-secondary">
              {deployment.detail}
            </p>
          </div>
        </div>
        <GovernanceStatusBadge status={deployment.status} label={deployment.label} />
      </div>

      <div className="grid border-y border-border-divider bg-surface-secondary md:grid-cols-2 md:divide-x md:divide-border-divider">
        {[
          ['promotion', promotion],
          ['acceptance', acceptance],
        ].map(([key, state]) => {
          const typedState = state as GovernanceState;
          return (
            <div
              key={key as string}
              className="flex items-start justify-between gap-3 px-5 py-3.5"
              data-release-check={key}
              data-governance-status={typedState.status}
              data-ui-severity={typedState.status === 'failed' ? 'error' : undefined}
              aria-label={`${typedState.label}：${typedState.status}`}
            >
              <div className="min-w-0">
                <p className="text-caption font-medium text-foreground">{typedState.label}</p>
                <p className="mt-0.5 text-tiny leading-relaxed text-foreground-muted">
                  {typedState.detail}
                </p>
              </div>
              <GovernanceStatusBadge status={typedState.status} />
            </div>
          );
        })}
      </div>

      <details className="group px-5 py-4">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-caption font-medium text-foreground marker:content-none">
          <span className="flex items-center gap-2">
            <Box className="h-4 w-4 text-foreground-muted" strokeWidth={1.5} aria-hidden="true" />
            构建产物与副作用边界
          </span>
          <ChevronDown
            className="h-4 w-4 text-foreground-muted transition-transform group-open:rotate-180"
            strokeWidth={1.5}
            aria-hidden="true"
          />
        </summary>
        <div className="mt-4 grid gap-4 border-t border-border-divider pt-4 md:grid-cols-[1fr_auto]">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-foreground-muted" strokeWidth={1.5} aria-hidden="true" />
              <p className="text-caption font-medium text-foreground">{artifact.label}</p>
              <GovernanceStatusBadge status={artifact.status} />
            </div>
            <p className="mt-1 text-tiny leading-relaxed text-foreground-muted">{artifact.detail}</p>
            <dl className="mt-3 space-y-1 text-tiny text-foreground-secondary">
              <div className="flex gap-2">
                <dt className="text-foreground-muted">构建版本</dt>
                <dd className="break-all font-mono">{artifact.release_id}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="text-foreground-muted">验证依据</dt>
                <dd className="break-all font-mono">{artifact.evidence_source ?? '暂无'}</dd>
              </div>
            </dl>
          </div>
          <ul className="space-y-1 rounded-card bg-surface-tertiary px-3 py-2 text-tiny font-medium text-foreground-secondary">
            {Object.entries(artifact.side_effect_boundaries).map(([key, value]) => (
              <li key={key} className="font-mono">
                {boundaryText(
                  key as keyof typeof artifact.side_effect_boundaries,
                  value,
                )}
              </li>
            ))}
          </ul>
        </div>
      </details>
    </section>
  );
}
