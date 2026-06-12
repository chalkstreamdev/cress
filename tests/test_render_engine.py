"""Tests for Django template engine setup in cress.render."""

from pathlib import Path

import pytest

from cress.config import SiteConfig, SiteMetaConfig
from cress.exceptions import TemplateNotFound
from cress.plugins import PluginRegistry
from cress.render import build_engine, render_template, resolve_template_name


@pytest.fixture
def site_config(tmp_path: Path) -> SiteConfig:
    target = tmp_path / "product"
    target.mkdir()
    output = target / "output"
    output.mkdir()
    return SiteConfig(
        target=target,
        vault_subfolder="B",
        output_dir=output,
        site=SiteMetaConfig(title="T", description="D", base_url="https://x.test"),
        assets_dir=output / "assets",
    )


@pytest.fixture
def site_config_with_templates(tmp_path: Path) -> SiteConfig:
    target = tmp_path / "product"
    (target / "blog-templates" / "defaults").mkdir(parents=True)
    output = target / "output"
    output.mkdir()
    return SiteConfig(
        target=target,
        vault_subfolder="B",
        output_dir=output,
        site=SiteMetaConfig(title="T", description="D", base_url="https://x.test"),
        assets_dir=output / "assets",
        template_dir=target / "blog-templates",
        templates={"custom": "my_template.html"},
    )


def test_engine_renders_trivial_string_template(site_config: SiteConfig) -> None:
    from django.template import Context

    engine = build_engine(site_config, PluginRegistry())
    tpl = engine.from_string("hello {{ n }}")
    assert tpl.render(Context({"n": "world"})) == "hello world"


def test_missing_template_raises_cress_template_not_found(site_config: SiteConfig) -> None:
    engine = build_engine(site_config, PluginRegistry())
    with pytest.raises(TemplateNotFound):
        render_template(engine, "defaults/absolutely-not-there.html", {})


def test_resolve_template_name_falls_back_to_default() -> None:
    config = SiteConfig(
        target=Path("/x"),
        vault_subfolder="B",
        output_dir=Path("/x/out"),
        site=SiteMetaConfig(title="T", description="D", base_url="https://x.test"),
        assets_dir=Path("/x/out/assets"),
    )
    assert resolve_template_name("post", config) == "defaults/post.html"


def test_resolve_template_name_uses_override() -> None:
    config = SiteConfig(
        target=Path("/x"),
        vault_subfolder="B",
        output_dir=Path("/x/out"),
        site=SiteMetaConfig(title="T", description="D", base_url="https://x.test"),
        assets_dir=Path("/x/out/assets"),
        templates={"post": "custom/my-post.html"},
    )
    assert resolve_template_name("post", config) == "custom/my-post.html"


def test_product_override_directory_wins_over_defaults(
    site_config_with_templates: SiteConfig,
) -> None:
    override_dir = site_config_with_templates.template_dir
    assert override_dir is not None
    (override_dir / "defaults").mkdir(exist_ok=True)
    (override_dir / "defaults" / "post.html").write_text("PRODUCT WINS", encoding="utf-8")
    engine = build_engine(site_config_with_templates, PluginRegistry())
    assert render_template(engine, "defaults/post.html", {}) == "PRODUCT WINS"


def test_product_template_can_extend_defaults(site_config_with_templates: SiteConfig) -> None:
    # Create a minimal default base, then a product template that extends it.
    override_dir = site_config_with_templates.template_dir
    assert override_dir is not None
    (override_dir / "defaults" / "post.html").write_text(
        "BASE:{% block body %}DEFAULT{% endblock %}", encoding="utf-8"
    )
    (override_dir / "overrides.html").write_text(
        '{% extends "defaults/post.html" %}{% block body %}EXTENDED{% endblock %}',
        encoding="utf-8",
    )
    engine = build_engine(site_config_with_templates, PluginRegistry())
    assert render_template(engine, "overrides.html", {}) == "BASE:EXTENDED"


def test_each_build_returns_fresh_engine(site_config: SiteConfig) -> None:
    e1 = build_engine(site_config, PluginRegistry())
    e2 = build_engine(site_config, PluginRegistry())
    assert e1 is not e2


def test_template_filter_isolated_per_engine(site_config: SiteConfig) -> None:
    def shout(value: str) -> str:
        return value.upper()

    from django.template import Context, TemplateSyntaxError

    registry_with = PluginRegistry(template_filters={"shout": shout})
    engine_with = build_engine(site_config, registry_with)
    assert engine_with.from_string("{{ s|shout }}").render(Context({"s": "hi"})) == "HI"

    # A fresh engine built with an empty registry does NOT see the filter.
    registry_without = PluginRegistry()
    engine_without = build_engine(site_config, registry_without)
    with pytest.raises(TemplateSyntaxError):
        engine_without.from_string("{{ s|shout }}").render(Context({"s": "hi"}))
