from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoopComponent:
    name: str
    purpose: str
    configured_for: str
    gate: str


DEFAULT_LOOP_COMPONENTS = [
    LoopComponent(
        name="objective",
        purpose="Define the bounded business outcome for the loop.",
        configured_for="Daily Reddit VOC digest for Momcozy and wearable pump category.",
        gate="No scope expansion beyond read-only Reddit evidence and DingTalk digest.",
    ),
    LoopComponent(
        name="state",
        purpose="Persist what the loop knows and what evidence exists.",
        configured_for="SQLite tables plus .kiro plan/progress/findings and local artifacts.",
        gate="No production DB writes; no secret-bearing state in repo artifacts.",
    ),
    LoopComponent(
        name="policy",
        purpose="Decide allowed actions, fallback order, and stop conditions.",
        configured_for="Browser JSON first, DOM fallback, TikHub gated fallback, RSS discovery fallback.",
        gate="Stop on login wall, CAPTCHA, provider call need, or DingTalk live-send need.",
    ),
    LoopComponent(
        name="executor",
        purpose="Run the next smallest action safely.",
        configured_for="Local dry-run CLI, fixtures, read-only smoke, and adapter execution.",
        gate="Default to dry-run; credentialed browser read needs explicit user confirmation.",
    ),
    LoopComponent(
        name="evaluator",
        purpose="Measure loop outcome before deciding next iteration.",
        configured_for="Unit tests, fixture counts, coverage grade, artifact presence, and boundary labels.",
        gate="Do not promote partial/read-only evidence to production acceptance.",
    ),
]


def loop_config_markdown() -> str:
    lines = [
        "# Loop Engineering Configuration",
        "",
        "| Component | Purpose | Configuration | Gate |",
        "|---|---|---|---|",
    ]
    for component in DEFAULT_LOOP_COMPONENTS:
        lines.append(
            f"| {component.name} | {component.purpose} | {component.configured_for} | {component.gate} |"
        )
    return "\n".join(lines)

