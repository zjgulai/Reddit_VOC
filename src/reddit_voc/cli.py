from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

from .adapters import BrowserJsonAdapter, BrowserJsonBlockedError
from .analyzer import analyze_text
from .browser_profile import init_browser_profile, inspect_browser_profile, launch_command_payload
from .browser_runner import BrowserHarnessRunner
from .collector import DEFAULT_DAILY_SUBREDDITS, collect_daily_reddit
from .dingtalk import build_payload, render_markdown_digest, render_run_digest, send_payload, with_required_keyword
from .exporter import export_run
from .models import RawCapture, RedditComment, RedditThread
from .ops import build_missed_run_report, build_run_issue_summary, parse_anchor_utc, prune_files
from .preflight import has_blocking_preflight_failure, local_doctor
from .search_config import DEFAULT_TIKHUB_SEARCH_TERMS
from .storage import VocStore
from .tikhub import TikHubClient, TikHubEndpointPlan, collect_daily_tikhub
from .time_window import daily_window


_DEEPSEEK_KEY_PATH = Path("/run/secrets/deepseek_api_key")
_PREPARED_DINGTALK_CREDENTIAL_PATH = Path(
    "/run/secrets/reddit_voc_report.env"
)
_PREPARED_DINGTALK_CREDENTIAL_MAX_BYTES = 64 * 1024
_SAFE_CONTROL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REPORT_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _read_deepseek_key(path: Path | None = None) -> str:
    key_path = Path(path or _DEEPSEEK_KEY_PATH)
    try:
        metadata = key_path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("deepseek_key_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("deepseek_key_not_regular")
    if metadata.st_uid != os.getuid():
        raise RuntimeError("deepseek_key_owner_invalid")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RuntimeError("deepseek_key_mode_invalid")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(key_path, flags)
    try:
        payload = os.read(descriptor, 4097)
        if len(payload) > 4096 or os.read(descriptor, 1):
            raise RuntimeError("deepseek_key_too_large")
    finally:
        os.close(descriptor)
    try:
        value = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("deepseek_key_invalid_utf8") from exc
    if value.endswith("\r\n"):
        value = value[:-2]
    elif value.endswith("\n"):
        value = value[:-1]
    if not value or value.strip() != value or "\n" in value or "\r" in value:
        raise RuntimeError("deepseek_key_invalid")
    return value


class _ProviderAttemptReservationSink:
    def __init__(self, *, root: Path, provider_authorization_id: str) -> None:
        _require_control_id(provider_authorization_id, "provider_authorization_id")
        _require_owned_mode_directory(root, mode=0o700)
        authorization_root = root / provider_authorization_id
        if authorization_root.exists() or authorization_root.is_symlink():
            _require_owned_mode_directory(authorization_root, mode=0o700)
        else:
            authorization_root.mkdir(mode=0o700)
            authorization_root.chmod(0o700)
            _fsync_cli_directory(root)
        self._provider_authorization_id = provider_authorization_id
        self._authorization_root = authorization_root
        self._path = authorization_root / "provider-attempts.jsonl"
        if self._path.exists() or self._path.is_symlink():
            raise RuntimeError("provider_attempt_log_exists")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self._path, flags, 0o600)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(self._path, 0o600)
        _fsync_cli_directory(authorization_root)

    def __call__(self, *, sequence: int, phase: str) -> None:
        if isinstance(sequence, bool) or sequence < 1:
            raise ValueError("provider_attempt_sequence_invalid")
        if phase not in {"translation", "semantic_validation"}:
            raise ValueError("provider_attempt_phase_invalid")
        record = {
            "schema_version": "provider-attempt-reservation-v1",
            "provider_authorization_id": self._provider_authorization_id,
            "sequence": sequence,
            "phase": phase,
        }
        payload = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"
        flags = os.O_WRONLY | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self._path, flags)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise RuntimeError("provider_attempt_log_write_failed")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_cli_directory(self._authorization_root)


def _provider_runtime_release_sha256(*, config_root: Path) -> str:
    """Fingerprint the exact local code/schema closure used for Provider calls."""
    package_root = Path(__file__).parent
    payloads = {
        "reddit_voc/cli.py": Path(__file__),
        "reddit_voc/deepseek_client.py": package_root / "deepseek_client.py",
        "reddit_voc/prepared_bundle.py": package_root / "prepared_bundle.py",
        "reddit_voc/prepared_report.py": package_root / "prepared_report.py",
        "reddit_voc/provider_attempt_ledger.py": package_root
        / "provider_attempt_ledger.py",
        "reddit_voc/report_contracts.py": package_root / "report_contracts.py",
        "reddit_voc/translation_pipeline.py": package_root / "translation_pipeline.py",
        "schemas/daily-translation-attempt-v1.schema.json": Path(config_root)
        / "schemas"
        / "daily-translation-attempt-v1.schema.json",
        "schemas/daily-translation-manifest-v1.schema.json": Path(config_root)
        / "schemas"
        / "daily-translation-manifest-v1.schema.json",
    }
    inventory: list[dict[str, object]] = []
    for name, path in sorted(payloads.items()):
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise RuntimeError("provider_runtime_payload_missing") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("provider_runtime_payload_invalid")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 5 * 1024 * 1024:
                    raise RuntimeError("provider_runtime_payload_too_large")
                chunks.append(chunk)
        finally:
            os.close(descriptor)
        payload = b"".join(chunks)
        inventory.append(
            {
                "name": name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return hashlib.sha256(
        json.dumps(
            inventory,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _private_provider_child(parent: Path, value: str, field: str) -> Path:
    _require_control_id(value, field)
    _require_owned_mode_directory(parent, mode=0o700)
    child = parent / value
    if child.exists() or child.is_symlink():
        _require_owned_mode_directory(child, mode=0o700)
    else:
        child.mkdir(mode=0o700)
        child.chmod(0o700)
        _fsync_cli_directory(parent)
    return child


def _create_provider_attempt_lifecycle(
    *,
    root: Path,
    provider_authorization_id: str,
    run_id: str,
    attempt_id: str,
    release_sha256: str,
):
    from .provider_attempt_ledger import ProviderAttemptLedger, ProviderAttemptLifecycle

    authorization_root = _private_provider_child(
        root, provider_authorization_id, "provider_authorization_id"
    )
    run_root = _private_provider_child(authorization_root, run_id, "run_id")
    attempt_root = _private_provider_child(run_root, attempt_id, "attempt_id")
    ledger = ProviderAttemptLedger(
        path=attempt_root / "provider-attempts-v2.jsonl",
        authorization_id=provider_authorization_id,
        release_sha256=release_sha256,
        run_id=run_id,
        attempt_id=attempt_id,
        clock=lambda: datetime.now(timezone.utc).isoformat(),
    )
    return ledger, ProviderAttemptLifecycle(ledger)


def _require_control_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_CONTROL_ID.fullmatch(value) is None:
        raise RuntimeError(f"{field}_invalid")
    return value


def _require_owned_mode_directory(path: Path, *, mode: int) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("control_directory_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("control_directory_invalid")
    if metadata.st_uid != os.getuid():
        raise RuntimeError("control_directory_owner_invalid")
    if stat.S_IMODE(metadata.st_mode) != mode:
        raise RuntimeError("control_directory_mode_invalid")


def _fsync_cli_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prepared_artifact_head_checker():
    from urllib.error import HTTPError
    from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

    from .prepared_report import validate_prepared_public_artifact_url

    class NoRedirectHandler(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = build_opener(ProxyHandler({}), NoRedirectHandler())

    def check(url: str, *, timeout_seconds: int) -> int:
        url = validate_prepared_public_artifact_url(url)
        request = Request(url, method="HEAD")
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                status = getattr(response, "status", None)
        except HTTPError as exc:
            status = exc.code
            exc.close()
        if not isinstance(status, int):
            raise RuntimeError("artifact_head_status_invalid")
        return status

    return check


def _prepared_delivery_transport():
    from .dingtalk import send_payload_bytes

    return send_payload_bytes


def _prepared_dingtalk_credential_values(
    *, path: Path | None = None
) -> dict[str, str]:
    """Read credential assignments from one private runtime file."""
    credential_path = Path(path or _PREPARED_DINGTALK_CREDENTIAL_PATH)
    try:
        path_metadata = credential_path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("dingtalk_secret_file_missing") from exc
    except OSError as exc:
        raise RuntimeError("dingtalk_secret_file_stat_failed") from exc
    if stat.S_ISLNK(path_metadata.st_mode) or not stat.S_ISREG(
        path_metadata.st_mode
    ):
        raise RuntimeError("dingtalk_secret_file_not_regular")
    if path_metadata.st_uid != os.getuid():
        raise RuntimeError("dingtalk_secret_file_owner_invalid")
    if stat.S_IMODE(path_metadata.st_mode) != 0o600:
        raise RuntimeError("dingtalk_secret_file_mode_invalid")

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(credential_path, flags)
    except OSError as exc:
        raise RuntimeError("dingtalk_secret_file_open_failed") from exc
    try:
        descriptor_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(descriptor_metadata.st_mode)
            or descriptor_metadata.st_dev != path_metadata.st_dev
            or descriptor_metadata.st_ino != path_metadata.st_ino
        ):
            raise RuntimeError("dingtalk_secret_file_changed")
        if descriptor_metadata.st_uid != os.getuid():
            raise RuntimeError("dingtalk_secret_file_owner_invalid")
        if stat.S_IMODE(descriptor_metadata.st_mode) != 0o600:
            raise RuntimeError("dingtalk_secret_file_mode_invalid")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 16 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _PREPARED_DINGTALK_CREDENTIAL_MAX_BYTES:
                raise RuntimeError("dingtalk_secret_file_too_large")
            chunks.append(chunk)
    except OSError as exc:
        raise RuntimeError("dingtalk_secret_file_read_failed") from exc
    finally:
        os.close(descriptor)

    payload = b"".join(chunks)
    if b"\x00" in payload or b"\r" in payload:
        raise RuntimeError("dingtalk_secret_file_control_character")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("dingtalk_secret_file_invalid_utf8") from exc
    values: dict[str, str] = {}
    seen: set[str] = set()
    credential_keys = {
        "DINGTALK_WEBHOOK_URL",
        "DINGTALK_WEBHOOK_SECRET",
        "DINGTALK_WEBHOOK_URL_2",
        "DINGTALK_WEBHOOK_SECRET_2",
    }
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError("dingtalk_secret_file_assignment_invalid")
        key, value = line.split("=", 1)
        if _REPORT_ENV_KEY.fullmatch(key) is None:
            raise RuntimeError("dingtalk_secret_file_key_invalid")
        if key in seen:
            raise RuntimeError("dingtalk_secret_file_duplicate_key")
        seen.add(key)
        if key in credential_keys:
            if value.strip() != value or any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in value
            ):
                raise RuntimeError("dingtalk_secret_file_credential_invalid")
            values[key] = value
    return values


def _prepared_dingtalk_credentials(
    *, path: Path | None = None
) -> tuple[str, str | None]:
    """Read only primary DingTalk credentials from one private runtime file."""
    values = _prepared_dingtalk_credential_values(path=path)
    secondary = {"DINGTALK_WEBHOOK_URL_2", "DINGTALK_WEBHOOK_SECRET_2"}
    if secondary.intersection(values):
        raise RuntimeError("dingtalk_secret_file_secondary_forbidden")
    if set(values) != {"DINGTALK_WEBHOOK_URL", "DINGTALK_WEBHOOK_SECRET"}:
        raise RuntimeError("dingtalk_secret_file_primary_missing")
    return values["DINGTALK_WEBHOOK_URL"], (
        values["DINGTALK_WEBHOOK_SECRET"] or None
    )


def _prepared_dingtalk_destination_credentials(
    *, path: Path | None = None
):
    from .daily_report_delivery import DingTalkDestinationCredential

    values = _prepared_dingtalk_credential_values(path=path)
    required = {
        "DINGTALK_WEBHOOK_URL",
        "DINGTALK_WEBHOOK_SECRET",
        "DINGTALK_WEBHOOK_URL_2",
        "DINGTALK_WEBHOOK_SECRET_2",
    }
    if set(values) != required or not values["DINGTALK_WEBHOOK_URL"] or not values[
        "DINGTALK_WEBHOOK_URL_2"
    ]:
        raise RuntimeError("dingtalk_secret_file_dual_credentials_missing")
    return (
        DingTalkDestinationCredential(
            destination_id="primary",
            webhook_url=values["DINGTALK_WEBHOOK_URL"],
            webhook_secret=values["DINGTALK_WEBHOOK_SECRET"] or None,
        ),
        DingTalkDestinationCredential(
            destination_id="secondary",
            webhook_url=values["DINGTALK_WEBHOOK_URL_2"],
            webhook_secret=values["DINGTALK_WEBHOOK_SECRET_2"] or None,
        ),
    )


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)


def _parse_optional_utc(value: str | None) -> datetime | None:
    return parse_anchor_utc(value) if value else None


def _apply_defaults(args: argparse.Namespace) -> argparse.Namespace:
    if hasattr(args, "database") and args.database is None:
        args.database = Path("data/reddit_voc.sqlite3")
    if hasattr(args, "output_dir") and args.output_dir is None:
        args.output_dir = Path("outputs")
    return args


def _insert_thread_analysis(store: VocStore, run_id: str, thread: RedditThread) -> None:
    analysis = analyze_text(f"{thread.title}\n{thread.selftext}")
    store.insert_analysis(
        analysis_id=f"analysis_post_{thread.post_id}",
        run_id=run_id,
        source_type="post",
        source_id=thread.post_id,
        sentiment_label=analysis.sentiment_label,
        sentiment_score=analysis.sentiment_score,
        topic=analysis.topic,
        severity=analysis.severity,
        confidence=analysis.confidence,
        pain_points=analysis.pain_points,
    )


def _insert_comment_analysis(store: VocStore, run_id: str, comment: RedditComment) -> None:
    analysis = analyze_text(comment.body)
    store.insert_analysis(
        analysis_id=f"analysis_comment_{comment.comment_id}",
        run_id=run_id,
        source_type="comment",
        source_id=comment.comment_id,
        sentiment_label=analysis.sentiment_label,
        sentiment_score=analysis.sentiment_score,
        topic=analysis.topic,
        severity=analysis.severity,
        confidence=analysis.confidence,
        pain_points=analysis.pain_points,
    )


def _export_artifact_paths(export_result) -> list[str]:
    return [
        str(export_result.posts_jsonl),
        str(export_result.comments_jsonl),
        str(export_result.analysis_jsonl),
        str(export_result.posts_csv),
        str(export_result.comments_csv),
        str(export_result.analysis_csv),
    ]


def _artifact_base_url(args: argparse.Namespace) -> str | None:
    value = getattr(args, "artifact_base_url", None) or os.getenv("REDDIT_VOC_ARTIFACT_BASE_URL", "")
    value = value.strip()
    return value or None


def _truncate(value: str, limit: int = 90) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _analysis_index(rows: list[dict[str, object]]) -> dict[tuple[str, str], dict[str, object]]:
    return {
        (str(row.get("source_type")), str(row.get("source_id"))): row
        for row in rows
    }


def _analysis_summary(row: dict[str, object] | None) -> str:
    if not row:
        return "sentiment=unknown | topic=unknown | severity=unknown"
    return (
        f"sentiment={row.get('sentiment_label')} | "
        f"topic={row.get('topic')} | "
        f"severity={row.get('severity')} | "
        f"confidence={row.get('confidence')}"
    )


def _build_dingtalk_detail_lines(store: VocStore, run_id: str, *, max_posts: int = 5, max_comments_per_post: int = 3) -> list[str]:
    posts = store.fetch_metric_threads_for_run(run_id)
    comments = store.fetch_metric_comments_for_run(run_id)
    analysis_by_source = _analysis_index(store.fetch_analysis_for_run(run_id))
    comments_by_post: dict[str, list[dict[str, object]]] = {}
    for comment in comments:
        comments_by_post.setdefault(str(comment.get("post_id")), []).append(comment)

    if not posts:
        return ["- No parsed Reddit posts for this run."]

    lines: list[str] = []
    for post in posts[:max_posts]:
        post_id = str(post.get("post_id"))
        post_url = str(post.get("source_url") or "")
        title = _truncate(str(post.get("title") or "untitled"))
        reported = post.get("num_comments_reported")
        parsed = post.get("parsed_comment_count")
        comment_count = f"{parsed}/{reported}" if reported is not None else str(parsed)
        post_label = f"Post {post_id}"
        if post_url:
            post_label = f"[{post_label}]({post_url})"
        lines.append(
            "- "
            + f"{post_label} | r/{post.get('subreddit')} | title={title} | "
            + f"comments={comment_count} | coverage={post.get('coverage_grade')} | "
            + _analysis_summary(analysis_by_source.get(("post", post_id)))
        )
        for comment in comments_by_post.get(post_id, [])[:max_comments_per_post]:
            comment_id = str(comment.get("comment_id"))
            comment_url = str(comment.get("source_url") or "")
            comment_label = f"Comment {comment_id}"
            if comment_url:
                comment_label = f"[{comment_label}]({comment_url})"
            body = _truncate(str(comment.get("body") or ""), 80)
            lines.append(
                "  - "
                + f"{comment_label} | text={body} | "
                + _analysis_summary(analysis_by_source.get(("comment", comment_id)))
            )
    if len(posts) > max_posts:
        lines.append(f"- Additional posts omitted from DingTalk preview: {len(posts) - max_posts}")
    return lines


def init_project(args: argparse.Namespace) -> int:
    for directory in ["data", "outputs", "logs", "tmp/smoke", "config", "docs", "tasks"]:
        Path(directory).mkdir(parents=True, exist_ok=True)
    store = VocStore(args.database)
    store.migrate()
    print(json.dumps({"status": "ok", "database": str(args.database)}, ensure_ascii=False))
    return 0


def export_run_command(args: argparse.Namespace) -> int:
    store = VocStore(args.database)
    store.migrate()
    if not store.get_run(args.run_id):
        result = {
            "run_id": args.run_id,
            "status": "failed",
            "reason": "run_not_found",
            "provider_call": False,
            "live_send": False,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 1
    result = export_run(store, run_id=args.run_id, output_dir=args.output_dir)
    print(json.dumps(result.as_dict(), ensure_ascii=False))
    return 0


def build_daily_source_batch_command(args: argparse.Namespace) -> int:
    from .daily_source_batch import build_daily_source_batch
    from .schema_migration import sha256_file

    database_path = Path(args.database)
    database_sha256_before = sha256_file(database_path)
    store = VocStore(database_path, read_only=True)
    store.require_daily_source_batch_schema()
    summary_path = args.collector_summary or Path(args.output_dir) / f"{args.run_id}-collector-summary.json"
    try:
        collector_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("collector_summary_invalid") from exc
    if not isinstance(collector_summary, dict):
        raise RuntimeError("collector_summary_invalid")
    result = build_daily_source_batch(
        store,
        run_id=args.run_id,
        raw_artifact_root=args.raw_artifact_root or Path(args.output_dir) / "raw-captures",
        output_root=args.source_batch_root or Path(args.output_dir) / "source-batches",
        query_profile_path=args.query_profile,
        coverage_profile_path=args.coverage_profile,
        collector_summary=collector_summary,
    )
    database_sha256_after = sha256_file(database_path)
    if database_sha256_after != database_sha256_before:
        raise RuntimeError("daily_source_batch_database_changed")
    print(
        json.dumps(
            {
                "batch_root": str(result.batch_root),
                "manifest_path": str(result.manifest_path),
                "manifest_sha256": result.manifest_sha256,
                "production_unchanged": True,
                "provider_call": False,
                "database_write": False,
                "database_sha256_before": database_sha256_before,
                "database_sha256_after": database_sha256_after,
                "remote_write": False,
                "deploy": False,
                "live_send": False,
                "write_status": result.write_status,
            },
            ensure_ascii=False,
        )
    )
    return 0


def migrate_database_schema_command(args: argparse.Namespace) -> int:
    from .schema_migration import migrate_database_schema

    if not args.authorize_schema_migration:
        raise RuntimeError("schema_migration_explicit_authorization_required")
    result = migrate_database_schema(
        database_path=args.database,
        expected_database_sha256=args.expected_database_sha256,
        backup_path=args.backup_path,
        rollback_path=args.rollback_path,
        authorization_id=args.authorization_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def build_backfill_source_batch_command(args: argparse.Namespace) -> int:
    from .backfill_source_batch import build_backfill_source_batch

    result = build_backfill_source_batch(
        database_path=args.database,
        archive_root=args.archive_root,
        run_id=args.run_id,
        output_root=args.source_batch_root or Path(args.output_dir) / "source-batches",
    )
    print(
        json.dumps(
            {
                "batch_root": str(result.batch_root),
                "manifest_path": str(result.manifest_path),
                "manifest_sha256": result.manifest_sha256,
                "production_unchanged": True,
                "provider_call": False,
                "database_write": False,
                "remote_write": False,
                "deploy": False,
                "live_send": False,
                "write_status": result.write_status,
            },
            ensure_ascii=False,
        )
    )
    return 0


def summarize_run_status(store: VocStore, run_id: str) -> dict[str, object]:
    run = store.get_run(run_id)
    if not run:
        return {
            "run_id": run_id,
            "status": "failed",
            "reason": "run_not_found",
            "provider_call": False,
            "live_send": False,
            "counts": {},
            "coverage": {},
        }

    counts = {
        "raw_captures": store.count_for_run("raw_captures", run_id),
        "threads": store.count_for_run("reddit_threads", run_id),
        "comments": store.count_for_run("reddit_comments", run_id),
        "analysis": store.count_for_run("analysis_results", run_id),
        "delivery_previews": store.count_for_run("delivery_previews", run_id),
    }
    coverage = store.coverage_summary_for_run(run_id)
    stored_status = str(run["status"])
    status = stored_status if stored_status in {"success", "partial", "empty", "failed"} else "failed"
    if status == "success" and counts["threads"] == 0:
        status = "empty"
    if status == "success" and any(coverage.get(grade, 0) for grade in ["partial", "post_only", "failed"]):
        status = "partial"

    return {
        "run_id": run_id,
        "status": status,
        "stored_status": stored_status,
        "window_start_utc": run["window_start_utc"],
        "window_end_utc": run["window_end_utc"],
        "provider_call": bool(run["provider_call"]),
        "live_send": bool(run["live_send"]) or store.delivery_live_send_count_for_run(run_id) > 0,
        "counts": counts,
        "coverage": coverage,
    }


def status_summary_command(args: argparse.Namespace) -> int:
    store = VocStore(args.database)
    store.migrate()
    result = summarize_run_status(store, args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "failed" and result.get("reason") == "run_not_found" else 0


def run_issue_summary_command(args: argparse.Namespace) -> int:
    store = VocStore(args.database)
    store.migrate()
    result = build_run_issue_summary(summarize_run_status(store, args.run_id))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["operational_state"] == "clear" else 1


def missed_run_check_command(args: argparse.Namespace) -> int:
    store = VocStore(args.database)
    store.migrate()
    result = build_missed_run_report(
        store,
        anchor_utc=parse_anchor_utc(args.anchor_utc),
        timezone_name=args.timezone,
        run_hour=args.run_hour,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "covered" else 2


def prune_artifacts_command(args: argparse.Namespace) -> int:
    result = prune_files(
        paths=args.path,
        patterns=args.pattern or ["*.log"],
        keep_last=args.keep_last,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def browser_profile_init_command(args: argparse.Namespace) -> int:
    result = init_browser_profile(args.profile_dir, workspace_root=Path.cwd())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "blocked" else 0


def browser_profile_status_command(args: argparse.Namespace) -> int:
    result = inspect_browser_profile(args.profile_dir, workspace_root=Path.cwd()).as_dict()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["inside_workspace"] else 0


def browser_profile_launch_command(args: argparse.Namespace) -> int:
    result = launch_command_payload(
        args.profile_dir,
        start_url=args.start_url,
        workspace_root=Path.cwd(),
        remote_debug_port=args.remote_debug_port,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "blocked" else 0


def build_dingtalk_dry_run_command(args: argparse.Namespace) -> int:
    store = VocStore(args.database)
    store.migrate()
    run_status = summarize_run_status(store, args.run_id)
    if run_status["status"] == "failed" and run_status.get("reason") == "run_not_found":
        print(json.dumps(run_status, ensure_ascii=False))
        return 1

    export_result = export_run(store, run_id=args.run_id, output_dir=args.output_dir)
    artifact_paths = _export_artifact_paths(export_result)
    title = f"Momcozy Reddit VOC Dry Run - {args.run_id}"
    markdown = render_run_digest(
        title=title,
        run_status=run_status,
        artifact_paths=artifact_paths,
        detail_lines=_build_dingtalk_detail_lines(store, args.run_id),
        artifact_base_url=_artifact_base_url(args),
    )
    payload = build_payload(title=title, markdown=markdown, live_send=False)
    store.insert_delivery_preview(
        f"delivery_{args.run_id}_dingtalk_dry_run",
        args.run_id,
        payload.message_hash,
        artifact_paths,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outbox = output_dir / f"{args.run_id}-dingtalk-dry-run.json"
    outbox.write_text(json.dumps(payload.body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "run_id": args.run_id,
        "outbox": str(outbox),
        "message_hash": payload.message_hash,
        "artifact_paths": artifact_paths,
        "provider_call": False,
        "live_send": False,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


def build_daily_report_command(args: argparse.Namespace) -> int:
    from .daily_report import build_daily_report, render_business_dingtalk_markdown_parts

    store = VocStore(args.database)
    store.migrate()
    run_status = summarize_run_status(store, args.run_id)
    if run_status["status"] == "failed" and run_status.get("reason") == "run_not_found":
        print(json.dumps(run_status, ensure_ascii=False))
        return 1

    translation_mode = args.translation_mode or os.getenv("REDDIT_VOC_TRANSLATION_MODE", "dry_run")
    report = build_daily_report(
        store,
        run_id=args.run_id,
        output_dir=args.output_dir,
        translation_mode=translation_mode,
    )
    title = f"Momcozy Reddit Post 日报 - {report.report_summary.get('report_date') or args.run_id}"
    report_provider_call = bool(run_status.get("provider_call")) or report.provider_call
    markdown_parts = render_business_dingtalk_markdown_parts(
        run_id=args.run_id,
        report=report,
        status_summary=run_status,
        artifact_base_url=_artifact_base_url(args),
        provider_call=report_provider_call,
        max_bytes=_dingtalk_markdown_max_bytes(),
        max_parts=_dingtalk_markdown_max_parts(),
    )
    required_keyword = args.required_keyword or os.getenv("DINGTALK_REQUIRED_KEYWORD", "")
    payloads = _build_business_report_payloads(
        title=title,
        markdown_parts=markdown_parts,
        required_keyword=required_keyword,
        live_send=False,
    )

    artifact_paths = report.artifact_paths()
    for index, payload in enumerate(payloads, start=1):
        store.insert_delivery_preview(
            _part_delivery_id(f"delivery_{args.run_id}_daily_report_dry_run", index, len(payloads)),
            args.run_id,
            payload.message_hash,
            artifact_paths,
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outbox = output_dir / f"{args.run_id}-daily-dingtalk-dry-run.json"
    outbox.write_text(json.dumps(_payload_outbox_body(payloads), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path = output_dir / f"{args.run_id}-daily-report-summary.json"
    result = {
        **report.as_dict(),
        "outbox": str(outbox),
        "summary": str(summary_path),
        "message_hash": _combined_message_hash(payloads),
        "message_hashes": [payload.message_hash for payload in payloads],
        "message_parts": len(payloads),
        "status_summary": run_status,
        "provider_call": report_provider_call,
        "live_send": False,
    }
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


def send_daily_report_live_command(args: argparse.Namespace) -> int:
    from .daily_report import build_daily_report, render_business_dingtalk_markdown_parts

    if not args.authorize_live_send or os.getenv("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND") != "1":
        result = {
            "run_id": args.run_id,
            "status": "blocked",
            "reason": "live_send_not_authorized",
            "provider_call": False,
            "live_send": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    webhook_url = os.getenv("DINGTALK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        result = {
            "run_id": args.run_id,
            "status": "blocked",
            "reason": "missing_dingtalk_webhook_env",
            "provider_call": False,
            "live_send": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    artifact_base_url = _artifact_base_url(args)
    if not artifact_base_url:
        result = {
            "run_id": args.run_id,
            "status": "blocked",
            "reason": "missing_artifact_base_url_for_html_report",
            "provider_call": False,
            "live_send": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    store = VocStore(args.database)
    store.migrate()
    run_status = summarize_run_status(store, args.run_id)
    if run_status["status"] == "failed" and run_status.get("reason") == "run_not_found":
        result = {**run_status, "live_send": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    translation_mode = args.translation_mode or os.getenv("REDDIT_VOC_TRANSLATION_MODE", "dry_run")
    report = build_daily_report(
        store,
        run_id=args.run_id,
        output_dir=args.output_dir,
        translation_mode=translation_mode,
    )
    if translation_mode == "deepseek" and report.translation_status not in {
        "translated",
        "local_glossary",
        "empty",
    }:
        result = {
            "run_id": args.run_id,
            "status": "blocked",
            "reason": "deepseek_translation_incomplete",
            "translation_mode": translation_mode,
            "translation_status": report.translation_status,
            "provider_call": report.provider_call,
            "live_send": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    required_keyword = args.required_keyword or os.getenv("DINGTALK_REQUIRED_KEYWORD", "")
    title = f"Momcozy Reddit Post 日报 - {report.report_summary.get('report_date') or args.run_id}"
    report_provider_call = bool(run_status.get("provider_call")) or report.provider_call
    markdown_parts = render_business_dingtalk_markdown_parts(
        run_id=args.run_id,
        report=report,
        status_summary={**run_status, "live_send": True},
        artifact_base_url=artifact_base_url,
        provider_call=report_provider_call,
        live_send=True,
        max_bytes=_dingtalk_markdown_max_bytes(),
        max_parts=_dingtalk_markdown_max_parts(),
    )
    payloads = _build_business_report_payloads(
        title=title,
        markdown_parts=markdown_parts,
        required_keyword=required_keyword,
        webhook_url=webhook_url,
        secret=os.getenv("DINGTALK_WEBHOOK_SECRET", "").strip() or None,
        live_send=True,
    )

    artifact_paths = report.artifact_paths()
    part_results = []
    for index, payload in enumerate(payloads, start=1):
        try:
            send_result = send_payload(
                webhook_url=webhook_url,
                payload=payload,
                timeout_seconds=args.timeout_seconds,
            )
        except Exception as exc:
            result = {
                "run_id": args.run_id,
                "status": "send_error",
                "error_type": type(exc).__name__,
                "message_hash": payload.message_hash,
                "message_part": index,
                "message_parts": len(payloads),
                "provider_call": report_provider_call,
                "live_send": False,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        store.insert_delivery_record(
            _part_delivery_id(f"delivery_{args.run_id}_daily_report_live", index, len(payloads)),
            args.run_id,
            payload.message_hash,
            artifact_paths,
            mode="live",
            status=send_result.status,
            live_send=True,
        )
        part_results.append(
            {
                "part": index,
                "status": send_result.status,
                "http_status": send_result.http_status,
                "response_hash": send_result.response_hash,
                "response_text": send_result.response_text,
                "message_hash": payload.message_hash,
                "body_bytes": len(json.dumps(payload.body, ensure_ascii=False).encode("utf-8")),
            }
        )
    overall_status = "sent" if all(part["status"] == "sent" for part in part_results) else "rejected"
    result = {
        "run_id": args.run_id,
        "status": overall_status,
        "http_status": part_results[-1]["http_status"] if part_results else None,
        "response_hash": part_results[-1]["response_hash"] if part_results else "",
        "response_text": part_results[-1]["response_text"] if part_results else "",
        "message_hash": _combined_message_hash(payloads),
        "message_hashes": [payload.message_hash for payload in payloads],
        "message_parts": len(payloads),
        "part_results": part_results,
        "required_keyword_present": bool(
            required_keyword
            and all(
                required_keyword
                in payload.body.get("markdown", {}).get("title", "")
                + payload.body.get("markdown", {}).get("text", "")
                for payload in payloads
            )
        ),
        "artifact_paths": artifact_paths,
        "provider_call": report_provider_call,
        "live_send": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _dingtalk_markdown_max_bytes() -> int:
    raw = os.getenv(
        "REDDIT_VOC_DINGTALK_MARKDOWN_MAX_BYTES",
        os.getenv("REDDIT_VOC_DINGTALK_MARKDOWN_MAX_CHARS", "15000"),
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        return 15000
    return max(4000, min(value, 19000))


def _dingtalk_markdown_max_parts() -> int:
    raw = os.getenv("REDDIT_VOC_DINGTALK_MARKDOWN_MAX_PARTS", "2").strip()
    try:
        value = int(raw)
    except ValueError:
        return 2
    return max(1, min(value, 2))


def _build_business_report_payloads(
    *,
    title: str,
    markdown_parts: list[str],
    required_keyword: str,
    webhook_url: str | None = None,
    secret: str | None = None,
    live_send: bool = False,
):
    payloads = []
    total = len(markdown_parts)
    for index, markdown in enumerate(markdown_parts, start=1):
        part_title = title if total == 1 else f"{title}（{index}/{total}）"
        part_title, part_markdown = with_required_keyword(
            title=part_title,
            markdown=markdown,
            required_keyword=required_keyword,
        )
        payloads.append(
            build_payload(
                title=part_title,
                markdown=part_markdown,
                webhook_url=webhook_url,
                secret=secret,
                live_send=live_send,
            )
        )
    return payloads


def _combined_message_hash(payloads) -> str:
    if len(payloads) == 1:
        return payloads[0].message_hash
    joined = "\n".join(payload.message_hash for payload in payloads)
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _payload_outbox_body(payloads):
    if len(payloads) == 1:
        return payloads[0].body
    return {"messages": [payload.body for payload in payloads]}


def _part_delivery_id(base: str, index: int, total: int) -> str:
    if total == 1:
        return base
    return f"{base}_part{index}"


def send_dingtalk_live_command(args: argparse.Namespace) -> int:
    if not args.authorize_live_send or os.getenv("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND") != "1":
        result = {
            "run_id": args.run_id,
            "status": "blocked",
            "reason": "live_send_not_authorized",
            "provider_call": False,
            "live_send": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    webhook_url = os.getenv("DINGTALK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        result = {
            "run_id": args.run_id,
            "status": "blocked",
            "reason": "missing_dingtalk_webhook_env",
            "provider_call": False,
            "live_send": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    store = VocStore(args.database)
    store.migrate()
    run_status = summarize_run_status(store, args.run_id)
    if run_status["status"] == "failed" and run_status.get("reason") == "run_not_found":
        result = {**run_status, "live_send": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    export_result = export_run(store, run_id=args.run_id, output_dir=args.output_dir)
    artifact_paths = _export_artifact_paths(export_result)
    required_keyword = args.required_keyword or os.getenv("DINGTALK_REQUIRED_KEYWORD", "")
    title = f"Momcozy Reddit VOC Live - {args.run_id}"
    markdown = render_run_digest(
        title=title,
        run_status={**run_status, "live_send": True},
        artifact_paths=artifact_paths,
        extra_summary_lines=[f"dingtalk_required_keyword={required_keyword}"] if required_keyword else None,
        detail_lines=_build_dingtalk_detail_lines(store, args.run_id),
        artifact_base_url=_artifact_base_url(args),
    )
    title, markdown = with_required_keyword(title=title, markdown=markdown, required_keyword=required_keyword)
    payload = build_payload(
        title=title,
        markdown=markdown,
        webhook_url=webhook_url,
        secret=os.getenv("DINGTALK_WEBHOOK_SECRET", "").strip() or None,
        live_send=True,
    )
    try:
        send_result = send_payload(
            webhook_url=webhook_url,
            payload=payload,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        result = {
            "run_id": args.run_id,
            "status": "send_error",
            "error_type": type(exc).__name__,
            "message_hash": payload.message_hash,
            "required_keyword_present": bool(required_keyword and required_keyword in markdown),
            "provider_call": False,
            "live_send": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    store.insert_delivery_record(
        f"delivery_{args.run_id}_dingtalk_live",
        args.run_id,
        payload.message_hash,
        artifact_paths,
        mode="live",
        status=send_result.status,
        live_send=True,
    )

    result = {
        "run_id": args.run_id,
        "status": send_result.status,
        "http_status": send_result.http_status,
        "response_hash": send_result.response_hash,
        "message_hash": payload.message_hash,
        "required_keyword_present": bool(required_keyword and required_keyword in markdown),
        "provider_call": False,
        "live_send": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_adapter_fixture_loop(args: argparse.Namespace) -> int:
    store = VocStore(args.database)
    store.migrate()

    fixture_path = args.fixture or Path("tests/fixtures/reddit_thread_browser_json.json")
    raw_text = fixture_path.read_text(encoding="utf-8")
    adapter = BrowserJsonAdapter()
    window = daily_window(anchor=datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc), run_hour=int(os.getenv("REDDIT_VOC_RUN_HOUR", "7")))
    run_id = args.run_id or "adapter_fixture_run_20260707"
    source_url = "https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json"

    store.upsert_run(run_id, "partial", window.start_utc.isoformat(), window.end_utc.isoformat())
    capture = adapter.build_raw_capture(
        raw_text,
        run_id=run_id,
        source_url=source_url,
        captured_at_utc=datetime.now(timezone.utc),
    )
    parsed = adapter.parse_thread_text(
        raw_text,
        run_id=run_id,
        raw_capture_id=capture.raw_capture_id,
        source_url=capture.source_url,
    )
    store.insert_raw_capture(capture)
    store.upsert_thread(parsed.thread)
    _insert_thread_analysis(store, run_id, parsed.thread)
    for comment in parsed.comments:
        store.upsert_comment(comment)
        _insert_comment_analysis(store, run_id, comment)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"{run_id}-adapter-summary.json"
    summary = {
        "run_id": run_id,
        "source_method": capture.source_method,
        "auth_boundary": capture.auth_boundary,
        "provider_call": False,
        "live_send": False,
        "coverage_grade": parsed.thread.coverage_grade,
        "more_node_count": parsed.thread.more_node_count,
        "counts": {
            "raw_captures": store.table_count("raw_captures"),
            "threads": store.table_count("reddit_threads"),
            "comments": store.table_count("reddit_comments"),
            "analysis": store.table_count("analysis_results"),
        },
    }
    artifact.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**summary, "artifact": str(artifact)}, ensure_ascii=False))
    return 0


def run_browser_json_smoke(args: argparse.Namespace) -> int:
    if not args.url:
        raise ValueError("--url is required for browser read-only smoke")

    store = VocStore(args.database)
    store.migrate()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    window = daily_window(anchor=datetime.now(timezone.utc))
    run_id = args.run_id or "browser_json_smoke_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    cdp_url = args.browser_cdp_url or os.getenv("REDDIT_VOC_BROWSER_CDP_URL", "").strip() or None
    browser_env = None
    reload_before_capture = False
    if cdp_url:
        browser_env = {
            "BU_CDP_URL": cdp_url,
            "BU_NAME": args.browser_daemon_name,
        }
        reload_before_capture = True
    runner = BrowserHarnessRunner(
        max_attempts=args.max_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
        env=browser_env,
        reload_before_capture=reload_before_capture,
    )
    adapter = BrowserJsonAdapter()

    capture_result = runner.capture_json_url(args.url)
    status = "success" if capture_result.is_usable_json else "failed"
    store.upsert_run(run_id, status, window.start_utc.isoformat(), window.end_utc.isoformat())

    summary = {
        "run_id": run_id,
        "source_method": "browser_json",
        "target_url": args.url,
        "page_url": capture_result.page_url,
        "browser_status": capture_result.browser_status,
        "blocked_reason": capture_result.blocked_reason,
        "provider_call": False,
        "live_send": False,
        "secrets_written": False,
        "browser_cdp_url": cdp_url,
        "raw_payload_hash": _hash_text(capture_result.raw_text) if capture_result.raw_text else None,
        "coverage_grade": "failed",
        "more_node_count": 0,
        "counts": {
            "raw_captures": store.table_count("raw_captures"),
            "threads": store.table_count("reddit_threads"),
            "comments": store.table_count("reddit_comments"),
            "analysis": store.table_count("analysis_results"),
        },
    }

    if capture_result.is_usable_json:
        ingest_ok = False
        capture = adapter.build_raw_capture(
            capture_result.raw_text,
            run_id=run_id,
            source_url=args.url,
            captured_at_utc=datetime.now(timezone.utc),
            browser_status=capture_result.browser_status,
        )
        try:
            parsed = adapter.parse_thread_text(
                capture_result.raw_text,
                run_id=run_id,
                raw_capture_id=capture.raw_capture_id,
                source_url=capture.source_url,
            )
            store.insert_raw_capture(capture)
            store.upsert_thread(parsed.thread)
            _insert_thread_analysis(store, run_id, parsed.thread)
            for comment in parsed.comments:
                store.upsert_comment(comment)
                _insert_comment_analysis(store, run_id, comment)
            store.upsert_run(run_id, "partial" if parsed.thread.coverage_grade == "partial" else "success", window.start_utc.isoformat(), window.end_utc.isoformat())
            summary["coverage_grade"] = parsed.thread.coverage_grade
            summary["more_node_count"] = parsed.thread.more_node_count
            ingest_ok = True
        except BrowserJsonBlockedError as exc:
            summary["browser_status"] = exc.browser_status
            summary["blocked_reason"] = exc.blocked_reason
        except json.JSONDecodeError:
            summary["browser_status"] = "error"
            summary["blocked_reason"] = "invalid_json_body"
        except ValueError:
            summary["browser_status"] = "error"
            summary["blocked_reason"] = "unexpected_reddit_json_shape"
        summary["counts"] = {
            "raw_captures": store.table_count("raw_captures"),
            "threads": store.table_count("reddit_threads"),
            "comments": store.table_count("reddit_comments"),
            "analysis": store.table_count("analysis_results"),
        }

    artifact = output_dir / f"{run_id}-browser-json-smoke-summary.json"
    artifact.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**summary, "artifact": str(artifact)}, ensure_ascii=False))
    return 0 if capture_result.is_usable_json and ingest_ok else 1


def run_daily_collector_command(args: argparse.Namespace) -> int:
    store = VocStore(args.database)
    store.migrate()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or "daily_collect_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    cdp_url = args.browser_cdp_url or os.getenv("REDDIT_VOC_BROWSER_CDP_URL", "").strip() or None
    browser_env = None
    reload_before_capture = False
    if cdp_url:
        browser_env = {
            "BU_CDP_URL": cdp_url,
            "BU_NAME": args.browser_daemon_name,
        }
        reload_before_capture = True
    runner = BrowserHarnessRunner(
        max_attempts=args.max_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
        env=browser_env,
        reload_before_capture=reload_before_capture,
    )
    summary = collect_daily_reddit(
        store,
        run_id=run_id,
        runner=runner,
        subreddits=args.subreddit or DEFAULT_DAILY_SUBREDDITS,
        anchor_utc=parse_anchor_utc(args.anchor_utc),
        window_end_utc=_parse_optional_utc(args.window_end_utc),
        rolling_window_hours=args.rolling_window_hours,
        run_hour=args.run_hour,
        listing_limit=args.listing_limit,
        max_detail_posts=args.max_detail_posts,
        raw_artifact_root=output_dir / "raw-captures",
    )
    artifact = output_dir / f"{run_id}-collector-summary.json"
    artifact.write_text(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**summary.as_dict(), "artifact": str(artifact)}, ensure_ascii=False))
    return 0 if summary.status in {"success", "partial", "empty"} else 1


def tikhub_api_plan_command(args: argparse.Namespace) -> int:
    result = {
        "provider": "tikhub",
        "platform": "reddit",
        "selected_plan": TikHubEndpointPlan().as_dict(),
        "provider_call": False,
        "live_send": False,
        "secret_required_env": "TIKHUB_API_KEY",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_tikhub_collector_command(args: argparse.Namespace) -> int:
    if not args.authorize_provider_call or os.getenv("REDDIT_VOC_ENABLE_TIKHUB") != "1":
        result = {
            "run_id": args.run_id,
            "status": "blocked",
            "reason": "tikhub_provider_call_not_authorized",
            "provider_call": False,
            "live_send": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    api_key = os.getenv("TIKHUB_API_KEY", "").strip()
    if not api_key:
        result = {
            "run_id": args.run_id,
            "status": "blocked",
            "reason": "missing_tikhub_api_key_env",
            "provider_call": False,
            "live_send": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    store = VocStore(args.database)
    store.migrate()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or "daily_collect_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    client = TikHubClient(
        api_key=api_key,
        base_url=os.getenv("TIKHUB_BASE_URL", "https://api.tikhub.io"),
        timeout_seconds=args.timeout_seconds,
    )
    summary = collect_daily_tikhub(
        store,
        run_id=run_id,
        client=client,
        subreddits=args.subreddit or DEFAULT_DAILY_SUBREDDITS,
        search_terms=args.search_term or DEFAULT_TIKHUB_SEARCH_TERMS,
        anchor_utc=parse_anchor_utc(args.anchor_utc),
        window_end_utc=_parse_optional_utc(args.window_end_utc),
        rolling_window_hours=args.rolling_window_hours,
        run_hour=args.run_hour,
        listing_limit=args.listing_limit,
        max_detail_posts=args.max_detail_posts,
        raw_artifact_root=output_dir / "raw-captures",
    )
    artifact = output_dir / f"{run_id}-tikhub-collector-summary.json"
    artifact.write_text(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**summary.as_dict(), "artifact": str(artifact)}, ensure_ascii=False))
    return 0 if summary.status in {"success", "partial", "empty"} else 1


def run_comment_refresh_command(args: argparse.Namespace) -> int:
    from .comment_refresh import build_comment_refresh_source_batch
    from .v2_center import V2CenterStore

    if not args.authorize_provider_call or os.getenv("REDDIT_VOC_ENABLE_TIKHUB") != "1":
        print(json.dumps({"status": "blocked", "reason": "tikhub_provider_call_not_authorized", "provider_call": False, "live_send": False}, ensure_ascii=False))
        return 1
    api_key = os.getenv("TIKHUB_API_KEY", "").strip()
    if not api_key:
        print(json.dumps({"status": "blocked", "reason": "missing_tikhub_api_key_env", "provider_call": False, "live_send": False}, ensure_ascii=False))
        return 1
    start = _parse_optional_utc(args.window_start_utc)
    end = _parse_optional_utc(args.window_end_utc)
    if start is None or end is None:
        raise ValueError("comment refresh window is required")
    center = V2CenterStore(args.center_database)
    client = TikHubClient(
        api_key=api_key,
        base_url=os.getenv("TIKHUB_BASE_URL", "https://api.tikhub.io"),
        timeout_seconds=args.timeout_seconds,
    )
    result = build_comment_refresh_source_batch(
        center,
        client=client,
        run_id=args.run_id,
        window_start_utc=start,
        window_end_utc=end,
        query_profile_path=args.query_profile,
        coverage_profile_path=args.coverage_profile,
        output_root=args.source_batch_root,
        max_active_threads=args.max_active_threads,
    )
    print(json.dumps({
        "manifest_path": str(result.manifest_path),
        "manifest_sha256": result.manifest_sha256,
        "new_comment_ids": list(result.new_comment_ids),
        "observed_comments": result.observed_comments,
        "provider_call": result.write_status != "no_change",
        "status": result.write_status,
        "live_send": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


def run_fixture_loop(args: argparse.Namespace) -> int:
    store = VocStore(args.database)
    store.migrate()

    window = daily_window(anchor=datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc), run_hour=int(os.getenv("REDDIT_VOC_RUN_HOUR", "7")))
    run_id = "fixture_run_20260707"
    store.upsert_run(run_id, "success", window.start_utc.isoformat(), window.end_utc.isoformat())

    raw_payload = json.dumps({"fixture": "browser_json", "post_id": "1fixture"}, sort_keys=True)
    capture = RawCapture(
        raw_capture_id="raw_fixture_1",
        run_id=run_id,
        source_method="manual_json",
        source_url="https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/example/",
        captured_at_utc=datetime.now(timezone.utc),
        auth_boundary="manual_import",
        raw_payload_hash=_hash_text(raw_payload),
        payload_format="json",
    )
    store.insert_raw_capture(capture)

    post_text = "Momcozy M5 vs eufy S1 Pro wearable pump through insurance"
    post_analysis = analyze_text(post_text)
    thread = RedditThread(
        post_id="1fixture",
        run_id=run_id,
        raw_capture_id=capture.raw_capture_id,
        subreddit="ExclusivelyPumping",
        title=post_text,
        selftext="Choosing a secondary wearable pump and worried about leaks.",
        source_url=capture.source_url,
        created_at_utc=datetime(2026, 7, 7, 0, 50, tzinfo=timezone.utc),
        parsed_comment_count=1,
        more_node_count=0,
        coverage_grade="full",
        matched_keywords=post_analysis.keyword_match.matched_terms,
    )
    store.upsert_thread(thread)
    _insert_thread_analysis(store, run_id, thread)

    comment_text = "I returned mine because it kept leaking and customer service was slow."
    comment_analysis = analyze_text(comment_text)
    comment = RedditComment(
        comment_id="t1_fixture",
        post_id=thread.post_id,
        run_id=run_id,
        raw_capture_id=capture.raw_capture_id,
        body=comment_text,
        created_at_utc=datetime(2026, 7, 7, 1, 10, tzinfo=timezone.utc),
        parent_id="t3_1fixture",
        matched_keywords=comment_analysis.keyword_match.matched_terms,
    )
    store.upsert_comment(comment)
    _insert_comment_analysis(store, run_id, comment)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"{run_id}-summary.json"
    summary = {
        "run_id": run_id,
        "provider_call": False,
        "live_send": False,
        "counts": {
            "raw_captures": store.table_count("raw_captures"),
            "threads": store.table_count("reddit_threads"),
            "comments": store.table_count("reddit_comments"),
            "analysis": store.table_count("analysis_results"),
        },
    }
    artifact.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")

    markdown = render_markdown_digest(
        title="Momcozy Reddit VOC Fixture Digest",
        summary_lines=[
            "fixture run completed",
            "provider_call=false",
            "live_send=false",
            f"threads={summary['counts']['threads']}",
            f"comments={summary['counts']['comments']}",
        ],
        artifact_paths=[str(artifact)],
    )
    payload = build_payload(title="Momcozy Reddit VOC Fixture Digest", markdown=markdown)
    store.insert_delivery_preview("delivery_fixture_1", run_id, payload.message_hash, [str(artifact)])

    outbox = output_dir / f"{run_id}-dingtalk-dry-run.json"
    outbox.write_text(json.dumps(payload.body, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({**summary, "artifact": str(artifact), "outbox": str(outbox)}, ensure_ascii=False))
    return 0


def doctor(args: argparse.Namespace) -> int:
    checks = local_doctor(no_network=args.no_network)
    result = {
        "status": "blocked" if has_blocking_preflight_failure(checks) else "ok",
        "no_network": args.no_network,
        "provider_call": False,
        "live_send": False,
        "checks": [check.as_dict() for check in checks],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "blocked" else 0


def reanalyze_run_command(args: argparse.Namespace) -> int:
    import os
    from .collector import _reanalyze_run_with_deepseek

    if not args.authorize_provider_call:
        print(json.dumps({"status": "blocked", "reason": "provider_call_not_authorized"}, ensure_ascii=False))
        return 1
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        print(json.dumps({"status": "blocked", "reason": "DEEPSEEK_API_KEY not set"}, ensure_ascii=False))
        return 1

    store = VocStore(args.database)
    store.migrate()

    run_ids = [args.run_id]

    total_updated = 0
    results = []
    for run_id in run_ids:
        updated = _reanalyze_run_with_deepseek(
            store,
            run_id,
            authorize_provider_call=True,
        )
        total_updated += updated
        results.append({"run_id": run_id, "updated": updated})

    print(json.dumps({
        "status": "ok",
        "runs_processed": len(run_ids),
        "total_updated": total_updated,
        "results": results,
    }, ensure_ascii=False, indent=2))
    return 0


def prepare_daily_report_command(args: argparse.Namespace) -> int:
    # These imports stay command-local so every legacy CLI path remains isolated
    # from the DeepSeek translation runtime.
    from .prepared_bundle import PreparedReportRoots, recover_projection_journal
    from .prepared_report import (
        PreparedAttemptContext,
        build_blocked_translation_attempt,
        preflight_daily_report,
        prepare_daily_report,
        stage_blocked_attempt,
        stage_daily_report,
        write_blocked_attempt,
    )
    from .translation_pipeline import TranslationPipelineBlocked, TranslationService

    roots = PreparedReportRoots(
        public_root=args.public_root,
        private_root=args.private_root,
        public_staging_root=args.public_staging_root,
        private_staging_root=args.private_staging_root,
        state_root=args.state_root,
        blocked_root=args.blocked_root,
        handoff_root=args.handoff_root,
    )
    attempt = PreparedAttemptContext(
        attempt_id=args.attempt_id,
        artifact_version_id=args.artifact_version_id,
    )
    blocked_writer = stage_blocked_attempt if args.defer_host_commit else write_blocked_attempt
    preflight = None
    provider_authorization_id: str | None = None
    pipeline_evidence = None
    provider_attempt_ledger = None
    provider_attempt_lifecycle = None

    try:
        _require_control_id(args.attempt_id, "attempt_id")
        _require_control_id(args.prepare_action_authorization_id, "prepare_action_authorization_id")
        if args.defer_host_commit:
            if (roots.state_root / "prepared-projection-journal.json").exists():
                raise RuntimeError("projection_recovery_required")
        else:
            recover_projection_journal(roots=roots)
        preflight = preflight_daily_report(
            database=args.database,
            run_id=args.run_id,
            roots=roots,
            config_root=args.config_root,
            artifact_base_url=args.artifact_base_url,
            dingtalk_required_keyword=args.dingtalk_required_keyword,
            dingtalk_max_bytes=args.dingtalk_max_bytes,
            dingtalk_max_parts=args.dingtalk_max_parts,
        )
    except Exception as exc:
        return _finish_prepare_blocked(
            roots=roots,
            run_id=args.run_id,
            attempt_id=args.attempt_id,
            preflight=preflight,
            pipeline_evidence=None,
            stage="preflight",
            reason_code=_prepare_reason_code(exc),
            provider_authorization_id=None,
            authorize_failure_alert=args.authorize_failure_alert,
            build_manifest=build_blocked_translation_attempt,
            write_manifest=blocked_writer,
        )

    client = None
    if preflight.provider_phases_required:
        gate_reason = _provider_gate_reason(args)
        if gate_reason is not None:
            return _finish_prepare_blocked(
                roots=roots,
                run_id=args.run_id,
                attempt_id=args.attempt_id,
                preflight=preflight,
                pipeline_evidence=None,
                stage="gate",
                reason_code=gate_reason,
                provider_authorization_id=None,
                authorize_failure_alert=args.authorize_failure_alert,
                build_manifest=build_blocked_translation_attempt,
                write_manifest=blocked_writer,
            )
        try:
            provider_authorization_id = _require_control_id(
                args.provider_authorization_id,
                "provider_authorization_id",
            )
            release_sha256 = _provider_runtime_release_sha256(
                config_root=args.config_root
            )
            provider_attempt_ledger, provider_attempt_lifecycle = (
                _create_provider_attempt_lifecycle(
                    root=args.provider_attempt_root,
                    provider_authorization_id=provider_authorization_id,
                    run_id=args.run_id,
                    attempt_id=args.attempt_id,
                    release_sha256=release_sha256,
                )
            )
            if provider_attempt_ledger.path.exists():
                provider_attempt_lifecycle.close_incomplete()
                raise RuntimeError("provider_attempt_ledger_exists")
            api_key = _read_deepseek_key()
            # The Provider module is imported only after the source/config/cache
            # preflight and every explicit authorization gate has passed.
            from .deepseek_client import DeepSeekClient

            client = DeepSeekClient(
                api_key=api_key,
                attempt_lifecycle_sink=provider_attempt_lifecycle,
            )
            del api_key
            translator = TranslationService(
                client=client,
                assets=preflight.translation_assets,
            )
        except Exception as exc:
            return _finish_prepare_blocked(
                roots=roots,
                run_id=args.run_id,
                attempt_id=args.attempt_id,
                preflight=preflight,
                pipeline_evidence=None,
                stage="key_metadata",
                reason_code=_prepare_reason_code(exc),
                provider_authorization_id=provider_authorization_id,
                authorize_failure_alert=args.authorize_failure_alert,
                build_manifest=build_blocked_translation_attempt,
                write_manifest=blocked_writer,
                provider_attempt_ledger=provider_attempt_ledger,
                provider_attempt_lifecycle=provider_attempt_lifecycle,
            )
    else:
        translator = TranslationService(client=None, assets=preflight.translation_assets)
        provider_authorization_id = None

    try:
        if args.defer_host_commit:
            prepared = stage_daily_report(
                preflight,
                attempt=attempt,
                translator=translator,
                roots=roots,
                provider_authorization_id=provider_authorization_id,
                prepare_action_authorization_id=args.prepare_action_authorization_id,
                provider_attempt_ledger=provider_attempt_ledger,
            )
            private_dir = prepared.staged_private_dir
            current_advanced = False
        else:
            prepared = prepare_daily_report(
                preflight,
                attempt=attempt,
                translator=translator,
                roots=roots,
                provider_authorization_id=provider_authorization_id,
                prepare_action_authorization_id=args.prepare_action_authorization_id,
                provider_attempt_ledger=provider_attempt_ledger,
            )
            private_dir = prepared.private_dir
            current_advanced = True
    except TranslationPipelineBlocked as exc:
        pipeline_evidence = exc
        return _finish_prepare_blocked(
            roots=roots,
            run_id=args.run_id,
            attempt_id=args.attempt_id,
            preflight=preflight,
            pipeline_evidence=pipeline_evidence,
            stage="pipeline",
            reason_code=exc.reason_codes[0] if exc.reason_codes else "translation_pipeline_blocked",
            provider_authorization_id=provider_authorization_id,
            authorize_failure_alert=args.authorize_failure_alert,
            build_manifest=build_blocked_translation_attempt,
            write_manifest=blocked_writer,
            provider_attempt_ledger=provider_attempt_ledger,
            provider_attempt_lifecycle=provider_attempt_lifecycle,
        )
    except Exception as exc:
        return _finish_prepare_blocked(
            roots=roots,
            run_id=args.run_id,
            attempt_id=args.attempt_id,
            preflight=preflight,
            pipeline_evidence=pipeline_evidence,
            stage="staging" if args.defer_host_commit else "commit",
            reason_code=_prepare_reason_code(exc),
            provider_authorization_id=provider_authorization_id,
            authorize_failure_alert=args.authorize_failure_alert,
            build_manifest=build_blocked_translation_attempt,
            write_manifest=blocked_writer,
            provider_attempt_ledger=provider_attempt_ledger,
            provider_attempt_lifecycle=provider_attempt_lifecycle,
        )

    manifest_path = private_dir / "translation-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = {
        "status": "complete",
        "run_id": prepared.run_id,
        "attempt_id": prepared.attempt_id,
        "artifact_version_id": prepared.artifact_version_id,
        "bundle_sha256": prepared.bundle_sha256,
        "outbox_sha256": prepared.outbox_sha256,
        "report_input_fingerprint": prepared.report_input_fingerprint,
        "commit_request_sha256": getattr(prepared, "commit_request_sha256", None),
        "provider_authorization_id": prepared.provider_authorization_id,
        "prepare_action_authorization_id": prepared.prepare_action_authorization_id,
        "provider_phases_required": list(preflight.provider_phases_required),
        "translation_provider_call": bool(manifest["translation_provider_call"]),
        "translation_provider_attempt_made": bool(
            manifest["translation_provider_attempt_made"]
        ),
        "translation_phase_attempt_made": bool(
            manifest["translation_phase_attempt_made"]
        ),
        "semantic_validation_phase_attempt_made": bool(
            manifest["semantic_validation_phase_attempt_made"]
        ),
        "translation_reused": bool(manifest["translation_reused"]),
        "semantic_validation_reused": bool(manifest["semantic_validation_reused"]),
        "provider_attempt_made": bool(manifest["translation_provider_attempt_made"]),
        "current_advanced": current_advanced,
        "report_live_send": False,
        "failure_alert_status": "not_applicable",
        "alert_live_send": False,
        "live_send": False,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _provider_gate_reason(args: argparse.Namespace) -> str | None:
    if os.getenv("REDDIT_VOC_TRANSLATION_MODE") != "deepseek":
        return "translation_mode_not_deepseek"
    if os.getenv("REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION") != "1":
        return "deepseek_translation_not_enabled"
    if not args.authorize_provider_call:
        return "provider_call_not_authorized"
    if not isinstance(args.provider_authorization_id, str) or not args.provider_authorization_id:
        return "provider_authorization_id_required"
    if _SAFE_CONTROL_ID.fullmatch(args.provider_authorization_id) is None:
        return "provider_authorization_id_invalid"
    return None


def _prepare_reason_code(error: BaseException) -> str:
    candidate = getattr(error, "reason_code", None)
    if isinstance(candidate, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", candidate):
        return candidate
    message = str(error)
    if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", message):
        return message
    return "prepare_daily_report_failed"


def _finish_prepare_blocked(
    *,
    roots,
    run_id: str,
    attempt_id: str,
    preflight,
    pipeline_evidence,
    stage: str,
    reason_code: str,
    provider_authorization_id: str | None,
    authorize_failure_alert: bool,
    build_manifest,
    write_manifest,
    provider_attempt_ledger=None,
    provider_attempt_lifecycle=None,
) -> int:
    if provider_attempt_lifecycle is not None:
        provider_attempt_lifecycle.close_incomplete()
    manifest = build_manifest(
        run_id=run_id,
        attempt_id=attempt_id,
        preflight=preflight,
        pipeline_evidence=pipeline_evidence,
        stage=stage,
        reason_codes=[reason_code],
        provider_authorization_id=provider_authorization_id,
        provider_attempt_ledger=provider_attempt_ledger,
    )
    path = write_manifest(
        roots=roots,
        run_id=run_id,
        attempt_id=attempt_id,
        manifest=manifest,
    )
    failure_alert_status = "failure_alert_not_authorized"
    alert_live_send = False
    deferred_to_host = Path(path).is_relative_to(roots.handoff_root)
    if deferred_to_host:
        failure_alert_status = "deferred_to_host"
    elif authorize_failure_alert:
        if os.getenv("REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT") != "1":
            failure_alert_status = "failure_alert_not_enabled"
        else:
            webhook_url = os.getenv("DINGTALK_WEBHOOK_URL", "")
            if not webhook_url:
                failure_alert_status = "failure_alert_webhook_missing"
            else:
                from .daily_report_delivery import send_report_failure_alert

                alert_summary = send_report_failure_alert(
                    roots=roots,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    stage=stage,
                    reason_code=reason_code,
                    occurred_at=datetime.now(timezone.utc),
                    webhook_url=webhook_url,
                    webhook_secret=os.getenv("DINGTALK_WEBHOOK_SECRET") or None,
                    timeout_seconds=10,
                    authorize_failure_alert=True,
                    transport=_prepared_delivery_transport(),
                )
                failure_alert_status = alert_summary.status
                alert_live_send = alert_summary.alert_live_send
    result = {
        "status": "blocked",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "stage": stage,
        "reason_codes": [reason_code],
        "blocked_manifest": str(path),
        "blocked_manifest_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "provider_authorization_id": provider_authorization_id,
        "translation_provider_call": bool(manifest["translation_provider_call"]),
        "translation_provider_attempt_made": bool(
            manifest["translation_provider_attempt_made"]
        ),
        "provider_attempt_made": bool(manifest["translation_provider_attempt_made"]),
        "current_advanced": False,
        "report_live_send": False,
        "failure_alert_status": failure_alert_status,
        "alert_live_send": alert_live_send,
        "live_send": alert_live_send,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1


def send_prepared_daily_report_command(args: argparse.Namespace) -> int:
    gate_reason = None
    if os.getenv("REDDIT_VOC_DINGTALK_MODE") != "live":
        gate_reason = "dingtalk_mode_not_live"
    elif os.getenv("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND") != "1":
        gate_reason = "dingtalk_live_send_not_enabled"
    elif not args.authorize_live_send:
        gate_reason = "live_send_not_authorized"
    elif not isinstance(args.authorization_id, str) or _SAFE_CONTROL_ID.fullmatch(
        args.authorization_id
    ) is None:
        gate_reason = "authorization_id_invalid"
    elif args.authorize_resend and not args.resend_part_index:
        gate_reason = "resend_part_index_required"
    elif args.resend_part_index and not args.authorize_resend:
        gate_reason = "resend_not_authorized"
    if gate_reason is not None:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": gate_reason,
                    "run_id": args.run_id,
                    "report_live_send": False,
                    "alert_live_send": False,
                    "live_send": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    # Keep this import command-local. The delivery graph has no renderer,
    # translation pipeline or DeepSeek dependency.
    from .daily_report_delivery import send_prepared_daily_report
    from .prepared_bundle import PreparedReportRoots

    unused_root = args.state_root / ".delivery-unused"
    roots = PreparedReportRoots(
        public_root=args.public_root,
        private_root=args.private_root,
        public_staging_root=unused_root / "public-staging",
        private_staging_root=unused_root / "private-staging",
        state_root=args.state_root,
        blocked_root=unused_root / "blocked",
        handoff_root=unused_root / "handoff",
    )
    try:
        summary = send_prepared_daily_report(
            database=args.database,
            run_id=args.run_id,
            expected_artifact_version_id=args.expected_artifact_version_id,
            expected_bundle_sha256=args.expected_bundle_sha256,
            expected_outbox_sha256=args.expected_outbox_sha256,
            authorization_id=args.authorization_id,
            roots=roots,
            config_root=args.config_root,
            webhook_url="",
            webhook_secret=None,
            webhook_url_2="",
            webhook_secret_2=None,
            timeout_seconds=args.timeout_seconds,
            authorize_live_send=True,
            authorize_resend=args.authorize_resend,
            resend_part_indexes=tuple(args.resend_part_index or ()),
            head_checker=_prepared_artifact_head_checker(),
            transport=_prepared_delivery_transport(),
            credential_loader=_prepared_dingtalk_credentials,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": _prepare_reason_code(exc),
                    "run_id": args.run_id,
                    "report_live_send": bool(
                        getattr(exc, "external_attempt_made", False)
                    ),
                    "alert_live_send": False,
                    "live_send": bool(getattr(exc, "external_attempt_made", False)),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if summary.status == "sent" else 1


def send_prepared_daily_report_dual_command(args: argparse.Namespace) -> int:
    gate_reason = None
    if os.getenv("REDDIT_VOC_DINGTALK_MODE") != "live":
        gate_reason = "dingtalk_mode_not_live"
    elif os.getenv("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND") != "1":
        gate_reason = "dingtalk_live_send_not_enabled"
    elif not args.authorize_live_send:
        gate_reason = "live_send_not_authorized"
    elif not isinstance(args.authorization_id, str) or _SAFE_CONTROL_ID.fullmatch(
        args.authorization_id
    ) is None:
        gate_reason = "authorization_id_invalid"
    elif args.authorize_resend and not args.resend_part_index:
        gate_reason = "resend_part_index_required"
    elif args.resend_part_index and not args.authorize_resend:
        gate_reason = "resend_not_authorized"
    if gate_reason is not None:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": gate_reason,
                    "run_id": args.run_id,
                    "destinations": [],
                    "report_live_send": False,
                    "alert_live_send": False,
                    "live_send": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    from .daily_report_delivery import send_prepared_daily_report_to_destinations
    from .prepared_bundle import PreparedReportRoots

    unused_root = args.state_root / ".delivery-unused"
    roots = PreparedReportRoots(
        public_root=args.public_root,
        private_root=args.private_root,
        public_staging_root=unused_root / "public-staging",
        private_staging_root=unused_root / "private-staging",
        state_root=args.state_root,
        blocked_root=unused_root / "blocked",
        handoff_root=unused_root / "handoff",
    )
    try:
        summary = send_prepared_daily_report_to_destinations(
            database=args.database,
            run_id=args.run_id,
            expected_artifact_version_id=args.expected_artifact_version_id,
            expected_bundle_sha256=args.expected_bundle_sha256,
            expected_outbox_sha256=args.expected_outbox_sha256,
            authorization_id=args.authorization_id,
            roots=roots,
            config_root=args.config_root,
            timeout_seconds=args.timeout_seconds,
            authorize_live_send=True,
            authorize_resend=args.authorize_resend,
            resend_part_indexes=tuple(args.resend_part_index or ()),
            head_checker=_prepared_artifact_head_checker(),
            transport=_prepared_delivery_transport(),
            credential_loader=_prepared_dingtalk_destination_credentials,
        )
    except Exception as exc:
        live_send = bool(getattr(exc, "external_attempt_made", False))
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": _prepare_reason_code(exc),
                    "run_id": args.run_id,
                    "destinations": [],
                    "report_live_send": live_send,
                    "alert_live_send": False,
                    "live_send": live_send,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if summary.status == "sent" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reddit-voc")
    _add_common_args(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init-local", help="Initialize local directories and SQLite schema")
    _add_common_args(init_parser)
    loop_parser = subparsers.add_parser("run-fixture-loop", help="Run a no-network local fixture loop")
    _add_common_args(loop_parser)
    adapter_loop_parser = subparsers.add_parser("run-adapter-fixture-loop", help="Run a no-network adapter fixture loop")
    _add_common_args(adapter_loop_parser)
    adapter_loop_parser.add_argument("--fixture", type=Path, default=None)
    adapter_loop_parser.add_argument("--run-id", default=None)
    export_parser = subparsers.add_parser("export-run", help="Export posts/comments JSONL and CSV for a local run")
    _add_common_args(export_parser)
    export_parser.add_argument("--run-id", required=True)
    daily_source_batch_parser = subparsers.add_parser(
        "build-daily-source-batch",
        help="Build an immutable SourceBatch v1 from one completed daily collector run",
    )
    _add_common_args(daily_source_batch_parser)
    daily_source_batch_parser.add_argument("--run-id", required=True)
    daily_source_batch_parser.add_argument("--collector-summary", type=Path, default=None)
    daily_source_batch_parser.add_argument("--raw-artifact-root", type=Path, default=None)
    daily_source_batch_parser.add_argument("--source-batch-root", type=Path, default=None)
    daily_source_batch_parser.add_argument(
        "--query-profile",
        type=Path,
        default=Path("config/source-batch/momcozy-query-v2.json"),
    )
    daily_source_batch_parser.add_argument(
        "--coverage-profile",
        type=Path,
        default=Path("config/source-batch/momcozy-coverage-v2.json"),
    )
    schema_migration_parser = subparsers.add_parser(
        "migrate-database-schema",
        help="Explicitly migrate an offline SQLite database with backup and rollback evidence",
    )
    schema_migration_parser.add_argument("--database", type=Path, required=True)
    schema_migration_parser.add_argument("--expected-database-sha256", required=True)
    schema_migration_parser.add_argument("--backup-path", type=Path, required=True)
    schema_migration_parser.add_argument("--rollback-path", type=Path, required=True)
    schema_migration_parser.add_argument("--authorization-id", required=True)
    schema_migration_parser.add_argument(
        "--authorize-schema-migration", action="store_true", required=True
    )
    backfill_source_batch_parser = subparsers.add_parser(
        "build-backfill-source-batch",
        help="Build an immutable SourceBatch v1 from one historical backfill run",
    )
    _add_common_args(backfill_source_batch_parser)
    backfill_source_batch_parser.add_argument("--run-id", required=True)
    backfill_source_batch_parser.add_argument("--archive-root", type=Path, required=True)
    backfill_source_batch_parser.add_argument("--source-batch-root", type=Path, default=None)
    status_parser = subparsers.add_parser("status-summary", help="Summarize one local run as success, partial, empty, or failed")
    _add_common_args(status_parser)
    status_parser.add_argument("--run-id", required=True)
    issue_parser = subparsers.add_parser("issue-summary", help="Summarize local run operational issues")
    _add_common_args(issue_parser)
    issue_parser.add_argument("--run-id", required=True)
    missed_parser = subparsers.add_parser("missed-run-check", help="Check whether the expected daily window has a local run")
    _add_common_args(missed_parser)
    missed_parser.add_argument("--anchor-utc", default=None)
    missed_parser.add_argument("--timezone", default="Asia/Shanghai")
    missed_parser.add_argument("--run-hour", type=int, default=int(os.getenv("REDDIT_VOC_RUN_HOUR", "7")))
    prune_parser = subparsers.add_parser("prune-artifacts", help="Prune local artifacts or logs by newest-file count")
    prune_parser.add_argument("--path", action="append", type=Path, required=True)
    prune_parser.add_argument("--pattern", action="append", default=None)
    prune_parser.add_argument("--keep-last", type=int, required=True)
    prune_parser.add_argument("--apply", action="store_true", default=False)
    profile_init_parser = subparsers.add_parser("browser-profile-init", help="Create a dedicated local Chrome user-data-dir outside the repo")
    profile_init_parser.add_argument("--profile-dir", type=Path, default=None)
    profile_status_parser = subparsers.add_parser("browser-profile-status", help="Inspect dedicated Chrome profile readiness without reading cookies")
    profile_status_parser.add_argument("--profile-dir", type=Path, default=None)
    profile_launch_parser = subparsers.add_parser("browser-profile-launch-command", help="Print the Chrome launch command for manual Reddit login")
    profile_launch_parser.add_argument("--profile-dir", type=Path, default=None)
    profile_launch_parser.add_argument("--start-url", default="https://www.reddit.com/login/")
    profile_launch_parser.add_argument("--remote-debug-port", type=int, default=None)
    dingtalk_parser = subparsers.add_parser("build-dingtalk-dry-run", help="Build DingTalk Markdown body without sending")
    _add_common_args(dingtalk_parser)
    dingtalk_parser.add_argument("--run-id", required=True)
    dingtalk_parser.add_argument("--artifact-base-url", default=None)
    daily_report_parser = subparsers.add_parser(
        "build-daily-report",
        help="Build Chinese daily detail table, insight image, and DingTalk dry-run body without provider or live send",
    )
    _add_common_args(daily_report_parser)
    daily_report_parser.add_argument("--run-id", required=True)
    daily_report_parser.add_argument("--translation-mode", default=None)
    daily_report_parser.add_argument("--artifact-base-url", default=None)
    daily_report_parser.add_argument("--required-keyword", default=None)
    prepared_report_parser = subparsers.add_parser(
        "prepare-daily-report",
        help="Prepare an immutable Chinese-first daily report under explicit DeepSeek gates without sending",
    )
    prepared_report_parser.add_argument("--database", type=Path, required=True)
    prepared_report_parser.add_argument("--run-id", required=True)
    prepared_report_parser.add_argument("--attempt-id", required=True)
    prepared_report_parser.add_argument("--artifact-version-id", required=True)
    prepared_report_parser.add_argument("--public-root", type=Path, required=True)
    prepared_report_parser.add_argument("--private-root", type=Path, required=True)
    prepared_report_parser.add_argument("--public-staging-root", type=Path, required=True)
    prepared_report_parser.add_argument("--private-staging-root", type=Path, required=True)
    prepared_report_parser.add_argument("--state-root", type=Path, required=True)
    prepared_report_parser.add_argument("--blocked-root", type=Path, required=True)
    prepared_report_parser.add_argument("--handoff-root", type=Path, required=True)
    prepared_report_parser.add_argument("--provider-attempt-root", type=Path, required=True)
    prepared_report_parser.add_argument("--config-root", type=Path, required=True)
    prepared_report_parser.add_argument("--artifact-base-url", required=True)
    prepared_report_parser.add_argument("--dingtalk-required-keyword", required=True)
    prepared_report_parser.add_argument("--dingtalk-max-bytes", type=int, required=True)
    prepared_report_parser.add_argument("--dingtalk-max-parts", type=int, default=2)
    prepared_report_parser.add_argument(
        "--authorize-provider-call", action="store_true", default=False
    )
    prepared_report_parser.add_argument("--provider-authorization-id", default=None)
    prepared_report_parser.add_argument(
        "--prepare-action-authorization-id", default=None
    )
    prepared_report_parser.add_argument(
        "--defer-host-commit", action="store_true", default=False
    )
    prepared_report_parser.add_argument(
        "--authorize-failure-alert", action="store_true", default=False
    )
    send_prepared_parser = subparsers.add_parser(
        "send-prepared-daily-report",
        help="Send only a verified immutable prepared report under explicit DingTalk gates",
    )
    send_prepared_parser.add_argument("--database", type=Path, required=True)
    send_prepared_parser.add_argument("--run-id", required=True)
    send_prepared_parser.add_argument(
        "--expected-artifact-version-id", required=True
    )
    send_prepared_parser.add_argument("--expected-bundle-sha256", required=True)
    send_prepared_parser.add_argument("--expected-outbox-sha256", required=True)
    send_prepared_parser.add_argument("--authorization-id", required=True)
    send_prepared_parser.add_argument("--public-root", type=Path, required=True)
    send_prepared_parser.add_argument("--private-root", type=Path, required=True)
    send_prepared_parser.add_argument("--state-root", type=Path, required=True)
    send_prepared_parser.add_argument("--config-root", type=Path, required=True)
    send_prepared_parser.add_argument("--timeout-seconds", type=int, default=10)
    send_prepared_parser.add_argument(
        "--authorize-live-send", action="store_true", default=False
    )
    send_prepared_parser.add_argument(
        "--authorize-resend", action="store_true", default=False
    )
    send_prepared_parser.add_argument(
        "--resend-part-index", action="append", type=int, default=None
    )
    send_prepared_dual_parser = subparsers.add_parser(
        "send-prepared-daily-report-dual",
        help=(
            "Send one verified immutable prepared report to exactly two "
            "independently ledgered DingTalk destinations"
        ),
    )
    send_prepared_dual_parser.add_argument("--database", type=Path, required=True)
    send_prepared_dual_parser.add_argument("--run-id", required=True)
    send_prepared_dual_parser.add_argument(
        "--expected-artifact-version-id", required=True
    )
    send_prepared_dual_parser.add_argument(
        "--expected-bundle-sha256", required=True
    )
    send_prepared_dual_parser.add_argument(
        "--expected-outbox-sha256", required=True
    )
    send_prepared_dual_parser.add_argument("--authorization-id", required=True)
    send_prepared_dual_parser.add_argument(
        "--public-root", type=Path, required=True
    )
    send_prepared_dual_parser.add_argument(
        "--private-root", type=Path, required=True
    )
    send_prepared_dual_parser.add_argument(
        "--state-root", type=Path, required=True
    )
    send_prepared_dual_parser.add_argument(
        "--config-root", type=Path, required=True
    )
    send_prepared_dual_parser.add_argument(
        "--timeout-seconds", type=int, default=10
    )
    send_prepared_dual_parser.add_argument(
        "--authorize-live-send", action="store_true", default=False
    )
    send_prepared_dual_parser.add_argument(
        "--authorize-resend", action="store_true", default=False
    )
    send_prepared_dual_parser.add_argument(
        "--resend-part-index", action="append", type=int, default=None
    )
    daily_report_live_parser = subparsers.add_parser(
        "send-daily-report-live",
        help="Send Chinese daily report to DingTalk only with explicit live-send gate",
    )
    _add_common_args(daily_report_live_parser)
    daily_report_live_parser.add_argument("--run-id", required=True)
    daily_report_live_parser.add_argument("--translation-mode", default=None)
    daily_report_live_parser.add_argument("--artifact-base-url", default=None)
    daily_report_live_parser.add_argument("--required-keyword", default=None)
    daily_report_live_parser.add_argument("--timeout-seconds", type=int, default=10)
    daily_report_live_parser.add_argument("--authorize-live-send", action="store_true", default=False)
    live_parser = subparsers.add_parser("send-dingtalk-live", help="Send DingTalk Markdown body only with explicit live-send gate")
    _add_common_args(live_parser)
    live_parser.add_argument("--run-id", required=True)
    live_parser.add_argument("--required-keyword", default=None)
    live_parser.add_argument("--timeout-seconds", type=int, default=10)
    live_parser.add_argument("--authorize-live-send", action="store_true", default=False)
    live_parser.add_argument("--artifact-base-url", default=None)
    browser_smoke_parser = subparsers.add_parser(
        "run-browser-json-smoke",
        help="Run browser-harness read-only .json smoke; write summary/hash/count artifact plus parsed SQLite rows",
    )
    _add_common_args(browser_smoke_parser)
    browser_smoke_parser.add_argument("--url", required=True)
    browser_smoke_parser.add_argument("--run-id", default=None)
    browser_smoke_parser.add_argument("--browser-cdp-url", default=None)
    browser_smoke_parser.add_argument("--browser-daemon-name", default="reddit-voc-profile")
    browser_smoke_parser.add_argument("--max-attempts", type=int, default=1)
    browser_smoke_parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    daily_collect_parser = subparsers.add_parser(
        "run-daily-collector",
        help="Run read-only daily Reddit listing discovery and post-detail ingestion for the 07:00 Asia/Shanghai window",
    )
    _add_common_args(daily_collect_parser)
    daily_collect_parser.add_argument("--run-id", default=None)
    daily_collect_parser.add_argument("--anchor-utc", default=None)
    daily_collect_parser.add_argument("--window-end-utc", default=None)
    daily_collect_parser.add_argument("--rolling-window-hours", type=int, default=int(os.getenv("REDDIT_VOC_ROLLING_WINDOW_HOURS", "24")))
    daily_collect_parser.add_argument("--run-hour", type=int, default=int(os.getenv("REDDIT_VOC_RUN_HOUR", "7")))
    daily_collect_parser.add_argument("--subreddit", action="append", default=None)
    daily_collect_parser.add_argument("--listing-limit", type=int, default=100)
    daily_collect_parser.add_argument("--max-detail-posts", type=int, default=50)
    daily_collect_parser.add_argument("--browser-cdp-url", default=None)
    daily_collect_parser.add_argument("--browser-daemon-name", default="reddit-voc-profile")
    daily_collect_parser.add_argument("--max-attempts", type=int, default=1)
    daily_collect_parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    tikhub_plan_parser = subparsers.add_parser("tikhub-api-plan", help="Show selected TikHub Reddit API plan without provider call")
    _add_common_args(tikhub_plan_parser)
    tikhub_collect_parser = subparsers.add_parser("run-tikhub-collector", help="Run authorized TikHub Reddit collector for the daily 07:00 Asia/Shanghai window")
    _add_common_args(tikhub_collect_parser)
    tikhub_collect_parser.add_argument("--run-id", default=None)
    tikhub_collect_parser.add_argument("--anchor-utc", default=None)
    tikhub_collect_parser.add_argument("--window-end-utc", default=None)
    tikhub_collect_parser.add_argument("--rolling-window-hours", type=int, default=int(os.getenv("REDDIT_VOC_ROLLING_WINDOW_HOURS", "24")))
    tikhub_collect_parser.add_argument("--run-hour", type=int, default=int(os.getenv("REDDIT_VOC_RUN_HOUR", "7")))
    tikhub_collect_parser.add_argument("--subreddit", action="append", default=None)
    tikhub_collect_parser.add_argument("--search-term", action="append", default=None)
    tikhub_collect_parser.add_argument("--listing-limit", type=int, default=100)
    tikhub_collect_parser.add_argument("--max-detail-posts", type=int, default=30)
    tikhub_collect_parser.add_argument("--timeout-seconds", type=int, default=30)
    tikhub_collect_parser.add_argument("--authorize-provider-call", action="store_true", default=False)
    refresh_parser = subparsers.add_parser(
        "run-comment-refresh",
        help="Refresh comments for the rotating V2 active-thread registry and emit one SourceBatch",
    )
    refresh_parser.add_argument("--center-database", type=Path, required=True)
    refresh_parser.add_argument("--source-batch-root", type=Path, required=True)
    refresh_parser.add_argument("--run-id", required=True)
    refresh_parser.add_argument("--window-start-utc", required=True)
    refresh_parser.add_argument("--window-end-utc", required=True)
    refresh_parser.add_argument("--query-profile", type=Path, required=True)
    refresh_parser.add_argument("--coverage-profile", type=Path, required=True)
    refresh_parser.add_argument("--max-active-threads", type=int, default=100)
    refresh_parser.add_argument("--timeout-seconds", type=int, default=30)
    refresh_parser.add_argument("--authorize-provider-call", action="store_true", default=False)
    doctor_parser = subparsers.add_parser("doctor", help="Run local preflight checks")
    _add_common_args(doctor_parser)
    doctor_parser.add_argument("--no-network", action="store_true", default=False)
    reanalyze_parser = subparsers.add_parser("reanalyze-run", help="Re-analyze one run's posts and comments with an explicitly authorized DeepSeek call")
    _add_common_args(reanalyze_parser)
    reanalyze_parser.add_argument("--run-id", required=True, help="Run ID to reanalyze")
    reanalyze_parser.add_argument("--authorize-provider-call", action="store_true", default=False)
    args = _apply_defaults(parser.parse_args(argv))

    if args.command == "init-local":
        return init_project(args)
    if args.command == "run-fixture-loop":
        return run_fixture_loop(args)
    if args.command == "run-adapter-fixture-loop":
        return run_adapter_fixture_loop(args)
    if args.command == "export-run":
        return export_run_command(args)
    if args.command == "build-daily-source-batch":
        return build_daily_source_batch_command(args)
    if args.command == "migrate-database-schema":
        return migrate_database_schema_command(args)
    if args.command == "build-backfill-source-batch":
        return build_backfill_source_batch_command(args)
    if args.command == "status-summary":
        return status_summary_command(args)
    if args.command == "issue-summary":
        return run_issue_summary_command(args)
    if args.command == "missed-run-check":
        return missed_run_check_command(args)
    if args.command == "prune-artifacts":
        return prune_artifacts_command(args)
    if args.command == "browser-profile-init":
        return browser_profile_init_command(args)
    if args.command == "browser-profile-status":
        return browser_profile_status_command(args)
    if args.command == "browser-profile-launch-command":
        return browser_profile_launch_command(args)
    if args.command == "build-dingtalk-dry-run":
        return build_dingtalk_dry_run_command(args)
    if args.command == "build-daily-report":
        return build_daily_report_command(args)
    if args.command == "prepare-daily-report":
        return prepare_daily_report_command(args)
    if args.command == "send-prepared-daily-report":
        return send_prepared_daily_report_command(args)
    if args.command == "send-prepared-daily-report-dual":
        return send_prepared_daily_report_dual_command(args)
    if args.command == "send-daily-report-live":
        return send_daily_report_live_command(args)
    if args.command == "send-dingtalk-live":
        return send_dingtalk_live_command(args)
    if args.command == "run-browser-json-smoke":
        return run_browser_json_smoke(args)
    if args.command == "run-daily-collector":
        return run_daily_collector_command(args)
    if args.command == "tikhub-api-plan":
        return tikhub_api_plan_command(args)
    if args.command == "run-tikhub-collector":
        return run_tikhub_collector_command(args)
    if args.command == "run-comment-refresh":
        return run_comment_refresh_command(args)
    if args.command == "doctor":
        return doctor(args)
    if args.command == "reanalyze-run":
        return reanalyze_run_command(args)
    raise ValueError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
