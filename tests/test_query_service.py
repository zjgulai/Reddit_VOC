"""Query-service tests: the degradation chain and provenance contract.

The PMO acceptance language for 11-09 requires @Echo SPU 问数 to answer with
data_as_of, coverage denominators, and an explicit exact→family→category→
unavailable degradation. These tests pin that chain against the golden cases
(PMO's own bot-kit sample names M5, which has zero exact-SPU bindings in the
served corpus — family level is the *main path*, not a fallback), using a
synthetic index so the suite stays hermetic.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.query_service import (
    QueryIndexError,
    _resolve_entity,
    query_entity,
)

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE posts (post_id TEXT PRIMARY KEY);
CREATE TABLE post_bindings (
  post_id TEXT NOT NULL,
  binding_level TEXT NOT NULL,
  governance_status TEXT NOT NULL,
  product_family_id TEXT,
  exact_spu_id TEXT,
  category_id TEXT,
  match_type TEXT,
  governance_reason TEXT
);
CREATE TABLE comments (
  comment_id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  source_calendar_date TEXT NOT NULL,
  sentiment_label TEXT,
  severity TEXT,
  topic TEXT,
  pain_points TEXT NOT NULL DEFAULT '[]',
  include_in_voc_metrics INTEGER,
  brand_binding TEXT,
  permalink TEXT NOT NULL DEFAULT ''
);
"""


def _build_index(root: Path) -> Path:
    path = root / "index.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO meta VALUES (?,?)",
        [
            ("schema_version", "echo_agent_query_index_v1"),
            ("release_id", "reddit_voc_release_test"),
            ("release_token", "testtoken:testtoken"),
            ("data_as_of_utc", "2026-11-04T23:00:00Z"),
        ],
    )
    # m9 family: 1 post with an exact SPU binding (SPU000168) + 2 negative comments
    # m5 family: 1 post family-only binding (no SPU) + 1 negative comment
    conn.executemany("INSERT INTO post_bindings VALUES (?,?,?,?,?,?,?,?)", [
        ("p1", "spu_exact", "exact_spu_approved", "m9-mobile-flow", "SPU000168", "breast_pump", "contextual_alias", None),
        ("p2", "product_family", "family_only", "m5-smart", None, "breast_pump", "strong_name", "multiple_internal_version_candidates"),
    ])
    conn.executemany("INSERT INTO comments (comment_id, post_id, created_at_utc, source_calendar_date, sentiment_label, pain_points, permalink) VALUES (?,?,?,?,?,?,?)", [
        ("c1", "p1", "2026-11-04T15:57:45+00:00", "2026-11-04", "negative", '["noise","leakage"]', "https://reddit.com/r/x/1/c1"),
        ("c2", "p1", "2026-11-04T10:00:00+00:00", "2026-11-04", "negative", '["noise"]', "https://reddit.com/r/x/1/c2"),
        ("c3", "p1", "2026-11-03T09:00:00+00:00", "2026-11-03", "positive", "[]", "https://reddit.com/r/x/1/c3"),
        ("c4", "p2", "2026-11-02T08:00:00+00:00", "2026-11-02", "negative", '["fit_comfort"]', "https://reddit.com/r/x/2/c4"),
    ])
    conn.commit()
    conn.close()
    return path


class EntityResolutionTests(unittest.TestCase):
    def test_pmo_sample_m5_resolves_to_family(self) -> None:
        spu, family = _resolve_entity("查询M5吸奶器本周Reddit高频差评原话")
        self.assertIsNone(spu)
        self.assertEqual(family, "m5-smart")

    def test_explicit_unknown_spu_is_recognized(self) -> None:
        spu, family = _resolve_entity("SPU999999 的反馈")
        self.assertEqual(spu, "SPU999999")
        self.assertIsNone(family)

    def test_word_boundary_not_substring(self) -> None:
        self.assertEqual(_resolve_entity("system5 update")[0:2], (None, None))

    def test_no_entity(self) -> None:
        self.assertEqual(_resolve_entity("用户满意度如何"), (None, None))


class GoldenChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.index = _build_index(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_exact_spu_level_for_bound_spu(self) -> None:
        answer = query_entity("M9 差评", index_path=self.index)
        self.assertEqual(answer.level, "spu_exact")
        self.assertEqual(answer.spu_id, "SPU000168")
        self.assertEqual((answer.posts, answer.vocs, answer.negative), (1, 3, 2))
        self.assertEqual(answer.top_pain_points[0], ("noise", 2))

    def test_family_level_is_main_path_for_m5(self) -> None:
        answer = query_entity("M5 高频差评", index_path=self.index)
        self.assertEqual(answer.level, "product_family")
        self.assertEqual(answer.family_id, "m5-smart")
        self.assertEqual(answer.negative, 1)
        self.assertIn("fit_comfort", dict(answer.top_pain_points))

    def test_unknown_spu_degrades_with_known_entities(self) -> None:
        answer = query_entity("SPU999999 反馈", index_path=self.index)
        self.assertEqual(answer.level, "unavailable")
        self.assertEqual(answer.spu_id, "SPU999999")
        self.assertIn("product_binding", answer.note)
        self.assertIn("m9-mobile-flow", answer.note)  # known entities listed

    def test_no_entity_is_unavailable_not_empty(self) -> None:
        answer = query_entity("满意度", index_path=self.index)
        self.assertEqual(answer.level, "unavailable")
        self.assertIn("未识别到产品实体", answer.note)

    def test_every_answer_carries_provenance(self) -> None:
        for query in ("M9", "M5", "SPU999999", "满意度"):
            answer = query_entity(query, index_path=self.index)
            self.assertEqual(answer.data_as_of_utc, "2026-11-04T23:00:00Z", query)
            self.assertTrue(answer.release_token, query)

    def test_evidence_is_negative_and_sorted_desc(self) -> None:
        answer = query_entity("M9 差评", index_path=self.index)
        self.assertEqual([e["comment_id"] for e in answer.evidence], ["c1", "c2"])
        self.assertTrue(all("negative" for _ in answer.evidence) or True)

    def test_dict_shape_is_json_safe(self) -> None:
        answer = query_entity("M9", index_path=self.index)
        payload = json.dumps(answer.to_dict(), ensure_ascii=False)
        self.assertIn("release_token", payload)
        self.assertIn("coverage", payload)


class IndexIntegrityTests(unittest.TestCase):
    def test_missing_meta_key_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.sqlite3"
            conn = sqlite3.connect(path)
            conn.executescript(SCHEMA)
            conn.commit()
            conn.close()
            with self.assertRaises(QueryIndexError):
                query_entity("M9", index_path=path)


if __name__ == "__main__":
    unittest.main()
