import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  compareCrossPageReconciliationScopes,
  crossPageReconciliationAttributes,
  normalizeCrossPageReconciliationScope,
  type CrossPageReconciliationScope,
} from '../crossPageReconciliation';

const sharedScope = {
  sourceSnapshotId: 'reddit_voc_snapshot_v3',
  scope: 'momcozy',
  vocType: 'post_voc+comment_context_voc',
} as const;

function scope(
  overrides: Partial<CrossPageReconciliationScope> = {},
): CrossPageReconciliationScope {
  return {
    ...sharedScope,
    page: 'overview',
    startDate: '2026-06-16',
    endDate: '2026-07-15',
    endBoundary: 'inclusive',
    ...overrides,
  };
}

describe('cross-page reconciliation contract', () => {
  it('normalizes inclusive and exclusive calendar windows before comparison', () => {
    const overview = scope();
    const report = scope({
      page: 'reports',
      endDate: '2026-07-16',
      endBoundary: 'exclusive',
    });

    expect(normalizeCrossPageReconciliationScope(overview)).toMatchObject({
      startDate: '2026-06-16',
      endDateExclusive: '2026-07-16',
    });
    expect(compareCrossPageReconciliationScopes(overview, report)).toEqual({
      status: 'comparable',
      reasonCodes: [],
    });
  });

  it('rejects different business windows instead of forcing their values to match', () => {
    const overview = scope();
    const insights = scope({
      page: 'insights',
      startDate: '2026-04-17',
    });

    expect(compareCrossPageReconciliationScopes(overview, insights)).toEqual({
      status: 'not_comparable',
      reasonCodes: ['window_mismatch'],
    });
  });

  it('reports source, scope, VOC type, and window mismatches independently', () => {
    const left = scope();
    const right = {
      ...scope({
        page: 'reports',
        sourceSnapshotId: 'another_snapshot',
        startDate: '2026-07-01',
      }),
      scope: 'category' as never,
      vocType: 'post_voc' as never,
    };

    expect(compareCrossPageReconciliationScopes(left, right)).toEqual({
      status: 'not_comparable',
      reasonCodes: [
        'source_snapshot_mismatch',
        'scope_mismatch',
        'voc_type_mismatch',
        'window_mismatch',
      ],
    });
  });

  it('publishes the same machine-readable contract on overview, insights, and reports', () => {
    const sourceRoot = resolve(process.cwd(), 'src');
    const integrations = [
      ['pages/SnapshotDashboard.tsx', "page: 'overview'"],
      ['components/insights/SnapshotInsightsV3.tsx', "page: 'insights'"],
      ['pages/SnapshotReports.tsx', "page: 'reports'"],
    ] as const;

    for (const [relativePath, pageLiteral] of integrations) {
      const source = readFileSync(resolve(sourceRoot, relativePath), 'utf8');
      expect(source).toContain('crossPageReconciliationAttributes');
      expect(source).toContain('CROSS_PAGE_RECONCILIATION_RULE_CN');
      expect(source).toContain(pageLiteral);
    }

    expect(crossPageReconciliationAttributes(scope())).toMatchObject({
      'data-reconciliation-contract': 'same-source-scope-voc-type-window',
      'data-reconciliation-page': 'overview',
      'data-reconciliation-end-date-exclusive': '2026-07-16',
    });
  });
});
