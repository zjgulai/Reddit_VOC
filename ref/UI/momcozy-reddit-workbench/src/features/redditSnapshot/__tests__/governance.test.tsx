import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  DataScopeBar,
  GovernanceContractError,
  GovernanceStatusBadge,
  ReleaseEvidenceCard,
  mapComparisonStatus,
  mapHighPriorityStatus,
  mapInsightsStatus,
  mapReportCoverageStatus,
  type UiGovernanceContract,
} from '../governance';

const governanceContract: UiGovernanceContract = {
  artifact_build_state: {
    status: 'verified',
    label: '构建产物已校验',
    detail: '静态资源与 manifest 绑定已通过本地校验。',
    release_id: 'reddit_voc_release_20260715_v2',
    evidence_source: 'current-release.json',
    side_effect_boundaries: {
      production_unchanged: true,
      provider_call: false,
      database_write: false,
      live_send: false,
    },
  },
  site_deployment_state: {
    status: 'verified',
    label: '当前服务身份已读取',
    detail: '只证明浏览器当前读取的 release identity。',
    served_release_id: 'reddit_voc_release_20260715_v2',
    independent_deployment_source: null,
    promotion_state: {
      status: 'verified',
      label: '生产提升',
      detail: '调用方不得在缺少独立来源时把此状态显示为 verified。',
    },
    acceptance_state: {
      status: 'verified',
      label: '生产验收',
      detail: '调用方不得在缺少独立来源时把此状态显示为 verified。',
    },
  },
  data_scope: {
    status: 'verified',
    label: '数据范围',
    detail: '历史快照与已合并增量。',
  },
  comparison_scope: {
    status: 'provisional',
    label: '对比范围',
    detail: 'Momcozy 主干与竞品方向性对比。',
  },
  tag_maturity: {
    status: 'unavailable',
    label: '标签成熟度',
    detail: '规则标签未完成全量人工复核。',
  },
};

describe('Reddit VOC UI governance components', () => {
  it('exposes all four governance states accessibly and reserves error severity for failed only', () => {
    const { container } = render(
      <div>
        <GovernanceStatusBadge status="verified" label="已验证" />
        <GovernanceStatusBadge status="provisional" label="暂定" />
        <GovernanceStatusBadge status="unavailable" label="不可用" />
        <GovernanceStatusBadge status="failed" label="失败" />
      </div>,
    );

    for (const status of ['verified', 'provisional', 'unavailable', 'failed']) {
      const badge = container.querySelector(`[data-governance-status="${status}"]`);
      expect(badge).toHaveAttribute('aria-label');
    }

    const errorNodes = container.querySelectorAll('[data-ui-severity="error"]');
    expect(errorNodes).toHaveLength(1);
    expect(errorNodes[0]).toHaveAttribute('data-governance-status', 'failed');
    expect(errorNodes[0].querySelector('[data-governance-glyph="error"]')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-governance-glyph="error"]')).toHaveLength(1);
  });

  it('renders one compact data scope bar with the three explicit governance dimensions', () => {
    render(<DataScopeBar contract={governanceContract} />);

    const bar = screen.getByRole('region', { name: '数据治理范围' });
    expect(bar).toHaveAttribute('data-governance-component', 'data-scope-bar');
    expect(bar).toHaveAttribute('data-governance-status', 'unavailable');
    expect(within(bar).getByText('数据范围')).toBeInTheDocument();
    expect(within(bar).getByText('对比范围')).toBeInTheDocument();
    expect(within(bar).getByText('标签成熟度')).toBeInTheDocument();
    expect(bar.querySelectorAll('[data-governance-dimension]')).toHaveLength(3);
  });

  it('defaults to served release identity and fails deployment promotion and acceptance closed', () => {
    const { container } = render(<ReleaseEvidenceCard contract={governanceContract} />);

    const card = screen.getByRole('region', { name: '发布证据' });
    expect(card).toHaveAttribute('data-governance-component', 'release-evidence-card');
    expect(card).toHaveAttribute('data-governance-status', 'unavailable');
    expect(screen.getAllByText('reddit_voc_release_20260715_v2')).toHaveLength(2);
    expect(screen.getByText('当前服务版本')).toBeInTheDocument();

    const promotion = container.querySelector('[data-release-check="promotion"]');
    const acceptance = container.querySelector('[data-release-check="acceptance"]');
    expect(promotion).toHaveAttribute('data-governance-status', 'unavailable');
    expect(acceptance).toHaveAttribute('data-governance-status', 'unavailable');
    expect(card).toHaveTextContent('缺少独立部署证据源');
    expect(card).not.toHaveTextContent('已部署');
    expect(card).not.toHaveTextContent('已验收');

    const details = card.querySelector('details');
    expect(details).not.toHaveAttribute('open');
    expect(details).toHaveTextContent('未变更线上环境');
    expect(details).toHaveTextContent('未调用外部分析服务');
    expect(details).toHaveTextContent('未写入业务数据库');
    expect(details).toHaveTextContent('未触发对外发送');
  });

  it('maps only typed structured statuses and never parses reason copy', () => {
    expect(mapReportCoverageStatus('complete')).toBe('verified');
    expect(mapReportCoverageStatus('partial')).toBe('provisional');
    expect(mapReportCoverageStatus('coverage_gap')).toBe('unavailable');
    expect(mapComparisonStatus('comparable')).toBe('verified');
    expect(mapComparisonStatus('provisional_observed_sample')).toBe('provisional');
    expect(mapComparisonStatus('unavailable')).toBe('unavailable');
    expect(mapInsightsStatus('passed_provisional_risk_threshold')).toBe('provisional');
    expect(mapHighPriorityStatus('unavailable_unfrozen_evidence_threshold')).toBe('unavailable');
  });

  it('fails closed on unknown governance enums instead of defaulting to unavailable', () => {
    expect(() => mapReportCoverageStatus('unknown' as never)).toThrow(GovernanceContractError);
    expect(() => mapComparisonStatus('unknown' as never)).toThrow(GovernanceContractError);
    expect(() => mapInsightsStatus('unknown')).toThrow(GovernanceContractError);
    expect(() => mapHighPriorityStatus('unknown')).toThrow(GovernanceContractError);
  });
});
