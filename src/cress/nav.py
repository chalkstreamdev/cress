"""Navigation tree + breadcrumb derivation (static-pages mode).

Pure functions over the parsed post list. :func:`build_nav` reconstructs the
vault's folder hierarchy from each post's ``url_path`` (the source of truth
stamped by the orchestrator), merging a section landing file with its same-named
folder into one node and marking folders without a landing file as non-clickable
section headers. :func:`breadcrumbs_for` walks the ancestor chain for a single
page.

Both are standalone and I/O-free — the orchestrator builds the tree once and
threads it through :class:`cress.pages.PageContext`; templates render it. No
``Post`` is mutated and no config flag gates the computation (it is cheap data;
whether a sidebar appears is a template concern).
"""

import math
from dataclasses import dataclass

from cress.config import SiteConfig
from cress.post import Post


@dataclass(frozen=True, slots=True)
class NavNode:
    """One node in the navigation tree.

    ``url`` and ``has_page`` are ``None``/``False`` for a folder that has no
    landing file — a non-clickable section header. ``url_path`` is the
    site-root-relative path (``""`` for Home), used as the breadcrumb/active key.
    """

    title: str
    url: str | None
    url_path: str
    has_page: bool
    children: tuple[NavNode, ...]


@dataclass(frozen=True, slots=True)
class NavTree:
    """The full tree: ``roots`` (Home first) plus a ``url_path`` → node index."""

    roots: tuple[NavNode, ...]
    by_path: dict[str, NavNode]


@dataclass(slots=True)
class _Builder:
    """Mutable construction node, frozen into a :class:`NavNode` at the end."""

    url_path: str
    segment: str
    post: Post | None = None
    children: dict[str, _Builder] | None = None

    def child_map(self) -> dict[str, _Builder]:
        if self.children is None:
            self.children = {}
        return self.children


def _titleize(segment: str) -> str:
    """Turn a path segment into a human label: ``position-tagging`` → ``Position Tagging``."""
    return segment.replace("-", " ").replace("_", " ").title()


def _node_url(url_path: str, config: SiteConfig) -> str:
    """Public URL for a page-backed node — mirrors :func:`cress.pages._post_url`."""
    return f"{config.url_prefix}/{url_path}/"


def _label(builder: _Builder) -> str:
    """Sidebar label: ``nav_title`` → ``title`` for a page; titleized segment otherwise."""
    if builder.post is not None:
        return builder.post.nav_title or builder.post.title
    return _titleize(builder.segment)


def _sort_key(builder: _Builder) -> tuple[float, str]:
    """Order siblings: ``nav_order`` ascending, then unordered alphabetically by label."""
    order = math.inf
    if builder.post is not None and builder.post.nav_order is not None:
        order = builder.post.nav_order
    return (order, _label(builder).lower())


def build_nav(posts: list[Post], config: SiteConfig) -> NavTree:
    """Reconstruct the nav tree from the posts' ``url_path`` values. Pure.

    Splits each ``url_path`` on ``/`` and walks/creates intermediate nodes,
    attaching the post to the node whose accumulated path equals its
    ``url_path`` (this merges a section landing with its folder). Intermediate
    nodes with no post become page-less section headers. Each level is ordered
    by ``(nav_order, label)``, a synthetic Home node is prepended, and every node
    is indexed in ``by_path`` (Home keyed ``""``).
    """
    roots: dict[str, _Builder] = {}
    index: dict[str, _Builder] = {}

    for post in posts:
        segments = post.url_path.split("/")
        accumulated = ""
        level = roots
        for segment in segments:
            accumulated = f"{accumulated}/{segment}" if accumulated else segment
            builder = index.get(accumulated)
            if builder is None:
                builder = _Builder(url_path=accumulated, segment=segment)
                index[accumulated] = builder
                level[accumulated] = builder
            level = builder.child_map()
        # The leaf of this post's path is the node the post backs.
        index[post.url_path].post = post

    by_path: dict[str, NavNode] = {}

    def freeze(builder: _Builder) -> NavNode:
        children = tuple(
            freeze(child) for child in sorted((builder.children or {}).values(), key=_sort_key)
        )
        has_page = builder.post is not None
        node = NavNode(
            title=_label(builder),
            url=_node_url(builder.url_path, config) if has_page else None,
            url_path=builder.url_path,
            has_page=has_page,
            children=children,
        )
        by_path[builder.url_path] = node
        return node

    root_nodes = tuple(freeze(b) for b in sorted(roots.values(), key=_sort_key))

    home = NavNode(
        title=config.site.title,
        url=f"{config.url_prefix}/",
        url_path="",
        has_page=True,
        children=(),
    )
    by_path[""] = home

    return NavTree(roots=(home, *root_nodes), by_path=by_path)


def breadcrumbs_for(url_path: str, tree: NavTree) -> tuple[NavNode, ...]:
    """Ancestor trail Home → … → current page for ``url_path``. Pure.

    Walks the prefix chain (``"a/b/c"`` → ``a``, ``a/b``, ``a/b/c``), resolving
    each via ``tree.by_path`` and prepending Home. A page-less ancestor still
    appears (the builder created a node for it). The index path (``""``) yields
    ``[Home]``. The empty (blog-mode) tree has no Home node, so the trail is
    simply empty — breadcrumbs are never rendered in blog mode anyway.
    """
    home = tree.by_path.get("")
    trail: list[NavNode] = [home] if home is not None else []
    if not url_path:
        return tuple(trail)
    accumulated = ""
    for segment in url_path.split("/"):
        accumulated = f"{accumulated}/{segment}" if accumulated else segment
        node = tree.by_path.get(accumulated)
        if node is not None:
            trail.append(node)
    return tuple(trail)
