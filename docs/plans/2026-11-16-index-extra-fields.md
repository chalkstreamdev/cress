# Implementation Plan: Extra frontmatter fields in `cress index`

- **Date:** 2026-11-16
- **Status:** Built — every task done 2026-11-16. cress has no deploy step: BackgammonDB's editable install sees the working tree now, after a Vite restart. Next: Nick reviews and commits, then `/complete-task`.
- **Scope:** The `index.extra` config list, the `extra` map on every `cress index` record, the value converter, the `unsupported_extra_value` warning in `cress index`, and the same check in `cress validate`. The plan does not cover templates, the human-readable listing, or any consumer-side code.
- **Depends on:** Nothing — the `cress index` command that this plan extends shipped with [`completed/2026-08-18-index-subcommand.md`](completed/2026-08-18-index-subcommand.md)
- **Blocks:**
  - [`../../../backgammondb/docs/plans/2026-11-16-blog-post-announcements.md`](../../../backgammondb/docs/plans/2026-11-16-blog-post-announcements.md) — its Task 4 (the browser check) and its deploy need this change in this repo's Windows venv
- **Reviews:** None — the unit tests and the CLI tests verify the config key, the record shape, the warnings, and the `validate` failure on the day. Nothing in this plan is a threshold, a heuristic, or a rate.
- **Related:**
  - [`../specs/2026-11-16-index-extra-fields.md`](../specs/2026-11-16-index-extra-fields.md) — the spec this plan executes: the config key (§ 3.1), the record (§ 3.2), the conversion table and the warning (§ 3.3), the `validate` check (§ 3.4), and Decisions 1 to 9
  - [`../specs/2026-08-18-index-subcommand.md`](../specs/2026-08-18-index-subcommand.md) — the `cress index` record and the `{version, ok, result, warnings, errors}` envelope that this plan extends
  - [`../../README.md`](../../README.md) — § Machine-readable post index and § Configuration
  - [`../../CHANGELOG.md`](../../CHANGELOG.md) — the `[Unreleased]` section

## Edit Summary

| Date | Changes | Summary |
|------|---------|---------|
| 2026-11-16 | Plan created | Four code tasks (the config block, the pure converter, the `extra` field on index records, the `validate` check) and the documentation. `cli.index` does not change. |
| 2026-11-16 | 4 fixes, 0 skips | Critique. A value nested too deeply for the recursive converter is unsupported, so `RecursionError` cannot crash the index. The Step 2 runs leave out `-x`, so every new test shows its failure reason. The docs task covers README § Post frontmatter, the § Commands row for `validate`, and the `_run_validate` docstring. The `validate` drafts test asserts the issue type. |
| 2026-11-16 | Built | Tasks 1 to 5 done. The suite passes (504 tests, up from 432), and mypy and ruff are clean. Task 3 splits the included-draft check into its own test, and its Step 2 filter adds `unsupported or anchor`. |

The spec settles what reaches the output. This plan settles where the code goes. Most of the parts exist. `Post.frontmatter_raw` holds the whole frontmatter mapping, so the change needs no new parse step. `build_post_index` already loops over the emitted posts after the draft filter, and `missing_hero_image` warns from that loop. `BuildWarning` and `_json_envelope` carry the new warning with no change. `_run_validate` already collects issues and fails on every type that is not in `_SOFT_VALIDATE_TYPES`.

The `index` command in `src/cress/cli.py` does not change. It prints every warning in `IndexResult.warnings` to stderr in the human-readable listing, and it puts them in the envelope with `--json`. The listing prints date, path, and title only, so it shows no `extra` fields (spec § 3.5).

The new code is a frozen `IndexConfig` in `config.py`, a `JsonValue` type and an `extra_fields` function in `index.py`, an `extra` field on `IndexEntry`, and four lines in `_run_validate`.

BackgammonDB's Vite plugin runs `../../cress/.venv/Scripts/cress.exe` (`scripts/vite-plugin-latest-posts.mjs`, line 130). That venv holds this repo as an editable install, so the change reaches BackgammonDB when the code is in the working tree. There is no release step. Task 3 is the point where BackgammonDB's dev server starts to see `extra`.

**Tech Stack:** Python 3.14, PyYAML 6.0.3 through python-frontmatter, typer 0.24.1 on click 8.3.2 (its `CliRunner` captures stderr apart from stdout, as `result.stderr`), pytest, mypy 1.20.2, ruff.

**Tooling.** Run the venv tools as CLAUDE.md § WSL/Windows venv quirk says (`./.venv/Scripts/pytest.exe`, `./.venv/Scripts/mypy.exe --strict src/cress`, `./.venv/Scripts/ruff.exe check .`). On 2026-11-16, every `.venv/Scripts/*.exe` call inside the Claude Code Bash sandbox failed with `UtilBindVsockAnyPort:307: socket failed 1`. Run these calls with the sandbox disabled. The Step 2 runs leave out `-x`, so pytest runs every selected test and each failure shows its reason. The Step 4 runs may use `-x`.

**Reuse.** The plan extends `SiteConfig` with a frozen `IndexConfig`, as `FeaturesConfig` and `GitConfig` do. It extends `IndexEntry` and `build_post_index`. It reuses `BuildWarning` for the new warning and `_json_envelope` unchanged. It reads `Post.frontmatter_raw`. New: `extra_fields` and its private helper `_to_json`. No existing function converts a frontmatter value to JSON: `IndexEntry.to_json_dict` converts only its own `date` and `updated`. The converter uses the stdlib only (`math.isfinite`).

### Decisions made while planning

- **The converter lives in `src/cress/index.py`.** Both callers use the `index` record's rules, and `cli.py` already imports `build_post_index` from `cress.index`. This beat a new `cress/extra.py` module, which adds a file for one function pair of about 50 lines.
- **One public function, `extra_fields(post, names) -> tuple[dict[str, JsonValue], list[BuildWarning]]`.** `build_post_index` and `_run_validate` both call it, so the warning type and the message are the same in both commands (spec Decision 7). This beat a public `to_json_value` that each caller wraps, which builds the warning in two places.
- **The recursion raises a private exception, and `extra_fields` catches it once per field.** `_to_json` raises `_UnsupportedValue` with the location and the reason. `extra_fields` turns it into a `null` value and a `BuildWarning`, so nothing is swallowed. This beat a result type that each list step and each map step must check and pass up.
- **Cycle detection uses the ids of the lists and maps on the current path.** `_to_json` passes a `frozenset[int]` down the recursion. A list or a map whose id is already in the set contains itself (spec § 2, the `&a [1, *a]` probe). A value that appears twice but does not contain itself, such as `[*x, *x]`, is still supported. This beat a global "seen" set, which rejects that shared anchor. It also beat a catch of `RecursionError`, which gives no location for the message.
- **A value nested too deeply is unsupported.** PyYAML's constructor builds nested values without recursion. A probe on 2026-11-16 loaded a 1,200-level nested list through `frontmatter.loads`, and `json.dumps` wrote it, but a recursive walk raised `RecursionError` (the limit is 1,000). At 5,000 levels the load itself fails, and `cress index` reports a `post_parse_error`. `extra_fields` therefore catches `RecursionError` for each field and reports it as unsupported, with the field as the location. This beat a fixed depth limit inside `_to_json`, which adds an arbitrary number, and an iterative converter, which is longer for a case that no real post has.
- **`JsonValue` is a recursive PEP 695 alias:** `type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]`. mypy 1.20.2 accepts it under `--strict` (checked on 2026-11-16). `IndexEntry.extra` is `dict[str, JsonValue]`. This beat `dict[str, Any]`, which CLAUDE.md allows only with a comment. `IndexEntry.to_json_dict` keeps its `dict[str, Any]` return type.
- **The message names the path to the bad part.** The form is `` `<location>`: <reason> ``. The location starts as `extra.<name>`. A list step adds `[i]`, and a map step adds `.<key>`: `` `extra.links[1].href`: NaN cannot be written as JSON ``. The spec's example, `` `extra.score`: NaN cannot be written as JSON ``, is the top-level case of this form, so spec § 3.3 needs no change. This beat a message that names only the field, where an author with a long list must search for the bad item.
- **The reasons are these five:**
  - a non-finite float: `NaN cannot be written as JSON`, `Infinity cannot be written as JSON`, or `-Infinity cannot be written as JSON` — the token that Python would write
  - a map key that is not a string: `map key 1 (int) is not a string`, with `str(key)` and the type name
  - a list or a map that contains itself: `the value contains itself`
  - a value nested deeper than the converter can walk: `the value is nested too deeply`, at the location `extra.<name>`
  - every other type (bytes, a set, a tuple, and any type the safe loader can give later): `<type name> cannot be written as JSON`, for example `bytes cannot be written as JSON`
- **A `null` `index:` or a `null` `index.extra:` is a `ConfigError`.** `features:` and `extra_stylesheets:` behave the same way today. A list whose items are all commented out loads as `null`, so it fails too. This beat a rule that treats `null` as empty for this block only, which a site owner cannot predict from the other keys.
- **A name must be a non-empty string, and names match frontmatter keys exactly.** `""` fails. The loader does not strip or fold the case of a name, because YAML keys are case-sensitive.
- **The `validate` check runs over every parsed post, right after the `if not posts: return issues` line.** It runs before the static-pages `missing_date` loop and before `plan_slug_writebacks`. The duplicate-slug branch returns early, so a later check would not run (spec § 3.4).
- **The converter tests use in-memory `Post` objects, and the YAML tests use real files.** `tests/test_pages.py` and `tests/test_feeds.py` build `Post` directly with `frontmatter_raw={}`, so the converter tests do the same and can build a cyclic value in Python. The tests in Task 3 write real frontmatter, so they pin the spec's § 2 probe table against the real loader.

---

## Task 1: `index.extra` in the site config

**Status:** Complete 2026-11-16

**Files:**
- Modify: `src/cress/config.py`
- Modify: `tests/test_config.py`

**Step 1: Write the tests.** In `tests/test_config.py`. The tests read `config.index.extra` and do not import `IndexConfig`, so the first run fails on the missing attribute, not on an import.

- `test_index_extra_defaults_to_empty_tuple` — `MINIMAL_CONFIG` loads with `config.index.extra == ()`.
- `test_index_extra_list_preserved_in_order` — `index:\n  extra:\n    - announce\n    - featured\n` gives `("announce", "featured")`.
- `test_index_unknown_key_ignored` — `index:\n  sitemap: true\n` loads, with `config.index.extra == ()`.
- `test_full_config_round_trips_every_field` — `FULL_CONFIG` gains `index:\n  extra:\n    - announce\n`, and the test gains `assert config.index.extra == ("announce",)`.
- `test_index_config_invalid_raises(body, message)`, parametrized. Each body is appended to `MINIMAL_CONFIG`, and the test asserts `message in str(exc.value)`:

  | Body | Message |
  |---|---|
  | `index: [announce]` | `index: must be a mapping` |
  | `index:` (null) | `index: must be a mapping` |
  | `index:\n  extra: announce` | `index.extra: must be a list` |
  | `index:\n  extra:` (null) | `index.extra: must be a list` |
  | `index:\n  extra:\n    - announce\n    - 42` | `index.extra[1]: must be a non-empty string` |
  | `index:\n  extra:\n    - ""` | `index.extra[0]: must be a non-empty string` |
  | `index:\n  extra:\n    - announce\n    - announce` | `index.extra[1]: duplicate name 'announce'` |

**Step 2: See them fail.** Run `./.venv/Scripts/pytest.exe tests/test_config.py -k index -v`. The default test fails with `AttributeError: 'SiteConfig' object has no attribute 'index'`. The invalid-config cases fail with `DID NOT RAISE`.

**Step 3: Implement.** In `src/cress/config.py`:

- Add `IndexConfig` beside `FeaturesConfig` and `GitConfig`: `@dataclass(frozen=True, slots=True)`, docstring "The `index:` block — settings for `cress index` and `cress validate`", one field `extra: tuple[str, ...] = ()` with a comment that it lists the frontmatter field names that `cress index` adds to every record under `extra`.
- Add `index: IndexConfig = field(default_factory=IndexConfig)` to `SiteConfig`, after `extra_stylesheets`. The comment says that `build`, `serve`, and `publish` read the block and do not use it.
- In `load_site_config`, after the `git:` block, read `index_raw = raw.get("index", {})`. Raise `ConfigError("index: must be a mapping")` when it is not a `dict`. Build `IndexConfig(extra=_as_field_names(index_raw.get("extra", []), "index.extra"))`, and pass it to `SiteConfig(index=...)`.
- Add `_as_field_names(value: Any, key: str) -> tuple[str, ...]` beside the other `_as_*` helpers. It raises `f"{key}: must be a list"` for a value that is not a `list`, `f"{key}[{idx}]: must be a non-empty string"` for an item that is not a `str` or is `""`, and `f"{key}[{idx}]: duplicate name {item!r}"` for a repeated item. It returns the names as a tuple in their order.

**Step 4: Green.** Run the single tests, then `tests/test_config.py`, then the full suite. Run `./.venv/Scripts/mypy.exe --strict src/cress` and `./.venv/Scripts/ruff.exe check .`.

**Tests:** the five tests above.

**Success criteria:** the full suite passes, mypy and ruff are clean, and a config with no `index:` block loads with `config.index == IndexConfig()`. No command uses the block yet.

---

## Task 2: The value converter

**Status:** Complete 2026-11-16

**Files:**
- Modify: `src/cress/index.py`
- Modify: `tests/test_index.py`

**Step 1: Write the tests.** In `tests/test_index.py`, a new section `# --- extra field conversion (extra-fields spec § 3.3) ---`. Import `math`, `extra_fields` from `cress.index`, `Post` from `cress.post`, and `BuildWarning` from `cress.reports`. Add a helper:

```python
def _post_with(frontmatter: dict[str, object]) -> Post:
    return Post(
        source_path=Path("vault/a.md"),
        title="A",
        date=_dt.date(2026, 11, 9),
        body_md="",
        frontmatter_raw=frontmatter,
    )
```

- `test_extra_fields_converts_supported_value(value, expected)`, parametrized. The test asserts `extra_fields(_post_with({"v": value}), ("v",)) == ({"v": expected}, [])`:

  | Value | Expected |
  |---|---|
  | `"text"` | `"text"` |
  | `3` | `3` |
  | `True` | `True` |
  | `None` | `None` |
  | `1.5` | `1.5` |
  | `_dt.date(2026, 11, 9)` | `"2026-11-09"` |
  | `_dt.datetime(2026, 11, 9, 10, 0)` | `"2026-11-09T10:00:00"` |
  | `_dt.datetime(2026, 11, 9, 10, 0, tzinfo=_dt.timezone(_dt.timedelta(hours=2)))` | `"2026-11-09T10:00:00+02:00"` |
  | `[1, _dt.date(2026, 11, 9)]` | `[1, "2026-11-09"]` |
  | `{"a": {"b": [_dt.date(2026, 11, 9)]}}` | `{"a": {"b": ["2026-11-09"]}}` |
  | `[]` | `[]` |
  | `{}` | `{}` |

- `test_extra_fields_unset_name_is_null` — `extra_fields(_post_with({}), ("missing",)) == ({"missing": None}, [])`.
- `test_extra_fields_no_names_gives_empty_map` — `extra_fields(_post_with({"v": 1}), ()) == ({}, [])`.
- `test_extra_fields_unsupported_value_nulls_field_and_warns(value, message)`, parametrized. The test asserts that the values are `{"v": None}` and the warnings are `[BuildWarning(type="unsupported_extra_value", file=str(Path("vault/a.md")), message=message)]`:

  | Value | Message |
  |---|---|
  | `math.nan` | `` `extra.v`: NaN cannot be written as JSON `` |
  | `math.inf` | `` `extra.v`: Infinity cannot be written as JSON `` |
  | `-math.inf` | `` `extra.v`: -Infinity cannot be written as JSON `` |
  | `b"hello"` | `` `extra.v`: bytes cannot be written as JSON `` |
  | `{"a", "b"}` | `` `extra.v`: set cannot be written as JSON `` |
  | `("a", 1)` | `` `extra.v`: tuple cannot be written as JSON `` |
  | `{1: "one"}` | `` `extra.v`: map key 1 (int) is not a string `` |
  | `{_dt.date(2026, 11, 9): "x"}` | `` `extra.v`: map key 2026-11-09 (date) is not a string `` |
  | `[1, math.nan]` | `` `extra.v[1]`: NaN cannot be written as JSON `` |
  | `{"links": [{"href": math.nan}]}` | `` `extra.v.links[0].href`: NaN cannot be written as JSON `` |

- `test_extra_fields_value_that_contains_itself_is_unsupported(kind)`, parametrized over a list (`loop = [1]; loop.append(loop)`, message `` `extra.v[1]`: the value contains itself ``) and a map (`loop = {}; loop["self"] = loop`, message `` `extra.v.self`: the value contains itself ``). The test asserts the `null` value and the one warning.
- `test_extra_fields_value_nested_too_deeply_is_unsupported` — a list nested `2 * sys.getrecursionlimit()` levels deep, built in a loop (`deep = [deep]`). The test asserts the `null` value and the one warning, with the message `` `extra.v`: the value is nested too deeply ``.
- `test_extra_fields_shared_value_is_not_a_cycle` — `shared = [1]`; the value `[shared, shared]` gives `[[1], [1]]` and no warning.
- `test_extra_fields_bad_field_leaves_other_fields` — frontmatter `{"good": 1, "bad": math.nan}` with names `("good", "bad")` gives `{"good": 1, "bad": None}` and one warning.

**Step 2: Add the signature and see the tests fail.** Add the `JsonValue` alias and `extra_fields` with its signature, its docstring, and a body of `raise NotImplementedError`. Run `./.venv/Scripts/pytest.exe tests/test_index.py -v`. Each new test fails with `NotImplementedError`, and the rest of `tests/test_index.py` passes.

**Step 3: Implement.** In `src/cress/index.py`:

- `type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]`, with a comment that it is the set of values that `json.dumps` writes as valid JSON.
- `class _UnsupportedValue(Exception)`, whose `__init__(self, location: str, reason: str)` calls `super().__init__(f"`{location}`: {reason}")`. The docstring says that `_to_json` raises it and `extra_fields` catches it.
- `extra_fields(post: Post, names: tuple[str, ...]) -> tuple[dict[str, JsonValue], list[BuildWarning]]`. For each name in order, it converts `post.frontmatter_raw.get(name)` with `_to_json(value, f"extra.{name}", frozenset())`. On `_UnsupportedValue`, it sets the value to `None` and appends `BuildWarning(type="unsupported_extra_value", file=str(post.source_path), message=str(exc))`. On `RecursionError`, it does the same with `_UnsupportedValue(f"extra.{name}", "the value is nested too deeply")`. A comment says why: PyYAML builds nested values without recursion, so a value can load that the recursive walk cannot convert. The docstring states the inputs, the outputs, and that the function is pure.
- `_to_json(value: object, location: str, on_path: frozenset[int]) -> JsonValue`, as a `match`:
  - `None | bool() | int() | str()` returns the value.
  - `float()` returns the value when `math.isfinite(value)`. Otherwise it raises with `NaN`, `Infinity`, or `-Infinity` (from `math.isnan` and the sign).
  - `_dt.date()` returns `value.isoformat()`. This case also matches a `datetime`, which is a subclass of `date`.
  - `list() | dict()` whose `id(value)` is in `on_path` raises `the value contains itself`.
  - `list()` converts each item with the location `f"{location}[{i}]"` and the set `on_path | {id(value)}`.
  - `dict()` raises `f"map key {key} ({type(key).__name__}) is not a string"` for a key that is not a `str`. It converts each value with the location `f"{location}.{key}"` and the set `on_path | {id(value)}`.
  - `_` raises `f"{type(value).__name__} cannot be written as JSON"`.
- The module docstring gains one sentence: `extra_fields` converts the frontmatter fields that `index.extra` lists, and `cress validate` in `cress.cli` calls it too.

**Step 4: Green.** Run the single tests, then `tests/test_index.py`, then the full suite, mypy, and ruff.

**Tests:** the eight tests above.

**Success criteria:** the full suite passes, and mypy and ruff are clean. `extra_fields` exists, and no command calls it yet.

---

## Task 3: `extra` on every index record

**Status:** Complete 2026-11-16. Two changes from the steps below. `test_extra_warning_skips_excluded_draft` is two tests, one assertion each: `test_extra_warning_skips_excluded_draft` (it passes before the change, and that is correct) and `test_extra_warning_covers_included_draft`. The Step 2 filter missed three CLI tests whose names do not contain `extra`, so the command now adds `unsupported or anchor`.

**Files:**
- Modify: `src/cress/index.py`
- Modify: `tests/test_index.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the tests.** In `tests/test_index.py`, `_set_up_site` gains a keyword argument `extra: tuple[str, ...] = ()`. When it is not empty, the helper appends `index:\n  extra:\n` and one `    - <name>\n` line per name to the config text. Add a section `# --- extra fields on records (extra-fields spec § 3.2) ---`:

- `test_extra_is_empty_map_when_config_lists_nothing` — `entry.extra == {}`, and `entry.to_json_dict()["extra"] == {}`.
- `test_extra_carries_listed_value` — `extra=("announce",)` and a post with `announce: true` give `entry.extra == {"announce": True}`.
- `test_extra_unset_and_explicit_null_give_same_value` — two posts, one with `announce: null` and one without `announce`. Both give `{"announce": None}`.
- `test_extra_listed_builtin_name_is_the_authored_value` — `extra=("summary",)` and a post with no `summary:` give `entry.extra == {"summary": None}`, while `entry.summary` is the summary inferred from the body.
- `test_extra_yaml_value_converts(yaml_value, expected)`, parametrized over real frontmatter lines for a field `score`:

  | Frontmatter | Expected |
  |---|---|
  | `score: 2026-11-09` | `"2026-11-09"` |
  | `score: 2026-11-09T10:00:00+02:00` | `"2026-11-09T10:00:00+02:00"` |
  | `score: [a, b]` | `["a", "b"]` |
  | `score: {zeta: 1, alpha: 2}` | `{"zeta": 1, "alpha": 2}` |
  | `x: &x [1]` and `score: [*x, *x]` | `[[1], [1]]` |

- `test_extra_unsupported_yaml_value_warns_and_nulls(yaml_value)`, parametrized over `score: .nan`, `score: .inf`, `score: !!binary aGVsbG8=`, `score: !!set {a, b}`, `score: !!omap [{a: 1}]`, `score: {1: one}`, `score: {2026-11-09: x}`, `score: &a [1, *a]`, and a list nested 1,200 levels deep (`"score: " + "[" * 1200 + "1" + "]" * 1200`, which loads, per the 2026-11-16 probe). Each gives one emitted entry with `extra == {"score": None}`, and warning types `["unsupported_extra_value"]`.
- `test_extra_warning_skips_excluded_draft` — a draft with `score: .nan` and a live post. The default run gives no warning. A run with `include_drafts=True` gives one `unsupported_extra_value` warning, and the draft's entry has `extra == {"score": None}`.
- `test_extra_in_static_pages_mode` — `static_pages=True` and `extra=("announce",)` give `entry.extra == {"announce": True}` for a dateless page.

In `tests/test_cli.py`, add a constant `_INDEX_EXTRA = "index:\n  extra:\n    - announce\n    - score\n"`, which each test appends to `_CONFIG`. Add a helper `_reject_constant(name: str) -> None` that raises `ValueError(f"non-JSON constant {name}")`.

- `test_cli_index_json_record_carries_extra` — a post with `announce: true` gives `record["extra"] == {"announce": True, "score": None}`, and `payload["version"] == 1`.
- `test_cli_index_json_unsupported_value_is_valid_json` — a post with `score: .nan` exits 0. `json.loads(result.stdout, parse_constant=_reject_constant)` succeeds, `payload["ok"] is True`, `record["extra"]["score"] is None`, and the warning types are `["unsupported_extra_value"]`. The `parse_constant` hook makes the test fail on `NaN`, which Python's `json.loads` accepts by default and a JavaScript `JSON.parse` does not.
- `test_cli_index_json_self_referring_anchor_emits_envelope` — a post with `score: &a [1, *a]` exits 0 and emits a parseable envelope with `ok: true` and one `unsupported_extra_value` warning.
- `test_cli_index_human_unsupported_value_warns_on_stderr` — a post with `score: .nan`, without `--json`. `result.stdout.splitlines() == ["2026-08-14  /a/  A"]`, and `"unsupported_extra_value" in result.stderr`.
- `test_cli_index_invalid_extra_config_json_ok_false` — `_CONFIG + "index:\n  extra: announce\n"` exits 1, with `payload["ok"] is False` and `payload["errors"][0]["type"] == "ConfigError"`.
- `test_cli_build_ignores_index_block` — `cress build` with `_INDEX_EXTRA` and a post with `score: .nan` exits 0. The block does not affect `build` (spec § 3.1).

**Step 2: See them fail.** Run `./.venv/Scripts/pytest.exe tests/test_index.py tests/test_cli.py -k "extra or index_block or unsupported or anchor" -v`. The record tests fail with `AttributeError` on `entry.extra` or `KeyError: 'extra'`. The warning tests fail because no warning is emitted. `test_cli_index_invalid_extra_config_json_ok_false` and `test_cli_build_ignores_index_block` pass already, because Task 1 built the config. That is correct: they pin the contract for this task.

**Step 3: Implement.** In `src/cress/index.py`:

- `IndexEntry` gains a last field `extra: dict[str, JsonValue]`. The class docstring says that `extra` holds the fields that `index.extra` lists.
- `to_json_dict` adds `"extra": self.extra`.
- In the entries loop of `build_post_index`, before `IndexEntry(...)`, call `extra, extra_warnings = extra_fields(post, config.index.extra)` and `warnings.extend(extra_warnings)`. Pass `extra=extra` to `IndexEntry`. The loop runs after the draft filter, so an excluded draft gives no warning (spec § 3.3).
- The `build_post_index` docstring gains one sentence: an unsupported extra value becomes `null` with an `unsupported_extra_value` warning.

**Step 4: Green.** Run the single tests, then `tests/test_index.py` and `tests/test_cli.py`, then the full suite, mypy, and ruff. The existing `test_cli_index_human_lists_date_path_title` and `test_cli_index_json_envelope_shape` must stay green unchanged.

**Tests:** the eight `test_index.py` tests and the six `test_cli.py` tests above.

**Success criteria:** the full suite passes, and mypy and ruff are clean. `cress index --json` emits `extra` on every record, and the envelope keeps `version: 1`.

---

## Task 4: `cress validate` reports unsupported values

**Status:** Complete 2026-11-16

**Files:**
- Modify: `src/cress/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the tests.** In `tests/test_cli.py`, with `_INDEX_EXTRA` from Task 3. Every post sets `slug:`, so `missing_slug` does not fail the run, except in the duplicate-slug test.

- `test_cli_validate_fails_on_unsupported_extra_value` — a post with `score: .nan` exits 1, and `"unsupported_extra_value" in result.stdout`.
- `test_cli_validate_json_lists_unsupported_extra_value` — the same post with `--json` gives `payload["ok"] is False`, and `"unsupported_extra_value"` is in the warning types.
- `test_cli_validate_passes_with_supported_extra_values` — a post with `score: 3` exits 0, and the last line of stdout is `0 issue(s)`.
- `test_cli_validate_ignores_unlisted_field` — `_CONFIG` with no `index:` block and a post with `score: .nan` exits 0. Only listed fields are checked.
- `test_cli_validate_reports_unsupported_value_despite_duplicate_slugs` — two posts with the same title and no `slug:`, one with `score: .nan`. stdout contains `duplicate_slug` and `unsupported_extra_value`.
- `test_cli_validate_checks_drafts_for_unsupported_values` — a draft with `score: .nan` exits 1, and `"unsupported_extra_value" in result.stdout`. `validate` parses every post, drafts included.

**Step 2: See them fail.** Run `./.venv/Scripts/pytest.exe tests/test_cli.py -k validate -v`. The two failure tests, the duplicate-slug test, and the drafts test fail because `validate` exits 0 or reports no `unsupported_extra_value`. `test_cli_validate_passes_with_supported_extra_values` and `test_cli_validate_ignores_unlisted_field` pass already, and that is correct: they pin what must not change.

**Step 3: Implement.** In `src/cress/cli.py`:

- Import `extra_fields` with `build_post_index` from `cress.index`.
- In `_run_validate`, right after `if not posts: return issues`, add a loop over `posts` that calls `extra_fields(post, site.config.index.extra)` and extends `issues` with its warnings. A comment says that the check runs before the slug checks because the duplicate-slug branch returns early.
- The `_run_validate` docstring names the new check: it reads "Parse every post, check the `index.extra` values, plan slugs, resolve wikilinks — collect issues without writing output."
- `_SOFT_VALIDATE_TYPES` does not change, so `unsupported_extra_value` fails the run.

**Step 4: Green.** Run the single tests, then `tests/test_cli.py`, then the full suite, mypy, and ruff.

**Tests:** the six tests above.

**Success criteria:** the full suite passes, and mypy and ruff are clean. `cress validate` exits 1 on a listed field with a value that JSON cannot carry, in a draft too, and with a duplicate slug in the same vault.

---

## Task 5: Update Documentation

**Status:** Complete 2026-11-16. Beyond the steps: the BackgammonDB plan's `Status` line, its Task 4 `Status` line, and its Edit Summary also record that the cress change is built. A real `cress index --config .cress/blog.config.yaml --json` run in BackgammonDB gave `extra: {"announce": null}` on all 16 live posts, `ok: true`, `version: 1`, and no warnings, and `cress validate` reported 0 issues.

- `README.md` § Machine-readable post index — add `"extra": { "announce": true }` to the JSON example record, after `image_alt`. Add a paragraph after the example's explanation. `extra` holds the frontmatter fields that `index.extra` names, on every record. Every listed name is a key, with `null` when the post does not set the field or sets it to `null`. Dates and datetimes become ISO 8601 strings. Lists and maps pass through at any depth, and the envelope sorts map keys, so only a list keeps an order. A value that JSON cannot carry becomes `null`, with an `unsupported_extra_value` warning, and `cress validate` fails on it. The envelope stays at `version: 1`: a consumer detects the feature from the `extra` key. Templates do not see these fields.
- `README.md` § Configuration — add the `index:` block to the schema, after `git:`, with a comment: "Frontmatter fields that `cress index` adds to every record, under `extra`. Only `index` and `validate` use them."
- `README.md` § Post frontmatter — add one sentence after the paragraph under the example: cress ignores other keys, except that `cress index` emits the keys that `index.extra` lists, under `extra` (link § Machine-readable post index).
- `README.md` § Commands — the `cress validate` row gains: "Fails on a value in an `index.extra` field that JSON cannot carry."
- `src/cress/cli.py` `_run_validate` docstring — Task 4 updates it. No further change.
- `CHANGELOG.md` — under `## [Unreleased]`, add `### Added` with one entry: the `index.extra` config list, the `extra` map on every `cress index` record, the `unsupported_extra_value` warning, and the `cress validate` check. Say that the envelope version does not change.
- `src/cress/index.py` module docstring — Task 2 updates it. No further change.
- `docs/plugins.md` — no change. `cress index` still fires no hooks.
- [`../specs/2026-11-16-index-extra-fields.md`](../specs/2026-11-16-index-extra-fields.md) — no change while the warning text matches § 3.3. If execution changes the message form, update the § 3.3 example and add an Edit Summary row. `/complete-task` sets the spec's `Status` and the `Plans` bullet.
- [`../../../backgammondb/docs/plans/2026-11-16-blog-post-announcements.md`](../../../backgammondb/docs/plans/2026-11-16-blog-post-announcements.md) — when Task 4 here is done, edit that plan's `Depends on` bullet for this plan to say that the cress change is in the working tree, so its Task 4 can start. Ask Nick to restart Vite first: the Vite plugin runs cress at `buildStart` only.

**Success criteria:** each doc above reads true against the code. `README.md` has no `**Date:**` line, so there is no date to bump.

---

## Edit History

### 2026-11-16 — Critique

**Fixes:**
- **[minor] A deeply nested value crashes the index** — PyYAML builds nested values without recursion, so a 1,200-level nested list loads, and the recursive `_to_json` then raises `RecursionError`. That error is not a `CressError`, so `cress index --json` printed a traceback and no envelope. A new decision makes such a value unsupported: `extra_fields` catches `RecursionError` for each field and warns with `` `extra.<name>`: the value is nested too deeply ``. Task 2 and Task 3 each gain a test, and spec § 2 and § 3.3 record the case.
- **[minor] The Step 2 runs stopped at the first failure** — With `-x`, Task 3's run stopped inside `tests/test_index.py` and never showed the `tests/test_cli.py` failures that it claims. The four Step 2 commands now leave out `-x`, and the Tooling paragraph says why. Task 2's run covers the whole module, so it also shows that the rest of `tests/test_index.py` passes.
- **[minor] The docs task missed three places** — README § Post frontmatter said nothing about custom keys, the § Commands row for `validate` did not name the new check, and the `_run_validate` docstring did not change. Task 5 now covers the two README places, and Task 4 updates the docstring.
- **[minor] The `validate` drafts test asserted only the exit code** — A fixture mistake, such as a missing `slug:`, also exits 1. The test now asserts `unsupported_extra_value` in stdout too.
