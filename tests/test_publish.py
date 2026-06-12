"""Tests for cress.publish — commit, push, gitignore guard."""

from pathlib import Path
from unittest import mock

import pytest
from git import Repo
from git.exc import GitCommandError

from cress import plugin
from cress.config import load_site_config
from cress.exceptions import PublishError
from cress.publish import commit_outputs
from cress.site import cress

_CONFIG = """\
vault_subfolder: "Blogs/Demo"
output_dir: "out"
site:
  title: "T"
  description: "D"
  base_url: "https://x.test"
git:
  auto_commit: true
  commit_prefix: "blog:"
  auto_push: false
"""


@pytest.fixture(autouse=True)
def _reset_plugins() -> None:
    plugin._reset_all()  # type: ignore[attr-defined]


def _make_target(tmp_path: Path, config_body: str = _CONFIG) -> tuple[Path, Path, Repo]:
    vault = tmp_path / "v"
    (vault / "Blogs/Demo").mkdir(parents=True)
    (vault / "_attachments").mkdir()
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\nbody\n", encoding="utf-8"
    )
    target = tmp_path / "t"
    target.mkdir()
    repo = Repo.init(target)
    # Create an initial commit on main so we have HEAD for diff checks.
    (target / "README.md").write_text("initial", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    (target / ".cress").mkdir()
    (target / ".cress/config.yaml").write_text(config_body, encoding="utf-8")
    (target / "out").mkdir()
    return vault, target, repo


def test_commit_outputs_creates_commit_with_expected_message(tmp_path: Path) -> None:
    vault, target, repo = _make_target(tmp_path)
    site = cress(vault, target)
    result = site.build()
    commit = commit_outputs(target, site.config.output_dir, site.config, result.pages_written)
    assert commit.changed is True
    assert commit.commit_sha
    head = repo.head.commit
    assert head.message.startswith("blog: rebuild — ")


def test_second_build_no_changes_skips_commit(tmp_path: Path) -> None:
    vault, target, repo = _make_target(tmp_path)
    site = cress(vault, target)
    result = site.build()
    commit_outputs(target, site.config.output_dir, site.config, result.pages_written)
    initial_head = repo.head.commit.hexsha

    result2 = site.build()
    commit2 = commit_outputs(target, site.config.output_dir, site.config, result2.pages_written)
    assert commit2.changed is False
    assert repo.head.commit.hexsha == initial_head


def test_auto_push_false_does_not_call_push(tmp_path: Path) -> None:
    vault, target, _repo = _make_target(tmp_path)
    site = cress(vault, target)
    result = site.build()
    with mock.patch("git.Remote.push") as push_mock:
        commit_outputs(target, site.config.output_dir, site.config, result.pages_written)
    push_mock.assert_not_called()


def test_missing_git_repo_raises_publish_error(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    (vault / "Blogs/Demo").mkdir(parents=True)
    (vault / "_attachments").mkdir()
    (vault / "Blogs/Demo/a.md").write_text(
        "---\ntitle: A\nslug: a\ndate: 2026-04-19\n---\n", encoding="utf-8"
    )
    target = tmp_path / "t"
    target.mkdir()
    (target / ".cress").mkdir()
    (target / ".cress/config.yaml").write_text(_CONFIG, encoding="utf-8")
    (target / "out").mkdir()
    site = cress(vault, target)
    result = site.build()
    with pytest.raises(PublishError):
        commit_outputs(target, site.config.output_dir, site.config, result.pages_written)


def test_gitignored_output_dir_raises_publish_error(tmp_path: Path) -> None:
    vault, target, repo = _make_target(tmp_path)
    (target / ".gitignore").write_text("out/\n", encoding="utf-8")
    repo.index.add([".gitignore"])
    repo.index.commit("add gitignore")
    site = cress(vault, target)
    result = site.build()
    with pytest.raises(PublishError) as exc:
        commit_outputs(target, site.config.output_dir, site.config, result.pages_written)
    assert "gitignore" in str(exc.value).lower()


def test_push_failure_captures_error_as_warning_not_raise(tmp_path: Path) -> None:
    auto_push_config = _CONFIG.replace("auto_push: false", "auto_push: true")
    vault, target, repo = _make_target(tmp_path, config_body=auto_push_config)
    # The bare remote doesn't need to be reachable — we mock push below.
    bare = tmp_path / "bare.git"
    Repo.init(bare, bare=True)
    repo.create_remote("origin", str(bare))

    assert load_site_config(target).git.auto_push is True

    site = cress(vault, target)
    result = site.build()

    def _raise(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise GitCommandError("push", 128, b"", b"auth denied")

    with mock.patch("git.Remote.push", side_effect=_raise):
        commit = commit_outputs(target, site.config.output_dir, site.config, result.pages_written)
    assert commit.changed is True
    assert commit.pushed is False
    assert commit.push_error is not None
    assert "auth denied" in commit.push_error


def test_uncommitted_user_changes_outside_output_dir_untouched(tmp_path: Path) -> None:
    vault, target, _repo = _make_target(tmp_path)
    user_file = target / "user-work.md"
    user_file.write_text("unfinished", encoding="utf-8")
    site = cress(vault, target)
    result = site.build()
    commit_outputs(target, site.config.output_dir, site.config, result.pages_written)
    assert user_file.read_text(encoding="utf-8") == "unfinished"
