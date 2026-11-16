"""Tests for cress CLI build + validate commands."""

import json
from pathlib import Path
from unittest import mock

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


def test_validate_warns_on_missing_date_in_static_mode(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    (target / ".cress/config.yaml").write_text(_CONFIG + "static_pages: true\n", encoding="utf-8")
    (vault / "Blogs/Demo/a.md").write_text("---\ntitle: A\nslug: a\n---\nbody\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--vault", str(vault), "--target", str(target)])
    # A dateless page is legitimate in static mode — surfaced, but not a failure.
    assert result.exit_code == 0
    assert "missing_date" in result.stdout


def test_build_config_option_selects_alternate_config(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    # Default config builds the blog into "out"; an alternate docs config
    # (static mode, its own subfolder + output dir) is selected via --config.
    (vault / "Docs").mkdir()
    (vault / "Docs/guide.md").write_text(
        "---\ntitle: Guide\nslug: guide\n---\nbody\n", encoding="utf-8"
    )
    docs_config = (
        'vault_subfolder: "Docs"\n'
        'output_dir: "out-docs"\n'
        "static_pages: true\n"
        "site:\n"
        '  title: "Docs"\n'
        '  description: "D"\n'
        '  base_url: "https://x.test/docs"\n'
    )
    alt = target / ".cress" / "docs.config.yaml"
    alt.write_text(docs_config, encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["build", "--vault", str(vault), "--target", str(target), "--config", str(alt)],
    )
    assert result.exit_code == 0
    # Hierarchy-preserving output landed in the docs output dir.
    assert (target / "out-docs" / "guide" / "index.html").is_file()
    # No RSS in static mode.
    assert not (target / "out-docs" / "rss.xml").exists()


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


def test_cli_serve_passes_list_drafts(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\nbody\n", encoding="utf-8"
    )
    runner = CliRunner()
    with mock.patch("cress.server.serve") as srv:
        result = runner.invoke(
            app, ["serve", "--vault", str(vault), "--target", str(target), "--list-drafts"]
        )
    assert result.exit_code == 0
    assert srv.call_args.kwargs["list_drafts"] is True


def test_cli_index_human_lists_date_path_title(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\nslug: a\ndate: 2026-08-14\n---\nbody\n", encoding="utf-8"
    )
    (vault / "Blogs/Demo/b.md").write_text(
        "---\ntitle: B\nslug: b\ndate: 2026-08-15\n---\nbody\n", encoding="utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(app, ["index", "--vault", str(vault), "--target", str(target)])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["2026-08-15  /b/  B", "2026-08-14  /a/  A"]


def test_cli_index_json_envelope_shape(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\nslug: a\ndate: 2026-08-14\n---\nbody\n", encoding="utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(app, ["index", "--vault", str(vault), "--target", str(target), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["version"] == 1
    assert payload["ok"] is True
    [record] = payload["result"]["posts"]
    assert record["title"] == "A"
    assert record["slug"] == "a"
    assert record["path"] == "/a/"
    assert record["url"] == "https://x.test/a/"
    assert record["date"] == "2026-08-14"
    assert record["draft"] is False


def _index_draft_fixture(vault: Path) -> None:
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\nslug: a\ndate: 2026-08-14\n---\nbody\n", encoding="utf-8"
    )
    (vault / "Blogs/Demo/secret.md").write_text(
        "---\ntitle: Secret\nslug: secret\ndate: 2026-08-15\ndraft: true\n---\nbody\n",
        encoding="utf-8",
    )


def test_cli_index_excludes_drafts_by_default(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _index_draft_fixture(vault)
    runner = CliRunner()
    result = runner.invoke(app, ["index", "--vault", str(vault), "--target", str(target)])
    assert result.exit_code == 0
    assert "Secret" not in result.stdout


def test_cli_index_drafts_flag_includes_marked(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _index_draft_fixture(vault)
    runner = CliRunner()
    result = runner.invoke(
        app, ["index", "--vault", str(vault), "--target", str(target), "--drafts"]
    )
    assert result.exit_code == 0
    draft_lines = [line for line in result.stdout.splitlines() if line.endswith(" [draft]")]
    assert len(draft_lines) == 1
    assert "-secret/" in draft_lines[0]


def test_cli_index_duplicate_slugs_exit_1_json_ok_false(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: Same Title\ndate: 2026-08-14\n---\nbody\n", encoding="utf-8"
    )
    (vault / "Blogs/Demo/b.md").write_text(
        "---\ntitle: Same Title\ndate: 2026-08-15\n---\nbody\n", encoding="utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(app, ["index", "--vault", str(vault), "--target", str(target), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert len(payload["errors"]) == 1


def test_cli_index_empty_vault_exits_0_with_warning(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    runner = CliRunner()
    result = runner.invoke(app, ["index", "--vault", str(vault), "--target", str(target), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["posts"] == []
    assert [w["type"] for w in payload["warnings"]] == ["empty_vault"]


def test_cli_index_config_option_selects_alternate_config(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    (vault / "Docs").mkdir()
    (vault / "Docs/guide.md").write_text(
        "---\ntitle: Guide\nslug: guide\n---\nbody\n", encoding="utf-8"
    )
    docs_config = (
        'vault_subfolder: "Docs"\n'
        'output_dir: "out-docs"\n'
        "static_pages: true\n"
        "site:\n"
        '  title: "Docs"\n'
        '  description: "D"\n'
        '  base_url: "https://x.test/docs"\n'
    )
    alt = target / ".cress" / "docs.config.yaml"
    alt.write_text(docs_config, encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["index", "--vault", str(vault), "--target", str(target), "--config", str(alt), "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    [record] = payload["result"]["posts"]
    assert record["path"] == "/docs/guide/"
    assert record["url"] == "https://x.test/docs/guide/"


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


# --- index.extra (extra-fields spec § 3.2–3.4) ----------------------------

_INDEX_EXTRA = "index:\n  extra:\n    - announce\n    - score\n"


def _reject_constant(name: str) -> None:
    """``json.loads`` hook: fail on ``NaN`` and ``Infinity``, as ``JSON.parse`` does."""
    raise ValueError(f"non-JSON constant {name}")


def _extra_site(target: Path, config_text: str = _CONFIG + _INDEX_EXTRA) -> None:
    (target / ".cress/config.yaml").write_text(config_text, encoding="utf-8")


def _write_extra_post(
    vault: Path, frontmatter: str, *, name: str = "a", draft: bool = False
) -> None:
    header = f"title: {name.upper()}\nslug: {name}\ndate: 2026-08-14\n"
    draft_line = "draft: true\n" if draft else ""
    (vault / f"Blogs/Demo/{name}.md").write_text(
        f"---\n{header}{draft_line}{frontmatter}---\nbody\n", encoding="utf-8"
    )


def _index_json(vault: Path, target: Path) -> tuple[int, str]:
    result = CliRunner().invoke(
        app, ["index", "--vault", str(vault), "--target", str(target), "--json"]
    )
    return result.exit_code, result.stdout


def test_cli_index_json_record_carries_extra(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _extra_site(target)
    _write_extra_post(vault, "announce: true\n")
    _, stdout = _index_json(vault, target)
    payload = json.loads(stdout)
    [record] = payload["result"]["posts"]
    assert (payload["version"], record["extra"]) == (1, {"announce": True, "score": None})


def test_cli_index_json_unsupported_value_is_valid_json(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _extra_site(target)
    _write_extra_post(vault, "score: .nan\n")
    exit_code, stdout = _index_json(vault, target)
    payload = json.loads(stdout, parse_constant=_reject_constant)
    [record] = payload["result"]["posts"]
    assert (exit_code, payload["ok"], record["extra"]["score"]) == (0, True, None)
    assert [w["type"] for w in payload["warnings"]] == ["unsupported_extra_value"]


def test_cli_index_json_self_referring_anchor_emits_envelope(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _extra_site(target)
    _write_extra_post(vault, "score: &a [1, *a]\n")
    exit_code, stdout = _index_json(vault, target)
    payload = json.loads(stdout, parse_constant=_reject_constant)
    assert (exit_code, payload["ok"], [w["type"] for w in payload["warnings"]]) == (
        0,
        True,
        ["unsupported_extra_value"],
    )


def test_cli_index_human_unsupported_value_warns_on_stderr(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _extra_site(target)
    _write_extra_post(vault, "score: .nan\n")
    result = CliRunner().invoke(app, ["index", "--vault", str(vault), "--target", str(target)])
    assert result.stdout.splitlines() == ["2026-08-14  /a/  A"]
    assert "unsupported_extra_value" in result.stderr


def test_cli_index_invalid_extra_config_json_ok_false(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _extra_site(target, _CONFIG + "index:\n  extra: announce\n")
    _write_extra_post(vault, "")
    exit_code, stdout = _index_json(vault, target)
    payload = json.loads(stdout)
    assert (exit_code, payload["ok"], payload["errors"][0]["type"]) == (1, False, "ConfigError")


def test_cli_build_ignores_index_block(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _extra_site(target)
    _write_extra_post(vault, "score: .nan\n")
    result = CliRunner().invoke(app, ["build", "--vault", str(vault), "--target", str(target)])
    assert result.exit_code == 0


def _validate(vault: Path, target: Path, *extra_args: str) -> tuple[int, str]:
    result = CliRunner().invoke(
        app, ["validate", "--vault", str(vault), "--target", str(target), *extra_args]
    )
    return result.exit_code, result.stdout


def test_cli_validate_fails_on_unsupported_extra_value(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _extra_site(target)
    _write_extra_post(vault, "score: .nan\n")
    exit_code, stdout = _validate(vault, target)
    assert (exit_code, "unsupported_extra_value" in stdout) == (1, True)


def test_cli_validate_json_lists_unsupported_extra_value(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _extra_site(target)
    _write_extra_post(vault, "score: .nan\n")
    _, stdout = _validate(vault, target, "--json")
    payload = json.loads(stdout)
    assert (payload["ok"], [w["type"] for w in payload["warnings"]]) == (
        False,
        ["unsupported_extra_value"],
    )


def test_cli_validate_passes_with_supported_extra_values(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _extra_site(target)
    _write_extra_post(vault, "score: 3\n")
    exit_code, stdout = _validate(vault, target)
    assert (exit_code, stdout.splitlines()[-1]) == (0, "0 issue(s)")


def test_cli_validate_ignores_unlisted_field(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _write_extra_post(vault, "score: .nan\n")
    exit_code, _ = _validate(vault, target)
    assert exit_code == 0


def test_cli_validate_reports_unsupported_value_despite_duplicate_slugs(
    fixture: tuple[Path, Path],
) -> None:
    vault, target = fixture
    _extra_site(target)
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: Same Title\ndate: 2026-08-14\nscore: .nan\n---\nbody\n", encoding="utf-8"
    )
    (vault / "Blogs/Demo/b.md").write_text(
        "---\ntitle: Same Title\ndate: 2026-08-15\n---\nbody\n", encoding="utf-8"
    )
    _, stdout = _validate(vault, target)
    assert ("duplicate_slug" in stdout, "unsupported_extra_value" in stdout) == (True, True)


def test_cli_validate_checks_drafts_for_unsupported_values(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _extra_site(target)
    _write_extra_post(vault, "score: .nan\n", name="secret", draft=True)
    exit_code, stdout = _validate(vault, target)
    assert (exit_code, "unsupported_extra_value" in stdout) == (1, True)


# --- validate: wikilinks resolve as in build --------------------------------


def _write_linked_post(vault: Path, name: str, body: str, *, slug: bool = True) -> None:
    slug_line = f"slug: {name}\n" if slug else ""
    (vault / f"Blogs/Demo/{name}.md").write_text(
        f"---\ntitle: {name.upper()}\n{slug_line}date: 2026-08-14\n---\n{body}\n",
        encoding="utf-8",
    )


def test_cli_validate_fails_on_broken_wikilink(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _write_linked_post(vault, "a", "See [[Missing]].")
    exit_code, stdout = _validate(vault, target)
    assert (exit_code, "broken_wikilink" in stdout, "'Missing'" in stdout) == (1, True, True)


def test_cli_validate_passes_with_valid_wikilink(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _write_linked_post(vault, "a", "See [[b]] and [[B|the other post]].")
    _write_linked_post(vault, "b", "No links.")
    exit_code, stdout = _validate(vault, target)
    assert (exit_code, stdout.splitlines()[-1]) == (0, "0 issue(s)")


def test_cli_validate_ignores_wikilink_in_code(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _write_linked_post(vault, "a", "Inline `[[Missing]]`.\n\n```\n[[Also Missing]]\n```")
    exit_code, _ = _validate(vault, target)
    assert exit_code == 0


def test_cli_validate_checks_body_with_quotes(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _write_linked_post(vault, "a", 'A "quoted" word and [[Missing]].')
    exit_code, stdout = _validate(vault, target)
    assert (exit_code, "broken_wikilink" in stdout) == (1, True)


def test_cli_validate_link_to_slugless_post_resolves(fixture: tuple[Path, Path]) -> None:
    vault, target = fixture
    _write_linked_post(vault, "a", "See [[d]].")
    _write_linked_post(vault, "d", "No slug yet.", slug=False)
    result = CliRunner().invoke(app, ["validate", "--vault", str(vault), "--target", str(target)])
    issue_types = [line.split(":")[0] for line in result.stdout.splitlines()[:-1]]
    assert (type(result.exception), issue_types) == (SystemExit, ["missing_slug"])
