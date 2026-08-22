# Candidate Registry Automation Inbox

The local scheduler processes at most one canonical JSON request per cycle.
Requests belong in `tmp/reddit-voc-candidate-automation/inbox/<request_id>.json`.
A request is eligible only when its reviewed profile is beneath
`config/candidate-automation/profiles/` and its exact SHA-256 is pinned.

The scheduler stops at the append-only local candidate registry. It cannot
promote, deploy, call providers, write a database, write remotely, or send
live messages. No candidate is created when the inbox is empty.

Request schema:

```json
{
  "boundaries": {
    "candidate_only": true,
    "database_write": false,
    "deploy": false,
    "live_send": false,
    "production_unchanged": true,
    "promotion": false,
    "provider_call": false,
    "remote_write": false,
    "schedule_change": false
  },
  "observed_at_utc": "2026-07-27T12:00:00Z",
  "profile_path": "config/candidate-automation/profiles/reviewed-profile.json",
  "profile_sha256": "<64 lowercase hex>",
  "request_id": "incremental-20260727-001",
  "schema_version": "reddit_voc_candidate_registry_automation_request_v1",
  "source_cutoff_utc": "capture-complete"
}
```
