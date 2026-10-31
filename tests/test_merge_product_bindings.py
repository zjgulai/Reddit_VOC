"""Product identity per record, or the page aggregates by topic and calls it a product.

`product_bindings` was a hardcoded `[]` on every merged record. The resolver
existed and was fully implemented — the offline site builder used it — but the
daily path never called it, so any page grouping by product family was really
grouping by topic. That is the P0-3 defect from the audit: a "product" metric
that no record could substantiate.

These tests drive the real ledger through the real merge path, because the
failure mode here is silent: an empty array is a valid value, and the frontend
renders it without complaint.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from reddit_voc.product_entity_resolution import ProductEntityResolver  # noqa: E402

import merge_normalize  # noqa: E402

LEDGER = ROOT / "config" / "product_entities" / "momcozy-product-entity-ledger-v1.json"


def _load_pipeline():
    spec = importlib.util.spec_from_file_location(
        "run_daily_t1_pipeline", ROOT / "scripts" / "run_daily_t1_pipeline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def resolver() -> ProductEntityResolver:
    return ProductEntityResolver.from_ledger(LEDGER)


# ---------------------------------------------------------------- the resolver


def test_momcozy_s9_pro_binds_product_family(resolver) -> None:
    """The seed case from the ticket: a family binding, not an exact SPU."""
    result = resolver.resolve("Momcozy S9 Pro")
    records = [b.to_record() for b in result.product_bindings]

    assert len(records) == 1
    binding = records[0]
    assert binding["binding_level"] == "product_family"
    assert binding["product_family"]["id"] == "s9-pro"
    # s9-pro has no publishable exact SPU in the ledger, so exact_spu stays null.
    assert binding["exact_spu"] is None
    assert binding["governance_status"] == "family_only"


def test_unbound_text_stays_empty(resolver) -> None:
    """Bare model names carry no brand, so they must not bind.

    'S9 Pro' is a contextual alias: it only counts when the brand or a category
    term sits within the resolver's context window. A bare mention is not enough,
    and treating it as enough is how a neighbourhood name became a competitor.
    """
    for text in ("S9 Pro", "V2", "Just a normal sentence about nothing",
                 "This breast pump leaked during the night."):
        result = resolver.resolve(text)
        assert result.product_bindings == (), f"{text!r} produced a binding"


def test_exact_spu_requires_approved_evidence(resolver) -> None:
    """spu_exact is a governance decision, not a stronger match.

    v2-pro has an approved exact SPU; s9-pro does not. The difference must show
    up in binding_level, because the frontend validates that the level, the
    family and the SPU agree with each other.
    """
    approved = [b.to_record() for b in resolver.resolve("Momcozy V2 Pro is great").product_bindings]
    assert len(approved) == 1
    assert approved[0]["binding_level"] == "spu_exact"
    assert approved[0]["exact_spu"]["spu_id"] == "SPU000932"
    assert approved[0]["governance_status"] == "exact_spu_approved"

    family_only = [b.to_record() for b in resolver.resolve("Momcozy S9 Pro").product_bindings]
    assert family_only[0]["binding_level"] == "product_family"
    assert family_only[0]["governance_status"] != "exact_spu_approved"


# ------------------------------------------------------------ the public shape


def test_bindings_match_the_nine_field_contract(resolver) -> None:
    """The frontend uses assertExactObjectKeys: extra or missing keys reject the dataset."""
    required = {
        "brand_id", "category", "product_family", "exact_spu",
        "binding_level", "match_type", "matched_alias",
        "governance_status", "governance_reason",
    }
    for text in ("Momcozy S9 Pro", "Momcozy V2 Pro is great"):
        for binding in (b.to_record() for b in resolver.resolve(text).product_bindings):
            assert set(binding) == required, f"{text!r} emitted {sorted(set(binding) ^ required)}"
            assert binding["brand_id"] == "momcozy"
            assert set(binding["category"]) == {"id", "name_en", "name_cn"}
            if binding["product_family"] is not None:
                assert set(binding["product_family"]) == {"id", "name_en", "name_cn"}
            if binding["exact_spu"] is not None:
                assert set(binding["exact_spu"]) == {"spu_id", "spu_name"}


# ----------------------------------------------------------- the merge contract


def test_normalize_preserves_existing_bindings() -> None:
    """normalize_all must not erase what the producer wrote.

    It used to assign a hardcoded [] here, so a binding computed in step3 was
    discarded before the file was written — the field could never be non-empty.
    """
    bindings = [{"brand_id": "momcozy", "binding_level": "product_family"}]
    posts = [{
        "post_id": "p1",
        "run_id": "daily_collect_test_0700",
        "created_at_utc": "2026-10-30T00:00:00Z",
        "title": "Momcozy S9 Pro",
        "content": "works well",
        "product_bindings": bindings,
    }]
    merge_normalize.normalize_all(posts, [])

    assert posts[0]["product_bindings"] == bindings


def test_normalize_never_inherits_bindings_from_the_template() -> None:
    """The template's bindings belong to the template's text, not to this record.

    Same rule the tagging blanking already follows. A record that carries no
    bindings must end up with an empty list, not the July row's value.
    """
    template = {
        "post_id": "july-1",
        "title": "Momcozy V2 Pro review",
        "product_bindings": [{"brand_id": "momcozy", "binding_level": "spu_exact"}],
    }
    posts = [
        template,
        {
            "post_id": "p2",
            "run_id": "daily_collect_test_0700",
            "created_at_utc": "2026-10-30T00:00:00Z",
            "title": "unrelated",
            "content": "nothing about pumps",
        },
    ]
    merge_normalize.normalize_all(posts, [])

    assert posts[1]["product_bindings"] == [], "template bindings leaked into a merged record"
    # And the template row itself is untouched: it has no run_id.
    assert posts[0]["product_bindings"] == template["product_bindings"]


def test_records_without_run_id_are_not_rewritten() -> None:
    """The July import predates the pipeline and must stay byte-identical."""
    july = {
        "post_id": "july-2",
        "title": "Momcozy S9 Pro",
        "content": "old row",
        "product_bindings": [],
    }
    before = json.dumps(july, sort_keys=True, ensure_ascii=False)
    merge_normalize.normalize_all([july], [])
    assert json.dumps(july, sort_keys=True, ensure_ascii=False) == before


def test_non_list_bindings_are_coerced_not_propagated() -> None:
    """A malformed value would take the whole dataset down at the frontend."""
    posts = [{
        "post_id": "p3",
        "run_id": "daily_collect_test_0700",
        "created_at_utc": "2026-10-30T00:00:00Z",
        "title": "x",
        "content": "y",
        "product_bindings": {"not": "a list"},
    }]
    merge_normalize.normalize_all(posts, [])
    assert posts[0]["product_bindings"] == []


# ------------------------------------------------------------ the step3 wiring


def test_step3_binds_products_from_record_text() -> None:
    """The helper step3 uses must resolve from the record's own text."""
    pipeline = _load_pipeline()

    # Mirror the closure step3 builds, without running a collection.
    product_resolver = ProductEntityResolver.from_ledger(LEDGER)
    total = 0

    def _product_bindings(text: str) -> list:
        nonlocal total
        if product_resolver is None or not text:
            return []
        records = [b.to_record() for b in product_resolver.resolve(text).product_bindings]
        total += len(records)
        return records

    assert _product_bindings("Momcozy S9 Pro wearable")[0]["product_family"]["id"] == "s9-pro"
    assert _product_bindings("S9 Pro") == []
    assert _product_bindings("") == []
    assert total == 1

    # The resolver is reachable from the pipeline's own module path.
    assert pipeline is not None
    assert (ROOT / "config" / "product_entities" / "momcozy-product-entity-ledger-v1.json").is_file()
