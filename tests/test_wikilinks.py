"""Tests for cress.wikilinks — slug map, resolver, substitution."""

from datetime import date
from pathlib import Path

import pytest

from cress.exceptions import DuplicateSlugError
from cress.post import Post
from cress.reports import BuildWarning
from cress.wikilinks import (
    ResolvedLink,
    build_slug_map,
    resolve_wikilink,
    substitute_wikilinks,
)


def _post(
    *, path: str, slug: str, title: str, draft: bool = False, url_path: str | None = None
) -> Post:
    return Post(
        source_path=Path(path),
        title=title,
        date=date(2026, 4, 19),
        body_md="",
        frontmatter_raw={},
        slug=slug,
        url_path=url_path if url_path is not None else slug,
        draft=draft,
    )


def test_build_slug_map_by_filename_and_title() -> None:
    a = _post(path="Notes/Hello.md", slug="hello", title="Hello Post")
    b = _post(path="Notes/Foo.md", slug="foo", title="Foo Item")
    slug_map = build_slug_map([a, b])
    assert slug_map.by_filename_lower["hello"] is a
    assert slug_map.by_filename_lower["foo"] is b
    assert slug_map.by_title_lower["hello post"] is a


def test_build_slug_map_raises_on_duplicate_slug() -> None:
    a = _post(path="A.md", slug="dup", title="A")
    b = _post(path="B.md", slug="dup", title="B")
    with pytest.raises(DuplicateSlugError) as exc:
        build_slug_map([a, b])
    assert "dup" in str(exc.value)


def test_build_slug_map_namespaced_allows_repeated_leaf() -> None:
    a = _post(path="guides/index.md", slug="index", title="Guides", url_path="guides/index")
    b = _post(path="api/index.md", slug="index", title="API", url_path="api/index")
    # Same bare slug in different folders must not collide when namespaced.
    slug_map = build_slug_map([a, b], namespace=lambda p: p.source_path.parent.name)
    assert slug_map.by_filename_lower["index"] is a  # first wins for filename lookup


def test_resolve_wikilink_filename_exact_match() -> None:
    a = _post(path="Notes/Hello.md", slug="hello", title="Hello Post")
    slug_map = build_slug_map([a])
    result = resolve_wikilink("Hello", None, slug_map)
    assert result == ResolvedLink(url="/hello/", label="Hello Post")


def test_resolve_wikilink_filename_case_insensitive() -> None:
    a = _post(path="Notes/Hello.md", slug="hello", title="Hello Post")
    slug_map = build_slug_map([a])
    result = resolve_wikilink("HELLO", None, slug_map)
    assert result is not None
    assert result.url == "/hello/"


def test_resolve_wikilink_title_fallback() -> None:
    a = _post(path="Notes/different-name.md", slug="hello", title="Hello Post")
    slug_map = build_slug_map([a])
    result = resolve_wikilink("hello post", None, slug_map)
    assert result is not None
    assert result.url == "/hello/"


def test_wikilink_resolves_to_nested_url() -> None:
    a = _post(path="guides/Install.md", slug="install", title="Install", url_path="guides/install")
    slug_map = build_slug_map([a])
    result = resolve_wikilink("Install", None, slug_map)
    assert result is not None
    assert result.url == "/guides/install/"


def test_resolve_wikilink_alias_used_as_label() -> None:
    a = _post(path="Notes/Other.md", slug="other", title="Other")
    slug_map = build_slug_map([a])
    result = resolve_wikilink("Other", "see here", slug_map)
    assert result == ResolvedLink(url="/other/", label="see here")


def test_resolve_wikilink_broken_returns_none() -> None:
    slug_map = build_slug_map([])
    assert resolve_wikilink("Nonexistent", None, slug_map) is None


def test_resolve_wikilink_to_draft_uses_draft_url() -> None:
    from cress.wikilinks import draft_url

    draft = _post(path="Notes/Secret.md", slug="secret", title="Secret", draft=True)
    slug_map = build_slug_map([draft])
    result = resolve_wikilink("Secret", None, slug_map)
    assert result is not None
    assert result.url == draft_url(draft)
    assert result.url.startswith("/_drafts/")
    assert result.url.endswith("-secret/")


def test_substitute_wikilinks_replaces_placeholder_anchor() -> None:
    a = _post(path="Notes/Target.md", slug="target", title="Target")
    slug_map = build_slug_map([a])
    warnings: list[BuildWarning] = []
    source = Path("Notes/Src.md")
    html = '<p>See <a data-cress-wikilink="Target" data-cress-alias="">Target</a>.</p>'
    out = substitute_wikilinks(html, slug_map, warnings, source)
    assert '<a href="/target/">Target</a>' in out
    assert "data-cress-wikilink" not in out
    assert warnings == []


def test_substitute_wikilinks_uses_alias() -> None:
    a = _post(path="Notes/Target.md", slug="target", title="Target")
    slug_map = build_slug_map([a])
    warnings: list[BuildWarning] = []
    source = Path("Notes/Src.md")
    html = '<a data-cress-wikilink="Target" data-cress-alias="see here">see here</a>'
    out = substitute_wikilinks(html, slug_map, warnings, source)
    assert '<a href="/target/">see here</a>' in out


def test_substitute_wikilinks_broken_link_emits_warning_and_span() -> None:
    slug_map = build_slug_map([])
    warnings: list[BuildWarning] = []
    source = Path("Notes/Src.md")
    html = '<a data-cress-wikilink="Ghost" data-cress-alias="">Ghost</a>'
    out = substitute_wikilinks(html, slug_map, warnings, source)
    assert '<span class="broken-link">Ghost</span>' in out
    assert len(warnings) == 1
    assert warnings[0].type == "broken_wikilink"
    assert "Ghost" in warnings[0].message
    assert warnings[0].file == str(source)
