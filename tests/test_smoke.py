"""Smoke tests — package imports and CLI reports its four subcommands."""

from typer.testing import CliRunner

import cress
from cress.cli import app


def test_package_importable() -> None:
    assert cress.__version__


def test_package_exposes_public_api() -> None:
    assert cress.cress is not None
    assert cress.plugin is not None
    assert cress.SiteConfig is not None


def test_cli_help_lists_four_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("build", "validate", "serve", "publish"):
        assert name in result.stdout


def test_cli_build_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
    assert "--target" in result.stdout


def test_cli_validate_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--help"])
    assert result.exit_code == 0
    assert "--target" in result.stdout


def test_cli_serve_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--target" in result.stdout


def test_cli_publish_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["publish", "--help"])
    assert result.exit_code == 0
    assert "--target" in result.stdout
