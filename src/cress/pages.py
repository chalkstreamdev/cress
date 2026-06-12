"""Page generators.

Produces the full set of output pages as :class:`~cress.manifest.OutputFile`
entries — per-post, per-draft, paginated index, tag and category pages, and
tag/category list pages. All generators accept a shared render context and
return in-memory output for the manifest writer to persist.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.template import Engine

from cress.config import SiteConfig
from cress.manifest import OutputFile
from cress.post import Post
from cress.render import render_template, resolve_template_name
from cress.taxonomy import Taxonomy


@dataclass(frozen=True, slots=True)
class PageContext:
    """Shared rendering context passed to every page generator."""

    config: SiteConfig
    engine: Engine
    now: datetime
    cress_version: str
    # Resolved once per build (Vite manifest + extra_stylesheets) and reused
    # across every page. Empty by default so consumers without a frontend
    # build pipeline render unstyled, per spec.
    stylesheets: tuple[str, ...] = ()


def _post_path(post: Post) -> str:
    """Path relative to the site root (no ``url_prefix``) for canonical URLs and on-disk layout."""
    assert post.slug is not None
    if post.draft:
        token = hashlib.sha256(post.slug.encode("utf-8")).hexdigest()[:8]
        return f"/_drafts/{token}-{post.slug}/"
    return f"/{post.slug}/"


def _post_url(post: Post, config: SiteConfig) -> str:
    """Public URL (``url_prefix`` applied). Used for hrefs rendered into HTML."""
    return f"{config.url_prefix}{_post_path(post)}"


def _page_view(post: Post, config: SiteConfig, body_html: str = "") -> dict[str, Any]:
    return {
        "slug": post.slug,
        "title": post.title,
        "date": post.date,
        "updated": post.updated,
        "author": post.author,
        "summary": post.summary,
        "tags": post.tags,
        "categories": post.categories,
        "html": body_html,
        "reading_time_minutes": post.reading_time_minutes,
        "image_url": post.image,
        "image_alt": post.image_alt,
        "url": _post_url(post, config),
    }


def _canonical(path: str, config: SiteConfig) -> str:
    base = config.site.base_url.rstrip("/")
    rel = path.lstrip("/")
    return f"{base}/{rel}"


def _base_context(ctx: PageContext, *, canonical_path: str) -> dict[str, Any]:
    return {
        "site": ctx.config.site,
        "features": ctx.config.features,
        "now": ctx.now,
        "cress_version": ctx.cress_version,
        "pygments_style": ctx.config.pygments_style,
        "url_prefix": ctx.config.url_prefix,
        "canonical_url": _canonical(canonical_path, ctx.config),
        "og_image_url": None,
        "page": None,
        "stylesheets": ctx.stylesheets,
    }


def render_post_page(post: Post, body_html: str, ctx: PageContext) -> OutputFile:
    """Render ``<slug>/index.html`` for a published post."""
    assert post.slug is not None
    path = _post_path(post)
    view = _page_view(post, ctx.config, body_html)
    context = _base_context(ctx, canonical_path=path)
    context["page"] = view
    name = resolve_template_name("post", ctx.config)
    html = render_template(ctx.engine, name, context)
    return OutputFile(relative_path=f"{post.slug}/index.html", content=html)


def render_draft_page(post: Post, body_html: str, ctx: PageContext) -> OutputFile:
    """Render the draft-preview page at ``_drafts/<token>-<slug>/index.html``."""
    assert post.slug is not None
    token = hashlib.sha256(post.slug.encode("utf-8")).hexdigest()[:8]
    path = f"/_drafts/{token}-{post.slug}/"
    view = _page_view(post, ctx.config, body_html)
    context = _base_context(ctx, canonical_path=path)
    context["page"] = view
    name = resolve_template_name("post", ctx.config)
    html = render_template(ctx.engine, name, context)
    return OutputFile(relative_path=f"_drafts/{token}-{post.slug}/index.html", content=html)


def render_index_pages(
    posts_with_html: list[tuple[Post, str]], ctx: PageContext
) -> list[OutputFile]:
    """Render reverse-chronological paginated ``/index.html`` + ``/page/N/index.html``."""
    published = [
        (p, body) for p, body in posts_with_html if not p.draft and p.slug is not None
    ]
    published.sort(key=lambda item: item[0].date, reverse=True)
    return _paginate(
        items=[_page_view(p, ctx.config, body) for p, body in published],
        template_name=resolve_template_name("index", ctx.config),
        path_prefix="",
        ctx=ctx,
        extra_context={},
    )


def render_tag_pages(taxonomy: Taxonomy, ctx: PageContext) -> list[OutputFile]:
    """Render ``/tag/<slug>/index.html`` + pagination pages."""
    outs: list[OutputFile] = []
    template = resolve_template_name("tag", ctx.config)
    for slug, display, posts in taxonomy.grouped():
        non_draft = [p for p in posts if not p.draft and p.slug is not None]
        outs.extend(
            _paginate(
                items=[_page_view(p, ctx.config) for p in non_draft],
                template_name=template,
                path_prefix=f"tag/{slug}",
                ctx=ctx,
                extra_context={"display": display},
            )
        )
    return outs


def render_category_pages(taxonomy: Taxonomy, ctx: PageContext) -> list[OutputFile]:
    """Render ``/category/<slug>/index.html`` + pagination pages."""
    outs: list[OutputFile] = []
    template = resolve_template_name("category", ctx.config)
    for slug, display, posts in taxonomy.grouped():
        non_draft = [p for p in posts if not p.draft and p.slug is not None]
        outs.extend(
            _paginate(
                items=[_page_view(p, ctx.config) for p in non_draft],
                template_name=template,
                path_prefix=f"category/{slug}",
                ctx=ctx,
                extra_context={"display": display},
            )
        )
    return outs


def render_tag_list(taxonomy: Taxonomy, ctx: PageContext) -> OutputFile:
    """Render ``/tags/index.html``."""
    entries = [
        (slug, display, sum(1 for p in posts if not p.draft))
        for slug, display, posts in taxonomy.grouped()
    ]
    entries = [(s, d, c) for s, d, c in entries if c > 0]
    context = _base_context(ctx, canonical_path="/tags/")
    context["entries"] = entries
    name = resolve_template_name("tag_list", ctx.config)
    html = render_template(ctx.engine, name, context)
    return OutputFile(relative_path="tags/index.html", content=html)


def render_category_list(taxonomy: Taxonomy, ctx: PageContext) -> OutputFile:
    """Render ``/categories/index.html``."""
    entries = [
        (slug, display, sum(1 for p in posts if not p.draft))
        for slug, display, posts in taxonomy.grouped()
    ]
    entries = [(s, d, c) for s, d, c in entries if c > 0]
    context = _base_context(ctx, canonical_path="/categories/")
    context["entries"] = entries
    name = resolve_template_name("category_list", ctx.config)
    html = render_template(ctx.engine, name, context)
    return OutputFile(relative_path="categories/index.html", content=html)


def _paginate(
    *,
    items: list[dict[str, Any]],
    template_name: str,
    path_prefix: str,
    ctx: PageContext,
    extra_context: dict[str, Any],
) -> list[OutputFile]:
    """Chunk ``items`` into pages of size ``paginate`` and render each."""
    page_size = ctx.config.paginate
    total = max(1, (len(items) + page_size - 1) // page_size)
    outs: list[OutputFile] = []
    prefix = f"{path_prefix}/" if path_prefix else ""
    url_pfx = ctx.config.url_prefix
    for page_num in range(1, total + 1):
        start = (page_num - 1) * page_size
        chunk = items[start : start + page_size]
        relative_path = (
            f"{prefix}index.html" if page_num == 1 else f"{prefix}page/{page_num}/index.html"
        )
        canonical_path = "/" + relative_path.removesuffix("index.html")
        prev_url: str | None
        if page_num == 2:
            prev_url = f"{url_pfx}/{prefix}" if prefix else f"{url_pfx}/"
        elif page_num > 2:
            prev_url = f"{url_pfx}/{prefix}page/{page_num - 1}/"
        else:
            prev_url = None
        next_url = f"{url_pfx}/{prefix}page/{page_num + 1}/" if page_num < total else None
        pagination = {
            "page": page_num,
            "total_pages": total,
            "prev_url": prev_url,
            "next_url": next_url,
        }
        context = _base_context(ctx, canonical_path=canonical_path)
        context["posts"] = chunk
        context["pagination"] = pagination
        context.update(extra_context)
        html = render_template(ctx.engine, template_name, context)
        outs.append(OutputFile(relative_path=relative_path, content=html))
    return outs
