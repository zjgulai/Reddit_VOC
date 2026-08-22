from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from scripts import build_reddit_site_snapshot as builder
from scripts import validate_reddit_site_snapshot as validator


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = ROOT / "tmp/reddit-voc-v3"
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _jsonl(rows: list[dict[str, object]]) -> bytes:
    return b"".join(_canonical(row) + b"\n" for row in rows)


def _write_private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _post(
    post_id: str,
    *,
    title: str,
    body: str,
    day: bool = False,
) -> dict[str, object]:
    record: dict[str, object] = {
        "author": f"private-{post_id}",
        "content": body,
        "permalink": f"https://www.reddit.com/r/test/comments/{post_id}/fixture/",
        "post_id": post_id,
        "reddit_id": f"t3_{post_id}",
        "title": title,
    }
    if day:
        record.update(
            {
                "event_time_precision": "day",
                "source_calendar_date": "2026-07-15",
                "source_timezone_status": "unknown",
            }
        )
    else:
        record.update(
            {
                "created_at_utc": "2026-07-15T02:03:04+00:00",
                "event_time_precision": "instant",
            }
        )
    return {
        "canonical_identity_state": "canonical_identity",
        "canonical_reddit_id": f"t3_{post_id}",
        "entity_type": "post",
        "post_id": post_id,
        "record": record,
        "record_authority": "governed_base",
        "schema_version": "reddit_voc_canonical_post_v1",
    }


def _comment(
    comment_id: str,
    *,
    post_id: str,
    body: str,
    state: str = "linked",
    day: bool = False,
) -> dict[str, object]:
    record: dict[str, object] = {
        "author": f"private-{comment_id}",
        "body": body,
        "comment_id": f"t1_{comment_id}",
        "parent_id": f"t3_{post_id}",
        "permalink": (
            f"https://www.reddit.com/r/test/comments/{post_id}/fixture/{comment_id}/"
        ),
        "post_id": post_id,
        "reddit_id": f"t1_{comment_id}",
    }
    if day:
        record.update(
            {
                "event_time_precision": "day",
                "source_calendar_date": "2026-07-15",
                "source_timezone_status": "unknown",
            }
        )
    else:
        record.update(
            {
                "created_at_utc": "2026-07-15T03:04:05+00:00",
                "event_time_precision": "instant",
            }
        )
    return {
        "canonical_identity_state": "canonical_identity",
        "canonical_reddit_id": f"t1_{comment_id}",
        "comment_state": state,
        "entity_type": "comment",
        "immediate_parent_resolution": "fixture",
        "post_id": post_id,
        "record": record,
        "record_authority": "governed_base",
        "schema_version": "reddit_voc_canonical_comment_v1",
    }


class SiteV3Fixture:
    def __init__(self) -> None:
        PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
        if (PRIVATE_ROOT.stat().st_mode & 0o777) != 0o700:
            raise AssertionError("private V3 test root must already have mode 0700")
        self._temporary = tempfile.TemporaryDirectory(
            prefix="site-v3-fixture-", dir=PRIVATE_ROOT
        )
        self.root = Path(self._temporary.name)
        self.root.chmod(0o700)
        self.canonical_root = self.root / "canonical"
        self.canonical_root.mkdir(mode=0o700)
        self.receipt_root = self.root / "canonical-validation"
        self.receipt_root.mkdir(mode=0o700)

        posts = [
            _post("p1", title="Instant parent", body="Ready body"),
            _post("p2", title="Floating parent", body="Ready body", day=True),
            _post("pempty", title="", body=""),
        ]
        comments = [
            _comment("c1", post_id="p1", body="Instant comment"),
            _comment("c2", post_id="p2", body="Floating comment", day=True),
            _comment("c3", post_id="pempty", body="Has body but no root context"),
            _comment(
                "orphan",
                post_id="missing",
                body="Unresolved comment",
                state="unresolved_parent",
                day=True,
            ),
        ]
        quarantined = _comment(
            "q1",
            post_id="missing2",
            body="Quarantined comment",
            state="quarantined",
        )
        quarantined["schema_version"] = "reddit_voc_canonical_quarantine_v1"
        record = quarantined["record"]
        assert isinstance(record, dict)
        record["missing_post_id"] = "missing2"

        self.documents: dict[str, list[dict[str, object]]] = {
            "comments.jsonl": comments,
            "conflict-ledger.jsonl": [],
            "posts.jsonl": posts,
            "provenance-ledger.jsonl": [],
            "quarantine.jsonl": [quarantined],
            "unresolved-parent-ledger.jsonl": [
                {
                    "canonical_reddit_id": "t1_orphan",
                    "comment_state": "unresolved_parent",
                    "post_id": "missing",
                    "schema_version": "reddit_voc_canonical_unresolved_parent_v1",
                }
            ],
        }
        bindings: dict[str, dict[str, object]] = {}
        for name, rows in self.documents.items():
            payload = _jsonl(rows)
            _write_private(self.canonical_root / name, payload)
            bindings[name] = {
                "bytes": len(payload),
                "rows": len(rows),
                "sha256": _sha(payload),
            }

        self.canonical_counts = {
            "comments_jsonl": 4,
            "linked_comments": 3,
            "posts": 3,
            "quarantined_comments": 1,
            "stored_comments": 5,
            "unresolved_parent_comments": 1,
        }
        inputs = {
            "base_lineage_manifest_sha256": "1" * 64,
            "base_public_manifest_sha256": "2" * 64,
            "source_manifest_sha256": "3" * 64,
            "workbook_import_manifest_sha256": "4" * 64,
            "workbook_import_validation_receipt_sha256": "5" * 64,
        }
        source_accounting = {
            "layer_separation": (
                "source_row_terminal_disposition_is_not_canonical_entity_state"
            ),
            "source_rows": 8,
            "terminal_outcomes": {"net_new_text_ready": 7, "unresolved_parent": 1},
        }
        manifest = {
            "boundaries": BOUNDARIES,
            "canonical_counts": self.canonical_counts,
            "consumption_status": "blocked_pending_independent_validation",
            "dataset_id": "fixture_canonical_v1",
            "files": bindings,
            "governed_base_parent_lineage_debt": {
                "linked_definition": (
                    "post_id_resolves_to_canonical_post_not_complete_immediate_parent_chain"
                ),
                "missing_immediate_parent_id": 0,
                "missing_parent_comment_entity": 0,
                "nested_links_whose_parent_record_lacks_immediate_parent_id": 0,
                "workbook_unresolved_parent_separate": True,
            },
            "independent_validation_status": "pending",
            "inputs": inputs,
            "promotable": False,
            "schema_version": "reddit_voc_canonical_snapshot_manifest_v1",
            "source_row_accounting": source_accounting,
            "state_contract": {
                "canonical_identity": True,
                "comment_states": ["linked", "unresolved_parent", "quarantined"],
                "states_mutually_exclusive": True,
            },
            "status": "candidate_built",
            "validation_receipt_sha256": None,
        }
        self.manifest_payload = _canonical(manifest) + b"\n"
        _write_private(
            self.canonical_root / "manifest.json", self.manifest_payload
        )
        receipt = {
            "boundaries": BOUNDARIES,
            "bundle_manifest_sha256": _sha(self.manifest_payload),
            "canonical_counts": self.canonical_counts,
            "consumption_status": "blocked_pending_voc_facts",
            "inputs": inputs,
            "promotable": False,
            "schema_version": (
                "reddit_voc_canonical_snapshot_validation_receipt_v1"
            ),
            "source_row_accounting": {
                "source_rows": source_accounting["source_rows"],
                "terminal_outcomes": source_accounting["terminal_outcomes"],
            },
            "status": "passed",
            "unaccounted_canonical_identities": 0,
            "unaccounted_foreign_keys": 0,
        }
        self.receipt_payload = _canonical(receipt) + b"\n"
        self.receipt_path = self.receipt_root / "receipt.json"
        _write_private(self.receipt_path, self.receipt_payload)

    def cleanup(self) -> None:
        self._temporary.cleanup()

    def v3_args(self, output: Path) -> list[str]:
        return [
            "--dataset-version",
            "reddit_voc_site_state_fixture_v3",
            "--generated-at-utc",
            "2026-07-16T00:00:00+00:00",
            "--output-dir",
            str(output),
            "--v3-canonical-root",
            str(self.canonical_root),
            "--v3-canonical-manifest-sha256",
            _sha(self.manifest_payload),
            "--v3-validation-receipt",
            str(self.receipt_path),
            "--v3-validation-receipt-sha256",
            _sha(self.receipt_payload),
        ]

    def validate(self, output: Path) -> dict[str, object]:
        return validator.validate(
            output,
            expected_dataset_version="reddit_voc_site_state_fixture_v3",
            v3_canonical_root=self.canonical_root,
            v3_canonical_manifest_sha256=_sha(self.manifest_payload),
            v3_validation_receipt=self.receipt_path,
            v3_validation_receipt_sha256=_sha(self.receipt_payload),
        )


class RedditSiteV3FusionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = SiteV3Fixture()
        self.addCleanup(self.fixture.cleanup)

    def test_v3_arguments_are_all_or_none_before_output_mutation(self) -> None:
        names_and_values = [
            ("--v3-canonical-root", str(self.fixture.canonical_root)),
            (
                "--v3-canonical-manifest-sha256",
                _sha(self.fixture.manifest_payload),
            ),
            ("--v3-validation-receipt", str(self.fixture.receipt_path)),
            (
                "--v3-validation-receipt-sha256",
                _sha(self.fixture.receipt_payload),
            ),
        ]
        for mask in range(1, 15):
            output = self.fixture.root / f"partial-{mask}"
            args = [
                "--dataset-version",
                "reddit_voc_site_state_fixture_v3",
                "--output-dir",
                str(output),
            ]
            for index, (name, value) in enumerate(names_and_values):
                if mask & (1 << index):
                    args.extend([name, value])
            with self.subTest(mask=mask), self.assertRaisesRegex(
                ValueError, "all.or.none"
            ):
                builder.main(args)
            self.assertFalse(output.exists())
            self.assertFalse(any(output.parent.glob(f".{output.name}.staging-*")))

    def test_v3_complete_union_state_vector_builds_and_independently_validates(self) -> None:
        output = self.fixture.root / "site-state"
        result = builder.main(self.fixture.v3_args(output))

        self.assertEqual(result, 0)
        self.assertEqual([path.name for path in output.iterdir()], ["manifest.json"])
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "reddit_voc_site_state_manifest_v3")
        self.assertEqual(manifest["files"], {})
        self.assertFalse(manifest["public_projection_complete"])
        self.assertFalse(manifest["release_candidate"])
        self.assertEqual(
            manifest["fusion_accounting"],
            {"fusion_mode": "complete_canonical_union", "legacy_append": False},
        )
        self.assertEqual(
            manifest["state_vector"]["canonical"],
            {
                **self.fixture.canonical_counts,
                "identity_lf_sha256": manifest["state_vector"]["canonical"][
                    "identity_lf_sha256"
                ],
                "total_identities": 8,
            },
        )
        self.assertEqual(manifest["state_vector"]["voc_facts"]["post_vocs"], 2)
        self.assertEqual(
            manifest["state_vector"]["voc_facts"]["comment_context_vocs"], 2
        )
        self.assertEqual(manifest["state_vector"]["voc_facts"]["total_vocs"], 4)
        self.assertEqual(manifest["state_vector"]["analysis_ready"]["total_vocs"], 4)
        self.assertEqual(manifest["state_vector"]["exclusions"]["excluded_identities"], 4)
        self.assertEqual(
            manifest["state_vector"]["metric_eligibility"]["membership_rows"],
            196,
        )
        self.assertEqual(
            manifest["state_vector"]["metric_eligibility"][
                "distinct_eligible_voc_facts"
            ],
            4,
        )
        self.assertEqual(
            manifest["state_vector"]["time_precision"],
            {
                "day_precision_vocs": 2,
                "instant_or_hour_precision_vocs": 2,
                "missing_event_time_vocs": 0,
            },
        )
        receipt = self.fixture.validate(output)
        self.assertEqual(receipt["status"], "passed_state_vector_only")
        self.assertFalse(receipt["release_candidate"])
        self.assertTrue(receipt["production_unchanged"])

    def test_v3_rejects_legacy_inputs_and_validator_partial_bindings(self) -> None:
        mixed_output = self.fixture.root / "mixed-inputs"
        mixed_args = [
            *self.fixture.v3_args(mixed_output),
            "--archive-dir",
            str(self.fixture.root / "must-not-be-read"),
        ]
        with self.assertRaisesRegex(ValueError, "rejects_legacy_inputs"):
            builder.main(mixed_args)
        self.assertFalse(mixed_output.exists())

        output = self.fixture.root / "validator-partial"
        builder.main(self.fixture.v3_args(output))
        with self.assertRaisesRegex(ValueError, "all-or-none"):
            validator.validate(
                output,
                expected_dataset_version="reddit_voc_site_state_fixture_v3",
                v3_canonical_root=self.fixture.canonical_root,
            )

    def test_v3_validator_requires_private_output_modes(self) -> None:
        output = self.fixture.root / "unsafe-mode"
        builder.main(self.fixture.v3_args(output))
        (output / "manifest.json").chmod(0o644)

        with self.assertRaisesRegex(ValueError, "0600"):
            self.fixture.validate(output)

    def test_floating_day_and_manifest_bytes_are_process_timezone_invariant(self) -> None:
        first = self.fixture.root / "tz-utc"
        second = self.fixture.root / "tz-shanghai"
        previous = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "UTC"
            if hasattr(time, "tzset"):
                time.tzset()
            builder.main(self.fixture.v3_args(first))
            os.environ["TZ"] = "Asia/Shanghai"
            if hasattr(time, "tzset"):
                time.tzset()
            builder.main(self.fixture.v3_args(second))
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            if hasattr(time, "tzset"):
                time.tzset()

        self.assertEqual(
            (first / "manifest.json").read_bytes(),
            (second / "manifest.json").read_bytes(),
        )

    def test_v3_validator_rejects_tampered_state_vector(self) -> None:
        output = self.fixture.root / "tampered"
        builder.main(self.fixture.v3_args(output))
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["state_vector"]["metric_eligibility"]["membership_rows"] += 1
        manifest_path.write_bytes(_canonical(manifest) + b"\n")
        manifest_path.chmod(0o600)

        with self.assertRaisesRegex(ValueError, "state|eligibility|mismatch"):
            self.fixture.validate(output)

    def test_wrong_canonical_binding_fails_before_output_creation(self) -> None:
        output = self.fixture.root / "wrong-sha"
        args = self.fixture.v3_args(output)
        index = args.index("--v3-canonical-manifest-sha256") + 1
        args[index] = "0" * 64

        with self.assertRaisesRegex(ValueError, "hash|SHA|binding"):
            builder.main(args)
        self.assertFalse(output.exists())
        self.assertFalse(any(output.parent.glob(f".{output.name}.staging-*")))


if __name__ == "__main__":
    unittest.main()
