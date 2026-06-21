"""Tests for cress.pages — per-post, draft, index, tag, category page generation."""

import json
from dataclasses import replace as _replace
from datetime import date, datetime
from pathlib import Path

import pytest

from cress.config import SiteConfig, SiteMetaConfig
from cress.manifest import OutputFile
from cress.nav import NavTree, build_nav
from cress.pages import (
    PageContext,
    _base_context,
    _post_context,
    _post_url,
    render_category_list,
    render_category_pages,
    render_draft_page,
    render_index_pages,
    render_post_page,
    render_tag_list,
    render_tag_pages,
)
from cress.plugins import PluginRegistry
from cress.post import Post
from cress.render import build_engine
from cress.reports import BuildWarning
from cress.taxonomy import Taxonomy
from cress.vite_manifest import resolve_stylesheets


@pytest.fixture
def site_config(tmp_path: Path) -> SiteConfig:
    target = tmp_path / "product"
    target.mkdir()
    output = target / "out"
    output.mkdir()
    return SiteConfig(
        target=target,
        vault_subfolder="B",
        output_dir=output,
        site=SiteMetaConfig(title="Example", description="D", base_url="https://example.com/blog"),
        assets_dir=output / "assets",
        paginate=10,
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
    tags: list[str] | None = None,
    categories: list[str] | None = None,
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
        tags=tags or [],
        categories=categories or [],
    )


def test_render_post_page_path(ctx: PageContext) -> None:
    post = _post("hello", title="Hello")
    out = render_post_page(post, "<p>body</p>", ctx)
    assert isinstance(out, OutputFile)
    assert out.relative_path == "hello/index.html"
    assert "Hello" in out.content  # type: ignore[operator]


def test_blog_post_path_unchanged(ctx: PageContext) -> None:
    # Regression: blog mode (url_path == slug) writes the flat path as before.
    post = _post("hello", title="Hello")
    out = render_post_page(post, "<p>body</p>", ctx)
    assert out.relative_path == "hello/index.html"
    assert _post_url(post, ctx.config) == "/hello/"


def test_static_post_writes_to_hierarchical_path(ctx: PageContext) -> None:
    post = _post("install", title="Install", url_path="guides/install")
    out = render_post_page(post, "<p>body</p>", ctx)
    assert out.relative_path == "guides/install/index.html"


def test_post_path_includes_folder(ctx: PageContext) -> None:
    post = _post("install", url_path="guides/install")
    assert _post_url(post, ctx.config) == "/guides/install/"


def test_render_draft_page_path_stable(ctx: PageContext) -> None:
    post = _post("secret", title="Secret", draft=True)
    out1 = render_draft_page(post, "<p>body</p>", ctx)
    out2 = render_draft_page(post, "<p>body</p>", ctx)
    assert out1.relative_path == out2.relative_path
    assert out1.relative_path.startswith("_drafts/")
    assert out1.relative_path.endswith("-secret/index.html")


def test_render_index_pages_paginates(ctx: PageContext) -> None:
    posts = [(_post(f"p{i:02d}", d=date(2026, 4, i + 1)), "") for i in range(25)]
    outs = render_index_pages(posts, ctx)
    paths = [o.relative_path for o in outs]
    assert "index.html" in paths
    assert "page/2/index.html" in paths
    assert "page/3/index.html" in paths
    # 25 posts / 10 per page = 3 pages (10, 10, 5)


def test_paginate_zero_renders_single_unlimited_page(site_config: SiteConfig) -> None:
    unlimited_cfg = _replace(site_config, paginate=0)
    engine = build_engine(unlimited_cfg, PluginRegistry())
    unlimited_ctx = PageContext(
        config=unlimited_cfg,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
    )
    posts = [(_post(f"p{i:02d}", d=date(2026, 4, i + 1)), "") for i in range(25)]
    outs = render_index_pages(posts, unlimited_ctx)
    paths = [o.relative_path for o in outs]
    # Everything on one page — no /page/N/ splits — and every post is present.
    assert paths == ["index.html"]
    html = outs[0].content
    for i in range(25):
        assert f"p{i:02d}" in html


def test_paginate_zero_with_no_posts_is_safe(site_config: SiteConfig) -> None:
    unlimited_cfg = _replace(site_config, paginate=0)
    engine = build_engine(unlimited_cfg, PluginRegistry())
    unlimited_ctx = PageContext(
        config=unlimited_cfg,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
    )
    outs = render_index_pages([], unlimited_ctx)
    assert [o.relative_path for o in outs] == ["index.html"]


def test_static_index_sorts_by_url_path(site_config: SiteConfig) -> None:
    static_cfg = _replace(site_config, static_pages=True)
    engine = build_engine(static_cfg, PluginRegistry())
    static_ctx = PageContext(
        config=static_cfg,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
    )
    # b/x has the *later* date but the *later* path; url_path-ascending must
    # win, putting a/y first — proving date is not consulted.
    posts = [
        (_post("x", d=date(2026, 5, 1), url_path="b/x"), ""),
        (_post("y", d=date(2026, 1, 1), url_path="a/y"), ""),
    ]
    outs = render_index_pages(posts, static_ctx)
    html = outs[0].content
    assert isinstance(html, str)
    assert html.index("/a/y/") < html.index("/b/x/")


def test_blog_index_still_sorts_by_date(ctx: PageContext) -> None:
    # alphabetical url_path "a" is older; date-desc must put the newer "z" first.
    posts = [
        (_post("a", d=date(2026, 1, 1)), ""),
        (_post("z", d=date(2026, 5, 1)), ""),
    ]
    outs = render_index_pages(posts, ctx)
    html = outs[0].content
    assert isinstance(html, str)
    assert html.index("/z/") < html.index("/a/")


def test_render_index_excludes_drafts(ctx: PageContext) -> None:
    posts = [
        (_post("p1"), ""),
        (_post("draft", draft=True), ""),
        (_post("p2"), ""),
    ]
    outs = render_index_pages(posts, ctx)
    html = outs[0].content
    assert isinstance(html, str)
    assert "/p1/" in html
    assert "/p2/" in html
    assert "/draft/" not in html


def test_render_tag_pages_emits_pagination_when_needed(ctx: PageContext) -> None:
    tax = Taxonomy()
    warnings: list[BuildWarning] = []
    posts = [_post(f"p{i:02d}", d=date(2026, 4, i + 1), tags=["charts"]) for i in range(15)]
    for p in posts:
        tax.add("Charts", p, warnings)
    outs = render_tag_pages(tax, ctx)
    paths = [o.relative_path for o in outs]
    assert "tag/charts/index.html" in paths
    assert "tag/charts/page/2/index.html" in paths


def test_render_category_pages_single_page(ctx: PageContext) -> None:
    tax = Taxonomy()
    warnings: list[BuildWarning] = []
    tax.add("Engineering", _post("p1", categories=["engineering"]), warnings)
    outs = render_category_pages(tax, ctx)
    paths = [o.relative_path for o in outs]
    assert paths == ["category/engineering/index.html"]


def test_tag_pages_exclude_drafts(ctx: PageContext) -> None:
    tax = Taxonomy()
    warnings: list[BuildWarning] = []
    tax.add("Charts", _post("p1", tags=["charts"]), warnings)
    tax.add("Charts", _post("secret", tags=["charts"], draft=True), warnings)
    outs = render_tag_pages(tax, ctx)
    content = outs[0].content
    assert isinstance(content, str)
    assert "/p1/" in content
    assert "/secret/" not in content
    assert "/_drafts/" not in content


def test_render_tag_list_counts_exclude_drafts(ctx: PageContext) -> None:
    tax = Taxonomy()
    warnings: list[BuildWarning] = []
    tax.add("Charts", _post("p1", tags=["charts"]), warnings)
    tax.add("Charts", _post("p2", tags=["charts"]), warnings)
    tax.add("Charts", _post("secret", tags=["charts"], draft=True), warnings)
    out = render_tag_list(tax, ctx)
    content = out.content
    assert isinstance(content, str)
    assert "(2)" in content  # drafts excluded from counts
    assert out.relative_path == "tags/index.html"


def test_render_category_list(ctx: PageContext) -> None:
    tax = Taxonomy()
    warnings: list[BuildWarning] = []
    tax.add("Engineering", _post("p1", categories=["engineering"]), warnings)
    out = render_category_list(tax, ctx)
    assert out.relative_path == "categories/index.html"
    content = out.content
    assert isinstance(content, str)
    assert "Engineering" in content


# --- url_prefix behaviour ------------------------------------------------


def _config_with_prefix(tmp_path: Path, prefix: str) -> SiteConfig:
    target = tmp_path / "product"
    target.mkdir(exist_ok=True)
    output = target / "out"
    output.mkdir(exist_ok=True)
    return SiteConfig(
        target=target,
        vault_subfolder="B",
        output_dir=output,
        site=SiteMetaConfig(title="E", description="D", base_url="https://e.com" + prefix),
        assets_dir=output / "assets",
        paginate=10,
        url_prefix=prefix,
    )


def test_post_url_applies_url_prefix(tmp_path: Path) -> None:
    cfg = _config_with_prefix(tmp_path, "/blog")
    post = _post("hello")
    assert _post_url(post, cfg) == "/blog/hello/"


def test_post_url_no_prefix_unchanged(tmp_path: Path) -> None:
    cfg = _config_with_prefix(tmp_path, "")
    post = _post("hello")
    assert _post_url(post, cfg) == "/hello/"


def test_page_view_url_uses_prefix_in_post_render(tmp_path: Path) -> None:
    cfg = _config_with_prefix(tmp_path, "/blog")
    engine = build_engine(cfg, PluginRegistry())
    ctx_prefix = PageContext(
        config=cfg,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
    )
    post = _post("hello", tags=["charts"], categories=["engineering"])
    out = render_post_page(post, "<p>body</p>", ctx_prefix)
    assert out.relative_path == "hello/index.html"  # disk path unchanged
    content = out.content
    assert isinstance(content, str)
    assert 'href="/blog/tag/charts/"' in content
    assert 'href="/blog/category/engineering/"' in content


def test_pagination_urls_include_prefix(tmp_path: Path) -> None:
    cfg = _config_with_prefix(tmp_path, "/blog")
    engine = build_engine(cfg, PluginRegistry())
    ctx_prefix = PageContext(
        config=cfg,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
    )
    posts = [(_post(f"p{i:02d}", d=date(2026, 4, i + 1)), "") for i in range(25)]
    outs = render_index_pages(posts, ctx_prefix)
    # Disk paths unchanged — no prefix on relative_path.
    paths = [o.relative_path for o in outs]
    assert "index.html" in paths
    assert "page/2/index.html" in paths
    # But internal nav hrefs must include /blog.
    page2 = next(o for o in outs if o.relative_path == "page/2/index.html")
    c = page2.content
    assert isinstance(c, str)
    assert 'href="/blog/"' in c  # prev link from page 2 back to home
    assert 'href="/blog/page/3/"' in c


# --- og:image ------------------------------------------------------------


def test_post_hero_og_image_is_absolute(ctx: PageContext) -> None:
    """A site-relative resolved hero becomes an absolute og:image URL."""
    post = _replace(_post("hello"), image="/blog/assets/hero/abc123.png", image_alt="Hero shot")
    out = render_post_page(post, "<p>body</p>", ctx)
    content = out.content
    assert isinstance(content, str)
    assert (
        'property="og:image" content="https://example.com/blog/assets/hero/abc123.png"' in content
    )


def test_post_hero_og_image_alt_rendered(ctx: PageContext) -> None:
    post = _replace(_post("hello"), image="/blog/assets/hero/abc123.png", image_alt="Hero shot")
    out = render_post_page(post, "<p>body</p>", ctx)
    content = out.content
    assert isinstance(content, str)
    assert 'property="og:image:alt" content="Hero shot"' in content


def test_post_external_hero_og_image_passes_through(ctx: PageContext) -> None:
    post = _replace(_post("hello"), image="https://cdn.example.com/x.png")
    out = render_post_page(post, "<p>body</p>", ctx)
    content = out.content
    assert isinstance(content, str)
    assert 'property="og:image" content="https://cdn.example.com/x.png"' in content


def test_default_image_og_is_absolute(site_config: SiteConfig) -> None:
    """The ``site.default_image`` fallback (site-relative) is absolutized for og:image."""
    engine = build_engine(site_config, PluginRegistry())
    page_ctx = PageContext(
        config=site_config,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
        default_image_url="/blog/assets/_site/default.png",
    )
    post = _post("hello")  # no per-post hero
    out = render_post_page(post, "<p>body</p>", page_ctx)
    content = out.content
    assert isinstance(content, str)
    assert (
        'property="og:image" content="https://example.com/blog/assets/_site/default.png"' in content
    )


# --- stylesheet wiring ---------------------------------------------------


_VITE_MANIFEST: dict[str, object] = {
    "src/main.ts": {
        "file": "assets/main.js",
        "isEntry": True,
        "css": ["assets/main-abc.css"],
    },
}


def _write_vite_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "dist" / ".vite" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_VITE_MANIFEST), encoding="utf-8")
    return path


def test_resolve_stylesheets_manifest_only(site_config: SiteConfig, tmp_path: Path) -> None:
    manifest_path = _write_vite_manifest(tmp_path)
    cfg = _replace(site_config, vite_manifest=manifest_path)
    assert resolve_stylesheets(cfg) == ["/assets/main-abc.css"]


def test_resolve_stylesheets_extras_only(site_config: SiteConfig) -> None:
    cfg = _replace(site_config, extra_stylesheets=("/fonts.css", "/print.css"))
    assert resolve_stylesheets(cfg) == ["/fonts.css", "/print.css"]


def test_resolve_stylesheets_both_manifest_first_extras_second(
    site_config: SiteConfig, tmp_path: Path
) -> None:
    manifest_path = _write_vite_manifest(tmp_path)
    cfg = _replace(
        site_config,
        vite_manifest=manifest_path,
        extra_stylesheets=("/fonts.css",),
    )
    assert resolve_stylesheets(cfg) == ["/assets/main-abc.css", "/fonts.css"]


def test_resolve_stylesheets_neither_returns_empty_list(site_config: SiteConfig) -> None:
    assert resolve_stylesheets(site_config) == []


@pytest.mark.parametrize(
    ("with_manifest", "extras", "expected"),
    [
        (False, (), ()),
        (True, (), ("/assets/main-abc.css",)),
        (False, ("/fonts.css",), ("/fonts.css",)),
        (True, ("/fonts.css",), ("/assets/main-abc.css", "/fonts.css")),
    ],
)
def test_base_context_stylesheets_reflects_config(
    site_config: SiteConfig,
    tmp_path: Path,
    with_manifest: bool,
    extras: tuple[str, ...],
    expected: tuple[str, ...],
) -> None:
    cfg = site_config
    if with_manifest:
        cfg = _replace(cfg, vite_manifest=_write_vite_manifest(tmp_path))
    if extras:
        cfg = _replace(cfg, extra_stylesheets=extras)
    engine = build_engine(cfg, PluginRegistry())
    page_ctx = PageContext(
        config=cfg,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
        stylesheets=tuple(resolve_stylesheets(cfg)),
    )
    base = _base_context(page_ctx, canonical_path="/")
    assert "stylesheets" in base
    assert tuple(base["stylesheets"]) == expected


def test_base_context_includes_stylesheets_key(ctx: PageContext) -> None:
    base = _base_context(ctx, canonical_path="/")
    assert "stylesheets" in base


def test_manifest_read_once_per_build(
    site_config: SiteConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _write_vite_manifest(tmp_path)
    cfg = _replace(site_config, vite_manifest=manifest_path)

    import cress.vite_manifest as vm

    calls: list[Path] = []
    real_reader = vm.read_vite_css_hrefs

    def spy(mp: Path, asset_prefix: str = "/") -> list[str]:
        calls.append(mp)
        return real_reader(mp, asset_prefix=asset_prefix)

    monkeypatch.setattr(vm, "read_vite_css_hrefs", spy)

    sheets = tuple(vm.resolve_stylesheets(cfg))
    engine = build_engine(cfg, PluginRegistry())
    page_ctx = PageContext(
        config=cfg,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
        stylesheets=sheets,
    )
    posts = [(_post(f"p{i}"), "<p>body</p>") for i in range(5)]
    for post, body in posts:
        render_post_page(post, body, page_ctx)
    render_index_pages(posts, page_ctx)

    assert len(calls) == 1


# --- nav + breadcrumbs context wiring ------------------------------------


def test_base_context_includes_nav_and_static_flag(ctx: PageContext) -> None:
    base = _base_context(ctx, canonical_path="/")
    assert "nav" in base
    assert "static_pages" in base
    # Default ctx has the empty tree and blog mode.
    assert isinstance(base["nav"], NavTree)
    assert base["static_pages"] is False


def test_base_context_static_flag_reflects_config(site_config: SiteConfig) -> None:
    static_cfg = _replace(site_config, static_pages=True)
    engine = build_engine(static_cfg, PluginRegistry())
    static_ctx = PageContext(
        config=static_cfg,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
    )
    base = _base_context(static_ctx, canonical_path="/")
    assert base["static_pages"] is True


def test_post_context_includes_breadcrumbs(site_config: SiteConfig) -> None:
    static_cfg = _replace(site_config, static_pages=True)
    engine = build_engine(static_cfg, PluginRegistry())
    posts = [
        _post("position-tagging", "Position Tagging", url_path="position-tagging"),
        _post("events", "Events", url_path="position-tagging/events"),
    ]
    tree = build_nav(posts, static_cfg)
    static_ctx = PageContext(
        config=static_cfg,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
        nav=tree,
    )
    events = posts[1]
    context = _post_context(events, "<p>body</p>", static_ctx, "/position-tagging/events/")
    assert "breadcrumbs" in context
    trail = context["breadcrumbs"]
    assert [n.title for n in trail] == ["Example", "Position Tagging", "Events"]


def test_canonical_url_not_double_prefixed(tmp_path: Path) -> None:
    cfg = _config_with_prefix(tmp_path, "/blog")
    engine = build_engine(cfg, PluginRegistry())
    ctx_prefix = PageContext(
        config=cfg,
        engine=engine,
        now=datetime(2026, 4, 21, 12, 0, 0),
        cress_version="0.0.1",
    )
    post = _post("hello")
    out = render_post_page(post, "<p>body</p>", ctx_prefix)
    content = out.content
    assert isinstance(content, str)
    # canonical URL should be https://e.com/blog/hello/ — NOT .../blog/blog/hello/.
    assert 'href="https://e.com/blog/hello/"' in content
    assert "/blog/blog/" not in content
