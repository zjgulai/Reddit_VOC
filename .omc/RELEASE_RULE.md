# Release Rules
<!-- last-analyzed: 2026-07-15T13:06:23Z -->

## Version Sources

- Production release identity is not SemVer. It is the deterministic
  `release_sha256` emitted by
  `ref/UI/momcozy-reddit-workbench/deploy/insights/build-release.mjs` and bound
  by a `reddit_voc_insights_site_release_v2` manifest.
- `pyproject.toml` field `project.version = "0.1.0"` and
  `ref/UI/momcozy-reddit-workbench/package.json` field `version = "0.0.0"` are
  development package metadata. Do not bump them for a Reddit VOC site
  candidate.
- Release builders are `scripts/build_insights_release.sh` and
  `ref/UI/momcozy-reddit-workbench/deploy/insights/build-release.mjs`.

## Release Trigger

- No tag, merge, branch, or CI trigger exists.
- A local candidate is built only by an explicit Plan C invocation over the
  exact Plan A data receipt and Plan B source manifest/receipt.
- A production promotion requires separate owner authorization naming the full
  promotion packet SHA-256 and release SHA-256. Building a packet is not an
  authorization or a deploy.

## Test Gate

- Python related/full tests: project `unittest` commands selected by the Plan C
  orchestrator; no new baseline failure may be introduced.
- Frontend gates in `ref/UI/momcozy-reddit-workbench`: `npm test`,
  `npm run lint`, `npx tsc -b --pretty false`, and the isolated Vite build
  performed by `scripts/build_insights_release.sh`.
- Final candidate gates: dist audit, 13 routes at desktop/mobile from the same
  dist, actual CSV/PDF/PPTX/DOCX downloads and structure validation,
  linux/amd64 image contract, isolated read-only UID-101 container smoke, and
  private-path 404 checks.
- There is no CI job and no bypass flag. Any failed gate blocks the promotable
  registry entry.

## Registry / Distribution

- No npm, PyPI, Cargo, GitHub Packages, or public Docker registry publish is
  configured.
- Distribution artifacts are an immutable local linux/amd64 Docker image tar,
  release directory, and content-addressed TGZ produced below `tmp/`.
- Candidate records are append-only under
  `output/reddit-voc-candidate-registry/`; failed or blocked runs are not
  promotable entries.
- Upload, remote `docker load`, candidate port 18339, or production-current
  switching require a later exact authorization and are outside local Plan C.

## Release Notes Strategy

- No `CHANGELOG` or release-note convention exists.
- Use the immutable candidate receipt, registry entry, promotion packet, and
  project progress/acceptance documents as the audit trail. Lead with user
  visible data/UI changes, then coverage debt and exact side-effect boundaries.

## CI Workflow Files

- None found in `.github/workflows/`, `.circleci/`, or other supported CI
  locations.

## First-Time Setup Gaps

- No CI release workflow and no git tags exist. This is intentional for the
  current controlled, content-addressed production lane; do not scaffold or
  push either without separate owner direction.
- Root `.gitignore` excludes `tmp/`, `*.tar`, and `*.tgz`; the frontend
  `.gitignore` excludes `dist`.
- The repository currently has no commits. Plan C does not authorize stage,
  commit, tag, push, registry publish, or GitHub release creation.
