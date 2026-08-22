from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

from .adapters import BrowserJsonAdapter
from .analyzer import analyze_text
from .backfill_archive import PrivateRawArchive
from .backfill_models import AnalysisRow, SeedImportSummary
from .backfill_storage import BackfillConflictError, BackfillStore
from .models import RawCapture


def make_raw_capture_id(
    *, run_id: str, source_method: str, source_url: str, payload_sha256: str
) -> str:
    value = "\0".join(
        (run_id, source_method, source_url, payload_sha256)
    ).encode()
    return "raw_backfill_" + sha256(value).hexdigest()[:24]


def import_seed_directory(
    store: BackfillStore,
    archive: PrivateRawArchive,
    *,
    run_id: str,
    source_dir: Path,
    window_start_utc: datetime,
    effective_end_utc: datetime,
    captured_at_utc: datetime,
) -> SeedImportSummary:
    source_root = _confined_source_root(source_dir)
    adapter = BrowserJsonAdapter()

    for relative_name, path in _seed_files(source_root):
        input_path_hash = sha256(relative_name.encode()).hexdigest()
        existing = store.load_seed_file(run_id, input_path_hash)
        payload_bytes = path.read_bytes()
        payload_sha256 = sha256(payload_bytes).hexdigest()
        if existing is not None:
            if existing["payload_sha256"] != payload_sha256:
                raise BackfillConflictError(
                    f"backfill_seed_files:{run_id}/{input_path_hash}"
                )
            continue

        source_method = "historical_seed"
        source_url = f"seed://{input_path_hash}"
        raw_capture_id = make_raw_capture_id(
            run_id=run_id,
            source_method=source_method,
            source_url=source_url,
            payload_sha256=payload_sha256,
        )
        provenance_captured_at_utc = captured_at_utc
        with store.connect() as conn:
            persisted_capture = conn.execute(
                "SELECT run_id, source_method, source_url, raw_payload_hash, "
                "captured_at_utc FROM raw_captures WHERE raw_capture_id = ?",
                (raw_capture_id,),
            ).fetchone()
        if persisted_capture is not None:
            expected_identity = (
                run_id,
                source_method,
                source_url,
                f"sha256:{payload_sha256}",
            )
            persisted_identity = tuple(
                persisted_capture[column]
                for column in (
                    "run_id",
                    "source_method",
                    "source_url",
                    "raw_payload_hash",
                )
            )
            if persisted_identity != expected_identity:
                raise BackfillConflictError(f"raw_captures:{raw_capture_id}")
            provenance_captured_at_utc = datetime.fromisoformat(
                str(persisted_capture["captured_at_utc"])
            )
        capture = RawCapture(
            raw_capture_id=raw_capture_id,
            run_id=run_id,
            source_method=source_method,
            source_url=source_url,
            captured_at_utc=provenance_captured_at_utc,
            auth_boundary="local_seed",
            raw_payload_hash=f"sha256:{payload_sha256}",
            payload_format="json",
        )
        artifact = archive.write(
            run_id=run_id,
            artifact_kind="seed",
            lane_type="seed",
            lane_key=input_path_hash,
            identity=payload_sha256,
            payload=payload_bytes,
            raw_capture_id=raw_capture_id,
            parser_kind="seed_browser_thread",
            source_method=source_method,
            source_url=source_url,
            source_endpoint="seed_file",
            captured_at_utc=provenance_captured_at_utc,
            page_number=0,
        )
        store.insert_entity_bundle(
            captures=(capture,), threads=(), comments=(), analyses=()
        )
        store.insert_raw_artifact(artifact)

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
            parsed = adapter.parse_thread_payload(
                payload,
                run_id=run_id,
                raw_capture_id=raw_capture_id,
                source_url=source_url,
            )
        except Exception as exc:
            store.record_seed_file(
                run_id=run_id,
                input_path_hash=input_path_hash,
                payload_sha256=payload_sha256,
                outcome="parse_error",
                artifact_id=artifact.artifact_id,
                post_id=None,
                error_class=type(exc).__name__,
                processed_at_utc=captured_at_utc,
            )
            continue

        thread = parsed.thread
        comments = tuple(parsed.comments)
        if not window_start_utc <= thread.created_at_utc < effective_end_utc:
            store.record_seed_file(
                run_id=run_id,
                input_path_hash=input_path_hash,
                payload_sha256=payload_sha256,
                outcome="outside_window",
                artifact_id=artifact.artifact_id,
                post_id=thread.post_id,
                error_class=None,
                processed_at_utc=captured_at_utc,
            )
            continue

        combined_text = "\n".join(
            (thread.title, thread.selftext, *(comment.body for comment in comments))
        )
        combined_analysis = analyze_text(combined_text)
        if not combined_analysis.keyword_match.is_relevant:
            store.record_seed_file(
                run_id=run_id,
                input_path_hash=input_path_hash,
                payload_sha256=payload_sha256,
                outcome="excluded",
                artifact_id=artifact.artifact_id,
                post_id=thread.post_id,
                error_class=None,
                processed_at_utc=captured_at_utc,
            )
            continue

        thread = replace(
            thread,
            matched_keywords=combined_analysis.keyword_match.matched_terms,
        )
        with store.connect() as conn:
            existing_thread = conn.execute(
                "SELECT raw_capture_id FROM reddit_threads WHERE post_id = ?",
                (thread.post_id,),
            ).fetchone()
        if (
            existing_thread is not None
            and existing_thread["raw_capture_id"] != raw_capture_id
        ):
            store.record_seed_file(
                run_id=run_id,
                input_path_hash=input_path_hash,
                payload_sha256=payload_sha256,
                outcome="duplicate",
                artifact_id=artifact.artifact_id,
                post_id=thread.post_id,
                error_class=None,
                processed_at_utc=captured_at_utc,
            )
            continue

        analyses = (
            _analysis_row(
                analysis_id=f"analysis_post_{thread.post_id}",
                run_id=run_id,
                source_type="post",
                source_id=thread.post_id,
                text=f"{thread.title}\n{thread.selftext}",
            ),
            *(
                _analysis_row(
                    analysis_id=f"analysis_comment_{comment.comment_id}",
                    run_id=run_id,
                    source_type="comment",
                    source_id=comment.comment_id,
                    text=comment.body,
                )
                for comment in comments
            ),
        )
        store.insert_entity_bundle(
            captures=(capture,),
            threads=(thread,),
            comments=comments,
            analyses=analyses,
        )
        store.record_seed_file(
            run_id=run_id,
            input_path_hash=input_path_hash,
            payload_sha256=payload_sha256,
            outcome="imported",
            artifact_id=artifact.artifact_id,
            post_id=thread.post_id,
            error_class=None,
            processed_at_utc=captured_at_utc,
        )

    outcome_counts = store.seed_outcome_counts(run_id)
    status = "failed" if outcome_counts.get("parse_error", 0) else "seed_complete"
    store.set_backfill_status(run_id, status, captured_at_utc)
    return _summary_from_store(store, run_id=run_id, status=status)


def _confined_source_root(source_dir: Path) -> Path:
    try:
        source_root = source_dir.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("source_dir must be an existing directory") from exc
    if not source_root.is_dir():
        raise ValueError("source_dir must be an existing directory")
    return source_root


def _seed_files(source_root: Path) -> tuple[tuple[str, Path], ...]:
    files: list[tuple[str, Path]] = []
    for path in source_root.rglob("*"):
        if path.is_symlink():
            raise ValueError("seed file must be confined to source_dir")
        if not path.is_file():
            continue
        if path.suffix.lower() != ".json":
            continue
        try:
            resolved = path.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ValueError("seed file must be confined to source_dir") from exc
        if not resolved.is_relative_to(source_root):
            raise ValueError("seed file must be confined to source_dir")
        if resolved.is_file():
            files.append((path.relative_to(source_root).as_posix(), resolved))
    return tuple(sorted(files, key=lambda item: item[0]))


def _analysis_row(
    *,
    analysis_id: str,
    run_id: str,
    source_type: str,
    source_id: str,
    text: str,
) -> AnalysisRow:
    analysis = analyze_text(text)
    return AnalysisRow(
        analysis_id=analysis_id,
        run_id=run_id,
        source_type=source_type,
        source_id=source_id,
        analysis_version="local_rules_v1",
        sentiment_label=analysis.sentiment_label,
        sentiment_score=analysis.sentiment_score,
        topic=analysis.topic,
        severity=analysis.severity,
        confidence=analysis.confidence,
        pain_points=tuple(analysis.pain_points),
        provider_call=False,
    )


def _summary_from_store(
    store: BackfillStore,
    *,
    run_id: str,
    status: str,
) -> SeedImportSummary:
    outcome_counts = store.seed_outcome_counts(run_id)
    with store.connect() as conn:
        threads = conn.execute(
            "SELECT COUNT(*) FROM reddit_threads WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        comments = conn.execute(
            "SELECT COUNT(*) FROM reddit_comments WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        analyses = conn.execute(
            "SELECT COUNT(*) FROM analysis_results WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        coverage_counts = {
            str(row["coverage_grade"]): int(row["count"])
            for row in conn.execute(
                "SELECT coverage_grade, COUNT(*) AS count FROM reddit_threads "
                "WHERE run_id = ? GROUP BY coverage_grade",
                (run_id,),
            ).fetchall()
        }
    return SeedImportSummary(
        run_id=run_id,
        status=status,
        files_total=store.seed_file_count(run_id),
        files_imported=outcome_counts.get("imported", 0),
        files_outside_window=outcome_counts.get("outside_window", 0),
        files_excluded=outcome_counts.get("excluded", 0),
        files_duplicate=outcome_counts.get("duplicate", 0),
        parse_errors=outcome_counts.get("parse_error", 0),
        threads=int(threads),
        comments=int(comments),
        analyses=int(analyses),
        coverage_full=coverage_counts.get("full", 0),
        coverage_partial=coverage_counts.get("partial", 0),
        coverage_post_only=coverage_counts.get("post_only", 0),
        provider_call=False,
        live_send=False,
    )
