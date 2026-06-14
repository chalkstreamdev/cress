"""Tests for cress.post — post parsing, summary, reading time, inline tags."""

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from cress.config import SiteConfig, SiteMetaConfig
from cress.exceptions import PostParseError
from cress.post import Post, _infer_summary, compute_url_path, parse_post, vault_rel_dir


@pytest.fixture
def site_config(tmp_path: Path) -> SiteConfig:
    return SiteConfig(
        target=tmp_path,
        vault_subfolder="Blogs/Demo",
        output_dir=tmp_path / "output",
        site=SiteMetaConfig(
            title="Demo",
            description="Demo site",
            base_url="https://example.com",
        ),
        assets_dir=tmp_path / "output" / "assets",
    )


def _write_post(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_parse_post_full_frontmatter(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "smart.md",
        """\
---
slug: smart-chart-defaults
title: "Smart Chart Defaults"
date: 2026-04-19
updated: 2026-04-20
author: "Nick"
summary: "One-liner for index and meta description"
image: images/hero.png
image_alt: "Chart picking UI"
categories: [engineering, product]
tags: [charts, defaults, ux]
draft: false
canonical: https://example.com/canonical
---
# Body

Some prose.
""",
    )
    post = parse_post(path, site_config)
    assert isinstance(post, Post)
    assert post.slug == "smart-chart-defaults"
    assert post.title == "Smart Chart Defaults"
    assert post.date == date(2026, 4, 19)
    assert post.updated == date(2026, 4, 20)
    assert post.author == "Nick"
    assert post.summary == "One-liner for index and meta description"
    assert post.image == "images/hero.png"
    assert post.image_alt == "Chart picking UI"
    assert post.categories == ["engineering", "product"]
    assert post.tags == ["charts", "defaults", "ux"]
    assert post.draft is False
    assert post.canonical == "https://example.com/canonical"
    assert post.source_path == path


def test_parse_post_missing_title_raises(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "notitle.md",
        """\
---
date: 2026-04-19
---
body
""",
    )
    with pytest.raises(PostParseError) as exc:
        parse_post(path, site_config)
    assert "title" in str(exc.value)


def test_parse_post_missing_date_raises(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "nodate.md",
        """\
---
title: "Hi"
---
body
""",
    )
    with pytest.raises(PostParseError) as exc:
        parse_post(path, site_config)
    assert "date" in str(exc.value)


def test_parse_post_invalid_iso_date_raises(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "baddate.md",
        """\
---
title: "Hi"
date: "2026-13-40"
---
body
""",
    )
    with pytest.raises(PostParseError) as exc:
        parse_post(path, site_config)
    assert "date" in str(exc.value)


def test_parse_post_tags_as_string_raises(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "strtags.md",
        """\
---
title: "Hi"
date: 2026-04-19
tags: "charts"
---
body
""",
    )
    with pytest.raises(PostParseError) as exc:
        parse_post(path, site_config)
    msg = str(exc.value)
    assert "tags" in msg
    assert "list" in msg


def test_parse_post_datetime_date_accepted(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "dt.md",
        """\
---
title: "Hi"
date: 2026-04-19T10:30:00
---
body
""",
    )
    post = parse_post(path, site_config)
    assert post.date == datetime(2026, 4, 19, 10, 30, 0)


def test_parse_post_defaults(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "defaults.md",
        """\
---
title: "Hi"
date: 2026-04-19
---
Hello world.
""",
    )
    post = parse_post(path, site_config)
    assert post.slug is None
    assert post.author == "Author"
    assert post.draft is False
    assert post.categories == []
    assert post.tags == []
    assert post.updated is None
    assert post.canonical is None
    assert post.image is None
    assert post.image_alt is None


# --- nav frontmatter fields ---------------------------------------------


def test_nav_fields_default(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "nav-defaults.md",
        """\
---
title: "Nav"
date: 2026-04-19
---
body
""",
    )
    post = parse_post(path, site_config)
    assert post.nav_order is None
    assert post.nav_title is None
    assert post.nav_hidden is False


def test_nav_order_parses_int(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "nav-order.md",
        """\
---
title: "Nav"
date: 2026-04-19
nav_order: 3
---
body
""",
    )
    post = parse_post(path, site_config)
    assert post.nav_order == 3


def test_nav_order_rejects_non_int(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "nav-order-bad.md",
        """\
---
title: "Nav"
date: 2026-04-19
nav_order: "three"
---
body
""",
    )
    with pytest.raises(PostParseError) as exc:
        parse_post(path, site_config)
    assert "nav_order" in str(exc.value)


def test_nav_order_rejects_bool(tmp_path: Path, site_config: SiteConfig) -> None:
    # YAML parses ``true`` as a bool, which is an ``int`` subclass — reject it.
    path = _write_post(
        tmp_path,
        "nav-order-bool.md",
        """\
---
title: "Nav"
date: 2026-04-19
nav_order: true
---
body
""",
    )
    with pytest.raises(PostParseError) as exc:
        parse_post(path, site_config)
    assert "nav_order" in str(exc.value)


def test_nav_title_parses(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "nav-title.md",
        """\
---
title: "Game Phases"
date: 2026-04-19
nav_title: "Phases"
---
body
""",
    )
    post = parse_post(path, site_config)
    assert post.nav_title == "Phases"


def test_nav_hidden_parses_bool(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "nav-hidden.md",
        """\
---
title: "Nav"
date: 2026-04-19
nav_hidden: true
---
body
""",
    )
    post = parse_post(path, site_config)
    assert post.nav_hidden is True


def test_nav_hidden_rejects_non_bool(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "nav-hidden-bad.md",
        """\
---
title: "Nav"
date: 2026-04-19
nav_hidden: "yes"
---
body
""",
    )
    with pytest.raises(PostParseError) as exc:
        parse_post(path, site_config)
    assert "nav_hidden" in str(exc.value)


# --- static pages mode --------------------------------------------------


def test_static_mode_allows_missing_date(tmp_path: Path, site_config: SiteConfig) -> None:
    static_config = replace(site_config, static_pages=True)
    path = _write_post(
        tmp_path,
        "nodate.md",
        """\
---
title: "Evergreen"
---
body
""",
    )
    post = parse_post(path, static_config)
    assert post.date is None


def test_blog_mode_still_requires_date(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "nodate.md",
        """\
---
title: "Dated"
---
body
""",
    )
    with pytest.raises(PostParseError) as exc:
        parse_post(path, site_config)
    assert "date" in str(exc.value)


def test_url_path_defaults_empty(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "u.md",
        """\
---
title: "U"
date: 2026-04-19
---
body
""",
    )
    post = parse_post(path, site_config)
    assert post.url_path == ""


def test_compute_url_path_blog_is_slug(tmp_path: Path) -> None:
    posts_dir = tmp_path / "Blogs" / "Demo"
    source = posts_dir / "guides" / "install.md"
    assert compute_url_path(source, "install", posts_dir, static_pages=False) == "install"


def test_compute_url_path_static_includes_folder(tmp_path: Path) -> None:
    posts_dir = tmp_path / "Blogs" / "Demo"
    source = posts_dir / "guides" / "install.md"
    assert compute_url_path(source, "install", posts_dir, static_pages=True) == "guides/install"


def test_compute_url_path_static_toplevel_is_slug(tmp_path: Path) -> None:
    posts_dir = tmp_path / "Blogs" / "Demo"
    source = posts_dir / "install.md"
    assert compute_url_path(source, "install", posts_dir, static_pages=True) == "install"


def test_vault_rel_dir_blog_is_empty(tmp_path: Path) -> None:
    posts_dir = tmp_path / "Blogs" / "Demo"
    source = posts_dir / "guides" / "deep" / "install.md"
    assert vault_rel_dir(source, posts_dir, static_pages=False) == ""


def test_vault_rel_dir_static_nested(tmp_path: Path) -> None:
    posts_dir = tmp_path / "Blogs" / "Demo"
    source = posts_dir / "guides" / "deep" / "install.md"
    assert vault_rel_dir(source, posts_dir, static_pages=True) == "guides/deep"


@pytest.mark.parametrize(
    ("body", "expected_prefix"),
    [
        ("# Heading\n\nFirst para text here.", "First para text here"),
        ("First paragraph.\n\nSecond paragraph.", "First paragraph"),
        ("Just one short paragraph.", "Just one short paragraph"),
        (
            "A paragraph with a [[wikilink]] inside and an ![[embed]] too.",
            "A paragraph with a wikilink inside and an",
        ),
    ],
)
def test_infer_summary(body: str, expected_prefix: str) -> None:
    summary = _infer_summary(body)
    assert summary.startswith(expected_prefix)


def test_infer_summary_truncates_at_word_boundary() -> None:
    body = "word " * 200
    summary = _infer_summary(body)
    assert len(summary) <= 160
    assert not summary.endswith(" ")
    assert summary.endswith("...") or summary.endswith("word")


def test_reading_time_short_body(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "short.md",
        """\
---
title: "S"
date: 2026-04-19
---
hello world
""",
    )
    post = parse_post(path, site_config)
    assert post.reading_time_minutes == 1


def test_reading_time_long_body(tmp_path: Path, site_config: SiteConfig) -> None:
    words = " ".join(["lorem"] * 900)
    path = _write_post(
        tmp_path,
        "long.md",
        f"""\
---
title: "L"
date: 2026-04-19
---
{words}
""",
    )
    post = parse_post(path, site_config)
    assert post.reading_time_minutes == 4


def test_inline_tag_harvested(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "inline.md",
        """\
---
title: "T"
date: 2026-04-19
tags: [explicit]
---
This post is about #machine-learning and #data.
""",
    )
    post = parse_post(path, site_config)
    assert "explicit" in post.tags
    assert "machine-learning" in post.tags
    assert "data" in post.tags


def test_inline_tag_dedupes_with_frontmatter(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "dup.md",
        """\
---
title: "T"
date: 2026-04-19
tags: [ml]
---
Discussing #ml here.
""",
    )
    post = parse_post(path, site_config)
    assert post.tags.count("ml") == 1


def test_hashtag_inside_fenced_code_block_ignored(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "code.md",
        """\
---
title: "T"
date: 2026-04-19
---
Regular text here.

```python
# this is a comment with #nottag inside
x = "#alsonot"
```

Now #realtag.
""",
    )
    post = parse_post(path, site_config)
    assert "realtag" in post.tags
    assert "nottag" not in post.tags
    assert "alsonot" not in post.tags


def test_hashtag_inside_inline_code_ignored(tmp_path: Path, site_config: SiteConfig) -> None:
    path = _write_post(
        tmp_path,
        "inlinecode.md",
        """\
---
title: "T"
date: 2026-04-19
---
See `#notagainst`. But #realtag counts.
""",
    )
    post = parse_post(path, site_config)
    assert "realtag" in post.tags
    assert "notagainst" not in post.tags


@pytest.mark.parametrize("prefix", ["# Heading", "## Heading", "###Heading", "######Heading"])
def test_hashtag_on_heading_line_ignored(
    tmp_path: Path, site_config: SiteConfig, prefix: str
) -> None:
    path = _write_post(
        tmp_path,
        "heading.md",
        f"""\
---
title: "T"
date: 2026-04-19
---
{prefix}

But #real counts.
""",
    )
    post = parse_post(path, site_config)
    assert "real" in post.tags
    assert "Heading" not in post.tags
