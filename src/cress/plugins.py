"""Plugin discovery and decorator API.

Exposes the :data:`plugin` singleton that plugin authors import
(``from cress import plugin``) to register shortcodes, template filters and
globals, inline patterns, lifecycle hooks, and custom pages.

:func:`discover_plugins` runs once per :meth:`cress.build` call. Entry-point
plugins are loaded on the first call (their decorators run once per process)
and live in a persistent bucket. Local plugins under
``<target>/.cress/plugins/`` are re-exec'd every call under a unique module
name so ``cress serve`` picks up edits.
"""

import contextlib
import importlib
import importlib.metadata
import importlib.util
import itertools
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cress.reports import BuildWarning

_VALID_HOOK_NAMES = frozenset({"before_build", "after_post", "before_write", "after_build"})


@dataclass(frozen=True, slots=True)
class PluginRegistry:
    """Collected plugin registrations — produced by :func:`discover_plugins`."""

    shortcodes: dict[str, Callable[..., str]] = field(default_factory=dict)
    template_filters: dict[str, Callable[..., Any]] = field(default_factory=dict)
    template_globals: dict[str, Callable[..., Any]] = field(default_factory=dict)
    hooks: dict[str, list[Callable[..., Any]]] = field(default_factory=dict)
    inline_patterns: list[tuple[str, Callable[..., Any]]] = field(default_factory=list)
    custom_pages: list[Callable[..., Any]] = field(default_factory=list)


@dataclass(slots=True)
class _Bucket:
    shortcodes: dict[str, Callable[..., str]] = field(default_factory=dict)
    template_filters: dict[str, Callable[..., Any]] = field(default_factory=dict)
    template_globals: dict[str, Callable[..., Any]] = field(default_factory=dict)
    hooks: dict[str, list[Callable[..., Any]]] = field(default_factory=dict)
    inline_patterns: list[tuple[str, Callable[..., Any]]] = field(default_factory=list)
    custom_pages: list[Callable[..., Any]] = field(default_factory=list)

    def clear(self) -> None:
        self.shortcodes.clear()
        self.template_filters.clear()
        self.template_globals.clear()
        self.hooks.clear()
        self.inline_patterns.clear()
        self.custom_pages.clear()


class _PluginSingleton:
    """The ``plugin`` object that plugin authors import.

    Decorators route into either ``_entrypoint_bucket`` or ``_local_bucket``
    based on the current ``_target`` flag, set by :func:`discover_plugins`
    while it walks entry-points / local files.
    """

    def __init__(self) -> None:
        self._entrypoint_bucket = _Bucket()
        self._local_bucket = _Bucket()
        self._entrypoint_loaded = False
        self._target: str = "local"
        self._local_module_names: list[str] = []

    # -- internal helpers ---------------------------------------------------
    def _bucket(self) -> _Bucket:
        return self._entrypoint_bucket if self._target == "entrypoint" else self._local_bucket

    def _reset_all(self) -> None:
        """Drop every registration — for tests and process re-init paths."""
        self._entrypoint_bucket.clear()
        self._local_bucket.clear()
        self._entrypoint_loaded = False
        for name in list(self._local_module_names):
            sys.modules.pop(name, None)
        self._local_module_names.clear()

    def _reset_local(self) -> None:
        self._local_bucket.clear()
        for name in list(self._local_module_names):
            sys.modules.pop(name, None)
        self._local_module_names.clear()

    # -- decorator API ------------------------------------------------------
    def shortcode(self, name: str) -> Callable[[Callable[..., str]], Callable[..., str]]:
        def decorator(func: Callable[..., str]) -> Callable[..., str]:
            self._bucket().shortcodes[name] = func
            return func

        return decorator

    def template_filter(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._bucket().template_filters[name] = func
            return func

        return decorator

    def template_global(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._bucket().template_globals[name] = func
            return func

        return decorator

    def hook(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        if name not in _VALID_HOOK_NAMES:
            raise ValueError(f"unknown hook {name!r}; valid: {sorted(_VALID_HOOK_NAMES)}")

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._bucket().hooks.setdefault(name, []).append(func)
            return func

        return decorator

    def inline(self, pattern: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._bucket().inline_patterns.append((pattern, func))
            return func

        return decorator

    def page(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        # Path is informational metadata; generators return their own OutputFile paths.
        del path

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._bucket().custom_pages.append(func)
            return func

        return decorator


plugin: _PluginSingleton = _PluginSingleton()

_BUILD_COUNTER = itertools.count()


def _assemble_registry() -> PluginRegistry:
    """Merge the entry-point and local buckets. Local wins on name collision."""
    ep = plugin._entrypoint_bucket  # noqa: SLF001 — helper lives next to the singleton
    lo = plugin._local_bucket  # noqa: SLF001
    shortcodes: dict[str, Callable[..., str]] = {**ep.shortcodes, **lo.shortcodes}
    template_filters = {**ep.template_filters, **lo.template_filters}
    template_globals = {**ep.template_globals, **lo.template_globals}
    hooks: dict[str, list[Callable[..., Any]]] = {}
    for name, fns in ep.hooks.items():
        hooks.setdefault(name, []).extend(fns)
    for name, fns in lo.hooks.items():
        hooks.setdefault(name, []).extend(fns)
    inline_patterns = [*ep.inline_patterns, *lo.inline_patterns]
    custom_pages = [*ep.custom_pages, *lo.custom_pages]
    return PluginRegistry(
        shortcodes=shortcodes,
        template_filters=template_filters,
        template_globals=template_globals,
        hooks=hooks,
        inline_patterns=inline_patterns,
        custom_pages=custom_pages,
    )


def discover_plugins(target: Path, warnings: list[BuildWarning]) -> PluginRegistry:
    """Build (and cache) entry-point plugins; reload local plugins every call."""
    # --- entry-point plugins: first call only -------------------------------
    if not plugin._entrypoint_loaded:  # noqa: SLF001
        plugin._target = "entrypoint"  # noqa: SLF001
        eps: Any
        try:
            eps = importlib.metadata.entry_points(group="cress.plugins")
        except Exception as exc:
            warnings.append(
                BuildWarning(
                    type="plugin_load_failed",
                    file="<entry_points>",
                    message=f"entry_points discovery failed: {exc}",
                )
            )
            eps = ()
        for ep in sorted(eps, key=lambda e: e.name):
            try:
                ep.load()
            except Exception as exc:
                warnings.append(
                    BuildWarning(
                        type="plugin_load_failed",
                        file=f"<entry_point:{ep.name}>",
                        message=f"failed to load entry-point plugin {ep.name!r}: {exc}",
                    )
                )
        plugin._entrypoint_loaded = True  # noqa: SLF001

    # --- local plugins: reset + reload every call ---------------------------
    plugin._target = "local"  # noqa: SLF001
    plugin._reset_local()  # noqa: SLF001
    plugin_dir = target / ".cress" / "plugins"
    if plugin_dir.is_dir():
        # Drop any stale __pycache__ — otherwise low-resolution mtimes on some
        # filesystems let the .pyc shadow an edited source file.
        _clear_pycache(plugin_dir)
        importlib.invalidate_caches()
        build_id = next(_BUILD_COUNTER)
        for py in sorted(plugin_dir.glob("*.py")):
            module_name = f"cress_local_plugins.{build_id}.{py.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, py)
                if spec is None or spec.loader is None:
                    raise ImportError(f"cannot build spec for {py}")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                plugin._local_module_names.append(module_name)  # noqa: SLF001
            except Exception as exc:
                sys.modules.pop(module_name, None)
                warnings.append(
                    BuildWarning(
                        type="plugin_load_failed",
                        file=str(py),
                        message=f"failed to load local plugin {py.name!r}: {exc}",
                    )
                )

    return _assemble_registry()


def _clear_pycache(plugin_dir: Path) -> None:
    cache = plugin_dir / "__pycache__"
    if not cache.is_dir():
        return
    for entry in cache.iterdir():
        with contextlib.suppress(OSError):
            entry.unlink()
