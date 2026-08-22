from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


TagContext = tuple[str, str, tuple[str, ...]]

CATEGORY_TAG_CONTEXTS: dict[str, tuple[str, str]] = {
    "breast_pump": ("吸奶器", "吸奶器"),
    "bottle_washer": ("喂养电器", "消毒器"),
    # The governed tag dictionary currently misclassifies BM03 as a
    # thermometer. A non-existent category label deliberately admits L1 but
    # prevents the incorrect L2/SPU rows from becoming eligible.
    "baby_monitor": ("智能母婴电器", "婴儿监视器"),
}


class ProductTagContextError(ValueError):
    """A product binding cannot safely govern tag-dictionary eligibility."""


def _record(value: object, *, error: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ProductTagContextError(error)
    return value


def tag_contexts_from_product_bindings(
    bindings: Iterable[Mapping[str, Any]],
) -> tuple[TagContext, ...]:
    """Convert governed product bindings into fail-closed dictionary contexts."""

    spu_ids_by_context: dict[tuple[str, str], set[str]] = defaultdict(set)
    for binding in bindings:
        if binding.get("brand_id") != "momcozy":
            raise ProductTagContextError("product_binding_brand_invalid")
        category = _record(
            binding.get("category"), error="product_binding_category_invalid"
        )
        category_id = category.get("id")
        if not isinstance(category_id, str) or category_id not in CATEGORY_TAG_CONTEXTS:
            raise ProductTagContextError("product_binding_category_unsupported")
        context = CATEGORY_TAG_CONTEXTS[category_id]
        binding_level = binding.get("binding_level")
        governance_status = binding.get("governance_status")
        product_family = binding.get("product_family")
        exact_spu = binding.get("exact_spu")
        if binding_level == "category":
            if governance_status != "category_only":
                raise ProductTagContextError("category_binding_governance_invalid")
            if product_family is not None or exact_spu is not None:
                raise ProductTagContextError("category_binding_child_entity_present")
            spu_ids_by_context[context]
        elif binding_level == "spu_exact":
            if governance_status != "exact_spu_approved":
                raise ProductTagContextError("exact_spu_governance_invalid")
            _record(product_family, error="exact_spu_product_family_invalid")
            spu = _record(exact_spu, error="exact_spu_reference_invalid")
            spu_id = spu.get("spu_id")
            if not isinstance(spu_id, str) or not spu_id.strip():
                raise ProductTagContextError("exact_spu_id_invalid")
            spu_ids_by_context[context].add(spu_id.strip())
        elif binding_level == "product_family":
            _record(product_family, error="family_binding_product_family_invalid")
            if exact_spu is not None:
                raise ProductTagContextError("family_binding_exact_spu_present")
            if governance_status not in {"family_only", "taxonomy_blocked"}:
                raise ProductTagContextError("family_binding_governance_invalid")
            spu_ids_by_context[context]
        else:
            raise ProductTagContextError("product_binding_level_invalid")

    return tuple(
        (product_line, voc_category, tuple(sorted(spu_ids)))
        for (product_line, voc_category), spu_ids in sorted(spu_ids_by_context.items())
    )
