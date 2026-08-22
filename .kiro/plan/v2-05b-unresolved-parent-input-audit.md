---
title: V2-05B Unresolved-parent Input Audit
doc_type: execution_evidence
status: blocked_missing_real_parent_post_evidence
date: 2026-07-27
production_boundary: unchanged
provider_call: false
database_write: false
remote_write: false
live_send: false
deployment: false
---

# V2-05B Unresolved-parent Input Audit

## Objective

Determine whether current governed local data contains real parent-post facts
that can move any of the formal V3 baseline's unresolved comments to `linked`.
Do not infer or fabricate a parent relationship.

## Bound inputs

Formal V3 baseline:

```text
root=tmp/reddit-voc-v3/reddit_add_data_20260715_v1/canonical-candidate-a1
manifest_sha256=36bbc15074437ab0b48732200a50a3356091391175e565f4e9769122ece2c1ce
posts_rows=3494
posts_sha256=73fa5d1f5b85018290817b0aa870bba46179b22d08db39be747389427e45eeb2
unresolved_rows=6943
unresolved_sha256=a171a76a0f4aff74ee4da383695c9b09833f20d5d2cc35b868892f61873395a6
```

Latest local daily canonical:

```text
root=tmp/reddit-voc-daily-ingest-20260723/v3/canonical
manifest_sha256=486a39cccf924ba4815c6fcb88284ae2756f0db34bf367d087bb0a87e301e4af
posts_rows=3591
posts_sha256=81dbddb5089dab9227fecf1515be826db6671bf664353593312178bedf3ee3c8
unresolved_rows=6953
unresolved_sha256=c79ea7c5b11d7c0a33ead6ba8c46d05f0c895e5d206ad65a8682ea664faf47fb
```

All four file bindings matched manifest-declared SHA-256 and row counts.

## Set reconciliation

```text
formal_unique_unresolved_parents=3859
latest_unique_unresolved_parents=3862
formal_parent_ids_present_as_latest_posts=0
formal_unresolved_comments_still_unresolved=6943
formal_unresolved_comments_removed_from_latest_ledger=0
new_latest_unresolved_comments=10
new_latest_unresolved_parent_ids=3

formal_parent_set_sha256=098991980ed0eb46d49a27d08ed0fd87b0af9e092633cc5839e9d93eebfae17b
latest_post_set_sha256=65f65079fa55124bc8c2cc075dba65877a3b897586ee808975491bfef0348430
relinkable_parent_intersection_sha256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

The intersection hash is the SHA-256 of empty input. No existing unresolved
parent is represented by a governed post in the latest local canonical.

## Decision

`V2-05B` remains incomplete and is blocked on real parent-post evidence.
V3CT has already validated the deterministic transition and ledger cleanup
when such evidence exists; running the builder now would produce no valid
relinks.

The next admissible input must provide:

1. Canonical Reddit post identity for one or more missing parent IDs.
2. Source bytes and SHA-256 binding.
3. Provenance and source eligibility.
4. Importer and independent-validator acceptance.
5. Canonical fusion conservation with linked/unresolved ledgers remaining
   mutually exclusive.

## Boundary

This audit used local read-only artifacts. It did not call a Provider, write a
database, fabricate a parent relationship, build a candidate release, perform
a remote write, deploy, send a message, or change production.
