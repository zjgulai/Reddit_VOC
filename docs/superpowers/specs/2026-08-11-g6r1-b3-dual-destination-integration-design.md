# G6R1-B3 dual-destination authority and runtime integration design

## Decision and evidence boundary

The approved approach is a versioned dual-destination contract layered beside
the existing single-destination v1 path. This gate may build and test a local
candidate and may later perform production L3 metadata-only observation. It
must not write production secrets, databases, cron, release pointers, or
containers, and it must not call a Provider or send a DingTalk request.

Local tests support only an L2 candidate claim. Production metadata observation
supports only an L3 read-only compatibility claim. Neither grade proves live
activation or delivery.

## Alternatives considered

1. **Versioned dual-destination contract (selected).** One prepared outbox, one
   scheduled cycle, one container, and an exact ordered destination plan. Each
   destination retains its own lock, ledger, database channel, and terminal
   delivery state.
2. **Two single-destination invocations.** Rejected because it duplicates the
   runtime boundary, weakens aggregate-state evidence, and adds crash windows.
3. **External fanout relay.** Rejected because it adds a new external service,
   credential boundary, and single point of failure.

## Authority documents

The implementation adds strict canonical v2 documents while preserving v1:

- `reddit-voc-g6r1-dual-report-env-install-receipt-v1`;
- `reddit-voc-g6r1-dual-credential-set-receipt-v1`;
- `reddit-voc-g6r1-scheduled-cycle-policy-v2`;
- `report-scheduled-cycle-policy-permit-v2`;
- `report-scheduled-cycle-send-permit-v2`.

Every dual document binds a non-secret `destination_set_id`, an ordered exact
destination list `primary`, `secondary`, their approved aliases, and a
`credential_set_epoch_id`. It never records webhook bytes, fingerprints,
lengths, query values, or signing-secret derivatives.

The send permit also binds the frozen report tuple, release and launcher SHA,
the commit receipt, the schedule lease, expiry, and one exact delivery action
per destination. Initial scheduled delivery authorizes both destinations.
Manual recovery must use a later destination-scoped resend permit; an automatic
scheduled cycle cannot derive such a resend.

## Secret materialization

The owner-managed report environment remains a single mode-0600 regular file.
The dual install receipt binds only its device, inode, owner, group, mode, path,
credential epoch, and destination set. The materializer opens the file once
with no-follow and inode checks, requires both exact key pairs, and checks only
that the two canonical DingTalk URLs are non-empty and distinct.

The attempt-scoped runtime environment contains both pairs and the non-secret
destination-set identity. It is never printed, hashed into a public receipt, or
passed in argv. The single-destination materializer continues to reject a
secondary credential.

## Scheduled runtime flow

1. Reserve one scheduled slot and prepare one report.
2. Host-commit the immutable prepared bundle and outbox.
3. Derive one v2 send permit bound to the ordered dual plan.
4. Revalidate the send window and exact authority at materialization time.
5. Create only the run-scoped delivery root as writable.
6. Launch one send-only container and call `send-dual`.
7. Verify the multi-destination summary and terminalize the permit with an
   aggregate state that cannot erase per-destination evidence.

Public/private prepared artifacts and the wider state tree remain read-only.
The writable delivery root is
`state/delivery/<run_id>/destinations/<destination_id>` and each destination
keeps its own lock and hash-chain ledger.

## Delivery and recovery semantics

- `sent`: matching sent evidence exists; never retry that destination.
- `unknown`: an external request may have happened; never auto-retry.
- `rejected`: a future explicit destination-scoped resend permit is required.
- `partially_sent`: at least one destination is sent and another is rejected or
  locally blocked.
- `partial_unknown_delivery_state`: at least one destination is sent and
  another is unknown.
- database projection failure after a sent ledger event is non-retryable.

The outer permit may become `consumed`, `partial`, `unknown`, `blocked`, or
`closed_no_attempt`. Its terminal record binds the aggregate status and both
destination ledger tips, but the destination ledgers remain the source of
truth for retry safety.

## L3 production preimage

Only after the local candidate is green, a separately frozen read-only observer
may report:

- launcher, release, report-control, cron, and report-env metadata identities;
- report-env regular/no-symlink, owner, group, and mode checks;
- booleans for exact required-key presence and distinct non-empty URLs;
- current authority schema names and destination count;
- database table/column compatibility using read-only access if available.

The observer must not output values, lengths, hashes, fingerprints, or any
credential-derived material. It performs no Docker command and no mutation.

## Acceptance tests

1. v1 canonical documents remain byte-for-byte valid.
2. v2 builders and validators reject reordered, missing, duplicated, or extra
   destinations and any unrecognized field.
3. the owner receipt, policy, owner permit, activation marker, send permit, and
   attempt environment agree on the exact destination set and credential epoch.
4. partial or duplicate credentials block before any transport or ledger write.
5. the scheduled launcher routes v2 only to `send-dual` and v1 only to `send`.
6. the container receives one shared read-only prepared outbox and one
   run-scoped writable delivery root.
7. sent, rejected, unknown, crash-after-primary, and concurrent cases preserve
   per-destination idempotency.
8. the launcher parses the dual summary and terminalizes without claiming both
   destinations sent when only one is sent.
9. the content-addressed release verifies its exact file set and import closure
   without repository fallback or generated bytecode.
10. all tests use fake transports and temporary databases; external effects are
    zero.

## Execution TODO

1. Add canonical destination-set helpers and v2 receipt/policy/permit schemas.
2. Extend authority loading and activation validation for v2 without weakening
   v1.
3. Add v2 scheduled send derivation and destination-plan binding.
4. Add dual secret materialization and exact runtime-env validation.
5. Route the scheduled launcher to `send-dual`, mount the correct delivery
   root, and parse multi-destination results.
6. Add `partial` terminal handling and destination evidence bindings.
7. Add cross-component, hostile-input, crash, and compatibility tests.
8. Build and verify a self-contained local release and admission receipt.
9. Freeze a metadata-only L3 observer and execute it only within the approved
   read-only boundary.
10. Report facts, inferences, uncertainties, and the next separately authorized
    production-write gate.
