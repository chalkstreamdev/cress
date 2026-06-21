"""Tests for cress.config — site config and user config loading."""

from pathlib import Path

import pytest

from cress.config import (
    FeaturesConfig,
    GitConfig,
    SiteConfig,
    SiteMetaConfig,
    load_site_config,
    load_user_config,
    resolve_vault,
)
from cress.exceptions import ConfigError

MINIMAL_CONFIG: str = """\
vault_subfolder: "Blogs/Demo"
output_dir: "public/blog"
site:
  title: "Demo"
  description: "A demo site"
  base_url: "https://example.com/blog"
"""

FULL_CONFIG: str = """\
vault_subfolder: "Blogs/Acme"
output_dir: "public/blog"
site:
  title: "Acme Blog"
  description: "Writing on data viz"
  base_url: "https://acme.com/blog"
  locale: "en_GB"
  twitter_handle: "@acme"
  default_image: "og-default.png"
template_dir: "blog-templates"
assets_dir: "public/blog/static"
attachments_subfolder: "_files"
paginate: 5
default_author: "Acme Team"
templates:
  base: "templates/blog-base.html"
  post_card: "templates/_post_card.html"
shortcodes:
  acme-chart: "blog-templates/shortcodes/acme-chart.html"
features:
  rss: false
  rss_count: 50
  sitemap: false
  syntax_highlighting: false
  json_ld: true
pygments_style: "monokai"
git:
  auto_commit: true
  auto_push: true
  remote: "deploy"
  commit_prefix: "site:"
"""


def _write_config(target: Path, body: str) -> None:
    cress_dir = target / ".cress"
    cress_dir.mkdir(parents=True, exist_ok=True)
    (cress_dir / "config.yaml").write_text(body, encoding="utf-8")


def test_minimal_config_fills_defaults(tmp_path: Path) -> None:
    _write_config(tmp_path, MINIMAL_CONFIG)
    config = load_site_config(tmp_path)
    assert isinstance(config, SiteConfig)
    assert config.target == tmp_path
    assert config.vault_subfolder == "Blogs/Demo"
    assert config.output_dir == (tmp_path / "public/blog").resolve()
    assert config.attachments_subfolder == "_attachments"
    assert config.paginate == 10
    assert config.default_author == "Author"
    assert config.template_dir is None
    assert config.assets_dir == (tmp_path / "public/blog/assets").resolve()
    assert config.templates == {}
    assert config.shortcodes == {}
    assert config.pygments_style == "default"
    assert config.vite_manifest is None
    assert config.vite_asset_prefix == "/"
    assert config.extra_stylesheets == ()
    assert config.site == SiteMetaConfig(
        title="Demo",
        description="A demo site",
        base_url="https://example.com/blog",
    )
    assert config.features == FeaturesConfig()
    assert config.git == GitConfig()


def test_full_config_round_trips_every_field(tmp_path: Path) -> None:
    _write_config(tmp_path, FULL_CONFIG)
    config = load_site_config(tmp_path)
    assert config.vault_subfolder == "Blogs/Acme"
    assert config.output_dir == (tmp_path / "public/blog").resolve()
    assert config.template_dir == (tmp_path / "blog-templates").resolve()
    assert config.assets_dir == (tmp_path / "public/blog/static").resolve()
    assert config.attachments_subfolder == "_files"
    assert config.paginate == 5
    assert config.default_author == "Acme Team"
    assert config.templates == {
        "base": "templates/blog-base.html",
        "post_card": "templates/_post_card.html",
    }
    assert config.shortcodes == {
        "acme-chart": "blog-templates/shortcodes/acme-chart.html",
    }
    assert config.pygments_style == "monokai"
    assert config.site == SiteMetaConfig(
        title="Acme Blog",
        description="Writing on data viz",
        base_url="https://acme.com/blog",
        locale="en_GB",
        twitter_handle="@acme",
        default_image="og-default.png",
    )
    assert config.features == FeaturesConfig(
        rss=False, rss_count=50, sitemap=False, syntax_highlighting=False, json_ld=True
    )
    assert config.git == GitConfig(
        auto_commit=True, auto_push=True, remote="deploy", commit_prefix="site:"
    )


def test_vault_subfolder_optional_defaults_to_whole_vault(tmp_path: Path) -> None:
    body = "\n".join(
        line for line in MINIMAL_CONFIG.splitlines() if not line.startswith("vault_subfolder")
    )
    _write_config(tmp_path, body + "\n")
    config = load_site_config(tmp_path)
    assert config.vault_subfolder == ""


@pytest.mark.parametrize(
    ("drop_path", "expected_fragment"),
    [
        ("output_dir", "output_dir"),
        ("site.title", "site.title"),
        ("site.description", "site.description"),
        ("site.base_url", "site.base_url"),
    ],
)
def test_missing_required_field_raises_config_error(
    tmp_path: Path, drop_path: str, expected_fragment: str
) -> None:
    import yaml

    data = yaml.safe_load(FULL_CONFIG)
    cursor: object = data
    parts = drop_path.split(".")
    for key in parts[:-1]:
        assert isinstance(cursor, dict)
        cursor = cursor[key]
    assert isinstance(cursor, dict)
    del cursor[parts[-1]]
    _write_config(tmp_path, yaml.safe_dump(data))
    with pytest.raises(ConfigError) as exc:
        load_site_config(tmp_path)
    assert expected_fragment in str(exc.value)


def test_missing_config_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_site_config(tmp_path)
    assert "config.yaml" in str(exc.value)


def test_invalid_paginate_type_raises(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + "paginate: ten\n"
    _write_config(tmp_path, body)
    with pytest.raises(ConfigError) as exc:
        load_site_config(tmp_path)
    assert "paginate" in str(exc.value)


def test_paginate_zero_means_unlimited(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + "paginate: 0\n"
    _write_config(tmp_path, body)
    config = load_site_config(tmp_path)
    assert config.paginate == 0


def test_negative_paginate_raises(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + "paginate: -1\n"
    _write_config(tmp_path, body)
    with pytest.raises(ConfigError) as exc:
        load_site_config(tmp_path)
    assert "paginate" in str(exc.value)


def test_assets_dir_outside_output_dir_raises(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + 'assets_dir: "somewhere/else"\n'
    _write_config(tmp_path, body)
    with pytest.raises(ConfigError) as exc:
        load_site_config(tmp_path)
    assert "assets_dir" in str(exc.value)


def test_assets_dir_inside_output_dir_accepted(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + 'assets_dir: "public/blog/nested/assets"\n'
    _write_config(tmp_path, body)
    config = load_site_config(tmp_path)
    assert config.assets_dir == (tmp_path / "public/blog/nested/assets").resolve()


def test_user_config_absent_returns_empty_dict(tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "config.yaml"
    assert load_user_config(missing) == {}


def test_user_config_with_vault_loads(tmp_path: Path) -> None:
    path = tmp_path / "user.yaml"
    path.write_text("vault: /home/me/Obsidian\n", encoding="utf-8")
    data = load_user_config(path)
    assert data == {"vault": "/home/me/Obsidian"}


def test_resolve_vault_cli_wins_over_user_config() -> None:
    vault = resolve_vault(Path("/cli/vault"), {"vault": "/user/vault"})
    assert vault == Path("/cli/vault")


def test_resolve_vault_user_config_used_when_no_cli_arg() -> None:
    vault = resolve_vault(None, {"vault": "/user/vault"})
    assert vault == Path("/user/vault")


def test_resolve_vault_raises_when_neither_provided() -> None:
    with pytest.raises(ConfigError) as exc:
        resolve_vault(None, {}, env={})
    assert "vault" in str(exc.value).lower()


def test_resolve_vault_site_config_wins_over_user_config(tmp_path: Path) -> None:
    # Most-specific wins: a project that declares its own vault (e.g. an
    # in-repo content folder) must not be shadowed by the user's global
    # default vault on machines that happen to have one configured.
    site_vault = (tmp_path / "site-vault").as_posix()
    _write_config(tmp_path, MINIMAL_CONFIG + f'vault: "{site_vault}"\n')
    vault = resolve_vault(None, {"vault": "/user/vault"}, target=tmp_path, env={})
    assert vault == Path(site_vault)


def test_resolve_vault_user_config_used_when_site_config_has_no_vault(tmp_path: Path) -> None:
    _write_config(tmp_path, MINIMAL_CONFIG)  # no vault key
    vault = resolve_vault(None, {"vault": "/user/vault"}, target=tmp_path, env={})
    assert vault == Path("/user/vault")


def test_resolve_vault_site_config_used_when_no_cli_or_user(tmp_path: Path) -> None:
    abs_vault = (tmp_path / "site-vault").as_posix()
    _write_config(tmp_path, MINIMAL_CONFIG + f'vault: "{abs_vault}"\n')
    vault = resolve_vault(None, {}, target=tmp_path, env={})
    assert vault == Path(abs_vault)


def test_resolve_vault_site_config_relative_resolves_against_target(tmp_path: Path) -> None:
    _write_config(tmp_path, MINIMAL_CONFIG + 'vault: "../vault"\n')
    vault = resolve_vault(None, {}, target=tmp_path, env={})
    assert vault == (tmp_path / ".." / "vault").resolve()


def test_resolve_vault_env_var_used_as_last_resort(tmp_path: Path) -> None:
    _write_config(tmp_path, MINIMAL_CONFIG)  # no vault key
    vault = resolve_vault(None, {}, target=tmp_path, env={"CRESS_VAULT": "/env/vault"})
    assert vault == Path("/env/vault")


def test_resolve_vault_site_config_wins_over_env(tmp_path: Path) -> None:
    abs_vault = (tmp_path / "site-vault").as_posix()
    _write_config(tmp_path, MINIMAL_CONFIG + f'vault: "{abs_vault}"\n')
    vault = resolve_vault(None, {}, target=tmp_path, env={"CRESS_VAULT": "/env/vault"})
    assert vault == Path(abs_vault)


def test_resolve_vault_missing_site_config_falls_through_to_env(tmp_path: Path) -> None:
    # No .cress/config.yaml at all — should not raise, just fall through.
    vault = resolve_vault(None, {}, target=tmp_path, env={"CRESS_VAULT": "/env/vault"})
    assert vault == Path("/env/vault")


# --- config selection (--config PATH) -----------------------------------


def test_load_site_config_honours_explicit_path(tmp_path: Path) -> None:
    # Default config at the usual location (blog); an alternate docs config.
    _write_config(tmp_path, MINIMAL_CONFIG)
    alt = tmp_path / ".cress" / "docs.config.yaml"
    alt.write_text(MINIMAL_CONFIG + "static_pages: true\n", encoding="utf-8")
    default_cfg = load_site_config(tmp_path)
    docs_cfg = load_site_config(tmp_path, config_path=alt)
    assert default_cfg.static_pages is False
    assert docs_cfg.static_pages is True
    # Paths still resolve relative to the target, not the config file's dir.
    assert docs_cfg.target == tmp_path


def test_resolve_vault_reads_alternate_config(tmp_path: Path) -> None:
    _write_config(tmp_path, MINIMAL_CONFIG)  # default config: no vault
    alt = tmp_path / ".cress" / "docs.config.yaml"
    docs_vault = (tmp_path / "docs-vault").as_posix()
    alt.write_text(MINIMAL_CONFIG + f'vault: "{docs_vault}"\n', encoding="utf-8")
    vault = resolve_vault(None, {}, target=tmp_path, env={}, config_path=alt)
    assert vault == Path(docs_vault)


# --- static pages mode --------------------------------------------------


def test_static_pages_defaults_false(tmp_path: Path) -> None:
    _write_config(tmp_path, MINIMAL_CONFIG)
    config = load_site_config(tmp_path)
    assert config.static_pages is False


def test_static_pages_parses_true(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + "static_pages: true\n"
    _write_config(tmp_path, body)
    config = load_site_config(tmp_path)
    assert config.static_pages is True


def test_static_pages_rejects_non_bool(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + 'static_pages: "yes"\n'
    _write_config(tmp_path, body)
    with pytest.raises(ConfigError) as exc:
        load_site_config(tmp_path)
    assert "static_pages" in str(exc.value)


# --- stylesheet wiring --------------------------------------------------


def test_vite_manifest_absent_defaults_to_none(tmp_path: Path) -> None:
    _write_config(tmp_path, MINIMAL_CONFIG)
    config = load_site_config(tmp_path)
    assert config.vite_manifest is None


def test_vite_manifest_path_resolved_against_target(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + 'vite_manifest: "dist/.vite/manifest.json"\n'
    _write_config(tmp_path, body)
    config = load_site_config(tmp_path)
    assert config.vite_manifest == (tmp_path / "dist/.vite/manifest.json").resolve()


def test_vite_asset_prefix_default(tmp_path: Path) -> None:
    _write_config(tmp_path, MINIMAL_CONFIG)
    config = load_site_config(tmp_path)
    assert config.vite_asset_prefix == "/"


def test_vite_asset_prefix_custom(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + 'vite_asset_prefix: "/app/"\n'
    _write_config(tmp_path, body)
    config = load_site_config(tmp_path)
    assert config.vite_asset_prefix == "/app/"


def test_extra_stylesheets_default_empty_tuple(tmp_path: Path) -> None:
    _write_config(tmp_path, MINIMAL_CONFIG)
    config = load_site_config(tmp_path)
    assert config.extra_stylesheets == ()


def test_extra_stylesheets_list_preserved_in_order(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + 'extra_stylesheets:\n  - "/a.css"\n  - "/b.css"\n'
    _write_config(tmp_path, body)
    config = load_site_config(tmp_path)
    assert config.extra_stylesheets == ("/a.css", "/b.css")


def test_vite_manifest_wrong_type_raises(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + "vite_manifest: 42\n"
    _write_config(tmp_path, body)
    with pytest.raises(ConfigError) as exc:
        load_site_config(tmp_path)
    assert "vite_manifest" in str(exc.value)


def test_extra_stylesheets_wrong_type_raises(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + 'extra_stylesheets: "not-a-list.css"\n'
    _write_config(tmp_path, body)
    with pytest.raises(ConfigError) as exc:
        load_site_config(tmp_path)
    assert "extra_stylesheets" in str(exc.value)


def test_extra_stylesheets_item_wrong_type_raises(tmp_path: Path) -> None:
    body = MINIMAL_CONFIG + "extra_stylesheets:\n  - 42\n"
    _write_config(tmp_path, body)
    with pytest.raises(ConfigError) as exc:
        load_site_config(tmp_path)
    assert "extra_stylesheets" in str(exc.value)
