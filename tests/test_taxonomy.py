"""Tests for cress.taxonomy — tag/category slug normalisation + grouping."""

from datetime import date
from pathlib import Path

from cress.post import Post
from cress.reports import BuildWarning
from cress.taxonomy import Taxonomy


def _post(path: str, slug: str, title: str, d: date) -> Post:
    return Post(
        source_path=Path(path),
        title=title,
        date=d,
        body_md="",
        frontmatter_raw={},
        slug=slug,
    )


def test_first_seen_display_wins_and_variants_group() -> None:
    tax = Taxonomy()
    warnings: list[BuildWarning] = []
    p1 = _post("a.md", "a", "A", date(2026, 4, 20))
    p2 = _post("b.md", "b", "B", date(2026, 4, 21))
    p3 = _post("c.md", "c", "C", date(2026, 4, 22))
    tax.add("Machine Learning", p1, warnings)
    tax.add("machine-learning", p2, warnings)
    tax.add("machine learning", p3, warnings)

    groups = tax.grouped()
    assert len(groups) == 1
    slug, display, posts = groups[0]
    assert slug == "machine-learning"
    assert display == "Machine Learning"
    assert {p.slug for p in posts} == {"a", "b", "c"}
    # Two display-mismatch warnings for p2 and p3
    assert sum(1 for w in warnings if w.type == "display_mismatch") == 2


def test_diacritic_stripping_collides() -> None:
    tax = Taxonomy()
    warnings: list[BuildWarning] = []
    p1 = _post("a.md", "a", "A", date(2026, 4, 20))
    p2 = _post("b.md", "b", "B", date(2026, 4, 21))
    tax.add("Café", p1, warnings)
    tax.add("cafe", p2, warnings)
    groups = tax.grouped()
    assert len(groups) == 1
    assert groups[0][0] == "cafe"


def test_empty_string_rejected() -> None:
    tax = Taxonomy()
    warnings: list[BuildWarning] = []
    p1 = _post("a.md", "a", "A", date(2026, 4, 20))
    tax.add("", p1, warnings)
    assert tax.grouped() == []
    assert any(w.type == "empty_taxonomy_value" for w in warnings)


def test_grouped_sorted_alphabetically_by_slug() -> None:
    tax = Taxonomy()
    warnings: list[BuildWarning] = []
    p1 = _post("a.md", "a", "A", date(2026, 4, 20))
    p2 = _post("b.md", "b", "B", date(2026, 4, 21))
    tax.add("Zeta", p1, warnings)
    tax.add("Alpha", p2, warnings)
    groups = tax.grouped()
    assert [g[0] for g in groups] == ["alpha", "zeta"]


def test_posts_sorted_by_date_descending() -> None:
    tax = Taxonomy()
    warnings: list[BuildWarning] = []
    a = _post("a.md", "a", "A", date(2026, 1, 1))
    b = _post("b.md", "b", "B", date(2026, 2, 1))
    c = _post("c.md", "c", "C", date(2026, 3, 1))
    tax.add("Tag", a, warnings)
    tax.add("Tag", b, warnings)
    tax.add("Tag", c, warnings)
    _, _, posts = tax.grouped()[0]
    assert [p.slug for p in posts] == ["c", "b", "a"]
