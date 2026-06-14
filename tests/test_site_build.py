"""Integration tests for the cress orchestrator's build() pipeline."""

from pathlib import Path
from unittest import mock

import pytest

from cress import plugin
from cress.exceptions import ConfigError, DuplicateSlugError
from cress.plugins import discover_plugins
from cress.site import cress

_MIN_CONFIG = """\
vault_subfolder: "Blogs/Demo"
output_dir: "out"
site:
  title: "T"
  description: "D"
  base_url: "https://x.test"
"""

_STATIC_CONFIG = """\
vault_subfolder: "Blogs/Demo"
output_dir: "out"
static_pages: true
site:
  title: "Manual"
  description: "D"
  base_url: "https://x.test"
"""


@pytest.fixture(autouse=True)
def _reset_plugins() -> None:
    plugin._reset_all()  # type: ignore[attr-defined]


def _set_up_fixture(
    tmp_path: Path, *, extra_posts: dict[str, str] | None = None
) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    posts_dir = vault / "Blogs/Demo"
    posts_dir.mkdir(parents=True)
    (vault / "_attachments").mkdir()

    target = tmp_path / "target"
    (target / ".cress").mkdir(parents=True)
    (target / ".cress" / "config.yaml").write_text(_MIN_CONFIG, encoding="utf-8")
    (target / "out").mkdir()

    (posts_dir / "hello.md").write_text(
        "---\ntitle: Hello\nslug: hello\ndate: 2026-04-19\n---\nBody text.\n",
        encoding="utf-8",
    )
    for name, body in (extra_posts or {}).items():
        (posts_dir / name).write_text(body, encoding="utf-8")
    return vault, target


def _set_up_static_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """A static-pages vault with a nested folder hierarchy (no slug write-backs)."""
    vault = tmp_path / "vault"
    posts_dir = vault / "Blogs/Demo"
    (posts_dir / "position-tagging").mkdir(parents=True)
    (vault / "_attachments").mkdir()

    target = tmp_path / "target"
    (target / ".cress").mkdir(parents=True)
    (target / ".cress" / "config.yaml").write_text(_STATIC_CONFIG, encoding="utf-8")
    (target / "out").mkdir()

    (posts_dir / "position-tagging.md").write_text(
        "---\ntitle: Position Tagging\nslug: position-tagging\n---\nLanding.\n",
        encoding="utf-8",
    )
    (posts_dir / "position-tagging" / "events.md").write_text(
        "---\ntitle: Events\nslug: events\n---\nEvents body.\n",
        encoding="utf-8",
    )
    return vault, target


def test_build_passes_nav_tree(tmp_path: Path) -> None:
    """build() constructs the nav tree from filtered posts and threads it via PageContext."""
    import cress.site as site_mod
    from cress.nav import NavTree, breadcrumbs_for

    vault, target = _set_up_static_fixture(tmp_path)

    captured: dict[str, NavTree] = {}
    real = site_mod.render_post_page

    def spy(post, body, ctx):  # type: ignore[no-untyped-def]
        captured["nav"] = ctx.nav
        return real(post, body, ctx)

    with mock.patch.object(site_mod, "render_post_page", spy):
        cress(vault, target).build()

    nav = captured["nav"]
    # The nested folder reconstructed a tree with a merged section node.
    section = nav.by_path["position-tagging"]
    assert section.has_page is True
    assert any(c.url_path == "position-tagging/events" for c in section.children)
    # And breadcrumbs resolve for the child page.
    trail = breadcrumbs_for("position-tagging/events", nav)
    assert [n.title for n in trail] == ["Manual", "Position Tagging", "Events"]


def test_nav_tree_excludes_drafts(tmp_path: Path) -> None:
    """A draft page is absent from the sidebar tree (its published URL isn't real)."""
    import cress.site as site_mod
    from cress.nav import NavTree

    vault, target = _set_up_static_fixture(tmp_path)
    (vault / "Blogs/Demo" / "wip.md").write_text(
        "---\ntitle: Work In Progress\nslug: wip\ndraft: true\n---\nDraft body.\n",
        encoding="utf-8",
    )

    captured: dict[str, NavTree] = {}
    real = site_mod.render_post_page

    def spy(post, body, ctx):  # type: ignore[no-untyped-def]
        captured["nav"] = ctx.nav
        return real(post, body, ctx)

    with mock.patch.object(site_mod, "render_post_page", spy):
        cress(vault, target).build()

    nav = captured["nav"]
    assert "wip" not in nav.by_path
    assert all(n.url_path != "wip" for n in nav.roots)


def test_init_is_cheap(tmp_path: Path) -> None:
    vault, target = _set_up_fixture(tmp_path)
    with (
        mock.patch("cress.site.discover_plugins", wraps=discover_plugins) as disc,
        mock.patch("cress.site.build_engine") as build_eng,
    ):
        c = cress(vault, target)
    assert disc.call_count == 0
    assert build_eng.call_count == 0
    assert c.config.site.title == "T"


def test_end_to_end_build_emits_expected_outputs(tmp_path: Path) -> None:
    vault, target = _set_up_fixture(tmp_path)
    result = cress(vault, target).build()
    assert result.errors == []
    out = target / "out"
    assert (out / "hello" / "index.html").exists()
    assert (out / "index.html").exists()
    assert (out / ".cress-manifest.json").exists()


def test_duplicate_slug_raises_and_no_files_touched(tmp_path: Path) -> None:
    vault, target = _set_up_fixture(
        tmp_path,
        extra_posts={
            "a.md": "---\ntitle: Same\ndate: 2026-04-19\n---\nbody-a\n",
            "b.md": "---\ntitle: Same\ndate: 2026-04-20\n---\nbody-b\n",
        },
    )
    a_before = (vault / "Blogs/Demo" / "a.md").read_text(encoding="utf-8")
    b_before = (vault / "Blogs/Demo" / "b.md").read_text(encoding="utf-8")
    with pytest.raises(DuplicateSlugError):
        cress(vault, target).build()
    assert (vault / "Blogs/Demo" / "a.md").read_text(encoding="utf-8") == a_before
    assert (vault / "Blogs/Demo" / "b.md").read_text(encoding="utf-8") == b_before


def test_drafts_only_emits_only_drafts(tmp_path: Path) -> None:
    vault, target = _set_up_fixture(
        tmp_path,
        extra_posts={
            "secret.md": (
                "---\ntitle: Secret\nslug: secret\ndate: 2026-04-20\ndraft: true\n---\nhidden\n"
            ),
        },
    )
    result = cress(vault, target).build(drafts_only=True)
    assert result.errors == []
    out = target / "out"
    # Non-draft "hello" SHOULD NOT have a published page (it's filtered out).
    assert not (out / "hello" / "index.html").exists()
    # Draft preview directory exists.
    draft_paths = list((out / "_drafts").glob("*-secret"))
    assert draft_paths


def test_no_drafts_excludes_drafts(tmp_path: Path) -> None:
    vault, target = _set_up_fixture(
        tmp_path,
        extra_posts={
            "secret.md": ("---\ntitle: Secret\nslug: secret\ndate: 2026-04-20\ndraft: true\n---\n"),
        },
    )
    cress(vault, target).build(no_drafts=True)
    out = target / "out"
    assert (out / "hello" / "index.html").exists()
    assert not (out / "_drafts").exists()


def test_hook_lifecycle_ordering(tmp_path: Path) -> None:
    vault, target = _set_up_fixture(tmp_path)
    plugins_dir = target / ".cress" / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    (plugins_dir / "hooks.py").write_text(
        """
from cress import plugin

calls = []

@plugin.hook('before_build')
def bb(config): calls.append('before_build')

@plugin.hook('after_post')
def ap(post): calls.append(f'after_post:{post.slug}')

@plugin.hook('before_write')
def bw(outputs): calls.append(f'before_write:{len(outputs)}')

@plugin.hook('after_build')
def ab(result): calls.append('after_build')
""",
        encoding="utf-8",
    )
    cress(vault, target).build()
    # Read the recorded calls from within the loaded plugin module.
    import sys

    matching = [
        m
        for m in sys.modules.values()
        if getattr(m, "__name__", "").startswith("cress_local_plugins.")
        and m.__name__.endswith(".hooks")
    ]
    assert matching
    calls = matching[-1].calls  # type: ignore[attr-defined]
    assert calls[0] == "before_build"
    assert calls[-1] == "after_build"
    assert any(c.startswith("after_post:hello") for c in calls)
    assert any(c.startswith("before_write:") for c in calls)
    after_post_idx = next(i for i, c in enumerate(calls) if c.startswith("after_post:"))
    before_write_idx = next(i for i, c in enumerate(calls) if c.startswith("before_write"))
    assert calls.index("before_build") < after_post_idx
    assert before_write_idx < calls.index("after_build")


def test_two_builds_produce_distinct_engines(tmp_path: Path) -> None:
    vault, target = _set_up_fixture(tmp_path)
    c = cress(vault, target)
    seen: list[object] = []

    def _capture_build_engine(*args, **kwargs):  # type: ignore[no-untyped-def]
        from cress.render import build_engine as real

        result = real(*args, **kwargs)
        seen.append(result)
        return result

    with mock.patch("cress.site.build_engine", side_effect=_capture_build_engine):
        c.build()
        c.build()
    assert len(seen) == 2
    assert seen[0] is not seen[1]


def test_empty_vault_raises_config_error(tmp_path: Path) -> None:
    vault, target = _set_up_fixture(tmp_path)
    # Remove all posts
    for p in (vault / "Blogs/Demo").iterdir():
        p.unlink()
    with pytest.raises(ConfigError):
        cress(vault, target).build()


def test_hero_image_is_routed_through_attachment_pipeline(tmp_path: Path) -> None:
    """Frontmatter ``image:`` is hashed + staged as a real asset on disk.

    The default ``post.html`` doesn't render ``page.image_url``, so the proof
    of correct behaviour is the asset file written under ``assets/<slug>/``.
    """
    vault, target = _set_up_fixture(tmp_path)
    (vault / "_attachments" / "hero.png").write_bytes(b"hero-bytes")
    (vault / "Blogs/Demo" / "with-hero.md").write_text(
        "---\ntitle: With Hero\nslug: with-hero\ndate: 2026-04-19\nimage: hero.png\n---\nBody.\n",
        encoding="utf-8",
    )
    result = cress(vault, target).build()
    assert "missing_hero_image" not in [w.type for w in result.warnings]
    out = target / "out"
    hero_dir = out / "assets" / "with-hero"
    assert hero_dir.is_dir()
    hashed = list(hero_dir.glob("*-hero.png"))
    assert len(hashed) == 1
    assert hashed[0].read_bytes() == b"hero-bytes"


def test_hero_image_missing_warns_and_clears(tmp_path: Path) -> None:
    vault, target = _set_up_fixture(tmp_path)
    (vault / "Blogs/Demo" / "no-hero.md").write_text(
        "---\n"
        "title: No Hero\n"
        "slug: no-hero\n"
        "date: 2026-04-19\n"
        "image: does-not-exist.png\n"
        "---\nBody.\n",
        encoding="utf-8",
    )
    result = cress(vault, target).build()
    types = [w.type for w in result.warnings]
    assert "missing_hero_image" in types


def test_hero_image_resolved_in_taxonomy_post_cards(tmp_path: Path) -> None:
    """Tag/category pages must render post cards with the resolved hero URL.

    Regression guard: hero resolution used to run inside the per-post render
    loop *after* taxonomies had captured the unresolved ``Post``, so tag-page
    cards showed the raw frontmatter filename.
    """
    vault, target = _set_up_fixture(tmp_path)
    (vault / "_attachments" / "hero.png").write_bytes(b"hero-bytes")
    (vault / "Blogs/Demo" / "tagged.md").write_text(
        "---\n"
        "title: Tagged\n"
        "slug: tagged\n"
        "date: 2026-04-19\n"
        "image: hero.png\n"
        "tags: [product]\n"
        "---\nBody.\n",
        encoding="utf-8",
    )
    cress(vault, target).build()
    tag_html = (target / "out" / "tag" / "product" / "index.html").read_text(encoding="utf-8")
    # The raw filename must not appear as an `src` on the tag page.
    assert 'src="hero.png"' not in tag_html
    # A hashed asset URL does appear.
    assert "/assets/tagged/" in tag_html
    assert "-hero.png" in tag_html


def test_hero_image_absolute_url_passes_through(tmp_path: Path) -> None:
    """External ``https://…`` or root-absolute ``/…`` hero URLs are not touched."""
    vault, target = _set_up_fixture(tmp_path)
    (vault / "Blogs/Demo" / "ext.md").write_text(
        "---\n"
        "title: Ext\n"
        "slug: ext\n"
        "date: 2026-04-19\n"
        "image: https://cdn.example.com/hero.png\n"
        "---\nBody.\n",
        encoding="utf-8",
    )
    cress(vault, target).build()
    html = (target / "out" / "ext" / "index.html").read_text(encoding="utf-8")
    # The literal external URL survives; no hashing, no assets dir entry for it.
    assert "https://cdn.example.com/hero.png" in html
