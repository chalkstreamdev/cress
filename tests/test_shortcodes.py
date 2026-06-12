"""Tests for cress.shortcodes — template + python shortcode registry and substitution."""

import base64
from pathlib import Path
from typing import Any

import pytest

from cress.config import SiteConfig, SiteMetaConfig
from cress.plugins import PluginRegistry
from cress.render import build_engine
from cress.reports import BuildWarning
from cress.shortcodes import ShortcodeRegistry, substitute_shortcodes


@pytest.fixture
def site_config(tmp_path: Path) -> SiteConfig:
    target = tmp_path / "product"
    (target / "templates" / "shortcodes").mkdir(parents=True)
    out = target / "out"
    out.mkdir()
    return SiteConfig(
        target=target,
        vault_subfolder="B",
        output_dir=out,
        site=SiteMetaConfig(title="T", description="D", base_url="https://x.test"),
        assets_dir=out / "assets",
        template_dir=target / "templates",
    )


def _placeholder(name: str, body: str) -> str:
    encoded = base64.b64encode(body.encode("utf-8")).decode("ascii")
    return f'<div data-cress-shortcode="{name}" data-cress-body="{encoded}"></div>'


def test_template_shortcode_renders_with_yaml_body(site_config: SiteConfig) -> None:
    tpl_dir = site_config.template_dir
    assert tpl_dir is not None
    tpl_file = tpl_dir / "shortcodes" / "chart.html"
    tpl_file.write_text("<figure>chart id={{ id }} series={{ series }}</figure>", encoding="utf-8")

    engine = build_engine(site_config, PluginRegistry())
    registry = ShortcodeRegistry()
    registry.register_template("chart", "shortcodes/chart.html", engine)

    html = _placeholder("chart", "id: 42\nseries: sales\n")
    warnings: list[BuildWarning] = []
    out = substitute_shortcodes(html, registry, warnings, Path("src.md"))
    assert "chart id=42 series=sales" in out
    assert warnings == []


def test_python_shortcode_receives_body_and_context(site_config: SiteConfig) -> None:
    _ = build_engine(site_config, PluginRegistry())
    seen: dict[str, Any] = {}

    def youtube(body: str, **ctx: Any) -> str:
        seen["body"] = body
        seen["ctx"] = ctx
        return "<iframe>yt</iframe>"

    registry = ShortcodeRegistry()
    registry.register_python("youtube", youtube)
    html = _placeholder("youtube", "id: dQw4w9WgXcQ\n")
    warnings: list[BuildWarning] = []
    out = substitute_shortcodes(
        html, registry, warnings, Path("src.md"), extra_context={"site_title": "X"}
    )
    assert "<iframe>yt</iframe>" in out
    assert "id: dQw4w9WgXcQ" in seen["body"]
    assert seen["ctx"]["site_title"] == "X"


def test_malformed_yaml_emits_warning(site_config: SiteConfig) -> None:
    _ = build_engine(site_config, PluginRegistry())
    registry = ShortcodeRegistry()
    registry.register_python("echo", lambda body, **_: body)
    # Unbalanced indentation / illegal YAML:
    html = _placeholder("echo", "a: :\n  - bad\n   b: 1")
    warnings: list[BuildWarning] = []
    out = substitute_shortcodes(html, registry, warnings, Path("src.md"))
    assert "cress-shortcode-error" in out
    assert any(w.type == "shortcode_error" for w in warnings)


def test_unknown_shortcode_emits_warning(site_config: SiteConfig) -> None:
    _ = build_engine(site_config, PluginRegistry())
    registry = ShortcodeRegistry()
    html = _placeholder("nope", "")
    warnings: list[BuildWarning] = []
    out = substitute_shortcodes(html, registry, warnings, Path("src.md"))
    assert "cress-shortcode-error" in out
    assert any(w.type == "shortcode_error" for w in warnings)


def test_multiple_shortcodes_in_one_doc(site_config: SiteConfig) -> None:
    _ = build_engine(site_config, PluginRegistry())
    registry = ShortcodeRegistry()
    registry.register_python("a", lambda body, **_: f"A:{body.strip()}")
    registry.register_python("b", lambda body, **_: f"B:{body.strip()}")
    html = _placeholder("a", "x: 1") + _placeholder("b", "y: 2")
    warnings: list[BuildWarning] = []
    out = substitute_shortcodes(html, registry, warnings, Path("src.md"))
    assert "A:x: 1" in out
    assert "B:y: 2" in out


def test_registry_names_lists_all_registered() -> None:
    registry = ShortcodeRegistry()
    registry.register_python("a", lambda b, **_: b)
    registry.register_python("b", lambda b, **_: b)
    assert registry.names() == {"a", "b"}
