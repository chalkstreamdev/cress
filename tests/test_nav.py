"""Tests for cress.nav — the pure nav-tree builder and breadcrumb derivation."""

from pathlib import Path

import pytest

from cress.config import SiteConfig, SiteMetaConfig
from cress.nav import NavNode, NavTree, breadcrumbs_for, build_nav
from cress.post import Post


def _config(*, title: str = "Manual", url_prefix: str = "") -> SiteConfig:
    return SiteConfig(
        target=Path("/target"),
        vault_subfolder="B",
        output_dir=Path("/target/out"),
        site=SiteMetaConfig(
            title=title, description="D", base_url="https://example.com" + url_prefix
        ),
        assets_dir=Path("/target/out/assets"),
        static_pages=True,
        url_prefix=url_prefix,
    )


def _post(
    url_path: str,
    title: str = "T",
    *,
    nav_order: int | None = None,
    nav_title: str | None = None,
) -> Post:
    slug = url_path.rsplit("/", 1)[-1]
    return Post(
        source_path=Path(f"{url_path}.md"),
        title=title,
        date=None,
        body_md="",
        frontmatter_raw={},
        slug=slug,
        url_path=url_path,
        nav_order=nav_order,
        nav_title=nav_title,
    )


def _child(node: NavNode, url_path: str) -> NavNode:
    """Find a child of ``node`` by its url_path (test helper)."""
    return next(c for c in node.children if c.url_path == url_path)


# --- build_nav -----------------------------------------------------------


def test_build_nav_two_level() -> None:
    posts = [
        _post("getting-started", "Getting Started"),
        _post("position-tagging", "Position Tagging"),
        _post("position-tagging/events", "Events"),
        _post("position-tagging/game-phases", "Game Phases"),
    ]
    tree = build_nav(posts, _config())
    labels = [n.title for n in tree.roots]
    assert labels == ["Manual", "Getting Started", "Position Tagging"]
    pt = next(n for n in tree.roots if n.url_path == "position-tagging")
    assert pt.has_page is True
    assert len(pt.children) == 2


def test_section_landing_merges_with_folder() -> None:
    posts = [
        _post("position-tagging", "Position Tagging"),
        _post("position-tagging/events", "Events"),
    ]
    tree = build_nav(posts, _config())
    section_nodes = [n for n in tree.roots if n.url_path == "position-tagging"]
    assert len(section_nodes) == 1
    pt = section_nodes[0]
    assert pt.has_page is True
    assert pt.url == "/position-tagging/"
    assert len(pt.children) == 1
    assert pt.children[0].url_path == "position-tagging/events"


def test_pageless_folder_is_nonclickable() -> None:
    posts = [_post("api/install", "Install")]
    tree = build_nav(posts, _config())
    api = next(n for n in tree.roots if n.url_path == "api")
    assert api.has_page is False
    assert api.url is None
    assert api.title == "Api"
    assert len(api.children) == 1
    assert api.children[0].url_path == "api/install"


def test_arbitrary_depth() -> None:
    posts = [_post("a/b/c/d", "Deep")]
    tree = build_nav(posts, _config())
    a = next(n for n in tree.roots if n.url_path == "a")
    b = _child(a, "a/b")
    c = _child(b, "a/b/c")
    d = _child(c, "a/b/c/d")
    assert d.title == "Deep"
    assert d.has_page is True


def test_orders_by_nav_order_then_title() -> None:
    posts = [
        _post("zebra", "Zebra"),  # no nav_order → after ordered, by label
        _post("alpha", "Alpha"),  # no nav_order
        _post("second", "Second", nav_order=2),
        _post("first", "First", nav_order=1),
    ]
    tree = build_nav(posts, _config())
    labels = [n.title for n in tree.roots[1:]]  # skip Home
    assert labels == ["First", "Second", "Alpha", "Zebra"]


def test_nav_title_overrides_label() -> None:
    posts = [_post("game-phases", "Game Phases", nav_title="Phases")]
    tree = build_nav(posts, _config())
    node = next(n for n in tree.roots if n.url_path == "game-phases")
    assert node.title == "Phases"


def test_by_path_indexes_all_nodes() -> None:
    posts = [
        _post("position-tagging", "Position Tagging"),
        _post("position-tagging/events", "Events"),
        _post("api/install", "Install"),
    ]
    tree = build_nav(posts, _config())
    assert tree.by_path[""].title == "Manual"
    assert tree.by_path["position-tagging"].has_page is True
    assert tree.by_path["position-tagging/events"].title == "Events"
    assert tree.by_path["api"].has_page is False
    assert tree.by_path["api/install"].title == "Install"


def test_home_node_first() -> None:
    tree = build_nav([_post("a", "A")], _config(title="My Site"))
    assert tree.roots[0].title == "My Site"
    assert tree.roots[0].url_path == ""
    assert tree.roots[0].url == "/"
    assert tree.roots[0].has_page is True


def test_home_url_includes_prefix() -> None:
    tree = build_nav([_post("a", "A")], _config(url_prefix="/manual"))
    home = tree.roots[0]
    assert home.url == "/manual/"
    a = next(n for n in tree.roots if n.url_path == "a")
    assert a.url == "/manual/a/"


def test_empty_posts_is_home_only() -> None:
    tree = build_nav([], _config())
    assert len(tree.roots) == 1
    assert tree.roots[0].url_path == ""


# --- breadcrumbs_for -----------------------------------------------------


def test_breadcrumbs_nested() -> None:
    posts = [
        _post("position-tagging", "Position Tagging"),
        _post("position-tagging/events", "Events"),
    ]
    tree = build_nav(posts, _config())
    trail = breadcrumbs_for("position-tagging/events", tree)
    assert [n.title for n in trail] == ["Manual", "Position Tagging", "Events"]


def test_breadcrumbs_through_pageless_folder() -> None:
    posts = [_post("api/install", "Install")]
    tree = build_nav(posts, _config())
    trail = breadcrumbs_for("api/install", tree)
    assert [n.title for n in trail] == ["Manual", "Api", "Install"]
    assert trail[1].url is None  # page-less crumb


def test_breadcrumbs_top_level() -> None:
    tree = build_nav([_post("getting-started", "Getting Started")], _config())
    trail = breadcrumbs_for("getting-started", tree)
    assert [n.title for n in trail] == ["Manual", "Getting Started"]


def test_breadcrumbs_index_is_home_only() -> None:
    tree = build_nav([_post("a", "A")], _config())
    trail = breadcrumbs_for("", tree)
    assert [n.title for n in trail] == ["Manual"]


def test_breadcrumbs_unknown_path_is_home_only() -> None:
    tree = build_nav([_post("a", "A")], _config())
    trail = breadcrumbs_for("does/not/exist", tree)
    assert [n.title for n in trail] == ["Manual"]


def test_navtree_is_frozen() -> None:
    tree = build_nav([_post("a", "A")], _config())
    assert isinstance(tree, NavTree)
    assert isinstance(tree.roots[0], NavNode)
    with pytest.raises((AttributeError, Exception)):
        tree.roots[0].title = "x"  # type: ignore[misc]
