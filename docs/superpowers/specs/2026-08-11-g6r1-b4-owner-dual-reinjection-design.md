# G6R1-B4 owner dual-credential reinjection design

## Authorized boundary

This gate may atomically replace only
`/home/ubuntu/.reddit-voc/secrets/reddit-voc-report.env` and create only the
two v2 dual-destination authority receipts. It may read the existing live and
report credential files in memory. It must not send DingTalk traffic, call a
Provider, access the production database, alter cron/current, or invoke Docker.

The primary pair comes from the current production `reddit-voc-live.env`.
The secondary URL is recovered locally from the exact 2102-byte retired sender
whose SHA-256 is
`9a4f697933077917883e364edc8d91f6c4e1b115cf08ffdf10ed05fa90c9a1bc`.
No webhook value, length, hash, fingerprint, or token is emitted. The retired
sender used an unsigned URL, so the v2 secondary signing-secret key is present
with an empty value, which the frozen runtime treats as optional.

The persistent report environment follows the frozen B3 runtime contract
instead of copying absent legacy values: the database path is fixed, dynamic
attempt roots are empty placeholders materialized under the shared lock, and
the DingTalk limits are exactly 18000 bytes / 2 parts. Only the artifact base
URL, required keyword, and primary credential pair are inherited from the
protected live environment.

## Transaction

1. Revalidate the fail-closed schedule, shared lock, current links, exact
   secret-file identities, and absence of both v2 receipts.
2. Acquire the shared daily-report flock.
3. Parse the live env without shell evaluation and validate the primary URL.
4. Accept one secondary URL through stdin, validate it, and require it to be
   distinct from primary.
5. Build an exact report env from the approved runtime keys, all gates off,
   v2 destination identities, and both webhook pairs.
6. Use `renameat2(RENAME_EXCHANGE)` so the old report env remains available at
   a mode-0600 swap name until commit.
7. Create the canonical dual report-env receipt and then the chained dual
   credential-set receipt; the latter is the commit marker.
8. Remove the displaced old env only after the commit marker is durable.
9. Read back exact env identity, receipt chain, fail-closed schedule, and both
   protected current links before returning a redacted L4 receipt.

Any ordinary pre-commit failure removes partial authority and exchanges the
old report env back. A valid credential-set receipt is the durable commit
marker and is never rolled back. No persistent transaction journal or secret
backup is created; the only intermediate writes are mode-0600/0444 sibling
files needed for atomic exchange/install, and they are removed before return.

## Acceptance

- Missing, duplicate, malformed, or identical destinations block before the
  report env is switched.
- Failure after env exchange or after the first receipt restores the exact old
  report-env bytes and leaves both receipts absent.
- Success leaves one exact v2 report env and two canonical root-owned receipt
  files while cron/current and all forbidden-effect counters remain unchanged.
- A second execution is verify-only and cannot rewrite the committed env.
