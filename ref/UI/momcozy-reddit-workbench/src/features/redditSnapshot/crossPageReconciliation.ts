export type CrossPageReconciliationPage = 'overview' | 'insights' | 'reports';
export type CrossPageReconciliationBoundary = 'inclusive' | 'exclusive';
export type CrossPageReconciliationStatus = 'comparable' | 'not_comparable';
export type CrossPageReconciliationReasonCode =
  | 'source_snapshot_mismatch'
  | 'scope_mismatch'
  | 'voc_type_mismatch'
  | 'window_mismatch';

export interface CrossPageReconciliationScope {
  page: CrossPageReconciliationPage;
  sourceSnapshotId: string;
  scope: 'momcozy';
  vocType: 'post_voc+comment_context_voc';
  startDate: string;
  endDate: string;
  endBoundary: CrossPageReconciliationBoundary;
}

export interface NormalizedCrossPageReconciliationScope {
  page: CrossPageReconciliationPage;
  sourceSnapshotId: string;
  scope: CrossPageReconciliationScope['scope'];
  vocType: CrossPageReconciliationScope['vocType'];
  startDate: string;
  endDateExclusive: string;
}

export interface CrossPageReconciliationResult {
  status: CrossPageReconciliationStatus;
  reasonCodes: CrossPageReconciliationReasonCode[];
}

export const CROSS_PAGE_RECONCILIATION_RULE_CN =
  '跨页对账：仅当来源快照、品牌范围、VOC 粒度和起止日期完全一致时比较数值；窗口不同则不比较。';

const CALENDAR_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function calendarDateTimestamp(value: string): number {
  if (!CALENDAR_DATE_PATTERN.test(value)) {
    throw new RangeError(`invalid calendar date: ${value}`);
  }
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  if (
    Number.isNaN(timestamp)
    || new Date(timestamp).toISOString().slice(0, 10) !== value
  ) {
    throw new RangeError(`invalid calendar date: ${value}`);
  }
  return timestamp;
}

function addCalendarDays(value: string, days: number): string {
  return new Date(calendarDateTimestamp(value) + days * 86_400_000)
    .toISOString()
    .slice(0, 10);
}

export function normalizeCrossPageReconciliationScope(
  scope: CrossPageReconciliationScope,
): NormalizedCrossPageReconciliationScope {
  calendarDateTimestamp(scope.startDate);
  const endDateExclusive = scope.endBoundary === 'inclusive'
    ? addCalendarDays(scope.endDate, 1)
    : new Date(calendarDateTimestamp(scope.endDate)).toISOString().slice(0, 10);
  if (scope.startDate >= endDateExclusive) {
    throw new RangeError(
      `reconciliation window must be non-empty: ${scope.startDate}..${endDateExclusive}`,
    );
  }
  return {
    page: scope.page,
    sourceSnapshotId: scope.sourceSnapshotId,
    scope: scope.scope,
    vocType: scope.vocType,
    startDate: scope.startDate,
    endDateExclusive,
  };
}

export function compareCrossPageReconciliationScopes(
  leftInput: CrossPageReconciliationScope,
  rightInput: CrossPageReconciliationScope,
): CrossPageReconciliationResult {
  const left = normalizeCrossPageReconciliationScope(leftInput);
  const right = normalizeCrossPageReconciliationScope(rightInput);
  const reasonCodes: CrossPageReconciliationReasonCode[] = [];

  if (left.sourceSnapshotId !== right.sourceSnapshotId) {
    reasonCodes.push('source_snapshot_mismatch');
  }
  if (left.scope !== right.scope) {
    reasonCodes.push('scope_mismatch');
  }
  if (left.vocType !== right.vocType) {
    reasonCodes.push('voc_type_mismatch');
  }
  if (
    left.startDate !== right.startDate
    || left.endDateExclusive !== right.endDateExclusive
  ) {
    reasonCodes.push('window_mismatch');
  }

  return {
    status: reasonCodes.length === 0 ? 'comparable' : 'not_comparable',
    reasonCodes,
  };
}

export function crossPageReconciliationAttributes(
  input: CrossPageReconciliationScope,
): Record<string, string> {
  const scope = normalizeCrossPageReconciliationScope(input);
  return {
    'data-reconciliation-contract': 'same-source-scope-voc-type-window',
    'data-reconciliation-page': scope.page,
    'data-reconciliation-source-snapshot-id': scope.sourceSnapshotId,
    'data-reconciliation-scope': scope.scope,
    'data-reconciliation-voc-type': scope.vocType,
    'data-reconciliation-start-date': scope.startDate,
    'data-reconciliation-end-date-exclusive': scope.endDateExclusive,
  };
}
