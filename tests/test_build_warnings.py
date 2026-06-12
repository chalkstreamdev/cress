"""Tests for Task 17 — every error path categorised + asserted."""

from pathlib import Path

import pytest

from cress import plugin
from cress.exceptions import ConfigError, DuplicateSlugError
from cress.site import cress

_CONFIG = """\
vault_subfolder: "Blogs/Demo"
output_dir: "out"
site:
  title: "T"
  description: "D"
  base_url: "https://x.test"
"""


@pytest.fixture(autouse=True)
def _reset_plugins() -> None:
    plugin._reset_all()  # type: ignore[attr-defined]


def _base(tmp_path: Path, posts: dict[str, str]) -> tuple[Path, Path]:
    vault = tmp_path / "v"
    posts_dir = vault / "Blogs/Demo"
    posts_dir.mkdir(parents=True)
    (vault / "_attachments").mkdir()
    target = tmp_path / "t"
    (target / ".cress").mkdir(parents=True)
    (target / ".cress/config.yaml").write_text(_CONFIG, encoding="utf-8")
    (target / "out").mkdir()
    for name, body in posts.items():
        (posts_dir / name).write_text(body, encoding="utf-8")
    return vault, target


# ---- soft errors (build continues) ------------------------------------------


def test_unresolvable_wikilink_warning(tmp_path: Path) -> None:
    vault, target = _base(
        tmp_path,
        {
            "a.md": (
                "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\n"
                "Here [[nonexistent]] goes.\n"
            )
        },
    )
    result = cress(vault, target).build()
    assert any(w.type == "broken_wikilink" for w in result.warnings)
    assert (target / "out" / "a" / "index.html").exists()


def test_missing_attachment_warning(tmp_path: Path) -> None:
    vault, target = _base(
        tmp_path,
        {"a.md": "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\n![[ghost.png]]\n"},
    )
    result = cress(vault, target).build()
    assert any(w.type == "missing_embed" for w in result.warnings)
    assert (target / "out" / "a" / "index.html").exists()


def test_transclusion_target_missing_warning(tmp_path: Path) -> None:
    vault, target = _base(
        tmp_path,
        {"a.md": "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\n![[ghost.md]]\n"},
    )
    result = cress(vault, target).build()
    assert any(w.type == "missing_embed" for w in result.warnings)


def test_shortcode_error_warning_on_unknown_name(tmp_path: Path) -> None:
    vault, target = _base(
        tmp_path,
        {
            "a.md": (
                "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\n"
                "```unknown-shortcode-name\nid: 1\n```\n"
            )
        },
    )
    # The renderer only emits shortcode placeholders for NAMES in ctx.shortcode_names,
    # so an unregistered name falls through to pygments/plain code — no warning expected.
    # Use a registered name via config templates to force dispatch through the registry.
    (target / "bad-template.html").write_text("{% load %}{{ broken }}", encoding="utf-8")
    config_yaml = target / ".cress/config.yaml"
    config_yaml.write_text(
        _CONFIG + 'shortcodes:\n  demo: "shortcodes/does-not-exist.html"\n',
        encoding="utf-8",
    )
    a = vault / "Blogs/Demo/a.md"
    a.write_text(
        "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\n```demo\nid: 1\n```\n",
        encoding="utf-8",
    )
    result = cress(vault, target).build()
    assert any(w.type == "shortcode_error" for w in result.warnings)


def test_frontmatter_type_error_single_post_soft(tmp_path: Path) -> None:
    vault, target = _base(
        tmp_path,
        {
            "good.md": "---\ntitle: G\nslug: good\ndate: 2026-04-19\n---\nok\n",
            "bad.md": '---\ntitle: B\nslug: bad\ndate: 2026-04-19\ntags: "not-a-list"\n---\n',
        },
    )
    result = cress(vault, target).build()
    assert any(w.type == "post_parse_error" for w in result.warnings)
    assert (target / "out" / "good" / "index.html").exists()
    assert not (target / "out" / "bad" / "index.html").exists()


def test_plugin_module_import_failure_soft(tmp_path: Path) -> None:
    vault, target = _base(
        tmp_path,
        {"a.md": "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\nbody\n"},
    )
    plugins_dir = target / ".cress" / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "broken.py").write_text("this is not valid python (((", encoding="utf-8")
    result = cress(vault, target).build()
    assert any(w.type == "plugin_load_failed" for w in result.warnings)
    assert (target / "out" / "a" / "index.html").exists()


def test_taxonomy_display_mismatch_warning(tmp_path: Path) -> None:
    vault, target = _base(
        tmp_path,
        {
            "a.md": "---\ntitle: A\nslug: a\ndate: 2026-04-19\ntags: [Machine Learning]\n---\n",
            "b.md": "---\ntitle: B\nslug: b\ndate: 2026-04-20\ntags: [machine-learning]\n---\n",
        },
    )
    result = cress(vault, target).build()
    assert any(w.type == "display_mismatch" for w in result.warnings)


# ---- hard errors (build aborts) ---------------------------------------------


def test_missing_config_raises(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    (vault / "Blogs/Demo").mkdir(parents=True)
    (vault / "_attachments").mkdir()
    target = tmp_path / "t"
    target.mkdir()
    with pytest.raises(ConfigError):
        cress(vault, target)


def test_vault_path_does_not_exist(tmp_path: Path) -> None:
    target = tmp_path / "t"
    (target / ".cress").mkdir(parents=True)
    (target / ".cress/config.yaml").write_text(_CONFIG, encoding="utf-8")
    with pytest.raises(ConfigError):
        cress(tmp_path / "nope", target)


def test_target_path_does_not_exist(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    (vault / "Blogs/Demo").mkdir(parents=True)
    with pytest.raises(ConfigError):
        cress(vault, tmp_path / "nope")


def test_empty_vault_subfolder_hard_error(tmp_path: Path) -> None:
    vault, target = _base(tmp_path, posts={})
    with pytest.raises(ConfigError):
        cress(vault, target).build()


def test_duplicate_slug_hard_error(tmp_path: Path) -> None:
    vault, target = _base(
        tmp_path,
        {
            "a.md": "---\ntitle: T\nslug: dup\ndate: 2026-04-19\n---\n",
            "b.md": "---\ntitle: T2\nslug: dup\ndate: 2026-04-20\n---\n",
        },
    )
    with pytest.raises(DuplicateSlugError):
        cress(vault, target).build()


# ---- filter-aware zero-page outcomes (exit 0 + warning) ---------------------


def test_drafts_only_with_no_drafts_is_soft(tmp_path: Path) -> None:
    vault, target = _base(
        tmp_path,
        {"a.md": "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\nbody\n"},
    )
    result = cress(vault, target).build(drafts_only=True)
    assert result.errors == []
    assert any(w.type == "empty_filtered_build" for w in result.warnings)


def test_no_drafts_when_only_drafts_is_soft(tmp_path: Path) -> None:
    vault, target = _base(
        tmp_path,
        {
            "a.md": (
                "---\ntitle: A\nslug: a\ndate: 2026-04-19\ndraft: true\n---\nbody\n"
            )
        },
    )
    result = cress(vault, target).build(no_drafts=True)
    assert result.errors == []
    assert any(w.type == "empty_filtered_build" for w in result.warnings)
