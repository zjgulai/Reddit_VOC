#!/usr/bin/env python3
"""Echo-Agent Daily T-1 Pipeline Orchestrator.

One command runs the full daily cycle end-to-end with structured step receipts:
  Step 1  collect_daily_apify       -> real T-1 posts + comments into SQLite
  Step 2  AgentBatchRunner          -> 3 business JSON artifacts (ideas/R&D/competitor)
  Step 3  incremental snapshot      -> merge new corpus into public datasets, rehash manifests
  Step 4  advance_daily_t1_release  -> atomically bump current-release.json
  Step 5  Feishu daily card         -> push report card with Agent highlights to group chat

Every step emits a JSON receipt; any failure fails the pipeline with a
structured error so systemd + Feishu alerting can pick it up.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import traceback
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
PIPELINE_SCHEMA = "echo_agent_daily_pipeline_receipt_v1"


def _shanghai_now() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def _t1_bounds() -> tuple[datetime, datetime, str, str]:
    """Return (window_start_utc, window_end_utc, run_id, report_date) for latest closed T-1."""
    now_utc = datetime.now(timezone.utc)
    close = now_utc.replace(hour=23, minute=0, second=0, microsecond=0)
    if close > now_utc:
        close -= timedelta(days=1)
    window_end = close
    window_start = close - timedelta(days=1)
    sh_now = _shanghai_now()
    report_date = sh_now.strftime("%Y-%m-%d")
    run_id = f"daily_collect_{sh_now:%Y%m%d}_0700"
    return window_start, window_end, run_id, report_date


def step1_collect(store_path: Path, run_id: str) -> dict:
    """Step 1: Apify collection into SQLite."""
    from reddit_voc.storage import VocStore
    from reddit_voc.apify_collector import ApifyRedditClient, collect_daily_apify

    store = VocStore(store_path)
    store.migrate()

    # `maxItems` is a GLOBAL budget for the whole actor run, not a per-query cap:
    # the previous maxItems=25 meant the entire daily collection was 25 items,
    # which is why rolling VOC counts sat in the single digits. Brand and category
    # searches out-yield `r/<sub>` queries under a shared budget, so they carry it.
    summary = collect_daily_apify(
        store=store,
        run_id=run_id,
        subreddits=[],
        search_terms=[
            "Momcozy",
            "Momcozy M5",
            "Momcozy M9",
            "Momcozy S12",
            "Elvie",
            "Willow pump",
            "Spectra pump",
            "Medela pump",
            "wearable breast pump",
            "pumping at work",
            "flange size",
            "milk supply",
        ],
        max_items_per_query=600,
        max_comments_per_post=30,
        # Depth knobs (see collector comment): block until yesterday so older items
        # do not eat the shared budget, and let each page scroll long enough to
        # reach past the newest slice.
        scroll_timeout_seconds=150,
        post_date_limit=(datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    return {
        "step": "collect",
        "status": summary.status,
        "run_id": summary.run_id,
        "discovered_posts": summary.discovered_posts,
        "ingested_threads": summary.ingested_threads,
        "ingested_comments": summary.ingested_comments,
        "issues": summary.issues,
    }


def _verify_agent_evidence(batch, posts) -> dict:
    """Drop any agent quote that does not appear in the post it cites.

    Returns a receipt so the run records how much evidence survived, and so a
    regression (quotes silently disappearing, or fabricated ones reappearing)
    is visible without reading the artifacts by hand.
    """
    from dataclasses import is_dataclass, replace

    from reddit_voc.agents.evidence import verify_quote

    def _null_quote(item, field: str):
        """Return `item` with `field` cleared, tolerating frozen and plain objects."""
        if is_dataclass(item):
            return replace(item, **{field: None})
        try:
            setattr(item, field, None)
            return item
        except (AttributeError, TypeError):
            return item

    source_by_id: dict[str, str] = {}
    for post in posts:
        if isinstance(post, dict):
            pid = str(post.get("post_id") or "")
            title = post.get("title") or ""
            body = post.get("selftext") or ""
        else:
            pid = str(getattr(post, "post_id", "") or "")
            title = getattr(post, "title", "") or ""
            body = getattr(post, "selftext", "") or ""
        if pid:
            source_by_id[pid] = f"{title}\n{body}"

    checked = 0
    dropped = 0
    absent_examples: list[dict] = []

    def _scrub(records, quote_field: str):
        """Null out unverifiable quotes, rebuilding the frozen dataclass in place."""
        nonlocal checked, dropped
        scrubbed = []
        for record in records:
            source = source_by_id.get(str(record.source_post_id), "")
            changed = False
            replacements = []
            for item in (record.comparisons if quote_field == "user_verbatim_quote" else record.defects):
                quote = getattr(item, quote_field, None)
                if not quote:
                    replacements.append(item)
                    continue
                checked += 1
                verdict = verify_quote(quote, source)
                if verdict["status"] != "verified":
                    dropped += 1
                    if len(absent_examples) < 5:
                        absent_examples.append({
                            "post_id": record.source_post_id,
                            "status": verdict["status"],
                            "quote": quote[:80],
                        })
                    # The contracts are frozen: rebuild rather than mutate.
                    replacements.append(_null_quote(item, quote_field))
                    changed = True
                else:
                    replacements.append(item)
            field = "comparisons" if quote_field == "user_verbatim_quote" else "defects"
            if changed:
                if is_dataclass(record):
                    scrubbed.append(replace(record, **{field: replacements}))
                else:
                    try:
                        setattr(record, field, replacements)
                    except (AttributeError, TypeError):
                        pass
                    scrubbed.append(record)
            else:
                scrubbed.append(record)
        return scrubbed

    # BatchAgentOutput is frozen too, so the scrubbed records are returned for the
    # caller to rebuild the batch rather than mutated in place.
    scrubbed_radar = list(getattr(batch, "competitor_radar_results", None) or [])
    scrubbed_rnd = list(getattr(batch, "rnd_voc_results", None) or [])
    if scrubbed_radar:
        scrubbed_radar = _scrub(scrubbed_radar, "user_verbatim_quote")
    if scrubbed_rnd:
        scrubbed_rnd = _scrub(scrubbed_rnd, "user_quote")

    if dropped:
        logging.warning(
            "agent_evidence_gate: dropped %s of %s unverifiable quotes", dropped, checked
        )
    return {
        "checked": checked,
        "dropped": dropped,
        "kept": checked - dropped,
        "examples": absent_examples,
        "competitor_radar_results": scrubbed_radar,
        "rnd_voc_results": scrubbed_rnd,
    }


def step2_agents(store_path: Path, run_id: str, out_dir: Path) -> dict:
    """Step 2: Agent batch runner over the just-collected run."""
    from reddit_voc.storage import VocStore
    from reddit_voc.agents import AgentBatchRunner

    store = VocStore(store_path)
    posts = store.fetch_threads_for_run(run_id)
    if not posts:
        return {"step": "agents", "status": "skipped_no_posts", "run_id": run_id}

    # Admission filter, separate from the evidence gate below. A verifiable quote is
    # not enough: a r/BayAreaBuyers house listing that says "Willow Glen" produced a
    # perfectly citable sentence about a neighbourhood, and the R&D agent turned it
    # into a product-defect finding. Only posts whose brand binding survived the
    # domain/transaction gate are eligible for product analysis at all.
    from reddit_voc.brand_binding import assess_brand_binding

    def _field(post, name: str) -> str:
        """fetch_threads_for_run returns dicts; older call sites pass objects.

        Using getattr alone silently returned "" for every dict row, which made
        every post look brand-less and excluded the whole run.
        """
        if isinstance(post, dict):
            value = post.get(name)
        else:
            value = getattr(post, name, None)
        return value if isinstance(value, str) else ""

    def _eligible(post) -> bool:
        assessment = assess_brand_binding(
            _field(post, "title"),
            _field(post, "selftext"),
            _field(post, "subreddit"),
        )
        return assessment.is_bound()

    admissible = [p for p in posts if _eligible(p)]
    excluded = len(posts) - len(admissible)
    if not admissible:
        return {
            "step": "agents",
            "status": "skipped_no_admissible_posts",
            "run_id": run_id,
            "evaluated": len(posts),
            "excluded_not_product_context": excluded,
        }

    runner = AgentBatchRunner(client=None, config_path=ROOT / "config/agent_settings.json")
    batch = runner.run_batch(admissible, run_id=run_id)

    # Evidence gate: every quote the agents emit must appear in the post it cites.
    # On 2026-10-30 a hardcoded fallback sentence was served to a business group as
    # a consumer's 原话, cited against a house listing that never mentioned the
    # brand (0 of 27 comparisons verified). A quote that cannot be found is dropped
    # here rather than rendered as if it were real.
    evidence_receipt = _verify_agent_evidence(batch, posts)

    # The offline agent path is deterministic: it reproduces one template analysis
    # per post, with a fixed takeaway and fixed advantages. The quotes are now real,
    # but the *analysis* is not generated. The card must say so, or a reader will
    # treat a template as a finding.
    analysis_mode = "template_offline" if runner.client is None else "llm"

    files = runner.persist_artifacts(batch, out_dir)

    # Publish into the canonical web root so the Agent Studio page can fetch them.
    published: dict[str, str] = {}
    public_root_env = os.getenv("AGENT_PUBLIC_ROOT", "/opt/voc-report/html")
    public_agent_dir = Path(public_root_env) / "data" / "reddit-voc" / "agent-studio"
    try:
        public_agent_dir.mkdir(parents=True, exist_ok=True)
        latest = {
            "content_ideas": public_agent_dir / "latest-content-ideas.json",
            "rnd_tickets": public_agent_dir / "latest-rnd-tickets.json",
            "competitor_radar": public_agent_dir / "latest-competitor-radar.json",
        }
        mapping = {
            "content_ideas": f"{run_id}-daily-content-ideas.json",
            "rnd_tickets": f"{run_id}-daily-rnd-tickets.json",
            "competitor_radar": f"{run_id}-daily-competitor-radar.json",
        }
        for key, dst in latest.items():
            src = out_dir / mapping[key]
            if src.exists():
                dst.write_bytes(src.read_bytes())
                published[key] = str(dst)
    except OSError as exc:
        logging.warning("agent publish to public root failed: %s", exc)

    return {
        "step": "agents",
        "status": "ok",
        "run_id": run_id,
        "content_ideas": len(batch.content_scout_results),
        "rnd_tickets": len(batch.rnd_voc_results),
        "competitor_comparisons": len(batch.competitor_radar_results),
        "artifacts": {k: str(v) for k, v in files.items()},
        "published": published,
        "evidence_gate": evidence_receipt,
        "analysis_mode": analysis_mode,
    }


def step3_merge_snapshot(run_id: str, store_path: Path, public_root: Path) -> dict:
    """Step 3: merge the corpus into the public snapshot datasets.

    Selects by DATE WINDOW, not by run_id. Selecting by run_id is why a corpus
    assembled from several independent runs (daily collection plus weekly backfill
    shards) could never publish: each run only sees its own rows, so 9,600
    backfilled posts sat in SQLite while every page still showed the July corpus.

    Writes/updates posts-public.json / comments-public.json inside the base dataset
    directory, and rewrites manifest-public.json with recomputed hashes and counts
    so content and pointer stay in lockstep.
    """
    from reddit_voc.storage import VocStore

    store = VocStore(store_path)

    # Union of everything already published plus everything newly collected. The
    # window is intentionally open-ended at both ends: the snapshot is the whole
    # observed corpus, not a per-run delta.
    WINDOW_START = "2000-01-01T00:00:00+00:00"
    WINDOW_END = "2100-01-01T00:00:00+00:00"
    new_threads = store.fetch_threads_in_window(WINDOW_START, WINDOW_END)
    new_comments = store.fetch_comments_in_window(WINDOW_START, WINDOW_END)

    base_binding_path = public_root / "data" / "reddit-voc" / "current-release.json"
    if not base_binding_path.exists():
        return {"step": "merge_snapshot", "status": "skipped_no_release", "reason": "current-release.json missing"}

    release = json.loads(base_binding_path.read_text(encoding="utf-8"))
    base_rel = release.get("datasets", {}).get("base", {})
    manifest_rel = Path(base_rel.get("manifest_path", ""))
    manifest_abs = public_root / manifest_rel
    if not manifest_abs.exists():
        return {"step": "merge_snapshot", "status": "skipped_no_manifest", "reason": f"missing {manifest_abs}"}

    dataset_dir = manifest_abs.parent
    posts_file = dataset_dir / "posts-public.json"
    existing_posts = json.loads(posts_file.read_text(encoding="utf-8")) if posts_file.exists() else []

    known_ids = {str(p.get("post_id") or p.get("reddit_id") or "") for p in existing_posts}
    added = 0
    sys.path.insert(0, str(ROOT / "src"))
    # Brand binding is decided by registry matching + a product-domain /
    # transaction gate, not a hand-written substring test. The old
    # `"willow" in text_l` turned a r/BayAreaBuyers house listing ("Willow Glen")
    # into a competitor comparison, and a r/dubaiclassifieds "for sale" ad into a
    # Momcozy post.
    from reddit_voc.brand_binding import assess_brand_binding
    from reddit_voc.analyzer import analyze_text
    import re as _re
    for t in new_threads:
        pid = t.get("post_id")
        if pid in known_ids:
            continue
        title = t.get("title") or ""
        content = t.get("selftext") or ""
        full_text = title + " " + content
        # Brand binding: registry match + product-domain / transaction gate. The gate
        # is what stops "Willow Glen" (a neighbourhood) and "[WTS] ... for sale" ads
        # from becoming VOC evidence.
        assessment = assess_brand_binding(title, content, t.get("subreddit") or "")
        brand_binding = assessment.binding
        mentioned = list(assessment.mentions)
        analysis = analyze_text(full_text)
        existing_posts.append({
            "post_id": pid,
            "reddit_id": f"t3_{pid}",
            "subreddit": t.get("subreddit"),
            "title": title,
            "content": content,
            "score": t.get("score"),
            "created_at_utc": t.get("created_at_utc"),
            "event_created_at_utc": t.get("created_at_utc"),
            "event_time_precision": "instant",
            "source_url": t.get("source_url"),
            "linked_comment_count": t.get("parsed_comment_count"),
            "mentioned_brands": mentioned,
            "brand_binding": brand_binding,
            "include_in_voc_metrics": brand_binding.startswith("momcozy"),
            "is_bot": False,
            "record_authority": "governed_base",
            "analysis": {
                "analysis_version": "local_rules_v1",
                "confidence": analysis.confidence,
                "sentiment_label": str(analysis.sentiment_label),
                "sentiment_score": analysis.sentiment_score,
                "topic": str(analysis.topic),
                "severity": str(analysis.severity),
                "pain_points": [str(pp) for pp in analysis.pain_points],
                "provider_call": False,
            },
            "run_id": run_id,
        })
        known_ids.add(pid)
        added += 1

    posts_file.write_text(json.dumps(existing_posts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Comments are half of the VOC surface (comment_context_voc): a post-level
    # sentiment reading without its thread replies silently understates every
    # derivative metric. Merge them with the same rule analysis as the posts.
    comments_file = dataset_dir / "comments-public.json"
    existing_comments = json.loads(comments_file.read_text(encoding="utf-8")) if comments_file.exists() else []
    # Dedupe on the BARE id. Published comment_ids are `t1_`-prefixed (the public
    # contract adds the prefix; snapshot_projection and normalize_all both emit
    # `t1_<id>`), while SQLite comment_ids are bare. Comparing raw to prefixed
    # matched 0 of 37,687 rows and re-appended the entire comment corpus in one
    # night (58,296 -> 95,983), with the manifest faithfully recording the doubled
    # counts. Strip exactly one prefix on both sides before comparing.
    def _bare_cid(value: object) -> str:
        text = str(value or "")
        return text[3:] if text.startswith("t1_") else text

    known_comment_ids = {
        _bare_cid(c.get("comment_id") or c.get("reddit_id")) for c in existing_comments
    }
    comments_added = 0
    for c in new_comments:
        cid = _bare_cid(c.get("comment_id"))
        if not cid or cid in known_comment_ids:
            continue
        body = c.get("body") or ""
        c_analysis = analyze_text(body)
        existing_comments.append({
            "comment_id": cid,
            "reddit_id": f"t1_{cid}",
            "post_id": str(c.get("post_id") or ""),
            "body": body,
            "score": c.get("score"),
            "created_at_utc": c.get("created_at_utc"),
            "event_created_at_utc": c.get("created_at_utc"),
            "event_time_precision": "instant",
            "parent_id": c.get("parent_id"),
            "matched_keywords": c.get("matched_keywords") or [],
            "is_bot": False,
            "record_authority": "governed_base",
            "analysis": {
                "analysis_version": "local_rules_v1",
                "confidence": c_analysis.confidence,
                "sentiment_label": str(c_analysis.sentiment_label),
                "sentiment_score": c_analysis.sentiment_score,
                "topic": str(c_analysis.topic),
                "severity": str(c_analysis.severity),
                "pain_points": [str(pp) for pp in c_analysis.pain_points],
                "provider_call": False,
            },
            "run_id": run_id,
        })
        known_comment_ids.add(_bare_cid(cid))
        comments_added += 1
    comments_file.write_text(json.dumps(existing_comments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Reshape every pipeline-merged record onto the validated public v3 contract.
    # Without this the client rejects the snapshot outright ("帖子结构覆盖等级不受支持").
    sys.path.insert(0, str(ROOT / "scripts"))
    from merge_normalize import normalize_all

    normalized = normalize_all(existing_posts, existing_comments)
    if normalized:
        posts_file.write_text(json.dumps(existing_posts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        comments_file.write_text(json.dumps(existing_comments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # `normalize_all` only repairs records carrying a `run_id`; the July import has
    # none, and it holds posts whose permalink is an image URL or a different post.
    # Repair those in place (permalink + basis only, governance untouched) so every
    # run self-heals instead of republishing 249 dead evidence links.
    from reddit_voc.permalink import repair_permalinks
    permalink_repair = repair_permalinks(existing_posts, existing_comments)
    if permalink_repair["posts_repaired"] or permalink_repair["comments_repaired"]:
        posts_file.write_text(json.dumps(existing_posts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        comments_file.write_text(json.dumps(existing_comments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Release guards (ADR-004 M-A): fail the step BEFORE any manifest is rewritten
    # if the corpus is corrupt. The comment-doubling incident this guards against
    # would otherwise pass every downstream check — refresh_base_manifest recomputes
    # counts from the doubled file, so the corruption is self-attesting.
    def _bare_entity(value: object, prefix: str) -> str:
        text = str(value or "")
        return text[len(prefix):] if text.startswith(prefix) else text

    _post_ids = [str(p.get("post_id") or "") for p in existing_posts]
    _comment_ids = [
        _bare_entity(c.get("comment_id") or c.get("reddit_id"), "t1_")
        for c in existing_comments
    ]
    if len(_post_ids) != len(set(_post_ids)):
        dupes = len(_post_ids) - len(set(_post_ids))
        raise RuntimeError(f"release_guard_post_ids_duplicate: {dupes}")
    if len(_comment_ids) != len(set(_comment_ids)):
        dupes = len(_comment_ids) - len(set(_comment_ids))
        raise RuntimeError(f"release_guard_comment_ids_duplicate: {dupes}")
    if len(existing_comments) < comments_added:
        raise RuntimeError("release_guard_comment_count_shrank")

    # Recompute manifest SHA and update the binding inside current-release.json
    # so the frontend integrity check (manifest SHA vs binding) stays consistent.
    manifest = json.loads(manifest_abs.read_text(encoding="utf-8"))
    from recompute_derivatives import refresh_base_manifest

    refresh_base_manifest(manifest, dataset_dir, existing_posts, existing_comments)
    manifest_abs.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_abs.read_bytes()).hexdigest()

    # CRITICAL: keep the binding in current-release.json in lockstep, otherwise every
    # page fails with 发布 manifest SHA-256 不一致.
    binding_updated = False
    if base_rel.get("public_manifest_sha256") != manifest_sha:
        base_rel["public_manifest_sha256"] = manifest_sha
        binding_updated = True
        release_path = public_root / "data" / "reddit-voc" / "current-release.json"
        tmp = release_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, release_path)

    return {
        "step": "merge_snapshot",
        "status": "ok",
        "run_id": run_id,
        "new_posts_added": added,
        "new_comments_added": comments_added,
        "total_posts_in_snapshot": len(existing_posts),
        "total_comments_in_snapshot": len(existing_comments),
        "manifest_sha256": manifest_sha,
        "binding_updated": binding_updated,
        "dataset_dir": str(dataset_dir),
    }


# Readiness contract for pointer advance. A step listed here must finish with one of
# READY_STATUSES before `advance_pointer` may run, otherwise the published
# `data_as_of_utc` would claim freshness the data does not have.
POINTER_PREREQUISITES = ("collect", "merge_snapshot", "recompute_derivatives")
READY_STATUSES = {"ok", "success", "empty_success", "partial", "skipped_already_covered"}


def step3_5_recompute_derivatives(public_root: Path) -> dict:
    """Step 3.5 (ADR-002 Phase B): recompute derivative datasets from merged snapshot.

    Recomputes aggregates / quarter-insights / reports daily from the full merged
    corpus, rewrites each dataset's manifest-file hashes, then updates every
    binding SHA in current-release.json. Pointer advance (Step 4) must only run
    AFTER this step succeeds — 先内容后指针.
    """
    sys.path.insert(0, str(ROOT))
    from recompute_derivatives import run_recompute

    receipt = run_recompute(public_root, dry_run=False)

    # Rewrite manifest-internal file hashes for the datasets we touched, then
    # sync binding SHAs in current-release.json (same mechanism as merge_snapshot).
    rel_path = public_root / "data" / "reddit-voc" / "current-release.json"
    release = json.loads(rel_path.read_text(encoding="utf-8"))
    bindings_updated = []

    base_binding = release["datasets"].get("base", {})
    base_manifest_abs = public_root / base_binding.get("manifest_path", "")
    if base_manifest_abs.exists():
        manifest = json.loads(base_manifest_abs.read_text(encoding="utf-8"))
        dataset_dir = base_manifest_abs.parent
        from recompute_derivatives import refresh_base_manifest

        base_posts = json.loads((dataset_dir / "posts-public.json").read_text(encoding="utf-8"))
        base_comments = json.loads((dataset_dir / "comments-public.json").read_text(encoding="utf-8"))
        refresh_base_manifest(manifest, dataset_dir, base_posts, base_comments)
        base_manifest_abs.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Refresh: recompute wrote new bytes into dataset files whose manifests embed
    # their hashes; recompute each binding's manifest sha after internal-fix pass.
    for key, b in release["datasets"].items():
        mp = public_root / b.get("manifest_path", "")
        if not mp.exists():
            continue
        # First sync internal file hashes where the manifest embeds them.
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        changed = False
        for fkey, entry in manifest.get("files", {}).items():
            fp = mp.parent / fkey
            if fp.exists():
                raw = fp.read_bytes()
                new_sha = hashlib.sha256(raw).hexdigest()
                if entry.get("sha256") != new_sha:
                    entry["sha256"] = new_sha
                    changed = True
                if "bytes" in entry and entry.get("bytes") != len(raw):
                    entry["bytes"] = len(raw)
                    changed = True
        if changed:
            mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        new_binding_sha = hashlib.sha256(mp.read_bytes()).hexdigest()
        if b.get("public_manifest_sha256") != new_binding_sha:
            b["public_manifest_sha256"] = new_binding_sha
            bindings_updated.append(key)

    # The reports bundle declares its own lineage hash and the client compares it
    # with the release binding, so both sides must move together.
    reports_lineage = receipt.get("reports_lineage_manifest_sha256")
    reports_binding = release["datasets"].get("reports")
    if reports_lineage and reports_binding is not None:
        if reports_binding.get("lineage_manifest_sha256") != reports_lineage:
            reports_binding["lineage_manifest_sha256"] = reports_lineage
            if "reports" not in bindings_updated:
                bindings_updated.append("reports")

    if bindings_updated:
        tmp = rel_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, rel_path)

    receipt["step"] = "recompute_derivatives"
    receipt["status"] = "ok"
    receipt["bindings_updated"] = bindings_updated
    return receipt


def step4_advance_pointer(public_root: Path, run_id: str) -> dict:
    """Step 4: advance current-release.json to the closed T-1 boundary."""
    sys.path.insert(0, str(ROOT))
    from scripts.advance_daily_t1_release import advance_current_release_to_t1

    result = advance_current_release_to_t1(
        current_release_path=public_root / "data" / "reddit-voc" / "current-release.json",
        status="partial",
    )
    return {"step": "advance_pointer", "status": result.get("status"), **result}


def step5_feishu_push(run_id: str, report_date: str, receipts: list[dict], output_dir: Path) -> dict:
    """Step 5: push the morning-brief card to the Feishu Echo-Agent group.

    ADR-005 v1: the card is business intelligence (risk radar, R&D defects,
    competitor head-to-head, content ideas), not a pipeline dashboard. The
    builder reads the run's own artifacts plus the public tree; falls back to
    the legacy metrics card if the new builder fails, so the push never blocks
    the pipeline on a template error.
    """
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    # Default target is the business group 品牌经营-舆情洞察Agent(Echo) (owner
    # decision 2026-10-29); the dev group is used by explicit override only.
    chat_id = os.getenv("FEISHU_REPORT_CHAT_ID", "oc_919ce85a13f3e19f6ca6c99dfdc01512")
    if not app_id or not app_secret:
        return {"step": "feishu_push", "status": "skipped_no_credentials"}

    from reddit_voc.feishu_bot import FeishuBotClient

    public_root = Path(os.getenv("PIPELINE_PUBLIC_ROOT", "/opt/voc-report/html"))
    card = None
    builder_error = None
    try:
        sys.path.insert(0, str(ROOT / "tools" / "feishu-card" / "builders"))
        from build_morning_brief_v4 import build_card

        card = build_card(output_dir, public_root, run_id)
    except Exception as exc:  # noqa: BLE001 — fallback card keeps the push alive
        builder_error = f"{type(exc).__name__}: {exc}"

    if card is None:
        # Legacy fallback: pipeline readings only (v0 card).
        collect = next((r for r in receipts if r.get("step") == "collect"), {})
        agents = next((r for r in receipts if r.get("step") == "agents"), {})
        merged = next((r for r in receipts if r.get("step") == "merge_snapshot"), {})
        markdown = (
            f"**📅 数据周期**: {report_date} (T-1 已闭合)\n"
            f"**📥 采集**: 帖子 {collect.get('ingested_threads', 0)} 篇 · 评论 {collect.get('ingested_comments', 0)} 条"
            f" · 新增入库 {merged.get('new_posts_added', 0)} 篇\n"
            f"**🤖 Agent 决策**: 爆款选题 {agents.get('content_ideas', 0)} · "
            f"研发改款 {agents.get('rnd_tickets', 0)} · 竞品情报 {agents.get('competitor_comparisons', 0)}\n\n"
            f"👉 [打开工作台](https://radar.luteos.com/dashboard)"
        )
        card = {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": f"📊 Echo-Agent 日报 · {report_date}"}, "template": "blue"},
            "elements": [
                {"tag": "markdown", "content": markdown},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": f"🤖 Echo-Agent 自动流水线 · Run: {run_id}"}]},
            ],
        }

    client = FeishuBotClient(app_id=app_id, app_secret=app_secret)
    resp = client.send_interactive_card(chat_id, card)
    ok = resp.get("code") == 0
    result: dict = {"step": "feishu_push", "status": "sent" if ok else f"failed_{resp.get('code')}", "msg": resp.get("msg")}
    if builder_error:
        result["builder_fallback"] = builder_error
    return result


def _collect_write_targets(public_root: Path, store_path: Path, output_dir: Path) -> list[Path]:
    """Enumerate every path the pipeline may create, rewrite, or read-for-copy.

    Driven by the release bindings rather than a hand-written list: a dataset added
    to current-release.json without a matching preflight entry is exactly how the
    10-29 failure shipped. Walks each binding's manifest `files` map, the dataset's
    own `lineage/` directory (both <version>/lineage and <version>/public/../lineage
    layouts), the reports top-level files, the agent-studio latest pointers, the
    store file itself, and the generations root when it exists.
    """
    data_voc = public_root / "data" / "reddit-voc"
    targets: list[Path] = [
        store_path,
        store_path.parent,
        output_dir,
        data_voc,
        data_voc / "lineage",
        data_voc / "current-release.json",
    ]

    generations = public_root / "data" / "reddit-voc-generations"
    if generations.exists():
        targets.append(generations)

    agent_public = Path(os.getenv("AGENT_PUBLIC_ROOT", str(public_root)))
    agent_dir = agent_public / "data" / "reddit-voc" / "agent-studio"
    targets.extend(
        agent_dir / name
        for name in (
            "latest-content-ideas.json",
            "latest-rnd-tickets.json",
            "latest-competitor-radar.json",
        )
    )
    targets.append(agent_dir)

    release_path = data_voc / "current-release.json"
    if not release_path.exists():
        return targets
    try:
        release = json.loads(release_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # An unreadable or corrupt pointer is itself a preflight failure; the
        # caller surfaces it when the same path fails the readability check.
        return targets

    for binding in (release.get("datasets") or {}).values():
        manifest_abs = public_root / (binding.get("manifest_path") or "")
        dataset_dir = manifest_abs.parent
        targets.append(manifest_abs)
        targets.append(dataset_dir)
        # Both layouts: <version>/manifest.json and <version>/public/manifest.json
        for candidate in (dataset_dir / "lineage", dataset_dir.parent / "lineage"):
            targets.append(candidate)
            if candidate.is_dir():
                try:
                    targets.extend(sorted(p for p in candidate.iterdir() if p.is_file()))
                except OSError:
                    pass
        manifest = None
        if manifest_abs.exists():
            try:
                manifest = json.loads(manifest_abs.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = None
        for rel_name in ((manifest or {}).get("files") or {}):
            targets.append(dataset_dir / rel_name)

    return targets


def _preflight_writability(public_root: Path, store_path: Path, output_dir: Path) -> dict:
    """Fail the run BEFORE collecting if any write-target is unusable.

    The 10-29 07:05 run passed preflight, collected and merged 73 posts / 291
    comments, then died in recompute writing a root-owned 0600
    lineage/product-entity-ledger.json that lived inside a *writable* directory.
    Directory-level `os.access(W_OK)` cannot see that, so check every target file
    itself: mode write bits first (a 0400 file denies everyone, root included),
    then readability (the generation copy reads what it publishes), then writability.

    Returns {'checked': int, 'warnings': [...]} on success; raises
    RuntimeError('pipeline_preflight_unwritable_targets: ...') with a per-path
    {path, uid, mode, reason} payload otherwise.
    """
    blocked: list[dict] = []
    warnings: list[dict] = []
    checked = 0
    seen: set[str] = set()
    euid = os.geteuid()

    for target in _collect_write_targets(public_root, store_path, output_dir):
        key = str(target)
        if key in seen:
            continue
        seen.add(key)

        try:
            stat = target.stat()
        except FileNotFoundError:
            # Not created yet: the nearest existing parent must be writable+searchable.
            parent = target.parent
            while not parent.exists() and parent != parent.parent:
                parent = parent.parent
            checked += 1
            if not (os.access(parent, os.W_OK) and os.access(parent, os.X_OK)):
                blocked.append({"path": key, "uid": None, "mode": None, "reason": "parent_not_writable"})
            continue
        except OSError as exc:
            checked += 1
            blocked.append({"path": key, "uid": None, "mode": None, "reason": f"stat_failed:{exc.strerror}"})
            continue

        checked += 1
        mode = stat.st_mode & 0o7777
        is_dir = target.is_dir()

        if is_dir:
            if not os.access(target, os.W_OK | os.X_OK):
                blocked.append({"path": key, "uid": stat.st_uid, "mode": oct(mode), "reason": "dir_not_writable"})
            elif stat.st_uid != euid:
                warnings.append({"path": key, "uid": stat.st_uid, "mode": oct(mode), "reason": "foreign_owner"})
            continue

        # Regular file. A file with no write bit set at all is a hard stop even for
        # root: that is the 0400/0600 root-owned artifact that broke 10-29.
        if mode & 0o222 == 0:
            blocked.append({"path": key, "uid": stat.st_uid, "mode": oct(mode), "reason": "mode_denies_write"})
            continue
        if not os.access(target, os.R_OK):
            blocked.append({"path": key, "uid": stat.st_uid, "mode": oct(mode), "reason": "not_readable"})
            continue
        if not os.access(target, os.W_OK):
            blocked.append({"path": key, "uid": stat.st_uid, "mode": oct(mode), "reason": "not_writable"})
            continue
        if stat.st_uid != euid:
            warnings.append({"path": key, "uid": stat.st_uid, "mode": oct(mode), "reason": "foreign_owner"})

    if blocked:
        payload = json.dumps(blocked, ensure_ascii=False)
        raise RuntimeError(f"pipeline_preflight_unwritable_targets: {payload}")

    if warnings:
        logging.warning("pipeline_preflight_foreign_owner: %s", json.dumps(warnings, ensure_ascii=False))
    return {"checked": checked, "warnings": warnings}


def run_pipeline(*, store_path: Path, public_root: Path, output_dir: Path, skip_feishu: bool = False) -> dict:
    started = datetime.now(timezone.utc)
    window_start, window_end, run_id, report_date = _t1_bounds()
    receipts: list[dict] = []
    errors: list[dict] = []

    _preflight_writability(public_root, store_path, output_dir)

    # ADR-002 Phase B: Step 3.5 recompute_derivatives runs before pointer advance,
    # so pointer/content parity is maintained. Guard remains available as a kill-switch.
    pointer_guard = os.getenv("PIPELINE_DISABLE_POINTER_ADVANCE", "") == "1"
    if pointer_guard:
        receipts.append({
            "step": "advance_pointer",
            "status": "skipped_by_kill_switch",
            "reason": "PIPELINE_DISABLE_POINTER_ADVANCE=1",
        })

    steps = [
        ("collect", lambda: step1_collect(store_path, run_id)),
        ("agents", lambda: step2_agents(store_path, run_id, output_dir)),
        ("merge_snapshot", lambda: step3_merge_snapshot(run_id, store_path, public_root)),
        ("recompute_derivatives", lambda: step3_5_recompute_derivatives(public_root)),
    ]
    if not pointer_guard:
        steps.append(("advance_pointer", lambda: step4_advance_pointer(public_root, run_id)))
    if not skip_feishu:
        steps.append(("feishu_push", lambda: step5_feishu_push(run_id, report_date, receipts, output_dir)))

    for name, fn in steps:
        # Readiness gate: every step the pointer advance depends on must have
        # succeeded. Previously each step's exception was caught and the loop simply
        # continued, so advance_pointer would publish a fresh `data_as_of_utc` even
        # when collection or recompute had failed -- the mechanism behind "the site
        # claims T-1 while the content is months old".
        prerequisite_failures = [
            r["step"] for r in receipts
            if isinstance(r, dict)
            and r.get("step") in POINTER_PREREQUISITES
            and str(r.get("status")) not in READY_STATUSES
        ]
        if name == "advance_pointer" and prerequisite_failures:
            receipt = {
                "step": name,
                "status": "blocked_by_prerequisites",
                "reason": "上游步骤未成功，指针不前移",
                "failed_prerequisites": prerequisite_failures,
            }
            receipts.append(receipt)
            continue
        try:
            receipt = fn()
        except Exception as exc:
            receipt = {"step": name, "status": "error", "error": str(exc), "traceback": traceback.format_exc()[-1500:]}
            errors.append(receipt)
        receipts.append(receipt)

    finished = datetime.now(timezone.utc)
    receipt_doc = {
        "schema_version": PIPELINE_SCHEMA,
        "run_id": run_id,
        "report_date": report_date,
        "window_start_utc": window_start.isoformat(),
        "window_end_utc": window_end.isoformat(),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "status": "success" if not errors else f"partial_{len(errors)}_step_errors",
        "steps": receipts,
        "errors": errors,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = output_dir / f"{run_id}-pipeline-receipt.json"
    receipt_path.write_text(json.dumps(receipt_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt_doc


def main() -> int:
    parser = argparse.ArgumentParser(description="Echo-Agent Daily T-1 Pipeline")
    parser.add_argument("--store", type=Path, default=Path("/opt/echo-agent-bot/data/reddit_voc_daily.sqlite3"))
    parser.add_argument("--public-root", type=Path, default=Path("/opt/voc-report/html"))
    parser.add_argument("--output-dir", type=Path, default=Path("/opt/echo-agent-bot/outputs"))
    parser.add_argument("--skip-feishu", action="store_true", default=False)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    receipt = run_pipeline(store_path=args.store, public_root=args.public_root, output_dir=args.output_dir, skip_feishu=args.skip_feishu)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
