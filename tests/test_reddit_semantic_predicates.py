import json
from pathlib import Path

import pytest

from reddit_voc.reddit_semantic_predicates import (
    TARGET_TAG_IDS,
    evaluate_assignment,
    load_policy,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/tagging/reddit-semantic-predicates-v1.json"
POLICY_V2_PATH = ROOT / "config/tagging/reddit-semantic-predicates-v2.json"
BASE_MANIFEST = ROOT / "data/processed/reddit_voc_site_snapshot_20260714/manifest.json"


@pytest.fixture(scope="module")
def policy():
    manifest = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    return load_policy(
        POLICY_PATH,
        expected_base_manifest_sha256="f04edef8dc73c8975e4bba56cbeefd8b734fd86f2c5a95aa2a041325503720ef",
        expected_dictionary_sha256=manifest["tagging"]["dictionary_sha256"],
    )


@pytest.fixture(scope="module")
def policy_v2():
    manifest = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    return load_policy(
        POLICY_V2_PATH,
        expected_base_manifest_sha256="f04edef8dc73c8975e4bba56cbeefd8b734fd86f2c5a95aa2a041325503720ef",
        expected_dictionary_sha256=manifest["tagging"]["dictionary_sha256"],
    )


@pytest.mark.parametrize(
    ("tag_id", "text", "keyword", "expected_status", "expected_reason"),
    [
        (
            "L2-PUMP-016",
            "I have elastic nipples and every flange pinches and hurts. I still feel full.",
            "elastic nipples",
            "confirmed",
            "elastic_fit_negative_outcome",
        ),
        (
            "L2-PUMP-016",
            "I have elastic nipples, but the M6 works well and never hurts me.",
            "elastic nipples",
            "rejected",
            "elastic_anatomy_without_negative_mismatch",
        ),
        (
            "L2-PUMP-016",
            (
                "The V2 cups work great with my elastic nipples. "
                "The Air 1 charging case was replaced. "
                "Silicone flanges just don't mesh with me."
            ),
            "elastic nipples",
            "needs_review",
            "material_preference_without_size_mismatch",
        ),
        (
            "L2-PUMP-016",
            (
                "I did have some nipple pain initially with the Eufy flanges, "
                "but it subsided within a few days."
            ),
            "nipple pain",
            "rejected",
            "resolved_or_correct_fit_counterevidence",
        ),
        (
            "L2-PUMP-016",
            (
                "I have the same problem with Spectra; every setting hurts. "
                "Does Medela Symphony help with elastic nipples? Any chance you had them?"
            ),
            "elastic nipples",
            "needs_review",
            "elastic_anatomy_question_without_self_binding",
        ),
        (
            "L2-PUMP-016",
            "The flange size is correct, although pumping still hurts.",
            "flange size",
            "rejected",
            "resolved_or_correct_fit_counterevidence",
        ),
        (
            "L2-PUMP-016",
            "I might have elastic nipples. Could that be the problem?",
            "elastic nipples",
            "needs_review",
            "suspected_fit_issue_without_confirmed_outcome",
        ),
        (
            "L2-PUMP-016",
            "The flange doesn't fit and is far too small.",
            "flange doesn't fit",
            "confirmed",
            "explicit_flange_size_or_fit_failure",
        ),
        (
            "L2-PUMP-016",
            "I have nipple pain after every pumping session.",
            "nipple pain",
            "needs_review",
            "flange_subject_binding_incomplete",
        ),
        (
            "L2-PUMP-016",
            "The flange causes nipple pain every time I pump.",
            "nipple pain",
            "confirmed",
            "elastic_fit_negative_outcome",
        ),
        (
            "L0-CHL-003",
            "The Momcozy washer is totally worth it for the price.",
            "worth it",
            "confirmed",
            "explicit_product_price_value_assertion",
        ),
        (
            "L0-CHL-003",
            "Is the Momcozy washer worth it?",
            "worth it",
            "rejected",
            "question_not_assertion",
        ),
        (
            "L0-CHL-003",
            "I am debating if splurging on a bottle washer is worth it.",
            "worth it",
            "rejected",
            "question_not_assertion",
        ),
        (
            "L0-CHL-003",
            "I just got a great deal on the Momcozy one used.",
            "great deal",
            "rejected",
            "discount_only_without_value_assertion",
        ),
        (
            "L0-CHL-003",
            "The pump strength may be worth it.",
            "worth it",
            "needs_review",
            "modal_value_claim",
        ),
        (
            "L0-CHL-003",
            "If the washer saves you time, it is absolutely worth it.",
            "worth it",
            "rejected",
            "conditional_value_claim",
        ),
        (
            "L0-CHL-003",
            "The carrier is worth it if it works with your body.",
            "worth it",
            "rejected",
            "conditional_value_claim",
        ),
        (
            "L0-CHL-003",
            "The washer may seem expensive, but it is definitely worth it for the price.",
            "worth it",
            "confirmed",
            "explicit_product_price_value_assertion",
        ),
        (
            "L0-CHL-003",
            "I pump for ten minutes longer, but it is absolutely worth it to be mobile.",
            "worth it",
            "rejected",
            "non_price_value_context",
        ),
        (
            "L0-CHL-003",
            "I paid $300 for the washer. It saves time and is absolutely worth it.",
            "worth it",
            "confirmed",
            "explicit_product_price_value_assertion",
        ),
        (
            "L0-CHL-003",
            "The extra twenty minutes was not worth it.",
            "worth it",
            "rejected",
            "negated_or_non_product_value",
        ),
        (
            "L0-CHL-003",
            "It was worth it for me.",
            "worth it",
            "needs_review",
            "value_subject_or_price_context_missing",
        ),
        (
            "L2-PUMP-030",
            "My Momcozy M5 gives me equal output as my Medela main pump.",
            "equal output",
            "confirmed",
            "momcozy_output_equal_or_better",
        ),
        (
            "L2-PUMP-030",
            "My Eufy gets better output than my Spectra.",
            "better output",
            "rejected",
            "wrong_brand_comparison",
        ),
        (
            "L2-PUMP-030",
            "My Momcozy M5 does not get better output than my Spectra; it gets less output.",
            "better output",
            "rejected",
            "momcozy_not_equal_or_better",
        ),
        (
            "L2-PUMP-030",
            "I get a better output as well.",
            "better output",
            "needs_review",
            "comparison_binding_incomplete",
        ),
        (
            "L2-PUMP-007",
            "I need to buy replacement parts for my Momcozy M5.",
            "replacement parts",
            "confirmed",
            "active_accessory_purchase_intent",
        ),
        (
            "L2-PUMP-007",
            "I bought replacement parts last month.",
            "replacement parts",
            "rejected",
            "past_accessory_purchase",
        ),
        (
            "L2-PUMP-007",
            "Insurance sends me free replacement parts every month.",
            "replacement parts",
            "rejected",
            "insurance_or_free_supply",
        ),
        (
            "L2-PUMP-007",
            "You should buy replacement parts before the trip.",
            "replacement parts",
            "rejected",
            "advice_to_other",
        ),
        (
            "L2-PUMP-007",
            "I'm concerned that replacement parts are not readily available.",
            "replacement parts",
            "needs_review",
            "availability_without_purchase_intent",
        ),
        (
            "L2-PUMP-007",
            "My friend needs to buy replacement parts before travelling.",
            "replacement parts",
            "needs_review",
            "purchase_subject_binding_incomplete",
        ),
        (
            "L2-PUMP-007",
            "My sister wants to get inserts for her pump.",
            "inserts",
            "needs_review",
            "purchase_subject_binding_incomplete",
        ),
    ],
)
def test_predicate_relation_cases(
    policy,
    tag_id: str,
    text: str,
    keyword: str,
    expected_status: str,
    expected_reason: str,
) -> None:
    result = evaluate_assignment(
        tag_id=tag_id,
        text=text,
        evidence_keywords=[keyword],
        policy=policy,
    )

    assert result.status == expected_status
    assert result.reason_code == expected_reason
    assert result.evidence_keywords == (keyword,)


def test_all_phrase_occurrences_are_considered(policy) -> None:
    result = evaluate_assignment(
        tag_id="L0-CHL-003",
        text=(
            "I first asked whether the washer was worth it. "
            "After using the Momcozy washer, it is totally worth it for the price."
        ),
        evidence_keywords=["worth it"],
        policy=policy,
    )

    assert result.status == "confirmed"
    assert result.reason_code == "explicit_product_price_value_assertion"
    assert result.sentence_indexes == (1,)


def test_comparison_does_not_bind_across_sentences(policy) -> None:
    result = evaluate_assignment(
        tag_id="L2-PUMP-030",
        text="My Momcozy V1 gives me better output. My Spectra is my main pump.",
        evidence_keywords=["better output"],
        policy=policy,
    )

    assert result.status == "needs_review"
    assert result.reason_code == "comparison_direction_incomplete"


def test_policy_is_exactly_bound_to_base_and_dictionary_hashes(tmp_path: Path) -> None:
    raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    raw["dictionary_sha256"] = "0" * 64
    tampered = tmp_path / "policy.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="dictionary sha256 mismatch"):
        load_policy(
            tampered,
            expected_base_manifest_sha256=raw["base_manifest_sha256"],
            expected_dictionary_sha256="22664c9c446ddfa17446852079f507ab75b5af3d4dde6e4e3f3e44c195582e14",
        )


def test_policy_target_set_is_frozen(policy) -> None:
    assert set(policy.target_tag_ids) == TARGET_TAG_IDS == {
        "L2-PUMP-016",
        "L0-CHL-003",
        "L2-PUMP-030",
        "L2-PUMP-007",
    }


def test_unknown_tag_fails_closed(policy) -> None:
    with pytest.raises(ValueError, match="not governed by predicate policy"):
        evaluate_assignment(
            tag_id="L0-SVC-010",
            text="Customer service replied.",
            evidence_keywords=["customer service"],
            policy=policy,
        )


@pytest.mark.parametrize(
    ("tag_id", "text", "keyword", "parent_text", "expected_status", "expected_reason"),
    [
        (
            "L2-PUMP-016",
            (
                "I don't find the flange comfortable and experience pinching. "
                "I have elastic nipples and tried multiple size inserts."
            ),
            "elastic nipples",
            None,
            "confirmed",
            "elastic_fit_negative_outcome",
        ),
        (
            "L0-CHL-003",
            "After a month of use, it is absolutely worth it.",
            "worth it",
            "Momcozy bottle washer review\nHas anyone used the washer pro?",
            "confirmed",
            "explicit_product_value_with_parent_grounding",
        ),
        (
            "L0-CHL-003",
            "I heard it is absolutely worth it.",
            "worth it",
            "Momcozy bottle washer review",
            "rejected",
            "hearsay_value_claim",
        ),
        (
            "L0-CHL-003",
            "It was absolutely worth it.",
            "worth it",
            "Night pumping schedule\nHow long do you keep trying?",
            "needs_review",
            "value_subject_or_price_context_missing",
        ),
        (
            "L2-PUMP-030",
            (
                "I use the Momcozy M5 for most sessions. "
                "I get the same amount of output as my Motif Luna wall pump."
            ),
            "same amount",
            None,
            "confirmed",
            "momcozy_output_equal_or_better_adjacent_binding",
        ),
        (
            "L2-PUMP-030",
            "I use a Momcozy M5. My Spectra gets better output.",
            "better output",
            None,
            "rejected",
            "wrong_brand_comparison",
        ),
        (
            "L2-PUMP-007",
            (
                "I primarily use Willow Gos lately and they work well during "
                "my second exclusively pumping journey with stretchier anatomy "
                "(need to get replacement parts for my Eufy)."
            ),
            "replacement parts",
            None,
            "confirmed",
            "active_accessory_purchase_intent_discourse_bound",
        ),
        (
            "L2-PUMP-007",
            "My sister uses a pump and needs to get replacement parts.",
            "replacement parts",
            None,
            "needs_review",
            "purchase_subject_binding_incomplete",
        ),
    ],
)
def test_v2_predicate_repairs_are_narrow_and_fail_closed(
    policy_v2,
    tag_id: str,
    text: str,
    keyword: str,
    parent_text: str | None,
    expected_status: str,
    expected_reason: str,
) -> None:
    result = evaluate_assignment(
        tag_id=tag_id,
        text=text,
        evidence_keywords=[keyword],
        policy=policy_v2,
        parent_text=parent_text,
    )

    assert result.status == expected_status
    assert result.reason_code == expected_reason


def test_v2_policy_declares_immutable_repair_dataset_version(policy_v2) -> None:
    assert policy_v2.repair_dataset_version == "reddit_voc_tag_repair_20260714_v2"
