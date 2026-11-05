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
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import errno
import fcntl
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

PIPELINE_GENERATION_MODE_ENV = "PIPELINE_GENERATION_MODE"


def _generation_mode() -> str:
    """Read the release-generation mode for this invocation.

    `off` (default) keeps the historical in-place behaviour byte for byte.
    `symlink` stages every data write into a new generation and publishes it with
    a single atomic pointer swap, so a failed run cannot leave the live tree
    half-updated.

    Read per call, never cached at module level: operators roll back by changing
    a systemd environment variable, and tests patch the environment after import.
    A typo raises instead of silently falling back to the live-write path.
    """
    raw = os.getenv(PIPELINE_GENERATION_MODE_ENV, "off").strip().lower()
    if raw in ("off", "symlink"):
        return raw
    raise RuntimeError(f"pipeline_generation_mode_invalid:{raw!r}")


def _shanghai_now() -> datetime:
    return datetime.now(SHANGHAI_TZ)


SCHEDULED_WINDOW_MINUTES = (6 * 60 + 35, 7 * 60 + 35)  # 07:05 CST ± 30 minutes


def _run_identity(sh_now: datetime) -> tuple[str, str, str]:
    """Return (run_id, run_kind, trigger) for one invocation.

    The old run id was `daily_collect_YYYYMMDD_0700`: two runs on the same day
    produced the same id, so the second receipt overwrote the first and the
    closure metric could not tell a scheduled run from a manual one. The id now
    carries the start time to the second; the kind is inferred from the same
    Shanghai clock the timer uses, so a manual rerun at noon is not counted as
    an unattended success.
    """
    run_id = f"daily_collect_{sh_now:%Y%m%d_%H%M%S}"
    seconds = sh_now.hour * 3600 + sh_now.minute * 60 + sh_now.second
    scheduled = (
        SCHEDULED_WINDOW_MINUTES[0] * 60
        <= seconds
        <= SCHEDULED_WINDOW_MINUTES[1] * 60
    )
    run_kind = "scheduled" if scheduled else "manual"
    trigger = "systemd_timer" if scheduled else "manual_cli"
    return run_id, run_kind, trigger


def _unique_run_id(base: str, output_dir: Path) -> str:
    """Make a same-second rerun get its own receipt instead of a collision.

    The id is time-based, but two invocations can start within the same second
    (a retry, or a test). The first keeps the clean id; later ones get `-2`,
    `-3`, ... so `write_build_receipt` never has to overwrite evidence.
    """
    candidate = base
    index = 2
    while (output_dir / f"{candidate}-pipeline-receipt.json").exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _t1_bounds(
    now_utc: datetime | None = None,
) -> tuple[datetime, datetime, str, str, str, str]:
    """Return (window_start, window_end, run_id, report_date, run_kind, trigger)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    close = now_utc.replace(hour=23, minute=0, second=0, microsecond=0)
    if close > now_utc:
        close -= timedelta(days=1)
    window_end = close
    window_start = close - timedelta(days=1)
    sh_now = now_utc.astimezone(SHANGHAI_TZ)
    report_date = sh_now.strftime("%Y-%m-%d")
    run_id, run_kind, trigger = _run_identity(sh_now)
    return window_start, window_end, run_id, report_date, run_kind, trigger


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


def _verify_agent_evidence(batch, posts) -> tuple[dict, dict]:
    """Drop any agent quote that does not appear in the post it cites.

    Returns `(receipt, scrubbed)`:

      * `receipt` is JSON-serialisable and goes into the run receipt, so a
        regression (quotes silently disappearing, or fabricated ones reappearing)
        is visible without reading the artifacts by hand;
      * `scrubbed` carries the cleaned records themselves.

    The two are separate on purpose. This function used to return one dict that
    held both, and the caller persisted the *original* batch -- so the gate
    counted a fabricated quote as dropped, wrote the count into the receipt, and
    then published the fabrication to disk and to the morning card. The 2026-10-30
    incident, in other words, would have recurred with a clean-looking receipt.
    That dict also carried raw dataclasses into `json.dumps`, which crashed the
    production run of 2026-10-31 (exit 1 after 19m48s).
    """
    from dataclasses import is_dataclass

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
    receipt = {
        "checked": checked,
        "dropped": dropped,
        "kept": checked - dropped,
        "examples": absent_examples,
        # Serialisable counts, not the records themselves: this dict is written
        # with json.dumps into the run receipt, and raw dataclasses there raised
        # "Object of type RndVocResult is not JSON serializable" in production.
        "competitor_radar_results": _scrubbed_summary(scrubbed_radar, "comparisons"),
        "rnd_voc_results": _scrubbed_summary(scrubbed_rnd, "defects"),
    }
    scrubbed = {"competitor_radar_results": scrubbed_radar, "rnd_voc_results": scrubbed_rnd}
    return receipt, scrubbed


def _scrubbed_summary(records, collection_field: str) -> dict:
    """Counts describing what survived, for the receipt."""
    items = 0
    with_evidence = 0
    for record in records or []:
        for item in getattr(record, collection_field, None) or []:
            items += 1
            field = "user_verbatim_quote" if collection_field == "comparisons" else "user_quote"
            if getattr(item, field, None):
                with_evidence += 1
    return {"records": len(records or []), "items": items, "items_with_evidence": with_evidence}


def _publish_agent_artifacts(run_id: str, out_dir: Path, *, data_root: Path | None = None) -> dict[str, str]:
    """Copy the three latest-*.json artifacts into the served agent-studio dir.

    In symlink mode the target is `<generation>/agent-studio`, and a failure is
    fatal: the run must not commit a generation whose Agent Studio page still
    shows the seed's stale artifacts. `AGENT_PUBLIC_ROOT` is not read at all in
    that mode -- its default (`/opt/voc-report/html`) is unrelated to the run's
    `public_root`, so honouring it would write a tree the caller never named.
    """
    published: dict[str, str] = {}
    if data_root is not None:
        public_agent_dir = data_root / "agent-studio"
    else:
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
        if data_root is not None:
            raise
        logging.warning("agent publish to public root failed: %s", exc)
    return published


def step2_agents(store_path: Path, run_id: str, out_dir: Path, *, data_root: Path | None = None) -> dict:
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

    # LLM wiring. `build_agent_client()` returns None unless AGENT_LLM_BASE_URL,
    # AGENT_LLM_MODEL and a key (direct or file) are all configured, so the
    # pipeline keeps running the template fallback when they are not -- which is
    # the current production state, and which the card must disclose.
    #
    # This is the adapter the agents always needed: DeepSeekClient rejects their
    # phase values ("rnd_voc", "content_scouting", "competitor_radar") and
    # requires system_prompt/deadline they do not pass, so it could never have
    # served them regardless of credentials.
    from reddit_voc.agents.llm_adapter import AgentLLMError, build_agent_client

    agent_client = build_agent_client()
    runner = AgentBatchRunner(client=agent_client, config_path=ROOT / "config/agent_settings.json")
    try:
        batch = runner.run_batch(admissible, run_id=run_id)
    except AgentLLMError as exc:
        # A provider outage must not silence the whole run. Fall back to the
        # template path and record why, so the receipt says which mode produced
        # the analysis instead of leaving a partial LLM batch looking complete.
        logging.warning("agent_llm_failed, falling back to template: %s", exc)
        agent_client = None
        runner = AgentBatchRunner(client=None, config_path=ROOT / "config/agent_settings.json")
        batch = runner.run_batch(admissible, run_id=run_id)
        llm_fallback_reason = str(exc)
    else:
        llm_fallback_reason = None

    # Evidence gate: every quote the agents emit must appear in the post it cites.
    # On 2026-10-30 a hardcoded fallback sentence was served to a business group as
    # a consumer's 原话, cited against a house listing that never mentioned the
    # brand (0 of 27 comparisons verified). A quote that cannot be found is dropped
    # here rather than rendered as if it were real.
    evidence_receipt, scrubbed = _verify_agent_evidence(batch, posts)

    # The gate must change what gets published, not just what gets reported.
    # Persisting `batch` here published quotes the gate had just rejected.
    gate_dropped = evidence_receipt["dropped"]
    if gate_dropped:
        batch = replace(
            batch,
            competitor_radar_results=scrubbed["competitor_radar_results"],
            rnd_voc_results=scrubbed["rnd_voc_results"],
        )

    # The offline agent path is deterministic: it reproduces one template analysis
    # per post, with a fixed takeaway and fixed advantages. The quotes are now real,
    # but the *analysis* is not generated. The card must say so, or a reader will
    # treat a template as a finding.
    analysis_mode = "template_offline" if runner.client is None else "llm"

    files = runner.persist_artifacts(batch, out_dir)

    # Publish into the canonical web root so the Agent Studio page can fetch them.
    published = _publish_agent_artifacts(run_id, out_dir, data_root=data_root)

    receipt = {
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
    if analysis_mode == "llm":
        receipt["llm_model"] = getattr(agent_client, "model", None)
    if llm_fallback_reason:
        # Distinguish "never configured" from "configured but the provider
        # failed". The second is an incident; the first is the known state.
        receipt["llm_fallback_reason"] = llm_fallback_reason
    return receipt


def step3_merge_snapshot(
    run_id: str, store_path: Path, public_root: Path, *, data_root: Path | None = None
) -> dict:
    """Step 3: merge the corpus into the public snapshot datasets.

    Selects by DATE WINDOW, not by run_id. Selecting by run_id is why a corpus
    assembled from several independent runs (daily collection plus weekly backfill
    shards) could never publish: each run only sees its own rows, so 9,600
    backfilled posts sat in SQLite while every page still showed the July corpus.

    Writes/updates posts-public.json / comments-public.json inside the base dataset
    directory, and rewrites manifest-public.json with recomputed hashes and counts
    so content and pointer stay in lockstep.

    `data_root` (symlink mode) is the staged reddit-voc directory. Every join
    below then lands inside the generation; with it None the expressions are the
    historical ones and `public_root/data/reddit-voc` is read and written in
    place.
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

    # Everything the release document points at is relative to the data root, not
    # to the site root: binding paths read `data/reddit-voc/<version>/...`. Joining
    # them onto public_root follows the live symlink in staging mode, which is how
    # a run that believed it was writing a private copy published to production.
    voc_root = Path(data_root) if data_root is not None else public_root / "data" / "reddit-voc"
    # Unconditional: the module works both as a script (its own directory is
    # sys.path[0]) and imported by tests, which do not add scripts/ themselves.
    sys.path.insert(0, str(ROOT / "scripts"))
    from release_paths import manifest_path as _manifest_path

    base_binding_path = voc_root / "current-release.json"
    if not base_binding_path.exists():
        return {"step": "merge_snapshot", "status": "skipped_no_release", "reason": "current-release.json missing"}

    release = json.loads(base_binding_path.read_text(encoding="utf-8"))
    base_rel = release.get("datasets", {}).get("base", {})
    manifest_abs = _manifest_path(voc_root, base_rel)
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

    # Product entity resolution. Until now nothing in the daily path produced
    # `product_bindings`: every merged record carried a hardcoded [], so any page
    # aggregating by product family was really aggregating by topic. The resolver
    # itself was already implemented and used by the offline site builder; only
    # the daily producer was missing.
    #
    # Loaded once per run, not per record: from_ledger reads and hashes the whole
    # ledger, and a nightly run adds thousands of records.
    product_resolver = None
    try:
        from reddit_voc.product_entity_resolution import ProductEntityResolver

        product_resolver = ProductEntityResolver.from_ledger(
            ROOT / "config" / "product_entities" / "momcozy-product-entity-ledger-v1.json"
        )
    except Exception as exc:  # noqa: BLE001
        # A missing or unreadable ledger must not stop the merge: the bindings
        # are an enrichment, and the run still owes the site its base snapshot.
        # The receipt records the failure so an empty page is explainable.
        logging.warning("product entity resolver unavailable: %s", exc)
        product_resolver = None
    product_bound_posts = 0
    product_bound_comments = 0
    product_binding_total = 0

    def _product_bindings(text: str) -> list:
        """Nine-field binding records for one record's own text.

        Returns [] on any resolver failure: the frontend validates every element
        strictly and rejects the dataset on a mismatch, so a partial or malformed
        binding is worse than none.
        """
        nonlocal product_binding_total
        if product_resolver is None or not text:
            return []
        try:
            result = product_resolver.resolve(text)
        except Exception as exc:  # noqa: BLE001
            logging.warning("product resolve failed: %s", exc)
            return []
        records = [binding.to_record() for binding in result.product_bindings]
        product_binding_total += len(records)
        return records

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
        post_bindings = _product_bindings(full_text)
        if post_bindings:
            product_bound_posts += 1
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
            # Product-level identity, from this record's own title+content.
            # Reuse the value computed above: calling the helper again would
            # resolve the post twice and double-count product_binding_total.
            "product_bindings": post_bindings,
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
        comment_bindings = _product_bindings(body)
        if comment_bindings:
            product_bound_comments += 1
        existing_comments.append({
            "comment_id": cid,
            "reddit_id": f"t1_{cid}",
            "post_id": str(c.get("post_id") or ""),
            "body": body,
            "score": c.get("score"),
            "created_at_utc": c.get("created_at_utc"),
            "event_created_at_utc": c.get("created_at_utc"),
            "event_time_precision": "instant",
            # Product identity from the comment's own body. Comments are half the
            # VOC surface; resolving posts only would leave every reply unbound.
            # Reuse the value computed above: calling the helper again would
            # resolve the comment twice and double-count product_binding_total.
            "product_bindings": comment_bindings,
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
        release_path = voc_root / "current-release.json"
        tmp = release_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, release_path)

    return {
        "step": "merge_snapshot",
        "status": "ok",
        "run_id": run_id,
        "new_posts_added": added,
        "new_comments_added": comments_added,
        # How much of this run's new content carries product identity. Zero is a
        # legitimate value (a run of unrelated posts), so it is reported rather
        # than asserted; a sudden drop is the signal that the resolver broke.
        "product_bound_posts": product_bound_posts,
        "product_bound_comments": product_bound_comments,
        "product_bindings_total": product_binding_total,
        "product_resolver_loaded": product_resolver is not None,
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


def step3_5_recompute_derivatives(public_root: Path, *, data_root: Path | None = None) -> dict:
    """Step 3.5 (ADR-002 Phase B): recompute derivative datasets from merged snapshot.

    Recomputes aggregates / quarter-insights / reports daily from the full merged
    corpus, rewrites each dataset's manifest-file hashes, then updates every
    binding SHA in current-release.json. Pointer advance (Step 4) must only run
    AFTER this step succeeds — 先内容后指针.

    `data_root` (symlink mode) sends every read and write into the staged
    generation, including the binding-sync pass below and the pointer rewrite it
    performs. Leaving it None reproduces the historical paths exactly.
    """
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    from recompute_derivatives import run_recompute
    from release_paths import manifest_path as _manifest_path

    voc_root = Path(data_root) if data_root is not None else public_root / "data" / "reddit-voc"

    receipt = run_recompute(public_root, data_root=data_root, dry_run=False)

    # Rewrite manifest-internal file hashes for the datasets we touched, then
    # sync binding SHAs in current-release.json (same mechanism as merge_snapshot).
    rel_path = voc_root / "current-release.json"
    release = json.loads(rel_path.read_text(encoding="utf-8"))
    bindings_updated = []

    base_binding = release["datasets"].get("base", {})
    base_manifest_abs = _manifest_path(voc_root, base_binding)
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
        mp = _manifest_path(voc_root, b)
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


def _write_run_build_receipt(
    *,
    public_root: Path,
    mode: str,
    tx,
    release_doc: dict | None,
    receipt_doc: dict,
    period_end_utc: str,
) -> dict:
    """Write `build-receipts/<run_id>.json` for this run.

    In symlink mode the receipt is written inside the staged generation, so a
    successful commit publishes it with the data it describes. A failed run's
    generation is kept as evidence; the live tree still points at the previous
    generation and therefore does not claim the failed run. In off mode the
    receipt goes into the live data root, preserving the historical behavior.
    """
    from build_receipt import write_build_receipt

    if mode == "symlink":
        if tx is None:
            raise RuntimeError("run_receipt_generation_missing")
        root = Path(tx.root)
    else:
        root = public_root / "data" / "reddit-voc"

    if release_doc is None:
        # A failed run may stop before step4, so the advanced document does not
        # exist. The generation still carries the seed pointer; bind the failed
        # receipt to that tree so the evidence is not silently dropped. The
        # receipt's status=failed prevents it from being read as a publish.
        try:
            release_doc = json.loads(
                (root / "current-release.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return {"step": "write_build_receipt", "status": "skipped_no_release"}

    path = write_build_receipt(
        root,
        str(receipt_doc["run_id"]),
        release=release_doc,
        status=str(receipt_doc["status"]),
        period_end_utc=period_end_utc,
        started_at_utc=receipt_doc.get("started_at_utc"),
        finished_at_utc=receipt_doc.get("finished_at_utc"),
        steps=receipt_doc.get("steps") or [],
        errors=receipt_doc.get("errors") or [],
    )
    return {"step": "write_build_receipt", "status": "ok", "path": str(path)}


def step4_advance_pointer(
    public_root: Path,
    run_id: str,
    *,
    data_root: Path | None = None,
    release_doc_holder: dict | None = None,
) -> dict:
    """Step 4: advance current-release.json to the closed T-1 boundary.

    In symlink mode this mutates the release document *in memory* and hands it to
    the single commit that publishes the generation. Writing a file here would be
    a third live pointer replace, and a failure after it would leave live
    freshness advanced over old content.

    Off mode keeps the historical atomic in-place write.
    """
    sys.path.insert(0, str(ROOT))
    from scripts.advance_daily_t1_release import (
        advance_current_release_to_t1,
        advance_release_document,
        release_receipt,
    )

    if data_root is not None:
        if release_doc_holder is None:
            raise RuntimeError("advance_pointer_holder_missing")
        document = json.loads((Path(data_root) / "current-release.json").read_text(encoding="utf-8"))
        advance_release_document(document, status="partial", run_id=run_id)
        release_doc_holder["document"] = document
        result = release_receipt(document, "partial")
    else:
        result = advance_current_release_to_t1(
            current_release_path=public_root / "data" / "reddit-voc" / "current-release.json",
            status="partial",
            run_id=run_id,
        )
    return {"step": "advance_pointer", "status": result.get("status"), **result}


def _build_query_index_step(run_id: str) -> dict:
    """Post-publish rebuild of the release-pinned query index (T6').

    Non-critical by design: returns status=skipped/failed with a reason rather
    than raising, so the publish receipt stays green (K1) while the bot keeps
    serving the previous generation's index. Index freshness self-identifies
    via its pinned release token, so a stale index is detectable, never lying.
    """
    receipt: dict = {"step": "build_query_index", "run_id": run_id}
    try:
        sys.path.insert(0, str(ROOT))
        from scripts.build_query_index import build as build_index

        output = ROOT / "outputs" / "query-index" / "query-index.sqlite3"
        result = build_index(output)
        receipt.update(status="ok", **result)
    except Exception as exc:  # noqa: BLE001 — non-critical step
        receipt.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        logging.warning("query index rebuild failed (non-critical): %s", exc)
    return receipt


def step5_feishu_push(
    run_id: str,
    report_date: str,
    receipts: list[dict],
    output_dir: Path,
    *,
    receipt: dict | None = None,
) -> dict:
    """Step 5: push the morning-brief card to the Feishu Echo-Agent group.

    ADR-005 v1: the card is business intelligence (risk radar, R&D defects,
    competitor head-to-head, content ideas), not a pipeline dashboard. The
    builder reads the run's own artifacts plus the public tree; falls back to
    the legacy metrics card if the new builder fails, so the push never blocks
    the pipeline on a template error.

    `receipt` is the in-memory run receipt. Without it the builder re-reads
    `<run_dir>/<run_id>-pipeline-receipt.json`, which this pipeline writes only
    AFTER the step loop -- so the card always found it missing, degraded to
    `status: unavailable`, and painted a successful run red on 2026-10-29.
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
        from build_morning_brief_v5 import build_card

        card = build_card(output_dir, public_root, run_id, receipt=receipt)
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


def _is_within(path: Path, root: Path) -> bool:
    """True when `path` is `root` or below it, without following symlinks.

    Lexical on purpose: `root/data/reddit-voc` is a symlink in staging mode, and
    resolving it would report every live-generation path as outside the tree the
    run only reads.
    """
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


def _preflight_writability(
    public_root: Path, store_path: Path, output_dir: Path, *, mode: str = "off"
) -> dict:
    """Fail the run BEFORE collecting if any write-target is unusable.

    The 10-29 07:05 run passed preflight, collected and merged 73 posts / 291
    comments, then died in recompute writing a root-owned 0600
    lineage/product-entity-ledger.json that lived inside a *writable* directory.
    Directory-level `os.access(W_OK)` cannot see that, so check every target file
    itself: mode write bits first (a 0400 file denies everyone, root included),
    then readability (the generation copy reads what it publishes), then writability.

    In symlink mode the live data tree is a read-only source: it is copied into
    the generation and then left alone until `os.replace` swaps the link. Asserting
    W_OK on it would reject a legitimately immutable live tree, so those targets
    are checked for readability only, and the paths the run really must write --
    the store, the output dir, the generations root and the symlink's parent --
    carry the write assertions.

    Returns {'checked': int, 'warnings': [...]} on success; raises
    RuntimeError('pipeline_preflight_unwritable_targets: ...') with a per-path
    {path, uid, mode, reason} payload otherwise.
    """
    blocked: list[dict] = []
    warnings: list[dict] = []
    checked = 0
    seen: set[str] = set()
    euid = os.geteuid()

    live_data = public_root / "data" / "reddit-voc"
    targets = _collect_write_targets(public_root, store_path, output_dir)
    # The symlink's parent must accept the atomic swap even though the link
    # target is read-only in this mode.
    if mode == "symlink":
        targets = targets + [public_root / "data", public_root / "data" / "reddit-voc-generations"]

    for target in targets:
        key = str(target)
        if key in seen:
            continue
        seen.add(key)

        read_only = mode == "symlink" and _is_within(target, live_data)

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
        mode_bits = stat.st_mode & 0o7777
        is_dir = target.is_dir()

        if read_only:
            # Source for the generation copy: must be readable and traversable,
            # never writable. Unreadable bytes cannot be published.
            if is_dir:
                if not (os.access(target, os.R_OK | os.X_OK)):
                    blocked.append({"path": key, "uid": stat.st_uid, "mode": oct(mode_bits), "reason": "dir_not_readable"})
            elif not os.access(target, os.R_OK):
                blocked.append({"path": key, "uid": stat.st_uid, "mode": oct(mode_bits), "reason": "not_readable"})
            continue

        if is_dir:
            if not os.access(target, os.W_OK | os.X_OK):
                blocked.append({"path": key, "uid": stat.st_uid, "mode": oct(mode_bits), "reason": "dir_not_writable"})
            elif stat.st_uid != euid:
                warnings.append({"path": key, "uid": stat.st_uid, "mode": oct(mode_bits), "reason": "foreign_owner"})
            continue

        # Regular file. A file with no write bit set at all is a hard stop even for
        # root: that is the 0400/0600 root-owned artifact that broke 10-29.
        if mode_bits & 0o222 == 0:
            blocked.append({"path": key, "uid": stat.st_uid, "mode": oct(mode_bits), "reason": "mode_denies_write"})
            continue
        if not os.access(target, os.R_OK):
            blocked.append({"path": key, "uid": stat.st_uid, "mode": oct(mode_bits), "reason": "not_readable"})
            continue
        if not os.access(target, os.W_OK):
            blocked.append({"path": key, "uid": stat.st_uid, "mode": oct(mode_bits), "reason": "not_writable"})
            continue
        if stat.st_uid != euid:
            warnings.append({"path": key, "uid": stat.st_uid, "mode": oct(mode_bits), "reason": "foreign_owner"})

    if blocked:
        payload = json.dumps(blocked, ensure_ascii=False)
        raise RuntimeError(f"pipeline_preflight_unwritable_targets: {payload}")

    if warnings:
        logging.warning("pipeline_preflight_foreign_owner: %s", json.dumps(warnings, ensure_ascii=False))
    return {"checked": checked, "warnings": warnings}


def _lock_path(public_root: Path) -> Path:
    """Where the single-writer lock lives.

    `public_root/data/` and NOT `data/reddit-voc/`: in symlink mode the latter is
    the generation pointer, which is replaced at commit. A lock file inside it
    would move to the new generation mid-run, so a second process would take a
    lock on a different inode and both would proceed. It would also be published
    with the data.

    Overridable so a test (or a second site root) can point elsewhere.
    """
    override = os.getenv("PIPELINE_LOCK_PATH", "").strip()
    if override:
        return Path(override)
    return public_root / "data" / "reddit-voc.lock"


class PipelineLock:
    """Exclusive, non-blocking single-writer lock for one pipeline run.

    Two overlapping runs would each open a generation, then each commit -- the
    second `os.replace` wins and the first run's tree is orphaned while the
    site briefly serves content from a run that reported success. systemd's
    timer only covers scheduled runs; manual re-runs are routine (there was one
    at 19:01 on 10-29), and they can overlap a long scheduled run.

    Non-blocking on purpose: a queued second run would start hours late and
    publish stale data under a fresh timestamp. Failing fast with a distinct
    exit code lets the operator decide.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fd: int | None = None
        self.acquired = False

    def acquire(self) -> bool:
        """Take the lock, or return False if another run holds it.

        Only EWOULDBLOCK/EAGAIN means contention. Every other failure -- a lock
        file owned by another user, a filesystem without flock support, I/O
        error -- is raised, not reported as "another run is active": telling the
        operator to wait, forever, for a run that does not exist is worse than a
        crash that names the real problem.
        """
        # The parent must exist before the lock can be created; a missing
        # directory is not a contention signal, so let it raise.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # O_CLOEXEC matters: this fd is inherited by every child process
        # otherwise, and a child holding the fd keeps the flock alive after the
        # pipeline exits, wedging all subsequent runs until the child ends.
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(self.path, flags, 0o644)
        except PermissionError:
            # A lock created by another user (a one-off `sudo` run is routine on
            # this host) cannot be opened O_RDWR. Fall back to read-only: flock
            # an existing fd does not need write access, and the file's content
            # is never read or written.
            try:
                fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            except OSError as exc:
                raise RuntimeError(
                    f"pipeline_lock_unusable:{self.path}:{exc.strerror}"
                ) from exc
        except OSError as exc:
            raise RuntimeError(f"pipeline_lock_unusable:{self.path}:{exc.strerror}") from exc

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                return False
            raise RuntimeError(
                f"pipeline_lock_unavailable:{self.path}:{exc.strerror}"
            ) from exc
        self._fd = fd
        self.acquired = True
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(self._fd)
            self._fd = None
            self.acquired = False

    def __enter__(self) -> "PipelineLock":
        # Acquire on entry. Returning self without locking made `with
        # PipelineLock(...)` silently unlocked, which is the exact bug this class
        # exists to prevent.
        if not self.acquire():
            raise RuntimeError(f"pipeline_lock_held:{self.path}")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def run_pipeline(*, store_path: Path, public_root: Path, output_dir: Path, skip_feishu: bool = False) -> dict:
    started = datetime.now(timezone.utc)
    window_start, window_end, run_id, report_date, run_kind, trigger = _t1_bounds(started)
    run_id = _unique_run_id(run_id, output_dir)
    receipts: list[dict] = []
    errors: list[dict] = []

    # Before any write, including collection. An aborted run must leave nothing
    # behind: no rows, no generation, no pointer move.
    lock = PipelineLock(_lock_path(public_root))
    if not lock.acquire():
        abort = {
            "schema_version": PIPELINE_SCHEMA,
            "run_id": run_id,
            "run_kind": run_kind,
            "trigger": trigger,
            "report_date": report_date,
            "window_start_utc": window_start.isoformat(),
            "window_end_utc": window_end.isoformat(),
            "started_at_utc": started.isoformat(),
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "aborted_already_running",
            "lock_path": str(lock.path),
            "steps": [],
            "errors": [],
        }
        logging.error("pipeline_aborted_already_running: %s", lock.path)
        return abort

    try:
        return _run_pipeline_locked(
            store_path=store_path,
            public_root=public_root,
            output_dir=output_dir,
            skip_feishu=skip_feishu,
            started=started,
            window_start=window_start,
            window_end=window_end,
            run_id=run_id,
            run_kind=run_kind,
            trigger=trigger,
            report_date=report_date,
            receipts=receipts,
            errors=errors,
        )
    finally:
        lock.release()


def _run_pipeline_locked(
    *,
    store_path: Path,
    public_root: Path,
    output_dir: Path,
    skip_feishu: bool,
    started: datetime,
    window_start: datetime,
    window_end: datetime,
    run_id: str,
    run_kind: str,
    trigger: str,
    report_date: str,
    receipts: list[dict],
    errors: list[dict],
) -> dict:
    """The body of a run that holds the writer lock."""
    mode = _generation_mode()
    tx = None
    release_doc_holder: dict = {}

    def _data_root() -> Path | None:
        """The staged generation root, or None in off mode.

        Resolved at call time inside each step lambda, so a failed
        begin_generation stops the run instead of letting the next step write the
        live tree with data_root=None.
        """
        if mode == "off":
            return None
        if tx is None:
            raise RuntimeError("pipeline_generation_not_started")
        return tx.root

    _preflight_writability(public_root, store_path, output_dir, mode=mode)

    # ADR-002 Phase B: Step 3.5 recompute_derivatives runs before pointer advance,
    # so pointer/content parity is maintained. Guard remains available as a kill-switch.
    pointer_guard = os.getenv("PIPELINE_DISABLE_POINTER_ADVANCE", "") == "1"
    if pointer_guard:
        receipts.append({
            "step": "advance_pointer",
            "status": "skipped_by_kill_switch",
            "reason": "PIPELINE_DISABLE_POINTER_ADVANCE=1",
        })

    def _begin_generation() -> dict:
        """Open a release generation after collection, before any data write.

        Collection has already committed to SQLite, which lives outside
        public_root on purpose: rows must survive a failed publish. Everything
        after this point writes into the new generation, so agent-studio, the
        merged snapshot and every derivative are published together or not at all.
        """
        nonlocal tx
        sys.path.insert(0, str(ROOT / "scripts"))
        from daily_release_transaction import begin_generation

        tx = begin_generation(public_root, run_id=run_id)
        return {
            "step": "begin_generation",
            "status": "ok",
            "generation_id": tx.generation_id,
            "root": str(tx.root),
        }

    steps = [
        ("collect", lambda: step1_collect(store_path, run_id)),
    ]
    if mode == "symlink":
        steps.append(("begin_generation", _begin_generation))
    steps.extend([
        ("agents", lambda: step2_agents(store_path, run_id, output_dir, data_root=_data_root())),
        ("merge_snapshot", lambda: step3_merge_snapshot(run_id, store_path, public_root, data_root=_data_root())),
        ("recompute_derivatives", lambda: step3_5_recompute_derivatives(public_root, data_root=_data_root())),
    ])
    if not pointer_guard:
        steps.append(("advance_pointer", lambda: step4_advance_pointer(
            public_root, run_id, data_root=_data_root(), release_doc_holder=release_doc_holder,
        )))
    # Release-pinned query index (T6'): built from the freshly published
    # generation so @Echo 问数 serves the same data_as_of the site does.
    # Non-critical: a failed build must not fail the publish receipt (K1), the
    # bot keeps serving the previous index until the next successful rebuild.
    if not pointer_guard:
        steps.append(("build_query_index", lambda: _build_query_index_step(run_id)))
    # In symlink mode the card is built after the commit decision, so it can never
    # describe a generation that was not published.
    if not skip_feishu and mode == "off":
        # `receipts` is passed by reference, so the card sees the steps collected
        # so far. It cannot see the final status: in off mode the receipt file is
        # written after the loop, so the builder reads an `unavailable` receipt.
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

    commit_receipt: dict | None = None
    if mode == "symlink":
        # Exactly one publish point for the whole run, and it lives here rather
        # than inside the loop: every write has finished, so the readiness
        # contract can be judged once against the final receipts.
        failures = [
            r["step"] for r in receipts
            if isinstance(r, dict)
            and r.get("step") in POINTER_PREREQUISITES
            and str(r.get("status")) not in READY_STATUSES
        ]
        advance_ok = any(
            isinstance(r, dict) and r.get("step") == "advance_pointer" and r.get("status") == "advanced"
            for r in receipts
        )

        # Build stamps must be written BEFORE the commit: they live inside the
        # generation, so a stamp written afterwards would describe a tree that
        # was already published without one. Each stamp makes the dataset prove
        # which run produced it, which is the evidence a freshness monitor needs
        # and the tree has never carried.
        if not pointer_guard and not errors and tx is not None and release_doc_holder.get("document"):
            try:
                sys.path.insert(0, str(ROOT / "scripts"))
                from build_receipt import collect_dataset_stamps

                stamped = collect_dataset_stamps(
                    tx.root,
                    release_doc_holder["document"],
                    run_id=run_id,
                    period_end_utc=window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    generated_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
                receipts.append({
                    "step": "build_stamps",
                    "status": "ok",
                    "datasets": sorted(stamped),
                })
            except Exception as exc:
                # A missing stamp is a monitoring gap, not a data defect: the
                # bytes being published are fine. Record it and keep going, so
                # stamp trouble never withholds a release the site needs.
                logging.warning("build stamps failed: %s", exc)
                receipts.append({
                    "step": "build_stamps",
                    "status": "error",
                    "error": str(exc),
                })

        if pointer_guard:
            commit_receipt = {"step": "commit_generation", "status": "skipped_by_kill_switch"}
        elif errors or tx is None or release_doc_holder.get("document") is None or failures or not advance_ok:
            commit_receipt = {
                "step": "commit_generation",
                "status": "blocked_by_prerequisites",
                "failed_prerequisites": failures,
                "run_errors": [r.get("step") for r in errors],
            }
        else:
            try:
                tx.commit(release_doc_holder["document"])
                commit_receipt = {
                    "step": "commit_generation",
                    "status": "committed",
                    "generation_id": tx.generation_id,
                    "root": str(tx.root),
                }
            except Exception as exc:
                commit_receipt = {
                    "step": "commit_generation",
                    "status": "error",
                    "error": str(exc),
                    "traceback": traceback.format_exc()[-1500:],
                }
                errors.append(commit_receipt)
        receipts.append(commit_receipt)

        # Collect old generations after a successful publish. Without this the
        # tree grows by a full copy (645M in production) every day, and nobody
        # runs gc by hand: the disk would fill in about two months. Only runs
        # that actually committed clean up -- a failed run's generation is the
        # evidence of what went wrong, so it is kept until the next good run.
        if commit_receipt.get("status") == "committed":
            try:
                from daily_release_transaction import gc

                removed = gc(public_root, keep=2)
                receipts.append({
                    "step": "gc_generations",
                    "status": "ok",
                    "removed": removed,
                    "kept": 2,
                })
            except Exception as exc:
                # Cleanup must never fail a published run.
                logging.warning("generation gc failed (disk pressure will follow): %s", exc)
                receipts.append({"step": "gc_generations", "status": "error", "error": str(exc)})

        if not skip_feishu:
            # After the publish decision, and not counted as a run error: the data
            # is already live, so a card failure must not mark the release failed.
            #
            # The in-memory receipt is handed to the builder so it can report the
            # run's real outcome. It cannot be written to disk first: this block
            # runs before the receipt is final, and re-reading the file here is
            # exactly the race that made 2026-10-29's green run render red.
            live_receipt = {
                "schema_version": PIPELINE_SCHEMA,
                "run_id": run_id,
                "run_kind": run_kind,
                "trigger": trigger,
                "report_date": report_date,
                "status": "success" if not errors else "failed",
                "steps": list(receipts),
                "errors": list(errors),
            }
            try:
                receipts.append(step5_feishu_push(
                    run_id, report_date, receipts, output_dir, receipt=live_receipt,
                ))
            except Exception as exc:
                receipts.append({
                    "step": "feishu_push",
                    "status": "error",
                    "error": str(exc),
                    "traceback": traceback.format_exc()[-1500:],
                })

    finished = datetime.now(timezone.utc)
    if mode == "symlink":
        # A run only succeeded if it published. "partial" is not a success state
        # here: the caller's exit code decides whether anyone investigates.
        committed = commit_receipt is not None and commit_receipt.get("status") in (
            "committed", "skipped_by_kill_switch",
        )
        status = "success" if (not errors and committed) else "failed"
    else:
        status = "success" if not errors else f"partial_{len(errors)}_step_errors"

    receipt_doc = {
        "schema_version": PIPELINE_SCHEMA,
        "run_id": run_id,
        "run_kind": run_kind,
        "trigger": trigger,
        "report_date": report_date,
        "window_start_utc": window_start.isoformat(),
        "window_end_utc": window_end.isoformat(),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "status": status,
        "steps": receipts,
        "errors": errors,
    }
    if mode == "symlink":
        receipt_doc["release_transaction"] = {
            "mode": mode,
            "generation_id": tx.generation_id if tx is not None else None,
            "root": str(tx.root) if tx is not None else None,
            "commit": commit_receipt,
        }
    # L5-T04: a run-level receipt is the evidence the freshness monitor reads.
    # It is written after the commit decision (so its steps include the commit)
    # and inside the generation (so a successful publish carries it). A failed
    # write is an error, not a warning: the run's evidence is incomplete.
    release_doc = None
    if not pointer_guard:
        if mode == "symlink":
            release_doc = release_doc_holder.get("document")
        else:
            try:
                release_doc = json.loads(
                    (public_root / "data" / "reddit-voc" / "current-release.json")
                    .read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                release_doc = None
    try:
        run_receipt_step = _write_run_build_receipt(
            public_root=public_root,
            mode=mode,
            tx=tx,
            release_doc=release_doc,
            receipt_doc=receipt_doc,
            period_end_utc=window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except Exception as exc:  # noqa: BLE001 - the run must report incomplete evidence
        run_receipt_step = {
            "step": "write_build_receipt",
            "status": "error",
            "error": str(exc),
        }
        errors.append(run_receipt_step)
        receipt_doc["status"] = "failed"
        receipt_doc["errors"] = errors
        logging.error("run build receipt failed: %s", exc)
    receipt_doc["steps"].append(run_receipt_step)

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
    # Exit codes are a contract for the operator and for systemd:
    #   0 success | 1 the run failed | 3 another run holds the lock (nothing ran)
    # 3 is distinct so a contended run is not mistaken for a data failure and
    # investigated as one; rerunning later is the whole remedy.
    if receipt["status"] == "success":
        return 0
    if receipt["status"] == "aborted_already_running":
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
