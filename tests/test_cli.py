"""Tests for cress CLI build + validate commands."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cress import plugin
from cress.cli import app

_CONFIG = """\
vault_subfolder: "Blogs/Demo"
output_dir: "out"
site:
  title: "T"
  description: "D"
  base_url: "https://x.test"
"""


@pytest.fixture(autouse=True)
def _reset_plugins() -> None:
    plugin._reset_all()  # type: ignore[attr-defined]


@pytest.fixture
def fixture(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "v"
    (vault / "Blogs/Demo").mkdir(parents=True)
    (vault / "_attachments").mkdir()
    target = tmp_path / "t"
    (target / ".cress").mkdir(parents=True)
    (target / ".cress/config.yaml").write_text(_CONFIG, encoding="utf-8")
    (target / "out").mkdir()
    return vault, target


def test_cli_build_clean_returns_zero(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\nbody\n", encoding="utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(app, ["build", "--vault", str(vault), "--target", str(target)])
    assert result.exit_code == 0
    assert "built" in result.stdout


def test_cli_build_target_defaults_to_cwd(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, target = fixture
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\nbody\n", encoding="utf-8"
    )
    monkeypatch.chdir(target)
    runner = CliRunner()
    result = runner.invoke(app, ["build", "--vault", str(vault)])
    assert result.exit_code == 0
    assert "built" in result.stdout


def test_cli_build_json_shape(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\nbody\n", encoding="utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(app, ["build", "--vault", str(vault), "--target", str(target), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["version"] == 1
    assert payload["ok"] is True
    assert "pages_written" in payload["result"]
    assert isinstance(payload["warnings"], list)
    assert isinstance(payload["errors"], list)


def test_cli_build_hard_error_exits_nonzero(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\nslug: dup\ndate: 2026-04-19\n---\n", encoding="utf-8"
    )
    (vault / "Blogs/Demo/b.md").write_text(
        "---\ntitle: B\nslug: dup\ndate: 2026-04-20\n---\n", encoding="utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(app, ["build", "--vault", str(vault), "--target", str(target)])
    assert result.exit_code == 1


def test_cli_validate_non_zero_when_missing_slug(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\ndate: 2026-04-19\n---\nbody\n", encoding="utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--vault", str(vault), "--target", str(target)])
    assert result.exit_code == 1
    assert "missing_slug" in result.stdout


def test_cli_validate_fix_writes_slug_and_returns_zero(
    fixture: tuple[Path, Path],
) -> None:
    vault, target = fixture
    src = vault / "Blogs/Demo/a.md"
    src.write_text("---\ntitle: Hello World\ndate: 2026-04-19\n---\nbody\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app, ["validate", "--fix", "--vault", str(vault), "--target", str(target)]
    )
    assert result.exit_code == 0
    contents = src.read_text(encoding="utf-8")
    assert "slug: hello-world" in contents


def test_cli_validate_fix_json(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    src = vault / "Blogs/Demo/a.md"
    src.write_text("---\ntitle: Hello World\ndate: 2026-04-19\n---\nbody\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["validate", "--fix", "--json", "--vault", str(vault), "--target", str(target)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["version"] == 1
    assert payload["ok"] is True
