---
title: Current Production Four-format Export Closure
doc_type: execution_evidence
status: complete_public_readonly
date: 2026-07-27
evidence_grade: L3_public_readonly_browser_download_acceptance
production_boundary: unchanged
remote_write: false
deploy: false
provider_call: false
database_write: false
schedule_change: false
live_send: false
---

# Current Production Four-format Export Closure

## Exact target

```text
site=https://reddit.lute-tlz-dddd.top
release_sha256=8a8a5a01772c73987cd7e471eedd8818b5b0c0d9efbdba4e8cecad54e7b5eded
release_id=reddit_voc_release_20260724_dashboard_fix_v1
pointer_sha256=bc715e35ace76028124152708d63662eaddfb6ff955d441a5d1d5a0bc5f382ca
reports_dataset_version=reddit_voc_reports_20260723_v3_47c49395e785_history2
report_id=daily:2026-07-23:2026-07-24
```

## Execution

The existing fail-closed export validator used callback template SHA
`1d4f337b7aff7620c373e1625b6877084b94b242fc0b54d3ff84cae2306aebc0`
and pinned Playwright CLI `0.1.17`.

The first attempt stopped at `playwright_open_execution_failed` before page
interaction or download. A direct same-runner diagnostic opened and closed the
public page successfully. The full validator was rerun in a new output root;
the failed root was not reused.

## Accepted downloads

```text
CSV
bytes=382
sha256=654ee1318d3165a3a266de04d57e8468aafc759e49a2a1e384ad079695674a07
headers=6
business_rows=7

PDF
bytes=10303087
sha256=fae12d02341157acf5ca01e1a36e728615466c5268bc8d11fbf95819a082cd76
page_markers=2

PPTX
bytes=181803
sha256=eb7095678a0542cd1021b255d0f588f9f30feafa093db1e42ef001f6ab26ce1f
package_members=47
business_content_verified=true

DOCX
bytes=9792
sha256=1aaab416bc86bcb50308c93a15eed99942dfc1d958faac958c37adff568db93c
package_members=22
business_content_verified=true
```

## Receipt

```text
path=tmp/reddit-voc-production-export-acceptance/8a8a5a01772c73987cd7e471eedd8818b5b0c0d9efbdba4e8cecad54e7b5eded-20260727-a2/acceptance-receipt.json
sha256=8f737906bfe83d32487169883e3afb53d476985b593d235dc310770405e5a5bb
status=passed_public_readonly_export_acceptance
download_count=4
release_and_report_binding_verified=true
browser_errors=0
same_origin_http_failures=0
external_requests=0
```

## Boundary

The browser only read the public site and downloaded client-generated files.
No remote write, deployment, Provider call, database write, schedule change,
live send, or production change occurred. This evidence does not apply to
unpromoted local source changes.
