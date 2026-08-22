import { Database, Scale, Tags } from 'lucide-react';
import {
  GovernanceStatusBadge,
  type GovernanceStatus,
  type UiGovernanceContract,
} from './GovernanceStatusBadge';

type ScopeContract = Pick<
  UiGovernanceContract,
  'data_scope' | 'comparison_scope' | 'tag_maturity'
>;

export interface DataScopeBarProps {
  contract: ScopeContract;
  className?: string;
}

const dimensions = [
  { key: 'data_scope', Icon: Database },
  { key: 'comparison_scope', Icon: Scale },
  { key: 'tag_maturity', Icon: Tags },
] as const;

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

export function DataScopeBar({ contract, className = '' }: DataScopeBarProps) {
  const status = aggregateStatus(dimensions.map(({ key }) => contract[key].status));

  return (
    <section
      className={`rounded-card border border-border-divider bg-surface-primary px-4 py-3 shadow-card ${className}`.trim()}
      role="region"
      aria-label="数据治理范围"
      data-governance-component="data-scope-bar"
      data-governance-status={status}
      data-ui-severity={status === 'failed' ? 'error' : undefined}
    >
      <div className="grid gap-2 md:grid-cols-3 md:gap-0 md:divide-x md:divide-border-divider">
        {dimensions.map(({ key, Icon }) => {
          const state = contract[key];
          return (
            <div
              key={key}
              className="flex min-w-0 items-start gap-2.5 md:px-4 first:md:pl-0 last:md:pr-0"
              data-governance-dimension={key}
            >
              <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-icon bg-surface-tertiary text-foreground-secondary">
                <Icon className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-caption font-medium text-foreground">{state.label}</p>
                  <GovernanceStatusBadge
                    status={state.status}
                    displayText={state.status === 'provisional'
                      ? '观察口径'
                      : state.status === 'unavailable'
                        ? '当前不适用'
                        : undefined}
                  />
                </div>
                <p className="mt-0.5 text-tiny leading-relaxed text-foreground-muted">{state.detail}</p>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
