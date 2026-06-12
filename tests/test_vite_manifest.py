"""Tests for cress.vite_manifest — parsing Vite build manifests for CSS hrefs."""

import json
from pathlib import Path

import pytest

from cress.exceptions import ConfigError
from cress.vite_manifest import read_vite_css_hrefs


def _write_manifest(path: Path, data: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_single_entry_one_css(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "src/main.ts": {
                "file": "assets/main-abc.js",
                "isEntry": True,
                "css": ["assets/main-xyz.css"],
            }
        },
    )
    assert read_vite_css_hrefs(manifest) == ["/assets/main-xyz.css"]


def test_single_entry_multiple_css(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "src/main.ts": {
                "file": "assets/main-abc.js",
                "isEntry": True,
                "css": ["assets/a-xyz.css", "assets/b-xyz.css"],
            }
        },
    )
    assert read_vite_css_hrefs(manifest) == ["/assets/a-xyz.css", "/assets/b-xyz.css"]


def test_entry_with_imports_transitive_css(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "src/main.ts": {
                "file": "assets/main.js",
                "isEntry": True,
                "css": ["assets/main.css"],
                "imports": ["_chunk-shared.js"],
            },
            "_chunk-shared.js": {
                "file": "assets/chunk-shared.js",
                "css": ["assets/chunk-shared.css"],
            },
        },
    )
    assert read_vite_css_hrefs(manifest) == [
        "/assets/main.css",
        "/assets/chunk-shared.css",
    ]


def test_multiple_entries_order_preserved(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "src/a.ts": {
                "file": "assets/a.js",
                "isEntry": True,
                "css": ["assets/a.css"],
            },
            "src/b.ts": {
                "file": "assets/b.js",
                "isEntry": True,
                "css": ["assets/b.css"],
            },
        },
    )
    assert read_vite_css_hrefs(manifest) == ["/assets/a.css", "/assets/b.css"]


def test_entry_without_css_returns_empty_for_that_entry(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "src/no-css.ts": {
                "file": "assets/no-css.js",
                "isEntry": True,
            },
            "src/with-css.ts": {
                "file": "assets/with-css.js",
                "isEntry": True,
                "css": ["assets/with-css.css"],
            },
        },
    )
    assert read_vite_css_hrefs(manifest) == ["/assets/with-css.css"]


def test_style_css_asset_entry_collected(tmp_path: Path) -> None:
    # Vite with ``cssCodeSplit: false`` (and rolldown-vite v8) emits the whole
    # CSS bundle as a top-level "style.css" asset entry; the entry chunk
    # carries no ``css`` array at all.
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "index.html": {
                "file": "assets/index-D3BgqrJ-.js",
                "isEntry": True,
            },
            "style.css": {
                "file": "assets/style-Bp0SMdj3.css",
                "src": "style.css",
            },
        },
    )
    assert read_vite_css_hrefs(manifest) == ["/assets/style-Bp0SMdj3.css"]


def test_style_css_asset_entry_deduplicated_against_entry_css(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "src/main.ts": {
                "file": "assets/main.js",
                "isEntry": True,
                "css": ["assets/style-abc.css"],
            },
            "style.css": {
                "file": "assets/style-abc.css",
                "src": "style.css",
            },
        },
    )
    assert read_vite_css_hrefs(manifest) == ["/assets/style-abc.css"]


def test_deduplicates_css_shared_between_entries(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "src/a.ts": {
                "file": "assets/a.js",
                "isEntry": True,
                "css": ["assets/shared.css", "assets/a.css"],
            },
            "src/b.ts": {
                "file": "assets/b.js",
                "isEntry": True,
                "css": ["assets/shared.css", "assets/b.css"],
            },
        },
    )
    assert read_vite_css_hrefs(manifest) == [
        "/assets/shared.css",
        "/assets/a.css",
        "/assets/b.css",
    ]


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("/", "/assets/x.css"),
        ("", "/assets/x.css"),
        ("/app/", "/app/assets/x.css"),
        ("/app", "/app/assets/x.css"),
    ],
)
def test_asset_prefix_applied_single_slash(tmp_path: Path, prefix: str, expected: str) -> None:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "src/main.ts": {
                "file": "assets/main.js",
                "isEntry": True,
                "css": ["assets/x.css"],
            }
        },
    )
    assert read_vite_css_hrefs(manifest, asset_prefix=prefix) == [expected]


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(ConfigError) as exc:
        read_vite_css_hrefs(missing)
    assert str(missing) in str(exc.value)
    assert "vite build" in str(exc.value)


def test_malformed_json_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        read_vite_css_hrefs(path)
    assert "invalid JSON" in str(exc.value)
    assert str(path) in str(exc.value)


def test_no_entry_chunks_raises_config_error(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "_chunk.js": {
                "file": "assets/chunk.js",
                "css": ["assets/chunk.css"],
            },
        },
    )
    with pytest.raises(ConfigError) as exc:
        read_vite_css_hrefs(manifest)
    assert "no entry chunks" in str(exc.value)


def test_dangling_import_raises_config_error(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        {
            "src/main.ts": {
                "file": "assets/main.js",
                "isEntry": True,
                "imports": ["_missing-chunk.js"],
            },
        },
    )
    with pytest.raises(ConfigError) as exc:
        read_vite_css_hrefs(manifest)
    assert "_missing-chunk.js" in str(exc.value)
