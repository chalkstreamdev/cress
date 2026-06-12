"""Sitemap and RSS feed generation.

``sitemap.xml`` renders from a Django template over non-draft posts.
``rss.xml`` is generated with feedgen and limited to ``features.rss_count``
recent posts.

Both generators return an empty list when their respective feature flag is
off, so the orchestrator can unconditionally splat them into the output list.
"""

import datetime as _dt

from feedgen.feed import FeedGenerator

from cress.manifest import OutputFile
from cress.pages import PageContext
from cress.post import Post
from cress.render import render_template
from cress.taxonomy import Taxonomy


def _canonical(path: str, base_url: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _post_url(post: Post, base_url: str) -> str:
    assert post.slug is not None
    return _canonical(f"{post.slug}/", base_url)


def _iso_date(value: _dt.date | _dt.datetime) -> str:
    return value.date().isoformat() if isinstance(value, _dt.datetime) else value.isoformat()


def render_sitemap(
    posts: list[Post],
    tag_taxonomy: Taxonomy,
    category_taxonomy: Taxonomy,
    ctx: PageContext,
) -> list[OutputFile]:
    """Render ``sitemap.xml``. Empty list when ``features.sitemap`` is off."""
    if not ctx.config.features.sitemap:
        return []

    base_url = ctx.config.site.base_url
    entries: list[dict[str, str | None]] = []
    # Home page
    entries.append({"loc": _canonical("/", base_url), "lastmod": None})
    # Posts (non-draft only)
    for post in posts:
        if post.draft or post.slug is None:
            continue
        lastmod = _iso_date(post.updated or post.date)
        entries.append({"loc": _post_url(post, base_url), "lastmod": lastmod})
    # Tag and category pages
    for slug, _display, group_posts in tag_taxonomy.grouped():
        if any(not p.draft for p in group_posts):
            entries.append({"loc": _canonical(f"/tag/{slug}/", base_url), "lastmod": None})
    for slug, _display, group_posts in category_taxonomy.grouped():
        if any(not p.draft for p in group_posts):
            entries.append({"loc": _canonical(f"/category/{slug}/", base_url), "lastmod": None})

    template = ctx.config.templates.get("sitemap", "defaults/sitemap.xml")
    xml = render_template(ctx.engine, template, {"entries": entries})
    return [OutputFile(relative_path="sitemap.xml", content=xml)]


def render_rss(posts: list[Post], ctx: PageContext) -> list[OutputFile]:
    """Render ``rss.xml`` via feedgen. Empty list when ``features.rss`` is off."""
    if not ctx.config.features.rss:
        return []

    site = ctx.config.site
    fg = FeedGenerator()
    fg.title(site.title)
    fg.link(href=site.base_url, rel="alternate")
    fg.description(site.description)
    fg.language(site.locale.replace("_", "-"))

    published = [p for p in posts if not p.draft and p.slug is not None]
    published.sort(key=lambda p: p.date, reverse=True)
    # Pin lastBuildDate to the latest post's date so rebuilds with no source
    # changes produce byte-identical RSS — otherwise feedgen inserts
    # ``datetime.now()`` and ``cress publish`` would churn commits.
    if published:
        fg.lastBuildDate(_ensure_tz(published[0].date))
    for post in published[: ctx.config.features.rss_count]:
        entry = fg.add_entry()
        entry.title(post.title)
        entry.link(href=_post_url(post, site.base_url))
        entry.description(post.summary or site.description)
        entry.pubDate(_ensure_tz(post.date))
        entry.guid(_post_url(post, site.base_url), permalink=True)

    rss_bytes = fg.rss_str(pretty=True)
    assert isinstance(rss_bytes, bytes)
    return [OutputFile(relative_path="rss.xml", content=rss_bytes.decode("utf-8"))]


def _ensure_tz(value: _dt.date | _dt.datetime) -> _dt.datetime:
    """Return a timezone-aware datetime — feedgen rejects naive values."""
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_dt.UTC)
        return value
    return _dt.datetime.combine(value, _dt.time(0, 0), tzinfo=_dt.UTC)
