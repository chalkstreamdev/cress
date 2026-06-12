"""Tests for cress.attachments — resolution, planning, embed substitution."""

import hashlib
from datetime import date
from pathlib import Path

import pytest

from cress.attachments import (
    plan_attachment,
    reset_attachment_cache,
    resolve_attachment,
    substitute_embeds,
    substitute_standard_images,
)
from cress.config import SiteConfig, SiteMetaConfig
from cress.manifest import OutputFile
from cress.post import Post
from cress.render import RenderContext
from cress.reports import BuildWarning
from cress.wikilinks import SlugMap, build_slug_map


@pytest.fixture(autouse=True)
def _clean_attachment_cache() -> None:
    reset_attachment_cache()


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "Blogs/Demo").mkdir(parents=True)
    (vault / "_attachments").mkdir()
    return vault


@pytest.fixture
def site_config(tmp_path: Path) -> SiteConfig:
    target = tmp_path / "target"
    output_dir = target / "public" / "blog"
    output_dir.mkdir(parents=True)
    return SiteConfig(
        target=target,
        vault_subfolder="Blogs/Demo",
        output_dir=output_dir,
        site=SiteMetaConfig(title="T", description="D", base_url="https://x.test"),
        assets_dir=output_dir / "assets",
        attachments_subfolder="_attachments",
    )


@pytest.fixture
def render_ctx() -> RenderContext:
    return RenderContext(shortcode_names=set(), pygments_style="default")


def _make_post(vault: Path, slug: str, title: str = "T", body: str = "") -> Post:
    path = vault / "Blogs" / "Demo" / f"{slug}.md"
    path.write_text(f"---\ntitle: {title}\ndate: 2026-04-19\n---\n{body}", encoding="utf-8")
    return Post(
        source_path=path,
        title=title,
        date=date(2026, 4, 19),
        body_md=body,
        frontmatter_raw={},
        slug=slug,
    )


def test_resolve_attachment_from_vault_attachments_subfolder(
    vault: Path, site_config: SiteConfig
) -> None:
    img = vault / "_attachments" / "hero.png"
    img.write_bytes(b"\x89PNG")
    post = _make_post(vault, "example")
    assert resolve_attachment("hero.png", post, site_config, vault) == img


def test_resolve_attachment_from_post_local_dir(vault: Path, site_config: SiteConfig) -> None:
    local = vault / "Blogs" / "Demo" / "images"
    local.mkdir()
    img = local / "inline.png"
    img.write_bytes(b"inline bytes")
    post = _make_post(vault, "example")
    assert resolve_attachment("images/inline.png", post, site_config, vault) == img


def test_resolve_attachment_not_found(vault: Path, site_config: SiteConfig) -> None:
    post = _make_post(vault, "example")
    assert resolve_attachment("ghost.png", post, site_config, vault) is None


def test_plan_attachment_produces_hashed_output_file(vault: Path, site_config: SiteConfig) -> None:
    src = vault / "_attachments" / "hero.png"
    src.write_bytes(b"hello")
    plan = plan_attachment(src, "post-slug", site_config)
    expected_hash = hashlib.sha256(b"hello").hexdigest()[:8]
    assert plan.public_url == f"/assets/post-slug/{expected_hash}-hero.png"
    assert plan.output_file.relative_path == f"assets/post-slug/{expected_hash}-hero.png"
    assert plan.output_file.content == b"hello"


def test_plan_attachment_is_memoised(vault: Path, site_config: SiteConfig) -> None:
    src = vault / "_attachments" / "hero.png"
    src.write_bytes(b"same")
    p1 = plan_attachment(src, "post-slug", site_config)
    p2 = plan_attachment(src, "post-slug", site_config)
    assert p1 is p2


def test_plan_attachment_public_url_includes_url_prefix(
    vault: Path, site_config: SiteConfig
) -> None:
    """Attachment URLs must carry the site's ``url_prefix`` so ``cress serve`` and
    production both resolve them under the blog path (e.g. ``/blog/assets/...``)."""
    from dataclasses import replace

    prefixed = replace(site_config, url_prefix="/blog")
    src = vault / "_attachments" / "hero.png"
    src.write_bytes(b"bytes")
    plan = plan_attachment(src, "post-slug", prefixed)
    assert plan.public_url.startswith("/blog/assets/post-slug/")
    # On-disk path is unchanged — only the URL gets the prefix.
    assert plan.output_file.relative_path.startswith("assets/post-slug/")


def test_substitute_embeds_image_resolves_and_collects_output(
    vault: Path, site_config: SiteConfig, render_ctx: RenderContext
) -> None:
    src = vault / "_attachments" / "hero.png"
    src.write_bytes(b"png-bytes")
    post = _make_post(vault, "hello")
    html = '<p><span data-cress-embed="hero.png"></span></p>'
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    result = substitute_embeds(
        html,
        post,
        site_config,
        warnings,
        out,
        vault=vault,
        slug_map=build_slug_map([post]),
        render_ctx=render_ctx,
    )
    assert "<img" in result and "hero.png" in result
    assert len(out) == 1
    assert warnings == []


def test_substitute_embeds_image_alias_becomes_alt(
    vault: Path, site_config: SiteConfig, render_ctx: RenderContext
) -> None:
    src = vault / "_attachments" / "hero.png"
    src.write_bytes(b"png-bytes")
    post = _make_post(vault, "hello")
    html = (
        '<span data-cress-embed="hero.png" data-cress-embed-alias="Board after the blitz"></span>'
    )
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    result = substitute_embeds(
        html,
        post,
        site_config,
        warnings,
        out,
        vault=vault,
        slug_map=build_slug_map([post]),
        render_ctx=render_ctx,
    )
    assert 'alt="Board after the blitz"' in result
    assert warnings == []


@pytest.mark.parametrize(
    ("alias", "expected_attrs"),
    [
        ("300", 'alt="hero" width="300"'),
        ("300x200", 'alt="hero" width="300" height="200"'),
        ("Board view|300", 'alt="Board view" width="300"'),
        ("right", 'alt="hero" class="embed-right"'),
        ("left", 'alt="hero" class="embed-left"'),
        ("Board view|right|300", 'alt="Board view" width="300" class="embed-right"'),
    ],
)
def test_substitute_embeds_image_alias_size_directives(
    vault: Path,
    site_config: SiteConfig,
    render_ctx: RenderContext,
    alias: str,
    expected_attrs: str,
) -> None:
    # Obsidian uses the pipe segment for resizing (``|300``, ``|300x200``) and
    # supports ``|alt|300`` combined; a bare size keeps the filename-stem alt.
    src = vault / "_attachments" / "hero.png"
    src.write_bytes(b"png-bytes")
    post = _make_post(vault, "hello")
    html = f'<span data-cress-embed="hero.png" data-cress-embed-alias="{alias}"></span>'
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    result = substitute_embeds(
        html,
        post,
        site_config,
        warnings,
        out,
        vault=vault,
        slug_map=build_slug_map([post]),
        render_ctx=render_ctx,
    )
    assert expected_attrs in result


def test_substitute_embeds_unknown_extension_link_uses_alias_text(
    vault: Path, site_config: SiteConfig, render_ctx: RenderContext
) -> None:
    src = vault / "_attachments" / "blob.xyz"
    src.write_bytes(b"stuff")
    post = _make_post(vault, "hello")
    html = '<span data-cress-embed="blob.xyz" data-cress-embed-alias="the data file"></span>'
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    result = substitute_embeds(
        html,
        post,
        site_config,
        warnings,
        out,
        vault=vault,
        slug_map=build_slug_map([post]),
        render_ctx=render_ctx,
    )
    assert ">the data file</a>" in result


def test_substitute_embeds_missing_attachment_warns_and_replaces_span(
    vault: Path, site_config: SiteConfig, render_ctx: RenderContext
) -> None:
    post = _make_post(vault, "hello")
    html = '<span data-cress-embed="ghost.png"></span>'
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    result = substitute_embeds(
        html,
        post,
        site_config,
        warnings,
        out,
        vault=vault,
        slug_map=build_slug_map([post]),
        render_ctx=render_ctx,
    )
    assert '<span class="broken-embed">' in result
    assert len(warnings) == 1
    assert warnings[0].type == "missing_embed"


def test_substitute_embeds_unknown_extension_renders_link(
    vault: Path, site_config: SiteConfig, render_ctx: RenderContext
) -> None:
    src = vault / "_attachments" / "blob.xyz"
    src.write_bytes(b"stuff")
    post = _make_post(vault, "hello")
    html = '<span data-cress-embed="blob.xyz"></span>'
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    result = substitute_embeds(
        html,
        post,
        site_config,
        warnings,
        out,
        vault=vault,
        slug_map=build_slug_map([post]),
        render_ctx=render_ctx,
    )
    assert "<a href=" in result
    assert "blob.xyz" in result


def test_same_attachment_twice_single_copy(
    vault: Path, site_config: SiteConfig, render_ctx: RenderContext
) -> None:
    src = vault / "_attachments" / "hero.png"
    src.write_bytes(b"once")
    post = _make_post(vault, "hello")
    html = '<span data-cress-embed="hero.png"></span><span data-cress-embed="hero.png"></span>'
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    substitute_embeds(
        html,
        post,
        site_config,
        warnings,
        out,
        vault=vault,
        slug_map=build_slug_map([post]),
        render_ctx=render_ctx,
    )
    assert len(out) == 1


def test_markdown_transclusion_renders_target_body(
    vault: Path, site_config: SiteConfig, render_ctx: RenderContext
) -> None:
    other_path = vault / "Blogs" / "Demo" / "other.md"
    other_body = "Transcluded **body** text."
    other = Post(
        source_path=other_path,
        title="Other",
        date=date(2026, 4, 20),
        body_md=other_body,
        frontmatter_raw={},
        slug="other",
    )
    other_path.write_text(
        f"---\ntitle: Other\ndate: 2026-04-20\n---\n{other_body}", encoding="utf-8"
    )
    post = _make_post(vault, "hello")

    html = '<span data-cress-embed="other.md"></span>'
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    result = substitute_embeds(
        html,
        post,
        site_config,
        warnings,
        out,
        vault=vault,
        slug_map=build_slug_map([post, other]),
        render_ctx=render_ctx,
    )
    assert '<blockquote class="transclusion">' in result
    assert "<strong>body</strong>" in result


def test_markdown_transclusion_depth_1_refuses_further_nesting(
    vault: Path, site_config: SiteConfig, render_ctx: RenderContext
) -> None:
    inner_path = vault / "Blogs" / "Demo" / "inner.md"
    inner_body = "Deep ![[even-deeper.md]] here."
    inner = Post(
        source_path=inner_path,
        title="Inner",
        date=date(2026, 4, 20),
        body_md=inner_body,
        frontmatter_raw={},
        slug="inner",
    )
    inner_path.write_text(
        f"---\ntitle: Inner\ndate: 2026-04-20\n---\n{inner_body}", encoding="utf-8"
    )

    deeper_path = vault / "Blogs" / "Demo" / "even-deeper.md"
    deeper = Post(
        source_path=deeper_path,
        title="Deeper",
        date=date(2026, 4, 21),
        body_md="deepest",
        frontmatter_raw={},
        slug="even-deeper",
    )
    deeper_path.write_text("---\ntitle: Deeper\ndate: 2026-04-21\n---\ndeepest", encoding="utf-8")

    post = _make_post(vault, "hello")
    html = '<span data-cress-embed="inner.md"></span>'
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    result = substitute_embeds(
        html,
        post,
        site_config,
        warnings,
        out,
        vault=vault,
        slug_map=build_slug_map([post, inner, deeper]),
        render_ctx=render_ctx,
    )
    assert '<blockquote class="transclusion">' in result
    assert '<span class="broken-embed">' in result
    # The second-level transclusion was refused
    assert any(w.type == "missing_embed" for w in warnings)


def test_substitute_embeds_wikilink_inside_transclusion_resolved(
    vault: Path, site_config: SiteConfig, render_ctx: RenderContext
) -> None:
    # Transclusion target contains a wikilink — must be resolved, not left as a placeholder.
    other_path = vault / "Blogs" / "Demo" / "other.md"
    other_body = "See [[hello]] for more."
    other = Post(
        source_path=other_path,
        title="Other",
        date=date(2026, 4, 20),
        body_md=other_body,
        frontmatter_raw={},
        slug="other",
    )
    other_path.write_text(
        f"---\ntitle: Other\ndate: 2026-04-20\n---\n{other_body}", encoding="utf-8"
    )
    post = _make_post(vault, "hello")
    html = '<span data-cress-embed="other.md"></span>'
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    slug_map: SlugMap = build_slug_map([post, other])
    result = substitute_embeds(
        html,
        post,
        site_config,
        warnings,
        out,
        vault=vault,
        slug_map=slug_map,
        render_ctx=render_ctx,
    )
    # Resolved <a> appears inside the transclusion; no wikilink placeholders survive.
    assert '<a href="/hello/">' in result
    assert "data-cress-wikilink" not in result


def test_substitute_standard_images_rewrites_and_hashes(
    vault: Path, site_config: SiteConfig
) -> None:
    src = vault / "_attachments" / "inline.png"
    src.write_bytes(b"pic")
    post = _make_post(vault, "hello")
    html = '<p><img src="inline.png" alt="pic"></p>'
    warnings: list[BuildWarning] = []
    out: list[OutputFile] = []
    result = substitute_standard_images(html, post, site_config, warnings, out, vault=vault)
    expected_hash = hashlib.sha256(b"pic").hexdigest()[:8]
    assert f'src="/assets/hello/{expected_hash}-inline.png"' in result
    assert len(out) == 1
