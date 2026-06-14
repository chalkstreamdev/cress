"""Post parsing and slug write-back planning.

Reads a markdown file, parses frontmatter via python-frontmatter, validates
types, infers summary/reading-time, harvests inline tags. Produces immutable
:class:`Post` objects.

Also owns the pure slug-planning step (:func:`plan_slug_writebacks`) and the
one-writer path that actually mutates source files
(:func:`apply_slug_writebacks`). The orchestrator in :mod:`cress.site` calls
plan → check-collisions → apply.
"""

import datetime as _dt
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter

from cress.config import SiteConfig
from cress.exceptions import PostParseError
from cress.slugify import slugify

_INLINE_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z][\w-]*)")
_FENCED_CODE_RE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_ATX_HEADING_RE = re.compile(r"^#{1,6}.*$", re.MULTILINE)
_WIKILINK_RE = re.compile(r"!?\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_MD_INLINE_RE = re.compile(r"[*_`]+")
_WHITESPACE_RE = re.compile(r"\s+")

_SUMMARY_MAX_CHARS = 160
_WORDS_PER_MINUTE = 225


@dataclass(frozen=True, slots=True)
class Post:
    """Parsed post.

    ``slug`` is ``None`` when the source file's frontmatter omitted it; the
    orchestrator plans a slug write-back and re-parses in that case. All
    other mandatory fields are non-None by construction.
    """

    source_path: Path
    title: str
    date: _dt.date | _dt.datetime | None
    body_md: str
    frontmatter_raw: dict[str, Any]
    slug: str | None = None
    # Site-root-relative path (no ``url_prefix``, no leading/trailing slash).
    # Blog mode: equal to ``slug``. Static mode: ``"<rel_dir>/<slug>"``. The
    # orchestrator sets this after slug write-back via :func:`compute_url_path`;
    # it is empty at parse time because parsing has no vault-root context.
    url_path: str = ""
    updated: _dt.date | _dt.datetime | None = None
    author: str = "Author"
    summary: str = ""
    image: str | None = None
    image_alt: str | None = None
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    draft: bool = False
    canonical: str | None = None
    reading_time_minutes: int = 1


@dataclass(frozen=True, slots=True)
class DuplicateSlug:
    """A slug that would be claimed by more than one post."""

    slug: str
    paths: list[Path]


@dataclass(frozen=True, slots=True)
class SlugPlan:
    """Pure-function output of :func:`plan_slug_writebacks`.

    ``writebacks`` is the list of ``(source_path, slug)`` pairs that
    :func:`apply_slug_writebacks` should inject. When ``duplicates`` is
    non-empty, ``writebacks`` is empty — the plan refuses to mutate any file
    in the face of a collision, so the orchestrator can raise
    :class:`cress.exceptions.DuplicateSlugError` first.
    """

    writebacks: list[tuple[Path, str]]
    duplicates: list[DuplicateSlug]


def generate_slug_for(post_path: Path, title: str) -> str:
    """Generate the slug a post *would* receive from its title.

    ``post_path`` is currently unused but reserved — a future variant may
    mix in the filename for disambiguation. Keeping the parameter lets
    callers pass it without a later API break.
    """
    del post_path
    return slugify(title)


def vault_rel_dir(source_path: Path, vault_posts_dir: Path, *, static_pages: bool) -> str:
    """POSIX directory of ``source_path`` relative to ``vault_posts_dir``.

    Returns ``""`` in blog mode (folder structure is discarded) or for a file
    sitting directly under the posts root. In static mode a nested file like
    ``<root>/guides/deep/install.md`` returns ``"guides/deep"``. This is both
    the URL-path prefix and the slug-uniqueness namespace for static sites.
    """
    if not static_pages:
        return ""
    rel = source_path.parent.relative_to(vault_posts_dir).as_posix()
    return "" if rel == "." else rel


def compute_url_path(
    source_path: Path, slug: str, vault_posts_dir: Path, *, static_pages: bool
) -> str:
    """Site-root-relative path for a post. Blog → ``slug``; static → ``<rel_dir>/<slug>``."""
    rel = vault_rel_dir(source_path, vault_posts_dir, static_pages=static_pages)
    return f"{rel}/{slug}" if rel else slug


def _global_namespace(post: Post) -> str:
    """Default slug namespace — every post shares one global namespace (blog mode)."""
    del post
    return ""


def plan_slug_writebacks(
    posts: list[Post], *, namespace: Callable[[Post], str] = _global_namespace
) -> SlugPlan:
    """Compute the slug write-back plan. Pure — no disk writes.

    For each post missing ``slug``, derive a candidate via :func:`generate_slug_for`.
    Build the full slug map (existing slugs + candidates). If any slug maps to
    more than one post, return that set as ``duplicates`` and drop every
    write-back — the orchestrator must surface the collision before any file
    is mutated.

    ``namespace`` partitions the uniqueness check. Blog mode uses a single
    global namespace (the default), so slugs must be unique site-wide. Static
    mode passes a per-folder namespace so ``guides/index`` and ``api/index``
    are legitimately distinct pages rather than a false collision.
    """
    slug_owners: dict[tuple[str, str], list[Path]] = {}
    for post in posts:
        if post.slug is not None:
            slug_owners.setdefault((namespace(post), post.slug), []).append(post.source_path)

    candidates: list[tuple[Path, str]] = []
    for post in posts:
        if post.slug is not None:
            continue
        candidate = generate_slug_for(post.source_path, post.title)
        candidates.append((post.source_path, candidate))
        slug_owners.setdefault((namespace(post), candidate), []).append(post.source_path)

    duplicates = [
        DuplicateSlug(slug=slug, paths=paths)
        for (_ns, slug), paths in sorted(slug_owners.items())
        if len(paths) > 1
    ]
    if duplicates:
        return SlugPlan(writebacks=[], duplicates=duplicates)
    return SlugPlan(writebacks=candidates, duplicates=[])


def apply_slug_writebacks(plan: SlugPlan) -> None:
    """Execute the plan's writebacks via surgical insert.

    Reads each file's bytes, locates the closing ``---`` of the opening
    frontmatter block, injects ``slug: <value>`` on its own line with the
    file's existing line-ending style, and writes the result back. Every
    byte outside the inserted line is preserved exactly.

    If the plan has unresolved duplicates this is a no-op (by construction
    the ``writebacks`` list is already empty).
    """
    for path, slug in plan.writebacks:
        _surgical_insert_slug(path, slug)


def _surgical_insert_slug(path: Path, slug: str) -> None:
    """Inject ``slug: <slug>`` immediately before the closing ``---`` of the frontmatter."""
    data = path.read_bytes()
    opening_end = _match_frontmatter_opening(data)
    if opening_end is None:
        raise PostParseError(f"{path}: expected opening `---` for frontmatter write-back")

    closing_start, closing_end = _find_closing_delim(data, opening_end)
    if closing_start is None or closing_end is None:
        raise PostParseError(f"{path}: expected closing `---` for frontmatter write-back")

    newline = _detect_newline(data, closing_end, default_byte_slice=opening_end)
    injected = f"slug: {slug}".encode() + newline
    new_data = data[:closing_start] + injected + data[closing_start:]
    path.write_bytes(new_data)


def _match_frontmatter_opening(data: bytes) -> int | None:
    """Return the byte index immediately after the opening ``---\\n`` (or ``---\\r\\n``)."""
    if data.startswith(b"---\n"):
        return 4
    if data.startswith(b"---\r\n"):
        return 5
    return None


def _find_closing_delim(data: bytes, start: int) -> tuple[int | None, int | None]:
    """Locate the closing ``---`` line beginning on a line boundary at or after ``start``.

    Returns ``(line_start, line_end)`` — the byte offsets bracketing the entire
    closing-delimiter line (excluding the opening LF that separates it from the
    previous line, so the insert target is exactly ``line_start``).
    """
    cursor = start
    while cursor < len(data):
        next_newline = data.find(b"\n", cursor)
        if next_newline == -1:
            line = data[cursor:]
            line_end = len(data)
        else:
            line = data[cursor:next_newline]
            line_end = next_newline + 1
        stripped = line.rstrip(b"\r")
        if stripped == b"---":
            return cursor, line_end
        cursor = line_end
    return None, None


def _detect_newline(data: bytes, up_to: int, default_byte_slice: int) -> bytes:
    """Infer line-ending style by sampling the bytes leading up to the closing delim."""
    sample = data[:up_to]
    if b"\r\n" in sample:
        return b"\r\n"
    if b"\n" in sample[default_byte_slice:]:
        return b"\n"
    return b"\n"


def parse_post(path: Path, config: SiteConfig) -> Post:
    """Parse ``path`` → :class:`Post`. Raises :class:`PostParseError` on validation failure."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PostParseError(f"{path}: cannot read file: {exc}") from exc

    try:
        fm = frontmatter.loads(raw)
    except Exception as exc:  # python-frontmatter wraps YAML errors in its own types
        raise PostParseError(f"{path}: invalid frontmatter: {exc}") from exc

    metadata: dict[str, Any] = dict(fm.metadata)
    body_md: str = fm.content

    if "title" not in metadata:
        raise PostParseError(f"{path}: missing required field `title`")
    # ``date`` is mandatory for blogs but optional for evergreen static pages.
    if "date" not in metadata and not config.static_pages:
        raise PostParseError(f"{path}: missing required field `date`")

    title = _as_str(metadata["title"], "title", path)
    post_date = _parse_date(metadata["date"], "date", path) if "date" in metadata else None
    updated_raw = metadata.get("updated")
    updated = _parse_date(updated_raw, "updated", path) if updated_raw is not None else None

    slug_raw = metadata.get("slug")
    slug = _as_str(slug_raw, "slug", path) if slug_raw is not None else None

    author = _as_str(metadata.get("author", config.default_author), "author", path)
    draft = _as_bool(metadata.get("draft", False), "draft", path)
    canonical_raw = metadata.get("canonical")
    canonical = _as_str(canonical_raw, "canonical", path) if canonical_raw is not None else None
    image_raw = metadata.get("image")
    image = _as_str(image_raw, "image", path) if image_raw is not None else None
    image_alt_raw = metadata.get("image_alt")
    image_alt = _as_str(image_alt_raw, "image_alt", path) if image_alt_raw is not None else None

    categories = _as_str_list(metadata.get("categories", []), "categories", path)
    frontmatter_tags = _as_str_list(metadata.get("tags", []), "tags", path)

    inline_tags = _extract_inline_tags(body_md)
    tags = _dedupe_preserve_order([*frontmatter_tags, *inline_tags])

    summary_raw = metadata.get("summary")
    if summary_raw is not None:
        summary = _as_str(summary_raw, "summary", path)
    else:
        summary = _infer_summary(body_md)

    word_count = len(body_md.split())
    reading_time = max(1, round(word_count / _WORDS_PER_MINUTE))

    return Post(
        source_path=path,
        slug=slug,
        title=title,
        date=post_date,
        updated=updated,
        author=author,
        summary=summary,
        image=image,
        image_alt=image_alt,
        categories=categories,
        tags=tags,
        draft=draft,
        canonical=canonical,
        body_md=body_md,
        frontmatter_raw=metadata,
        reading_time_minutes=reading_time,
    )


def _infer_summary(body_md: str) -> str:
    """Strip code/headings/markdown syntax and return a word-bounded 160-char-max summary."""
    text = _FENCED_CODE_RE.sub("", body_md)
    text = _INLINE_CODE_RE.sub("", text)
    text = _ATX_HEADING_RE.sub("", text)
    text = _WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1), text)
    text = _MD_INLINE_RE.sub("", text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return ""
    first = _WHITESPACE_RE.sub(" ", paragraphs[0]).strip()
    if len(first) <= _SUMMARY_MAX_CHARS:
        return first
    cut = first[: _SUMMARY_MAX_CHARS - 3]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return f"{cut}..."


def _extract_inline_tags(body_md: str) -> list[str]:
    """Harvest ``#tag`` tokens from body text, skipping code blocks and ATX headings."""
    text = _FENCED_CODE_RE.sub("", body_md)
    text = _INLINE_CODE_RE.sub("", text)
    text = _ATX_HEADING_RE.sub("", text)
    return [m.group(1) for m in _INLINE_TAG_RE.finditer(text)]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _parse_date(value: Any, key: str, path: Path) -> _dt.date | _dt.datetime:
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            if "T" in value:
                return _dt.datetime.fromisoformat(value)
            return _dt.date.fromisoformat(value)
        except ValueError as exc:
            raise PostParseError(f"{path}: `{key}` is not ISO 8601 ({value!r})") from exc
    kind = type(value).__name__
    raise PostParseError(f"{path}: `{key}` must be a date or ISO 8601 string, got {kind}")


def _as_str(value: Any, key: str, path: Path) -> str:
    if not isinstance(value, str):
        kind = type(value).__name__
        raise PostParseError(f"{path}: `{key}` expected string, got {kind}")
    return value


def _as_bool(value: Any, key: str, path: Path) -> bool:
    if not isinstance(value, bool):
        kind = type(value).__name__
        raise PostParseError(f"{path}: `{key}` expected boolean, got {kind}")
    return value


def _as_str_list(value: Any, key: str, path: Path) -> list[str]:
    if isinstance(value, str):
        raise PostParseError(
            f"{path}: `{key}` expected list of strings, got string — "
            "did you forget the square brackets?"
        )
    if not isinstance(value, list):
        kind = type(value).__name__
        raise PostParseError(f"{path}: `{key}` expected list of strings, got {kind}")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            kind = type(item).__name__
            raise PostParseError(f"{path}: `{key}` items must all be strings, got {kind}")
        out.append(item)
    return out
