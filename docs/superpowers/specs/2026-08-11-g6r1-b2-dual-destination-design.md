# G6R1-B2 dual DingTalk destination design

## Scope and evidence boundary

This candidate adds deterministic two-destination delivery for one immutable
prepared report. It is local-only evidence. Tests must use fake transports and
temporary databases. The gate forbids Provider calls, production secret access
or writes, DingTalk HTTP requests, cron/current changes, SSH, Docker, and
production database writes.

## Selected architecture

One prepared outbox is verified once. Source-state equality and public-artifact
HEAD checks also run once before credentials are loaded. The sender then fans
out in a fixed `primary`, `secondary` order.

Each destination owns:

- a stable non-secret destination id;
- an independent append-only hash-chain ledger;
- an independent process lock held across duplicate evaluation, transport, the
  terminal ledger event, and its database projection;
- database delivery identities and channel values that include the destination
  id.

The outbox bytes, bundle hash, artifact version, authorization, and artifact
URLs are shared. Credentials are never copied into ledgers, database rows,
summaries, logs, or receipts.

## Credential contract

The prepared-report credential file must contain both exact pairs:

- `DINGTALK_WEBHOOK_URL` and `DINGTALK_WEBHOOK_SECRET`;
- `DINGTALK_WEBHOOK_URL_2` and `DINGTALK_WEBHOOK_SECRET_2`.

URLs must be non-empty, distinct, canonical DingTalk robot URLs. A signing
secret may be empty, but the key must be present. Environment values are never
accepted as a fallback. File owner, mode, no-symlink, single-open-fd, duplicate
key, size, UTF-8, and control-character checks remain fail-closed.

## Ledger and idempotency

Report ledgers use:

`state/delivery/<run_id>/destinations/<destination_id>/ledger.jsonl`

New destination events use `delivery-event-v2` and bind `destination_id` in
every hash-chained event. Legacy failure-alert ledgers remain `delivery-event-v1`
at their existing path and are not changed by this candidate.

Before delivery, a per-destination lock serializes duplicate evaluation and the
whole external-attempt boundary. A sent or unknown destination is never
automatically retried. Rejected parts require the existing explicit resend
authorization. A clean destination with no history may still proceed when the
other destination is already sent.

## Database projection

Each successful destination/part inserts one `delivery_previews` row. Its
identity includes `destination_id`, and `channel` is
`dingtalk:<destination_id>`. Duplicate checks only load the selected
destination's rows. A ledger `sent` event followed by a database projection
failure remains non-retryable and is reported explicitly.

## Aggregate states

- `sent`: both destinations are sent or already have matching sent evidence.
- `partially_sent`: at least one destination is sent and another is rejected or
  locally blocked.
- `partial_unknown_delivery_state`: at least one destination is sent and another
  is unknown.
- `unknown_delivery_state`: no destination is confirmed sent and at least one is
  unknown.
- `rejected`: all attempted destinations are rejected.
- `blocked`: no destination is sent and a pre-request or contract gate blocks
  progress.

The summary includes only destination ids, part indexes, status, ledger tips,
and live-attempt booleans. It never includes credential material or credential
derivatives.

## Failure and concurrency rules

- Credential loading happens after all shared no-secret preflights.
- A failure for one destination does not erase evidence for the other.
- Unknown state is terminal and blocks automatic retry only for that
  destination.
- Concurrent processes cannot create a second attempt for the same destination.
- The frozen outbox is never rebuilt between destinations.
- No secondary legacy cron or forwarding script is reintroduced.

## Test acceptance

The local candidate must prove with fake transports and temporary files:

1. both destinations receive byte-identical frozen outbox parts;
2. each destination gets a distinct v2 hash-chain and database identity;
3. sent plus rejected aggregates to `partially_sent`;
4. sent plus unknown aggregates to `partial_unknown_delivery_state`;
5. rerun after primary sent sends only a clean secondary;
6. rejected resend is destination-safe and requires explicit authorization;
7. concurrent invocations attempt each destination at most once;
8. malformed, duplicate, missing, identical, symlinked, or wrong-mode
   credentials block before transport;
9. legacy single-destination and failure-alert tests remain green;
10. no real network, Provider, production database, Docker, SSH, cron, or
    current operation occurs.

## Explicit non-goals

This gate does not install production credentials, activate a release, enable a
schedule, send a DingTalk message, prove the unchanged historical webhook is
safe, or claim production readiness. Production integration requires a later
permit/schema/launcher gate that binds both destination ids and a separately
authorized secret installation transaction.
