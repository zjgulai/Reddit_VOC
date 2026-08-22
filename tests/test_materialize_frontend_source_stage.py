from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import scripts.materialize_frontend_source_stage as materializer


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


class FrontendSourceStageTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, str]:
        source = root / "source"
        (source / "src").mkdir(parents=True)
        (source / "public").mkdir()
        (source / "src/main.tsx").write_text("export const value = 1;\n", encoding="utf-8")
        (source / "package.json").write_text('{"scripts":{"build":"vite build"}}\n', encoding="utf-8")
        (source / "public/favicon.svg").write_text("<svg/>\n", encoding="utf-8")
        rows = []
        for relative in ("package.json", "public/favicon.svg", "src/main.tsx"):
            payload = (source / relative).read_bytes()
            rows.append(
                {"path": relative, "bytes": len(payload), "sha256": sha256(payload).hexdigest()}
            )
        rows.sort(key=lambda row: row["path"])
        manifest = {
            "schema_version": "reddit_voc_frontend_source_manifest_v1",
            "status": "frontend_source_frozen_local",
            "frontend_candidate_input_sha256": "a" * 64,
            "source": {
                "root_label": "fixture",
                "allowlist": ["package.json", "public", "src"],
                "inventory": {
                    "files": rows,
                    "file_count": len(rows),
                    "total_bytes": sum(row["bytes"] for row in rows),
                    "inventory_sha256": sha256(
                        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest(),
                },
            },
            "boundaries": {
                "artifact_build": False,
                "database_write": False,
                "deploy": False,
                "deployment": False,
                "live_send": False,
                "provider_call": False,
                "remote_write": False,
                "production_unchanged": True,
                "promotable_dist_included": False,
            },
        }
        manifest_path = root / "frontend-source-manifest.json"
        payload = canonical(manifest)
        manifest_path.write_bytes(payload)
        return source, manifest_path, sha256(payload).hexdigest()

    def test_materializes_only_manifest_files_and_returns_no_change(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest, manifest_sha = self.fixture(root)
            destination = root / "stage"
            receipt = root / "source-stage-receipt.json"
            first = materializer.materialize_source_stage(
                source_root=source,
                manifest_path=manifest,
                expected_manifest_sha256=manifest_sha,
                expected_candidate_input_sha256="a" * 64,
                destination=destination,
                receipt_path=receipt,
            )
            self.assertEqual(first["status"], "created")
            self.assertEqual(
                sorted(path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()),
                ["package.json", "public/favicon.svg", "src/main.tsx"],
            )
            mtime = receipt.stat().st_mtime_ns
            second = materializer.materialize_source_stage(
                source_root=source,
                manifest_path=manifest,
                expected_manifest_sha256=manifest_sha,
                expected_candidate_input_sha256="a" * 64,
                destination=destination,
                receipt_path=receipt,
            )
            self.assertEqual(second["status"], "no_change")
            self.assertEqual(receipt.stat().st_mtime_ns, mtime)

    def test_rejects_tamper_symlink_and_destination_collision(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest, manifest_sha = self.fixture(root)
            destination = root / "stage"
            receipt = root / "source-stage-receipt.json"
            (source / "src/main.tsx").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(materializer.SourceStageError, "source_member_contract_mismatch"):
                materializer.materialize_source_stage(
                    source_root=source,
                    manifest_path=manifest,
                    expected_manifest_sha256=manifest_sha,
                    expected_candidate_input_sha256="a" * 64,
                    destination=destination,
                    receipt_path=receipt,
                )

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest, manifest_sha = self.fixture(root)
            real = source / "src/main.real.tsx"
            (source / "src/main.tsx").rename(real)
            (source / "src/main.tsx").symlink_to(real)
            with self.assertRaisesRegex(materializer.SourceStageError, "source_member_unsafe"):
                materializer.materialize_source_stage(
                    source_root=source,
                    manifest_path=manifest,
                    expected_manifest_sha256=manifest_sha,
                    expected_candidate_input_sha256="a" * 64,
                    destination=root / "stage",
                    receipt_path=root / "receipt.json",
                )

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest, manifest_sha = self.fixture(root)
            destination = root / "stage"
            receipt = root / "receipt.json"
            materializer.materialize_source_stage(
                source_root=source,
                manifest_path=manifest,
                expected_manifest_sha256=manifest_sha,
                expected_candidate_input_sha256="a" * 64,
                destination=destination,
                receipt_path=receipt,
            )
            (destination / "extra.txt").write_text("collision", encoding="utf-8")
            with self.assertRaisesRegex(materializer.SourceStageError, "destination_immutable_collision"):
                materializer.materialize_source_stage(
                    source_root=source,
                    manifest_path=manifest,
                    expected_manifest_sha256=manifest_sha,
                    expected_candidate_input_sha256="a" * 64,
                    destination=destination,
                    receipt_path=receipt,
                )


if __name__ == "__main__":
    unittest.main()
