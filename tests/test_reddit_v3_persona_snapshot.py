from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.v3_persona_inference import (
    load_persona_cohort_config,
    load_persona_dictionary,
)
from reddit_voc.v3_persona_snapshot import PersonaSnapshotError
from scripts.build_reddit_personas_snapshot import (
    build_v3,
    write_v3_snapshot,
)
from scripts.validate_reddit_personas_snapshot import validate_v3


ROOT = Path(__file__).resolve().parents[1]
DICTIONARY_PATH = ROOT / "data/reference/reddit-voc-v3/dim_persona_v1.csv"
CONFIG_PATH = ROOT / "config/personas/reddit-voc-persona-cohorts-v3.json"
REFERENCE_MANIFEST_PATH = ROOT / "data/reference/reddit-voc-v3/manifest.json"


def _post(post_id: str, text: str) -> dict[str, object]:
    return {
        "analysis_fields": {
            "current_comment_body": "",
            "post_body": text,
            "post_title": "",
        },
        "analysis_text_status": "ready",
        "canonical_entity_id": f"t3_{post_id}",
        "comment_id": None,
        "post_id": post_id,
        "schema_version": "reddit_voc_fielded_voc_v1",
        "thread_id": post_id,
        "voc_id": f"post:{post_id}",
        "voc_type": "post_voc",
    }


def _comment(comment_id: str, text: str, post_id: str = "root") -> dict[str, object]:
    return {
        "analysis_fields": {
            "current_comment_body": text,
            "post_body": "Parent-only text must not become persona evidence.",
            "post_title": "Parent",
        },
        "analysis_text_status": "ready",
        "canonical_entity_id": f"t1_{comment_id}",
        "comment_id": comment_id,
        "post_id": post_id,
        "schema_version": "reddit_voc_fielded_voc_v1",
        "thread_id": post_id,
        "voc_id": f"comment:{comment_id}",
        "voc_type": "comment_context_voc",
    }


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class PersonaSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dictionary = load_persona_dictionary(DICTIONARY_PATH)
        self.config = load_persona_cohort_config(
            CONFIG_PATH, dictionary=self.dictionary
        )
        self.vocs = (
            _post("purchase", "I am pregnant and building my registry."),
            _comment("comment", "I am a new parent with my first baby."),
            _post("automation", "I am pregnant and building my registry."),
        )
        self.automation = {"post:automation"}

    def _documents(self):
        return build_v3(
            self.vocs,
            automation_voc_ids=self.automation,
            dictionary=self.dictionary,
            config=self.config,
            snapshot_id="reddit_voc_personas_fixture_v3",
            generated_at_utc="2026-07-16T00:00:00+00:00",
            source_facts_manifest_sha256="a" * 64,
            source_facts_validation_receipt_sha256="c" * 64,
            automation_manifest_sha256="b" * 64,
            automation_classifications_sha256="d" * 64,
            automation_classification_rows=3,
            reference_manifest_sha256=_sha(REFERENCE_MANIFEST_PATH),
            project_root=ROOT,
            upstream_consumption_status="blocked_pending_atomic_facts",
            upstream_promotable=False,
        )

    def test_builds_82_atomic_definitions_and_8_content_entity_cohorts(self) -> None:
        documents = self._documents()
        self.assertEqual(documents.catalog["atomic_persona_count"], 82)
        self.assertEqual(documents.bridge["cohort_count"], 8)
        self.assertEqual(documents.bridge["bridge_edge_count"], 141)
        self.assertEqual(documents.personas["persona_cohort_count"], 8)
        self.assertEqual(len(documents.personas["personas"]), 8)
        self.assertEqual(
            documents.manifest["counts"]["automation_excluded_vocs"], 1
        )
        self.assertFalse(
            any(fact.voc_id == "post:automation" for fact in documents.facts)
        )
        public = json.dumps(
            {
                "personas": documents.personas,
                "assignments": documents.assignments,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for forbidden in (
            "author_pseudonym",
            "distinct_pseudonyms",
            '"population_share":',
            '"users"',
        ):
            self.assertNotIn(forbidden, public)
        for row in documents.personas["personas"]:
            self.assertEqual(
                row["assignment_count"], row["post_count"] + row["comment_count"]
            )
            self.assertLessEqual(row["unique_entity_count"], row["assignment_count"])
            self.assertIn(
                row["status"],
                {
                    "stable_observed_sample",
                    "directional_observed_sample",
                    "unavailable_insufficient_observed_sample",
                },
            )

    def test_snapshot_writes_nine_safe_avatar_assets_and_replays(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "personas-v3"
            manifest = write_v3_snapshot(
                output,
                self._documents(),
                project_root=ROOT,
                config=self.config,
            )
            avatar_names = sorted(
                name for name in manifest["files"] if name.startswith("assets/")
            )
            self.assertEqual(len(avatar_names), 9)
            self.assertIn("assets/persona-fallback-neutral.svg", avatar_names)
            result = validate_v3(
                output,
                vocs=self.vocs,
                automation_voc_ids=self.automation,
                dictionary=self.dictionary,
                config=self.config,
                project_root=ROOT,
                expected_source_facts_manifest_sha256="a" * 64,
                expected_source_facts_validation_receipt_sha256="c" * 64,
                expected_automation_manifest_sha256="b" * 64,
                expected_automation_classifications_sha256="d" * 64,
                expected_automation_classification_rows=3,
                expected_reference_manifest_sha256=_sha(REFERENCE_MANIFEST_PATH),
                expected_upstream_consumption_status="blocked_pending_atomic_facts",
                expected_upstream_promotable=False,
            )
            self.assertEqual(result["status"], "passed_candidate_only")
            self.assertFalse(result["promotable"])
            self.assertTrue(result["production_unchanged"])
            self.assertFalse(result["provider_call"])

    def test_validator_rejects_semantic_tamper_even_with_updated_file_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "personas-v3"
            write_v3_snapshot(
                output,
                self._documents(),
                project_root=ROOT,
                config=self.config,
            )
            personas_path = output / "personas.json"
            personas = json.loads(personas_path.read_text(encoding="utf-8"))
            personas["personas"][0]["unique_entity_count"] += 1
            personas_path.write_text(
                json.dumps(
                    personas,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["personas.json"]["bytes"] = personas_path.stat().st_size
            manifest["files"]["personas.json"]["sha256"] = _sha(personas_path)
            manifest_path.write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PersonaSnapshotError, "replay"):
                validate_v3(
                    output,
                    vocs=self.vocs,
                    automation_voc_ids=self.automation,
                    dictionary=self.dictionary,
                    config=self.config,
                    project_root=ROOT,
                    expected_source_facts_manifest_sha256="a" * 64,
                    expected_source_facts_validation_receipt_sha256="c" * 64,
                    expected_automation_manifest_sha256="b" * 64,
                    expected_automation_classifications_sha256="d" * 64,
                    expected_automation_classification_rows=3,
                    expected_reference_manifest_sha256=_sha(REFERENCE_MANIFEST_PATH),
                    expected_upstream_consumption_status="blocked_pending_atomic_facts",
                    expected_upstream_promotable=False,
                )

    def test_orphan_automation_exclusion_fails_closed(self) -> None:
        with self.assertRaisesRegex(PersonaSnapshotError, "non-VOC"):
            build_v3(
                self.vocs,
                automation_voc_ids={"post:missing"},
                dictionary=self.dictionary,
                config=self.config,
                snapshot_id="fixture",
                generated_at_utc="2026-07-16T00:00:00+00:00",
                source_facts_manifest_sha256="a" * 64,
                source_facts_validation_receipt_sha256="c" * 64,
                automation_manifest_sha256="b" * 64,
                automation_classifications_sha256="d" * 64,
                automation_classification_rows=3,
                reference_manifest_sha256=_sha(REFERENCE_MANIFEST_PATH),
                project_root=ROOT,
                upstream_consumption_status="blocked_pending_atomic_facts",
                upstream_promotable=False,
            )

    def test_lineage_and_file_metadata_tamper_fail_closed(self) -> None:
        for mutation, message in (
            (
                lambda manifest: manifest.__setitem__(
                    "source_facts_manifest_sha256", "d" * 64
                ),
                "lineage",
            ),
            (
                lambda manifest: manifest["files"]["personas.json"].__setitem__(
                    "media_type", "text/plain"
                ),
                "metadata",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "personas-v3"
                write_v3_snapshot(
                    output,
                    self._documents(),
                    project_root=ROOT,
                    config=self.config,
                )
                manifest_path = output / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutation(manifest)
                manifest_path.write_text(
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(PersonaSnapshotError, message):
                    validate_v3(
                        output,
                        vocs=self.vocs,
                        automation_voc_ids=self.automation,
                        dictionary=self.dictionary,
                        config=self.config,
                        project_root=ROOT,
                        expected_source_facts_manifest_sha256="a" * 64,
                        expected_source_facts_validation_receipt_sha256="c" * 64,
                        expected_automation_manifest_sha256="b" * 64,
                        expected_automation_classifications_sha256="d" * 64,
                        expected_automation_classification_rows=3,
                        expected_reference_manifest_sha256=_sha(
                            REFERENCE_MANIFEST_PATH
                        ),
                        expected_upstream_consumption_status=(
                            "blocked_pending_atomic_facts"
                        ),
                        expected_upstream_promotable=False,
                    )

    def test_missing_ready_status_and_wrong_thread_are_rejected(self) -> None:
        for mutation in (
            lambda row: row.pop("analysis_text_status"),
            lambda row: row.__setitem__("thread_id", "different_root"),
        ):
            with self.subTest(mutation=mutation):
                invalid = [dict(row) for row in self.vocs]
                invalid[0] = json.loads(json.dumps(invalid[0]))
                mutation(invalid[0])
                with self.assertRaisesRegex(
                    PersonaSnapshotError, "not analysis ready|thread identity"
                ):
                    build_v3(
                        invalid,
                        automation_voc_ids=self.automation,
                        dictionary=self.dictionary,
                        config=self.config,
                        snapshot_id="fixture",
                        generated_at_utc="2026-07-16T00:00:00+00:00",
                        source_facts_manifest_sha256="a" * 64,
                        source_facts_validation_receipt_sha256="c" * 64,
                        automation_manifest_sha256="b" * 64,
                        automation_classifications_sha256="d" * 64,
                        automation_classification_rows=3,
                        reference_manifest_sha256=_sha(REFERENCE_MANIFEST_PATH),
                        project_root=ROOT,
                        upstream_consumption_status="blocked_pending_atomic_facts",
                        upstream_promotable=False,
                    )

    def test_non_utc_timestamp_and_undeclared_empty_directory_are_rejected(self) -> None:
        with self.assertRaisesRegex(PersonaSnapshotError, "must be UTC"):
            build_v3(
                self.vocs,
                automation_voc_ids=self.automation,
                dictionary=self.dictionary,
                config=self.config,
                snapshot_id="fixture",
                generated_at_utc="2026-07-16T08:00:00+08:00",
                source_facts_manifest_sha256="a" * 64,
                source_facts_validation_receipt_sha256="c" * 64,
                automation_manifest_sha256="b" * 64,
                automation_classifications_sha256="d" * 64,
                automation_classification_rows=3,
                reference_manifest_sha256=_sha(REFERENCE_MANIFEST_PATH),
                project_root=ROOT,
                upstream_consumption_status="blocked_pending_atomic_facts",
                upstream_promotable=False,
            )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "personas-v3"
            write_v3_snapshot(
                output,
                self._documents(),
                project_root=ROOT,
                config=self.config,
            )
            undeclared = output / "undeclared-empty"
            undeclared.mkdir()
            undeclared.chmod(0o700)
            with self.assertRaisesRegex(PersonaSnapshotError, "directories"):
                validate_v3(
                    output,
                    vocs=self.vocs,
                    automation_voc_ids=self.automation,
                    dictionary=self.dictionary,
                    config=self.config,
                    project_root=ROOT,
                    expected_source_facts_manifest_sha256="a" * 64,
                    expected_source_facts_validation_receipt_sha256="c" * 64,
                    expected_automation_manifest_sha256="b" * 64,
                    expected_automation_classifications_sha256="d" * 64,
                    expected_automation_classification_rows=3,
                    expected_reference_manifest_sha256=_sha(
                        REFERENCE_MANIFEST_PATH
                    ),
                    expected_upstream_consumption_status=(
                        "blocked_pending_atomic_facts"
                    ),
                    expected_upstream_promotable=False,
                )


if __name__ == "__main__":
    unittest.main()
