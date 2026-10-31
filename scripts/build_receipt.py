#!/usr/bin/env python3
"""Per-dataset build stamps and a per-run build receipt.

Why this exists
---------------
The site publishes seven datasets and a pointer that names them. Between "the
pipeline ran" and "the bytes a browser receives are the bytes this run wrote"
there was no evidence at all: on 2026-10-31 `data/reddit-voc` became a dangling
symlink and every `/data/` request 404'd while a plain `curl` of `/` returned
200 from the SPA fallback. Nothing in the tree contradicted that.

A build stamp is the missing link. It sits next to each dataset's manifest and
records which run produced it and what the manifest bytes hashed to, so a
monitor can ask each dataset to prove itself instead of trusting one pointer:

    pointer binding.public_manifest_sha256
        == sha256(<dataset>/manifest.json bytes)
        == <dataset>/build.json manifest_sha256

Three values that must agree, from three different places. One of them being
wrong is now detectable without reading the pipeline's own logs.

Design rules:
  * `write_build_receipt` is create-new and immutable. A run id names one run;
    rewriting it with different bytes would erase the evidence of whatever the
    first write recorded. A conflicting rewrite raises instead.
  * Stamps are ordinary atomic writes (tmp + fsync + os.replace) because they
    live inside a generation and are replaced on every run.
  * Frozen datasets (personas, insights) are built out of band, so their stamp
    may carry `generated_at_utc: null` — but then it MUST say why, or a reader
    cannot tell "unknown" from "forgot to record".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

STAMP_SCHEMA = "echo_agent_dataset_build_stamp_v1"
RECEIPT_SCHEMA = "echo_agent_build_receipt_v1"

# Same shape the frontend accepts for `collector_run_id` (release.ts). A run id
# ends up in a filename and in a URL-visible JSON field, so it is restricted
# rather than merely "not empty".
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")

BUILD_BASES = frozenset({"pipeline", "external_manual_build"})

# Produced by the daily pipeline. Everything else is built out of band and may
# legitimately lack a fresh timestamp.
PIPELINE_DATASETS = frozenset({"base", "quarter_insights", "brand_health", "reports"})

RECEIPTS_DIRNAME = "build-receipts"


class BuildReceiptError(RuntimeError):
    """Base for this module's failures."""


class BuildReceiptCollision(BuildReceiptError):
    """A run id was written twice with different bytes."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def relocate(manifest_path: str) -> Path:
    """Turn a pointer binding path into a data-root-relative path.

    Delegates to release_paths so the `data/reddit-voc/` prefix is stripped in
    exactly one place. Imported lazily: this module must be importable on its
    own (tests and scripts both use it) without the caller managing sys.path.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from release_paths import relocate_manifest_path

    return Path(str(relocate_manifest_path(manifest_path)))


def _atomic_write(path: Path, payload: bytes, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def canonical_bytes(value: object) -> bytes:
    """Sorted, compact JSON — the same bytes on every machine and every run."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def write_dataset_stamp(
    data_root: Path,
    dataset_key: str,
    binding: Mapping[str, Any],
    *,
    run_id: str,
    build_basis: str,
    period_end_utc: str | None,
    generated_at_utc: str | None = None,
    source_unavailable_reason: str | None = None,
) -> Path:
    """Write `<dataset>/build.json` and return its path.

    The manifest hash is computed from the bytes on disk, then compared with the
    binding the pointer advertises. A mismatch means the pointer and the tree
    disagree, which is precisely the state a monitor must never accept — so this
    refuses rather than writing a stamp that would launder the disagreement.
    """
    if not RUN_ID_PATTERN.match(run_id or ""):
        raise ValueError(f"invalid_run_id:{run_id!r}")
    if build_basis not in BUILD_BASES:
        raise ValueError(f"invalid_build_basis:{build_basis!r}")

    manifest_rel = relocate(str(binding.get("manifest_path") or ""))
    dataset_dir = Path(data_root) / manifest_rel.parent
    manifest_abs = Path(data_root) / manifest_rel
    if not manifest_abs.is_file():
        raise BuildReceiptError(f"manifest_missing:{manifest_rel.as_posix()}")

    actual = _sha256(manifest_abs.read_bytes())
    declared = str(binding.get("public_manifest_sha256") or "")
    if declared and declared != actual:
        raise BuildReceiptError(
            f"manifest_sha_mismatch:{dataset_key}:declared={declared[:12]}:actual={actual[:12]}"
        )

    # A frozen dataset has no fresh build time. Recording null without a reason
    # would be indistinguishable from a producer that forgot to set it.
    if generated_at_utc is None and not source_unavailable_reason:
        raise BuildReceiptError(f"generated_at_missing_without_reason:{dataset_key}")

    stamp = {
        "schema_version": STAMP_SCHEMA,
        "dataset_key": dataset_key,
        "dataset_version": str(binding.get("dataset_version") or ""),
        "run_id": run_id,
        "build_basis": build_basis,
        "manifest_sha256": actual,
        "manifest_path": manifest_rel.as_posix(),
        "period_end_utc": period_end_utc,
        "generated_at_utc": generated_at_utc,
    }
    if source_unavailable_reason:
        stamp["source_unavailable_reason"] = source_unavailable_reason

    target = dataset_dir / "build.json"
    _atomic_write(target, canonical_bytes(stamp))
    return target


def write_build_receipt(
    data_root: Path,
    run_id: str,
    *,
    release: Mapping[str, Any],
    status: str,
    period_end_utc: str | None,
    started_at_utc: str | None = None,
    finished_at_utc: str | None = None,
    steps: list[Mapping[str, Any]] | None = None,
    errors: list[Mapping[str, Any]] | None = None,
) -> Path:
    """Write `build-receipts/<run_id>.json`, create-new and immutable.

    A run id names exactly one run. If the file already exists with the same
    bytes this is a no-op (a retried identical run); different bytes for the
    same id means either a duplicate run id or a mutated history, and both
    destroy the receipt's value — so it raises instead of overwriting.
    """
    if not RUN_ID_PATTERN.match(run_id or ""):
        raise ValueError(f"invalid_run_id:{run_id!r}")

    datasets: dict[str, dict[str, Any]] = {}
    for key, binding in (release.get("datasets") or {}).items():
        manifest_rel = relocate(str(binding.get("manifest_path") or ""))
        manifest_abs = Path(data_root) / manifest_rel
        stamp_abs = manifest_abs.parent / "build.json"
        entry: dict[str, Any] = {
            "dataset_version": str(binding.get("dataset_version") or ""),
            "manifest_path": manifest_rel.as_posix(),
            "binding_manifest_sha256": str(binding.get("public_manifest_sha256") or ""),
            "manifest_sha256": (
                _sha256(manifest_abs.read_bytes()) if manifest_abs.is_file() else None
            ),
            "build_stamp_present": stamp_abs.is_file(),
        }
        if stamp_abs.is_file():
            try:
                stamp = json.loads(stamp_abs.read_text(encoding="utf-8"))
                entry["build_stamp_manifest_sha256"] = stamp.get("manifest_sha256")
                entry["build_basis"] = stamp.get("build_basis")
            except (OSError, ValueError):
                entry["build_stamp_manifest_sha256"] = None
        datasets[key] = entry

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "run_id": run_id,
        "status": status,
        "release_id": str(release.get("release_id") or ""),
        "period_end_utc": period_end_utc,
        "started_at_utc": started_at_utc,
        "finished_at_utc": finished_at_utc,
        "datasets": datasets,
        "steps": [
            {k: s.get(k) for k in ("step", "status", "error") if k in s}
            for s in (steps or [])
            if isinstance(s, Mapping)
        ],
        "errors": [
            {k: e.get(k) for k in ("step", "status", "error") if k in e}
            for e in (errors or [])
            if isinstance(e, Mapping)
        ],
    }

    payload = canonical_bytes(receipt)
    target = Path(data_root) / RECEIPTS_DIRNAME / f"{run_id}.json"
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file():
            raise BuildReceiptCollision(f"build_receipt_collision:{run_id}")
        if target.read_bytes() == payload:
            return target
        raise BuildReceiptCollision(f"build_receipt_collision:{run_id}")

    # 0600: the receipt names run ids and hashes but no secrets; still, it is an
    # internal artifact, not something to serve.
    _atomic_write(target, payload, mode=0o600)
    return target


def collect_dataset_stamps(
    data_root: Path,
    release: Mapping[str, Any],
    *,
    run_id: str,
    period_end_utc: str | None,
    generated_at_utc: str | None,
    frozen_reason: str = "external_manual_build",
) -> dict[str, Path]:
    """Write a stamp for every dataset the pointer names.

    Pipeline-built datasets get this run's id and timestamp. Frozen ones get the
    same run id (they were served by this run) but no timestamp, with the reason
    recorded — they were built out of band and pretending otherwise would make
    the stamp claim a freshness it does not have.
    """
    written: dict[str, Path] = {}
    for key, binding in (release.get("datasets") or {}).items():
        is_pipeline = key in PIPELINE_DATASETS
        written[key] = write_dataset_stamp(
            data_root,
            key,
            binding,
            run_id=run_id,
            build_basis="pipeline" if is_pipeline else "external_manual_build",
            period_end_utc=period_end_utc,
            generated_at_utc=generated_at_utc if is_pipeline else None,
            source_unavailable_reason=None if is_pipeline else frozen_reason,
        )
    return written
