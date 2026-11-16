"""Tests for cress.index — the read-only, machine-readable post index."""

import datetime as _dt
import hashlib
import math
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from cress import plugin
from cress.attachments import plan_attachment
from cress.config import SiteConfig, load_site_config
from cress.exceptions import ConfigError, DuplicateSlugError
from cress.index import build_post_index, extra_fields
from cress.post import Post, parse_post
from cress.reports import BuildWarning
from cress.site import cress

_MIN_CONFIG = """\
vault_subfolder: "Blogs/Demo"
output_dir: "out"
site:
  title: "T"
  description: "D"
  base_url: "{base_url}"
"""


@pytest.fixture(autouse=True)
def _reset_plugins() -> None:
    plugin._reset_all()  # type: ignore[attr-defined]


def _set_up_site(
    tmp_path: Path,
    *,
    base_url: str = "https://x.test",
    static_pages: bool = False,
    extra: tuple[str, ...] = (),
) -> tuple[Path, SiteConfig]:
    vault = tmp_path / "vault"
    (vault / "Blogs/Demo").mkdir(parents=True)
    (vault / "_attachments").mkdir()

    target = tmp_path / "target"
    (target / ".cress").mkdir(parents=True)
    config_text = _MIN_CONFIG.format(base_url=base_url)
    if static_pages:
        config_text += "static_pages: true\n"
    if extra:
        config_text += "index:\n  extra:\n" + "".join(f"    - {name}\n" for name in extra)
    (target / ".cress" / "config.yaml").write_text(config_text, encoding="utf-8")
    (target / "out").mkdir()
    return vault, load_site_config(target)


def _write_post(vault: Path, name: str, content: str) -> Path:
    path = vault / "Blogs/Demo" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --- record shape and fields ---------------------------------------------


def test_entry_has_all_spec_fields(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(
        vault,
        "full.md",
        "---\n"
        "title: Fully Specified\n"
        "slug: full\n"
        "date: 2026-08-14\n"
        "updated: 2026-08-15\n"
        "summary: A summary.\n"
        "author: Nick\n"
        "tags: [study]\n"
        "categories: [news]\n"
        'image: "/img/hero.png"\n'
        "image_alt: A hero\n"
        "---\nBody text.\n",
    )
    result = build_post_index(vault, config)
    [entry] = result.entries
    assert entry.title == "Fully Specified"
    assert entry.slug == "full"
    assert entry.path == "/full/"
    assert entry.url == "https://x.test/full/"
    assert entry.date == _dt.date(2026, 8, 14)
    assert entry.updated == _dt.date(2026, 8, 15)
    assert entry.summary == "A summary."
    assert entry.author == "Nick"
    assert entry.tags == ["study"]
    assert entry.categories == ["news"]
    assert entry.reading_time_minutes == 1
    assert entry.draft is False
    assert entry.image == "/img/hero.png"
    assert entry.image_alt == "A hero"


def test_path_is_prefix_relative_and_url_is_absolute(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path, base_url="https://x.test/blog")
    _write_post(vault, "a.md", "---\ntitle: A\nslug: a\ndate: 2026-08-14\n---\nBody.\n")
    result = build_post_index(vault, config)
    [entry] = result.entries
    assert entry.path == "/blog/a/"
    assert entry.url == "https://x.test/blog/a/"


def test_to_json_dict_serialises_dates_iso_and_none_passthrough(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(vault, "a.md", "---\ntitle: A\nslug: a\ndate: 2026-08-14T10:30:00\n---\nBody.\n")
    result = build_post_index(vault, config)
    record = result.entries[0].to_json_dict()
    assert record["date"] == "2026-08-14T10:30:00"
    assert record["updated"] is None
    assert record["image"] is None
    assert record["image_alt"] is None


# --- slug determinism (spec D3) ------------------------------------------


def test_slugless_post_gets_promised_slug_without_writeback(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    src = _write_post(vault, "a.md", "---\ntitle: Hello World\ndate: 2026-08-14\n---\nBody.\n")
    before = src.read_bytes()
    result = build_post_index(vault, config)
    assert result.entries[0].slug == "hello-world"
    assert src.read_bytes() == before


def test_promised_slug_matches_build(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    src = _write_post(vault, "a.md", "---\ntitle: Hello World\ndate: 2026-08-14\n---\nBody.\n")
    promised = build_post_index(vault, config).entries[0].slug
    cress(vault, config.target).build()
    assert parse_post(src, config).slug == promised


# --- drafts (spec D5) ----------------------------------------------------


def _draft_fixture(tmp_path: Path) -> tuple[Path, SiteConfig]:
    vault, config = _set_up_site(tmp_path)
    _write_post(vault, "a.md", "---\ntitle: A\nslug: a\ndate: 2026-08-14\n---\nBody.\n")
    _write_post(
        vault,
        "secret.md",
        "---\ntitle: Secret\nslug: secret\ndate: 2026-08-15\ndraft: true\n---\nBody.\n",
    )
    return vault, config


def test_drafts_excluded_by_default(tmp_path: Path) -> None:
    vault, config = _draft_fixture(tmp_path)
    result = build_post_index(vault, config)
    assert [e.slug for e in result.entries] == ["a"]


def test_include_drafts_carries_token_path_and_draft_flag(tmp_path: Path) -> None:
    vault, config = _draft_fixture(tmp_path)
    result = build_post_index(vault, config, include_drafts=True)
    draft = next(e for e in result.entries if e.slug == "secret")
    token = hashlib.sha256(b"secret").hexdigest()[:8]
    assert draft.path == f"/_drafts/{token}-secret/"
    assert draft.draft is True


# --- images (spec D4) ----------------------------------------------------


def test_image_is_hashed_public_url(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    hero = vault / "_attachments" / "hero.png"
    hero.write_bytes(b"png-bytes")
    _write_post(
        vault,
        "a.md",
        "---\ntitle: A\nslug: a\ndate: 2026-08-14\nimage: hero.png\n---\nBody.\n",
    )
    result = build_post_index(vault, config)
    assert result.entries[0].image == plan_attachment(hero, "a", config).public_url
    assert list(config.output_dir.rglob("*")) == []


@pytest.mark.parametrize(
    "ref",
    [
        "https://cdn.example/hero.png",
        "//cdn.example/hero.png",
        "/img/hero.png",
        "data:image/png;base64,aGVybw==",
    ],
)
def test_absolute_image_reference_passes_through(tmp_path: Path, ref: str) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(
        vault,
        "a.md",
        f'---\ntitle: A\nslug: a\ndate: 2026-08-14\nimage: "{ref}"\n---\nBody.\n',
    )
    result = build_post_index(vault, config)
    assert result.entries[0].image == ref


def test_missing_image_warns_and_nulls(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(
        vault,
        "a.md",
        "---\ntitle: A\nslug: a\ndate: 2026-08-14\nimage: nope.png\n---\nBody.\n",
    )
    result = build_post_index(vault, config)
    assert result.entries[0].image is None
    assert [w.type for w in result.warnings] == ["missing_hero_image"]


# --- sort (spec D7) ------------------------------------------------------


def test_blog_sort_date_desc_with_slug_tiebreak(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(vault, "c.md", "---\ntitle: C\nslug: c\ndate: 2026-08-14\n---\nBody.\n")
    _write_post(vault, "b.md", "---\ntitle: B\nslug: b\ndate: 2026-08-15\n---\nBody.\n")
    _write_post(vault, "a.md", "---\ntitle: A\nslug: a\ndate: 2026-08-14\n---\nBody.\n")
    result = build_post_index(vault, config)
    assert [e.slug for e in result.entries] == ["b", "a", "c"]


def test_blog_sort_survives_mixed_date_and_datetime(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(vault, "a.md", "---\ntitle: A\nslug: a\ndate: 2026-08-14\n---\nBody.\n")
    _write_post(vault, "b.md", "---\ntitle: B\nslug: b\ndate: 2026-08-15T10:00:00\n---\nBody.\n")
    result = build_post_index(vault, config)
    assert [e.slug for e in result.entries] == ["b", "a"]


def test_blog_sort_survives_naive_and_aware_datetimes(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(vault, "a.md", "---\ntitle: A\nslug: a\ndate: 2026-08-13T10:00:00\n---\nBody.\n")
    _write_post(
        vault,
        "b.md",
        '---\ntitle: B\nslug: b\ndate: "2026-08-14T10:00:00+02:00"\n---\nBody.\n',
    )
    result = build_post_index(vault, config)
    assert [e.slug for e in result.entries] == ["b", "a"]


def test_static_mode_sorts_by_url_path_and_allows_null_date(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path, static_pages=True)
    _write_post(vault, "guides/install.md", "---\ntitle: Install\nslug: install\n---\nBody.\n")
    _write_post(vault, "about.md", "---\ntitle: About\nslug: about\n---\nBody.\n")
    result = build_post_index(vault, config)
    assert [e.path for e in result.entries] == ["/about/", "/guides/install/"]
    assert result.entries[0].date is None


# --- leniency and failure (spec D2, D6) ----------------------------------


def test_unparseable_post_warns_and_rest_emitted(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(vault, "a.md", "---\ntitle: A\nslug: a\ndate: 2026-08-14\n---\nBody.\n")
    _write_post(vault, "broken.md", "---\ndate: 2026-08-14\n---\nNo title.\n")
    result = build_post_index(vault, config)
    assert [e.slug for e in result.entries] == ["a"]
    assert [w.type for w in result.warnings] == ["post_parse_error"]


def test_empty_vault_returns_empty_with_warning(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    result = build_post_index(vault, config)
    assert result.entries == []
    assert [w.type for w in result.warnings] == ["empty_vault"]


def test_all_posts_unparseable_raises_config_error(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(vault, "broken.md", "---\ndate: 2026-08-14\n---\nNo title.\n")
    with pytest.raises(ConfigError):
        build_post_index(vault, config)


def test_duplicate_slugs_raise(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(vault, "a.md", "---\ntitle: Same Title\ndate: 2026-08-14\n---\nBody.\n")
    _write_post(vault, "b.md", "---\ntitle: Same Title\ndate: 2026-08-15\n---\nBody.\n")
    with pytest.raises(DuplicateSlugError):
        build_post_index(vault, config)


# --- extra field conversion (extra-fields spec § 3.3) ---------------------


def _post_with(frontmatter: dict[str, object]) -> Post:
    return Post(
        source_path=Path("vault/a.md"),
        title="A",
        date=_dt.date(2026, 11, 9),
        body_md="",
        frontmatter_raw=frontmatter,
    )


def _unsupported(message: str) -> BuildWarning:
    return BuildWarning(
        type="unsupported_extra_value", file=str(Path("vault/a.md")), message=message
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("text", "text"),
        (3, 3),
        (True, True),
        (None, None),
        (1.5, 1.5),
        (_dt.date(2026, 11, 9), "2026-11-09"),
        (_dt.datetime(2026, 11, 9, 10, 0), "2026-11-09T10:00:00"),
        (
            _dt.datetime(2026, 11, 9, 10, 0, tzinfo=_dt.timezone(_dt.timedelta(hours=2))),
            "2026-11-09T10:00:00+02:00",
        ),
        ([1, _dt.date(2026, 11, 9)], [1, "2026-11-09"]),
        ({"a": {"b": [_dt.date(2026, 11, 9)]}}, {"a": {"b": ["2026-11-09"]}}),
        ([], []),
        ({}, {}),
    ],
    ids=[
        "str",
        "int",
        "bool",
        "null",
        "float",
        "date",
        "naive-datetime",
        "aware-datetime",
        "list",
        "nested-map",
        "empty-list",
        "empty-map",
    ],
)
def test_extra_fields_converts_supported_value(value: object, expected: object) -> None:
    assert extra_fields(_post_with({"v": value}), ("v",)) == ({"v": expected}, [])


def test_extra_fields_unset_name_is_null() -> None:
    assert extra_fields(_post_with({}), ("missing",)) == ({"missing": None}, [])


def test_extra_fields_no_names_gives_empty_map() -> None:
    assert extra_fields(_post_with({"v": 1}), ()) == ({}, [])


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (math.nan, "`extra.v`: NaN cannot be written as JSON"),
        (math.inf, "`extra.v`: Infinity cannot be written as JSON"),
        (-math.inf, "`extra.v`: -Infinity cannot be written as JSON"),
        (b"hello", "`extra.v`: bytes cannot be written as JSON"),
        ({"a", "b"}, "`extra.v`: set cannot be written as JSON"),
        (("a", 1), "`extra.v`: tuple cannot be written as JSON"),
        ({1: "one"}, "`extra.v`: map key 1 (int) is not a string"),
        ({_dt.date(2026, 11, 9): "x"}, "`extra.v`: map key 2026-11-09 (date) is not a string"),
        ([1, math.nan], "`extra.v[1]`: NaN cannot be written as JSON"),
        ({"links": [{"href": math.nan}]}, "`extra.v.links[0].href`: NaN cannot be written as JSON"),
    ],
    ids=[
        "nan",
        "inf",
        "minus-inf",
        "bytes",
        "set",
        "tuple",
        "int-key",
        "date-key",
        "nan-in-list",
        "nan-deep",
    ],
)
def test_extra_fields_unsupported_value_nulls_field_and_warns(value: object, message: str) -> None:
    assert extra_fields(_post_with({"v": value}), ("v",)) == (
        {"v": None},
        [_unsupported(message)],
    )


def _list_that_contains_itself() -> object:
    loop: list[object] = [1]
    loop.append(loop)
    return loop


def _map_that_contains_itself() -> object:
    loop: dict[str, object] = {}
    loop["self"] = loop
    return loop


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (_list_that_contains_itself, "`extra.v[1]`: the value contains itself"),
        (_map_that_contains_itself, "`extra.v.self`: the value contains itself"),
    ],
    ids=["list", "map"],
)
def test_extra_fields_value_that_contains_itself_is_unsupported(
    make: Callable[[], object], message: str
) -> None:
    assert extra_fields(_post_with({"v": make()}), ("v",)) == (
        {"v": None},
        [_unsupported(message)],
    )


def test_extra_fields_value_nested_too_deeply_is_unsupported() -> None:
    deep: object = 1
    for _ in range(2 * sys.getrecursionlimit()):
        deep = [deep]
    assert extra_fields(_post_with({"v": deep}), ("v",)) == (
        {"v": None},
        [_unsupported("`extra.v`: the value is nested too deeply")],
    )


def test_extra_fields_shared_value_is_not_a_cycle() -> None:
    shared = [1]
    assert extra_fields(_post_with({"v": [shared, shared]}), ("v",)) == ({"v": [[1], [1]]}, [])


def test_extra_fields_bad_field_leaves_other_fields() -> None:
    values, warnings = extra_fields(_post_with({"good": 1, "bad": math.nan}), ("good", "bad"))
    assert (values, len(warnings)) == ({"good": 1, "bad": None}, 1)


# --- extra fields on records (extra-fields spec § 3.2) --------------------


def _post_text(frontmatter: str, *, slug: str = "a", date: str = "2026-08-14") -> str:
    return f"---\ntitle: {slug.upper()}\nslug: {slug}\ndate: {date}\n{frontmatter}---\nBody.\n"


def test_extra_is_empty_map_when_config_lists_nothing(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path)
    _write_post(vault, "a.md", _post_text("announce: true\n"))
    [entry] = build_post_index(vault, config).entries
    assert (entry.extra, entry.to_json_dict()["extra"]) == ({}, {})


def test_extra_carries_listed_value(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path, extra=("announce",))
    _write_post(vault, "a.md", _post_text("announce: true\n"))
    [entry] = build_post_index(vault, config).entries
    assert entry.extra == {"announce": True}


def test_extra_unset_and_explicit_null_give_same_value(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path, extra=("announce",))
    _write_post(vault, "a.md", _post_text("announce: null\n", slug="a"))
    _write_post(vault, "b.md", _post_text("", slug="b"))
    entries = build_post_index(vault, config).entries
    assert [e.extra for e in entries] == [{"announce": None}, {"announce": None}]


def test_extra_listed_builtin_name_is_the_authored_value(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path, extra=("summary",))
    _write_post(vault, "a.md", _post_text(""))
    [entry] = build_post_index(vault, config).entries
    assert (entry.extra, entry.summary) == ({"summary": None}, "Body.")


@pytest.mark.parametrize(
    ("frontmatter", "expected"),
    [
        ("score: 2026-11-09\n", "2026-11-09"),
        ("score: 2026-11-09T10:00:00+02:00\n", "2026-11-09T10:00:00+02:00"),
        ("score: [a, b]\n", ["a", "b"]),
        ("score: {zeta: 1, alpha: 2}\n", {"zeta": 1, "alpha": 2}),
        ("x: &x [1]\nscore: [*x, *x]\n", [[1], [1]]),
    ],
    ids=["date", "aware-datetime", "list", "map", "shared-anchor"],
)
def test_extra_yaml_value_converts(tmp_path: Path, frontmatter: str, expected: object) -> None:
    vault, config = _set_up_site(tmp_path, extra=("score",))
    _write_post(vault, "a.md", _post_text(frontmatter))
    [entry] = build_post_index(vault, config).entries
    assert entry.extra == {"score": expected}


@pytest.mark.parametrize(
    "frontmatter",
    [
        "score: .nan\n",
        "score: .inf\n",
        "score: !!binary aGVsbG8=\n",
        "score: !!set {a, b}\n",
        "score: !!omap [{a: 1}]\n",
        "score: {1: one}\n",
        "score: {2026-11-09: x}\n",
        "score: &a [1, *a]\n",
        # Loads through PyYAML, which builds nested values without recursion
        # (extra-fields spec § 2).
        "score: " + "[" * 1200 + "1" + "]" * 1200 + "\n",
    ],
    ids=["nan", "inf", "binary", "set", "omap", "int-key", "date-key", "self-anchor", "deep"],
)
def test_extra_unsupported_yaml_value_warns_and_nulls(tmp_path: Path, frontmatter: str) -> None:
    vault, config = _set_up_site(tmp_path, extra=("score",))
    _write_post(vault, "a.md", _post_text(frontmatter))
    result = build_post_index(vault, config)
    [entry] = result.entries
    assert (entry.extra, [w.type for w in result.warnings]) == (
        {"score": None},
        ["unsupported_extra_value"],
    )


def _extra_draft_fixture(tmp_path: Path) -> tuple[Path, SiteConfig]:
    vault, config = _set_up_site(tmp_path, extra=("score",))
    _write_post(vault, "a.md", _post_text("score: 1\n", slug="a"))
    _write_post(vault, "secret.md", _post_text("draft: true\nscore: .nan\n", slug="secret"))
    return vault, config


def test_extra_warning_skips_excluded_draft(tmp_path: Path) -> None:
    vault, config = _extra_draft_fixture(tmp_path)
    assert build_post_index(vault, config).warnings == []


def test_extra_warning_covers_included_draft(tmp_path: Path) -> None:
    vault, config = _extra_draft_fixture(tmp_path)
    result = build_post_index(vault, config, include_drafts=True)
    draft = next(e for e in result.entries if e.slug == "secret")
    assert (draft.extra, [w.type for w in result.warnings]) == (
        {"score": None},
        ["unsupported_extra_value"],
    )


def test_extra_in_static_pages_mode(tmp_path: Path) -> None:
    vault, config = _set_up_site(tmp_path, static_pages=True, extra=("announce",))
    _write_post(vault, "about.md", "---\ntitle: About\nslug: about\nannounce: true\n---\nBody.\n")
    [entry] = build_post_index(vault, config).entries
    assert (entry.date, entry.extra) == (None, {"announce": True})
