from __future__ import annotations

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from scripts.capture_reddit_candidate_sources import (
    CandidateSourceCaptureError,
    REMOTE_ROOT,
    REMOTE_SCHEMA_VERSION,
    _resolve_source_cutoff,
    capture_local_allowlist,
    capture_remote_sources,
    materialize_source_freeze,
    validate_remote_payload,
    write_manifest,
)


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _remote_payload(
    *,
    relative_path: str = "task-a/run/reports/search-lane-probe.json",
    payload: bytes = b'{"fixture":1}\n',
    role: str = "report",
) -> dict[str, object]:
    row = {
        "relative_path": relative_path,
        "basename": Path(relative_path).name,
        "role": role,
        "bytes": len(payload),
        "mtime_ns": 1_784_089_595_790_580_000,
        "mode": stat.S_IFREG | 0o600,
        "device": 1,
        "inode": 2,
        "sha256": _digest(payload),
    }
    return {
        "schema_version": REMOTE_SCHEMA_VERSION,
        "remote_root": REMOTE_ROOT,
        "observation_interval_seconds": 10,
        "first_observation": [row],
        "second_observation": [
            {**row, "content_base64": base64.b64encode(payload).decode("ascii")}
        ],
        "boundaries": {
            "provider_call": False,
            "provider_attempt_made": False,
            "remote_write": False,
            "database_write": False,
            "deploy": False,
            "live_send": False,
        },
    }


class CandidateSourceCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_local_external_root_copies_only_explicit_allowlist_and_is_immutable(self) -> None:
        external = self.root / "external"
        allowed = external / "Momcozy/Momcozy_01.json"
        ignored = external / "README.md"
        allowed.parent.mkdir(parents=True)
        allowed.write_bytes(b'{"posts":[]}\n')
        ignored.write_text("not selected\n", encoding="utf-8")

        members = capture_local_allowlist(
            "ai_nlp_reddit", external, ["Momcozy/Momcozy_01.json"]
        )
        output = self.root / "private-freeze"
        manifest, status = materialize_source_freeze(
            output,
            source_cutoff_utc="2026-07-15T08:00:00Z",
            members=members,
        )

        self.assertEqual(status, "created")
        copied = output / "sources/ai_nlp_reddit/Momcozy/Momcozy_01.json"
        self.assertEqual(copied.read_bytes(), allowed.read_bytes())
        self.assertFalse((output / "sources/ai_nlp_reddit/README.md").exists())
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        self.assertEqual(copied.stat().st_mode & 0o777, 0o600)
        manifest_path = output / "source-freeze-manifest.json"
        self.assertEqual(manifest_path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(manifest["raw_payload_embedded_in_manifest"])
        first_mtime = manifest_path.stat().st_mtime_ns

        repeated, repeated_status = materialize_source_freeze(
            output,
            source_cutoff_utc="2026-07-15T08:00:00+00:00",
            members=members,
        )
        self.assertEqual(repeated_status, "no_change")
        self.assertEqual(repeated, manifest)
        self.assertEqual(manifest_path.stat().st_mtime_ns, first_mtime)

    def test_local_governed_data_suffixes_and_capture_complete_cutoff(self) -> None:
        external = self.root / "external"
        external.mkdir()
        paths = ["tags.csv", "config.yaml", "history.sqlite3", "events.jsonl", "reddit.xlsx"]
        for relative in paths:
            (external / relative).write_bytes(f"fixture:{relative}\n".encode("utf-8"))

        members = capture_local_allowlist("governed_inputs", external, paths)
        self.assertTrue(all(member.fusion_eligible for member in members))
        output = self.root / "private"
        first_cutoff = _resolve_source_cutoff("capture-complete", output)
        manifest, status = materialize_source_freeze(
            output, source_cutoff_utc=first_cutoff, members=members
        )
        self.assertEqual(status, "created")
        self.assertEqual(
            _resolve_source_cutoff("capture-complete", output),
            manifest["source_cutoff_utc"],
        )
        self.assertEqual(
            _resolve_source_cutoff(manifest["source_cutoff_utc"], output),
            manifest["source_cutoff_utc"],
        )
        with self.assertRaisesRegex(
            CandidateSourceCaptureError, "source_cutoff_immutable_collision"
        ):
            _resolve_source_cutoff("2026-07-15T00:00:00Z", output)

        with self.assertRaisesRegex(
            CandidateSourceCaptureError, "source_cutoff_requires_capture_complete"
        ):
            _resolve_source_cutoff(
                "2026-07-15T08:00:00Z", self.root / "new-private"
            )

    def test_local_rejects_traversal_symlink_special_file_and_observation_drift(self) -> None:
        external = self.root / "external"
        external.mkdir()
        regular = external / "safe.json"
        regular.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(CandidateSourceCaptureError, "path_invalid"):
            capture_local_allowlist("archive", external, ["../safe.json"])

        target = self.root / "outside.json"
        target.write_text("{}\n", encoding="utf-8")
        (external / "linked.json").symlink_to(target)
        with self.assertRaisesRegex(CandidateSourceCaptureError, "member_unsafe"):
            capture_local_allowlist("archive", external, ["linked.json"])

        fifo = external / "pipe.json"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(CandidateSourceCaptureError, "member_unsafe"):
            capture_local_allowlist("archive", external, ["pipe.json"])

        def mutate() -> None:
            regular.write_text('{"changed":true}\n', encoding="utf-8")

        with self.assertRaisesRegex(CandidateSourceCaptureError, "source_drift"):
            capture_local_allowlist(
                "archive", external, ["safe.json"], between_observations=mutate
            )

    def test_remote_payload_allows_exact_reports_and_governed_plan_names(self) -> None:
        allowed = [
            "search-lane-probe.json",
            "search-continuation-probe.json",
            "comment-repair-probe.json",
            "comment-reply-probe.json",
        ]
        for basename in allowed:
            payload = _remote_payload(
                relative_path=f"task/run/reports/{basename}"
            )
            members = validate_remote_payload(payload)
            self.assertEqual(members[0].relative_path, f"task/run/reports/{basename}")

        plan = _remote_payload(
            relative_path="task/run/v2-search-cont-task2600-plan.json",
            role="plan",
        )
        self.assertEqual(validate_remote_payload(plan)[0].source_kind, "remote_plan")

    def test_remote_payload_rejects_unknown_name_traversal_special_and_drift(self) -> None:
        with self.assertRaisesRegex(CandidateSourceCaptureError, "filename_invalid"):
            validate_remote_payload(
                _remote_payload(relative_path="task/run/reports/secret.json")
            )

        with self.assertRaisesRegex(CandidateSourceCaptureError, "path_invalid"):
            validate_remote_payload(
                _remote_payload(relative_path="task/../reports/search-lane-probe.json")
            )

        special = _remote_payload()
        special["first_observation"][0]["mode"] = stat.S_IFIFO | 0o600  # type: ignore[index]
        special["second_observation"][0]["mode"] = stat.S_IFIFO | 0o600  # type: ignore[index]
        with self.assertRaisesRegex(CandidateSourceCaptureError, "member_unsafe"):
            validate_remote_payload(special)

        drift = _remote_payload()
        drift["second_observation"][0]["mtime_ns"] += 1  # type: ignore[index,operator]
        with self.assertRaisesRegex(CandidateSourceCaptureError, "source_drift"):
            validate_remote_payload(drift)

    @mock.patch("scripts.capture_reddit_candidate_sources.subprocess.run")
    def test_remote_capture_uses_pinned_known_hosts_and_stdout_only(
        self, run: mock.Mock
    ) -> None:
        identity = self.root / "DDDD.pem"
        known_hosts = self.root / "known_hosts"
        identity.write_text("private-key-fixture\n", encoding="utf-8")
        known_hosts.write_text("host-key-fixture\n", encoding="utf-8")
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(_remote_payload()).encode("utf-8"),
            stderr=b"",
        )

        members = capture_remote_sources(
            remote="ubuntu@101.34.52.232",
            identity_file=identity,
            known_hosts_file=known_hosts,
            observation_interval_seconds=10,
        )

        self.assertEqual(len(members), 1)
        command = run.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn(f"UserKnownHostsFile={known_hosts}", command)
        self.assertNotIn(identity.read_text(encoding="utf-8"), " ".join(command))
        self.assertIsNone(run.call_args.kwargs.get("stdin"))
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertIn("sudo -n python3 -c", command[-1])

    @mock.patch("scripts.capture_reddit_candidate_sources.subprocess.run")
    def test_remote_capture_exposes_only_allowlisted_failure_reason(
        self, run: mock.Mock
    ) -> None:
        identity = self.root / "DDDD.pem"
        known_hosts = self.root / "known_hosts"
        identity.write_text("private-key-fixture\n", encoding="utf-8")
        known_hosts.write_text("host-key-fixture\n", encoding="utf-8")
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=b"",
            stderr=b"candidate_source_capture_failed:remote_capture_bound_exceeded\n",
        )

        with self.assertRaisesRegex(
            CandidateSourceCaptureError,
            "remote_capture_failed:remote_capture_bound_exceeded",
        ):
            capture_remote_sources(
                remote="ubuntu@101.34.52.232",
                identity_file=identity,
                known_hosts_file=known_hosts,
            )

        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=b"",
            stderr=b"permission denied: /private/path\n",
        )
        with self.assertRaisesRegex(
            CandidateSourceCaptureError,
            "remote_capture_failed:remote_unclassified",
        ):
            capture_remote_sources(
                remote="ubuntu@101.34.52.232",
                identity_file=identity,
                known_hosts_file=known_hosts,
            )

    def test_manifest_and_destination_collisions_fail_closed(self) -> None:
        external = self.root / "external"
        external.mkdir()
        source = external / "one.json"
        source.write_text('{"version":1}\n', encoding="utf-8")
        members = capture_local_allowlist("archive", external, ["one.json"])
        output = self.root / "private"
        _, status = materialize_source_freeze(
            output,
            source_cutoff_utc="2026-07-15T08:00:00Z",
            members=members,
        )
        self.assertEqual(status, "created")

        manifest_path = output / "source-freeze-manifest.json"
        with self.assertRaisesRegex(CandidateSourceCaptureError, "manifest_immutable_collision"):
            write_manifest(manifest_path, {"different": True})

        copied = output / "sources/archive/one.json"
        copied.write_text('{"tampered":true}\n', encoding="utf-8")
        with self.assertRaisesRegex(
            CandidateSourceCaptureError, "destination_member_content_mismatch"
        ):
            materialize_source_freeze(
                output,
                source_cutoff_utc="2026-07-15T08:00:00Z",
                members=members,
            )

    def test_existing_manifest_requires_exact_tree_and_never_repairs_missing_member(self) -> None:
        external = self.root / "external"
        external.mkdir()
        source = external / "one.json"
        source.write_text('{"version":1}\n', encoding="utf-8")
        members = capture_local_allowlist("archive", external, ["one.json"])
        output = self.root / "private"
        materialize_source_freeze(
            output,
            source_cutoff_utc="2026-07-15T08:00:00Z",
            members=members,
        )
        copied = output / "sources/archive/one.json"
        copied.unlink()

        with self.assertRaisesRegex(
            CandidateSourceCaptureError, "destination_tree_set_mismatch"
        ):
            materialize_source_freeze(
                output,
                source_cutoff_utc="2026-07-15T08:00:00Z",
                members=members,
            )
        self.assertFalse(copied.exists())

    def test_rejects_extra_tree_members_and_partial_tree_without_manifest(self) -> None:
        external = self.root / "external"
        external.mkdir()
        source = external / "one.json"
        source.write_text('{"version":1}\n', encoding="utf-8")
        members = capture_local_allowlist("archive", external, ["one.json"])
        output = self.root / "private"
        materialize_source_freeze(
            output,
            source_cutoff_utc="2026-07-15T08:00:00Z",
            members=members,
        )
        extra = output / "extra.json"
        extra.write_text("{}\n", encoding="utf-8")
        extra.chmod(0o600)
        with self.assertRaisesRegex(
            CandidateSourceCaptureError, "destination_tree_set_mismatch"
        ):
            materialize_source_freeze(
                output,
                source_cutoff_utc="2026-07-15T08:00:00Z",
                members=members,
            )

        partial = self.root / "partial"
        partial.mkdir(mode=0o700)
        orphan = partial / "orphan.json"
        orphan.write_text("{}\n", encoding="utf-8")
        orphan.chmod(0o600)
        with self.assertRaisesRegex(
            CandidateSourceCaptureError, "destination_tree_without_manifest"
        ):
            materialize_source_freeze(
                partial,
                source_cutoff_utc="2026-07-15T08:00:00Z",
                members=members,
            )


if __name__ == "__main__":
    unittest.main()
