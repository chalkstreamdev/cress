"""Git publish — powers ``cress publish``.

Builds the site, stages ``<output_dir>`` in the target repo, commits with the
configured prefix, and optionally pushes. Credentials are delegated entirely
to the user's git setup (ssh-agent, credential helper, CI tokens). cress
never stores or wraps credentials; it sets ``GIT_TERMINAL_PROMPT=0`` so a
misconfigured auth stack fails fast instead of hanging.
"""

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from git import GitCommandError, Repo
from git.exc import InvalidGitRepositoryError

from cress.config import SiteConfig
from cress.exceptions import PublishError


@dataclass(frozen=True, slots=True)
class CommitResult:
    """Outcome of a :func:`commit_outputs` call."""

    changed: bool
    commit_sha: str | None = None
    pushed: bool = False
    push_error: str | None = None


def commit_outputs(
    target: Path, output_dir: Path, config: SiteConfig, pages_written: int
) -> CommitResult:
    """Stage, commit, and optionally push the output directory.

    Raises :class:`PublishError` when the target is not a git repo or when
    ``output_dir`` is matched by a ``.gitignore`` rule.
    """
    try:
        repo = Repo(target, search_parent_directories=False)
    except InvalidGitRepositoryError as exc:
        raise PublishError(f"{target} is not a git repository") from exc

    # Gitignore guard: if output_dir is ignored, commits would be surprising.
    try:
        ignored = repo.git.check_ignore(str(output_dir))
    except GitCommandError as exc:
        # Exit code 1 from check_ignore means "not ignored" — that's success.
        if exc.status == 1:
            ignored = ""
        else:
            raise PublishError(f"git check-ignore failed: {exc}") from exc
    if ignored:
        raise PublishError(
            "output_dir is gitignored in the target repo — `cress publish` cannot commit "
            "ignored paths. Either remove the pattern from `.gitignore` or use `cress build` "
            "for a local-only render."
        )

    # Stage only the output tree.
    repo.git.add(str(output_dir))
    if not repo.is_dirty(index=True, working_tree=False, untracked_files=False):
        return CommitResult(changed=False)

    now = datetime.now().isoformat(timespec="seconds")
    message = f"{config.git.commit_prefix} rebuild — {pages_written} pages, {now}"
    commit = repo.index.commit(message)

    result = CommitResult(changed=True, commit_sha=commit.hexsha)

    if config.git.auto_push:
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        try:
            with repo.git.custom_environment(**env):
                repo.remotes[config.git.remote].push()
            result = CommitResult(
                changed=True, commit_sha=commit.hexsha, pushed=True, push_error=None
            )
        except (GitCommandError, IndexError) as exc:
            result = CommitResult(
                changed=True,
                commit_sha=commit.hexsha,
                pushed=False,
                push_error=str(exc),
            )

    return result
