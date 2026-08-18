# Implementation Plan: `cress index` subcommand

**Date:** 2026-08-18
**Status:** Complete — awaiting review
**Scope:** The `cress index` CLI subcommand and its supporting module — a read-only,
machine-readable post index per the spec. Does not touch rendering, the manifest writer, or any
consumer-side code (the BGDB vite plugin is planned in the BGDB repo).
**Depends on:** [`../specs/2026-08-18-index-subcommand.md`](../specs/2026-08-18-index-subcommand.md) — all design decisions (D1–D7); this plan does not re-litigate them
**Blocks:** The BGDB-side widget plan ([`../../../backgammondb/docs/specs/2026-08-17-latest-posts-widget.md`](../../../backgammondb/docs/specs/2026-08-17-latest-posts-widget.md) §3), which consumes this command
**Related:** [`../../../backgammondb/docs/specs/2026-08-17-latest-posts-widget.md`](../../../backgammondb/docs/specs/2026-08-17-latest-posts-widget.md) · `src/cress/cli.py` · `src/cress/post.py` · `src/cress/pages.py` · `src/cress/attachments.py`

## Edit Summary

| Date | Changes | Summary |
|------|---------|---------|
| 2026-08-18 | Plan created | Three code tasks (promote path helpers, index module, CLI command) plus documentation |
| 2026-08-18 | 8 fixes | All-unparseable vaults hard-fail, tz-aware sort key, corrected validate precedent, real fixture paths, Task 1 rename ripple, attachment-cache reset, URL-join wording, quoted pytest `-k` |
| 2026-08-18 | Plan complete | Implemented as planned (422 tests green, mypy/ruff clean); minor mechanical deviations only, plus a post-plan BGDB-spec update recording the ship |

The spec settled *what* `index` emits; this plan settles *where the logic lives* and pins the
few remaining plan-level choices. The command is almost entirely assembly of existing pure
functions: `parse_post` (post.py), `plan_slug_writebacks` + `compute_url_path` + `vault_rel_dir`
(post.py), `resolve_attachment` + `plan_attachment` (attachments.py), `pages._post_path` (which
already derives the draft `_drafts/<sha256(slug)[:8]>-<slug>/` token path deterministically),
and the CLI's `_json_envelope` / `_emit_hard_error` machinery. The only new orchestration is a
~60-line loop in a new `src/cress/index.py`, deliberately parallel to `site.build()` steps 3–7
rather than refactored out of it: `build()`'s version applies write-backs and re-parses, while
`index` must stay read-only, so a shared helper would need a mutation flag — more coupling than
the duplication it saves. `index` discovers no plugins and fires no hooks — it is a query, not a
build.

Plan-level decisions (each beat the alternative shown):

- **Empty vault → `ok: true`, empty `posts`, an `empty_vault` warning, exit 0** — zero posts is
  a legitimate answer to a query (a new blog; the BGDB strip renders nothing). Beats `build`'s
  hard `ConfigError`, which is right for a build (nothing to build) but wrong for a question.
  This deliberately diverges from *both* other commands — `validate` also treats `empty_vault`
  as a hard issue and exits 1 (only `missing_date` is soft; `_SOFT_VALIDATE_TYPES`, cli.py) —
  but neither precedent fits a query, which has a well-defined answer for an empty vault.
- **A vault with files but zero parseable posts → hard `ConfigError`, exactly like `build`'s
  "no parseable posts" error** — distinct from the empty vault: files exist and every one is
  broken, so the vault is un-deployable (build will fail) and D6's duplicate-slug reasoning
  applies — fail loudly at the earliest, cheapest place. Lenient emptiness here would let a
  consumer silently render nothing while the whole vault is broken.
- **Human output: one post per line, `<date>  <path>  <title>`, with `-` for a null date and a
  trailing ` [draft]` marker under `--drafts`** — `path` beats `slug` in the listing because it
  shows the prefix and static-mode nesting. Warnings print to stderr in human mode so stdout
  stays the clean listing (in `--json` mode they live in the envelope, as everywhere else).
- **Absolute URL joined inline as `config.site.base_url.rstrip("/") + post_path(post)`** — the
  prefix-less `post_path` form, *not* the record's prefix-relative `path` field, which already
  carries `url_prefix` and would double the prefix (`…/blog/blog/…`). Identical to
  `feeds._canonical`, but two lines; importing another module's private helper or promoting it
  to a shared `urls` module is more machinery than the join is worth.
- **Blog-mode sort key normalises `date` values to timezone-aware `datetime`** (dates become
  UTC midnight; naive datetimes are pinned to UTC) before sorting descending with a slug
  ascending tie-break — Python raises `TypeError` when comparing `date` to `datetime` *and*
  when comparing naive to aware datetimes, and `_parse_date` accepts plain dates, naive
  datetimes, and offset-bearing ISO strings alike, so a vault may legitimately mix all three.
  The normalisation is a small local helper deliberately duplicating `feeds._ensure_tz`'s
  logic — promoting that private helper is more machinery than ~5 lines are worth (same call
  as the URL join above). (`pages._sort_date` and `feeds._require_date` share the latent
  mixed-type issue; fixing them is out of scope.)

**Tech Stack:** Python 3.14, typer, python-frontmatter, pytest. No new dependencies.

---

## Task 1: Promote `pages._post_path` / `_post_url` to public `post_path` / `post_url`

**Status:** Complete

**Files:**
- Modify: `src/cress/pages.py`
- Modify: `src/cress/nav.py` (docstring reference only)
- Modify: `tests/test_pages.py`

The draft token path (`/_drafts/<sha256(slug)[:8]>-<slug>/`) and the prefix application are
single-sourced in these two helpers; `index.py` must reuse them, not re-derive the token. A
public name is the honest signal that another module depends on them.

**Step 1: Write the tests**

In `tests/test_pages.py`, following its existing fixture style:

- `test_post_path_published_is_url_path_wrapped_in_slashes` — a published post with
  `url_path="guides/install"` → `post_path(post) == "/guides/install/"`.
- `test_post_path_draft_carries_sha_token` — a draft with slug `s` →
  `post_path(post) == f"/_drafts/{hashlib.sha256(b's').hexdigest()[:8]}-s/"`.

Prefix application is already covered by the existing `test_post_url_applies_url_prefix`
(tests/test_pages.py:324) — do **not** add a new test under that name; a same-name
redefinition silently shadows the original (ruff F811 would flag it). The rename step below
updates the existing tests to the public names instead.

Run `./.venv/Scripts/pytest.exe tests/test_pages.py -v -k "post_path or post_url"` (quote the
`-k` expression — unquoted, the shell passes `or`/`post_url` as file arguments) — both new
tests must fail via the module failing to collect with `ImportError` (the public names don't
exist yet).

**Step 2: Rename**

Rename `_post_path` → `post_path` and `_post_url` → `post_url` in `pages.py`; update every
internal caller in that module. The ripple extends beyond `pages.py`: update the existing
`_post_url` import and its four call sites in `tests/test_pages.py` (the line 17 import;
`test_blog_post_path_unchanged`, `test_post_path_includes_folder`,
`test_post_url_applies_url_prefix`, `test_post_url_no_prefix_unchanged`), and the docstring
reference in `nav.py:68` (``:func:`cress.pages._post_url` ``). Docstrings stay; add one line
noting `index.py` as a consumer.

**Tests:** the two above, then `tests/test_pages.py`, then the full suite — all green.

**Success criteria:** full suite green; `./.venv/Scripts/mypy.exe --strict src/cress` and
`./.venv/Scripts/ruff.exe check .` clean; no behaviour change anywhere (pure rename).

---

## Task 2: `index.py` — `IndexEntry`, `build_post_index`, JSON serialisation

**Status:** Complete

**Files:**
- Create: `src/cress/index.py`
- Create: `tests/test_index.py`

**Reuses:** `parse_post`, `plan_slug_writebacks`, `compute_url_path`, `vault_rel_dir` (post.py);
`resolve_attachment`, `plan_attachment`, `reset_attachment_cache` (attachments.py); `post_path`
(pages.py, Task 1); `BuildWarning` (reports.py); `DuplicateSlugError`, `ConfigError`
(exceptions.py). New code is the `IndexEntry` dataclass, the orchestration loop, and the
sort/serialise helpers only.

**Step 1: Write the tests**

`tests/test_index.py`, with a `tmp_path` vault/config fixture modelled on `test_cli.py`'s.
Parametrise where a table fits (`pytest.mark.parametrize`):

Record shape and fields:
- `test_entry_has_all_spec_fields` — a fully-specified post yields every field of the spec's
  record (title, slug, path, url, date, updated, summary, author, tags, categories,
  reading_time_minutes, draft, image, image_alt).
- `test_path_is_prefix_relative_and_url_is_absolute` — `base_url: https://x.test/blog` →
  `path == "/blog/a/"`, `url == "https://x.test/blog/a/"`.
- `test_to_json_dict_serialises_dates_iso_and_none_passthrough` — `date`/`updated` become ISO
  strings (a datetime keeps its time component); absent optionals are `None`.

Slug determinism (spec D3):
- `test_slugless_post_gets_promised_slug_without_writeback` — a post with no `slug:` yields the
  `slugify(title)` slug in its entry **and the source file's bytes are unchanged**.
- `test_promised_slug_matches_build` — run `build_post_index`, then `cress(...).build()`, then
  re-parse the post: the written-back slug equals the promised one.

Drafts (spec D5):
- `test_drafts_excluded_by_default`.
- `test_include_drafts_carries_token_path_and_draft_flag` — with `include_drafts=True`, the
  draft's `path` equals `pages.post_path` for it (token form) and `draft` is `True`.

Images (spec D4):
- `test_image_is_hashed_public_url` — an `image:` referencing a real file in `_attachments`
  yields exactly `plan_attachment(...).public_url`, and nothing is written to `output_dir`.
- `test_absolute_image_reference_passes_through` — parametrise `https://…`, `//…`, `/…`,
  `data:…`.
- `test_missing_image_warns_and_nulls` — `missing_hero_image` warning; `image is None`.

Sort (spec D7):
- `test_blog_sort_date_desc_with_slug_tiebreak` — three posts, two sharing a date.
- `test_blog_sort_survives_mixed_date_and_datetime` — one `date:`, one `datetime` frontmatter.
- `test_blog_sort_survives_naive_and_aware_datetimes` — one naive datetime, one offset-bearing
  ISO datetime (`2026-08-14T10:00:00+02:00`); comparing them raw raises `TypeError`.
- `test_static_mode_sorts_by_url_path_and_allows_null_date`.

Leniency and failure (spec D2, D6, plan decisions):
- `test_unparseable_post_warns_and_rest_emitted` — one broken file → `post_parse_error`
  warning, other posts still present.
- `test_empty_vault_returns_empty_with_warning` — no `.md` files → `entries == []`, single
  `empty_vault` warning, no exception.
- `test_all_posts_unparseable_raises_config_error` — `.md` files exist but every one fails to
  parse → `ConfigError` (mirrors `build()`'s "no parseable posts"), not a silent empty list.
- `test_duplicate_slugs_raise` — two slugless posts with the same title →
  `DuplicateSlugError`.

Run `./.venv/Scripts/pytest.exe tests/test_index.py -x` — all must fail with import errors
(module doesn't exist), not typos.

**Step 2: Implement `src/cress/index.py`**

Module docstring per convention (responsibility + pipeline position: "read-only query over the
vault; consumed by `cli.index`; writes nothing"). Contents:

- `@dataclass(frozen=True, slots=True) class IndexEntry` — the spec's record, dates as
  `date | datetime | None`, plus `to_json_dict(self) -> dict[str, Any]` (ISO strings via
  `.isoformat()`, everything else verbatim).
- `@dataclass(frozen=True, slots=True) class IndexResult` — `entries: list[IndexEntry]`,
  `warnings: list[BuildWarning]` (mirrors `BuildResult`'s shape).
- `def build_post_index(vault: Path, config: SiteConfig, *, include_drafts: bool = False) ->
  IndexResult` — explicit dependency injection, no `cress` instance needed:
  1. `reset_attachment_cache()` — mirror `build()`: the `plan_attachment` memo cache is
     module-level, and without the reset a long-lived caller (watcher, test suite) could be
     served stale hashed URLs after an image edit. Then
     `vault_posts_dir = vault / config.vault_subfolder`; missing dir → `ConfigError` (same as
     build — a wrong config is a hard error even for a query).
  2. `sorted(vault_posts_dir.rglob("*.md"))`; empty → `empty_vault` warning, empty result.
  3. Parse leniently: `PostParseError` → `post_parse_error` warning, continue. If files were
     found but *zero* posts parsed, raise `ConfigError("no parseable posts — every file failed
     to parse")` exactly as `build()` does (see plan decisions).
  4. `plan_slug_writebacks(posts, namespace=…)` with the same namespace closure `build()` uses;
     `plan.duplicates` → raise `DuplicateSlugError` with the same message format as `build()`.
     Promised slugs come from the `plan.writebacks` mapping — **never** call
     `apply_slug_writebacks`.
  5. Stamp `url_path` via `compute_url_path` using each post's effective slug.
  6. Filter drafts unless `include_drafts`.
  7. Resolve images: absolute prefixes (`http://`, `https://`, `//`, `/`, `data:`) pass
     through; otherwise `resolve_attachment` → `None` gives a `missing_hero_image` warning and
     `image=None`, else `plan_attachment(resolved, effective_slug, config).public_url`
     (discard the plan's `OutputFile` — nothing is written).
  8. Sort posts: blog mode by normalised timezone-aware datetime descending (dates → UTC
     midnight, naive datetimes → UTC; a local helper mirroring `feeds._ensure_tz`), slug
     ascending tie-break; static mode by `url_path` ascending.
  9. Build entries: `post_path` is prefix-less, so `path = post_url(post, config)` (which is
     `f"{config.url_prefix}{post_path(post)}"`) and
     `url = config.site.base_url.rstrip("/") + post_path(post)`.

**Tests:** the file above, then the full suite.

**Success criteria:** `tests/test_index.py` green; full suite green; `mypy --strict` and `ruff`
clean; `build_post_index` provably writes nothing (the write-back and no-output tests).

---

## Task 3: The `index` CLI command

**Status:** Complete

**Files:**
- Modify: `src/cress/cli.py`
- Modify: `tests/test_cli.py`

**Reuses:** `_resolve_vault_option`, `_CONFIG_OPTION`, `_json_envelope`, `_emit_hard_error`,
the `cress` constructor (existence checks + config load). New code is the command function only.

**Step 1: Write the tests**

In `tests/test_cli.py`, using its existing `fixture` and `CliRunner` pattern:

- `test_cli_index_human_lists_date_path_title` — two posts → two stdout lines, newest first,
  each `<iso-date>  <path>  <title>`.
- `test_cli_index_json_envelope_shape` — `--json` → `version == 1`, `ok is True`,
  `result["posts"]` a list whose first record contains the spec's fields with correct values.
- `test_cli_index_excludes_drafts_by_default` / `test_cli_index_drafts_flag_includes_marked` —
  the draft appears only with `--drafts`, suffixed ` [draft]` in human mode.
- `test_cli_index_duplicate_slugs_exit_1_json_ok_false` — two same-title slugless posts →
  exit 1; with `--json` the envelope has `ok: false` and one error.
- `test_cli_index_empty_vault_exits_0_with_warning` — exit 0, `result["posts"] == []`, one
  `empty_vault` warning in the envelope.
- `test_cli_index_config_option_selects_alternate_config` — mirrors the existing `--config`
  coverage so index composes with multi-site repos.

Run and confirm they fail (unknown command `index`).

**Step 2: Implement**

`@app.command() def index(...)` with `target` / `vault` / `config` options identical to the
other commands, plus `drafts: bool = typer.Option(False, "--drafts", help=…)` and
`json_output`. Body: resolve vault → construct `cress` → `build_post_index(site.vault,
site.config, include_drafts=drafts)` inside the standard `except CressError` →
`_emit_hard_error` wrapper. Output:

- `--json`: `_json_envelope(ok=True, result={"posts": [e.to_json_dict() for e in …]},
  warnings=result.warnings, errors=[])`.
- Human: one line per entry (`-` for a null date, ` [draft]` when `entry.draft`); warnings to
  stderr as `warning: {type}: {file}: {message}`.
- Exit 0 unless a `CressError` was raised (duplicates, config) — warnings never change the
  exit code.

Update the module docstring's "four subcommands" wording to five.

**Tests:** the new tests, then `tests/test_cli.py`, then the full suite.

**Success criteria:** full suite green; `mypy --strict` and `ruff` clean;
`uv run cress index --target tests/fixtures/e2e/vite-manifest/product/
--vault tests/fixtures/e2e/vite-manifest/vault --json` (WSL: `./.venv/Scripts/cress.exe`
equivalent via `python.exe -m cress.cli` if no console script) prints a valid envelope with a
non-empty `posts` array, exit 0. (`tests/fixtures/e2e/product/` does not exist — the
vite-manifest fixture is the only e2e fixture, and its config carries no `vault:` key, so
`--vault` is required.)

---

## Task 4: Update Documentation

**Status:** Complete

- `README.md` — add a `cress index` row to the Commands table ("Emits the post list as
  structured data without building — for host-app integration. `--drafts` includes drafts;
  `--json` for the envelope."). Below the table's `--json` paragraph, add a short "Machine-
  readable post index" subsection: the record's fields, the `path`/`url` distinction, the
  promised-slug guarantee, and a trimmed envelope example.
- `CLAUDE.md` — add `index.py` to the § Module layout tree (`# read-only post index (cress
  index)`), and fix § Running cress against a fixture: it cites
  `tests/fixtures/e2e/product/`, which does not exist — point its three commands at
  `tests/fixtures/e2e/vite-manifest/product/` (with
  `--vault tests/fixtures/e2e/vite-manifest/vault`). No convention changes otherwise.
- `docs/specs/2026-08-18-index-subcommand.md` — already updated at plan-writing time (header
  links this plan); verify no drift with the implemented behaviour, fold any deviation into its
  Edit History.
- The BGDB spec's cross-links were also updated at plan-writing time; nothing further there
  from this repo's side.

---

## Edit History

<!-- Created by /critique on its first pass, or by /complete-task at the end. Newest last. -->

### 2026-08-18 — Critique

**Fixes:**
- **[moderate] Empty-vault justification cited a false precedent** — the plan claimed
  exit-0-with-warning "mirrors `validate`'s soft `empty_vault` handling", but `validate` treats
  `empty_vault` as a hard issue and exits 1 (only `missing_date` is in `_SOFT_VALIDATE_TYPES`).
  The decision stands on its own merits; the bullet now states the divergence from both `build`
  and `validate` explicitly.
- **[moderate] Smoke-test fixture path didn't exist** — Task 3's success criterion ran against
  `tests/fixtures/e2e/product/`, which is not in the repo. Repointed at
  `tests/fixtures/e2e/vite-manifest/product/` with the required `--vault` flag; Task 4 now also
  corrects the same stale path in CLAUDE.md's fixture commands.
- **[moderate] Naive-vs-aware datetime mixing still crashed the blog sort** — normalising dates
  to midnight left `TypeError` reachable on naive-vs-aware comparisons, since `_parse_date`
  accepts offset-bearing ISO strings. The sort key now normalises to timezone-aware UTC
  (mirroring `feeds._ensure_tz`), with a new test.
- **[moderate] All-posts-unparseable was undefined** — the lenient loop would have emitted
  `ok: true` with an empty list while the whole vault is broken. Now a hard `ConfigError`
  mirroring `build()`'s "no parseable posts", per D6's un-deployable-vault reasoning, with a
  test.
- **[minor] Task 1 test name collided with an existing test** — the proposed
  `test_post_url_applies_url_prefix` already exists (tests/test_pages.py:324); a redefinition
  would silently shadow it. Dropped the duplicate — the rename updates the existing tests
  instead — and the rename ripple now explicitly lists the `tests/test_pages.py` import/call
  sites and the `nav.py:68` docstring reference.
- **[minor] `reset_attachment_cache()` was never called** — the `plan_attachment` memo cache is
  module-level and `build()` resets it at start; `build_post_index` now does the same so
  long-lived callers can't be served stale hashed image URLs.
- **[minor] Absolute-URL decision bullet named the wrong variable** — it read
  `base_url.rstrip("/") + path`, but the record's `path` field is prefix-relative and would
  double the prefix; the bullet now names the prefix-less `post_path(post)` that Task 2 step 9
  already used.
- **[minor] Verify-fail pytest command was unquoted and used `-x`** — `-k post_path or
  post_url` splits in the shell, and `-x` stops at the first failure so "all must fail" can't
  be observed in one run. Quoted the expression and dropped `-x` from the verify-fail run.

### 2026-08-18 — Plan complete

- All four tasks executed in order under TDD; full suite 422 green (up from 394),
  `mypy --strict` and `ruff check` clean, smoke test against the vite-manifest fixture passed.
- Mechanical deviations only: Task 2's hero-image resolution runs inline during entry
  construction rather than as a discrete step between draft-filter and sort (behaviourally
  identical — warnings still only for included posts, matching `build`); the
  date-descending/slug-ascending sort is implemented as two stable sorts instead of a single
  composite key.
- Beyond Task 4's scope, at the user's request the BGDB widget spec
  (`../../../../backgammondb/docs/specs/2026-08-17-latest-posts-widget.md`) was updated to
  record that the cress side shipped, including the envelope contract its vite plugin will
  consume.
