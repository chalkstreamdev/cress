"""Tests for slug auto-write-back (post.plan_slug_writebacks + apply_slug_writebacks)."""

from datetime import date
from pathlib import Path

import pytest

from cress.config import SiteConfig, SiteMetaConfig
from cress.exceptions import PostParseError
from cress.post import (
    Post,
    apply_slug_writebacks,
    generate_slug_for,
    parse_post,
    plan_slug_writebacks,
)


@pytest.fixture
def site_config(tmp_path: Path) -> SiteConfig:
    return SiteConfig(
        target=tmp_path,
        vault_subfolder="Blogs",
        output_dir=tmp_path / "output",
        site=SiteMetaConfig(title="T", description="D", base_url="https://x.test"),
        assets_dir=tmp_path / "output" / "assets",
    )


def _post_with(path: Path, *, slug: str | None, title: str) -> Post:
    return Post(
        source_path=path,
        title=title,
        date=date(2026, 4, 19),
        body_md="",
        frontmatter_raw={},
        slug=slug,
    )


def test_generate_slug_for_uses_slugify() -> None:
    assert generate_slug_for(Path("x.md"), "My Shiny Post!") == "my-shiny-post"


def test_plan_writeback_for_post_missing_slug(tmp_path: Path) -> None:
    p = tmp_path / "a.md"
    post = _post_with(p, slug=None, title="Hello World")
    plan = plan_slug_writebacks([post])
    assert plan.duplicates == []
    assert plan.writebacks == [(p, "hello-world")]


def test_plan_no_op_when_slug_present(tmp_path: Path) -> None:
    p = tmp_path / "a.md"
    post = _post_with(p, slug="existing", title="Hello World")
    plan = plan_slug_writebacks([post])
    assert plan.writebacks == []
    assert plan.duplicates == []


def test_plan_detects_collision_between_two_missing_slugs(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    plan = plan_slug_writebacks(
        [_post_with(a, slug=None, title="Same Title"), _post_with(b, slug=None, title="Same Title")]
    )
    assert plan.writebacks == []
    assert len(plan.duplicates) == 1
    assert plan.duplicates[0].slug == "same-title"
    assert set(plan.duplicates[0].paths) == {a, b}


def test_plan_detects_collision_with_existing_slug(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    plan = plan_slug_writebacks(
        [
            _post_with(a, slug="same-title", title="Original"),
            _post_with(b, slug=None, title="Same Title"),
        ]
    )
    assert plan.writebacks == []
    assert len(plan.duplicates) == 1
    assert plan.duplicates[0].slug == "same-title"


def test_apply_writeback_preserves_body_bytes(tmp_path: Path, site_config: SiteConfig) -> None:
    path = tmp_path / "post.md"
    original = (
        "---\n"
        'title: "Hello World"\n'
        "date: 2026-04-19\n"
        "tags: [a, b]\n"
        "---\n"
        "# Heading\n"
        "\n"
        "Some body **text** here.\n"
    )
    path.write_text(original, encoding="utf-8")
    plan = plan_slug_writebacks([parse_post(path, site_config)])
    apply_slug_writebacks(plan)

    after = path.read_text(encoding="utf-8")
    body_index_before = original.index("# Heading")
    body_index_after = after.index("# Heading")
    assert after[body_index_after:] == original[body_index_before:]
    reparsed = parse_post(path, site_config)
    assert reparsed.slug == "hello-world"


def test_apply_writeback_preserves_crlf(tmp_path: Path, site_config: SiteConfig) -> None:
    path = tmp_path / "crlf.md"
    original = (
        "---\r\n"
        'title: "Hello World"\r\n'
        "date: 2026-04-19\r\n"
        "---\r\n"
        "body line one\r\n"
        "body line two\r\n"
    )
    path.write_bytes(original.encode("utf-8"))
    plan = plan_slug_writebacks([parse_post(path, site_config)])
    apply_slug_writebacks(plan)
    after = path.read_bytes()
    assert b"\r\nslug: hello-world\r\n" in after
    assert after.endswith(b"body line one\r\nbody line two\r\n")


def test_apply_writeback_preserves_trailing_newline(
    tmp_path: Path, site_config: SiteConfig
) -> None:
    path = tmp_path / "trail.md"
    original = "---\ntitle: Hi\ndate: 2026-04-19\n---\nbody\n"
    path.write_text(original, encoding="utf-8")
    plan = plan_slug_writebacks([parse_post(path, site_config)])
    apply_slug_writebacks(plan)
    after = path.read_text(encoding="utf-8")
    assert after.endswith("body\n")


def test_apply_writeback_preserves_quirky_frontmatter(
    tmp_path: Path, site_config: SiteConfig
) -> None:
    path = tmp_path / "quirky.md"
    original = (
        "---\n"
        "# author note: this is a comment-like line\n"
        'title: "Multi\\nLine"\n'
        "date: 2026-04-19\n"
        "categories:\n"
        "  - engineering   # inline comment\n"
        "  - product\n"
        "summary: |\n"
        "  Multi-line\n"
        "  YAML string\n"
        "---\n"
        "body\n"
    )
    path.write_text(original, encoding="utf-8")
    before_open = original.index("---\n") + len("---\n")
    before_close = original.index("\n---\n", before_open)
    fm_before = original[before_open:before_close]

    plan = plan_slug_writebacks([parse_post(path, site_config)])
    apply_slug_writebacks(plan)

    after = path.read_text(encoding="utf-8")
    after_open = after.index("---\n") + len("---\n")
    after_close = after.index("\n---\n", after_open)
    fm_after = after[after_open:after_close]

    # Exactly one new line was injected; it's the slug line.
    extra_bytes = len(fm_after) - len(fm_before)
    assert fm_after.endswith("\nslug: multi-line")
    assert extra_bytes == len("\nslug: multi-line")
    # Everything before the injection is byte-identical.
    assert fm_after[: len(fm_before)] == fm_before

    # Body unchanged.
    assert after[after.index("\n---\n", after_open) + len("\n---\n") :] == original[
        original.index("\n---\n", before_open) + len("\n---\n") :
    ]


def test_apply_writeback_is_noop_for_posts_with_existing_slug(
    tmp_path: Path, site_config: SiteConfig
) -> None:
    path = tmp_path / "has-slug.md"
    original = "---\nslug: already-here\ntitle: Hi\ndate: 2026-04-19\n---\nbody\n"
    path.write_text(original, encoding="utf-8")
    plan = plan_slug_writebacks([parse_post(path, site_config)])
    apply_slug_writebacks(plan)
    assert path.read_text(encoding="utf-8") == original


def test_apply_writeback_does_not_touch_files_when_duplicates_present(
    tmp_path: Path, site_config: SiteConfig
) -> None:
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    body_a = "---\ntitle: Same\ndate: 2026-04-19\n---\nbody-a\n"
    body_b = "---\ntitle: Same\ndate: 2026-04-20\n---\nbody-b\n"
    a.write_text(body_a, encoding="utf-8")
    b.write_text(body_b, encoding="utf-8")
    plan = plan_slug_writebacks([parse_post(a, site_config), parse_post(b, site_config)])
    assert plan.writebacks == []
    assert plan.duplicates != []
    apply_slug_writebacks(plan)
    assert a.read_text(encoding="utf-8") == body_a
    assert b.read_text(encoding="utf-8") == body_b


def test_apply_writeback_non_ascii_title(tmp_path: Path, site_config: SiteConfig) -> None:
    path = tmp_path / "unicode.md"
    original = "---\ntitle: \"Café Résumé\"\ndate: 2026-04-19\n---\nbody\n"
    path.write_text(original, encoding="utf-8")
    plan = plan_slug_writebacks([parse_post(path, site_config)])
    apply_slug_writebacks(plan)
    reparsed = parse_post(path, site_config)
    assert reparsed.slug == "cafe-resume"


def test_apply_writeback_raises_when_file_has_no_frontmatter(
    tmp_path: Path,
) -> None:
    path = tmp_path / "no-fm.md"
    path.write_text("just a body, no frontmatter\n", encoding="utf-8")
    bogus_post = _post_with(path, slug=None, title="Title")
    plan = plan_slug_writebacks([bogus_post])
    with pytest.raises(PostParseError):
        apply_slug_writebacks(plan)
