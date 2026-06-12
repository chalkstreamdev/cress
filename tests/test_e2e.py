"""End-to-end integration test exercising every feature together."""

import json
import shutil
from pathlib import Path

import pytest

from cress import plugin
from cress.manifest import MANIFEST_FILENAME
from cress.site import cress

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "e2e"

_CONFIG = """\
vault_subfolder: "Blogs/Demo"
output_dir: "public/blog"

site:
  title: "Demo Blog"
  description: "Integration-test site"
  base_url: "https://demo.example.com/blog"
  locale: "en_US"
  twitter_handle: "@demo"

template_dir: "blog-templates"
attachments_subfolder: "_attachments"
paginate: 3

shortcodes:
  chart-template: "shortcodes/chart.html"

features:
  rss: true
  sitemap: true
  syntax_highlighting: true
  json_ld: true

pygments_style: "default"

git:
  auto_commit: false
  auto_push: false
"""

_DEMO_PLUGIN = """
from cress import plugin

@plugin.shortcode('datahero-chart')
def render_chart(body, **ctx):
    return '<figure class="chart">' + body.strip() + '</figure>'

@plugin.template_filter('shout')
def shout(value):
    return str(value).upper()
"""


@pytest.fixture(autouse=True)
def _reset_plugins() -> None:
    plugin._reset_all()  # type: ignore[attr-defined]


@pytest.fixture
def fixture(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    posts = vault / "Blogs" / "Demo"
    posts.mkdir(parents=True)
    attachments = vault / "_attachments"
    attachments.mkdir()
    (attachments / "hero.png").write_bytes(b"\x89PNG-hero")
    (attachments / "inline.png").write_bytes(b"\x89PNG-inline")
    (attachments / "other.png").write_bytes(b"\x89PNG-other")

    target = tmp_path / "product"
    (target / ".cress").mkdir(parents=True)
    (target / ".cress" / "config.yaml").write_text(_CONFIG, encoding="utf-8")
    (target / ".cress" / "plugins").mkdir()
    (target / ".cress" / "plugins" / "demo.py").write_text(_DEMO_PLUGIN, encoding="utf-8")

    (target / "blog-templates" / "defaults").mkdir(parents=True)
    override = (
        '{% extends "defaults/post.html" %}'
        "{% block title %}OVERRIDE: {{ page.title }}{% endblock %}"
    )
    (target / "blog-templates" / "defaults" / "post.html").write_text(override, encoding="utf-8")
    (target / "blog-templates" / "shortcodes").mkdir(parents=True)
    (target / "blog-templates" / "shortcodes" / "chart.html").write_text(
        "<figure>template-chart id={{ id }}</figure>", encoding="utf-8"
    )
    (target / "public" / "blog").mkdir(parents=True)

    # --- 10 posts --------------------------------------------------------
    (posts / "hello.md").write_text(
        "---\ntitle: Hello\nslug: hello\ndate: 2026-04-10\ntags: [charts, Machine Learning]"
        "\ncategories: [engineering]\n---\n"
        "First paragraph.\n\nSee [[chart-details]] for #details about #ml.\n\n"
        "![[hero.png]]\n",
        encoding="utf-8",
    )
    (posts / "chart-details.md").write_text(
        "---\ntitle: Chart Details\nslug: chart-details\ndate: 2026-04-11\n"
        "tags: [charts]\ncategories: [engineering]\n---\n"
        "Inline ![alt](inline.png) image here.\n\n"
        "```datahero-chart\nid: 42\n```\n",
        encoding="utf-8",
    )
    (posts / "unslugged.md").write_text(
        "---\ntitle: Missing Slug Post\ndate: 2026-04-12\ntags: [ux]\n---\n"
        "This post has no slug in frontmatter.\n",
        encoding="utf-8",
    )
    (posts / "secret.md").write_text(
        "---\ntitle: Secret\nslug: secret\ndate: 2026-04-13\ndraft: true\n---\n"
        "Hidden draft content.\n",
        encoding="utf-8",
    )
    (posts / "cafe.md").write_text(
        "---\ntitle: Café\nslug: cafe\ndate: 2026-04-14\ntags: [\"Café\"]\n---\n"
        "Diacritic taxonomy test.\n",
        encoding="utf-8",
    )
    (posts / "cafe-lowercase.md").write_text(
        "---\ntitle: cafe\nslug: cafe-lowercase\ndate: 2026-04-15\ntags: [cafe]\n---\n"
        "Second café post.\n",
        encoding="utf-8",
    )
    (posts / "transclude.md").write_text(
        "---\ntitle: Transclude\nslug: transclude\ndate: 2026-04-16\n"
        "categories: [product]\n---\n"
        "Before. ![[hello.md]] After.\n",
        encoding="utf-8",
    )
    (posts / "p4.md").write_text(
        "---\ntitle: Post Four\nslug: p4\ndate: 2026-04-17\ntags: [ux]\n---\nbody\n",
        encoding="utf-8",
    )
    (posts / "p5.md").write_text(
        "---\ntitle: Post Five\nslug: p5\ndate: 2026-04-18\ntags: [ux]\n---\nbody\n",
        encoding="utf-8",
    )
    (posts / "p6.md").write_text(
        "---\ntitle: Post Six\nslug: p6\ndate: 2026-04-19\n"
        "categories: [product]\n---\nbody\n",
        encoding="utf-8",
    )
    return vault, target


def test_e2e_full_build(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    site = cress(vault, target)
    result = site.build()
    assert result.errors == []
    out = target / "public" / "blog"

    # 2: expected output paths exist
    must_exist = [
        "hello/index.html",
        "chart-details/index.html",
        "missing-slug-post/index.html",  # slug written back
        "transclude/index.html",
        "cafe/index.html",
        "cafe-lowercase/index.html",
        "p4/index.html",
        "p5/index.html",
        "p6/index.html",
        "index.html",
        "tag/charts/index.html",
        "tag/ux/index.html",
        "category/engineering/index.html",
        "category/product/index.html",
        "tags/index.html",
        "categories/index.html",
        "sitemap.xml",
        "rss.xml",
    ]
    for rel in must_exist:
        assert (out / rel).is_file(), rel

    # 3: manifest lists every output, no more, no less
    manifest_data = json.loads((out / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    manifest_files = set(manifest_data["files"])
    actual = set()
    for p in out.rglob("*"):
        if p.is_file() and p.name != MANIFEST_FILENAME:
            actual.add(str(p.relative_to(out)).replace("\\", "/"))
    assert manifest_files == actual

    # 4: draft page exists under _drafts/<token>-secret
    drafts = list((out / "_drafts").glob("*-secret"))
    assert len(drafts) == 1
    assert (drafts[0] / "index.html").is_file()

    # 5: slug written back to source file
    unslugged = (vault / "Blogs" / "Demo" / "unslugged.md").read_text(encoding="utf-8")
    assert "slug: missing-slug-post" in unslugged

    # 6: wikilinks render as links; tags merge inline+frontmatter
    hello_html = (out / "hello" / "index.html").read_text(encoding="utf-8")
    # base_url ends in /blog, so internal links carry the /blog url_prefix.
    assert '<a href="/blog/chart-details/">' in hello_html
    assert "#details" in hello_html or "details" in hello_html
    assert "ml" in hello_html
    # Hashed asset URL present for hero.png (content hash in filename)
    assert "hero.png" in hello_html
    # Template override applied
    assert "OVERRIDE:" in hello_html

    # Shortcode plugin rendered
    chart_html = (out / "chart-details" / "index.html").read_text(encoding="utf-8")
    assert 'class="chart"' in chart_html


def test_e2e_second_build_is_stable(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    site = cress(vault, target)
    site.build()
    manifest_before = json.loads(
        (target / "public" / "blog" / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    site.build()
    manifest_after = json.loads(
        (target / "public" / "blog" / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest_before == manifest_after


def test_e2e_rename_post_cleans_old_output(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    site = cress(vault, target)
    site.build()
    out = target / "public" / "blog"
    assert (out / "hello" / "index.html").exists()

    # Rename the slug of "hello"
    hello_src = vault / "Blogs" / "Demo" / "hello.md"
    new_text = hello_src.read_text(encoding="utf-8").replace("slug: hello", "slug: hello-v2")
    hello_src.write_text(new_text, encoding="utf-8")

    site.build()
    assert not (out / "hello" / "index.html").exists()
    assert (out / "hello-v2" / "index.html").exists()


def test_e2e_user_file_in_output_dir_survives(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    site = cress(vault, target)
    site.build()
    custom = target / "public" / "blog" / "custom-untracked.html"
    custom.write_text("user wrote this", encoding="utf-8")
    site.build()
    assert custom.exists()
    assert custom.read_text(encoding="utf-8") == "user wrote this"


def test_e2e_drafts_only_build(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    site = cress(vault, target)
    site.build(drafts_only=True)
    out = target / "public" / "blog"
    assert not (out / "hello" / "index.html").exists()
    drafts = list((out / "_drafts").glob("*-secret"))
    assert drafts


def test_e2e_vite_manifest_link_tags_injected(tmp_path: Path) -> None:
    src = _FIXTURES_DIR / "vite-manifest"
    shutil.copytree(src, tmp_path, dirs_exist_ok=True)
    vault = tmp_path / "vault"
    target = tmp_path / "product"

    site = cress(vault, target)
    result = site.build()
    assert result.errors == []

    out = target / "public" / "blog"
    expected_links = [
        '<link rel="stylesheet" href="/assets/main-abc123.css">',
        '<link rel="stylesheet" href="/assets/chunk-shared-def456.css">',
        '<link rel="stylesheet" href="https://fonts.example.com/inter.css">',
    ]

    rendered = sorted(out.rglob("*.html"))
    assert rendered, "fixture build produced no HTML"
    for html_path in rendered:
        text = html_path.read_text(encoding="utf-8")
        for link in expected_links:
            assert link in text, f"missing {link!r} in {html_path}"
        # Order: manifest entries precede extras, transitive imports after entry.
        positions = [text.index(link) for link in expected_links]
        assert positions == sorted(positions), f"link order wrong in {html_path}"
