"""Wikilink resolution.

Builds a site-wide slug map (filename-lowercased → Post, title-lowercased →
Post fallback), resolves ``[[Target]]`` / ``[[Target|Alias]]`` placeholders
into real ``<a>`` tags, and emits warnings for broken references.
"""

import hashlib
import html
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cress.exceptions import DuplicateSlugError
from cress.post import Post
from cress.reports import BuildWarning

_PLACEHOLDER_RE = re.compile(
    r'<a data-cress-wikilink="(?P<target>[^"]*)"'
    r' data-cress-alias="(?P<alias>[^"]*)">'
    r"(?P<inner>[^<]*)</a>"
)


@dataclass(frozen=True, slots=True)
class ResolvedLink:
    """A wikilink resolved to its final URL and visible label."""

    url: str
    label: str


@dataclass(frozen=True, slots=True)
class SlugMap:
    """Site-wide post lookup by filename (primary) and title (fallback)."""

    by_filename_lower: dict[str, Post]
    by_title_lower: dict[str, Post]


def draft_url(post: Post, url_prefix: str = "") -> str:
    """Draft preview URL. Token is a stable hash of the slug."""
    assert post.slug is not None, "draft_url called on slugless post"
    token = hashlib.sha256(post.slug.encode("utf-8")).hexdigest()[:8]
    return f"{url_prefix}/_drafts/{token}-{post.slug}/"


def _post_url(post: Post, url_prefix: str = "") -> str:
    assert post.slug is not None, "slug map contains a slugless post"
    if post.draft:
        return draft_url(post, url_prefix)
    return f"{url_prefix}/{post.url_path}/"


def _global_namespace(post: Post) -> str:
    """Default slug namespace — every post shares one global namespace (blog mode)."""
    del post
    return ""


def build_slug_map(
    posts: list[Post], *, namespace: Callable[[Post], str] = _global_namespace
) -> SlugMap:
    """Build the ``{filename: post, title: post}`` lookups. Raises on duplicate slugs.

    ``namespace`` partitions the duplicate check exactly as in
    :func:`cress.post.plan_slug_writebacks`: blog mode keeps a single global
    namespace, static mode passes a per-folder namespace so the same leaf slug
    in different folders does not raise.
    """
    slug_owners: dict[tuple[str, str], Post] = {}
    for post in posts:
        if post.slug is None:
            continue
        key = (namespace(post), post.slug)
        existing = slug_owners.get(key)
        if existing is not None:
            raise DuplicateSlugError(
                f"slug {post.slug!r} claimed by {existing.source_path} and {post.source_path}"
            )
        slug_owners[key] = post

    by_filename_lower: dict[str, Post] = {}
    by_title_lower: dict[str, Post] = {}
    for post in posts:
        stem = post.source_path.stem.lower()
        by_filename_lower.setdefault(stem, post)
        by_title_lower.setdefault(post.title.lower(), post)
    return SlugMap(by_filename_lower=by_filename_lower, by_title_lower=by_title_lower)


def resolve_wikilink(
    target: str, alias: str | None, slug_map: SlugMap, url_prefix: str = ""
) -> ResolvedLink | None:
    """Resolve a wikilink target against the slug map. ``None`` = broken link."""
    key = target.strip().lower()
    post = slug_map.by_filename_lower.get(key) or slug_map.by_title_lower.get(key)
    if post is None:
        return None
    label = alias if alias else post.title
    return ResolvedLink(url=_post_url(post, url_prefix), label=label)


def substitute_wikilinks(
    html_body: str,
    slug_map: SlugMap,
    warnings: list[BuildWarning],
    source_path: Path,
    url_prefix: str = "",
) -> str:
    """Replace every wikilink placeholder with a real ``<a>`` or a broken-link span."""

    def _repl(match: re.Match[str]) -> str:
        target = html.unescape(match.group("target"))
        alias_raw = html.unescape(match.group("alias"))
        alias = alias_raw if alias_raw else None
        resolved = resolve_wikilink(target, alias, slug_map, url_prefix)
        if resolved is None:
            warnings.append(
                BuildWarning(
                    type="broken_wikilink",
                    file=str(source_path),
                    message=f"wikilink target {target!r} does not resolve to any post",
                )
            )
            return f'<span class="broken-link">{html.escape(target)}</span>'
        return f'<a href="{html.escape(resolved.url)}">{html.escape(resolved.label)}</a>'

    return _PLACEHOLDER_RE.sub(_repl, html_body)
