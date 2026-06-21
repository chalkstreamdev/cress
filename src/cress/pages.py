"""Page generators.

Produces the full set of output pages as :class:`~cress.manifest.OutputFile`
entries — per-post, per-draft, paginated index, tag and category pages, and
tag/category list pages. All generators accept a shared render context and
return in-memory output for the manifest writer to persist.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from django.template import Engine

from cress.config import SiteConfig
from cress.manifest import OutputFile
from cress.nav import NavTree, breadcrumbs_for
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
    # Site-wide fallback ``og:image`` URL (from ``site.default_image``). A post
    # with its own resolved hero image overrides this; pages without a hero fall
    # back to it. ``None`` when no default image is configured.
    default_image_url: str | None = None
    # Navigation tree (static-pages mode), built once per build from the
    # filtered, non-``nav_hidden`` posts. Always present in context so templates
    # can render a sidebar; the default templates only do so when
    # ``static_pages`` is true. Empty by default (blog mode never uses it).
    nav: NavTree = field(default_factory=lambda: NavTree(roots=(), by_path={}))


def _sort_date(post: Post) -> date | datetime:
    """Index sort key for blog mode, where ``date`` is guaranteed present."""
    assert post.date is not None, "blog-mode index requires a date on every post"
    return post.date


def _post_path(post: Post) -> str:
    """Path relative to the site root (no ``url_prefix``) for canonical URLs and on-disk layout."""
    assert post.slug is not None
    if post.draft:
        token = hashlib.sha256(post.slug.encode("utf-8")).hexdigest()[:8]
        return f"/_drafts/{token}-{post.slug}/"
    return f"/{post.url_path}/"


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


def _absolute_image_url(url: str, config: SiteConfig) -> str:
    """Promote an image reference to the absolute URL og:image requires.

    External (``http(s)://``), protocol-relative (``//``) and ``data:`` URLs are
    already absolute enough for social scrapers and pass through. Site-relative
    references (e.g. a resolved hero's ``/blog/assets/...`` public URL, which
    already carries ``url_prefix``) are prefixed with the site *origin* —
    scheme + host from ``site.base_url`` — not ``base_url`` itself, which would
    duplicate the path prefix.
    """
    if url.startswith(("http://", "https://", "//", "data:")):
        return url
    parsed = urlparse(config.site.base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return f"{origin}{url}" if url.startswith("/") else f"{origin}/{url}"


def _base_context(ctx: PageContext, *, canonical_path: str) -> dict[str, Any]:
    return {
        "site": ctx.config.site,
        "features": ctx.config.features,
        "now": ctx.now,
        "cress_version": ctx.cress_version,
        "pygments_style": ctx.config.pygments_style,
        "url_prefix": ctx.config.url_prefix,
        "canonical_url": _canonical(canonical_path, ctx.config),
        "og_image_url": (
            _absolute_image_url(ctx.default_image_url, ctx.config)
            if ctx.default_image_url is not None
            else None
        ),
        "og_image_alt": None,
        "page": None,
        "stylesheets": ctx.stylesheets,
        "nav": ctx.nav,
        "static_pages": ctx.config.static_pages,
        # Default trail (Home, or empty in blog mode). Post pages override this
        # with their own ancestor chain in :func:`_post_context`.
        "breadcrumbs": breadcrumbs_for("", ctx.nav),
    }


def _post_context(post: Post, body_html: str, ctx: PageContext, path: str) -> dict[str, Any]:
    """Build the template context for a single-post page (published or draft)."""
    view = _page_view(post, ctx.config, body_html)
    context = _base_context(ctx, canonical_path=path)
    context["page"] = view
    context["breadcrumbs"] = breadcrumbs_for(post.url_path, ctx.nav)
    # A post's own hero image wins over the site-wide default for og:image.
    if view["image_url"] is not None:
        context["og_image_url"] = _absolute_image_url(view["image_url"], ctx.config)
        context["og_image_alt"] = view["image_alt"]
    return context


def render_post_page(post: Post, body_html: str, ctx: PageContext) -> OutputFile:
    """Render ``<slug>/index.html`` for a published post."""
    assert post.slug is not None
    path = _post_path(post)
    context = _post_context(post, body_html, ctx, path)
    name = resolve_template_name("post", ctx.config)
    html = render_template(ctx.engine, name, context)
    return OutputFile(relative_path=f"{post.url_path}/index.html", content=html)


def render_draft_page(post: Post, body_html: str, ctx: PageContext) -> OutputFile:
    """Render the draft-preview page at ``_drafts/<token>-<slug>/index.html``."""
    assert post.slug is not None
    token = hashlib.sha256(post.slug.encode("utf-8")).hexdigest()[:8]
    path = f"/_drafts/{token}-{post.slug}/"
    context = _post_context(post, body_html, ctx, path)
    name = resolve_template_name("post", ctx.config)
    html = render_template(ctx.engine, name, context)
    return OutputFile(relative_path=f"_drafts/{token}-{post.slug}/index.html", content=html)


def render_index_pages(
    posts_with_html: list[tuple[Post, str]], ctx: PageContext
) -> list[OutputFile]:
    """Render the paginated ``/index.html`` + ``/page/N/index.html``.

    Blog mode sorts reverse-chronological by ``date``. Static-pages mode has no
    reliable date (it may be ``None``), so it sorts by ``url_path`` ascending —
    deterministic and date-free.
    """
    published = [(p, body) for p, body in posts_with_html if not p.draft and p.slug is not None]
    if ctx.config.static_pages:
        published.sort(key=lambda item: item[0].url_path)
    else:
        published.sort(key=lambda item: _sort_date(item[0]), reverse=True)
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
    """Chunk ``items`` into pages of size ``paginate`` and render each.

    ``paginate == 0`` means unlimited: a single page holding every item, with no
    ``/page/N/`` splits.
    """
    if ctx.config.paginate <= 0:
        page_size = max(1, len(items))
        total = 1
    else:
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
