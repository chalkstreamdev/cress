# Spec: Extra frontmatter fields in `cress index`

- **Date:** 2026-11-16
- **Status:** Planned
- **Type:** Spec (what & why)
- **Plans:**
  - [`../plans/2026-11-16-index-extra-fields.md`](../plans/2026-11-16-index-extra-fields.md) — active
- **Scope:** A site config lists frontmatter field names, and `cress index` adds those fields to every record under one key, `extra`. The spec covers the config key, the record shape, how values become JSON, the warnings, the `validate` check, and the envelope version. It does not cover templates, the human-readable listing, type checks on values, or any consumer-side code.
- **Depends on:**
  - [`2026-08-18-index-subcommand.md`](2026-08-18-index-subcommand.md) — the `cress index` command, its record, and the `{version, ok, result, warnings, errors}` envelope that this spec extends
- **Blocks:**
  - [`../../../backgammondb/docs/specs/2026-11-15-blog-post-announcements.md`](../../../backgammondb/docs/specs/2026-11-15-blog-post-announcements.md) — a post opts into the in-app card with `announce: true`, and the field must reach the Vite plugin through `cress index`
  - [`../../../backgammondb/docs/plans/2026-11-16-blog-post-announcements.md`](../../../backgammondb/docs/plans/2026-11-16-blog-post-announcements.md) — Task 3 reads the config key and the record shape from this spec; Task 4 and the deploy need the cress change
- **Related:**
  - [`../../../backgammondb/docs/marketing/blog.md`](../../../backgammondb/docs/marketing/blog.md) — § Latest-posts widget, the first consumer of `cress index`
  - [`../../../backgammondb/scripts/vite-plugin-latest-posts.mjs`](../../../backgammondb/scripts/vite-plugin-latest-posts.mjs) — the Vite plugin that reads the envelope
  - [`../plugins.md`](../plugins.md) — plugin hooks, which fire during `build` only
  - [`../../README.md`](../../README.md) — § Machine-readable post index and § Configuration, the user-facing docs that change with this feature

## Edit Summary

| Date | Changes | Summary |
|------|---------|---------|
| 2026-11-16 | Spec created | Brainstormed from BackgammonDB's blog post announcements spec. Direction accepted: a list of named fields in `index.extra`, emitted under `extra` on every record with `null` for an unset field, any YAML value with dates as ISO strings, index-only, and no envelope version bump. |
| 2026-11-16 | 6 fixes, 0 skips | Critique. A value that contains itself is unsupported, so a self-referring YAML anchor cannot crash the index. The `validate` check runs before the slug checks. `cress index` warns only for emitted records. Key sorting applies at every depth. Non-string map keys and tuples stay unsupported, with the reasons in § 5. A § 3.6 row names the right keys. |
| 2026-11-16 | Plan written | Implementation plan linked: 2026-11-16-index-extra-fields.md |
| 2026-11-16 | 1 fix | Plan critique. A value nested too deeply for the converter is unsupported, so `RecursionError` cannot crash the index. § 2 records the probe, and § 3.3 lists the case. |

---

## 1. Problem

`cress index --json` emits a fixed set of fields for each post. A custom frontmatter key never reaches the output. A host app that needs a site-specific field therefore has no way to read it without parsing the vault itself.

The first consumer is BackgammonDB. A post opts into an in-app card with `announce: true` in its frontmatter. The BackgammonDB Vite plugin reads `cress index --json` at build time, but the `announce` key is not in the output. The other routes do not work. A tag gets a public page on the blog. A category gets a public page too. A plugin hook fires during `build` only, and the Vite plugin runs `cress index` before `cress build`.

cress is a general-purpose open-source tool. The feature must therefore work for any field and any consumer, not only for `announce`.

## 2. Findings / constraints

All findings were read from the code on 2026-11-16, unless the finding gives another source.

- **The record is a fixed set.** `IndexEntry` in `src/cress/index.py` holds title, slug, path, url, date, updated, summary, author, tags, categories, reading time, draft, image, and image alt. `IndexEntry.to_json_dict` converts its own `date` and `updated` to ISO strings, and nothing else.
- **The data is already at hand.** `parse_post` in `src/cress/post.py` keeps the whole frontmatter mapping as `Post.frontmatter_raw`. `build_post_index` holds every `Post`, so the change needs no new parse step.
- **An old cress ignores a key it does not know.** `load_site_config` in `src/cress/config.py` reads each key with `raw.get`. An older cress therefore accepts a config with a new block and emits nothing extra, with no warning.
- **The envelope version is shared.** `_json_envelope` in `src/cress/cli.py` writes `version: 1` for all five commands. It calls `json.dumps(payload, indent=2, sort_keys=True)` with no `default` argument. BackgammonDB's Vite plugin does not read `version`.
- **The frontmatter parser uses YAML's safe loader.** `python-frontmatter` loads YAML with `CSafeLoader`, or `SafeLoader` when the C loader is missing (`frontmatter/default_handlers.py`). A value can therefore be a string, int, float, bool, null, date, datetime, list, or map. An explicit tag gives a few more types: `!!binary` gives bytes, `!!set` gives a set, and `!!omap` and `!!pairs` give a list of tuples.
- **Some YAML values break `json.dumps`.** A probe on 2026-11-16 (PyYAML `safe_load`, then stdlib `json.dumps`) gave these results:

  | YAML value | Python type | `json.dumps` result |
  |---|---|---|
  | `2026-11-09` | `date` | `TypeError` |
  | `2026-11-09T10:00:00` | `datetime` | `TypeError` |
  | `.nan` | `float` | `NaN` — not valid JSON |
  | `.inf` | `float` | `Infinity` — not valid JSON |
  | `!!binary aGVsbG8=` | `bytes` | `TypeError` |
  | `!!set {a, b}` | `set` | `TypeError` |
  | `{1: one}` | `dict` with an int key | `{"1": "one"}` — the key becomes a string |
  | `{2026-11-09: x}` | `dict` with a date key | `TypeError` |

  A `TypeError` fails the whole envelope. `NaN` and `Infinity` are worse: Python emits them without an error, and then a JavaScript `JSON.parse` in the consumer throws.
- **A YAML anchor can refer to itself.** A second probe on 2026-11-16 loaded `loop: &a [1, *a]` through `python-frontmatter`. The result is a list that contains itself. `json.dumps` raises `ValueError: Circular reference detected`, and a plain recursive walk raises `RecursionError`. Neither error is a `CressError`, so the CLI prints a traceback and no envelope.
- **A value can be nested deeper than a recursive walk can go.** A third probe on 2026-11-16 loaded a list nested 1,200 levels deep through `python-frontmatter`. PyYAML's constructor builds nested values without recursion, so the load succeeds, and `json.dumps` writes the value. A plain recursive walk raises `RecursionError`, because Python's recursion limit is 1,000. At 5,000 levels the load itself fails, and `cress index` reports a `post_parse_error`.
- **The envelope sorts keys at every depth.** `sort_keys=True` sorts the keys of a map inside a value too. The probe gave `{"alpha": 2, "zeta": 1}` for an authored `{zeta: 1, alpha: 2}`.
- **Templates see no custom frontmatter.** `_page_view` in `src/cress/pages.py` builds a fixed dict of built-in fields for each page. `frontmatter_raw` does not reach a template.
- **Plugin hooks fire during `build` only.** All four hooks in `docs/plugins.md` (`before_build`, `after_post`, `before_write`, `after_build`) run inside `build()`. `cress index` runs no hooks.
- **`validate` is strict.** `cress validate` fails on every issue type that is not in `_SOFT_VALIDATE_TYPES` in `src/cress/cli.py`. It parses every post in the vault, drafts included.
- **The first vault carries no custom fields today.** BackgammonDB's blog vault has 17 posts and 11 distinct frontmatter keys. Every key is a built-in field: `title`, `date`, `slug`, `summary`, `author`, `tags`, `categories`, `draft`, `image`, `image_alt`, and `og_image` (counted on 2026-11-16).

## 3. Design

### 3.1 Config

A new `index:` block in the site config holds an `extra` list of frontmatter field names:

```yaml
index:
  # Frontmatter fields that `cress index` adds to every record, under `extra`.
  extra:
    - announce
```

`load_site_config` loads the block into a frozen `IndexConfig` dataclass on `SiteConfig`, with `extra: tuple[str, ...] = ()`. It validates at the boundary:

- `index` must be a mapping.
- `index.extra` must be a list.
- Each item must be a non-empty string.
- No name may appear twice.

A failure raises `ConfigError` with the key path, for example `index.extra[1]: must be a non-empty string`. This is the pattern `extra_stylesheets` uses today. cress ignores unknown keys inside `index:`, as it does everywhere else in the config.

The block affects `cress index` and `cress validate` only. `build`, `serve`, and `publish` read it as part of the config, and do not use it.

### 3.2 Record

Every record gains one key, `extra`. It is a map from each listed name to that field's value:

```json
{
  "title": "Full match analysis",
  "slug": "full-match-analysis",
  "path": "/blog/full-match-analysis/",
  "date": "2026-10-10",
  "extra": { "announce": true },
  "…": "the other built-in fields, unchanged"
}
```

- `extra` is on every record. When the config lists nothing, `extra` is `{}`.
- Every listed name is a key in `extra` on every record. When the post does not set the field, the value is `null`.
- A post that sets a field to `null` and a post that omits it give the same output. A consumer cannot tell the two apart.
- The names in `extra` are separate from the built-in fields. A listed `summary` gives `extra.summary`, which is the authored value or `null`. The built-in `summary` is still the authored value or the summary that cress infers from the body.
- The envelope sorts keys at every depth (§ 2). The order of keys in `extra` therefore carries no meaning, and the order of keys in a map value carries no meaning either. A list keeps its order, so a field that needs an order must be a list.
- Drafts under `--drafts` carry `extra` too. Static-pages mode works the same way as blog mode.

### 3.3 Values

A pure function converts each field's value to a JSON value:

| Input | Output |
|---|---|
| string, int, bool, null | unchanged |
| finite float | unchanged |
| date, datetime | ISO 8601 string (`isoformat()`), as for the built-in `date` |
| list | a list, each item converted |
| map with string keys | a map, each value converted |
| anything else: a non-finite float, bytes, a set, a tuple, a map with a key that is not a string, a value that contains itself, or a value nested too deeply to walk | unsupported |

The function applies at any depth. It tracks the lists and maps on the current path. A list or a map that is already on that path is a value that contains itself (§ 2). The function reports it as unsupported, and does not recurse into it again. A value nested deeper than the function can walk (§ 2) is unsupported too, and its warning names the field. When any part of a field's value is unsupported, the whole field is unsupported. Its value in `extra` is then `null`, and `cress index` adds a warning to the envelope:

```json
{ "type": "unsupported_extra_value", "file": "<post path>", "message": "`extra.score`: NaN cannot be written as JSON" }
```

The post still emits. A partial conversion would change a list or a map without telling the consumer, so the field is `null` as a whole.

`cress index` warns only for the records that it emits. A draft that the run leaves out gives no warning. This is the rule for `missing_hero_image`, which `build_post_index` checks after the draft filter. Without `--json`, the warning goes to stderr with the other warnings, and the listing on stdout does not change.

A consumer cannot tell a YAML date from a string that reads `"2026-11-09"`. Both give the same ISO string, as the built-in `date` does today.

### 3.4 `cress validate`

`cress validate` reads `index.extra` and runs the same conversion over every parsed post. The check runs right after the parse step, before the slug checks. `_run_validate` returns early when it finds a duplicate slug, so a later check would not run. Each unsupported value becomes an `unsupported_extra_value` issue. The type is not in `_SOFT_VALIDATE_TYPES`, so `validate` fails. A strict run in CI therefore catches the value before a consumer sees a `null`.

### 3.5 What does not change

- The envelope keeps `version: 1`.
- The human-readable listing (`cress index` without `--json`) shows no `extra` fields.
- `cress index` stays a pure query. The conversion is a pure function. Only `load_site_config` reads the new config, at the boundary.

### 3.6 Failure and recovery

| Failure | Effect | Recovery |
|---|---|---|
| The consumer runs a cress older than this feature | Records carry no `extra` key. A consumer that checks for it can warn. | Update cress. |
| The config misspells the `index:` key or the `extra:` key (`indexes:`, `extras:`) | Every record has `extra: {}`. A consumer that checks for its field finds it missing and can warn. | Fix the config key. |
| The config misspells a field name (`anounce`) | Every record has `extra.anounce: null` and no `announce` key. A consumer that checks for its field can warn. | Fix the name. |
| `index.extra` is not a list of unique non-empty strings | `ConfigError`. Every command fails, and `cress index --json` emits `ok: false`. | Fix the config. |
| A post sets a value that JSON cannot carry | The field is `null` on that record, with an `unsupported_extra_value` warning. `cress validate` fails. | Fix the frontmatter. |
| A post sets a field to an unexpected type (`announce: "yes"`) | cress passes the value through as written. | The consumer checks the type it needs. |
| The vault is empty | No records, so the consumer cannot check for `extra`. | None needed. With no posts there is nothing to read. |

## 4. Decisions

- **Decision 1 — Index-only.** The fields reach `cress index` and `cress validate`, not templates. A template author owns the vault, so a template would want all the frontmatter, not a listed subset. The argument for a list applies to the JSON output, which other repos depend on. This beat one list that feeds both the index and templates, which ties two features with different needs to one setting.
- **Decision 2 — A list of named fields, not all frontmatter.** The config names each field that reaches the output. This beat a pass-through of all frontmatter. A pass-through puts raw copies of the built-in fields beside the processed ones. It also publishes every private field unless the consumer trims it (see § 5).
- **Decision 3 — The fields sit under one key, `extra`.** A listed name can never clash with a built-in field, now or in a later release. This beat fields at the top level of each record, which makes every built-in name reserved, including names cress adds later. The name follows Zola's `[extra]` table for user-defined frontmatter.
- **Decision 4 — `extra` is on every record, and every listed name is in it.** A field the post does not set is `null`. A consumer can then tell three cases apart: an old cress (no `extra`), a misspelled config (no key for the field), and a vault where no post sets the field (the key is present, and no value is set). BackgammonDB's announcement spec requires this property (its § 3.1). This beat omitting unset fields, which hides a misspelled config from the consumer and gives typed consumers no fixed shape.
- **Decision 5 — Any YAML value, with dates as ISO strings.** Lists and maps pass through at any depth, and dates and datetimes become ISO strings, as the built-in `date` does. This beat scalars only. That limit is arbitrary: lists are a plausible general use, the converter is small, and cress already emits lists for `tags` and `categories`.
- **Decision 6 — An unsupported value becomes `null`, with a per-post warning.** `cress index` stays lenient, like `build` and like the index spec's choice for parse errors. This beat a hard error, where one stray `.nan` in one post would remove the index from every consumer.
- **Decision 7 — `cress validate` reports unsupported values as issues.** This follows the repo rule that `build` is lenient and `validate` is strict. A strict CI run catches the value before it ships as `null`. The check reuses the conversion function from `index`.
- **Decision 8 — The config key is `index.extra`.** The config key matches the record key, and the `index:` block says which command the setting affects. The block follows the `features:` and `git:` pattern. It also gives the open `site` block question in the index spec a home, if a consumer ever asks for it. This beat a top-level key such as `extra_fields` or `frontmatter_fields`, which suggests that templates see the fields.
- **Decision 9 — No envelope version bump.** The change only adds a key to each record, so a consumer of version 1 does not break. `version` belongs to the envelope that all five commands share. A bump would tell every consumer of every command that something broke. A consumer detects the feature from the `extra` key, not from `version`.

## 5. Rejected alternatives

- **Pass all frontmatter through.** It needs no config key and no list. It loses for two reasons:
  - The raw built-in fields would sit beside the processed ones. `frontmatter.image` is a vault filename, which the index spec rejected as useless without the attachment pipeline. `frontmatter.tags` leaves out inline `#tags`. `frontmatter.summary` is `null` when cress infers the summary. Each one is a trap for a consumer that reads the wrong copy. In BackgammonDB's vault today, every one of the 11 keys is a built-in, so a pass-through would emit 11 raw copies and no custom field. To exclude the built-in keys instead makes the boundary move: when cress adds a built-in field, that field leaves the pass-through and breaks the consumers that read it.
  - Obsidian frontmatter often holds data that is not for publication, such as private notes, review status, and data from other plugins. Index output feeds production surfaces. For the same reason, the index spec leaves out drafts by default. A list publishes only what the site owner names.
- **Fields at the top level of each record.** The record reads `.announce`, not `.extra.announce`. Every built-in name then becomes reserved, including names that later releases add. A site that lists `featured` breaks on the upgrade that adds a built-in `featured`. It also needs a rule for names that clash with built-in fields.
- **Scalars only.** It rejects lists and maps for no saving (Decision 5).
- **A hard error for an unsupported value in `cress index`.** One bad value in one post removes the index from every consumer (Decision 6). `cress validate` is the strict path.
- **No conversion: pass each value to `json.dumps` as parsed.** A date raises `TypeError` and fails the envelope. A `.nan` emits `NaN`, which a JavaScript consumer cannot parse (§ 2).
- **Convert a map key that is not a string, and a tuple, as `json.dumps` does.** `json.dumps` turns an int, float, bool, or null key into a string, and a tuple into a list. It loses for two reasons:
  - Two keys can become one. `{1: a, "1": b}` gives two keys that both read `"1"`, and one value is lost without a warning. `true` and `"true"` collide in the same way.
  - A tuple comes only from `!!omap` or `!!pairs`, which an author writes to get an ordered map. The consumer would get a list of pairs, not a map. An author who wants that shape can write a list of lists.
- **Null for the bad part only, inside a list or a map.** It keeps the rest of the value, but it changes a list or a map without telling the consumer. The whole field is `null`, and the warning names it.
- **Omit a field the post does not set.** The record is smaller. But a misspelled config name is then invisible to the consumer, and a typed consumer gets no fixed shape (Decision 4).
- **A top-level config key, such as `extra_fields` or `frontmatter_fields`.** It suggests that templates see the fields, and it does not match the record key (Decision 8).
- **A plugin hook that adds fields to index records.** Hooks fire during `build` only. An index hook would be a larger plugin API for the same result, and every consumer would need to write Python to get a field. A config list needs no code.
- **An envelope version bump.** Nothing breaks, so there is nothing to announce (Decision 9).
- **Templates see the same listed fields.** Rejected in Decision 1.

## 6. Open questions

None that block a plan. The warning type `unsupported_extra_value` and its message are set in § 3.3. The plan may change the message wording.

## 7. Non-goals

- Templates. If a template needs custom frontmatter later, that is a separate feature, probably all frontmatter as `page.frontmatter`, with no list (Decision 1).
- `extra` fields in the human-readable listing.
- Type checks or schemas for extra values. cress passes each value as written, and the consumer checks the type it needs.
- Renaming or aliasing a field on its way to the output.
- `extra` fields in RSS, the sitemap, or JSON-LD.
- Strict checks for unknown keys anywhere in the config.
- Any consumer-side code, BackgammonDB's Vite plugin and card included.

---

## Edit History

### 2026-11-16 — Critique

**Fixes:**
- **[moderate] A self-referring YAML anchor crashes the index** — `loop: &a [1, *a]` loads as a list that contains itself, and a plain recursive converter raises `RecursionError`. That error is not a `CressError`, so `cress index --json` printed a traceback and no envelope. § 2 now records the probe. § 3.3 lists "a value that contains itself" as unsupported, and says the converter tracks the lists and maps on the current path.
- **[minor] A duplicate slug hides the `validate` check** — `_run_validate` returns early when it finds a duplicate slug. § 3.4 now says the check runs right after the parse step, before the slug checks.
- **[minor] The scope of the `cress index` warning was not stated** — The spec did not say whether a draft that the run leaves out still warns. § 3.3 now says the warning is only for emitted records, as for `missing_hero_image`, and that it goes to stderr in the human-readable listing.
- **[minor] Nested maps lose their order** — `sort_keys=True` sorts keys at every depth, but § 3.2 named only the keys of `extra`. § 2 records the probe, and § 3.2 says that the order of keys in a map value carries no meaning and that a list keeps its order.
- **[minor] No reason was recorded for the unsupported keys and tuples** — `json.dumps` stringifies a non-string key and turns a tuple into a list, so conversion was an obvious alternative. § 5 now rejects it: two keys can become one, and `!!omap` would arrive as a list of pairs.
- **[minor] A § 3.6 row named the wrong key** — The row called `extras:` the block key. It now reads "misspells the `index:` key or the `extra:` key".

### 2026-11-16 — Plan critique

**Fixes:**
- **[minor] A deeply nested value crashes the index** — PyYAML builds nested values without recursion, so a 1,200-level nested list loads, and a recursive converter then raises `RecursionError`. That error is not a `CressError`, so `cress index --json` printed a traceback and no envelope. § 2 now records the probe, and § 3.3 lists "a value nested too deeply to walk" as unsupported, with a warning that names the field.
