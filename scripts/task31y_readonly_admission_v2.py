#!/usr/bin/env python3
"""Task31Y stdout-only, fail-closed, read-only admission verifier."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import zlib
from urllib.parse import quote


TASK_ID = "Task31Y"
RUN_ID = "backfill_momcozy_20250101_20260711"
BASE = Path(
    "/opt/reddit-voc-staging/"
    "task28-5b0ff5afc5bac1df7907bcd8fd2fa2a3d335918f97471c378d4d405db194cd63/"
    "backfill_momcozy_20250101_20260711"
)
SOURCE = BASE / "reddit_voc_backfill.sqlite3"
RAW = BASE / "private-raw"
FRESH_ROOT = BASE / "task31y-comment-scope-recovery-20260729"
ROOTS = {
    "Task31": Path(
        "/opt/reddit-voc-staging/task31-comments-schema-recovery-20260727"
    ),
    "Task31R": Path(
        "/opt/reddit-voc-staging/task31r-comments-schema-recovery-20260727"
    ),
    "Task31S": Path(
        "/opt/reddit-voc-staging/task31s-comments-schema-recovery-20260727"
    ),
    "Task31T": BASE / "task31t-comments-schema-recovery-20260727",
    "Task31U": BASE / "task31u-comments-only-recovery-20260728",
    "Task31W": BASE / "task31w-owner-batch-recovery-20260728",
    "Task31X": BASE / "task31x-owner-batch-recovery-20260729",
}

BASELINE_RECEIPT_SHA256 = (
    "f89bf0f7155924f82b945b644c3a281e29d19032f8df4d405bb6e918c6ffb278"
)
TASK31Y_BUNDLE_SHA256 = (
    "4c6076a156214c3df0753c5a3b491ea4e71550bff8f52e9099bce6cf66b2deef"
)
EXPECTED_SOURCE_SHA256 = (
    "8baa66135aa58e34c83c7b1d7fd3170adf05f7fdeb342363f3cac13459c29f2f"
)
EXPECTED_TASK31X_REPORT_SHA256 = (
    "0b22029274d61328402161dab6fd99c87cb88edd0f743ab93d9110de88806f6f"
)
EXPECTED_TASK31X_BUNDLE_SHA256 = (
    "8260287ed8fd63333dfd35856576d3eac43f40ef5b5abcc41f85adcbae32f112"
)
EXPECTED_PROVIDER_COUNT = 969
EXPECTED_FAILED_IDS = (
    "1ue7uwh",
    "1uh2p4y",
    "1uii9fu",
    "1ulxa39",
    "1um6nu9",
    "1umdtae",
    "1umxfjy",
    "1un846y",
    "1unwyjp",
    "1uo8h0l",
    "1uq84k9",
    "1use8ft",
)
EXPECTED_CURSOR_PATH = [
    "data",
    "postInfoById",
    "commentForest",
    "pageInfo",
    "endCursor",
]

FILE_SHA256_DOMAIN = "file_bytes_sha256_v1"
INVENTORY_DOMAIN = "relative_path_file_sha256_canonical_json_v1"
PROVIDER_LEDGER_DOMAIN = "provider_attempt_rows_canonical_json_sha256_v1"
ARTIFACT_MAPPING_DOMAIN = "comment_artifact_mapping_canonical_json_sha256_v1"
CHECKPOINT_MAPPING_DOMAIN = "comment_checkpoint_mapping_canonical_json_sha256_v1"

BASELINE_PROVIDER_DIGEST = "21d6295278ccc2743f5b87f74a1d23aee2148abc4ff79b6870d8c7ad8c7ce9d5"
BASELINE_RAW_INVENTORY_DIGEST = (
    "0cddec4e00ebf49fb8067433b6a1fcc869b12580b4e7f1e4f9f708447d31fad2"
)
BASELINE_ARTIFACT_MAPPING_DIGEST = (
    "6a6c59ab833775f505097bd3406db030980df6ca36a8c645c05728947649a8de"
)
BASELINE_CHECKPOINT_MAPPING_DIGEST = (
    "1b582e61a0a9d7878c5d816cc924e814a7c60a55377791fccf7b0d593da158c6"
)
BASELINE_ROOT_DIGESTS = {
    "Task31": "1bf7e7b2f8b65979f54893542686be4e6e1d4cd87f2f2db2026cb8c32b08116c",
    "Task31R": "7b59c7c22ce433779377a352aea983ccb117e8469c495c69623548cfdc4fb369",
    "Task31S": "9586fd9b9be4303562822df6016f1bdc1a1f2c543250671ce2287dc6ae69994f",
    "Task31T": "222c9d0c3d60c914a609ca7a2e714d7acc1410b2bd76796f25edddb6af6628b5",
    "Task31U": "092eae5b2ee2926689666377c16895be6df768497924208f1758c21915570f54",
    "Task31W": "72eb0398fe0d555e4ba36fa7a2b414457422d45dfee4705cd7c7ff03e8209b9b",
    "Task31X": "8468f43282a3dc61449e7513ba1a0dc5eff0e7bd7c4bdfc21450e3adc57ac5ff",
}

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class AdmissionContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class DigestEvidence:
    domain: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.domain or _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("digest evidence is invalid")

    def as_dict(self) -> dict[str, str]:
        return {"domain": self.domain, "sha256": self.sha256}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: object, *, domain: str) -> DigestEvidence:
    return DigestEvidence(domain, hashlib.sha256(canonical_bytes(value)).hexdigest())


def file_digest(path: Path) -> DigestEvidence:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return DigestEvidence(FILE_SHA256_DOMAIN, digest.hexdigest())


def assert_same_digest(
    expected: DigestEvidence,
    actual: DigestEvidence,
    *,
    label: str,
) -> None:
    if expected.domain != actual.domain:
        raise AdmissionContractError(f"{label}_digest_domain_mismatch")
    if not hmac.compare_digest(expected.sha256, actual.sha256):
        raise AdmissionContractError(f"{label}_digest_value_mismatch")


def deterministic_gzip(payload: bytes) -> bytes:
    buffer = BytesIO()
    with gzip.GzipFile(
        filename="",
        fileobj=buffer,
        mode="wb",
        mtime=0,
    ) as compressed:
        compressed.write(payload)
    return buffer.getvalue()


def read_verified_gzip_payload(path: Path, expected_payload_sha256: str) -> bytes:
    try:
        if (
            path.is_symlink()
            or not path.is_file()
            or _SHA256_PATTERN.fullmatch(expected_payload_sha256) is None
        ):
            raise AdmissionContractError("raw_artifact_integrity_failed")
        compressed = path.read_bytes()
        payload = gzip.decompress(compressed)
        if not hmac.compare_digest(compressed, deterministic_gzip(payload)):
            raise AdmissionContractError("raw_artifact_integrity_failed")
        if not hmac.compare_digest(
            hashlib.sha256(payload).hexdigest(),
            expected_payload_sha256,
        ):
            raise AdmissionContractError("raw_artifact_integrity_failed")
        return payload
    except (
        AdmissionContractError,
        EOFError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        zlib.error,
    ):
        raise AdmissionContractError("raw_artifact_integrity_failed") from None


def inventory_digest(root: Path) -> tuple[DigestEvidence, list[list[str]]]:
    if root.is_symlink() or not root.is_dir():
        raise AdmissionContractError(f"inventory_root_invalid:{root}")
    rows: list[list[str]] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            if entry.is_symlink():
                raise AdmissionContractError(f"inventory_symlink:{entry.path}")
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                path = Path(entry.path)
                rows.append(
                    [
                        path.relative_to(root).as_posix(),
                        file_digest(path).sha256,
                    ]
                )
            else:
                raise AdmissionContractError(f"inventory_special:{entry.path}")
    rows.sort()
    return canonical_digest(rows, domain=INVENTORY_DOMAIN), rows


def checked_artifact_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise AdmissionContractError("comment_artifact_path_invalid")
    current = RAW
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise AdmissionContractError("comment_artifact_symlink")
    if not current.is_file():
        raise AdmissionContractError("comment_artifact_missing")
    return current


def active_recovery_processes() -> list[int]:
    matches: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\x00", b" ")
        except OSError:
            continue
        if b"recover-collection" in command:
            matches.append(int(entry.name))
    return sorted(matches)


def _record_digest_check(
    errors: list[str],
    checks: dict[str, bool],
    *,
    label: str,
    expected: DigestEvidence,
    actual: DigestEvidence,
) -> None:
    try:
        assert_same_digest(expected, actual, label=label)
    except AdmissionContractError as exc:
        checks[f"{label}_digest_exact"] = False
        errors.append(str(exc))
    else:
        checks[f"{label}_digest_exact"] = True


def collect_admission() -> dict[str, object]:
    errors: list[str] = []
    checks: dict[str, bool] = {}
    receipt: dict[str, object] = {
        "schema_version": "task31y_readonly_admission_v2",
        "task_id": TASK_ID,
        "generated_at_utc": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "baseline_receipt_sha256": BASELINE_RECEIPT_SHA256,
        "bound_task31y_bundle_sha256": TASK31Y_BUNDLE_SHA256,
        "proposed_root": str(FRESH_ROOT),
        "explicit_root_paths": {label: str(path) for label, path in ROOTS.items()},
        "automatic_root_discovery": False,
        "boundaries": {
            "sudo_readonly": True,
            "directory_created": False,
            "bundle_transferred": False,
            "bundle_extracted": False,
            "source_write": False,
            "raw_write": False,
            "old_root_write": False,
            "provider_call": False,
            "recover_collection_invoked": False,
            "target_created": False,
            "report_created": False,
        },
    }
    try:
        fresh_absent_before = not os.path.lexists(FRESH_ROOT)
        source_before = file_digest(SOURCE)
        raw_before, raw_rows_before = inventory_digest(RAW)
        roots_before: dict[str, DigestEvidence] = {}
        root_rows_before: dict[str, list[list[str]]] = {}
        for label, root in ROOTS.items():
            digest, rows = inventory_digest(root)
            roots_before[label] = digest
            root_rows_before[label] = rows

        connection = sqlite3.connect(
            f"file:{quote(str(SOURCE))}?mode=ro&immutable=1",
            uri=True,
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            integrity = [
                str(row[0]) for row in connection.execute("PRAGMA integrity_check")
            ]
            foreign_keys = [
                list(row) for row in connection.execute("PRAGMA foreign_key_check")
            ]
            manifest = connection.execute(
                "SELECT max_provider_requests, provider_request_count "
                "FROM backfill_manifests WHERE run_id=?",
                (RUN_ID,),
            ).fetchall()
            attempts = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM backfill_provider_attempts "
                    "WHERE run_id=? ORDER BY request_number",
                    (RUN_ID,),
                ).fetchall()
            ]
            provider_digest = canonical_digest(
                attempts,
                domain=PROVIDER_LEDGER_DOMAIN,
            )
            candidate_aggregate = [
                list(row)
                for row in connection.execute(
                    "SELECT status, status_reason, COUNT(*) "
                    "FROM backfill_candidates WHERE run_id=? "
                    "GROUP BY status, status_reason "
                    "ORDER BY status, status_reason",
                    (RUN_ID,),
                ).fetchall()
            ]
            failed_ids = tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT post_id FROM backfill_candidates "
                    "WHERE run_id=? AND status='failed' "
                    "AND status_reason='comments_schema_drift' "
                    "ORDER BY post_id",
                    (RUN_ID,),
                ).fetchall()
            )
            lane_hashes = {
                hashlib.sha256(post_id.encode()).hexdigest(): post_id
                for post_id in EXPECTED_FAILED_IDS
            }
            hash_marks = ",".join("?" for _ in lane_hashes)
            artifacts = connection.execute(
                "SELECT artifact_id, artifact_kind, lane_key_hash, "
                "payload_sha256, relative_path, parser_kind, source_method, "
                "page_number, request_cursor, response_cursor "
                "FROM backfill_raw_artifacts "
                "WHERE run_id=? AND lane_type='comments' "
                f"AND lane_key_hash IN ({hash_marks}) "
                "ORDER BY lane_key_hash, artifact_id",
                (RUN_ID, *sorted(lane_hashes)),
            ).fetchall()
            candidate_marks = ",".join("?" for _ in EXPECTED_FAILED_IDS)
            checkpoints = connection.execute(
                "SELECT lane_key, cursor, previous_cursor, page_number, "
                "discovered_count, unique_count, last_success_utc, last_error, "
                "status, stop_reason, cursor_json_path, cursor_schema_sha256 "
                "FROM backfill_checkpoints "
                "WHERE run_id=? AND lane_type='comments' "
                f"AND lane_key IN ({candidate_marks}) ORDER BY lane_key",
                (RUN_ID, *EXPECTED_FAILED_IDS),
            ).fetchall()
            artifact_mapping: list[list[str]] = []
            for row in artifacts:
                read_verified_gzip_payload(
                    checked_artifact_path(str(row["relative_path"])),
                    str(row["payload_sha256"]),
                )
                if (
                    row["artifact_kind"],
                    row["parser_kind"],
                    row["source_method"],
                    row["page_number"],
                    row["request_cursor"],
                    row["response_cursor"],
                ) != (
                    "comments",
                    "tikhub_comments",
                    "tikhub_comments",
                    1,
                    None,
                    None,
                ):
                    errors.append(
                        f"comment_artifact_contract:{row['artifact_id']}"
                    )
                artifact_mapping.append(
                    [
                        lane_hashes.get(str(row["lane_key_hash"]), ""),
                        str(row["artifact_id"]),
                        str(row["payload_sha256"]),
                    ]
                )
            checkpoint_mapping: list[list[str]] = []
            for row in checkpoints:
                try:
                    cursor_path = json.loads(str(row["cursor_json_path"]))
                except (TypeError, ValueError):
                    cursor_path = None
                if (
                    row["cursor"] is not None
                    or row["previous_cursor"] is not None
                    or row["page_number"] != 0
                    or row["discovered_count"] != 0
                    or row["unique_count"] != 0
                    or row["last_success_utc"] is not None
                    or row["last_error"] != "TikHubSchemaDrift"
                    or row["status"] != "partial"
                    or row["stop_reason"] != "comments_schema_drift"
                    or cursor_path != EXPECTED_CURSOR_PATH
                    or _SHA256_PATTERN.fullmatch(
                        str(row["cursor_schema_sha256"])
                    )
                    is None
                ):
                    errors.append(
                        f"comment_checkpoint_contract:{row['lane_key']}"
                    )
                checkpoint_mapping.append(
                    [
                        str(row["lane_key"]),
                        hashlib.sha256(
                            str(row["lane_key"]).encode()
                        ).hexdigest(),
                        str(row["cursor_schema_sha256"]),
                    ]
                )
            artifact_mapping_digest = canonical_digest(
                artifact_mapping,
                domain=ARTIFACT_MAPPING_DOMAIN,
            )
            checkpoint_mapping_digest = canonical_digest(
                checkpoint_mapping,
                domain=CHECKPOINT_MAPPING_DOMAIN,
            )
            structured_threads = int(
                connection.execute(
                    "SELECT COUNT(*) FROM reddit_threads WHERE run_id=? "
                    f"AND post_id IN ({candidate_marks})",
                    (RUN_ID, *EXPECTED_FAILED_IDS),
                ).fetchone()[0]
            )
            structured_comments = int(
                connection.execute(
                    "SELECT COUNT(*) FROM reddit_comments WHERE run_id=? "
                    f"AND post_id IN ({candidate_marks})",
                    (RUN_ID, *EXPECTED_FAILED_IDS),
                ).fetchone()[0]
            )
        finally:
            connection.close()

        source_after = file_digest(SOURCE)
        raw_after, raw_rows_after = inventory_digest(RAW)
        roots_after: dict[str, DigestEvidence] = {}
        root_rows_after: dict[str, list[list[str]]] = {}
        for label, root in ROOTS.items():
            digest, rows = inventory_digest(root)
            roots_after[label] = digest
            root_rows_after[label] = rows
        fresh_absent_after = not os.path.lexists(FRESH_ROOT)
        active = active_recovery_processes()

        _record_digest_check(
            errors,
            checks,
            label="source_before",
            expected=DigestEvidence(FILE_SHA256_DOMAIN, EXPECTED_SOURCE_SHA256),
            actual=source_before,
        )
        _record_digest_check(
            errors,
            checks,
            label="source_after",
            expected=DigestEvidence(FILE_SHA256_DOMAIN, EXPECTED_SOURCE_SHA256),
            actual=source_after,
        )
        _record_digest_check(
            errors,
            checks,
            label="provider",
            expected=DigestEvidence(
                PROVIDER_LEDGER_DOMAIN,
                BASELINE_PROVIDER_DIGEST,
            ),
            actual=provider_digest,
        )
        _record_digest_check(
            errors,
            checks,
            label="raw_before",
            expected=DigestEvidence(
                INVENTORY_DOMAIN,
                BASELINE_RAW_INVENTORY_DIGEST,
            ),
            actual=raw_before,
        )
        _record_digest_check(
            errors,
            checks,
            label="raw_after",
            expected=DigestEvidence(
                INVENTORY_DOMAIN,
                BASELINE_RAW_INVENTORY_DIGEST,
            ),
            actual=raw_after,
        )
        _record_digest_check(
            errors,
            checks,
            label="artifact_mapping",
            expected=DigestEvidence(
                ARTIFACT_MAPPING_DOMAIN,
                BASELINE_ARTIFACT_MAPPING_DIGEST,
            ),
            actual=artifact_mapping_digest,
        )
        _record_digest_check(
            errors,
            checks,
            label="checkpoint_mapping",
            expected=DigestEvidence(
                CHECKPOINT_MAPPING_DOMAIN,
                BASELINE_CHECKPOINT_MAPPING_DIGEST,
            ),
            actual=checkpoint_mapping_digest,
        )
        for label in ROOTS:
            expected = DigestEvidence(
                INVENTORY_DOMAIN,
                BASELINE_ROOT_DIGESTS[label],
            )
            _record_digest_check(
                errors,
                checks,
                label=f"{label.lower()}_before",
                expected=expected,
                actual=roots_before[label],
            )
            _record_digest_check(
                errors,
                checks,
                label=f"{label.lower()}_after",
                expected=expected,
                actual=roots_after[label],
            )

        expected_aggregate = [
            ["excluded", None, 5],
            ["failed", "comments_schema_drift", 12],
            ["hydrated", None, 147],
            ["hydrated", "unresolved_more", 95],
        ]
        task31x_rows = root_rows_before["Task31X"]
        checks.update(
            {
                "fresh_root_absent_before": fresh_absent_before,
                "fresh_root_absent_after": fresh_absent_after,
                "source_unchanged_during_admission": source_before == source_after,
                "source_sidecars_absent": not any(
                    os.path.lexists(Path(str(SOURCE) + suffix))
                    for suffix in ("-wal", "-shm", "-journal")
                ),
                "sqlite_integrity_ok": integrity == ["ok"],
                "foreign_keys_clean": not foreign_keys,
                "provider_manifest_count_exact": len(manifest) == 1
                and int(manifest[0]["provider_request_count"])
                == EXPECTED_PROVIDER_COUNT,
                "provider_attempt_count_exact": len(attempts)
                == EXPECTED_PROVIDER_COUNT,
                "candidate_aggregate_exact": candidate_aggregate
                == expected_aggregate,
                "failed_candidate_ids_exact": failed_ids
                == EXPECTED_FAILED_IDS,
                "comment_artifact_count_exact": len(artifacts)
                == len(EXPECTED_FAILED_IDS),
                "comment_checkpoint_count_exact": len(checkpoints)
                == len(EXPECTED_FAILED_IDS),
                "comment_artifact_lane_set_exact": sorted(
                    row[0] for row in artifact_mapping
                )
                == list(EXPECTED_FAILED_IDS),
                "comment_checkpoint_lane_set_exact": sorted(
                    row[0] for row in checkpoint_mapping
                )
                == list(EXPECTED_FAILED_IDS),
                "structured_residue_absent": structured_threads == 0
                and structured_comments == 0,
                "raw_unchanged_during_admission": raw_rows_before
                == raw_rows_after,
                "roots_unchanged_during_admission": roots_before
                == roots_after
                and root_rows_before == root_rows_after,
                "task31x_report_exact": sum(
                    1
                    for _path, digest in task31x_rows
                    if digest == EXPECTED_TASK31X_REPORT_SHA256
                )
                == 1,
                "task31x_bundle_exact": sum(
                    1
                    for _path, digest in task31x_rows
                    if digest == EXPECTED_TASK31X_BUNDLE_SHA256
                )
                == 1,
                "task31x_target_absent": not any(
                    path.endswith(".sqlite3")
                    for path, _digest in task31x_rows
                ),
                "active_recovery_processes_zero": not active,
            }
        )
        errors.extend(name for name, passed in checks.items() if not passed)
        receipt.update(
            {
                "status": "passed" if not errors else "failed",
                "errors": sorted(set(errors)),
                "checks": checks,
                "digest_evidence": {
                    "source_before": source_before.as_dict(),
                    "source_after": source_after.as_dict(),
                    "provider": provider_digest.as_dict(),
                    "raw_before": raw_before.as_dict(),
                    "raw_after": raw_after.as_dict(),
                    "artifact_mapping": artifact_mapping_digest.as_dict(),
                    "checkpoint_mapping": checkpoint_mapping_digest.as_dict(),
                    "roots_before": {
                        label: digest.as_dict()
                        for label, digest in roots_before.items()
                    },
                    "roots_after": {
                        label: digest.as_dict()
                        for label, digest in roots_after.items()
                    },
                },
                "provider_max_requests": (
                    int(manifest[0]["max_provider_requests"])
                    if len(manifest) == 1
                    else None
                ),
                "provider_attempt_count": len(attempts),
                "candidate_aggregate": candidate_aggregate,
                "failed_candidate_ids": list(failed_ids),
                "comment_artifact_count": len(artifacts),
                "comment_checkpoint_count": len(checkpoints),
                "structured_thread_residue": structured_threads,
                "structured_comment_residue": structured_comments,
                "raw_file_count": len(raw_rows_before),
                "task31x_file_count": len(task31x_rows),
                "active_recovery_processes": active,
            }
        )
    except Exception as exc:
        receipt["status"] = "failed"
        receipt["errors"] = sorted(
            set(
                errors
                + [f"operational_error:{type(exc).__name__}:{exc}"]
            )
        )
        receipt["checks"] = checks
    return receipt


def main() -> int:
    receipt = collect_admission()
    print(
        json.dumps(
            receipt,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if receipt["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
