from __future__ import annotations

import unittest

from reddit_voc.v3_canonical_identity import (
    CanonicalIdentityError,
    CommentState,
    assert_comment_root_consistency,
    canonical_comment_fullname,
    canonical_comment_id,
    canonical_entity_id,
    canonical_parent_id,
    canonical_post_fullname,
    canonical_post_id,
)


class CanonicalIdentityTests(unittest.TestCase):
    def test_post_identity_accepts_bare_or_t3_and_normalizes_case(self) -> None:
        self.assertEqual(canonical_post_id(" AbC123 "), "abc123")
        self.assertEqual(canonical_post_id("T3_AbC123"), "abc123")
        self.assertEqual(canonical_post_fullname("AbC123"), "t3_abc123")

    def test_comment_identity_accepts_bare_or_t1_and_normalizes_case(self) -> None:
        self.assertEqual(canonical_comment_id(" DeF456 "), "def456")
        self.assertEqual(canonical_comment_id("T1_DeF456"), "def456")
        self.assertEqual(canonical_comment_fullname("DeF456"), "t1_def456")

    def test_wrong_prefixes_and_non_base36_values_fail_closed(self) -> None:
        bad_posts = (
            "",
            "t1_abc",
            "t3_t3_abc",
            "abc/def",
            "abc_def",
            "äbc",
            "K",
            "ſ",
        )
        bad_comments = (
            "",
            "t3_abc",
            "t1_t1_abc",
            "abc/def",
            "abc_def",
            "评",
            "K",
            "ſ",
        )
        for value in bad_posts:
            with self.subTest(kind="post", value=value):
                with self.assertRaises(CanonicalIdentityError):
                    canonical_post_id(value)
        for value in bad_comments:
            with self.subTest(kind="comment", value=value):
                with self.assertRaises(CanonicalIdentityError):
                    canonical_comment_id(value)

    def test_entity_type_controls_fullname_namespace(self) -> None:
        self.assertEqual(canonical_entity_id(" POST ", "abc"), "t3_abc")
        self.assertEqual(canonical_entity_id("Comment", "def"), "t1_def")
        with self.assertRaisesRegex(CanonicalIdentityError, "entity type"):
            canonical_entity_id("thread", "abc")

    def test_parent_identity_preserves_post_or_comment_namespace(self) -> None:
        post_parent = canonical_parent_id("T3_AbC")
        comment_parent = canonical_parent_id("t1_DeF")
        self.assertEqual(
            (post_parent.entity_type, post_parent.bare_id, post_parent.fullname),
            ("post", "abc", "t3_abc"),
        )
        self.assertEqual(
            (comment_parent.entity_type, comment_parent.bare_id, comment_parent.fullname),
            ("comment", "def", "t1_def"),
        )

    def test_parent_requires_an_explicit_fullname(self) -> None:
        for value in ("abc", "t2_abc", "t3_", "t1_abc/def"):
            with self.subTest(value=value):
                with self.assertRaises(CanonicalIdentityError):
                    canonical_parent_id(value)

    def test_root_parent_must_match_comment_post_id(self) -> None:
        parent = assert_comment_root_consistency("AbC", "t3_ABC")
        self.assertEqual(parent.fullname, "t3_abc")
        nested = assert_comment_root_consistency(
            "AbC",
            "t1_DeF",
            comment_id="ghi",
            comment_post_ids={"def": "abc"},
            comment_parent_ids={"def": "t3_abc"},
        )
        self.assertEqual(nested.fullname, "t1_def")
        with self.assertRaisesRegex(CanonicalIdentityError, "root parent mismatch"):
            assert_comment_root_consistency("abc", "t3_other")

    def test_nested_parent_requires_same_thread_and_complete_chain(self) -> None:
        with self.assertRaisesRegex(CanonicalIdentityError, "nested parent context"):
            assert_comment_root_consistency("abc", "t1_def")
        with self.assertRaisesRegex(CanonicalIdentityError, "nested parent .*missing"):
            assert_comment_root_consistency(
                "abc",
                "t1_def",
                comment_id="ghi",
                comment_post_ids={},
                comment_parent_ids={},
            )
        with self.assertRaisesRegex(CanonicalIdentityError, "cross-thread"):
            assert_comment_root_consistency(
                "abc",
                "t1_def",
                comment_id="ghi",
                comment_post_ids={"def": "other"},
                comment_parent_ids={"def": "t3_other"},
            )

    def test_nested_parent_cycle_fails_closed(self) -> None:
        with self.assertRaisesRegex(CanonicalIdentityError, "parent cycle"):
            assert_comment_root_consistency(
                "abc",
                "t1_def",
                comment_id="ghi",
                comment_post_ids={"def": "abc", "ghi": "abc"},
                comment_parent_ids={"def": "t1_ghi", "ghi": "t1_def"},
            )

    def test_comment_states_are_exact_and_mutually_distinct(self) -> None:
        self.assertEqual(
            {state.value for state in CommentState},
            {"linked", "unresolved_parent", "quarantined"},
        )
        self.assertEqual(len(CommentState), 3)


if __name__ == "__main__":
    unittest.main()
