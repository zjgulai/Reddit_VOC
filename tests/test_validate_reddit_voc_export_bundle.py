from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from reddit_voc.v3_export_bundle import (
    ARTIFACT_FILES,
    canonical_json_document,
    canonical_jsonl,
)
from scripts import validate_reddit_voc_export_bundle as validator
from tests.test_reddit_voc_export_bundle import BundleFixture


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _resign_artifact(bundle: Path, name: str, rows: list[dict]) -> str:
    payload = canonical_jsonl(rows)
    path = bundle / name
    path.write_bytes(payload)
    path.chmod(0o600)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract = next(row for row in manifest["artifacts"] if row["path"] == name)
    contract.update(
        {"byte_count": len(payload), "row_count": len(rows), "sha256": _sha(payload)}
    )
    manifest_payload = canonical_json_document(manifest)
    manifest_path.write_bytes(manifest_payload)
    manifest_path.chmod(0o600)
    return _sha(manifest_payload)


class ValidateRedditVocExportBundleTests(unittest.TestCase):
    def test_dynamic_materialization_source_layout_rejects_unsafe_paths(self) -> None:
        layout = {
            label: {"manifest": f"evidence/{label}/manifest.json", "receipt": f"evidence/{label}/receipt.json"}
            for label in validator.SOURCE_LAYOUT
        }
        layout["current_release"] = {"pointer": "evidence/current-release.json"}
        materialization = {"source_layout": layout}
        self.assertEqual(
            validator._source_layout(materialization)["canonical"]["manifest"],
            "evidence/canonical/manifest.json",
        )
        layout["canonical"]["manifest"] = "../outside/manifest.json"
        with self.assertRaisesRegex(
            validator.ExportBundleValidationError, "source layout invalid|path invalid"
        ):
            validator._source_layout(materialization)

    def test_validates_all_foreign_keys_and_writes_independent_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary))
            manifest_sha = fixture.build()
            result = validator.validate_export_bundle(
                fixture.output, expected_manifest_sha256=manifest_sha
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["artifact_count"], 4)
            self.assertEqual(
                result["cross_reference_counts"]["unresolved_entity_references"],
                0,
            )
            receipt = Path(temporary) / "validation/receipt.json"
            self.assertEqual(validator.write_receipt(receipt, result), "created")
            self.assertEqual(validator.write_receipt(receipt, result), "no_change")
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)

    def test_mixed_release_bundle_fails_even_when_file_and_manifest_are_resigned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary))
            fixture.build()
            name = "reddit-metrics-reporting.jsonl"
            rows = [
                json.loads(line)
                for line in (fixture.output / name).read_text(encoding="utf-8").splitlines()
            ]
            rows[0]["release_id"] = "reddit_voc_release_attacker_a1"
            manifest_sha = _resign_artifact(fixture.output, name, rows)
            with self.assertRaisesRegex(
                validator.ExportBundleValidationError, "release_id"
            ):
                validator.validate_export_bundle(
                    fixture.output, expected_manifest_sha256=manifest_sha
                )

    def test_rehashed_unresolved_reference_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary))
            fixture.build()
            name = "reddit-governance-casebook.jsonl"
            rows = [
                json.loads(line)
                for line in (fixture.output / name).read_text(encoding="utf-8").splitlines()
            ]
            rows[0]["entity_refs"] = ["t3_missing"]
            manifest_sha = _resign_artifact(fixture.output, name, rows)
            with self.assertRaisesRegex(
                validator.ExportBundleValidationError, "unresolved entity"
            ):
                validator.validate_export_bundle(
                    fixture.output, expected_manifest_sha256=manifest_sha
                )

    def test_deleted_refs_fail_after_artifact_and_manifest_are_resigned(self) -> None:
        for key in ("entity_refs", "fact_refs"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                fixture = BundleFixture(Path(temporary))
                fixture.build()
                name = "reddit-metrics-reporting.jsonl"
                rows = [
                    json.loads(line)
                    for line in (fixture.output / name)
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
                rows[0][key] = []
                manifest_sha = _resign_artifact(fixture.output, name, rows)
                with self.assertRaisesRegex(
                    validator.ExportBundleValidationError,
                    "independent payload derivation",
                ):
                    validator.validate_export_bundle(
                        fixture.output, expected_manifest_sha256=manifest_sha
                    )

    def test_forged_primary_key_fails_after_resign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary))
            fixture.build()
            name = "reddit-metrics-reporting.jsonl"
            rows = [
                json.loads(line)
                for line in (fixture.output / name)
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            rows[0]["metric_record_id"] = "metric:forged"
            manifest_sha = _resign_artifact(fixture.output, name, rows)
            with self.assertRaisesRegex(
                validator.ExportBundleValidationError,
                "metric_record_id.*independent payload derivation",
            ):
                validator.validate_export_bundle(
                    fixture.output, expected_manifest_sha256=manifest_sha
                )

    def test_receipt_parent_symlink_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real"
            real_parent.mkdir()
            alias = root / "alias"
            alias.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(
                validator.ExportBundleValidationError, "directory chain.*symlink"
            ):
                validator.write_receipt(alias / "receipt.json", {"status": "passed"})

    def test_source_path_swap_during_fd_read_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_bytes(b"a" * (2 * 1024 * 1024))
            replacement = root / "replacement.json"
            replacement.write_bytes(b"b" * (2 * 1024 * 1024))
            original_read = os.read
            swapped = False

            def swapping_read(descriptor: int, size: int) -> bytes:
                nonlocal swapped
                payload = original_read(descriptor, size)
                if payload and not swapped:
                    os.replace(replacement, source)
                    swapped = True
                return payload

            with mock.patch.object(validator.os, "read", side_effect=swapping_read), self.assertRaisesRegex(
                validator.ExportBundleValidationError, "bytes drift"
            ):
                validator._regular_payload(source, label="swapped source")

    def test_symlink_unknown_member_unsafe_mode_and_bytes_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary))
            manifest_sha = fixture.build()
            target = fixture.output / "reddit-entities-full.jsonl"
            target.chmod(0o644)
            with self.assertRaisesRegex(validator.ExportBundleValidationError, "mode"):
                validator.validate_export_bundle(
                    fixture.output, expected_manifest_sha256=manifest_sha
                )
            target.chmod(0o600)

            unknown = fixture.output / "unknown.jsonl"
            unknown.write_text("{}\n", encoding="utf-8")
            unknown.chmod(0o600)
            with self.assertRaisesRegex(validator.ExportBundleValidationError, "unknown"):
                validator.validate_export_bundle(
                    fixture.output, expected_manifest_sha256=manifest_sha
                )
            unknown.unlink()

            original = target.read_bytes()
            target.write_bytes(original + b" ")
            target.chmod(0o600)
            with self.assertRaisesRegex(
                validator.ExportBundleValidationError, "bytes drift"
            ):
                validator.validate_export_bundle(
                    fixture.output, expected_manifest_sha256=manifest_sha
                )
            target.write_bytes(original)
            target.chmod(0o600)

            outside = Path(temporary) / "outside.jsonl"
            outside.write_bytes(target.read_bytes())
            target.unlink()
            target.symlink_to(outside)
            with self.assertRaisesRegex(validator.ExportBundleValidationError, "symlink"):
                validator.validate_export_bundle(
                    fixture.output, expected_manifest_sha256=manifest_sha
                )

    def test_builder_and_validator_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary))
            inputs = Path(temporary) / "inputs"
            inputs.mkdir()
            paths = {}
            for name in ARTIFACT_FILES:
                path = inputs / name
                path.write_bytes(canonical_jsonl(fixture.rows[name]))
                paths[name] = path
            root = Path(__file__).resolve().parents[1]
            output = Path(temporary) / "cli-bundle"
            built = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_reddit_voc_export_bundle.py",
                    "--entities-full",
                    str(paths["reddit-entities-full.jsonl"]),
                    "--voc-facts",
                    str(paths["reddit-voc-facts.jsonl"]),
                    "--metrics-reporting",
                    str(paths["reddit-metrics-reporting.jsonl"]),
                    "--governance-casebook",
                    str(paths["reddit-governance-casebook.jsonl"]),
                    "--output",
                    str(output),
                    "--export-bundle-id",
                    fixture.bundle_id,
                    "--release-id",
                    fixture.release_id,
                    "--source-snapshot-id",
                    fixture.snapshot_id,
                    "--source-cutoff-value",
                    "2026-07-15",
                    "--source-cutoff-precision",
                    "day",
                    "--source-timezone-status",
                    "unknown_floating_date",
                    "--dictionary-sha256",
                    "1" * 64,
                    "--indicator-registry-sha256",
                    "2" * 64,
                    "--eligibility-policy-sha256",
                    "3" * 64,
                    "--builder-code-sha256",
                    _sha(
                        (
                            root / "scripts/build_reddit_voc_export_bundle.py"
                        ).read_bytes()
                    ),
                    "--validator-code-sha256",
                    _sha(
                        (
                            root / "scripts/validate_reddit_voc_export_bundle.py"
                        ).read_bytes()
                    ),
                    "--candidate-release-sha256",
                    "6" * 64,
                    "--bundle-mode",
                    "private_audit",
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            built_result = json.loads(built.stdout)
            receipt = Path(temporary) / "receipt.json"
            validated = subprocess.run(
                [
                    sys.executable,
                    "scripts/validate_reddit_voc_export_bundle.py",
                    "--bundle-root",
                    str(output),
                    "--expected-manifest-sha256",
                    built_result["export_bundle_manifest_sha256"],
                    "--receipt",
                    str(receipt),
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(validated.stdout)["status"], "passed")


if __name__ == "__main__":
    unittest.main()
