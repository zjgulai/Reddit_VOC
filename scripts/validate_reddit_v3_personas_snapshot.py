#!/usr/bin/env python3
"""Independently replay and validate the immutable V3 persona snapshot."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_persona_inference import (  # noqa: E402
    load_persona_cohort_config,
    load_persona_dictionary,
)
from reddit_voc.v3_persona_snapshot import validate_v3_persona_snapshot  # noqa: E402
from scripts.build_reddit_v3_personas_snapshot import (  # noqa: E402
    load_bound_governed_persona_signals,
    load_bound_persona_inputs,
)


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_receipt(path: Path, result: dict[str, object]) -> str:
    payload = (
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValueError("persona V3 validation receipt collision")
        return "no_change"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.write(descriptor, payload)
        os.close(descriptor)
        descriptor = -1
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
    return "created"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--personas-dir", type=Path, required=True)
    parser.add_argument("--expected-personas-manifest-sha256", required=True)
    parser.add_argument("--facts-dir", type=Path, required=True)
    parser.add_argument("--facts-manifest-sha256", required=True)
    parser.add_argument("--facts-validation-receipt", type=Path, required=True)
    parser.add_argument("--facts-validation-receipt-sha256", required=True)
    parser.add_argument("--governed-signals-manifest", type=Path, required=True)
    parser.add_argument("--governed-signals-manifest-sha256", required=True)
    parser.add_argument(
        "--governed-signals-validation-receipt", type=Path, required=True
    )
    parser.add_argument(
        "--governed-signals-validation-receipt-sha256", required=True
    )
    parser.add_argument("--reference-manifest", type=Path, required=True)
    parser.add_argument("--reference-manifest-sha256", required=True)
    parser.add_argument("--persona-dictionary", type=Path, required=True)
    parser.add_argument("--cohort-config", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    (
        vocs,
        automation_vocs,
        facts_sha,
        facts_receipt_sha,
        automation_classifications_sha,
        automation_classification_rows,
        reference_sha,
        _facts_upstream_consumption_status,
        _facts_upstream_promotable,
    ) = load_bound_persona_inputs(
        facts_dir=args.facts_dir,
        expected_facts_manifest_sha256=args.facts_manifest_sha256,
        facts_validation_receipt_path=args.facts_validation_receipt,
        expected_facts_validation_receipt_sha256=(
            args.facts_validation_receipt_sha256
        ),
        reference_manifest_path=args.reference_manifest,
        expected_reference_manifest_sha256=args.reference_manifest_sha256,
        allow_blocked_upstream_candidate=True,
    )
    governed = load_bound_governed_persona_signals(
        manifest_path=args.governed_signals_manifest,
        expected_manifest_sha256=args.governed_signals_manifest_sha256,
        validation_receipt_path=args.governed_signals_validation_receipt,
        expected_validation_receipt_sha256=(
            args.governed_signals_validation_receipt_sha256
        ),
        expected_facts_manifest_sha256=facts_sha,
        expected_facts_validation_receipt_sha256=facts_receipt_sha,
    )
    dictionary = load_persona_dictionary(args.persona_dictionary)
    config = load_persona_cohort_config(args.cohort_config, dictionary=dictionary)
    result = validate_v3_persona_snapshot(
        args.personas_dir,
        vocs=vocs,
        automation_voc_ids=automation_vocs,
        dictionary=dictionary,
        config=config,
        project_root=args.project_root,
        expected_source_facts_manifest_sha256=facts_sha,
        expected_source_facts_validation_receipt_sha256=facts_receipt_sha,
        expected_automation_manifest_sha256=facts_sha,
        expected_automation_classifications_sha256=(
            automation_classifications_sha
        ),
        expected_automation_classification_rows=automation_classification_rows,
        expected_reference_manifest_sha256=reference_sha,
        expected_upstream_consumption_status=governed.consumption_status,
        expected_upstream_promotable=governed.promotable,
        governed_signals_by_voc_id=governed.signals_by_voc_id,
        governed_signal_facts_by_voc_id=governed.facts_by_voc_id,
        expected_governed_signal_manifest_sha256=governed.manifest_sha256,
        expected_governed_signal_validation_receipt_sha256=(
            governed.validation_receipt_sha256
        ),
        expected_governed_signal_snapshot_id=governed.snapshot_id,
        expected_governed_signal_source_snapshot_id=governed.source_snapshot_id,
        expected_governed_signal_loaded_promoted_fact_count=(
            governed.loaded_promoted_fact_count
        ),
        expected_governed_signal_dropped_comment_fact_count=(
            governed.dropped_comment_fact_count
        ),
        expected_governed_signal_dropped_comment_voc_count=(
            governed.dropped_comment_voc_count
        ),
    )
    if result["manifest_sha256"] != args.expected_personas_manifest_sha256:
        raise ValueError("persona V3 manifest SHA mismatch")
    result["receipt_write_status"] = _write_receipt(args.receipt, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
