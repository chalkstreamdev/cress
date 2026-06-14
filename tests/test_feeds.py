"""Tests for cress.feeds — sitemap + RSS generation."""

import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from cress.config import FeaturesConfig, SiteConfig, SiteMetaConfig
from cress.feeds import render_rss, render_sitemap
from cress.pages import PageContext
from cress.plugins import PluginRegistry
from cress.post import Post
from cress.render import build_engine
from cress.reports import BuildWarning
from cress.taxonomy import Taxonomy


@pytest.fixture
def site_config(tmp_path: Path) -> SiteConfig:
    target = tmp_path / "product"
    target.mkdir()
    out = target / "o"
    out.mkdir()
    return SiteConfig(
        target=target,
        vault_subfolder="B",
        output_dir=out,
        site=SiteMetaConfig(
            title="Example",
            description="Example blog",
            base_url="https://example.com/blog",
            locale="en_US",
        ),
        assets_dir=out / "assets",
        features=FeaturesConfig(rss=True, sitemap=True, rss_count=5),
    )


@pytest.fixture
def ctx(site_config: SiteConfig) -> PageContext:
    engine = build_engine(site_config, PluginRegistry())
    return PageContext(
        config=site_config,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
    )


def _post(
    slug: str,
    title: str = "T",
    *,
    draft: bool = False,
    d: date | None = date(2026, 4, 19),
    summary: str = "",
    url_path: str | None = None,
) -> Post:
    return Post(
        source_path=Path(f"{slug}.md"),
        title=title,
        date=d,
        body_md="",
        frontmatter_raw={},
        slug=slug,
        url_path=url_path if url_path is not None else slug,
        draft=draft,
        summary=summary,
    )


def test_render_sitemap_contains_post_urls(ctx: PageContext) -> None:
    posts = [_post("p1"), _post("p2", d=date(2026, 4, 20))]
    tag_tax, cat_tax = Taxonomy(), Taxonomy()
    outs = render_sitemap(posts, tag_tax, cat_tax, ctx)
    assert len(outs) == 1
    xml = outs[0].content
    assert isinstance(xml, str)
    root = ET.fromstring(xml)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text for el in root.iterfind(".//sm:loc", ns)]
    assert "https://example.com/blog/p1/" in locs
    assert "https://example.com/blog/p2/" in locs


def test_rss_disabled_in_static_mode(ctx: PageContext) -> None:
    static_ctx = replace(ctx, config=replace(ctx.config, static_pages=True))
    outs = render_rss([_post("p1"), _post("p2")], static_ctx)
    assert outs == []


def test_sitemap_omits_lastmod_for_dateless_page(ctx: PageContext) -> None:
    posts = [_post("install", d=None, url_path="guides/install")]
    outs = render_sitemap(posts, Taxonomy(), Taxonomy(), ctx)
    content = outs[0].content
    assert isinstance(content, str)
    assert "https://example.com/blog/guides/install/" in content
    # No date anywhere → no <lastmod> elements at all (home is dateless too).
    assert "<lastmod>" not in content


def test_sitemap_uses_hierarchical_url(ctx: PageContext) -> None:
    posts = [_post("install", url_path="guides/install")]
    outs = render_sitemap(posts, Taxonomy(), Taxonomy(), ctx)
    content = outs[0].content
    assert isinstance(content, str)
    assert "https://example.com/blog/guides/install/" in content


def test_render_sitemap_excludes_drafts(ctx: PageContext) -> None:
    posts = [_post("p1"), _post("secret", draft=True)]
    outs = render_sitemap(posts, Taxonomy(), Taxonomy(), ctx)
    content = outs[0].content
    assert isinstance(content, str)
    assert "/p1/" in content
    assert "/secret/" not in content
    assert "_drafts" not in content


def test_render_sitemap_disabled_returns_empty(site_config: SiteConfig, ctx: PageContext) -> None:
    config = SiteConfig(
        target=site_config.target,
        vault_subfolder=site_config.vault_subfolder,
        output_dir=site_config.output_dir,
        site=site_config.site,
        assets_dir=site_config.assets_dir,
        features=FeaturesConfig(sitemap=False),
    )
    ctx_disabled = PageContext(
        config=config,
        engine=ctx.engine,
        now=ctx.now,
        cress_version=ctx.cress_version,
    )
    assert render_sitemap([_post("p1")], Taxonomy(), Taxonomy(), ctx_disabled) == []


def test_render_rss_emits_well_formed_xml_and_excludes_drafts(ctx: PageContext) -> None:
    posts = [
        _post("p1", d=date(2026, 4, 19), summary="sum1"),
        _post("p2", d=date(2026, 4, 20), summary="sum2"),
        _post("secret", d=date(2026, 4, 21), draft=True, summary="nope"),
    ]
    outs = render_rss(posts, ctx)
    assert len(outs) == 1
    assert outs[0].relative_path == "rss.xml"
    xml = outs[0].content
    assert isinstance(xml, (str, bytes))
    xml_str = xml if isinstance(xml, str) else xml.decode("utf-8")
    root = ET.fromstring(xml_str)
    items = root.findall(".//item")
    titles = [item.findtext("title") for item in items]
    assert "T" in titles
    links = [item.findtext("link") for item in items]
    assert "https://example.com/blog/p1/" in links
    assert "https://example.com/blog/p2/" in links
    assert "https://example.com/blog/secret/" not in links
    # pubDate RFC 822 — starts with a day-of-week abbrev like "Sun, " / "Mon, " etc.
    pubdates = [item.findtext("pubDate") for item in items]
    assert all(pd and pd[3:5] == ", " for pd in pubdates)


def test_render_rss_respects_rss_count_cap(ctx: PageContext) -> None:
    posts = [_post(f"p{i}", d=date(2026, 4, (i % 28) + 1), summary="s") for i in range(20)]
    outs = render_rss(posts, ctx)
    xml = outs[0].content
    xml_str = xml if isinstance(xml, str) else xml.decode("utf-8")
    root = ET.fromstring(xml_str)
    # rss_count in fixture is 5
    assert len(root.findall(".//item")) == 5


def test_render_rss_disabled_returns_empty(site_config: SiteConfig, ctx: PageContext) -> None:
    config = SiteConfig(
        target=site_config.target,
        vault_subfolder=site_config.vault_subfolder,
        output_dir=site_config.output_dir,
        site=site_config.site,
        assets_dir=site_config.assets_dir,
        features=FeaturesConfig(rss=False),
    )
    ctx_disabled = PageContext(
        config=config,
        engine=ctx.engine,
        now=ctx.now,
        cress_version=ctx.cress_version,
    )
    assert render_rss([_post("p1")], ctx_disabled) == []


def test_sitemap_uses_updated_when_present(ctx: PageContext) -> None:
    p = Post(
        source_path=Path("p.md"),
        title="T",
        date=date(2026, 4, 19),
        updated=date(2026, 4, 21),
        body_md="",
        frontmatter_raw={},
        slug="p",
    )
    outs = render_sitemap([p], Taxonomy(), Taxonomy(), ctx)
    content = outs[0].content
    assert isinstance(content, str)
    assert "2026-04-21" in content


def test_sitemap_suppresses_drafts_and_includes_tag_and_category_urls(ctx: PageContext) -> None:
    warnings: list[BuildWarning] = []
    tag_tax = Taxonomy()
    cat_tax = Taxonomy()
    p1 = _post("p1")
    p2 = _post("secret", draft=True)
    tag_tax.add("charts", p1, warnings)
    tag_tax.add("charts", p2, warnings)
    cat_tax.add("engineering", p1, warnings)
    outs = render_sitemap([p1, p2], tag_tax, cat_tax, ctx)
    content = outs[0].content
    assert isinstance(content, str)
    assert "/tag/charts/" in content
    assert "/category/engineering/" in content
