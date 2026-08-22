#!/usr/bin/env python3
"""Project the governed tag dictionary to the fields needed by the public UI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PUBLIC_RULE_FIELDS = (
    "tag_id",
    "name_cn",
    "name_en",
    "theme",
    "sentiment",
    "tag_scope",
)


def build_public_dictionary(source: dict[str, Any]) -> dict[str, Any]:
    rules = source.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("source dictionary rules must be a non-empty list")

    public_rules: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"source rule {index} must be an object")
        public_rule = {field: rule.get(field) for field in PUBLIC_RULE_FIELDS}
        if any(not isinstance(value, str) or not value for value in public_rule.values()):
            raise ValueError(f"source rule {index} is missing a public field")
        tag_id = public_rule["tag_id"]
        if tag_id in seen_ids:
            raise ValueError(f"duplicate tag_id: {tag_id}")
        seen_ids.add(tag_id)
        public_rules.append(public_rule)

    return {
        "schema_version": "reddit_voc_public_tag_dictionary_v1",
        "dictionary_version": source["dictionary_version"],
        "dictionary_sha256": source["dictionary_sha256"],
        "projection": {
            "audience": "public_ui",
            "source_schema_version": source["schema_version"],
            "rule_fields": list(PUBLIC_RULE_FIELDS),
            "internal_strategy_fields_excluded": True,
        },
        "rules": public_rules,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    public_dictionary = build_public_dictionary(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(public_dictionary, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
