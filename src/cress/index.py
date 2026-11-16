"""Read-only, machine-readable post index.

A pure query over the vault: parses every post, computes the slugs, paths,
and image URLs a build *would* produce — via the same deterministic pure
functions ``build`` uses (:func:`cress.post.plan_slug_writebacks`,
:func:`cress.attachments.plan_attachment`) — and returns structured
:class:`IndexEntry` records. Writes nothing: slug write-backs are promised,
never applied, and attachment plans are discarded after their URL is read.
Consumed by the ``cress index`` CLI command in :mod:`cress.cli`.

:func:`extra_fields` converts the frontmatter fields that ``index.extra``
lists to JSON values; ``cress validate`` in :mod:`cress.cli` calls it too.
"""

import datetime as _dt
import math
from dataclasses import dataclass
from dataclasses import replace as _replace
from pathlib import Path
from typing import Any

from cress.attachments import plan_attachment, reset_attachment_cache, resolve_attachment
from cress.config import SiteConfig
from cress.exceptions import ConfigError, DuplicateSlugError, PostParseError
from cress.pages import post_path, post_url
from cress.post import Post, compute_url_path, parse_post, plan_slug_writebacks, vault_rel_dir
from cress.reports import BuildWarning

# The values that ``json.dumps`` writes as valid JSON — no NaN, no Infinity.
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """One post's record in the index — the spec's full field set.

    ``extra`` holds the frontmatter fields that ``index.extra`` lists, already
    converted to JSON values: one key per listed name, ``None`` when unset.
    """

    title: str
    slug: str
    path: str
    url: str
    date: _dt.date | _dt.datetime | None
    updated: _dt.date | _dt.datetime | None
    summary: str
    author: str
    tags: list[str]
    categories: list[str]
    reading_time_minutes: int
    draft: bool
    image: str | None
    image_alt: str | None
    extra: dict[str, JsonValue]

    def to_json_dict(self) -> dict[str, Any]:
        """Serialise for the ``--json`` envelope: dates become ISO 8601 strings."""
        return {
            "title": self.title,
            "slug": self.slug,
            "path": self.path,
            "url": self.url,
            "date": self.date.isoformat() if self.date is not None else None,
            "updated": self.updated.isoformat() if self.updated is not None else None,
            "summary": self.summary,
            "author": self.author,
            "tags": self.tags,
            "categories": self.categories,
            "reading_time_minutes": self.reading_time_minutes,
            "draft": self.draft,
            "image": self.image,
            "image_alt": self.image_alt,
            "extra": self.extra,
        }


@dataclass(frozen=True, slots=True)
class IndexResult:
    """Entries plus the soft warnings gathered while indexing."""

    entries: list[IndexEntry]
    warnings: list[BuildWarning]


def build_post_index(
    vault: Path, config: SiteConfig, *, include_drafts: bool = False
) -> IndexResult:
    """Build the post index. Pure query — reads the vault, writes nothing.

    Lenient like ``build``: an unparseable post becomes a ``post_parse_error``
    warning and the rest still emit. An empty vault is a legitimate answer
    (empty entries, ``empty_vault`` warning). Hard errors mirror ``build``:
    a missing vault subfolder or an all-unparseable vault raise
    :class:`ConfigError`; duplicate slugs raise :class:`DuplicateSlugError`.
    An ``index.extra`` value that JSON cannot carry becomes ``None`` with an
    ``unsupported_extra_value`` warning, for the emitted posts only.
    """
    reset_attachment_cache()
    warnings: list[BuildWarning] = []

    vault_posts_dir = vault / config.vault_subfolder
    if not vault_posts_dir.is_dir():
        raise ConfigError(f"vault subfolder does not exist: {vault_posts_dir}")
    md_paths = sorted(vault_posts_dir.rglob("*.md"))
    if not md_paths:
        warnings.append(
            BuildWarning(type="empty_vault", file=str(vault_posts_dir), message="no posts found")
        )
        return IndexResult(entries=[], warnings=warnings)

    posts: list[Post] = []
    for md_path in md_paths:
        try:
            posts.append(parse_post(md_path, config))
        except PostParseError as exc:
            warnings.append(
                BuildWarning(type="post_parse_error", file=str(md_path), message=str(exc))
            )
    if not posts:
        raise ConfigError("no parseable posts — every file failed to parse")

    def _namespace(post: Post) -> str:
        return vault_rel_dir(post.source_path, vault_posts_dir, static_pages=config.static_pages)

    plan = plan_slug_writebacks(posts, namespace=_namespace)
    if plan.duplicates:
        detail = "; ".join(
            f"{d.slug}: {', '.join(str(p) for p in d.paths)}" for d in plan.duplicates
        )
        raise DuplicateSlugError(f"duplicate slugs detected: {detail}")

    # Promised slugs come from the plan — never applied to disk (spec D3).
    promised = dict(plan.writebacks)
    resolved: list[Post] = []
    for post in posts:
        slug = post.slug if post.slug is not None else promised[post.source_path]
        resolved.append(
            _replace(
                post,
                slug=slug,
                url_path=compute_url_path(
                    post.source_path, slug, vault_posts_dir, static_pages=config.static_pages
                ),
            )
        )
    posts = resolved

    if not include_drafts:
        posts = [p for p in posts if not p.draft]

    # Descending date with ascending slug tie-break, via two stable sorts.
    if config.static_pages:
        posts.sort(key=lambda p: p.url_path)
    else:
        posts.sort(key=lambda p: p.slug or "")
        posts.sort(key=_blog_sort_key, reverse=True)

    entries: list[IndexEntry] = []
    for post in posts:
        assert post.slug is not None
        # After the draft filter, so an excluded draft gives no warning
        # (extra-fields spec § 3.3), as for ``missing_hero_image``.
        extra, extra_warnings = extra_fields(post, config.index.extra)
        warnings.extend(extra_warnings)
        entries.append(
            IndexEntry(
                title=post.title,
                slug=post.slug,
                path=post_url(post, config),
                url=config.site.base_url.rstrip("/") + post_path(post),
                date=post.date,
                updated=post.updated,
                summary=post.summary,
                author=post.author,
                tags=post.tags,
                categories=post.categories,
                reading_time_minutes=post.reading_time_minutes,
                draft=post.draft,
                image=_resolve_image(post, config, vault, warnings),
                image_alt=post.image_alt,
                extra=extra,
            )
        )
    return IndexResult(entries=entries, warnings=warnings)


def _blog_sort_key(post: Post) -> _dt.datetime:
    """Blog-mode sort key: normalise to a timezone-aware datetime.

    A vault may legitimately mix plain dates, naive datetimes, and
    offset-bearing datetimes; comparing those raw raises ``TypeError``, so
    dates become UTC midnight and naive datetimes are pinned to UTC (mirrors
    ``feeds._ensure_tz``, kept local per the plan).
    """
    assert post.date is not None, "blog-mode index requires a date on every post"
    value = post.date
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=_dt.UTC)
    return _dt.datetime.combine(value, _dt.time(0, 0), tzinfo=_dt.UTC)


def _resolve_image(
    post: Post, config: SiteConfig, vault: Path, warnings: list[BuildWarning]
) -> str | None:
    """Compute the hashed public URL a post's ``image:`` will get, without writing it.

    Mirrors ``cress.site.cress._resolve_hero_image``: absolute references pass
    through, missing files warn and null out, resolved files yield the pure
    :func:`plan_attachment` URL (the plan's output file is discarded).
    """
    if post.image is None:
        return None
    if post.image.startswith(("http://", "https://", "//", "/", "data:")):
        return post.image
    assert post.slug is not None
    resolved = resolve_attachment(post.image, post, config, vault)
    if resolved is None:
        warnings.append(
            BuildWarning(
                type="missing_hero_image",
                file=str(post.source_path),
                message=f"hero image {post.image!r} not found",
            )
        )
        return None
    return plan_attachment(resolved, post.slug, config).public_url


def extra_fields(
    post: Post, names: tuple[str, ...]
) -> tuple[dict[str, JsonValue], list[BuildWarning]]:
    """Convert the frontmatter fields that ``index.extra`` lists to JSON values.

    Args:
        post: The parsed post. Only ``frontmatter_raw`` and ``source_path`` are read.
        names: The field names from ``index.extra``, in order.

    Returns:
        A map with one key per name, and the warnings. A field the post does
        not set is ``None``. A field whose value JSON cannot carry is ``None``
        too, with one ``unsupported_extra_value`` warning that names the path
        to the bad part.

    Pure: no I/O. ``build_post_index`` and ``cress validate`` both call it, so
    the two commands give the same warning.
    """
    values: dict[str, JsonValue] = {}
    warnings: list[BuildWarning] = []
    for name in names:
        location = f"extra.{name}"
        try:
            values[name] = _to_json(post.frontmatter_raw.get(name), location, frozenset())
            continue
        except _UnsupportedValue as exc:
            error = exc
        except RecursionError:
            # PyYAML builds nested values without recursion, so a value can
            # load that this recursive walk cannot convert (spec § 2).
            error = _UnsupportedValue(location, "the value is nested too deeply")
        values[name] = None
        warnings.append(
            BuildWarning(
                type="unsupported_extra_value", file=str(post.source_path), message=str(error)
            )
        )
    return values, warnings


class _UnsupportedValue(Exception):
    """A part of an extra field that JSON cannot carry.

    :func:`_to_json` raises it; :func:`extra_fields` catches it once per field.
    """

    def __init__(self, location: str, reason: str) -> None:
        super().__init__(f"`{location}`: {reason}")


def _to_json(value: object, location: str, on_path: frozenset[int]) -> JsonValue:
    """Convert one frontmatter value to a JSON value, recursing into lists and maps.

    ``location`` is the path to ``value`` for the warning message
    (``extra.links[1].href``). ``on_path`` holds the ids of the lists and maps
    between the field and ``value``: meeting one of them again means the
    value contains itself (a self-referring YAML anchor). A list or a map
    that appears twice but does not contain itself is still supported.

    Raises:
        _UnsupportedValue: for the first part that JSON cannot carry.
    """
    match value:
        case None | bool() | int() | str():
            return value
        case float():
            if math.isfinite(value):
                return value
            token = "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
            raise _UnsupportedValue(location, f"{token} cannot be written as JSON")
        case _dt.date():
            # Also matches ``datetime``, a subclass of ``date``.
            return value.isoformat()
        case list() | dict() if id(value) in on_path:
            raise _UnsupportedValue(location, "the value contains itself")
        case list():
            inner = on_path | {id(value)}
            return [_to_json(item, f"{location}[{i}]", inner) for i, item in enumerate(value)]
        case dict():
            inner = on_path | {id(value)}
            converted: dict[str, JsonValue] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise _UnsupportedValue(
                        location, f"map key {key} ({type(key).__name__}) is not a string"
                    )
                converted[key] = _to_json(item, f"{location}.{key}", inner)
            return converted
        case _:
            raise _UnsupportedValue(location, f"{type(value).__name__} cannot be written as JSON")
