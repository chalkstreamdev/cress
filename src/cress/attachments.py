"""Attachment resolution and embed substitution.

Resolves ``![[file]]`` embeds and standard ``![alt](file)`` image references,
content-hashes the bytes, and returns :class:`~cress.manifest.OutputFile`
entries so the manifest writer owns every byte cress produces.

Also drives markdown transclusion at depth=1 (further nesting produces a
broken-embed warning).
"""

import hashlib
import html
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cress.config import SiteConfig
from cress.manifest import OutputFile
from cress.post import Post
from cress.render import RenderContext, render_markdown_text
from cress.reports import BuildWarning
from cress.wikilinks import SlugMap, substitute_wikilinks

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif"}
_VIDEO_EXTS = {".mp4", ".webm", ".mov"}
_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a"}
_MARKDOWN_EXTS = {".md", ".markdown"}
_MAX_TRANSCLUSION_DEPTH = 1

_EMBED_PLACEHOLDER_RE = re.compile(
    r'<span data-cress-embed="(?P<target>[^"]*)"'
    r'(?: data-cress-embed-alias="(?P<alias>[^"]*)")?></span>'
)
# Obsidian's pipe segment doubles as a resize directive: ``|300``, ``|300x200``,
# or combined with alt text as ``|alt text|300``.
_ALIAS_SIZE_RE = re.compile(r"(?P<width>\d+)(?:x(?P<height>\d+))?")
_STANDARD_IMG_RE = re.compile(r'<img([^>]*?)src="(?P<src>[^"]+)"([^>]*)>')

_CACHE: dict[tuple[str, str, str], AttachmentPlan] = {}


@dataclass(frozen=True, slots=True)
class AttachmentPlan:
    """An attachment resolved and staged for the manifest."""

    output_file: OutputFile
    public_url: str


def reset_attachment_cache() -> None:
    """Clear the module-level memoisation cache — called at the start of each build."""
    _CACHE.clear()


def resolve_attachment(ref: str, post: Post, config: SiteConfig, vault: Path) -> Path | None:
    """Find ``ref`` in the vault attachments folder or the post's local dir."""
    # 1. <vault>/<attachments_subfolder>/<ref>
    vault_candidate = vault / config.attachments_subfolder / ref
    if vault_candidate.is_file():
        return vault_candidate
    # 2. <post_dir>/<ref>
    local_candidate = post.source_path.parent / ref
    if local_candidate.is_file():
        return local_candidate
    return None


def plan_attachment(src: Path, post_slug: str, config: SiteConfig) -> AttachmentPlan:
    """Hash the source bytes and stage an :class:`OutputFile` under ``<assets_dir>/<slug>/``.

    Memoised per (src, post_slug, assets_dir) for the duration of a build.
    """
    src_key = str(src.resolve())
    key = (src_key, post_slug, str(config.assets_dir))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    data = src.read_bytes()
    digest = hashlib.sha256(data).hexdigest()[:8]
    assets_rel = PurePosixPath(config.assets_dir.relative_to(config.output_dir).as_posix())
    hashed_name = f"{digest}-{src.name}"
    relative_path = str(assets_rel / post_slug / hashed_name)
    public_url = f"{config.url_prefix}/{assets_rel.as_posix()}/{post_slug}/{hashed_name}"
    plan = AttachmentPlan(
        output_file=OutputFile(relative_path=relative_path, content=data),
        public_url=public_url,
    )
    _CACHE[key] = plan
    return plan


def substitute_embeds(
    html_body: str,
    post: Post,
    config: SiteConfig,
    warnings: list[BuildWarning],
    attachments_out: list[OutputFile],
    *,
    vault: Path,
    slug_map: SlugMap,
    render_ctx: RenderContext,
    depth: int = 0,
) -> str:
    """Replace every ``data-cress-embed`` placeholder with the appropriate tag."""

    def _repl(match: re.Match[str]) -> str:
        target = html.unescape(match.group("target"))
        alias = html.unescape(match.group("alias") or "")
        return _render_embed(
            target,
            alias,
            post,
            config,
            warnings,
            attachments_out,
            vault,
            slug_map,
            render_ctx,
            depth,
        )

    return _EMBED_PLACEHOLDER_RE.sub(_repl, html_body)


def substitute_standard_images(
    html_body: str,
    post: Post,
    config: SiteConfig,
    warnings: list[BuildWarning],
    attachments_out: list[OutputFile],
    *,
    vault: Path,
) -> str:
    """Resolve every ``<img src="...">`` against the attachment pipeline."""
    assert post.slug is not None, "substitute_standard_images requires a slugged post"

    def _repl(match: re.Match[str]) -> str:
        pre, src, post_attrs = match.group(1), match.group("src"), match.group(3)
        src_unescaped = html.unescape(src)
        if src_unescaped.startswith(("http://", "https://", "/", "data:")):
            return match.group(0)
        resolved = resolve_attachment(src_unescaped, post, config, vault)
        if resolved is None:
            warnings.append(
                BuildWarning(
                    type="missing_attachment",
                    file=str(post.source_path),
                    message=f"image src {src_unescaped!r} not found",
                )
            )
            return match.group(0)
        assert post.slug is not None
        plan = plan_attachment(resolved, post.slug, config)
        if plan.output_file not in attachments_out:
            attachments_out.append(plan.output_file)
        return f'<img{pre}src="{html.escape(plan.public_url)}"{post_attrs}>'

    return _STANDARD_IMG_RE.sub(_repl, html_body)


def _split_alias(alias: str) -> tuple[str, str, str]:
    """Split an Obsidian embed alias into (alt text, size attrs, class attr).

    Each pipe segment is classified independently: ``300`` / ``300x200`` set
    width/height, ``left`` / ``right`` set a float hook class (``embed-left``
    / ``embed-right`` — the consumer's stylesheet decides what that means),
    and anything else is alt text. ``"Board view|right|300"`` →
    ``("Board view", ' width="300"', ' class="embed-right"')``.
    """
    if not alias:
        return "", "", ""
    alt_parts: list[str] = []
    size_attrs = ""
    class_attr = ""
    for segment in alias.split("|"):
        token = segment.strip()
        size = _ALIAS_SIZE_RE.fullmatch(token)
        if size is not None:
            size_attrs = f' width="{size.group("width")}"'
            if size.group("height"):
                size_attrs += f' height="{size.group("height")}"'
        elif token.lower() in ("left", "right"):
            class_attr = f' class="embed-{token.lower()}"'
        else:
            alt_parts.append(segment)
    return "|".join(alt_parts), size_attrs, class_attr


def _render_embed(
    target: str,
    alias: str,
    post: Post,
    config: SiteConfig,
    warnings: list[BuildWarning],
    attachments_out: list[OutputFile],
    vault: Path,
    slug_map: SlugMap,
    render_ctx: RenderContext,
    depth: int,
) -> str:
    """Dispatch a single embed target to image/video/audio/markdown/link/broken."""
    suffix = PurePosixPath(target).suffix.lower()
    if suffix in _MARKDOWN_EXTS:
        return _render_markdown_transclusion(
            target, post, config, warnings, attachments_out, vault, slug_map, render_ctx, depth
        )

    resolved = resolve_attachment(target, post, config, vault)
    if resolved is None:
        warnings.append(
            BuildWarning(
                type="missing_embed",
                file=str(post.source_path),
                message=f"embed target {target!r} not found",
            )
        )
        return f'<span class="broken-embed">{html.escape(target)}</span>'

    assert post.slug is not None, "embed substitution requires a slugged post"
    plan = plan_attachment(resolved, post.slug, config)
    if plan.output_file not in attachments_out:
        attachments_out.append(plan.output_file)

    url = html.escape(plan.public_url)
    alt_text, size_attrs, class_attr = _split_alias(alias)
    alt = html.escape(alt_text or PurePosixPath(target).stem)
    if suffix in _IMAGE_EXTS:
        return f'<img src="{url}" alt="{alt}"{size_attrs}{class_attr}>'
    if suffix in _VIDEO_EXTS:
        return f'<video src="{url}"{size_attrs}{class_attr} controls></video>'
    if suffix in _AUDIO_EXTS:
        return f'<audio src="{url}" controls></audio>'
    return f'<a href="{url}">{html.escape(alt_text or target)}</a>'


def _render_markdown_transclusion(
    target: str,
    post: Post,
    config: SiteConfig,
    warnings: list[BuildWarning],
    attachments_out: list[OutputFile],
    vault: Path,
    slug_map: SlugMap,
    render_ctx: RenderContext,
    depth: int,
) -> str:
    """Inline another post's body as a ``<blockquote class="transclusion">``."""
    if depth >= _MAX_TRANSCLUSION_DEPTH:
        warnings.append(
            BuildWarning(
                type="missing_embed",
                file=str(post.source_path),
                message=f"transclusion depth exceeded for {target!r}",
            )
        )
        return f'<span class="broken-embed">{html.escape(target)}</span>'

    stem = PurePosixPath(target).stem.lower()
    target_post = slug_map.by_filename_lower.get(stem)
    if target_post is None:
        warnings.append(
            BuildWarning(
                type="missing_embed",
                file=str(post.source_path),
                message=f"transclusion target {target!r} not found",
            )
        )
        return f'<span class="broken-embed">{html.escape(target)}</span>'

    inner_html = render_markdown_text(target_post.body_md, render_ctx)
    inner_html = substitute_wikilinks(
        inner_html, slug_map, warnings, target_post.source_path, config.url_prefix
    )
    inner_html = substitute_embeds(
        inner_html,
        target_post,
        config,
        warnings,
        attachments_out,
        vault=vault,
        slug_map=slug_map,
        render_ctx=render_ctx,
        depth=depth + 1,
    )
    return f'<blockquote class="transclusion">{inner_html}</blockquote>'
