# Contributing to cress

Thanks for your interest in cress! This is a small, focused tool and contributions
are welcome — bug reports, docs fixes, and pull requests alike.

## Ground rules

- **Be respectful.** See the [Code of Conduct](CODE_OF_CONDUCT.md).
- **Open an issue first** for anything beyond a small fix, so we can agree on the
  approach before you spend time on it.
- **Keep the scope tight.** cress deliberately does a few things well (see the
  philosophy in [`CLAUDE.md`](CLAUDE.md)). Notably, cress has **no CSS pipeline** —
  it consumes a build tool's manifest rather than compiling styles.

## Development setup

cress uses [`uv`](https://docs.astral.sh/uv/) for dependency management and targets
**Python 3.14**.

```bash
git clone https://github.com/chalkstreamdev/cress.git
cd cress
uv sync                  # install + reconcile with uv.lock
uv run cress --help      # sanity check
```

## The workflow

cress is almost entirely unit-testable (pure functions, parsers, resolvers,
generators, a thin orchestrator), and we follow **test-driven development**:

1. Write the test first.
2. Run it and watch it fail for the right reason.
3. Write the minimum code to make it pass.
4. Refactor with the tests green.

Before opening a PR, make sure all three checks pass:

```bash
uv run pytest                      # full suite must be green
uv run mypy --strict src/cress     # must be clean — typing is strict everywhere
uv run ruff check .                # lint
uv run ruff format .               # format
```

## Coding standards

- **Strict typing everywhere** — every function and public attribute annotated; no
  bare `Any` without a `# type: ignore` and a comment explaining why.
- **Frozen, slotted dataclasses** for immutable value types.
- **Pure core, thin shell** — parsers/resolvers/generators return in-memory objects;
  only the manifest writer touches disk.
- **Boundary validation only** — validate user input, the filesystem, git, and
  subprocesses; trust internal contracts. No defensive `try/except` walls.
- **Module + public-function docstrings** on every new `.py` file.

## Pull requests

- Branch from `master` and keep PRs focused on a single concern.
- Include tests for any behaviour change.
- Update the docs (`README.md`, `docs/`) in the same PR when behaviour changes.
- Add an entry to [`CHANGELOG.md`](CHANGELOG.md) under "Unreleased".
- CI (tests, mypy, ruff) must pass.

## Reporting bugs

Open an issue with: what you ran, what you expected, what happened, and a minimal
config / vault snippet that reproduces it. The `--json` output of the failing
command is often the most useful thing to paste.
