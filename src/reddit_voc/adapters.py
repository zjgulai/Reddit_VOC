from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Any
from xml.etree import ElementTree

from .analyzer import analyze_text
from .models import RawCapture, RedditComment, RedditThread


REDDIT_BASE_URL = "https://www.reddit.com"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


@dataclass(frozen=True)
class DiscoveryPost:
    post_id: str
    subreddit: str
    title: str
    source_url: str
    created_at_utc: datetime | None
    source_method: str
    score: int | None = None
    num_comments_reported: int | None = None
    coverage_grade: str = "discovery_only"


@dataclass(frozen=True)
class ParsedThread:
    thread: RedditThread
    comments: list[RedditComment]


class BrowserJsonBlockedError(ValueError):
    def __init__(self, browser_status: str, blocked_reason: str) -> None:
        super().__init__(f"browser json blocked: {browser_status}:{blocked_reason}")
        self.browser_status = browser_status
        self.blocked_reason = blocked_reason


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_author(author: str | None) -> str | None:
    if not author or author in {"[deleted]", "AutoModerator"}:
        return None
    return "author_sha256:" + hashlib.sha256(author.encode("utf-8")).hexdigest()[:16]


def _utc_from_epoch(value: Any) -> datetime:
    if value is None:
        raise ValueError("missing created_utc")
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _utc_from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _canonical_url(value: str | None) -> str:
    if not value:
        return REDDIT_BASE_URL + "/"
    if value.startswith("http://") or value.startswith("https://"):
        url = value
    else:
        url = REDDIT_BASE_URL + value
    if url.endswith("/.json"):
        return url[:-6] + "/"
    if url.endswith(".json"):
        return url[:-5]
    return url


def _clean_media_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = unescape(value).strip()
    if not text.startswith(("http://", "https://")):
        return None
    if text.lower() in {"self", "default", "nsfw", "spoiler"}:
        return None
    return text


def _looks_like_image_url(value: str) -> bool:
    lowered = value.lower().split("?", 1)[0]
    return lowered.endswith(IMAGE_EXTENSIONS) or "preview.redd.it/" in lowered or "i.redd.it/" in lowered


def _add_media_url(urls: list[str], value: Any, *, allow_thumbnail: bool = False) -> None:
    cleaned = _clean_media_url(value)
    if not cleaned:
        return
    if not allow_thumbnail and not _looks_like_image_url(cleaned):
        return
    if cleaned not in urls:
        urls.append(cleaned)


def _extract_media_urls(data: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    post_hint = str(data.get("post_hint") or data.get("postHint") or "").lower()
    if post_hint == "image":
        _add_media_url(urls, data.get("url_overridden_by_dest") or data.get("url"), allow_thumbnail=True)
    else:
        _add_media_url(urls, data.get("url_overridden_by_dest") or data.get("url"))

    preview = data.get("preview")
    images = preview.get("images") if isinstance(preview, dict) else None
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            source = image.get("source") if isinstance(image.get("source"), dict) else {}
            _add_media_url(urls, source.get("url"), allow_thumbnail=True)
            for resolution in image.get("resolutions") or []:
                if isinstance(resolution, dict):
                    _add_media_url(urls, resolution.get("url"), allow_thumbnail=True)

    media_metadata = data.get("media_metadata") or data.get("mediaMetadata")
    if isinstance(media_metadata, dict):
        for item in media_metadata.values():
            if not isinstance(item, dict):
                continue
            source = item.get("s") if isinstance(item.get("s"), dict) else {}
            _add_media_url(urls, source.get("u") or source.get("gif") or source.get("mp4"), allow_thumbnail=True)
            for preview_item in item.get("p") or []:
                if isinstance(preview_item, dict):
                    _add_media_url(urls, preview_item.get("u"), allow_thumbnail=True)

    gallery_items = data.get("gallery_data", {}).get("items") if isinstance(data.get("gallery_data"), dict) else []
    if isinstance(gallery_items, list) and isinstance(media_metadata, dict):
        for item in gallery_items:
            media_id = item.get("media_id") if isinstance(item, dict) else None
            metadata = media_metadata.get(media_id) if media_id else None
            if isinstance(metadata, dict):
                source = metadata.get("s") if isinstance(metadata.get("s"), dict) else {}
                _add_media_url(urls, source.get("u"), allow_thumbnail=True)

    _add_media_url(urls, data.get("thumbnail"), allow_thumbnail=True)
    return urls


def _post_identity_from_url(value: str) -> tuple[str | None, str | None]:
    match = re.search(r"/r/([^/]+)/comments/([^/?#]+)/", value)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _fullname(prefix: str, value: str | None, name: str | None = None) -> str:
    if name:
        return name
    if not value:
        return ""
    return value if value.startswith(prefix + "_") else prefix + "_" + value


class BrowserJsonAdapter:
    source_method = "browser_json"
    auth_boundary = "browser_login"

    def build_raw_capture(
        self,
        raw_text: str,
        *,
        run_id: str,
        source_url: str,
        captured_at_utc: datetime | None = None,
        browser_status: str = "ok",
    ) -> RawCapture:
        raw_payload_hash = _hash_text(raw_text)
        return RawCapture(
            raw_capture_id="raw_browser_json_" + raw_payload_hash.split(":", 1)[1][:16],
            run_id=run_id,
            source_method=self.source_method,
            source_url=source_url,
            captured_at_utc=captured_at_utc or datetime.now(timezone.utc),
            auth_boundary=self.auth_boundary,
            raw_payload_hash=raw_payload_hash,
            payload_format="json",
            browser_status=browser_status,
            secrets_written=False,
        )

    def classify_browser_text(self, raw_text: str) -> tuple[str, str | None]:
        stripped = raw_text.strip()
        lowered = stripped[:4000].lower()
        if not stripped:
            return "blocked", "empty_body"
        if "captcha" in lowered:
            return "captcha", "captcha_text_detected"
        if stripped.startswith("<") or "<html" in lowered:
            if "log in" in lowered or "login" in lowered:
                return "login_required", "html_login_wall"
            return "blocked", "html_body"
        if not (stripped.startswith("[") or stripped.startswith("{")):
            if "log in" in lowered or "login" in lowered:
                return "login_required", "text_login_wall"
            return "blocked", "non_json_body"
        return "ok", None

    def parse_listing_text(self, raw_text: str) -> list[DiscoveryPost]:
        browser_status, blocked_reason = self.classify_browser_text(raw_text)
        if browser_status != "ok":
            raise BrowserJsonBlockedError(browser_status, blocked_reason or "unknown")
        return self.parse_listing_payload(json.loads(raw_text))

    def parse_listing_payload(self, payload: dict[str, Any]) -> list[DiscoveryPost]:
        children = payload.get("data", {}).get("children", [])
        posts: list[DiscoveryPost] = []
        for child in children:
            if child.get("kind") != "t3":
                continue
            data = child.get("data", {})
            source_url = _canonical_url(data.get("permalink") or data.get("url"))
            subreddit, post_id = _post_identity_from_url(source_url)
            posts.append(
                DiscoveryPost(
                    post_id=post_id or data.get("id", ""),
                    subreddit=subreddit or data.get("subreddit", ""),
                    title=data.get("title", ""),
                    source_url=source_url,
                    created_at_utc=_utc_from_epoch(data.get("created_utc")) if data.get("created_utc") is not None else None,
                    source_method=self.source_method,
                    score=_int_or_none(data.get("score")),
                    num_comments_reported=_int_or_none(data.get("num_comments")),
                )
            )
        return posts

    def parse_thread_text(self, raw_text: str, *, run_id: str, raw_capture_id: str, source_url: str) -> ParsedThread:
        browser_status, blocked_reason = self.classify_browser_text(raw_text)
        if browser_status != "ok":
            raise BrowserJsonBlockedError(browser_status, blocked_reason or "unknown")
        return self.parse_thread_payload(json.loads(raw_text), run_id=run_id, raw_capture_id=raw_capture_id, source_url=source_url)

    def parse_thread_payload(
        self,
        payload: list[Any],
        *,
        run_id: str,
        raw_capture_id: str,
        source_url: str,
    ) -> ParsedThread:
        if not isinstance(payload, list) or len(payload) < 2:
            raise ValueError("expected reddit thread .json listing array")

        post_children = payload[0].get("data", {}).get("children", [])
        if not post_children or post_children[0].get("kind") != "t3":
            raise ValueError("expected first listing to contain a post")

        post_data = post_children[0].get("data", {})
        post_id = post_data.get("id")
        if not post_id:
            raise ValueError("missing post id")

        title = post_data.get("title", "")
        selftext = post_data.get("selftext", "")
        post_analysis = analyze_text(f"{title}\n{selftext}")
        comments, more_node_count = self._parse_comments(
            payload[1].get("data", {}).get("children", []),
            post_id=post_id,
            run_id=run_id,
            raw_capture_id=raw_capture_id,
            depth=0,
        )
        reported_count = _int_or_none(post_data.get("num_comments"))
        coverage_grade = self._coverage_grade(
            parsed_comment_count=len(comments),
            more_node_count=more_node_count,
            reported_count=reported_count,
        )

        thread = RedditThread(
            post_id=post_id,
            run_id=run_id,
            raw_capture_id=raw_capture_id,
            subreddit=post_data.get("subreddit", ""),
            title=title,
            selftext=selftext,
            source_url=_canonical_url(post_data.get("permalink") or source_url),
            created_at_utc=_utc_from_epoch(post_data.get("created_utc")),
            score=_int_or_none(post_data.get("score")),
            num_comments_reported=reported_count,
            parsed_comment_count=len(comments),
            more_node_count=more_node_count,
            coverage_grade=coverage_grade,
            matched_keywords=post_analysis.keyword_match.matched_terms,
            media_urls=_extract_media_urls(post_data),
            author_hash=_hash_author(post_data.get("author")),
        )
        return ParsedThread(thread=thread, comments=comments)

    def _parse_comments(
        self,
        nodes: list[dict[str, Any]],
        *,
        post_id: str,
        run_id: str,
        raw_capture_id: str,
        depth: int,
    ) -> tuple[list[RedditComment], int]:
        comments: list[RedditComment] = []
        more_node_count = 0
        for node in nodes:
            kind = node.get("kind")
            data = node.get("data", {})
            if kind == "more":
                more_node_count += 1
                continue
            if kind != "t1":
                continue

            body = data.get("body") or ""
            deleted_or_removed = body in {"[deleted]", "[removed]"}
            analysis = analyze_text(body)
            comment = RedditComment(
                comment_id=_fullname("t1", data.get("id"), data.get("name")),
                post_id=post_id,
                run_id=run_id,
                raw_capture_id=raw_capture_id,
                body=body,
                created_at_utc=_utc_from_epoch(data.get("created_utc")),
                parent_id=data.get("parent_id"),
                score=_int_or_none(data.get("score")),
                depth=_int_or_none(data.get("depth")) if data.get("depth") is not None else depth,
                is_submitter=data.get("is_submitter") if isinstance(data.get("is_submitter"), bool) else None,
                matched_keywords=analysis.keyword_match.matched_terms,
                author_hash=None if deleted_or_removed else _hash_author(data.get("author")),
                deleted_or_removed=deleted_or_removed,
            )
            comments.append(comment)

            replies = data.get("replies")
            if isinstance(replies, dict):
                child_comments, child_more = self._parse_comments(
                    replies.get("data", {}).get("children", []),
                    post_id=post_id,
                    run_id=run_id,
                    raw_capture_id=raw_capture_id,
                    depth=depth + 1,
                )
                comments.extend(child_comments)
                more_node_count += child_more
        return comments, more_node_count

    @staticmethod
    def _coverage_grade(*, parsed_comment_count: int, more_node_count: int, reported_count: int | None) -> str:
        if more_node_count > 0:
            return "partial"
        if parsed_comment_count == 0 and reported_count and reported_count > 0:
            return "post_only"
        return "full"


class RssDiscoveryAdapter:
    source_method = "rss"

    def parse_feed_text(self, raw_text: str) -> list[DiscoveryPost]:
        root = ElementTree.fromstring(raw_text)
        return self.parse_feed_root(root)

    def parse_feed_root(self, root: ElementTree.Element) -> list[DiscoveryPost]:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns) or root.findall("entry")
        posts: list[DiscoveryPost] = []
        for entry in entries:
            title = self._find_text(entry, "title")
            link = self._find_link(entry)
            updated = self._find_text(entry, "updated") or self._find_text(entry, "published")
            subreddit, post_id = _post_identity_from_url(link)
            if not post_id:
                continue
            posts.append(
                DiscoveryPost(
                    post_id=post_id,
                    subreddit=subreddit or "",
                    title=title or "",
                    source_url=_canonical_url(link),
                    created_at_utc=_utc_from_iso(updated),
                    source_method=self.source_method,
                )
            )
        return posts

    @staticmethod
    def _find_text(entry: ElementTree.Element, tag: str) -> str | None:
        for child in entry:
            if child.tag.endswith("}" + tag) or child.tag == tag:
                return child.text
        return None

    @staticmethod
    def _find_link(entry: ElementTree.Element) -> str:
        for child in entry:
            if child.tag.endswith("}link") or child.tag == "link":
                href = child.attrib.get("href")
                if href:
                    return href
        return ""
