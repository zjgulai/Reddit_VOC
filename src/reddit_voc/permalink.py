"""One rule for deriving an evidence permalink. Used by every producer.

Three producers each carried their own idea of "permalink", and they disagreed:

  - `apify_collector` persisted Reddit's post `url`, which for a link post is the
    OUTBOUND destination and for a gallery is `reddit.com/gallery/<id>`.
  - `merge_normalize.normalize_all` rebuilt records from a template and never set
    `permalink`, so 159 merged posts all inherited ONE template URL.
  - the July import trusted whatever the export called `permalink`, which for 90
    rows was an `i.redd.it` image.

The published corpus shows the damage: 249 posts and 1,928 comments in
`reddit_voc_site_snapshot_20260723_v3_daily_001` do not resolve to their own
post. A permalink that points at a different post is worse than a missing one --
it makes every downstream evidence click land on the wrong VOC quote.

So: a permalink is valid only if its `/comments/<id>` segment equals the id of the
entity it is attached to. Anything else is replaced with the canonical identity
URL, and the basis says which happened.
"""
from __future__ import annotations

import re
from typing import Any

REDDIT_HOSTS = frozenset({
    "reddit.com", "www.reddit.com", "old.reddit.com",
    "redd.it", "i.redd.it", "v.redd.it",
})
_COMMENTS_ID = re.compile(r"/comments/([A-Za-z0-9]+)")
_SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{1,64}$")

BASIS_SOURCE_PERMALINK = "source_permalink"
BASIS_SOURCE_URL = "source_url"
BASIS_CANONICAL = "canonical_reddit_identity"
BASIS_PARENT_POST = "parent_post_permalink"


def bare_subreddit(value: Any) -> str | None:
    """Strip one leading `r/`. Reddit's `communityName` already carries it."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text[:2].lower() == "r/":
        text = text[2:]
    return text or None


def canonical_post_permalink(post_id: str, subreddit: Any) -> str | None:
    """`https://www.reddit.com/r/<sub>/comments/<id>` -- no slug, which Reddit resolves."""
    sub = bare_subreddit(subreddit)
    if not post_id or not sub or _SUBREDDIT.fullmatch(sub) is None:
        return None
    return f"https://www.reddit.com/r/{sub}/comments/{post_id}"


def permalink_targets_entity(permalink: Any, entity_id: str) -> bool:
    """True when the URL's own `/comments/<id>` segment names this entity."""
    if not isinstance(permalink, str) or not permalink.strip():
        return False
    match = _COMMENTS_ID.search(permalink)
    return bool(match) and match.group(1) == str(entity_id or "")


def resolve_post_permalink(
    *,
    post_id: str,
    subreddit: Any,
    permalink: Any = None,
    source_url: Any = None,
    recorded_basis: Any = None,
) -> tuple[str | None, str]:
    """Return (permalink, basis) for a post, preferring any URL that proves identity.

    Order matters: a URL that carries this post's own id is evidence; a URL that
    does not is either a media asset or another post entirely, and neither may be
    published as if it identified this one.
    """
    for candidate, basis in (
        (permalink, recorded_basis if recorded_basis in {
            BASIS_SOURCE_PERMALINK, BASIS_SOURCE_URL, BASIS_CANONICAL} else BASIS_SOURCE_PERMALINK),
        (source_url, BASIS_SOURCE_URL),
    ):
        if candidate and permalink_targets_entity(candidate, post_id):
            return str(candidate), basis
    canonical = canonical_post_permalink(post_id, subreddit)
    if canonical:
        return canonical, BASIS_CANONICAL
    # No usable subreddit: publish nothing rather than a link that misleads.
    return None, BASIS_CANONICAL


def resolve_comment_permalink(
    post_permalink: str | None,
    *,
    comment_id: str | None = None,
    post_id: str | None = None,
    current: Any = None,
) -> tuple[str | None, str]:
    """Return the best available permalink for a comment.

    The corpus has two legitimate comment link shapes and they are NOT equivalent:

      `.../r/X/comments/<post>/comment/<comment>`  -- anchors to the comment itself
      `.../r/X/comments/<post>`                     -- anchors to the whole thread

    3,624 published comments use the first form. Collapsing them all to the parent
    URL (the obvious implementation) silently degrades every evidence link from
    "the exact reply" to "somewhere in this thread", so the anchored form is
    preserved whenever it is genuinely correct:

      - it must name this comment, and
      - it must live under this comment's own post.

    A URL failing either test is another comment's or another post's, and is
    replaced. The two ids are optional for callers that only have the parent post.
    """
    text = str(current or "").strip()
    if text and comment_id and post_id:
        anchored = re.search(r"/comments/([A-Za-z0-9]+)/comment/([A-Za-z0-9]+)", text)
        if anchored and anchored.group(1) == str(post_id) and anchored.group(2) == str(comment_id):
            return text, BASIS_SOURCE_URL
        # A post-level permalink under the right post is also acceptable, but the
        # parent URL below is equally good -- fall through so one code path decides.
    if post_permalink:
        return post_permalink, BASIS_PARENT_POST
    return None, BASIS_PARENT_POST


def repair_permalinks(
    posts: list[dict], comments: list[dict]
) -> dict[str, int]:
    """Fix records whose permalink does not identify them. Touches ONLY those two fields.

    `merge_normalize.normalize_all` can only repair records carrying a `run_id`,
    because that is the marker of a pipeline-produced row. The July import has no
    such marker, yet it holds 90 posts whose permalink is an image or a different
    post -- and 1,242 comments that inherit them. Those rows must be repaired in
    place: rebuilding them through the template would overwrite governance fields
    the import is the only source for.

    Idempotent. Returns per-entity counts for the caller to report.
    """
    stats = {"posts_repaired": 0, "comments_repaired": 0, "posts_unfixable": 0,
             "comments_unfixable": 0}

    post_permalink: dict[str, str | None] = {}
    for post in posts:
        post_id = str(post.get("post_id") or "")
        if not post_id:
            continue
        if not permalink_targets_entity(post.get("permalink"), post_id):
            resolved, basis = resolve_post_permalink(
                post_id=post_id,
                subreddit=post.get("subreddit"),
                permalink=post.get("permalink"),
                source_url=post.get("source_url"),
                recorded_basis=post.get("permalink_basis"),
            )
            if resolved:
                post["permalink"] = resolved
                post["permalink_basis"] = basis
                stats["posts_repaired"] += 1
            else:
                stats["posts_unfixable"] += 1
        post_permalink[post_id] = post.get("permalink")

    for comment in comments:
        parent_id = str(comment.get("post_id") or "")
        parent = post_permalink.get(parent_id)
        if not parent:
            stats["comments_unfixable"] += 1
            continue
        resolved, basis = resolve_comment_permalink(
            parent,
            comment_id=str(comment.get("comment_id") or "").removeprefix("t1_"),
            post_id=parent_id,
            current=comment.get("permalink"),
        )
        if comment.get("permalink") != resolved:
            comment["permalink"] = resolved
            comment["permalink_basis"] = basis
            stats["comments_repaired"] += 1

    return stats
