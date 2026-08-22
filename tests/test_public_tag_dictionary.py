from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts/build_public_tag_dictionary.py"
SPEC = importlib.util.spec_from_file_location("build_public_tag_dictionary", BUILDER_PATH)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
PUBLIC_RULE_FIELDS = BUILDER.PUBLIC_RULE_FIELDS
build_public_dictionary = BUILDER.build_public_dictionary
SOURCE = (
    ROOT
    / "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc"
    / "reddit_voc_site_snapshot_20260714_v1/tag-dictionary.json"
)


def test_public_dictionary_is_an_allowlisted_projection() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    public_dictionary = build_public_dictionary(source)

    assert public_dictionary["schema_version"] == "reddit_voc_public_tag_dictionary_v1"
    assert public_dictionary["dictionary_version"] == source["dictionary_version"]
    assert public_dictionary["dictionary_sha256"] == source["dictionary_sha256"]
    assert len(public_dictionary["rules"]) == len(source["rules"])
    assert all(set(rule) == set(PUBLIC_RULE_FIELDS) for rule in public_dictionary["rules"])
    assert all(
        field not in rule
        for rule in public_dictionary["rules"]
        for field in ("keywords_en", "consumer_phrases", "biz_action", "strategy_package", "dept_owner")
    )
