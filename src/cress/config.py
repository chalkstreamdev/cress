"""Site and user configuration loading.

Reads ``<target>/.cress/config.yaml`` and ``~/.config/cress/config.yaml``,
merges them with CLI overrides, validates required fields, fills in defaults.

Produces a frozen :class:`SiteConfig` — the single config handle passed around
the rest of the pipeline.
"""

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from cress.exceptions import ConfigError

DEFAULT_USER_CONFIG_PATH: Path = Path.home() / ".config" / "cress" / "config.yaml"


@dataclass(frozen=True, slots=True)
class SiteMetaConfig:
    """The ``site:`` block — surfaced to templates as ``site.*``."""

    title: str
    description: str
    base_url: str
    locale: str = "en_US"
    twitter_handle: str | None = None
    default_image: str | None = None


@dataclass(frozen=True, slots=True)
class FeaturesConfig:
    """The ``features:`` block — feature flags."""

    rss: bool = True
    rss_count: int = 20
    sitemap: bool = True
    syntax_highlighting: bool = True
    json_ld: bool = False


@dataclass(frozen=True, slots=True)
class GitConfig:
    """The ``git:`` block — publish-time behaviour."""

    auto_commit: bool = False
    auto_push: bool = False
    remote: str = "origin"
    commit_prefix: str = "blog:"


@dataclass(frozen=True, slots=True)
class SiteConfig:
    """Resolved site configuration.

    All filesystem paths are **absolute** — resolved against the target at
    load time so downstream code never re-resolves.
    """

    target: Path
    vault_subfolder: str
    output_dir: Path
    site: SiteMetaConfig
    assets_dir: Path
    attachments_subfolder: str = "_attachments"
    # Items per index / tag / category page. ``0`` means unlimited — every item
    # on a single page, no ``/page/N/`` splits (useful for static-page manuals
    # whose index reads one summary per section). Must be >= 0.
    paginate: int = 10
    default_author: str = "Author"
    template_dir: Path | None = None
    templates: dict[str, str] = field(default_factory=dict)
    shortcodes: dict[str, str] = field(default_factory=dict)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    pygments_style: str = "default"
    git: GitConfig = field(default_factory=GitConfig)
    # When true, the vault is built as an evergreen documentation site rather
    # than a dated blog: ``date`` frontmatter becomes optional, the vault's
    # folder hierarchy is mirrored into output paths/URLs, the index sorts by
    # path instead of date, and RSS is disabled. Default false → blog mode,
    # byte-for-byte unchanged.
    static_pages: bool = False
    # Derived at load time from ``site.base_url``'s path component. Example:
    # ``base_url: https://example.com/blog`` → ``url_prefix: "/blog"``. Empty
    # when the site is served at the domain root. Used to prefix every
    # cress-generated internal URL (post, tag, category, pagination) and to
    # mount the dev server at the same path so dev matches production.
    url_prefix: str = ""
    # Stylesheet wiring. ``vite_manifest`` points at a Vite build manifest
    # (resolved against ``target`` at load time); cress reads it and emits a
    # ``<link>`` for every CSS asset reachable from an entry chunk.
    # ``vite_asset_prefix`` is the URL prefix under which those assets are
    # served. ``extra_stylesheets`` are appended verbatim after the
    # manifest-derived hrefs (fonts, hand-written stylesheets, etc.).
    vite_manifest: Path | None = None
    vite_asset_prefix: str = "/"
    extra_stylesheets: tuple[str, ...] = ()


def load_site_config(target: Path, config_path: Path | None = None) -> SiteConfig:
    """Load and validate a site config.

    Defaults to ``<target>/.cress/config.yaml``; ``config_path`` overrides that
    so one product repo can host several cress sites (e.g. a blog and a docs
    site) from different config files. All filesystem paths inside the config
    still resolve relative to ``target``, not the config file's directory.
    """
    if config_path is None:
        config_path = target / ".cress" / "config.yaml"
    if not config_path.is_file():
        raise ConfigError(f"config.yaml not found at {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: top-level must be a mapping")

    _require_keys(raw, ("output_dir", "site"), parent="")
    site_raw = raw["site"]
    if not isinstance(site_raw, dict):
        raise ConfigError("site: must be a mapping")
    _require_keys(site_raw, ("title", "description", "base_url"), parent="site.")

    # Optional: omit to publish the whole vault ("" → ``vault / ""`` is the vault root).
    vault_subfolder = _as_str(raw.get("vault_subfolder", ""), "vault_subfolder")
    output_dir_rel = _as_str(raw["output_dir"], "output_dir")
    output_dir = (target / output_dir_rel).resolve()

    template_dir_rel = _maybe(raw.get("template_dir"), "template_dir", _as_str)
    template_dir = (target / template_dir_rel).resolve() if template_dir_rel is not None else None

    assets_dir_rel = _maybe(raw.get("assets_dir"), "assets_dir", _as_str)
    assets_dir = (
        (target / assets_dir_rel).resolve() if assets_dir_rel is not None else output_dir / "assets"
    )
    if not assets_dir.is_relative_to(output_dir):
        raise ConfigError(f"assets_dir must be inside output_dir; got {assets_dir!s}")

    site_meta = SiteMetaConfig(
        title=_as_str(site_raw["title"], "site.title"),
        description=_as_str(site_raw["description"], "site.description"),
        base_url=_as_str(site_raw["base_url"], "site.base_url"),
        locale=_as_str(site_raw.get("locale", "en_US"), "site.locale"),
        twitter_handle=_maybe(site_raw.get("twitter_handle"), "site.twitter_handle", _as_str),
        default_image=_maybe(site_raw.get("default_image"), "site.default_image", _as_str),
    )

    features_raw = raw.get("features", {})
    if not isinstance(features_raw, dict):
        raise ConfigError("features: must be a mapping")
    features = FeaturesConfig(
        rss=_as_bool(features_raw.get("rss", True), "features.rss"),
        rss_count=_as_int(features_raw.get("rss_count", 20), "features.rss_count"),
        sitemap=_as_bool(features_raw.get("sitemap", True), "features.sitemap"),
        syntax_highlighting=_as_bool(
            features_raw.get("syntax_highlighting", True), "features.syntax_highlighting"
        ),
        json_ld=_as_bool(features_raw.get("json_ld", False), "features.json_ld"),
    )

    git_raw = raw.get("git", {})
    if not isinstance(git_raw, dict):
        raise ConfigError("git: must be a mapping")
    git_cfg = GitConfig(
        auto_commit=_as_bool(git_raw.get("auto_commit", False), "git.auto_commit"),
        auto_push=_as_bool(git_raw.get("auto_push", False), "git.auto_push"),
        remote=_as_str(git_raw.get("remote", "origin"), "git.remote"),
        commit_prefix=_as_str(git_raw.get("commit_prefix", "blog:"), "git.commit_prefix"),
    )

    templates_raw = raw.get("templates", {})
    if not isinstance(templates_raw, dict):
        raise ConfigError("templates: must be a mapping")
    templates = {str(k): _as_str(v, f"templates.{k}") for k, v in templates_raw.items()}

    shortcodes_raw = raw.get("shortcodes", {})
    if not isinstance(shortcodes_raw, dict):
        raise ConfigError("shortcodes: must be a mapping")
    shortcodes = {str(k): _as_str(v, f"shortcodes.{k}") for k, v in shortcodes_raw.items()}

    vite_manifest_rel = _maybe(raw.get("vite_manifest"), "vite_manifest", _as_str)
    vite_manifest = (
        (target / vite_manifest_rel).resolve() if vite_manifest_rel is not None else None
    )

    extra_stylesheets_raw = raw.get("extra_stylesheets", [])
    if not isinstance(extra_stylesheets_raw, list):
        raise ConfigError("extra_stylesheets: must be a list")
    extra_stylesheets = tuple(
        _as_str(item, f"extra_stylesheets[{idx}]") for idx, item in enumerate(extra_stylesheets_raw)
    )

    return SiteConfig(
        target=target,
        vault_subfolder=vault_subfolder,
        output_dir=output_dir,
        site=site_meta,
        assets_dir=assets_dir,
        attachments_subfolder=_as_str(
            raw.get("attachments_subfolder", "_attachments"), "attachments_subfolder"
        ),
        paginate=_as_int(raw.get("paginate", 10), "paginate", minimum=0),
        default_author=_as_str(raw.get("default_author", "Author"), "default_author"),
        template_dir=template_dir,
        templates=templates,
        shortcodes=shortcodes,
        features=features,
        pygments_style=_as_str(raw.get("pygments_style", "default"), "pygments_style"),
        git=git_cfg,
        static_pages=_as_bool(raw.get("static_pages", False), "static_pages"),
        url_prefix=_derive_url_prefix(site_meta.base_url),
        vite_manifest=vite_manifest,
        vite_asset_prefix=_as_str(raw.get("vite_asset_prefix", "/"), "vite_asset_prefix"),
        extra_stylesheets=extra_stylesheets,
    )


def _derive_url_prefix(base_url: str) -> str:
    """Extract the URL path portion of ``base_url`` as a no-trailing-slash prefix.

    ``https://example.com``              → ``""``
    ``https://example.com/``             → ``""``
    ``https://example.com/blog``         → ``"/blog"``
    ``https://example.com/blog/``        → ``"/blog"``
    ``https://example.com/news/blog/``   → ``"/news/blog"``
    """
    path = urlparse(base_url).path.rstrip("/")
    return path


def load_user_config(path: Path | None = None) -> dict[str, Any]:
    """Load ``~/.config/cress/config.yaml`` (or ``path`` if given). Absent → ``{}``."""
    user_path = path if path is not None else DEFAULT_USER_CONFIG_PATH
    if not user_path.is_file():
        return {}
    data = yaml.safe_load(user_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{user_path}: top-level must be a mapping")
    return data


def _site_config_vault(target: Path, config_path: Path | None = None) -> str | None:
    """Read the optional ``vault:`` key from the site config.

    Defaults to ``<target>/.cress/config.yaml``; ``config_path`` overrides it
    so ``--config`` selects the alternate config's vault too. Tolerant by
    design — a missing, unreadable, or malformed config returns ``None`` so
    vault resolution can fall through to the next source. Genuine config errors
    surface later from :func:`load_site_config`.
    """
    if config_path is None:
        config_path = target / ".cress" / "config.yaml"
    if not config_path.is_file():
        return None
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return None
    vault = raw.get("vault")
    return vault if isinstance(vault, str) else None


def resolve_vault(
    cli_arg: Path | None,
    user_config: dict[str, Any],
    target: Path | None = None,
    env: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> Path:
    """Resolve the vault path from the first available source.

    Order: CLI ``--vault`` → ``vault:`` in the site config
    (``<target>/.cress/config.yaml``) → ``vault:`` in the user config
    (``~/.config/cress/config.yaml``) → the ``CRESS_VAULT`` environment
    variable. Most-specific wins: a project that declares its own vault
    (e.g. an in-repo content folder) beats the user's global default vault,
    and the vault path travels with the repo — a synced-drive, multi-machine
    setup needs no per-user setup step. A site-config vault given as a
    relative path is resolved against ``target``.
    """
    if cli_arg is not None:
        return cli_arg
    if target is not None:
        site_vault = _site_config_vault(target, config_path)
        if site_vault is not None:
            path = Path(site_vault)
            return path if path.is_absolute() else (target / path).resolve()
    user_vault = user_config.get("vault")
    if user_vault is not None:
        return Path(user_vault)
    environ = env if env is not None else os.environ
    env_vault = environ.get("CRESS_VAULT")
    if env_vault:
        return Path(env_vault)
    raise ConfigError(
        "vault path not provided — pass --vault, set `vault:` in "
        "~/.config/cress/config.yaml or in <target>/.cress/config.yaml, "
        "or set the CRESS_VAULT environment variable"
    )


def _require_keys(data: dict[str, Any], keys: Iterable[str], parent: str) -> None:
    for key in keys:
        if key not in data:
            raise ConfigError(f"missing required field: {parent}{key}")


def _as_str(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{key}: expected string, got {type(value).__name__}")
    return value


def _as_int(value: Any, key: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{key}: expected integer, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{key}: must be >= {minimum}, got {value}")
    return value


def _as_bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{key}: expected boolean, got {type(value).__name__}")
    return value


def _maybe[T](value: Any, key: str, cast: Callable[[Any, str], T]) -> T | None:
    if value is None:
        return None
    return cast(value, key)
