"""Batch runner and dispatch orchestrator for Reddit VOC Multi-Agent System."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .competitor_radar import CompetitorRadarAgent
from .content_scout import ContentScoutAgent
from .contracts import (
    CompetitorRadarResult,
    ContentScoutResult,
    RndVocResult,
)
from .rnd_voc import RndVocAgent

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/agent_settings.json")

# Concurrent posts when an LLM client is attached. Measured 2026-10-31 against
# tokenhub/deepseek-v4-flash with reasoning off, same results at every level:
#   1 worker : 35.0 s/post  -> ~45 min for a 78-post day
#   4 workers:  8.5 s/post  -> ~11 min
#   8 workers:  7.2 s/post  ->  ~9 min
# Eight is the knee of the curve; past it the provider latency dominates and the
# gain is noise.
#
# Even 9 minutes does not fit the current 30-minute unit on its own: the
# non-LLM part of a recent production run took 27.8-29.6 minutes (see
# daily_collect_2026102{9,30}_0700 receipts). Enabling this requires raising
# TimeoutStartSec -- the baseline is already at the edge without it.
DEFAULT_LLM_WORKERS = 8


@dataclass(frozen=True)
class BatchAgentOutput:
    """Consolidated outputs from running agents over a batch of posts."""

    run_id: str
    total_posts_analyzed: int
    content_scout_results: Sequence[ContentScoutResult] = field(default_factory=list)
    rnd_voc_results: Sequence[RndVocResult] = field(default_factory=list)
    competitor_radar_results: Sequence[CompetitorRadarResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_posts_analyzed": self.total_posts_analyzed,
            "content_scout_results": [r.to_dict() for r in self.content_scout_results],
            "rnd_voc_results": [r.to_dict() for r in self.rnd_voc_results],
            "competitor_radar_results": [r.to_dict() for r in self.competitor_radar_results],
        }


class AgentBatchRunner:
    """Orchestrates multi-agent analysis over posts and persists structured business artifacts."""

    def __init__(
        self,
        *,
        client: Any = None,
        config_path: Path | None = None,
    ) -> None:
        self.client = client
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.config = self._load_config()

        self.scout_agent = ContentScoutAgent(client=self.client)
        self.rnd_agent = RndVocAgent(client=self.client)
        self.radar_agent = CompetitorRadarAgent(client=self.client)

    def _load_config(self) -> Mapping[str, Any]:
        if self.config_path.exists():
            try:
                return json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", self.config_path, exc)
        return {}

    def run_batch(
        self,
        posts: Sequence[Mapping[str, Any]],
        *,
        run_id: str = "batch_run_default",
        max_workers: int | None = None,
    ) -> BatchAgentOutput:
        """Route posts to relevant specialized agents based on heuristic rules.

        Posts are processed concurrently when an LLM client is attached.

        This is a timeout decision, not a latency preference. Measured on
        tokenhub/deepseek-v4-flash with reasoning disabled (2026-10-31):

            serial   : 35.0 s/post -> ~45 min for a 78-post day
            workers=8:  7.2 s/post ->  ~9 min for the same day

        The systemd unit stops this service at 30 minutes, and the non-LLM part
        of a recent run already took 27.8-29.6 minutes. Serial LLM calls would
        be killed mid-run every day; concurrency brings the total within reach
        only once TimeoutStartSec is raised.

        Results keep input order regardless of completion order, so the
        artifacts are deterministic. With `client=None` there is nothing to wait
        on and the post loop runs inline, exactly as before.
        """
        scout_results: list[ContentScoutResult] = []
        rnd_results: list[RndVocResult] = []
        radar_results: list[CompetitorRadarResult] = []

        competitor_keywords: list[str] = []
        for comp in self.config.get("competitors", []):
            competitor_keywords.extend([alias.lower() for alias in comp.get("aliases", [])])
        if not competitor_keywords:
            competitor_keywords = ["elvie", "willow", "spectra", "medela", "lansinoh"]

        if self.client is None or len(posts) <= 1:
            per_post = [self._analyze_one(post, competitor_keywords) for post in posts]
        else:
            from concurrent.futures import ThreadPoolExecutor

            workers = max_workers if max_workers is not None else DEFAULT_LLM_WORKERS
            workers = max(1, min(workers, len(posts)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                per_post = list(pool.map(
                    lambda post: self._analyze_one(post, competitor_keywords), posts
                ))

        for scout, rnd, radar in per_post:
            if scout is not None:
                scout_results.append(scout)
            if rnd is not None:
                rnd_results.append(rnd)
            if radar is not None:
                radar_results.append(radar)

        return BatchAgentOutput(
            run_id=run_id,
            total_posts_analyzed=len(posts),
            content_scout_results=scout_results,
            rnd_voc_results=rnd_results,
            competitor_radar_results=radar_results,
        )

    def _analyze_one(self, post: Mapping[str, Any], competitor_keywords: Sequence[str]):
        """Run every agent this post routes to, returning (scout, rnd, radar).

        Pure with respect to `self`: it reads the configured agents and returns
        results, so it is safe to call from several threads at once. Each agent
        holds only a client reference, and the client opens its own connection
        per request.
        """
        post_id = str(post.get("post_id", "unknown"))
        subreddit = str(post.get("subreddit", "r/ExclusivelyPumping"))
        title = str(post.get("title", ""))
        content = str(post.get("selftext", "") or post.get("content", ""))
        text_lower = (title + " " + content).lower()

        scout_res = rnd_res = radar_res = None

        # 1. R&D Defect Routing: Contains defect/leak/noise/suction/broken/valve indicators
        if any(k in text_lower for k in ("leak", "spill", "noise", "loud", "squeak", "suction", "broken", "valve", "tear", "defect")):
            res = self.rnd_agent.analyze(
                post_id=post_id,
                subreddit=subreddit,
                title=title,
                content=content,
            )
            if res.defects:
                rnd_res = res

        # 2. Competitor Intelligence Routing: Mentions competitor brand aliases
        if any(comp in text_lower for comp in competitor_keywords):
            res = self.radar_agent.analyze(
                post_id=post_id,
                subreddit=subreddit,
                title=title,
                content=content,
            )
            if res.comparisons:
                radar_res = res

        # 3. Content Scout Routing: General pain points, high interest or specific questions
        if any(k in text_lower for k in ("recommend", "worth it", "vs", "help", "work", "office", "hate", "love", "leak", "secret")):
            res = self.scout_agent.scout(
                post_id=post_id,
                subreddit=subreddit,
                title=title,
                content=content,
            )
            if res.ideas:
                scout_res = res

        return scout_res, rnd_res, radar_res

    def persist_artifacts(
        self,
        output: BatchAgentOutput,
        output_dir: Path,
    ) -> Mapping[str, Path]:
        """Atomically persist separate JSON artifacts for each business domain."""
        output_dir.mkdir(parents=True, exist_ok=True)
        files = {}

        # 1. Content Ideas artifact for social media marketing teams
        ideas_file = output_dir / f"{output.run_id}-daily-content-ideas.json"
        ideas_payload = {
            "run_id": output.run_id,
            "total_topics": sum(len(r.ideas) for r in output.content_scout_results),
            "results": [r.to_dict() for r in output.content_scout_results],
        }
        ideas_file.write_text(json.dumps(ideas_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files["content_ideas"] = ideas_file

        # 2. R&D Defect Tickets artifact for engineering and QA
        rnd_file = output_dir / f"{output.run_id}-daily-rnd-tickets.json"
        rnd_payload = {
            "run_id": output.run_id,
            "total_defects": sum(len(r.defects) for r in output.rnd_voc_results),
            "results": [r.to_dict() for r in output.rnd_voc_results],
        }
        rnd_file.write_text(json.dumps(rnd_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files["rnd_tickets"] = rnd_file

        # 3. Competitor Radar artifact for marketing and sales
        radar_file = output_dir / f"{output.run_id}-daily-competitor-radar.json"
        radar_payload = {
            "run_id": output.run_id,
            "total_comparisons": sum(len(r.comparisons) for r in output.competitor_radar_results),
            "results": [r.to_dict() for r in output.competitor_radar_results],
        }
        radar_file.write_text(json.dumps(radar_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files["competitor_radar"] = radar_file

        return files
