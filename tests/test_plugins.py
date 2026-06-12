"""Tests for cress.plugins — discover_plugins + decorator API + hot-reload."""

import importlib.metadata
import sys
from pathlib import Path
from typing import Any

import pytest

from cress.plugins import PluginRegistry, discover_plugins, plugin
from cress.reports import BuildWarning


@pytest.fixture(autouse=True)
def _clean_plugin_state(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wipe any state from previous tests and make entry-point discovery empty by default.
    plugin._reset_all()  # type: ignore[attr-defined]
    monkeypatch.setattr(
        importlib.metadata, "entry_points", lambda group=None: ()  # type: ignore[misc]
    )


def _write_plugin(target: Path, body: str, name: str = "foo.py") -> Path:
    pdir = target / ".cress" / "plugins"
    pdir.mkdir(parents=True, exist_ok=True)
    path = pdir / name
    path.write_text(body, encoding="utf-8")
    return path


def test_local_shortcode_registered(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.shortcode('chart')\n"
        "def chart(body, **ctx):\n"
        "    return '<figure></figure>'\n",
    )
    warnings: list[BuildWarning] = []
    registry = discover_plugins(tmp_path, warnings)
    assert "chart" in registry.shortcodes
    assert registry.shortcodes["chart"]("") == "<figure></figure>"
    assert warnings == []


def test_template_filter_registered(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.template_filter('money')\n"
        "def money(v):\n"
        "    return f'${v}'\n",
    )
    registry = discover_plugins(tmp_path, [])
    assert "money" in registry.template_filters
    assert registry.template_filters["money"](3) == "$3"


def test_hook_registered_and_collected(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "calls = []\n"
        "@plugin.hook('after_post')\n"
        "def after(post): calls.append(post)\n",
    )
    registry = discover_plugins(tmp_path, [])
    assert "after_post" in registry.hooks
    assert len(registry.hooks["after_post"]) == 1


def test_plugin_template_global_registered(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.template_global('year')\n"
        "def year():\n"
        "    return 2026\n",
    )
    registry = discover_plugins(tmp_path, [])
    assert "year" in registry.template_globals


def test_plugin_inline_pattern_registered(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.inline(r'@(\\w+)')\n"
        "def at_mention(match, context): return '<mention>'\n",
    )
    registry = discover_plugins(tmp_path, [])
    assert len(registry.inline_patterns) == 1


def test_plugin_page_registered(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.page('/archive/')\n"
        "def archive(): return []\n",
    )
    registry = discover_plugins(tmp_path, [])
    assert len(registry.custom_pages) == 1


def test_invalid_plugin_file_warns_not_raises(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "this is (( not valid python\n", name="bad.py")
    warnings: list[BuildWarning] = []
    registry = discover_plugins(tmp_path, warnings)
    assert any(w.type == "plugin_load_failed" for w in warnings)
    assert isinstance(registry, PluginRegistry)


def test_no_double_registration_across_two_calls(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.shortcode('chart')\n"
        "def chart(body, **ctx):\n"
        "    return 'ok'\n",
    )
    r1 = discover_plugins(tmp_path, [])
    r2 = discover_plugins(tmp_path, [])
    assert len(r1.shortcodes) == 1
    assert len(r2.shortcodes) == 1


def test_hot_reload_picks_up_edits(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.shortcode('x')\n"
        "def x(body, **ctx):\n"
        "    return 'OLD'\n",
    )
    r1 = discover_plugins(tmp_path, [])
    assert r1.shortcodes["x"]("") == "OLD"

    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.shortcode('x')\n"
        "def x(body, **ctx):\n"
        "    return 'NEW'\n",
    )
    r2 = discover_plugins(tmp_path, [])
    assert r2.shortcodes["x"]("") == "NEW"


def test_local_module_cleanup_from_sys_modules(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.shortcode('x')\n"
        "def x(body, **ctx):\n"
        "    return 'hi'\n",
    )
    discover_plugins(tmp_path, [])
    first_call_modules = [m for m in sys.modules if m.startswith("cress_local_plugins.")]
    assert first_call_modules
    discover_plugins(tmp_path, [])
    # The first call's modules are gone from sys.modules
    for m in first_call_modules:
        assert m not in sys.modules


def test_entry_point_plugin_discovered_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin._reset_all()  # type: ignore[attr-defined]

    # Synthesise a fake entry-point plugin that registers a shortcode on load.
    def _ep_load() -> Any:
        @plugin.shortcode("ep_chart")
        def _handler(body: str, **ctx: Any) -> str:
            return "<ep/>"
        return _handler

    class _FakeEP:
        name = "fake"
        def load(self) -> Any:
            return _ep_load()

    def _fake_entry_points(group: str | None = None) -> tuple[_FakeEP, ...]:
        if group == "cress.plugins":
            return (_FakeEP(),)
        return ()

    monkeypatch.setattr(importlib.metadata, "entry_points", _fake_entry_points)

    # First call — entry-point loaded, local empty
    r1 = discover_plugins(tmp_path, [])
    assert "ep_chart" in r1.shortcodes

    # Second call after adding a local plugin — entry-point still present
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.shortcode('local_chart')\n"
        "def lc(body, **ctx): return 'L'\n",
    )
    r2 = discover_plugins(tmp_path, [])
    assert "ep_chart" in r2.shortcodes
    assert "local_chart" in r2.shortcodes


def test_local_overrides_entry_point_on_name_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin._reset_all()  # type: ignore[attr-defined]

    class _FakeEP:
        name = "fake"
        def load(self) -> Any:
            @plugin.shortcode("chart")
            def _h(body: str, **ctx: Any) -> str:
                return "ENTRY"
            return _h

    def _fake_entry_points(group: str | None = None) -> tuple[_FakeEP, ...]:
        if group == "cress.plugins":
            return (_FakeEP(),)
        return ()

    monkeypatch.setattr(importlib.metadata, "entry_points", _fake_entry_points)
    _write_plugin(
        tmp_path,
        "from cress import plugin\n"
        "@plugin.shortcode('chart')\n"
        "def ch(body, **ctx): return 'LOCAL'\n",
    )
    registry = discover_plugins(tmp_path, [])
    assert registry.shortcodes["chart"]("") == "LOCAL"
