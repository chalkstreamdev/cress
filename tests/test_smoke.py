"""Smoke tests — package imports and CLI exposes its four subcommands."""

import pytest
from typer.main import get_command

import cress
from cress.cli import app


def _option_flags(command_name: str) -> set[str]:
    """Return the registered option flags (e.g. ``--target``) of a subcommand.

    Introspects the Click command directly rather than scraping ``--help``
    output: Typer renders help via Rich, which syntax-highlights option names
    and so interleaves ANSI escapes through a token like ``--target`` whenever
    colour is forced on (as CI does). That breaks naive substring assertions on
    the rendered text while telling us nothing about the actual CLI contract.
    """
    group = get_command(app)
    command = group.commands[command_name]  # type: ignore[attr-defined]
    return {flag for param in command.params for flag in param.opts}


def test_package_importable() -> None:
    assert cress.__version__


def test_package_exposes_public_api() -> None:
    assert cress.cress is not None
    assert cress.plugin is not None
    assert cress.SiteConfig is not None


def test_cli_exposes_four_subcommands() -> None:
    group = get_command(app)
    assert set(group.commands) >= {"build", "validate", "serve", "publish"}  # type: ignore[attr-defined]


@pytest.mark.parametrize("command", ["build", "validate", "serve", "publish"])
def test_cli_command_has_target_option(command: str) -> None:
    assert "--target" in _option_flags(command)
