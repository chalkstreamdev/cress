"""Vite build-manifest parsing.

Reads ``dist/.vite/manifest.json`` and returns the list of CSS hrefs that
should be emitted into rendered pages.

Vite's manifest is a JSON object keyed by source-file path. Each entry may
declare ``isEntry: true``, an array ``css: [...]`` of CSS files produced by
the chunk, and an array ``imports: [...]`` whose elements are keys back into
the manifest pointing at chunks whose CSS must also be loaded for the entry
to render correctly. We walk every entry chunk, transitively follow
``imports`` to collect every reachable CSS asset, deduplicate while
preserving first-seen order, and prefix each path with the configured asset
prefix.

This module is pure — it knows nothing about cress's pipeline, ``SiteConfig``,
or the consumer's filesystem layout beyond the manifest path itself. The
``SiteConfig`` integration lives in :mod:`cress.config` and the call site in
:mod:`cress.pages`.
"""

import json
from pathlib import Path
from typing import Any

from cress.config import SiteConfig
from cress.exceptions import ConfigError


def read_vite_css_hrefs(manifest_path: Path, asset_prefix: str = "/") -> list[str]:
    """Parse a Vite manifest and return CSS hrefs prefixed for serving.

    Args:
        manifest_path: Path to the Vite ``manifest.json`` file.
        asset_prefix: URL prefix joined to each manifest-provided path.
            Defaults to ``"/"`` (site root). A trailing slash on the prefix
            and a leading slash on the path collapse to exactly one slash.

    Returns:
        CSS hrefs in manifest order, deduplicated, each prefixed with
        ``asset_prefix``.

    Raises:
        ConfigError: If the file is missing, malformed JSON, contains no
            entry chunks, or an entry's ``imports`` references a missing key.
    """
    if not manifest_path.is_file():
        raise ConfigError(
            f"vite_manifest not found at {manifest_path} — did you run `vite build` first?"
        )

    try:
        manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"vite_manifest: invalid JSON at {manifest_path}: {exc}") from exc

    if not isinstance(manifest, dict):
        raise ConfigError(
            f"vite_manifest: expected JSON object at {manifest_path}, got {type(manifest).__name__}"
        )

    entry_keys = [key for key, chunk in manifest.items() if chunk.get("isEntry") is True]
    if not entry_keys:
        raise ConfigError(f"vite_manifest: no entry chunks found in {manifest_path}")

    seen: set[str] = set()
    hrefs: list[str] = []
    for entry_key in entry_keys:
        for css_path in _collect_chunk_css(manifest, entry_key, visited=set()):
            if css_path in seen:
                continue
            seen.add(css_path)
            hrefs.append(_join_prefix(asset_prefix, css_path))

    # With ``build.cssCodeSplit: false`` Vite extracts the whole CSS bundle
    # into a single top-level "style.css" asset entry; the entry chunks then
    # carry no ``css`` arrays (observed in rolldown-vite v8, documented for
    # classic Vite too). Dedup against ``seen`` covers builds that list the
    # file in both places.
    style_entry = manifest.get("style.css")
    if style_entry is not None:
        css_path = style_entry["file"]
        if css_path not in seen:
            seen.add(css_path)
            hrefs.append(_join_prefix(asset_prefix, css_path))

    return hrefs


def _collect_chunk_css(manifest: dict[str, Any], chunk_key: str, *, visited: set[str]) -> list[str]:
    """Yield CSS paths for ``chunk_key`` and every chunk it transitively imports."""
    if chunk_key in visited:
        return []
    visited.add(chunk_key)

    chunk = manifest[chunk_key]
    css: list[str] = list(chunk.get("css", []))

    for import_key in chunk.get("imports", []):
        if import_key not in manifest:
            raise ConfigError(
                f"vite_manifest: chunk {chunk_key!r} imports missing chunk {import_key!r}"
            )
        css.extend(_collect_chunk_css(manifest, import_key, visited=visited))

    return css


def _join_prefix(prefix: str, path: str) -> str:
    """Join ``prefix`` and ``path`` with exactly one slash between them."""
    if not prefix:
        return f"/{path.lstrip('/')}"
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def resolve_stylesheets(config: SiteConfig) -> list[str]:
    """Combine Vite-manifest CSS and ``extra_stylesheets`` for the page context.

    Order: manifest hrefs first (in manifest order), then ``extra_stylesheets``
    (in config order). No deduplication across the two — if a user double-
    specifies, that's a config smell to fix at the source. Called once per
    build; the result is cached on :class:`~cress.pages.PageContext`.
    """
    sheets: list[str] = []
    if config.vite_manifest is not None:
        sheets.extend(
            read_vite_css_hrefs(config.vite_manifest, asset_prefix=config.vite_asset_prefix)
        )
    sheets.extend(config.extra_stylesheets)
    return sheets
