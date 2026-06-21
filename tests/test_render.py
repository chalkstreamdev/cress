"""Tests for cress.render — markdown rendering with cress extensions."""

import base64

import pytest

from cress.render import RenderContext, render_markdown_text


@pytest.fixture
def ctx() -> RenderContext:
    return RenderContext(shortcode_names=set(), pygments_style="default")


@pytest.fixture
def ctx_with_chart() -> RenderContext:
    return RenderContext(shortcode_names={"acme-chart"}, pygments_style="default")


def test_paragraph_renders(ctx: RenderContext) -> None:
    assert "<p>Hello world.</p>" in render_markdown_text("Hello world.", ctx)


def test_unordered_list_renders(ctx: RenderContext) -> None:
    html = render_markdown_text("- one\n- two\n", ctx)
    assert "<ul>" in html and "<li>one</li>" in html


def test_emphasis_and_link(ctx: RenderContext) -> None:
    html = render_markdown_text("*em* [x](https://e.g/)", ctx)
    assert "<em>em</em>" in html
    assert '<a href="https://e.g/">x</a>' in html


def test_plain_code_block_without_language(ctx: RenderContext) -> None:
    html = render_markdown_text("```\nfoo\n```\n", ctx)
    assert "<pre>" in html and "foo" in html
    assert "highlight" not in html.lower() or 'class="codehilite"' not in html


def test_python_code_block_pygments_classes(ctx: RenderContext) -> None:
    html = render_markdown_text("```python\nprint(1)\n```\n", ctx)
    assert 'class="k"' in html or 'class="nb"' in html  # `print` → builtin


def test_heading_id_from_slugify(ctx: RenderContext) -> None:
    html = render_markdown_text("## My Heading\n", ctx)
    assert '<h2 id="my-heading">My Heading</h2>' in html


def test_heading_id_strips_inline_html(ctx: RenderContext) -> None:
    html = render_markdown_text("### My *key* point\n", ctx)
    assert '<h3 id="my-key-point">' in html
    assert "<em>key</em>" in html  # body keeps the inline HTML


def test_wikilink_bare_placeholder(ctx: RenderContext) -> None:
    html = render_markdown_text("[[Target]]", ctx)
    assert 'data-cress-wikilink="Target"' in html
    assert 'data-cress-alias=""' in html
    # Inner text is the raw target when no alias, so the page still reads sensibly.
    assert ">Target<" in html


def test_wikilink_with_alias_placeholder(ctx: RenderContext) -> None:
    html = render_markdown_text("[[Target|see here]]", ctx)
    assert 'data-cress-wikilink="Target"' in html
    assert 'data-cress-alias="see here"' in html
    assert ">see here<" in html


def test_embed_placeholder(ctx: RenderContext) -> None:
    html = render_markdown_text("![[image.png]]", ctx)
    assert 'data-cress-embed="image.png"' in html
    assert "data-cress-embed-alias" not in html


def test_embed_with_alias_placeholder(ctx: RenderContext) -> None:
    html = render_markdown_text("![[image.png|Board after the blitz]]", ctx)
    assert 'data-cress-embed="image.png"' in html
    assert 'data-cress-embed-alias="Board after the blitz"' in html


def test_shortcode_fenced_block(ctx_with_chart: RenderContext) -> None:
    body = "id: x\nseries: y\n"
    html = render_markdown_text(f"```acme-chart\n{body}```\n", ctx_with_chart)
    assert 'data-cress-shortcode="acme-chart"' in html
    encoded = base64.b64encode(body.encode("utf-8")).decode("ascii")
    assert f'data-cress-body="{encoded}"' in html


def test_unregistered_fenced_info_not_treated_as_shortcode(
    ctx: RenderContext,
) -> None:
    html = render_markdown_text("```mystery\nid: x\n```\n", ctx)
    assert "data-cress-shortcode" not in html


def test_hashtag_inside_code_block_not_converted_to_wikilink(ctx: RenderContext) -> None:
    html = render_markdown_text("```\n#tag here\n```\n", ctx)
    assert "data-cress-wikilink" not in html
    assert "data-cress-embed" not in html


def test_callout_renders_with_type_and_title(ctx: RenderContext) -> None:
    html = render_markdown_text("> [!warning] Heads up\n> Be **careful** here.\n", ctx)
    assert 'class="callout callout-warning"' in html
    assert "Heads up" in html
    assert "callout-icon" in html
    # body is parsed as markdown
    assert "<strong>careful</strong>" in html


def test_callout_type_aliases_map_to_canonical(ctx: RenderContext) -> None:
    assert "callout callout-success" in render_markdown_text("> [!tip] x\n> y\n", ctx)
    assert "callout callout-error" in render_markdown_text("> [!danger] x\n> y\n", ctx)
    assert "callout callout-info" in render_markdown_text("> [!note] x\n> y\n", ctx)


def test_callout_without_title_uses_type_label(ctx: RenderContext) -> None:
    html = render_markdown_text("> [!success]\n> done\n", ctx)
    assert "<span>Success</span>" in html


def test_unknown_callout_type_falls_back_to_info(ctx: RenderContext) -> None:
    html = render_markdown_text("> [!mystery] x\n> y\n", ctx)
    assert "callout callout-info" in html


def test_plain_blockquote_is_not_a_callout(ctx: RenderContext) -> None:
    html = render_markdown_text("> just a normal quote\n", ctx)
    assert "callout" not in html
    assert "<blockquote>" in html


def test_callout_fold_marker_is_ignored(ctx: RenderContext) -> None:
    html = render_markdown_text("> [!info]+ Foldable\n> body\n", ctx)
    assert 'class="callout callout-info"' in html
    assert "Foldable" in html
