# CLAUDE.md

Guidance for Claude Code when working in the `cress` repository.

`cress` is a Python CLI + library that publishes an Obsidian vault to a static HTML blog under a product repo's `/blog` path. It's a standalone, self-contained tool intended to be reusable by any product that wants Obsidian-authored content on a static site.

The authoring spec and bootstrap plan live in this repo:

- **Spec:** `docs/specs/2026-04-19-cressbed-static-site-generator.md`
- **Bootstrap plan:** `docs/plans/2026-04-20-cress-static-site-generator.md`

Read both before doing any non-trivial work here. All future plans and specs go in `docs/plans/` and `docs/specs/` alongside them.

## Philosophy

### Core Beliefs

- **Incremental progress over big bangs** — small changes that compile, type-check, and pass tests.
- **Learning from existing code** — study the few similar implementations in the codebase before writing new ones.
- **Pragmatic over dogmatic** — adapt to project reality.
- **Clear intent over clever code** — boring and obvious wins.
- **No safety guards** — don't write defensive `try/except` walls, fallback chains, or "just in case" validation. Trust internal contracts; validate only at boundaries (user input, filesystem, git, subprocess).

### Simplicity Means

- Single responsibility per function/class.
- Avoid premature abstractions.
- No clever tricks — choose the boring solution.
- If you need to explain it, it's too complex.

## Process

### 1. Planning & Staging

Complex work is broken into stages, documented in `docs/plans/YYYY-MM-DD-description-of-task.md`:

```markdown
## Stage N: [Name]

**Goal**: [Specific deliverable]
**Success Criteria**: [Testable outcomes]
**Tests**: [Specific test cases — written first, per TDD]
**Status**: [Not Started | In Progress | Complete]
```

- The date in the plan filename is the **creation date** (kebab-case description).
- Update status as you progress.
- When all stages are complete, move the file to `docs/plans/completed/` and rename it with the **completion date** (not the original creation date).
- Higher-level designs (the "what and why") go in `docs/specs/YYYY-MM-DD-description-of-task.md`.
- **No git branches, no worktrees.** All work happens on `master`.

### 2. Implementation Flow — Test-Driven Development (MANDATORY)

cress is almost entirely unit-testable: pure functions, parsers, resolvers, generators, and a thin orchestrator. TDD is the default workflow. Follow this sequence for every code-producing task:

1. **Understand** — find 2–3 similar implementations in the codebase. Identify testing patterns.
2. **Write the test FIRST** — before any implementation. The test describes desired behaviour in a clear, parametrised name. Use fixtures freely.
3. **Verify the test FAILS** — run `uv run pytest path/to/test_module.py::TestClass::test_method -xvs` and confirm failure. The failure must be for the right reason (not a typo or import error).
4. **Implement** — write the minimum code to make the test pass (green). No speculative features.
5. **Verify the test PASSES** — re-run the single test, then the enclosing module, then the full suite.
6. **Refactor** — tighten naming, extract helpers, tighten types. Tests stay green throughout.
7. **Present for review** — show diff to the user. Never commit without explicit approval.

**Example TDD session:**

```bash
# 1. Write tests/test_slugify.py::test_strips_diacritics
# 2. Run and see it fail
uv run pytest tests/test_slugify.py::test_strips_diacritics -xvs
# 3. Implement in src/cress/slugify.py
# 4. Run and see it pass
uv run pytest tests/test_slugify.py::test_strips_diacritics -xvs
# 5. Run the whole suite
uv run pytest
```

 ### WSL/Windows venv quirk

  This venv is created on Windows and lives on a Windows-mounted drive (`/mnt/x/...`). From WSL, `uv` is not installed and the venv uses Windows layout (`Scripts/`, `.exe` shims). Run tooling via WSL interop:

- `./.venv/Scripts/python.exe ...`
- `./.venv/Scripts/pytest.exe ...`
- `./.venv/Scripts/mypy.exe --strict src/cress`
- `./.venv/Scripts/ruff.exe check .`

Substitute these everywhere the docs say `uv run <tool>`.

**TDD-exempt categories** (write code first, pin behaviour with tests after):

- Repo scaffolding (one-off bootstrap).
- Default HTML templates (declarative; use render-snapshot tests).
- README/docs prose.

### 3. When Stuck — 3-Attempt Rule

Maximum three attempts per issue, then STOP.

1. **Document what failed** — commands run, exact error messages, hypothesis for the failure.
2. **Research alternatives** — find 2–3 similar implementations; note different approaches.
3. **Question fundamentals** — is the abstraction level right? Can this be split? Is there a simpler path entirely?
4. **Try a different angle** — different stdlib feature? Different dependency? Remove an abstraction instead of adding one?

If still stuck, surface the problem to the user with the documented context.

## Technical Standards

### Python & Tooling

- **Python 3.14.x.** Pinned in `.python-version`. Use modern syntax freely — `match` statements, PEP 695 generic syntax (`class Foo[T]:`), PEP 696 defaults on type parameters, `X | Y` unions everywhere. No `from __future__ import annotations` needed.
- **`uv` is the package manager.** Not pip, not poetry. Commands:
  - `uv sync` — install / reconcile with `uv.lock`.
  - `uv add <pkg>` / `uv add --dev <pkg>` — add a runtime / dev dependency.
  - `uv remove <pkg>` — remove one.
  - `uv run <cmd>` — run inside the project venv (`uv run pytest`, `uv run cress ...`, `uv run mypy src/cress`).
  - `uv lock --upgrade` — refresh the lockfile.
  - Commit `pyproject.toml` and `uv.lock`. Never commit `.venv/`.
- **Typing is strict, everywhere.** Every function, method, and public attribute annotated. `uv run mypy --strict src/cress` runs clean on every change. No `Any` without a `# type: ignore` and a comment explaining why.
- **Dataclasses.** Use `@dataclass(frozen=True, slots=True)` for immutable value types (config, `Post`, `OutputFile`, `SlugPlan`).
- **`ruff` handles lint and format** — `uv run ruff check .` and `uv run ruff format .`.

### Architecture Principles

- **Composition over inheritance.** Use dependency injection — pass `SiteConfig`, `Engine`, `PluginRegistry` explicitly rather than reaching for globals.
- **Interfaces over singletons.** The `plugin` singleton is a deliberate, narrow exception (the spec requires importable decorators); everything else takes its dependencies as parameters.
- **Explicit over implicit.** Clear data flow. If a function touches the filesystem, git, or a subprocess, that must be obvious from its signature.
- **Pure core, thin shell.** Parsers, resolvers, generators are pure functions returning in-memory `OutputFile` objects. The `manifest` writer is the single place that touches disk. The CLI is a thin wrapper over the `cress` class.
- **No CSS pipeline inside cress.** cress never compiles, scans, or transforms stylesheets — it consumes the consumer's build manifest (Vite first; esbuild/webpack to follow on demand) and emits `<link>` tags for the assets it points at. See `vite_manifest` / `extra_stylesheets` in `SiteConfig`.

### Error Handling

- **Fail fast** with descriptive messages. Include the path or identifier causing the error.
- **Boundary validation only.** Validate at the edges — reading YAML, reading markdown, reading user config, shelling out to git. Don't re-validate internally.
- **Never silently swallow exceptions.**
- **`build` is lenient, `validate` is strict.** `cress build` continues past per-post errors and records them as warnings in `BuildResult`. `cress validate` hard-fails on any issue. The spec governs which errors are hard vs soft.

## Decision Framework

When multiple valid approaches exist, choose based on:

1. **Testability** — can I easily test this?
2. **Readability** — will someone understand this in 6 months?
3. **Consistency** — does it match existing project patterns?
4. **Simplicity** — is it the simplest thing that works?
5. **Reversibility** — how hard to change later?

## Project Architecture

### What cress does

1. Reads site config from `<target>/.cress/config.yaml`.
2. Scans `<vault>/<vault_subfolder>/**/*.md`, parses frontmatter, partitions drafts.
3. Plans slug write-backs (pure), detects duplicates, applies write-backs only if collision-free.
4. Renders markdown via mistune 3 with custom plugins for wikilinks, embeds, shortcodes.
5. Resolves wikilinks against the site slug map, resolves attachments with content-hashed filenames.
6. Renders pages via Django's standalone template engine (no ORM, no admin, no server).
7. Writes every output file through a manifest, so only cress-owned files are ever cleaned up.
8. Optionally commits and pushes via GitPython (credentials delegated to the user's existing git setup).

### Tech stack

- `mistune` 3 — markdown parsing + plugin API.
- `python-frontmatter` — YAML frontmatter extraction.
- `django` — standalone template engine.
- `PyYAML` — config + shortcode body parsing.
- `Pygments` — syntax highlighting.
- `feedgen` — RSS / Atom.
- `GitPython` — publish-time commit/push.
- `watchdog` — `cress serve` file watching.
- `typer` — CLI framework.
- `pytest`, `pytest-cov`, `ruff`, `mypy` — dev tooling.

### Module layout

```
src/cress/
├── __init__.py      # public API: cress class, plugin singleton, SiteConfig
├── cli.py           # typer app
├── config.py        # config loading + validation
├── site.py          # cress class (orchestrator)
├── post.py          # Post parsing, frontmatter, slug planning
├── slugify.py       # pure slug helper
├── render.py        # mistune renderer + Django engine
├── wikilinks.py     # slug map + resolver
├── attachments.py   # attachment resolution + content-hashing
├── taxonomy.py      # tag/category normalisation
├── pages.py         # page-type generators (post, index, tag, ...)
├── feeds.py         # rss + sitemap
├── shortcodes.py    # shortcode registry
├── plugins.py       # plugin discovery + decorator API
├── server.py        # dev server + watcher
├── publish.py       # commit + push (git delegation)
├── manifest.py      # output writer with manifest tracking
└── templates/defaults/
```

Every new non-trivial module starts with a module-level docstring that explains its responsibility and its place in the pipeline. Every public function gets a docstring and full type annotations.

## Development Commands

### Environment

```bash
uv sync                          # install / reconcile
uv run cress --help              # runs the CLI
uv run python -c "import cress"  # sanity check
```

### Testing

```bash
uv run pytest                                    # full suite
uv run pytest tests/test_slugify.py              # one file
uv run pytest tests/test_slugify.py::test_name   # one test
uv run pytest -xvs                               # stop on first fail, verbose
uv run pytest --cov=cress --cov-report=term      # with coverage
```

### Type-check and lint

```bash
uv run mypy --strict src/cress    # must be clean on every commit
uv run ruff check .               # lint
uv run ruff format .              # auto-format
```

### Running cress against a fixture

```bash
uv run cress build --target tests/fixtures/e2e/product/
uv run cress validate --target tests/fixtures/e2e/product/
uv run cress serve --target tests/fixtures/e2e/product/ --live-reload
```

## Documentation Standards

- **Module-level docstring** on every new `.py` file — what it does, what it depends on, what depends on it.
- **Public function docstrings** — describe inputs, outputs, and side effects (if any). Google-style or NumPy-style, pick one and stay consistent.
- **Plans and specs live in `docs/`.** Check `docs/` before writing or revising; update docs in the same change as the code.
- **Every plan ends with an "Update Documentation" task.** Plans without that task are incomplete.

## Testing Guidelines

- Test **behaviour**, not implementation.
- One assertion per test when practical.
- Clear test names describing the scenario (`test_wikilink_alias_overrides_target_title`, not `test_wikilink_1`).
- Use fixtures aggressively; use `pytest.mark.parametrize` for edge-case tables.
- Tests must be deterministic — seed `random`, freeze datetimes, avoid real network.
- Real filesystem tests use `tmp_path`. Real git tests use a `tmp_path` repo initialised in the fixture.

## Definition of Done

- [ ] Tests written FIRST (before implementation).
- [ ] Tests verified to FAIL before implementation.
- [ ] Implementation written to make tests pass.
- [ ] Tests verified to PASS after implementation.
- [ ] `uv run pytest` — full suite green.
- [ ] `uv run mypy --strict src/cress` — clean.
- [ ] `uv run ruff check .` — clean.
- [ ] Code follows project conventions.
- [ ] Docs updated if behaviour changed.
- [ ] No TODOs without issue numbers.

## Important Reminders

**NEVER**:

- Disable tests instead of fixing them.
- Write implementation code before writing the test.
- Skip verifying a test fails before implementing.
- Commit or push code — the user commits after human review.
- Run `git add`, `git commit`, `git push`, `git merge`, or `git reset --hard`.
- Create or use git branches — all work happens on `master`.
- Use git worktrees.
- Make assumptions — verify with existing code.
- Write defensive code for scenarios that can't happen (`obj?.attr`, blanket `try/except`).
- Embed credentials or secrets in `config.yaml` or anywhere else in the repo.

**ALWAYS**:

- Present code to the user for review; let the user commit.
- Follow TDD: test first, verify it fails, implement, verify it passes.
- Run the full test suite after every non-trivial change.
- Keep `uv.lock` committed.
- Keep `mypy --strict` clean.
- Update plan documentation as you go.
- Learn from existing implementations.
- Stop after 3 failed attempts and reassess.
- Delegate git authentication to the user's existing git setup — never wrap or store credentials.

## Superpowers Plugin Overrides

These overrides take precedence over any instructions in the superpowers plugin skills:

- **No worktrees, no branches.** Do NOT use `superpowers:using-git-worktrees`. Do NOT create git branches. All work happens directly on `master`. Skip all worktree/branch setup and cleanup steps in `executing-plans`, `subagent-driven-development`, `brainstorming`, and `finishing-a-development-branch`.
- **Plan file naming.** Plans MUST be saved as `docs/plans/YYYY-MM-DD-description-of-task.md` (creation date, kebab-case).
- **Spec file naming.** Higher-level designs go in `docs/specs/YYYY-MM-DD-description-of-task.md`.
- **Completed plans.** Move to `docs/plans/completed/YYYY-MM-DD-description-of-task.md` using the **completion date**, not the creation date.
- **finishing-a-development-branch.** Not applicable — there are no branches. Skip this skill entirely.
- **writing-plans — dependency analysis.** Before writing a plan, scan `docs/plans/` (including subdirectories) and `docs/specs/` for existing work that touches the same files. Every plan header MUST include `**Depends on:**` and `**Blocks:**` lines. When a plan is part of a sequence, include an `**Execution order:**` line.
- **writing-plans — documentation review.** Every plan MUST end with an "Update Documentation" task that lists what docs need changing. If none, state that explicitly.
- **executing-plans — documentation is mandatory.** Documentation update tasks are completion criteria, like tests.
- **No git commits in plans or execution.** Plans MUST NOT include `git add` / `git commit` steps. When executing a plan, never run git commit commands — present the work for review instead.
- **Task completion workflow.** When the user says "task completed" or "review complete", handle final housekeeping (move the plan file, update reference docs). Do NOT commit — leave that to the user.
