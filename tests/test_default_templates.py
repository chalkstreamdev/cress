"""Render-snapshot tests for shipped default templates — all must render cleanly."""

from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest

from cress.config import FeaturesConfig, SiteConfig, SiteMetaConfig
from cress.plugins import PluginRegistry
from cress.render import build_engine, render_template


@pytest.fixture
def engine(tmp_path: Path):  # noqa: ANN201 — return type is django.Engine, pulled lazily
    target = tmp_path / "product"
    target.mkdir()
    output = target / "out"
    output.mkdir()
    config = SiteConfig(
        target=target,
        vault_subfolder="B",
        output_dir=output,
        site=SiteMetaConfig(
            title="Example",
            description="An example blog",
            base_url="https://example.com/blog",
            locale="en_US",
            twitter_handle="@example",
        ),
        assets_dir=output / "assets",
    )
    return build_engine(config, PluginRegistry())


@pytest.fixture
def site() -> SiteMetaConfig:
    return SiteMetaConfig(
        title="Example",
        description="An example blog",
        base_url="https://example.com/blog",
        locale="en_US",
        twitter_handle="@example",
    )


@pytest.fixture
def features() -> FeaturesConfig:
    return FeaturesConfig(json_ld=True, syntax_highlighting=True)


def _page(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "title": "Smart Chart Defaults",
        "slug": "smart-chart-defaults",
        "date": date(2026, 4, 19),
        "updated": date(2026, 4, 20),
        "author": "Nick",
        "summary": "A one-line summary",
        "tags": ["charts", "ux"],
        "categories": ["engineering"],
        "html": "<p>body <strong>text</strong></p>",
        "reading_time_minutes": 3,
        "image_url": "/assets/hero.png",
        "image_alt": "Hero",
        "url": "/smart-chart-defaults/",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _WellFormedChecker(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []
        # HTML5 void elements that have no closing tag.
        self._void = {"br", "img", "meta", "link", "hr", "input", "source"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag not in self._void:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._void:
            return
        if not self.stack:
            self.errors.append(f"closing {tag!r} with empty stack")
            return
        if self.stack[-1] != tag:
            # allow un-nested but paired tags at same level to pop
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.stack.pop()
                self.stack.pop()
            else:
                self.errors.append(f"unexpected close {tag!r} (stack top {self.stack[-1]!r})")
        else:
            self.stack.pop()


def _assert_well_formed_html(html: str) -> None:
    checker = _WellFormedChecker()
    checker.feed(html)
    assert not checker.errors, f"HTML not well-formed: {checker.errors}"
    assert not checker.stack, f"unclosed tags: {checker.stack}"


def test_post_html_renders_well_formed(
    engine, site: SiteMetaConfig, features: FeaturesConfig
) -> None:
    ctx: dict[str, object] = {
        "site": site,
        "features": features,
        "page": _page(),
        "now": date(2026, 4, 21),
        "cress_version": "0.0.1",
        "pygments_style": "default",
        "canonical_url": "https://example.com/blog/smart-chart-defaults/",
        "og_image_url": "https://example.com/blog/assets/hero.png",
    }
    html = render_template(engine, "defaults/post.html", ctx)
    assert "Smart Chart Defaults" in html
    assert "body <strong>text</strong>" in html
    assert 'href="/tag/charts/"' in html
    assert 'href="/category/engineering/"' in html
    assert 'rel="canonical"' in html
    assert 'article:tag" content="charts"' in html
    _assert_well_formed_html(html)


def test_index_html_renders(engine, site: SiteMetaConfig, features: FeaturesConfig) -> None:
    ctx = {
        "site": site,
        "features": features,
        "posts": [_page(title="Post A", url="/a/"), _page(title="Post B", url="/b/")],
        "pagination": SimpleNamespace(page=1, total_pages=2, prev_url=None, next_url="/page/2/"),
        "now": date(2026, 4, 21),
        "cress_version": "0.0.1",
        "pygments_style": "default",
        "canonical_url": "https://example.com/blog/",
        "og_image_url": None,
        "page": None,
    }
    html = render_template(engine, "defaults/index.html", ctx)
    assert "Post A" in html and "Post B" in html
    assert 'rel="next"' in html
    _assert_well_formed_html(html)


def test_tag_html_renders(engine, site: SiteMetaConfig, features: FeaturesConfig) -> None:
    ctx = {
        "site": site,
        "features": features,
        "display": "Charts",
        "posts": [_page(title="Post A", url="/a/")],
        "pagination": SimpleNamespace(page=1, total_pages=1, prev_url=None, next_url=None),
        "now": date(2026, 4, 21),
        "cress_version": "0.0.1",
        "pygments_style": "default",
        "canonical_url": "https://example.com/blog/tag/charts/",
        "og_image_url": None,
        "page": None,
    }
    html = render_template(engine, "defaults/tag.html", ctx)
    assert "Tag: Charts" in html


def test_category_html_renders(engine, site: SiteMetaConfig, features: FeaturesConfig) -> None:
    ctx = {
        "site": site,
        "features": features,
        "display": "Engineering",
        "posts": [_page(title="Post A", url="/a/")],
        "pagination": SimpleNamespace(page=1, total_pages=1, prev_url=None, next_url=None),
        "now": date(2026, 4, 21),
        "cress_version": "0.0.1",
        "pygments_style": "default",
        "canonical_url": "https://example.com/blog/category/engineering/",
        "og_image_url": None,
        "page": None,
    }
    html = render_template(engine, "defaults/category.html", ctx)
    assert "Category: Engineering" in html


def test_tag_list_and_category_list_render(
    engine, site: SiteMetaConfig, features: FeaturesConfig
) -> None:
    entries = [("charts", "Charts", 3), ("ux", "UX", 1)]
    for tpl in ("tag_list.html", "category_list.html"):
        ctx = {
            "site": site,
            "features": features,
            "entries": entries,
            "now": date(2026, 4, 21),
            "cress_version": "0.0.1",
            "pygments_style": "default",
            "canonical_url": "https://example.com/blog/",
            "og_image_url": None,
            "page": None,
        }
        html = render_template(engine, f"defaults/{tpl}", ctx)
        assert "(3)" in html and "(1)" in html


def _base_ctx(
    site: SiteMetaConfig, features: FeaturesConfig, **overrides: object
) -> dict[str, object]:
    ctx: dict[str, object] = {
        "site": site,
        "features": features,
        "now": date(2026, 4, 21),
        "cress_version": "0.0.1",
        "pygments_style": "default",
        "canonical_url": "https://example.com/blog/",
        "og_image_url": None,
        "page": None,
        "stylesheets": (),
    }
    ctx.update(overrides)
    return ctx


def test_base_html_emits_no_link_when_stylesheets_empty(
    engine, site: SiteMetaConfig, features: FeaturesConfig
) -> None:
    bare_features = FeaturesConfig(syntax_highlighting=False)
    html = render_template(
        engine,
        "defaults/base.html",
        _base_ctx(site, bare_features, stylesheets=()),
    )
    assert '<link rel="stylesheet"' not in html


def test_base_html_emits_one_link_per_stylesheet(
    engine, site: SiteMetaConfig, features: FeaturesConfig
) -> None:
    bare_features = FeaturesConfig(syntax_highlighting=False)
    html = render_template(
        engine,
        "defaults/base.html",
        _base_ctx(
            site,
            bare_features,
            stylesheets=("/assets/main-abc.css", "/fonts.css"),
        ),
    )
    assert html.count('<link rel="stylesheet"') == 2
    assert 'href="/assets/main-abc.css"' in html
    assert 'href="/fonts.css"' in html


def test_base_html_escapes_stylesheet_href(
    engine, site: SiteMetaConfig, features: FeaturesConfig
) -> None:
    bare_features = FeaturesConfig(syntax_highlighting=False)
    nasty = '/x.css"><script>alert(1)</script>'
    html = render_template(
        engine,
        "defaults/base.html",
        _base_ctx(site, bare_features, stylesheets=(nasty,)),
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html or "&quot;" in html


def test_sitemap_xml_renders_urls(engine) -> None:
    entries = [
        SimpleNamespace(loc="https://example.com/blog/", lastmod="2026-04-19"),
        SimpleNamespace(loc="https://example.com/blog/a/", lastmod=None),
    ]
    xml = render_template(engine, "defaults/sitemap.xml", {"entries": entries})
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    locs = [e.text for e in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert "https://example.com/blog/" in locs
    assert "https://example.com/blog/a/" in locs
