---
title: PPC-02 Cross-page Reconciliation Closure
doc_type: execution_evidence
status: complete_local
date: 2026-07-27
production_boundary: unchanged
provider_call: false
remote_write: false
live_send: false
deployment: false
---

# PPC-02 Cross-page Reconciliation Closure

## Decision

Overview, insights, and reports are comparable only when all of the following
fields match:

1. Source snapshot ID.
2. Business scope: `momcozy`.
3. VOC grain: `post_voc+comment_context_voc`.
4. Calendar start date.
5. Normalized exclusive calendar end date.

The page name is retained as provenance but does not affect comparability.
Dashboard and quarter windows provide inclusive end dates; report periods
provide exclusive end dates. Both are normalized to a half-open
`[start, end)` interval before comparison.

## Implemented

- Added
  `src/features/redditSnapshot/crossPageReconciliation.ts` with strict calendar
  validation, boundary normalization, reason-coded comparison, and shared DOM
  attributes.
- Added the same machine-readable reconciliation contract to the overview
  rolling window, the insights rolling quarter, and the reports complete
  calendar period.
- Added a visible Chinese explanation on all three pages: values are compared
  only for the same source, scope, VOC grain, and date window.
- Kept the brand-health card's existing full-history projection independent
  from the overview range tabs.

## Validation

```text
npm test -- src/features/redditSnapshot/__tests__/crossPageReconciliation.test.ts
1 test file passed
4 tests passed

SnapshotDashboardV3.test.tsx
5 tests passed

SnapshotInsightsV3.test.tsx
4 tests passed

SnapshotReportsV3.test.tsx
9 tests passed

npm run lint
exit 0
8 existing react(only-export-components) warnings

npm run build
TypeScript passed
Vite passed
2654 modules transformed
```

## Boundary

This closure is local source and validation evidence only. It did not create a
candidate release, authorization packet, permit, remote write, Provider call,
deployment, live send, or production change.
