---
title: Reddit VOC Acceptance Evidence
doc_type: acceptance
status: active
created: 2026-07-09
updated: 2026-08-11
owner: codex
production_boundary: g6r0_candidate_frozen_production_unchanged_activation_no_go
provider_call: false
live_send: false
---

# Reddit VOC Acceptance Evidence

## 2026-08-11 G6R0 Daily-report Translation Runtime Candidate Acceptance

- L3 production read-only evidence confirms the 2026-08-11 live report was sent with
  `translation_status=provider_missing_config`: the host secret existed, while the legacy Docker launcher did not
  propagate it. The production 08:00 bounded route and separate 08:10 secondary forwarder remain unchanged.
- The admissible local report release is
  `6992babec0539499f40063ddccfffa629d77b33e313d27b0f9abb614aca888d5`; manifest SHA is
  `35c1c6bd5d74bad72ae6132005a4304316fe3b66f02a3306c7b0f38ae66cd1d4`. An out-of-repository read-only copy
  passed 218/218 self-contained tests, 21-module import closure, no repository fallback, exact post-test manifest and
  zero bytecode residue.
- The real-release-byte shadow transaction is
  `d3395ef4af663606decec7d18e02ce0835b3822d28567bf3175a4c1aa122b181`; package manifest SHA is
  `48d6714e66ae726fde7b43533c1772ae0cbde026eae6411a8daa6274b7c948de`. Fifteen fault-injection tests passed,
  including symlink escape refusal, post-switch crash recovery, rollback I/O retry and cross-artifact identity binding.
- Admission receipt SHA:
  `91cfedb69ca352075f85294748b661e17751e97a790d32a33099df68de0f8b37`. Receipt status is
  `candidate_frozen_local_closure_passed_production_activation_no_go`; its canonical payload self-hash and all bound
  release/transaction receipts were independently recomputed.
- Candidate acceptance covers the local runtime closure only: read-only DeepSeek secret injection, complete typed
  title/body/comment translation gates, one-time prepared build, frozen-outbox send, translation-failure send block,
  independent Provider ledger and rollback package.
- Production activation is rejected until a new gate closes the 08:00 exact scheduled send permit, retires or converts
  the 08:10 secondary sender, performs production daily-namespace/pinned-image bootstrap smoke, and obtains bounded real
  DeepSeek translation evidence.

```text
evidence_grade=L3-production-read-only + L2-local-real-release-shadow
report_release=6992babec0539499f40063ddccfffa629d77b33e313d27b0f9abb614aca888d5
report_manifest=35c1c6bd5d74bad72ae6132005a4304316fe3b66f02a3306c7b0f38ae66cd1d4
transaction_release=d3395ef4af663606decec7d18e02ce0835b3822d28567bf3175a4c1aa122b181
admission_receipt=91cfedb69ca352075f85294748b661e17751e97a790d32a33099df68de0f8b37
report_tests=218/218
transaction_tests=15/15
runtime_candidate_frozen=true
production_activation_ready=false
provider_call=false
live_send=false
production_write=false
database_write=false
cron_change=false
container_command=false
container_restart=false
public_current_switch=false
remote_candidate_write=false
production unchanged
```

## 2026-07-27 Current Production Four-format Export Acceptance

- Live public markers identify current release
  `8a8a5a01772c73987cd7e471eedd8818b5b0c0d9efbdba4e8cecad54e7b5eded`,
  pointer release ID `reddit_voc_release_20260724_dashboard_fix_v1`, and pointer
  SHA `bc715e35ace76028124152708d63662eaddfb6ff955d441a5d1d5a0bc5f382ca`.
- A pinned Playwright 0.1.17 read-only run downloaded CSV, PDF, PPTX and DOCX
  from latest complete daily report `daily:2026-07-23:2026-07-24`.
- Report binding passed for dataset
  `reddit_voc_reports_20260723_v3_47c49395e785_history2`, manifest
  `0a95f263a9df87738b3e5678a93b71950f996fe128bc2fa0e32cbf0b2a243ce7`,
  index `0af4521e7476f11ddba486fa2d8f454430056e051730e1fdce8e9566817a85ca`,
  and daily document
  `d227f27ac80160396b4d0f0ee4ac5ebfc22657f1391068701fbed14afb68f623`.
- Four-file validation passed structure, business content and exact
  release/report binding. Browser errors, same-origin HTTP failures and
  external requests were all zero.
- Acceptance receipt:
  `tmp/reddit-voc-production-export-acceptance/8a8a5a01772c73987cd7e471eedd8818b5b0c0d9efbdba4e8cecad54e7b5eded-20260727-a2/acceptance-receipt.json`;
  SHA
  `8f737906bfe83d32487169883e3afb53d476985b593d235dc310770405e5a5bb`.

```text
evidence_grade=L3_public_readonly_browser_download_acceptance
production_current=8a8a5a01772c73987cd7e471eedd8818b5b0c0d9efbdba4e8cecad54e7b5eded
release_id=reddit_voc_release_20260724_dashboard_fix_v1
four_exports_complete=true
download_count=4
browser_errors=0
same_origin_http_failures=0
external_requests=0
remote_write=false
deploy=false
provider_call=false
database_write=false
schedule_change=false
live_send=false
production unchanged by export acceptance
```

This receipt applies only to the observed current production release. Later
unpromoted local source changes do not inherit it.

## 2026-07-17 A9 Insights-only Production Acceptance

- Exact owner authorization: packet
  `7ff1227cc63e03c1102de9bad4371361d3cf00da6739cbec91d5a9c29bcdceb8`, permit
  `8e68138ba62a624e5c03af9070615ad6623af37358638de8a37d00b7f04c95c5`, release
  `9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5` and expected current
  `627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4`.
- The isolated 18339 candidate, compare-and-swap cutover and 18338 production smoke passed under the same
  deployment lock. Remote promotion receipt SHA:
  `c4e7d2f01b186bfb2313cf5176e388c0c5e6d8ba795e4fcaf15709ffdf6e597a`.
- Fresh post-promotion evidence found the production container healthy, restart 0, UID/GID 101, read-only and
  zero-mount; candidate and port 18339 residue were zero. Collector and translation IDs/restarts, cron, shared
  Nginx, database/report markers and unrelated running-container inventory remained stable.
- Public HTTPS evidence SHA
  `f0c9b1b8bcbf09bada49fd7ecf691f1d2cbcbce7081faf9bb4e3aae620609a6f` passed 13 routes, eight public artifacts,
  20 security 404s, health, TLS, release marker and data pointer. Browser r2 evidence SHA
  `086d3bbf4171bbed26cdc22757f186f2fc216a04628fe2064a93ac78fb956176` passed 26/26 desktop/mobile pages,
  three report states and cases 33/17/1 with zero browser errors, same-origin HTTP failures or external requests.
- The first browser attempt remains preserved as failed evidence SHA
  `5b6465cff1ada8ca41ebfd868fe1f54ee24911da9359fd7ac0b6bff7e4a9050e`. It exposed missing waits in the E2E
  interaction harness, not a release rebuild; the corrected harness SHA is
  `cac4c7662ad95abca1639eff3f9c845678aeb163c4305329f4514225198a641a`, with 10/10 local harness tests before r2.
- Production acceptance receipt SHA:
  `c37248efc026457286adbc3d7d8eab9005d24072e889afab67b120004518255a`. Immutable permit-consumption receipt
  SHA: `20d4d05d832e42427ec37c6e26b1e3d68434a618f1e1b286cdb55503c0259058`. Rollback target
  `627fbab6...2478bed4` remains checksum-verified and ready; rollback was not executed.

```text
evidence_grade=L4-authorized-live
production_current=9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5
data_release=reddit_voc_release_20260716_v3_818f7eae7627_ui2
posts=3494
stored_comments=27158
linked_comments=20205
unresolved_parent_comments=6943
quarantined_comments=10
historical_collection_completeness_percent=100
insights_site_remote_write=true
collector_modified=false
cron_modified=false
shared_nginx_modified=false
tls_modified=false
dns_modified=false
other_docker_environment_modified=false
provider_call=false
database_write=false
schedule_change=false
live_send=false
four_exports_complete=false
registry_automation_enabled=false
```

The previous release's CSV/PDF/PPTX/DOCX receipt is historical evidence and is not inherited as a fresh 4/4
acceptance for this release.

## 2026-07-16 Previous Production and Four-format Export Acceptance

- Exact owner authorization: packet
  `ace4553d7007703e081a4a0a4a654417d332368661b357d972d1e16891de4f6e`, release
  `627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4`.
- At that checkpoint, production pointed to data release `reddit_voc_release_20260716_v3_818f7eae7627_ui2`:
  3,494 posts and 27,158 stored comments = 20,205 linked + 6,943 unresolved-parent +
  10 quarantined. Historical collection completeness follows the owner's 100% declaration;
  unresolved-parent remains relationship debt.
- Public acceptance passed 13 routes, eight artifacts, 20 security 404s, 26/26 pages and
  cases 33/17/1 with zero browser, same-origin HTTP and external-request failures.
- Production acceptance receipt SHA:
  `c609b83bd200fc010afb9bbc89e7bdc61b4f9135b318ea0892485eec9abdeb1d`.
- Permit consumption receipt SHA:
  `de757bd20e2fa3a6571c07c11b1f8106570020ef7ff6fe3dac5a38cca469323c`.
- A later read-only browser run downloaded CSV/PDF/PPTX/DOCX from the same production
  daily report and validated all four structures, business content and release/report binding.
  Export acceptance receipt SHA:
  `c2ce743d6babd7d6abbb114efebff5db0041411e39e6befdfd53c0878d6ca5a4`.
- Two-point read-only HTTPS observation found `release.json` and `current-release.json`
  byte-stable and terminal/quiescent. Monitor receipt SHA:
  `8ab8dee2d853f420c64c1d4d23d6bf45a6d3b2c66d78b14b19c1a76a0020ad88`.

```text
evidence_grade=L4-authorized-live + L3-public-readonly-export
production_current=627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4
provider_call=false
database_write=false
schedule_change=false
live_send=false
four_exports_complete=true
registry_automation_enabled=false
latest_collection_integrated=true
production unchanged by export acceptance
production unchanged by monitor acceptance
```

## 2026-07-15 Plan C Authorized Production Acceptance

- Exact owner authorization: packet
  `83d5ebeaf2345bc78495ed99064d34dcb4f23d09d2c8eda5274110f50a510570`, release
  `a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3`.
- Fresh L3 matched old current `9e0d2313...d650`; the exact TGZ, image, manifest and dist passed
  remote verification. Candidate 18339 passed 13 routes, eight public artifacts and 20 security
  404s before the compare-and-swap cutover.
- Production container `f43dbccc...e49e` is healthy, restart 0, UID 101, read-only, zero-mount and
  serves pointer `reddit_voc_release_20260715_70a917e5bdf0`.
- Public HTTPS and headless browser acceptance passed 26/26 pages, six report states, cases
  38/12/0, collector links, zero browser errors and zero external requests.
- Acceptance receipt SHA:
  `b5fcd6821de7f4047b1deb9bee6bd60c3d81bcaa6380fc2d8e8912f0a5a76ade`.
- Collector, LibreTranslate, shared Nginx, cron, database/report state and other Docker environments
  were unchanged. Candidate/18339/staging/upload residue is zero; old release remains rollback-ready.

```text
evidence_grade=L4-authorized-live
production_current=a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3
provider_call=false
database_write=false
schedule_change=false
live_send=false
four_exports_complete=false
registry_automation_enabled=false
latest_collection_integrated=true
latest_collection_fully_hydrated=false
```

## 2026-07-13 Task 21R Local Compatibility Evidence

- The reviewed legacy content path now accepts only `SearchPost` and
  `SearchCrosspost`; only the exact nested
  `SearchTelemetryTrackingContext` metadata contract is exempted. Unknown or
  drifted `post` wrappers remain fail-closed.
- A new immutable, source-SHA-bound read-only corpus audit contract reports
  strict-pass artifacts, wrapper and disposition counts, recognized/eligible/
  outside/invalid counts, payload integrity and exact candidate/provenance
  parity without database writes or external calls.
- Tests: reindex `26/26`, related provider/validation/CLI/wrapper `200/200`,
  serialized full suite `452/452` using the configured complete Python runtime.
  The system-Python attempt's seven missing-dependency import errors were not
  treated as passing evidence.
- Candidate release manifest: canonical `22/22`, SHA-256
  `88f3d58c89980ed0c685796c340c6752c11f5394e61409f6beeb8a4303b3938f`.
- The real frozen DB/raw corpus is not local, so `670/670` real-corpus audit is
  pending. No subagent or independent reviewer was used by explicit owner
  instruction; primary-agent self-review found no remaining issue in the
  changed scope.

```text
evidence_grade=L2-fixture-or-dry-run
local_only
production unchanged
provider_call=false
provider_attempt_made=false
ssh_used=false
remote_transfer=false
real_corpus_gate_executed=false
staging_reindex_attempted=false
database_write=local-test-only
live_send=false
independent_review=false
second_remote_reindex_authorized=false
Task14_acceptance=false
Task15_authorized=false
Task22_authorized=false
```

Task 21R closes the local wrapper-compatibility defect only. A second remote
reindex still requires explicit authorization and must first exact-pass the
real `670`-artifact read-only gate. See
`.superpowers/sdd/task-21r-legacy-wrapper-compatibility-report.md`.

## 2026-07-13 Task 21 Authorized Remote Reindex Evidence

- The owner authorized only transfer of manifest SHA
  `347c6ede1fe36852509dffe051fa7bf2b4d0c1e24ead8dda1af085bc44ff9d94`
  and at most one digest-pinned network-disabled staging reindex.
- The exact bundle tree SHA is
  `bf72561aac84588c5e0ae87baddfa3c2775bf278bac99df610e5158c090950da`.
  Frozen source DB SHA is
  `f2b2a2b2322749bc1b584ea0dd7f05cb084041be452e3521d7616fdf287362c6`;
  frozen raw inventory is `725` files at tree SHA
  `1012eb52df0f9264937998d2798d11f12f046eb9e460a0f42327b5533ce961b0`.
- Read-only preflight passed `20/20` checks and bound SHA
  `3c9f5122df3f96b9825a3190942ae0853f9f017a16fecab750d775496969b475`.
- Exactly one reindex ran. It returned exit code `1`,
  `failed/strict_discovery_schema_unknown`; no target DB was published. The
  byte-identical stdout/failure-report SHA is
  `9de8ca1170a9479d269fc2f6ab2421513b0cc0a01a52d530658d4e07a8ee1a62`.
- Postflight returned `0`, all `14/14` invariants passed, and its SHA is
  `8bf8746bd0b8e29270258d2dd8abed42367824ec471947c50d658c4026dbf9b4`.
  Original/frozen source and raw inputs plus the production DB/container remain
  unchanged; Provider/live-send stayed false and no target/sidecar/temp remains.
- Independent remote read-only postflight review returned `CLEAN_NO_P0_P1` with
  high confidence. Independent schema-gap review found three P1 compatibility
  defects and no P0; the failure boundary itself remained correct.
- Read-only structural diagnosis found `670` legacy discovery artifacts:
  the `635` empty pages are strict-v2 compatible, while all `35` non-empty pages
  fail (`33` telemetry container ambiguity and `2` unaccepted Crosspost
  wrappers). The explicit content rows are `241` SearchPost plus `2`
  SearchCrosspost, deriving `238` eligible and `5` outside-window rows with
  exact source candidate/provenance parity. Payload SHA mismatch count is zero.

```text
evidence_grade=L4-authorized-live
staging_only
production unchanged
provider_call=false
provider_attempt_made=false
remote_transfer=true
staging_reindex_attempted=true
reindex_attempt_count=1
staging_reindex_status=failed
reindex_stop_reason=strict_discovery_schema_unknown
target_database_published=false
failure_report_published=true
live_send=false
Task14_acceptance=false
Task15_authorized=false
Task22_authorized=false
```

Task 21 is closed as `failed_closed`, not accepted. The permanent one-shot guard
is consumed. Local compatibility repair, a new reviewed manifest and any second
remote attempt all require separate authorization. See
`.superpowers/sdd/task-21-remote-reindex-report.md`.

## 2026-07-13 Task 20 Local Verification Evidence

- Task 20 is authorized only for local code, fixtures, tests, documentation,
  independent review preparation and release-manifest preparation. It does not
  authorize SSH, remote transfer/reindex, Provider calls, production merge, Git
  push or DingTalk.
- The locally verified implementation covers append-only budget-extension
  authorization, hydration-resume accounting, bounded round-robin discovery and
  an offline strict discovery reindex path. This is local machinery-readiness
  evidence, not full historical collection or remote/production acceptance.
- Tests: budget extension `15/15`, hydration resume `11/11`, CLI `56/56`,
  reindex `19/19`, CLI plus reindex `75/75`, combined regression `243/243`,
  validation/replay/reindex `108/108`, serialized offline full suite `445/445`.
- Independent review: `PASS_NO_P0_P1`.
- Reviewed release manifest: canonical `22/22`, SHA-256
  `347c6ede1fe36852509dffe051fa7bf2b4d0c1e24ead8dda1af085bc44ff9d94`.

```text
evidence_grade=L2-fixture-or-dry-run
local_only
production unchanged
provider_call=false
provider_attempt_made=false
ssh_used=false
remote_transfer=false
remote_reindex_authorized=false
database_write=local-test-only
staging_database_write=false
live_send=false
Task14_acceptance=false
Task15_authorized=false
Task21_authorized=false
Task22_authorized=false
```

Task 20 local verification is closed. Task 21 would separately authorize an
exact new-manifest bundle transfer and at most one network-none staging reindex;
Task 22 would separately authorize a specific Provider budget-extension packet.
Neither is authorized, and the historical collection is still incomplete. See
`.superpowers/sdd/task-20-budget-extension-and-discovery-reindex-report.md`.

## 2026-07-13 Task 19 Authorized Remote Replay Evidence

- Owner authorized only the exact manifest SHA
  `c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc`
  transfer and one network-disabled staging replay.
- Atomic transfer verified `22/22` reviewed hashes, exact `23/23` files and
  bundle tree
  `d5554d72d724cf46b65de5621ba0a787dc20254a400cc26cb6453db0291b6940`.
- Final independently approved runner SHA
  `f9efc59fc94c7bba7899a75bf7e429c6ec891c0b70b33d612c83bdf7b24c1dd3`
  exact-bound the source/raw/production baselines, prepublished evidence files,
  then permanently created the SHA guard before the sole replay.
- The `env -i`, digest-pinned `--network none` replay returned exit code `0`,
  `complete/replay_complete`, `fingerprints.equivalent=true`,
  `provider_attempt_made=false` and `live_send=false`.
- Replay DB SHA is
  `3504190ab2b80ad1a003da27574455802f4184499eeaa7d458a6b771c3a8c638`.
  Source/target row counts and canonical fingerprints match for all six replay
  tables. Replay Provider attempts and delivery previews are both zero.
- Postflight source DB/raw tree/Provider/delivery and production DB/container
  baselines remained exact. SQLite integrity/FK passed; sidecar, temp, marker,
  one-shot and live-send counts are zero.

```text
evidence_grade=L4-authorized-live
staging_only
production unchanged
provider_call=false
provider_attempt_made=false
remote_transfer=true
staging_replay_attempted=true
replay_attempt_count=1
staging_replay_status=complete
replay_database_published=true
live_send=false
Task14_acceptance=false
Task15_authorized=false
```

This is replay proof, not full-coverage acceptance. The frozen source remains
partial and formal full validation was not run. See
`.superpowers/sdd/task-19-remote-replay-report.md`.

## 2026-07-13 Task 18 Local Replay Repair Evidence

- RED proved the current set-equality defect with one artifact lane plus one
  configured page-zero budget-exhausted checkpoint-only lane.
- Replay now preserves only the exact legal zero-page state: configured lane,
  integer-zero page/discovered/unique/consecutive-old counts, all cursor/time
  and cursor-contract fields exactly `None`, manifest/run/checkpoint
  `partial`, exact `budget_exhausted/ProviderBudgetExhausted`, and checkpoint
  request count equal to the exhausted manifest request count and cap.
- Artifact-only, unconfigured, positive-page, non-partial,
  not-yet-exhausted, empty-string, SQLite REAL and field-drift cases remain
  fail-closed. No artifact is fabricated. Seed-only replay remains compatible.
- Positive replay preserves the checkpoint exactly while target Provider
  attempts remain zero and target manifest
  `(provider_request_count, provider_call, live_send)` remains `(0, 0, 0)`.
- Verification: focused `5/5`, validation `56/56`, offline isolated full suite
  `351/351`, manifest contract `1/1`, reviewed hashes `22/22`, and two
  independent read-only reviews `APPROVED`.
- Task 18 close-time candidate manifest SHA:
  `c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc`.
  At the Task 18 boundary it had not been transferred; Task 19 later transferred
  and replayed this exact candidate under separate authorization.

```text
evidence_grade=L2-fixture-or-dry-run
local_only
production unchanged
provider_call=false
provider_attempt_made=false
ssh_used=false
remote_transfer=false
remote_replay_authorized=false
database_write=local-test-only
staging_database_write=false
live_send=false
Task14_acceptance=false
Task15_authorized=false
```

Task 18 did not create Task 14 acceptance. Task 19 later published a replay DB,
but no full-validation acceptance report or merge plan exists. See
`.superpowers/sdd/task-18-zero-page-budget-checkpoint-replay-report.md`.

## 2026-07-13 Task 17 Authorized Remote Replay Evidence

- Owner authorized only the exact manifest SHA
  `0663168b890cbd858068548eb3b43ee70345e01854090f42ae0baf91ac9fe0ba`
  bundle transfer and at most one network-disabled staging replay.
- Transfer verified `22/22` reviewed hashes, exact `23/23` regular files, no
  xattr/symlink/extra entries and remote tree SHA
  `d538e1fd662740e484f818f8e22fdf8e186b8ad367e4b40a944e95752ace1da2`.
- A permanent SHA-bound attempt guard was created before the only replay.
  Runner SHA was
  `89077fb363d0e9511c5be8052702e0d18be4a14946da6a900ca40bb27075d50c`;
  replay used the reviewed digest wrapper's `--network none` path and a clean
  `env -i` replay-only environment.
- Replay returned `failed/discovery_checkpoint_mismatch`, exit code `1`,
  `provider_attempt_made=false`, `live_send=false`; canonical result SHA is
  `4c857db837f81c0b59b97e5c603d3126c3448fad8cb511279114d1a21978073b`.
- Read-only aggregate diagnosis found `30` discovery checkpoint lanes, one
  artifact lane and `29` checkpoint-only lanes. All 29 are page-zero
  `partial/budget_exhausted`; the artifact lane has no page-count mismatch.
- Pre/post source DB SHA, 725-file raw tree, Provider `670`, delivery zero,
  production DB/container and historical bundle trees matched. No replay DB,
  replay temp, marker, one-shot container or live-send artifact remains.

```text
evidence_grade=L4-authorized-live
staging_only
production unchanged
provider_call=false
provider_attempt_made=false
remote_transfer=true
staging_replay_attempted=true
replay_attempt_count=1
staging_replay_status=failed
replay_database_published=false
live_send=false
Task14_acceptance=false
Task15_authorized=false
```

At Task 17 close, the next safe work was local-only replay-contract TDD for
zero-page checkpoint lanes. The Task 18 section above records its local
completion; no replay retry, Provider call, full validation, merge plan,
production merge, Git push or DingTalk was authorized by Task 17. See
`.superpowers/sdd/task-17-remote-replay-report.md`.

## 2026-07-13 Task 16 Canonical-Order Replay Repair Evidence

- Owner authorized the next local safe step only: root-cause analysis, replay
  repair, tests, reviewed manifest refresh and evidence synchronization.
- RED proved both directions of the defect: replay failed when canonical object
  keys exchanged invalid-row ordinals, and collection recorded client insertion
  order instead of archive byte order.
- Collection now parses the exact canonical bytes it archives. Replay compares
  an exact page-level multiset of base disposition and persisted fields, then
  reconstructs frozen source ordinal order. It does not use null wildcard,
  partial substitution, cross-page matching or relaxed fingerprints.
- Four source-tamper cases—post ID, ordinal, artifact and capture time—return
  `failed/discovery_occurrence_mismatch`, publish no target and retain
  `provider_attempt_made=false`, `live_send=false`.
- Verification: focused GREEN `2/2`, tamper subcases `4/4`, related suite
  `155/155`, Python 3.11 backfill `263/263`, isolated full suite `346/346`,
  wrapper syntax OK, manifest `22/22`, independent review `APPROVED`.
- Current local candidate manifest SHA:
  `0663168b890cbd858068548eb3b43ee70345e01854090f42ae0baf91ac9fe0ba`.
  The Task 14A SHA `ec5548...52253` and Task 13/14 SHA
  `471dc848...fb949e` remain immutable historical execution evidence.

```text
evidence_grade=L2-fixture-or-dry-run
local_only
production unchanged
provider_call=false
provider_attempt_made=false
remote_transfer=false
staging_database_write=false
live_send=false
Task14_acceptance=false
Task15_authorized=false
ready_for_owner_authorization
```

This section records the Task 16 local L2 state. Task 17 later exercised the
candidate against the frozen remote snapshot and reached the next strict
checkpoint gate. See `.superpowers/sdd/task-17-remote-replay-report.md`.

## 2026-07-13 Task 14A Authorized Remote Replay Evidence

- Owner authorized only a manifest-SHA-versioned reviewed bundle transfer and
  one `--network none` staging replay.
- Candidate manifest
  `ec5548c6606e587ae8d9d18809ae643553a03306a44ef2371867a64659a52253`
  was installed as an exact 23-file versioned bundle without changing the
  historical `/code` manifest/tree hashes.
- Replay returned `failed/discovery_occurrence_mismatch`,
  `provider_attempt_made=false`, `live_send=false`; no replay DB was published.
  Canonical result JSON SHA is
  `f3325553e6e51bc0a62739defecbdcaa75d08a17cba776431357e301c75301d2`.
- Read-only diagnosis found an ordinal where replay parsing had a post ID while
  the source occurrence stored null `post_id`, URL and timestamp. Task 14A
  initially interpreted this as a second historical persistence shape; Task 16
  showed that interpretation was unproven and reproduced the observation via
  canonical object-key reordering within the same page-level row multiset.
- Postchecks: replay/temp/marker/one-shot counts all zero, staging source DB SHA
  stayed `f2b2a2b2322749bc1b584ea0dd7f05cb084041be452e3521d7616fdf287362c6`,
  production DB/container pre/post state matched, delivery stayed zero, and no
  live-send artifact exists.

```text
evidence_grade=L4-authorized-live
staging_only
production unchanged
provider_call=false
provider_attempt_made=false
remote_transfer=true
staging_replay_attempted=true
staging_replay_status=failed
live_send=false
Task14_acceptance=false
Task15_authorized=false
```

See `.superpowers/sdd/task-14a-remote-replay-report.md`. No full validation,
merge-plan, production merge, Git push or DingTalk ran.

## 2026-07-13 Task 14 Replay Repair Local Evidence

Authorization and boundary:

- Owner authorized local replay-contract repair, regression tests and a new
  reviewed manifest candidate only.
- Remote transfer/replay, additional Provider requests, production merge, Git
  push and DingTalk were not authorized.

Actual evidence:

- A new replay fixture first reproduced the Task 14 mismatch as RED:
  expected `complete`, actual `failed`.
- Collector and replay now share one `discovery_occurrence_contract`; invalid
  rows preserve any parsed identity/time fields, missing-title remains invalid,
  and the time window remains `[start, end)`.
- Provider regression locks fully empty, partial-identity and missing-title
  invalid-row persistence. Replay regression proves source/target occurrence
  rows and fingerprints are equivalent.
- Python 3.11 backfill family `261/261 OK`; workspace full suite `344/344 OK`;
  independent related-suite rerun `97/97 OK`.
- Independent code/manifest review returned `APPROVED` with zero actionable
  findings.
- Canonical local candidate manifest SHA:
  `ec5548c6606e587ae8d9d18809ae643553a03306a44ef2371867a64659a52253`,
  reviewed file hashes `22/22` matching.
- Historical Task 14 executed manifest SHA remains
  `471dc848cdadff544a8e7009e044ca2cdba03e2add81f741d0d37b4dd0fb949e`;
  it was not rewritten.

Evidence-grade decision:

```text
evidence_grade=L2-fixture-or-dry-run
local_only
production unchanged
provider_call=false
remote_transfer=false
staging_database_write=false
live_send=false
ready_for_owner_authorization
```

This proves the local fixture contract passed; it did not prove compatibility
with every historical invalid-row persistence shape. The later authorized
remote replay still failed. The collected snapshot also still has 30 partial
lanes and 238 `budget_deferred` candidates.

## 2026-07-12 Historical Backfill Task 14 Option B Evidence

Authorization:

- Owner-approved cumulative budget `670`, subreddit sweep `1`, probe SHA
  `75abc643a745ac0a63c2e65d7c0bcda4167981594980b2c664448a1bb206e2bc`
  and release-manifest SHA
  `471dc848cdadff544a8e7009e044ca2cdba03e2add81f741d0d37b4dd0fb949e`.
- Canonical owner-authorization SHA:
  `dffd03fb276c2c90be3f0803f0923b35cab2c338d2ba330ba709a662cd7982ca`.
- Explicitly excluded: production merge, Git push and DingTalk.

Actual collect evidence:

- Immutable report SHA:
  `fa551a86f0508c3c962701246839ea58e48b734f43ca38fcb3cc8277ab3d2f76`.
- Exact result: `partial/budget_exhausted`, cumulative requests `670/670`, all
  attempts `succeeded`, `provider_call=true`, `live_send=false`.
- 15 dynamic and 15 subreddit lanes were frozen into the contract. Only the
  first `Momcozy` dynamic lane committed pages (`670`); the other 29 lanes
  committed zero. Hydration also stopped at budget exhaustion.
- Raw artifacts `725`, occurrences `24,845`, candidates `238` all
  `budget_deferred`, issues `0`, delivery previews `0`, integrity `ok`, FK
  violations `0`.
- Cursor chain `669/669`, distinct payload/cursor counts `670/670`, duplicate
  cursor count `0`. First-lane oldest seen timestamp is
  `2026-06-18T20:48:35.770000+00:00`, so approved history was not covered.

Replay and acceptance evidence:

- Network-disabled replay returned `failed/discovery_occurrence_mismatch`,
  `provider_attempt_made=false`, `live_send=false`.
- Read-only diagnosis found 16,013 partial-identity invalid occurrences that
  collect preserves but replay normalizes to all-null identity fields before
  strict comparison. Replay correctly removed its unpublished temporary DB.
- No replay DB remained. Formal full validation therefore failed its input
  precondition and generated no acceptance report. No merge plan was run.
- Independent final audit decision: Task 14 authorization/safety boundary
  compliant, collection acceptance failed; stop before merge-plan and Task 15.

Boundary:

```text
evidence_grade=L4-authorized-live-partial
staging_only
production unchanged
provider_call=true
provider_attempt_made=true
provider_request_count=670
actor_run=false
live_send=false
Task14_acceptance=false
Task15_authorized=false
```

Production DB inode/size/mtime/SHA and production container
ID/image/start/restart/running state were identical before and after; production
DB SHA remained
`8d762c64cea055c4b361676d8c1da4214b9208afa0084408bde333723074a52d`.

## 2026-07-12 Historical Backfill Task 13 Contract Probe Evidence

Authorization:

- Owner-authorized scope: transfer only the reviewed bundle/staging snapshot and
  execute at most four TikHub contract-probe attempts.
- Explicitly excluded: Task 14 full collection, production merge, Git push,
  deploy and DingTalk.

Actual evidence:

- The stale repository SSH identity failed before any remote change. The
  owner-supplied repo-external replacement identity restored access; no private
  key content entered the repository, transfer or container.
- Remote release exact-set verification: manifest `22/22`, total files `23`,
  symlinks/forbidden entries `0`, release archive SHA
  `06093e2d9dedaa47aa78afab219c48f8068de2f7151c9b5f98c0b5b06bb9e814`.
- Remote staging matched the accepted local 58-file inventory SHA
  `4149f5663936fca0cab78f28140d9f94af76a36c408c7cb3d86ea557eb6bd12d`
  before the probe.
- Digest-pinned one-shot image:
  `python@sha256:f5cf0344c9886ff24d34797578d5d7dd6e8911ae0fe5962bb55d0f89603ec361`.
- Probe: `ready`, `probe_page_limit`, attempts `2/2 succeeded` within the cap of
  `4`, committed pages `2`, unique candidates `9`, occurrences `406`.
- Cursor path
  `["data","search","dynamic","components","main","pageInfo","endCursor"]`;
  cursor schema SHA
  `5a84fbe4871635778aaf66ff75c03feb6cdaa857d1f274a8befa40038a7416dd`.
- Raw artifacts/captures/files `57/57/57`, delivery `0`, SQLite integrity
  `ok`, foreign-key violations `0`, mount/container/temp-helper residue `0`.
- Probe report SHA:
  `75abc643a745ac0a63c2e65d7c0bcda4167981594980b2c664448a1bb206e2bc`.
- Production container ID/image/start/restart/running state and production DB
  inode/size/mtime/SHA were identical before and after. Production DB SHA:
  `8d762c64cea055c4b361676d8c1da4214b9208afa0084408bde333723074a52d`.
- Independent pre-transfer and final probe audits both returned `APPROVED`.

Evidence-grade decision: `L4-authorized-live` for the completed bounded probe
only. The Task 13 closeout boundary was `staging_only`, `production unchanged`,
`provider_call=true`, `provider_attempt_made=true`, request count `2`,
`actor_run=false`, `live_send=false`, and `Task14_authorized=false`.

Budget packet:

- Dynamic only: cumulative `335`, remaining `333`, subreddit sweep `0`.
- Dynamic plus reviewed subreddit sweep: cumulative `670`, remaining `668`,
  subreddit sweep `1`.
- Both options bind probe SHA
  `75abc643a745ac0a63c2e65d7c0bcda4167981594980b2c664448a1bb206e2bc`
  and release-manifest SHA
  `471dc848cdadff544a8e7009e044ca2cdba03e2add81f741d0d37b4dd0fb949e`.
- At that Task 13 boundary, cost uncertainty was
  `high_unbounded_comment_pagination` and neither option was authorized yet.

## 2026-07-12 Historical Backfill Task 12 Local Seed Evidence

Required evidence:

- Enforce the `lsof` single-writer preflight.
- Import the fixed 55-file seed corpus into the isolated local staging DB.
- Re-run the identical seed command and prove deterministic idempotence.
- Pass seed-scope validation without Provider, delivery, or production writes.
- Keep the run root stable before any later transfer.

Actual evidence:

- Preflight: `/usr/sbin/lsof` present, source JSON `55`, DB initially absent,
  concurrent DB openers `0`.
- First seed and identical second seed both returned the exact baseline:
  files `55/48/7/0/0/0`, entities `48/1,894/1,942`, coverage `45/3/0`.
- The second seed left DB size and SHA-256 byte-identical:
  `f8cfa0727be667ae2f9c6d8b89372251cb50db08b53bd370cf22b380ce082c43`.
- Seed acceptance SHA-256:
  `f6060cd81136010b6716b32760f2c50404e388bd774662b4d8dac5fd9ae91076`.
  It is canonical JSON with `27/27` checks true, zero failed checks/issues,
  `status=accepted`, `replay_status=not_run`, and `full_ready=false`.
- Counts include raw captures/artifacts `55/55`, threads/comments/analyses
  `48/1,894/1,942`, Provider attempts `0`, and delivery previews `0`.
- Independent read-only audit decompressed and rehashed all 55 gzip payloads,
  verified JSON, lineage and `0600` file permissions, DB integrity/FK, current
  manifest `22/22`, and the exact UTC window
  `[2024-12-31T16:00:00Z, 2026-07-11T16:00:00Z)`.

Historical blocker and resolution:

- During the first audit, BaiduNetdisk PID `881` opened raw archive files and
  generated 48 `.baiduyun.uploading.cfg` sidecars. The owner then confirmed
  synchronization was paused and explicitly authorized sidecar cleanup.
- Pre-cleanup proof held the sidecar count at 48 for five seconds with zero
  open files and zero non-regular sidecars. Exactly 48 files were deleted; the
  canonical relative-path list SHA-256 was
  `ca113b45569258484642565c075dc9bec779c1b03456dc6a138f283b7c196838`.
- Post-cleanup validation stayed byte-identical: DB SHA
  `f8cfa0727be667ae2f9c6d8b89372251cb50db08b53bd370cf22b380ce082c43`,
  acceptance SHA
  `f6060cd81136010b6716b32760f2c50404e388bd774662b4d8dac5fd9ae91076`,
  and `27/27` checks accepted.
- The exact run root is now 55 gzip raw files, one SQLite DB and two JSON
  reports: total `58`, sidecars `0`, symlinks/special/unexpected nodes `0`,
  openers `0`. Repeated canonical inventory SHA-256 is
  `4149f5663936fca0cab78f28140d9f94af76a36c408c7cb3d86ea557eb6bd12d`.
- Independent final re-audit returned `APPROVED` after three matching inventory
  hashes, including two samples ten seconds apart.

Evidence-grade decision: `allowed_with_label`; Task 12 is
`local stable snapshot complete`. Supported boundary is `production unchanged`,
`provider_call=false`, `actor_run=false`, `provider_attempt_made=false`,
`live_send=false`, and no Git stage/commit/push. Historical BaiduNetdisk sync
remains recorded; at the Task 12 boundary, Task 13 transfer and Provider
authorization were both false.

## 2026-07-12 Historical Backfill Task 11 Acceptance

Required evidence:

- Independently calculate the fixed 55-file seed baseline twice without network
  or future-staging-derived expected values.
- Store exact canonical baseline and cursor contracts under `config/backfill/`.
- Store an exact release manifest that hashes every reviewed runtime file,
  excludes itself from the map, and contains no secret/runtime payload path.
- Pass the focused repository release-bundle contract, all backfill modules, and
  the complete local test suite before Task 12.

Actual evidence:

- Direct source parse and formal importer in `TemporaryDirectory` both returned
  files `55/48/7/0/0/0`, entities `48/1,894/1,942`, coverage `45/3/0`, source
  inventory SHA
  `af39a40c8ed657f440f9db6595d5f4e8e4a26164f43ffa78373215b40b3e881b`,
  and partial-ID SHA
  `1664b77cb94992959a0dc638d25580aad41aa65e8665462490c78d5220532769`.
- `momcozy-seed-baseline-20250101-20260711.json` SHA:
  `ec3fd0aac2ba32b89348a4f98935bc1a851d9250e39304285107f671c1944abc`.
- `momcozy-comment-cursor-contract-20260711.json` SHA:
  `f5dc8d698a4f38bfb6f49bbe4fb220ef67c8f811393576a407308921f0a997fd`.
- `momcozy-backfill-release-manifest-20260711.json` SHA:
  `471dc848cdadff544a8e7009e044ca2cdba03e2add81f741d0d37b4dd0fb949e`.
- Focused release-bundle TDD contract: initial missing-file RED, then `1/1`
  GREEN; final exact-bundle contract rerun: `5/5`, `OK`.
- Backfill suite: `260/260`, `186.855s`, `OK`, with no external network call.
- Complete local suite: `343/343`, `224.683s`, `OK`; the first exit-0 run had
  truncated output, so the same suite was rerun with fixture stdout suppressed
  to obtain the complete `Ran 343 tests ... OK` evidence.
- Post-static-fix focused storage suite: `56/56`, `0.672s`, `OK`.
- Static checks: no-index whitespace check `41/41`, wrapper `bash -n` `2/2`,
  and targeted sensitive-value scan `41/41` all clean.
- Independent Task 11 release/config/docs review: `APPROVED`; manifest paths
  `22/22`, with zero missing, extra, or SHA-mismatched reviewed files.

Task 11 is complete. Boundary: `local_only`, `production unchanged`, `provider_call=false`,
`actor_run=false`, `external_network_call=false`,
`provider_attempt_made=false`, `live_send=false`; no push/deploy/merge/send.

## 2026-07-10 Natural Cycle and Two-Part DingTalk Acceptance

Required evidence:

- Confirm whether the natural cron cycle executed before calling it a scheduler miss.
- If DingTalk delivery fails with HTTP 200, inspect DingTalk business response body instead of relying on HTTP status.
- Keep each DingTalk markdown payload below the platform's 20,000 byte body limit.
- Validate real live delivery after deploying the split-message fix.

Actual evidence:

- Remote cron is active and enabled. `/etc/cron.d/reddit-voc-site` contains `CRON_TZ=Asia/Shanghai`, `0 7 * * *` collect, and `0 8 * * *` report/send.
- `cron-collect.log` and `cron-report.log` both recorded `daily_collect_20260710_0700` with `provider_call=true` and `return_code=0`.
- Root cause of the missed DingTalk notification was not cron. The prior live-send result was DingTalk business rejection `errcode=460101` / `body 大小不合法`, caused by a markdown JSON body above 20,000 bytes.
- Code now supports at most two DingTalk markdown parts for the business daily report, uses UTF-8 byte budgeting, and stores per-part `body_bytes` plus DingTalk `response_text`.
- Local validation passed:
  - `bash -n scripts/deploy_webapp_tencent.sh scripts/server_daily_collect.sh scripts/server_daily_report.sh scripts/run_daily_report.sh scripts/run_daily_collect.sh`
  - `PYTHONPATH=src:. /Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests/test_daily_report.py -v`
  - `PYTHONPATH=src:. /Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -v` ran 79 tests and passed.
- Production deploy completed and `/api/health` returned `status=ok`.
- Real resend for `daily_collect_20260710_0700` returned `status=sent`, `message_parts=2`, `required_keyword_present=true`, and both DingTalk responses were `{"errcode":0,"errmsg":"ok"}`.
- The two production DingTalk request bodies were 13473 and 14987 bytes, both below 20,000 bytes.
- Public artifacts for `daily_collect_20260710_0700` returned HTTP 200: HTML report, Excel detail, CSV detail, and report screenshot PNG.

## 2026-07-09 Scheduler and Project Initialization Acceptance

Required evidence:

- Root `.gitignore` excludes secrets and runtime artifacts before Git initialization.
- `git init` completes and `git status --short` does not show `ai_video.pem`, `data/`, `outputs/`, `logs/`, or `tmp/` as stageable project files.
- `codex doctor` completes, or any failure is recorded exactly.
- CodeGraph state is checked. If the executable is unavailable, record that `.codegraph/` exists but fresh sync is not verified.
- `/api/settings` returns `collection_time=07:00` and `report_time=08:00`.
- Shell syntax, launchd plist lint, and Python tests pass.
- If production deployment is performed, `/etc/cron.d/reddit-voc-site` contains `0 7 * * *` collect-only and `0 8 * * *` report/DingTalk entries under `CRON_TZ=Asia/Shanghai`.

Actual evidence:

- Git initialized on branch `main`; no commit was created.
- `git status --short --branch --ignored` shows `ai_video.pem`, `data/`, `outputs/`, `logs/`, `tmp/`, and `.codegraph/codegraph.db` as ignored.
- `codex --version` returned `codex-cli 0.142.5`; `codex doctor` and `codex doctor --summary --ascii --no-color` produced no output within 30 seconds and were interrupted, so doctor health is not verified.
- `codex --help` shows no `init` subcommand; Codex project context is maintained through `.codex/context-pack.md` and `.codex/session-thread.md`.
- `.codegraph/` and `.codegraph/codegraph.db` exist; `codegraph --help` returned `command not found`, and no executable was found through local command/path searches, so fresh CodeGraph sync is not verified.
- `bash -n scripts/deploy_webapp_tencent.sh scripts/server_daily_collect.sh scripts/server_daily_report.sh scripts/run_daily_collect.sh scripts/run_daily_report.sh` passed.
- `plutil -lint config/launchd/com.reddit-voc.daily-collect.plist.template config/launchd/com.reddit-voc.daily-report.plist.template` passed.
- Local `/api/settings` payload check returned `collection_time=07:00` and `report_time=08:00`.
- `PYTHONPATH=src:. python3 -m unittest discover -s tests -v` ran 77 tests in 20.218 seconds and passed.
- Production deploy completed without triggering a manual provider collection or DingTalk send.
- Remote `/etc/cron.d/reddit-voc-site` now contains:
  - `0 7 * * * ubuntu /opt/reddit-voc-site/scripts/server_daily_collect.sh >> /opt/reddit-voc-site/logs/cron-collect.log 2>&1`
  - `0 8 * * * ubuntu /opt/reddit-voc-site/scripts/server_daily_report.sh >> /opt/reddit-voc-site/logs/cron-report.log 2>&1`
- Remote cron service reported active; `reddit_voc_site_app` is up on `127.0.0.1:18337`, and `reddit_voc_libretranslate` is healthy.
- Remote `/api/settings` returned `collection_time=07:00`, `collection_window_hours=24`, and `report_time=08:00`.
- Public `https://reddit.brand.lute-tlz-dddd.top/api/health` returned HTTP 200.

## 2026-07-14 Task 23 Local Parser Contract Acceptance

Required evidence:

- RED tests reproduce the exact subredditV3 and terminal-comments contract gaps.
- Only reviewed structures are accepted; negative drift cases remain closed.
- Provider, replay/reindex, CLI and complete-runtime regressions pass.
- Release manifest, deterministic bundle and authorization packet are canonical
  and SHA-bound.
- No SSH, Provider, production write, Git push or DingTalk occurs in local
  acceptance.

Actual evidence:

- Focused RED-to-GREEN passed `7/7`; Provider passed `64/64`; validation passed
  `63/63`; CLI plus hydration-resume passed `67/67`.
- Workspace dependency runtime full suite passed `529/529` with exit code `0`.
- Release manifest SHA:
  `edc6ec9b44871d9a93e9a77ca2fdaf3f91a7ede2e282d48bd3f6d1bdc91e9c51`.
- Deterministic 23-file bundle SHA:
  `de66baf3c76f9a69289feb43045de9c3cf7b3f4ed1dc5dc06f9fc6b89664a01e`.
- Task 23 packet SHA:
  `ab5386e7d2022dd1a354569bd5fa0abfadcd741549902d4cae53b90d8f17daa1`.
- Boundary: `local_only`, `production unchanged`, `provider_call=false`,
  `provider_attempt_made=false`, `live_send=false`, `git_push=false`.

## 2026-07-14 Task 23 Remote Execution Acceptance

Required evidence:

- Exact-match the owner-approved packet, manifest, bundle, probe and Task 21S
  source DB/raw hashes before any persistent remote write.
- Install into fresh SHA-versioned paths and create a fresh staging copy only.
- Pass stable preflight and a network-none contract audit before arming the
  permanent one-shot guard.
- Execute no more than one Provider collect invocation.
- Preserve source/raw/production and prohibit merge, push and DingTalk.
- Do not label partial collection as complete historical coverage.

Actual evidence:

- Local hashes matched; deterministic bundle rebuild reproduced
  `de66baf3...4a01e`; operational contract/scanner checks passed `22/22` and
  `4/4`; latest complete-runtime suite passed `549/549`.
- Remote read-only preflight exact-passed the approved source, `670/670`
  Provider ledger and fresh-target/process/container/storage gates.
- The 23-file bundle and seven-file operational set were atomically installed.
  Fresh staging began at DB SHA `2046e908...e3d9` and raw tree
  `725 / 1012eb...61b0`.
- Host preflight and network-none contract audit passed all 30 lane contracts.
  One permanent-guarded collect invocation advanced Provider `670 -> 702` with
  `32/32` new succeeded attempts.
- Collect result SHA
  `2d1503229d9b50ee03756d494a601d48c79daed9fb748634357f301269016888`
  is `partial/candidate_failures`, not success. Structured rows remained
  `48/1,894/1,942`.
- Fresh postflight SHA
  `6c619e21dffcaffab489845889beaec0a11ecbb8a0edadcd454671ce75d0325e`
  passed `26/26`; source/raw/production stayed unchanged, active process and
  one-shot container counts were zero, and live send was false.
- New staging DB SHA is
  `f53ddf6f7ebac2bd88b05954b0f452cf1ccbacd182c83c79266daefd102ab5cb`;
  raw is `757` files at tree SHA
  `8ffcc30d1b3cd95e7757032b1d19623222b49eb23368f131a721731c0cd5339e`.
- Offline diagnosis confirmed the remaining subreddit structural-mirror and
  nonterminal missing-cursor/failure-isolation gaps. No retry was attempted.

Acceptance decision: `allowed_with_label`. Task 23 is complete only as an
`L3-remote-authorized-staging-partial` execution. Historical coverage is not
complete, Task 14 acceptance remains false, Task 15 remains unauthorized, and
Task 24 requires a separate local-only repair authorization.

## 2026-07-14 Task 24 Local Archive Recovery Acceptance

Required evidence:

- Reproduce the exact 757-corpus parser and failure-spread defects with RED
  tests, retain negative fail-closed cases, and publish no remote side effect.
- Prove offline recovery preserves source DB/raw and Provider ledger and leaves
  no target on failure.
- Preserve old budget-extension behavior while adding a distinct append-only
  ledger for unexhausted-budget continuation.
- Pass complete-runtime regression and produce canonical manifest/bundle and a
  bounded next authorization packet.

Actual evidence:

- Provider/reindex/recovery `102/102`; related modules `179/179`; wrappers
  `26/26`; complete-runtime suite `613/613`, exit code `0`.
- Canonical manifest SHA `dbaf6186...181ad`; deterministic 24-file bundle SHA
  `28eb1847...e034`, reproduced `2/2`.
- Task 25 offline recovery packet SHA `8821d64a...11f5` pins Task 23 DB
  `f53ddf6f...ab5cb`, raw `757 / 8ffcc30d...339e`, Provider `702/1200`, one
  recovery invocation and `network=none`.
- Boundary: `local_only`, `production unchanged`, `provider_call=false`,
  `provider_attempt_made=false`, `live_send=false`, `git_push=false`.

Acceptance decision: `allowed_with_label`. Task 24 is locally verified. Task 25
is a candidate requiring exact owner approval; historical coverage is still
incomplete and no Provider continuation is authorized.

## 2026-07-14 Task 25 Remote Offline Recovery Acceptance

Required evidence:

- Exact-match the approved packet, manifest, bundle, source DB/raw inventory,
  Provider `702/1200`, 252 candidates and nine batches.
- Install only into fresh SHA-versioned paths and run no recovery unless the
  read-only preflight remains stable through final admission.
- Consume at most one permanent-guarded `--network none` recovery invocation.
- Preserve source/raw, Provider ledger, production and live-send state whether
  recovery succeeds or fails.

Actual evidence:

- Preflight SHA `fc14bcb1...12b5` and admission SHA `98735158...a837`
  exact-passed all approved inputs and side-effect boundaries.
- One recovery invocation returned exit `1`,
  `failed/strict_discovery_page_chain_invalid`; result/report SHA
  `10aded9b...ad7e`. No recovered DB was published.
- Failure-state postflight `21/21`, SHA `572e6114...0239`, proved source DB/raw,
  Provider ledger and production DB/container unchanged, with
  `provider_call=false`, `provider_attempt_made=false`, `database_write=false`
  and `live_send=false`.
- Read-only root-cause evidence showed 14/14 sequential schema-drift extra pages
  but 0/14 checkpoint request counts equal final manifest count 702.

Acceptance decision: `failed_closed`. Task 25 is safely closed but did not
produce the required recovered staging database. Its guard is consumed. Task 26
local repair, any second remote recovery and any Provider continuation each
require separate authorization; historical coverage remains incomplete.

## 2026-07-14 Task 26 Local Recovery Contract Acceptance

Required evidence:

- RED tests reproduce multi-lane per-request binding defects and failure-state
  postflight gaps; invalid bindings stay fail-closed.
- Related and complete-runtime regression pass without SSH, remote recovery or
  Provider activity.
- A new canonical manifest, reproducible bundle and separately reviewable
  one-shot packet bind the exact Task 23 source state.

Actual evidence:

- Focused reindex/recovery passed `38/38`; related bundled-runtime regression
  passed `407/407`; complete bundled-runtime suite passed `634/634`.
- Release manifest SHA is
  `d375b127d1e0ac282b5c714f8882e0c8db6a0792cc703273fb50e93ba2b38d17`.
- Deterministic 24-file bundle SHA is
  `a265dc1f1334e71d592d2cc722f946ba2d1b5ed39336ee6d02bde6a1b8dadfed`;
  it reproduced byte-identically twice.
- Task 27 packet SHA is
  `66f666a2183e76194abc4376ae867e3ac2ee54ca8ac1885de048f1af1c01c6b3`.
- Local release review passed `19/19`, SHA
  `9cf3e88e1775d7ff350654f1b8956fda800693635766a3e84b496182f9884cf5`.
- Boundary: `local_only`, `provider_call=false`,
  `provider_attempt_made=false`, `database_write=local-test-only`,
  `production unchanged`, `live_send=false`, `git_push=false`.

Acceptance decision at Task 26 closeout: `local_verified_candidate`. Task 26
was complete within its local authorization; Task 27 then required a separate
exact authorization. Historical coverage was still incomplete at that point.

## 2026-07-14 Task 27 Remote Network-None Recovery Acceptance

Required evidence:

- Exact packet/manifest/bundle and source DB/raw/Provider/candidate/batch
  inputs match before the one-shot guard is armed.
- Execute no more than one `--network none` recovery into a new staging target.
- Run failure-aware postflight and preserve source/raw/Provider/production.

Actual evidence:

- Preflight passed with SHA
  `7e657b94a282f5063d0b4775342d93f09040f0263c8cc3d327cc5717d4f01f8c`;
  admission passed with SHA
  `9e88981ac8cabc7e6152c224ce11bb0d6a8bf696763f466acfbba9356571cca2`.
- One recovery invocation returned `rc=0`,
  `complete/collection_recovery_complete`; result/report SHA
  `465b4aa64185c120421a52cc163d30276264248e16301d3c82aaec76f997de19`.
- Target staging DB SHA is
  `56d749514bd0d9851fbf6f74d44934f56b777990246668cc94ed901e818570a4`.
- Final postflight passed all invariants, SHA
  `95bad68f7bb2f8d4042f87d28ed18c0c95d4346ae16d79d6c56006081565bb93`.
- Target counts are 49 threads, 1902 comments, 1951 analysis results and 259
  candidates. `258` remain pending and `7` batch members are missing.
- Boundary: `network=none`, `provider_call=false`,
  `provider_attempt_made=false`, `database_write=recovery_target_only`,
  `production unchanged`, `live_send=false`, `git_push=false`.

Acceptance decision: `allowed_with_label`. Task 27 recovery is complete and
verified as isolated staging recovery. Historical coverage is incomplete;
Provider continuation requires a new packet and separate authorization.

## 2026-07-14 Task 28 Provider Continuation Candidate Acceptance

Required evidence:

- Freeze the Task 27 target DB and re-read candidate/batch/checkpoint state.
- Bind the pending candidate state, seven missing members, lane ceilings and
  remaining budget into a new packet.
- Do not call Provider or alter remote/production state during packet creation.

Actual evidence:

- Target DB SHA `56d74951...8570a4` rechecked read-only; 258 pending candidates,
  seven missing batch members, nine detail batches and Provider `702/1200`.
- Candidate state SHA `d889fdd9...6c42`; missing-member state SHA
  `d34c9c83...2878`; lane-page-ceiling SHA `f6f2564f...3a8f`.
- Initial Task 28 packet SHA (rejected before Provider):
  `a9fff5d75d1e63cdb2dcecd0dd8ed8a3ef8398831b4f7ddc58a14f1807043c68`.
- Corrected packet SHA:
  `5b0ff5afc5bac1df7907bcd8fd2fa2a3d335918f97471c378d4d405db194cd63`;
  CLI resume packet SHA:
  `031e4d961e757067419fcbcc91ad20dcc65997e46b168fb98731b6c710d5002d`.
- Boundary: `local_only`, `provider_call=false`,
  `provider_attempt_made=false`, `database_write=local-test-only`,
  `production unchanged`, `live_send=false`, `git_push=false`.

Acceptance decision at packet-generation time: `local_verified_candidate`.
The corrected packet was later authorized and executed once. Result is
`partial/candidate_failures` at `969/1200`; target integrity/FK postflight
passed, production remained unchanged, and historical coverage is incomplete.
Any further Provider work requires a new state freeze and authorization.

## 2026-07-14 DeepSeek L2 Semantic-Fix Replacement Acceptance

Authorized scope:

- Exact request ID
  `deepseek-l2-semanticfix-replacement-20260714-175924`, request SHA-256
  `70dba4a85d7b963120bd963baee1b78b9b623c95ec9c6938cbe46acf1d1e8940`.
- Exact candidate release `eec615b6...e29d4`, manifest
  `bec40c15...1e249`, validation manifest `1106ad79...1de` and copied DB
  `b4151728...2d7c`.
- At most `91` additional DeepSeek attempts for exactly one replacement shadow
  report; key read/copy only through the verified isolated no-log path.
- DingTalk/report-alert send, production DB/output/control write, Docker/Colima
  mutation, software installation, L4/L5 activation, deploy, cron/service
  changes, commit, push and merge are prohibited.

Required pre-Provider evidence:

- Latest full suite passes serially on one stable workspace snapshot.
- Release/import verifier, candidate DB preflight, shell/static gates and
  provider-free runtime smoke pass against the exact semantic-fix bytes.
- New shadow/runtime roots begin absent and are created with restrictive modes;
  packet/release/manifest/DB/key metadata and one-use permits exact-match.
- Isolated gates recover to all-off before any permit reservation or key read.

Required terminal evidence:

- Exactly one authorized runner action reaches either `complete` or a preserved
  fail-closed terminal result; request/response/usage/retry/model hashes are
  recorded without secret or source leakage.
- Translation and semantic-validation attempt state is explicit. A translation
  success without semantic-validation success cannot generate or accept a
  report.
- All gates are restored to all-off and no active permit/journal/snapshot,
  process or runtime residue remains outside the explicit evidence allowlist.
- `live_send=false`, `failure_alert_send=false`, `production unchanged` and no
  L4/L5 action are reverified after execution.
- Automatic quality gates either all pass or preserve the exact blocking
  reasons. L3 owner acceptance remains a separate decision on exact hashes.

Actual terminal evidence:

- Exclusive full suite passed `640/640` in `273.525s`, command exit `0`;
  release/import, copied-DB preflight, shell/static gates and provider-free smoke
  passed before Provider.
- The single replacement runner terminalized attempt
  `attempt-20260714T110910709607Z-e02570c9af4a8905` as `blocked/pipeline` with
  reason `protected_entity_changed`; blocked manifest SHA is
  `3c20a6a9f0c2eab5a401f2a68254ac07fe7c7db1ed007fe6cec2add3e90b8ca9`.
- 9/9 translation responses succeeded on `deepseek-v4-flash`, retry count `0`,
  total usage `17,711` tokens. The manifest marked all 54 items pending under one
  local entity-gate reason; later tracing proved this was first-failure
  propagation and not 54 independent failures. Semantic validation did not run
  and no prepared/L3 review artifact exists.
- Copied DB remained `b4151728...c92d7c` with integrity `ok` and zero FK errors;
  both permits are terminal `blocked`, gate journal is `restored`, gates are
  all-off, runtime is cleaned, public/private artifact count is zero,
  `live_send=false`, `production unchanged`, L4/L5 unauthorized.
- Sanitized terminal evidence SHA is `871d3eb5...699945`; cumulative attempt
  usage is `18/100`, leaving `82`.

Acceptance decision: `blocked_requires_new_repair_authorization`. The automatic
quality gate rejected the candidate; L3 cannot be requested from this output.
Do not retry either terminal permit or infer L4/L5/send authority.

## 2026-07-14 DeepSeek L2 Post-Block Local Repair Candidate Acceptance

Accepted local scope:

- Attribute and aggregate deterministic item failures without persisting source
  or candidate `zh`; leave unvalidated rows pending without per-item errors.
- Permit case normalization only for model-pattern matches whose source casing
  is noncanonical; preserve model identity and existing number, exact currency,
  URL and Reddit-reference gates.
- Repair provider-free runtime smoke so child imports cannot add unmanifested
  bytecode to an immutable release.
- Build and validate a new candidate packet only. Provider/key/permit/shadow,
  DingTalk, production, Docker/Colima, deploy, cron/service, commit/push/merge
  actions are outside this local acceptance.

Actual evidence:

- Original RED regressions reproduced model case-only rejection and missing
  attributed item failure evidence. GREEN translation tests passed `23/23`;
  prepared-report tests passed `30/30`.
- A 9-bundle/54-item synthetic shape yields exactly `1 blocked + 53 pending` for
  one deterministic failure. A second test aggregates model and number failures
  across bundles before blocking.
- Runtime-smoke bytecode regression reproduced `release_file_set_mismatch`, then
  passed after child environments pinned `PYTHONDONTWRITEBYTECODE=1`. Four
  generated `.pyc` files were preserved in mode-700 quarantine; final release
  contains zero unmanifested bytecode before and after smoke.
- Release contracts passed `7/7`; the fresh Python 3.12 serialized suite passed
  `652/652` in `221.614s`, exit `0`.
- Final release `861a88d829f4afce2ec3c3f2db99f75e7d59db9a764ae1e1975d38bbe6aa5f54`
  has manifest SHA
  `193035f220ae2ca953f0a5a1402dce62975159629c003d355e1f7f6b8b874174`;
  release/import verification reports 19 modules and
  `repository_fallback=false`.
- Validation manifest SHA is
  `9f8f096130834d7df99f5f6176546ebb1f4ef0128057157ecc36f555d85d0668`.
  Copied DB remains `b4151728...c92d7c`, integrity `ok`, zero FK violations;
  release-only preflight reports 9 visible posts, 9 bundles and 54 items, with
  `deepseek_client_imported=false`.
- Provider-free smoke passed with `translation_provider_attempt_made=false`,
  `live_send=false`, `database_write=local-test-only`; post-smoke release verify
  passed with zero `.pyc`.
- Exact request `deepseek-l2-postblock-repair-20260714-193359` has packet SHA
  `13f576a3fea6b2173f372a167f850bc76fbdc3646cf5973bced8b123a09a80a5`,
  status `ready_for_owner_authorization`, cumulative cap 100, consumed 18 and
  remaining-attempt cap 82. Remaining budget is not authorization.
- New shadow/runtime roots are absent, no new permit exists, key was not read,
  `provider_call=false`, `live_send=false`, `production unchanged`.

Acceptance decision: `local_verified_candidate_ready_for_owner_authorization`.
The exact previous offending entity remains unrecoverable, and the unproven
numeric-surface hypothesis was not relaxed. A real third L2 shadow requires
explicit approval of packet SHA `13f576a3...80a5`; this decision grants no
L3/L4/L5/send authority.

The owner later granted that exact approval and the packet was executed once;
the following section supersedes this candidate-stage decision.

## 2026-07-14 DeepSeek L2 Post-Block Authorized Shadow Acceptance

Authorized scope:

- Exact request `deepseek-l2-postblock-repair-20260714-193359`, packet SHA
  `13f576a3fea6b2173f372a167f850bc76fbdc3646cf5973bced8b123a09a80a5`.
- Exact release `861a88d8...a5f54`, manifest `193035f2...4174`, validation
  `9f8f0961...0668` and copied DB `b4151728...c92d7c`.
- At most 82 additional attempts for one isolated L2 report. DingTalk,
  failure-alert send, production writes, Docker/Colima, deploy, cron/service,
  commit/push/merge and L3/L4/L5 actions remained prohibited.

Actual evidence:

- Pre-Provider freeze exact-matched packet/release/manifest/validation/DB and
  runner hashes. Focused regressions passed `60/60` in `5.687s`; the immutable
  release remains backed by full-suite `652/652`. Release/import, read-only DB
  preflight and provider-free smoke passed with 9 visible posts, 9 bundles, 54
  items, `deepseek_client_imported=false` and zero `.pyc`.
- The exact runner was launched once. Attempt
  `attempt-20260714T121707742472Z-a002e0ab7bc44646` terminalized
  `blocked/pipeline`; 9/9 translation responses succeeded on
  `deepseek-v4-flash`, finish reason `stop`, zero retry and 17,650 tokens.
- Blocked manifest SHA is
  `6f3ecb2b4b812bca8488d12473e057800a333d5d294d7cdc399e01a99c02da4d`.
  It contains 4 blocked items plus 50 pending items with no copied item error.
  Later read-only input diagnosis established that `protected_entity_changed`
  is a generic row-level deterministic reason: all 4 items have number
  categories, while only 2 also have a model category. Attempt-schema and
  recursive sensitive-field checks passed; source and candidate `zh` were not
  retained.
- Semantic validation did not run. Mapping/entity-number gates are blocked;
  the five-true semantic gate was not run, and no prepared report or L3 package
  exists. Cumulative usage is 27/100 attempts, leaving 73.
- Both permits are terminal `blocked`; gate journal is `restored`, gates are
  all-off, runtime-attempt env and runner runtime are absent, copied DB/release
  hashes pass, zero public/private/staging files exist and no Provider process
  remains. `live_send=false`, `failure_alert_send=false`,
  `production unchanged`.
- Sanitized terminal evidence is
  `tmp/translation-quality/deepseek-l2-20260714-150456/postblock-repair-terminal-evidence.json`,
  SHA `106c2904816f654d2d5648246781dc470175b75d65bc071cdd3409b98c8eb784`.

Acceptance decision: `blocked_requires_new_local_contract_repair_authorization`.
This terminal permit/attempt cannot be retried. L3 cannot be requested from
this output, and no L4/L5/send authority can be inferred.

## 2026-07-14 DeepSeek Protected-Placeholder Local Repair Acceptance

Accepted scope: local translation-contract repair, tests, provider-free copied
input proof, immutable release construction and one exact authorization-request
packet. No Provider, key, permit, shadow/runtime, DingTalk, production, Docker,
deploy, cron/service or Git remote action was authorized.

Implementation evidence:

- Every maximal overlapping protected span is replaced before translation with
  a collision-safe, occurrence-specific marker of the form
  `[[RVOC_P_<namespace>_<sequence>]]`. Repeated values receive distinct markers;
  currency/number, URL/number and Reddit-reference/entity overlaps restore from
  one exact source slice.
- Every expected marker must occur exactly once and no unknown same-namespace
  marker may occur. Omission, duplication, alteration or injection blocks as
  `protected_placeholder_changed` before semantic validation.
- Exact source bytes are restored before the unchanged deterministic
  entity/number gate and before semantic validation. The versioned prompt is
  the single prompt source and the changed prompt version invalidates cache.
- RED evidence first showed the success case blocked on
  `protected_entity_changed` and four tamper modes returned the old reason,
  command exit `1`. After the repair the same cases passed; translation-pipeline
  tests are `25/25` and focused translation/prepared/release tests are `62/62`.
- One combined Python 3.12 discovery attempt ran 654 actual tests green but
  reported one loader error because that interpreter lacks pytest for the
  unrelated pytest-only module. The clean split full verification then passed
  40 unittest modules as `654/654`, 0 failures, 0 errors, and the pytest-only
  module separately as `3/3`, both exit `0`. No test was deleted, skipped or
  modified to manufacture green.

Copied-input and release evidence:

- Read-only copied-input proof rebuilt 9 visible posts, 9 bundles and 54 items.
  32 items used 157 markers, maximum 38 per item; protected-value residuals
  after marker removal were zero, namespace collisions were zero, exact byte
  round-trip passed and copied DB SHA remained
  `b415172856a336a1a00ac5118984159a4afab299fb2913d7bace3dcdc8c92d7c`.
- Immutable release SHA is
  `bc51d736f3d07b1c307fa3b6ecc1948be2ef541947be6cd32f08bd13aec340e4`;
  release manifest SHA is
  `e4edef8fd83eda87aeb19c04aee7abffb875f7d0be345cc53fde3787ae939d92`.
  Release/import verification passed for 19 modules with
  `repository_fallback=false`, before and after provider-free smoke, with zero
  unmanifested `.pyc`.
- Provider-free runtime smoke returned
  `translation_provider_call=false`,
  `translation_provider_attempt_made=false`, `report_live_send=false`,
  `live_send=false`, `database_write=local-test-only`. Release-only copied-DB
  preflight passed integrity `ok`, zero FK violations, 9/9/54 alignment,
  required phases `translation,semantic_validation`, exact round-trip and
  `deepseek_client_imported=false`.
- Protected round-trip evidence SHA is
  `2f49e8241482f4a37f9bd1d74b78994d43c3e3cc5b913557e6f682723d855c35`;
  validation manifest SHA is
  `a6be9cc34df7a65a85ed54d2671c6f8fe76b25dd721cc55058a1a87cf38a43f2`.
  Their local artifact directory is mode 700 and files are mode 600.

Authorization boundary:

- Request ID is
  `deepseek-l2-protected-placeholder-repair-20260714-205534`; exact packet SHA
  is `7f76571b67a1178b54827e64d281cdee0e53519f4f8f22fb1711260caeda3002`,
  status `ready_for_owner_authorization`, expiry
  `2026-07-16T23:59:59+08:00`, and additional-attempt cap `73` under cumulative
  cap `100` with `27` consumed.
- Packet bindings to release, release manifest, validation manifest, copied DB,
  evidence, runtime template, runner, wrapper and shim exact-match. The new
  requested shadow/runtime roots are absent, no permit exists, the key was not
  read and no Provider process is active.
- Remaining budget is not authorization. No fourth DeepSeek attempt may start
  until the owner explicitly approves this exact request packet.

Acceptance decision:
`local_verified_candidate_ready_for_owner_authorization`.
`provider_call=false`, `translation_provider_attempt_made=false`,
`live_send=false`, `production unchanged`, `L3_authorized=false`,
`L4_authorized=false`, `L5_authorized=false`.

## 2026-07-14 Approved Packet Pre-Provider Stop and Runtime-Fix Candidate

Owner approval was received for the exact packet
`deepseek-l2-protected-placeholder-repair-20260714-205534` with SHA
`7f76571b67a1178b54827e64d281cdee0e53519f4f8f22fb1711260caeda3002` and cap
73. The runner was invoked exactly once under the approved scope.

Actual result:

- Shadow initialization, copied DB SHA, all-off env, exact permit bindings and
  mode-600 key metadata passed. Key content was copied via stdin/no-log and was
  not emitted.
- The runner stopped before Provider transport during
  `materialize-prepare-env` with `runtime_env_required_value_missing`.
  Attempt identity was `attempt-20260714T131210891567Z-8c39ed09de543958`.
  `translation_provider_attempt_made=false`; no DeepSeek request, response,
  token usage, semantic validation or blocked report manifest exists.
- The packet's runtime template had only gate fields. The runner requires five
  additional non-secret fields: database path, HTTPS artifact base URL, required
  keyword, byte cap and part cap. This is a local packet defect, not a Provider
  quality result.
- Cleanup passed: gate journal is `restored`, both permits are terminal
  `blocked`, the empty runner runtime root was removed, no Provider process
  remains, `live_send=false`, and production is unchanged. Cumulative usage is
  still 27/100; 73 attempts remain.

Replacement local candidate:

- Runtime template adds the five required fields, keeps webhook URL/secret
  blank, uses a non-network `https://files.example/reddit-voc` base URL, and
  binds DB path to the new requested shadow root. Static contract checks passed.
- Runtime template SHA is
  `b1a317c7d69f3d574f19f1bf23ed21536173ac684c8b0f89f7cc48e41afee302`;
  validation manifest SHA is
  `e066dd14fd9a954db063485e8dc355b0e0f67bfa8e188f70e7f1de867654daa2`.
- Replacement request is
  `deepseek-l2-protected-placeholder-runtimefix-20260714-211414`; packet SHA
  is `f1f9b99d696fb60ab76edb5de3b6c783ed1e734bf4f4a47fac4ee7e7f54ce066`,
  status `ready_for_owner_authorization`, cap 73. No replacement root, permit,
  key read or Provider attempt exists.

Acceptance decision:
`preprovider_blocked_requires_new_exact_runtimefix_authorization`.

## 2026-07-14 Runtime-Fix Replacement Terminal Acceptance

Accepted evidence scope: one owner-authorized replacement shadow only. The
owner approved Request ID
`deepseek-l2-protected-placeholder-runtimefix-20260714-211414`, packet SHA
`f1f9b99d696fb60ab76edb5de3b6c783ed1e734bf4f4a47fac4ee7e7f54ce066`, and the
73-attempt cap. Exact preflight, fresh shadow initialization, copied DB,
all-off runtime, permits and mode-600 key metadata were verified.

Actual terminal result:

- The host-native runner was invoked exactly once, exited `1`, and stopped
  before Provider transport with `runtime_env_required_name_missing` followed
  by `prepare_runtime_env_materialize_failed`.
- Attempt ID was
  `attempt-20260714T133104260742Z-d970fb46d50debfe`. The runner proved
  `provider_call=false` and `translation_provider_attempt_made=false`; no
  Provider request/response/tokens, semantic validation, blocked report
  manifest or artifact exists.
- The template contained the five newly added non-secret base values but
  omitted the dynamic names that `materialize-prepare-env` replaces: run,
  attempt and artifact IDs, report roots, provider-attempt root and config
  root. This is a local runtime-template contract defect, not Provider
  quality evidence.
- Both permits are terminal `blocked`, the gate journal is `restored`, gates
  are all-off, the materialized env and empty runner runtime are absent, no
  Provider process remains, source/shadow DB SHA is unchanged at
  `b415172856a336a1a00ac5118984159a4afab299fb2913d7bace3dcdc8c92d7c`, and
  production is unchanged. `live_send=false`, `failure_alert_send=false`.

Acceptance decision:
`preprovider_blocked_requires_new_runtime_template_and_exact_authorization`.
The approved packet and its permits cannot be retried. The remaining 73 is a
cap, not authorization. No L3/L4/L5/send/deploy/cron/service/Git action is
authorized or inferred.

## 2026-07-14 Full Runtime-Template Candidate Acceptance

Accepted scope: local diagnosis, runtime template repair, static parser
round-trip, validation manifest and a new exact authorization packet. No
permit, key, shadow/runtime root, Provider or send action was authorized in
this step.

Evidence:

- The immutable release contract was read-only inspected. It requires five
  non-empty base values and 18 source names for materializer replacement.
- The new all-off mode-600 runtime template contains all 18 names, binds its
  database path to the requested future shadow root, uses a non-network HTTPS
  artifact placeholder, leaves both webhook values blank and keeps all gates
  off. Release parser and replacement round-trip passed.
- New packet:
  `deepseek-l2-protected-placeholder-runtimefix-fields-20260714-225341`;
  packet SHA
  `355d95b17702386de786dc53ed78eb49f276e0c2c9ffd79f1a6c9752c80e5ceb`;
  validation SHA
  `b54b283079d380d83d9e418f71baa66c1c810fd7ec82e4ae598f070fb800240c`;
  runtime SHA
  `8aeb1ae50f2d2a7040630b3957b4d379dc796c5c2382aab8a72591685eaaf0c6`;
  remaining cap 73.
- Release/import verification remains 19 modules with
  `repository_fallback=false`; no unmanifested bytecode remains. No new
  permit, key read, root, Provider call, send or production change exists.

Acceptance decision:
`local_verified_full_runtime_candidate_ready_for_owner_authorization`.
RF11 was subsequently approved and is closed by the L2 result below.

## 2026-07-14 Full-Field Replacement L2 Acceptance

Accepted scope: one exact owner-authorized L2 shadow using the full-field
runtime candidate. No L3/L4/L5, live send, production commit, deployment,
cron/service or Git authority is included.

Evidence:

- Request
  `deepseek-l2-protected-placeholder-runtimefix-fields-20260714-225341`,
  packet SHA
  `355d95b17702386de786dc53ed78eb49f276e0c2c9ffd79f1a6c9752c80e5ceb`,
  cap 73; runner exit `0`; attempt
  `attempt-20260714T152314241954Z-ff5dfb42df4dc5a8`.
- 9 translation + 9 semantic-validation requests, actual model
  `deepseek-v4-flash`, 0 retries, total tokens 45,249. All 54 items accepted;
  entity status `32 accepted / 22 not_applicable`; all five semantic verdicts
  true; zero critical errors.
- Bundle/outbox SHA:
  `e1ce1bd16d8f49157a0258d026ea40d5c5632dfa9e5b66a1ce5535e884f1a68f` /
  `0d0a6d055c88cb1d8e9422990da017caf6dfcea638059faa1b5bd9a96abae338`.
  Eight bundle entries are hash-aligned. Report and alert live sends are false;
  prepare stdout records `current_advanced=false`.
- Both permits are terminal `consumed`, gates are all-off with journal
  `restored`, runtime is absent, DB SHA is unchanged, no Provider process
  remains, and production is unchanged. Sanitized evidence SHA is
  `0befd35b3fe6147a7436c39f9f5897a95863525258ec119c24aac9786f60acc6`.

Acceptance decision:
`l2_automatic_gates_passed_l3_review_pending`.
This does not authorize L3 human acceptance, L4 release, L5 production
prepare, DingTalk delivery or deployment. Cumulative DeepSeek use is now
`45/100`; 55 remain, and consumed permits cannot be reused.

## 2026-07-15 L4 Report-Only Bootstrap Acceptance

Accepted scope: one owner-authorized report-only bootstrap attempt against
`ubuntu@101.34.52.232`. The candidate release/import verification passed for
release `bc51d736f3d07b1c307fa3b6ecc1948be2ef541947be6cd32f08bd13aec340e4`,
manifest `e4edef8fd83eda87aeb19c04aee7abffb875f7d0be345cc53fde3787ae939d92`
and launcher SHA
`1448eafc8aa669b0aab8f870b03a251824d5b43b7f718d2ca5b9ea924aa91d8e`.

Actual result:

- Bootstrap stopped before current/launcher replacement with
  `cron_file_invalid`. The existing `/etc/cron.d/reddit-voc-site` is
  `root:root` mode `0644`; the admin reader requires caller ownership.
- Permit `reddit-voc-l4-bootstrap-20260715-002405` is terminal `blocked`.
  Recovery removed the failed freeze marker and verified no current pointer,
  launcher change, cron change, service restart, report-network creation,
  Provider call or DingTalk send.
- The immutable release remains staged for audit, and all-off report-control
  metadata remains outside the active production pointer.

Acceptance decision:
`l4_bootstrap_blocked_requires_cron_owner_contract_repair`.
The permit cannot be reused. A new release and fresh exact L4 authorization are
required after the narrow root-owned-cron validation repair.

## 2026-07-15 Root-Owned Cron Contract Repair Acceptance

Accepted scope: local source/test repair and immutable release verification only.
No remote action is included.

Evidence:

- Host file ownership remains strict by default. Only fixed cron checks allow
  UID 0, with regular-file, mode and SHA validation preserved.
- Regression and affected suites passed: report ops `30/30`, release/import
  `7/7`, and related report/translation/DeepSeek/DingTalk tests `130/130`.
  Shell syntax and compileall checks passed.
- New candidate release SHA:
  `d6c97382d12bf861663b767b2592ae884c75df08e30bb6767ac4a5c01cf5f61c`;
  manifest SHA:
  `ec21502990fee9a3638d4803e7c7e638f7943b191a3d05b7d87972f0f77a21d5`;
  launcher SHA:
  `1448eafc8aa669b0aab8f870b03a251824d5b43b7f718d2ca5b9ea924aa91d8e`;
  import closure `19` modules, `repository_fallback=false`.

Acceptance decision:
`local_contract_repair_verified_fresh_l4_authorization_pending`.
The release is local-only. The old blocked permit cannot be reused; no remote
transfer, current switch, cron/service change, Provider call or DingTalk send
was performed.

## 2026-07-15 Fresh L4 Bootstrap Acceptance

Accepted scope: one exact fresh L4 bootstrap attempt for release
`d6c97382d12bf861663b767b2592ae884c75df08e30bb6767ac4a5c01cf5f61c`. The
attempt is terminal and cannot be retried.

Evidence:

- Remote release/import verification passed with `19` modules and
  `repository_fallback=false`.
- Bootstrap stopped during report smoke because the launcher passed relative
  `python3` to strict `verify-imports`, yielding
  `release_import_verification_failed` and outer `report_smoke_failed`.
- Recovery restored the legacy launcher and absent current pointer, removed the
  empty report network and freeze marker, and preserved the original cron SHA.
  The site app stayed running with restart count `0`; Provider and DingTalk
  calls were false.

Acceptance decision:
`l4_bootstrap_blocked_requires_absolute_python_verifier_contract_repair`.
The permit is `blocked`. A new launcher fix, new release and fresh exact L4
authorization are required.

## 2026-07-15 Absolute Host Python Verifier Repair Acceptance

Accepted scope: local launcher repair, regression coverage and immutable release
verification only. No remote action is included.

Evidence:

- `server_daily_report.sh` resolves relative host Python command names to an
  absolute executable before `verify-imports`; invalid paths fail closed.
- Targeted control/launcher/release suites passed `45/45`; related
  report/translation/DeepSeek/DingTalk suites passed `122/122`. Shell syntax,
  compileall and import closure (`19`, `repository_fallback=false`) passed.
- New candidate release SHA:
  `463a9e17ee8e181741b0a4fd223cb9ba2e3b7e08bd9eea7032d133390f4ac5f9`;
  manifest SHA:
  `3b023951d9808727f9fbc6b715c040303b2383be6217af51455137104d91850f`;
  launcher SHA:
  `cc0340f50b3e2f9b7ae48679a998e15264c42289ed2a686ee873599aacf1025d`.

Acceptance decision:
`local_absolute_python_repair_verified_fresh_l4_authorization_pending`.
The release is local-only; no new remote, Provider, DingTalk or Git action was
performed.

## 2026-07-15 Admin Smoke Lock Inheritance Repair Acceptance

Accepted scope: local lock-contract repair, regression coverage and immutable
release verification only. No remote action is included.

Evidence:

- The fresh exact L4 bootstrap permit
  `reddit-voc-l4-bootstrap-20260715-011053` reached report smoke and stopped at
  `report_smoke_failed`. The admin process held the report lock while the
  launcher attempted to acquire it again, producing the inner `lock_busy`
  boundary. Direct launcher-only smoke with a held descriptor passed with all
  live/provider flags false.
- Recovery left `current=absent`, the legacy launcher and cron SHA unchanged,
  no report network/freeze, and service restart count `0`; the permit is
  terminal `blocked`.
- The repair passes the held descriptor through `pass_fds` and validates it in
  the launcher only for authorized smoke. Targeted control/launcher/release
  tests passed `46/46`; related report/translation/DeepSeek/DingTalk tests
  passed `122/122`; import closure passed for `19` modules with
  `repository_fallback=false`.
- New local candidate release SHA
  `3594a09e0fce3f311a2708a6e77a1c24937d5919c3f0080b3d2377aab72e8aa4`, manifest
  SHA `227acfd5c44a08477c7ad98ace5a80c1abc5c85c19c4d2ea1f8a8743deedd370`,
  launcher SHA
  `ed32f3708ac1bdec446cdf7fc3d53d5f9931062311958f31777b5da592072424`.

Acceptance decision:
`local_admin_smoke_lock_repair_verified_fresh_l4_authorization_pending`.
The candidate is local-only. No remote transfer, permit installation, current
switch, cron/service change, Provider call, DingTalk send or Git action was
performed.

## 2026-07-17 Reddit VOC Overview and Quarterly Insights Local Acceptance

Accepted scope: local source freeze, independent source validation, same-dist browser
acceptance, isolated container smoke and a fresh production read-only baseline. No
production side effect is included.

Evidence:

- A9 source identity `c7e5eeedf118c1af74564f843e57699d1f3efb925658533b6efe75ccd35df7c8`,
  manifest SHA `41b567ac32b9e8c145921cbd4cc2ac64cce13b628e748509cfdbff571cdf17ac`,
  independent receipt SHA `fcee393f38ca264402dcc519f9e2dc6d280d91c47fdebd72578243c819b0479b`,
  source-stage receipt SHA `650d4c08104bb7b64067ff365dd723cb5c0e158bb2c9754b9b2443bdaffa6e1b`.
- Full frontend verification passed `195 tests / 40 files`; 46 pre-existing conditional
  tests stayed skipped. TypeScript/Vite build passed; lint had zero errors and seven
  pre-existing Fast Refresh warnings.
- Same-dist desktop/mobile E2E passed with receipt SHA
  `5f6b705095186d97df6f53a380d65af92209113c7063970ad94ac259f504bc09`.
  It covers the circular radar, five clickable formulas, three governed windows,
  dual-axis trend, quarterly personas and four insight themes, 26 routes, zero external
  requests, no login and no horizontal overflow.
- Release `9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`
  passed static dist/image audits and isolated local container smoke; release manifest
  SHA is `41f46821f335f198df6375ca6fc3328e6468f1c960e13548c59cfb589015a30e`,
  build receipt SHA `e2c9755d88a90b40588463539288c8e85345de8565fc4fb79314d8f041f0531b`,
  container receipt SHA `8b1f78386047bbe32c7737f5afa891c2e5f228c366093e9b0ef36516a41d3e3a`.
- Fresh L3 read-only baseline kept production at
  `627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4`.
  Promotion packet `7ff1227cc63e03c1102de9bad4371361d3cf00da6739cbec91d5a9c29bcdceb8`
  validated and remains `ready_for_owner_authorization`.

Acceptance decision:
`local_candidate_accepted_ready_for_exact_owner_authorization`.
`production unchanged`, `deploy=false`, `remote_write=false`, `database_write=false`,
`provider_call=false`, `live_send=false`. No permit was generated or consumed.

## 2026-07-27 — CRG-01 Candidate registry local governance acceptance

- `validator_command=PYTHONPATH=src:. python3 scripts/validate_reddit_candidate_registry.py --registry-root output/reddit-voc-candidate-registry`
- `validator_exit=0`
- `validator_status=passed`
- `entry_count=5`
- `event_count=5`
- `commit_count=5`
- `run_count=5`
- `pending_transaction_count=0`
- `blocked_run_count=0`
- `failed_run_count=0`
- `registry_tree_sha256=ef5c38f91801e303b91d085b58d6d80b145d7210c93c69f60764f591dc931e6b`
- `local_registry_governance_complete=true`
- `registry_automation_enabled=false`
- `candidate_created=false`
- `registry_write=false`
- `schedule_change=false`
- `promotion=false`
- `deploy=false`
- `remote_write=false`
- `provider_call=false`
- `database_write=false`
- `live_send=false`
- `production_unchanged=true`

## 2026-08-10 — P2E local candidate acceptance

- `evidence_grade=L3-production-read-only-plus-local-candidate`
- `root_cause=collector_cli_abi_mismatch_raw_artifact_root`
- `aug10_provider_call=false`
- `aug10_database_run_created=false`
- `production_database_integrity=ok`
- `production_foreign_key_violation_count=0`
- `production_data_as_of_utc=2026-08-08T23:00:00Z`
- `collector_preimage_sha256=d5336ae84a405e4bf1f84be9c33bf2f66f07ebf9f264ddd36523b9578561592e`
- `collector_candidate_sha256=71ffb7f050c76fd50db550193a83f16ddee48d1cc2d0b8ab1f1a4c7181222b43`
- `hotfix_package_sha256=8ad103863479b5b19ef4df1b4c29aaf9e9de2156e0d403a4a354bf0b18d022a4`
- `installer_sha256=2dbda95c956884fcbc64da3de0e8fc6994dac119f351af66647abb023020d259`
- `focused_tests=6_passed`
- `full_regression=1944_passed_942_subtests_passed`
- `full_regression_exit_code=0`
- `provider_free_smoke=passed`
- `forced_failure_rollback=passed`
- `source_receipt_runtime=blocked_incomplete`
- `production_code_write=false`
- `provider_call=false`
- `database_write=false`
- `scheduler_change=false`
- `container_restart=false`
- `production_current_switch=false`
- `live_send=false`
- `next_gate=explicit_owner_authorization_for_collector_only_hotfix`

## 2026-08-10 — P2E collector-only production acceptance

- `evidence_grade=L4-authorized-live-code-write`
- `status=installed_no_provider_smoke_passed`
- `target_before_sha256=d5336ae84a405e4bf1f84be9c33bf2f66f07ebf9f264ddd36523b9578561592e`
- `target_after_sha256=71ffb7f050c76fd50db550193a83f16ddee48d1cc2d0b8ab1f1a4c7181222b43`
- `remote_install_receipt_sha256=bca8ea6e550afa90e1b669a5850a77d9b9581586d59bd63c24e80e16e5978c2f`
- `postflight_audit_sha256=db508c5e4ab5242f77eec041a0f1f9821503474b94f850b1ae6a742356991e3a`
- `production_collect_only_runtime=passed`
- `source_receipt_runtime=blocked_incomplete`
- `database_identity_unchanged=true`
- `database_integrity_check=ok`
- `foreign_key_violation_count=0`
- `cron_and_logs_unchanged=true`
- `current_and_freshness_unchanged=true`
- `protected_containers_unchanged=true`
- `provider_call=false`
- `database_write=false`
- `scheduler_change=false`
- `container_restart=false`
- `production_current_switch=false`
- `live_send=false`
- `collection_retry=false`
- `next_gate=separate_explicit_authorization_for_aug10_collection_retry`

## 2026-08-10 — P2E August 10 collection retry acceptance

- `evidence_grade=L4-authorized-live-provider-and-database-write`
- `status=passed`
- `run_id=daily_collect_20260810_0700_retry1`
- `run_status=partial`
- `window_start_utc=2026-08-08T23:00:00Z`
- `window_end_utc=2026-08-09T23:00:00Z`
- `threads=11`
- `comments=43`
- `analysis_results=54`
- `raw_captures=31`
- `raw_artifact_files=31`
- `coverage_full=7`
- `coverage_partial=4`
- `provider_issue_count=0`
- `provider_http_requests_derived=42`
- `database_integrity_check=ok`
- `foreign_key_violation_count=0`
- `secrets_written_count=0`
- `live_delivery_count=0`
- `automatic_retry=false`
- `cron_unchanged=true`
- `protected_containers_unchanged=true`
- `scheduled_failure_evidence_unchanged=true`
- `production_current_switch=false`
- `public_data_as_of_utc=2026-08-08T23:00:00Z`
- `report_retry=false`
- `live_send=false`
- `candidate_build=false`
- `next_gate=source_receipt_and_candidate_build_admission_then_separate_publication`

## 2026-08-10 — P2E G3 local shadow acceptance

- `evidence_grade=L2-local-shadow-on-L3-production-snapshot`
- `status=passed_local_candidate_on_production_snapshot`
- `production_database_schema=already_current_no_migration_required`
- `production_database_sha256=16f9d9493843bf49d40c349a4cc9ab06a2b2a0370151d404fce99b555492c63f`
- `production_snapshot_database_unchanged=true`
- `runtime_payload_count=7`
- `runtime_package_sha256=ae8766a6e43ee38247f5df5b2f01272b70577844fd6ae8dce298af377f341b23`
- `runtime_closure_validation=passed`
- `focused_source_storage_tests=52`
- `gate_failure_injection_tests=7`
- `source_batch_manifest_sha256=f0d92ce642d139f2cda8b4b316cc7db25dbeda35e364b27112345fb499fdaada`
- `source_batch_status=partial`
- `source_batch_consumable=true`
- `raw_objects=31`
- `posts=11`
- `comments=43`
- `issues=0`
- `unresolved_continuations=7`
- `remote_write=false`
- `production_code_write=false`
- `production_database_write=false`
- `provider_call=false`
- `scheduler_change=false`
- `container_restart=false`
- `candidate_build=false`
- `production_current_switch=false`
- `live_send=false`
- `next_gate=p2e_g3_remote_runtime_source_receipt_explicit_authorization_required`

## 2026-08-10 — P2E G3 first production attempt acceptance

- `evidence_grade=L4-authorized-live-failed-closed`
- `status=failed_runtime_smoke`
- `error_code=runtime_smoke_failed`
- `root_cause=installer_imported_nonexistent_symbol`
- `rollback_status=restored`
- `source_receipt_executed=false`
- `production_database_sha256=16f9d9493843bf49d40c349a4cc9ab06a2b2a0370151d404fce99b555492c63f`
- `production_database_write=false`
- `restored_storage_sha256=1c58905c6f31dcec8da7adf7fa2c4805729fc01b0b6dff9ca7aae7619cf9c28f`
- `restored_runner_sha256=0f88f0a5009353b7a3f8d71c57e5bcf3eb9df25a920641cc62c75d04a000014a`
- `create_absent_targets_absent=true`
- `source_batch_absent=true`
- `provider_call=false`
- `live_send=false`
- `scheduler_change=false`
- `container_restart=false`
- `candidate_build=false`
- `production_current_switch=false`
- `automatic_retry=false`
- `production_receipt_sha256=c5f24bb55ffd7869d79cf6ed90fdef41f96ad221a0f01918a9ba52143e573408`
- `corrected_installer_sha256=e29fa81f55a8583f7b1a42092f89c2a7d5e48488f1fd26c9828dd17228adefee`
- `corrected_gate_tests=8_passed`
- `next_gate=p2e_g3_retry1_exact_authorization_required`

## 2026-08-10 — P2E G3 retry1 production acceptance

- `evidence_grade=L4-authorized-live`
- `status=passed_remote_runtime_and_readonly_source_receipt`
- `run_id=daily_collect_20260810_0700_retry1`
- `runtime_payload_count=7`
- `runtime_smoke=passed`
- `container_visible_runtime_smoke=passed`
- `source_receipt_status=passed_remote_readonly_source_receipt`
- `source_batch_manifest_sha256=f0d92ce642d139f2cda8b4b316cc7db25dbeda35e364b27112345fb499fdaada`
- `source_batch_manifest_exact_local_shadow=true`
- `source_batch_status=partial`
- `source_batch_consumable=true`
- `raw_objects=31`
- `posts=11`
- `comments=43`
- `issues=0`
- `unresolved_continuations=7`
- `database_sha256_before=16f9d9493843bf49d40c349a4cc9ab06a2b2a0370151d404fce99b555492c63f`
- `database_sha256_after=16f9d9493843bf49d40c349a4cc9ab06a2b2a0370151d404fce99b555492c63f`
- `database_integrity_check=ok`
- `foreign_key_violation_count=0`
- `cron_unchanged=true`
- `current_pointer_unchanged=true`
- `protected_containers_running_restart_count_zero=true`
- `provider_call=false`
- `production_database_write=false`
- `live_send=false`
- `scheduler_change=false`
- `container_restart=false`
- `candidate_build=false`
- `production_current_switch=false`
- `install_receipt_sha256=c832a5126a6af7fbd5a5dd0cecf203a9ce4c9d2f0cf296f4c8ddb89e75302498`
- `source_receipt_sha256=4e28587ce02438b284c9ad9e353725f91ef4ce0794489eed4b5230a6821ef9fc`
- `next_gate=p2e_g4_candidate_shadow_exact_authorization_required`

## 2026-07-27 — CRA-01 Candidate registry automation enablement acceptance

- `focused_test_command=PYTHONPATH=src:. python3 -m unittest tests.test_run_reddit_candidate_registry_automation -v`
- `focused_test_exit=0`
- `focused_tests_passed=4`
- `launchd_label=com.reddit-voc.candidate-registry`
- `launchd_plist_lint=passed`
- `launchd_bootstrap=passed`
- `launchd_start_interval_seconds=900`
- `launchd_first_run_count=1`
- `launchd_first_exit=0`
- `launchd_first_status=idle`
- `launchd_first_reason_code=no_pending_request`
- `registry_automation_enabled=true`
- `reviewed_request_present=false`
- `candidate_created=false`
- `registry_write=false`
- `registry_tree_sha256=ef5c38f91801e303b91d085b58d6d80b145d7210c93c69f60764f591dc931e6b`
- `schedule_change=authorized_local_launchagent_only`
- `promotion=false`
- `deploy=false`
- `remote_write=false`
- `provider_call=false`
- `database_write=false`
- `live_send=false`
- `production_unchanged=true`

## 2026-07-27 — Task 29 Post-Task-28 review acceptance

- `evidence_grade=L3-remote-read-only-local-review`
- `target_database_sha256=8baa66135aa58e34c83c7b1d7fd3170adf05f7fdeb342363f3cac13459c29f2f`
- `integrity_check=ok`
- `foreign_key_violation_count=0`
- `candidate_status_hydrated=242`
- `candidate_status_failed=12`
- `candidate_status_excluded=5`
- `failed_reason_comments_schema_drift=12`
- `candidate_state_sha256=4f984d81eec82d35b946af60649bb0af3be9a64006e28c7a6b9e9c93a86406ff`
- `failed_candidate_state_sha256=b20c669f7cef65608a0ed5a08451c242a075dc9ed3518ed03669caf290af054d`
- `detail_batch_count=10`
- `missing_batch_member_count=0`
- `provider_request_count=969`
- `provider_attempt_row_count=969`
- `remaining_provider_ceiling=231`
- `state_freeze_sha256=b110e886ccde7da07cb471de88bd75d6de50f9a12153a7b073f68b76a307c7b3`
- `review_packet_sha256=c949d101b1fc02564815961332b67cf705a1397f5b297fdffd49d74af250cae7`
- `review_packet_validation=passed`
- `authorization_status=not_requested`
- `requested_provider_attempt_cap=0`
- `cli_resume_authorization_generated=false`
- `provider_call=false`
- `provider_attempt_made=false`
- `database_write=false`
- `remote_write=false`
- `production_merge=false`
- `live_send=false`
- `git_push=false`
- `production_unchanged=true`

## 2026-08-10 — P2E G4 isolated shadow admission

- `evidence_grade=L2-local-shadow-on-frozen-L3-inputs`
- `status=blocked_translation_delta_required`
- `admitted=false`
- `source_batch_manifest_sha256=f0d92ce642d139f2cda8b4b316cc7db25dbeda35e364b27112345fb499fdaada`
- `source_batch_validation=passed`
- `center_posts=3847`
- `center_stored_comments=28565`
- `center_linked_comments=21612`
- `center_unresolved_parent_comments=6953`
- `center_net_new_posts=11`
- `center_net_new_comments=43`
- `canonical_validation=passed`
- `canonical_unaccounted_identities=0`
- `canonical_unaccounted_foreign_keys=0`
- `voc_facts_validation=passed`
- `governed_signals_validation=passed`
- `metrics_validation=passed_candidate_only_deterministic_full_byte_replay`
- `reports_public_validation=passed_candidate_only`
- `insights_public_validation=passed_candidate_only`
- `daily_period_id=daily:2026-08-10:2026-08-11`
- `daily_pop_yoy_trend_groups=5_5_5`
- `weekly_period_id=weekly:2026-08-03:2026-08-10`
- `weekly_pop_yoy_trend_groups=9_9_9`
- `monthly_period_id=monthly:2026-07-01:2026-08-01`
- `monthly_pop_yoy_trend_groups=10_10_10`
- `comparison_contract_proven=false`
- `comparison_contract_basis=not_owner_attested`
- `comparison_display=provisional_observed_same_profile`
- `translation_expected_fields=29306`
- `translation_reusable_hash_bound_fields=28281`
- `translation_empty_source_fields=961`
- `translation_invalid_existing_fields=0`
- `translation_missing_fields=64`
- `translation_missing_post_titles=11`
- `translation_missing_post_contents=10`
- `translation_missing_comments=43`
- `focused_regression_tests=26_passed`
- `report_comparison_trend_receipt_sha256=e56174e672427bcf6c03b18a71a2c1566f76c9a4e6d4d9c4b31c659298fa897a`
- `translation_reuse_receipt_sha256=b42ae029464be9908e06f71184ac2aa73728e4df54f36699ed3798b708105cd2`
- `g4_admission_receipt_sha256=c434620e85dbf642035524bfb62aaa790f4bd3ee5de26a8ff713e91c38735618`
- `provider_call=false`
- `production_database_write=false`
- `live_send=false`
- `scheduler_change=false`
- `container_restart=false`
- `remote_candidate_write=false`
- `production_current_switch=false`
- `next_gate=p2e_g4t_exact_64_field_translation_delta_then_g4_revalidation`

## 2026-08-10 — 2026-08-11 scheduled DingTalk read-only readiness

- `evidence_grade=L3-production-read-only`
- `status=conditionally_ready_pending_future_collection`
- `cron_timezone=Asia/Shanghai`
- `collect_schedule=0_7_daily`
- `report_schedule=0_8_daily`
- `target_run_id=daily_collect_20260811_0700`
- `bounded_live_policy_status=passed`
- `bounded_live_policy_id=task32aa-daily-live-20260802-20260831`
- `policy_destination_check=true`
- `policy_enable_check=true`
- `policy_keyword_check=true`
- `policy_mode_check=true`
- `script_syntax_checks=passed`
- `external_attempt_made=false`
- `live_send=false`
- `cron_change=false`
- `strict_future_delivery_guarantee=false`
- `remaining_dependency=future_0700_collection_and_external_transports`
- `readiness_receipt_sha256=ddc008b800804f2266778ec3dd9c8a229329c71c922d9293ec7668df7e9c8ca9`

## 2026-08-10 — P2E G4T local pre-admission

- `evidence_grade=L2-local-fixture_plus_frozen_input_preflight`
- `delta_item_count=64`
- `post_title_count=11`
- `post_content_count=10`
- `comment_body_count=43`
- `delta_packet_sha256=5130b4d6c614a9af8465530004a31e75dcea00e2567ddc4f1397dc3098aaa167`
- `delta_source_manifest_sha256=7f3e0f272d57d3a0b94d208cf3403a6f2e4cf9ba8b6fbdf2b2dde3f63c981676`
- `independent_packet_validation=passed`
- `fixture_merge_validation=passed_non_publishable`
- `fixture_translation_reuse_missing=0`
- `fixture_translation_reuse_invalid=0`
- `negative_gate_tests=3_passed`
- `provider_gate_sha256=74d4a36900a9babc2b8399db30bc18e4038874591bb6fd129d41216399c67258`
- `provider_gate_preflight=passed_no_call`
- `provider_max_requests=24`
- `provider_call=false`
- `production_database_write=false`
- `report_send=false`
- `cron_change=false`
- `container_restart=false`
- `remote_candidate_write=false`
- `production_current_switch=false`
- `next_gate=p2e_g4t_exact_provider_authorization_required`

## 2026-08-10 — P2E G4T authorized live-provider result

- `evidence_grade=L4-authorized-live-provider_plus_local-shadow-admission`
- `gate_status=passed`
- `g4t_admitted=true`
- `g4t_status=admitted_local_shadow_candidate`
- `delta_item_count=64`
- `provider_attempts=12`
- `provider_attempt_limit=24`
- `provider_http_200=12`
- `provider_success_batches=10`
- `provider_invalid_json_content=2`
- `provider_quality_failures=0`
- `provider_total_tokens=24598`
- `translation_expected_fields=29306`
- `translation_reusable_hash_bound_fields=28345`
- `translation_empty_source_fields=961`
- `translation_invalid_existing_fields=0`
- `translation_missing_fields=0`
- `translation_complete=true`
- `old_post_rows_unchanged=3836`
- `old_comment_rows_unchanged=21569`
- `merged_post_rows=3847`
- `merged_comment_rows=21612`
- `new_cjk_translations=62`
- `allowed_opaque_source_equal_titles=2`
- `gate_receipt_sha256=6c3f6e704688689d1b3136831cfc5d51aa1fda01ee20e70c9a5769163aeac689`
- `g4t_admission_receipt_sha256=8b26bf929f4e8899e42fe7425f7bdff1a1391b1c8f57e6081d6187425381660b`
- `translation_reuse_audit_sha256=7fc4c404db90b8f45a9b7e5cfe9f353db64ba9b14536dbcda4db0cf0f513925c`
- `production_database_write=false`
- `report_send=false`
- `cron_change=false`
- `container_restart=false`
- `remote_candidate_write=false`
- `production_current_switch=false`
- `next_gate=p2e_g5_local_public_candidate_assembly_and_ui_validation`

## 2026-08-10 — P2E G5 local public-candidate admission

- `evidence_grade=L2-local-candidate-plus-browser-validation`
- `gate_status=passed`
- `g5_admitted=true`
- `g5_status=admitted_local_public_candidate`
- `release_id=reddit_voc_release_20260810_g5_local_candidate_v2`
- `candidate_root=tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g5-local-public-candidate/release-dist-v4`
- `current_release_sha256=0fff0406ac280c041189dd9a335aa1c55ef8ea111809c87977fe21cca8f15046`
- `ui_index_sha256=10f8f6c54ca1afa7a2371b27b493b2ec3aee47b12c00e0601cc074d6c2485eac`
- `dataset_count=7`
- `declared_file_count=72`
- `data_as_of_utc=2026-08-09T23:00:00Z`
- `translation_expected_fields=29306`
- `translation_missing_fields=0`
- `translation_invalid_fields=0`
- `daily_pop_yoy_trend=5_5_5`
- `weekly_pop_yoy_trend=9_9_9`
- `monthly_pop_yoy_trend=10_10_10`
- `desktop_routes=15_passed`
- `mobile_routes=15_passed_no_horizontal_overflow`
- `post_detail_chinese_translation=true`
- `frontend_tests=229_passed_46_skipped`
- `targeted_insights_tests=12_passed_1_skipped`
- `python_insights_audit_tests=22_passed`
- `frontend_lint=passed_0_errors_15_warnings`
- `comparison_contract_proven=false`
- `comparison_values_observed_provisional=true`
- `translated_base_promotable=false`
- `g5_admission_receipt_sha256=50d09c1742eb53964823089ed1615b50726e5c95172e48bbc5ef0dc885b68dc7`
- `production_database_write=false`
- `report_send=false`
- `cron_change=false`
- `container_restart=false`
- `remote_candidate_write=false`
- `production_current_switch=false`
- `next_gate=p2e_g6_production_candidate_freeze_and_promotion_readiness_exact_authorization_required`

## 2026-08-11 — P2E G6 production-candidate freeze and readiness audit

- `evidence_grade=L3-production-read-only-plus-L2-local-deploy-package`
- `gate_status=artifact_ready_public_promotion_blocked_freshness`
- `decision=conditional_no_go`
- `artifact_integrity_admitted=true`
- `public_promotion_admitted=false`
- `production_preimage_double_observation_identical=true`
- `production_preimage_receipt_sha256=ee6354026459631d2d17b6ed6fdae652642ad32753311986173f466fb0741422`
- `g6_candidate_freeze_sha256=10125d1d82459c12d5b003e77ffd4dd8a654e8c458bae2aeb7ab8afe0aced62a`
- `release_sha256=be87ce04603d20e15db37aa88c41f84b0f09e1dc5718fb472f6dddb19643c6b6`
- `release_manifest_sha256=e7fe825d9bf65af6ba650bbae56b5f60e378f1fd09aaf6a154c9371fd5aac1fa`
- `image_archive_sha256=d171ce4eff6eee35dbf1f4ee80eb4bd6df29068739cb0e105da7553caa03155a`
- `release_archive_sha256=41a03fffb3f64afc12a8cef744ce2009aad2c229d740ea1f97578db8d8296f9a`
- `data_archive_sha256=b88e969ad95be6dd5efdb15840a4f3e1f114ccaa16b5434e0bb248282cf706c7`
- `deploy_package_audit_sha256=6c035947aea5dc8187390e75c530ac1a0b90d670d277e8501c3b8e9211c799ce`
- `g6_admission_sha256=80406d3e8f81cc73dec131d07a9ed3edbfe98af9c55690e396668bca8698bbeb`
- `insights_dist_audit_tests=23_passed`
- `site_archive_projection_exact=true`
- `data_archive_projection_exact=true`
- `image_static_overlay_projection_exact=true`
- `image_platform=linux_amd64`
- `daily_pop_yoy_trend=5_5_5`
- `weekly_pop_yoy_trend=9_9_9`
- `monthly_pop_yoy_trend=10_10_10`
- `post_detail_chinese_translation_complete=true`
- `translation_required_ui_label_exact=true`
- `translation_independent_human_review=false`
- `candidate_source_batch_id=daily_collect_20260810_0700_retry1`
- `newer_available_source_batch_id=daily_collect_20260811_0700`
- `newer_source_integrated=false`
- `local_docker_accessed=false`
- `production_deploy=false`
- `public_current_switch=false`
- `report_send=false`
- `production_database_write=false`
- `cron_change=false`
- `container_restart=false`
- `remote_candidate_write=false`
- `production_unchanged=true`
- `next_gate=p2e_g6f_20260811_fresh_candidate_forward_port_exact_authorization_required`

## 2026-08-11 — P2E G6F fresh-candidate forward port and report translation incident

- `evidence_grade=L3-production-read-only-plus-L2-local-candidate-and-code-fix`
- `gate_status=blocked_translation_delta_and_report_runtime_gate_required`
- `g6f_admitted=false`
- `source_batch_id=daily_collect_20260811_0700`
- `source_batch_manifest_sha256=45d037bad30e8a3ba85a0c86a2b9e0076786cdb1e0fbe9318fa785b5181d7a52`
- `source_batch_status=partial`
- `net_new_posts=12`
- `net_new_comments=36`
- `canonical_posts=3859`
- `canonical_stored_comments=28601`
- `canonical_linked_comments=21648`
- `canonical_unresolved_parent_comments=6953`
- `daily_period=daily:2026-08-11:2026-08-12`
- `daily_pop_yoy_trend=5_5_5`
- `weekly_pop_yoy_trend=9_9_9`
- `monthly_pop_yoy_trend=10_10_10`
- `translation_reusable_fields=28345`
- `translation_empty_fields=962`
- `translation_invalid_fields=0`
- `translation_missing_fields=59`
- `translation_delta_titles=12`
- `translation_delta_post_bodies=11`
- `translation_delta_comment_bodies=36`
- `g6ft_delta_packet_sha256=a7a2711ce7a3b427e25b67661de22030f3d1b787b932a2621b1a640c6dcfdd8d`
- `production_report_translation_status=provider_missing_config`
- `production_report_root_cause=deepseek_secret_not_propagated_into_legacy_report_container`
- `local_deepseek_incomplete_send_fail_closed=true`
- `local_post_title_translation=true`
- `daily_report_tests=20_passed`
- `production_report_fix_applied=false`
- `report_resend=false`
- `provider_call=false`
- `production_deploy=false`
- `production_code_write=false`
- `production_database_write=false`
- `cron_change=false`
- `container_restart=false`
- `remote_candidate_write=false`
- `production_current_switch=false`
- `production_unchanged=true`
- `g6f_admission_sha256=b58c6a9de827c7d0efdf9e31febbddd0d176cebcdb556dddf6d4b57839b7d4a3`
- `next_gate_1=p2e_g6ft_59_field_deepseek_translation_delta_exact_authorization_required`
- `next_gate_2=p2e_g6r_prepared_report_runtime_closure_exact_authorization_required`
