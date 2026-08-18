# Spec: `cress index` — machine-readable post index

**Date:** 2026-08-18
**Status:** Direction accepted (decisions D1–D7 below)
**Type:** Spec (what & why) — the implementation plan is [`../plans/completed/2026-08-18-index-subcommand.md`](../plans/completed/2026-08-18-index-subcommand.md) (complete)
**Scope:** A fifth CLI subcommand that emits the vault's post list as structured data without
rendering the site. Covers the CLI shape, the output contract, and its semantics (drafts,
duplicates, static-pages mode). Deliberately leaves out every consumer-side concern — how a host
app ingests the output is the consumer's business.
**Depends on:** [`../../../backgammondb/docs/specs/2026-08-17-latest-posts-widget.md`](../../../backgammondb/docs/specs/2026-08-17-latest-posts-widget.md) — settled the mechanism (its D1–D2): a cress subcommand consumed by a host-app build step
**Blocks:** Nothing — the implementation plan ([`../plans/completed/2026-08-18-index-subcommand.md`](../plans/completed/2026-08-18-index-subcommand.md)) executed this design and is complete
**Related:** [`../../../backgammondb/docs/blog.md`](../../../backgammondb/docs/blog.md) · `src/cress/cli.py` (envelope convention) · `src/cress/post.py` (`plan_slug_writebacks`) · `src/cress/attachments.py` (`plan_attachment`)

## Edit Summary

| Date | Changes | Summary |
|------|---------|---------|
| 2026-08-18 | Spec created | CLI shape, record schema, and semantics settled in brainstorm |
| 2026-08-18 | Plan linked | Implementation plan written (`../plans/2026-08-18-index-subcommand.md`); header links updated |
| 2026-08-18 | Implemented | Human line format settled (`<date>  <path>  <title>`); JSON contract implemented with no drift |

---

## 1. Problem

A host app that embeds a cress blog (BackgammonDB's SPA is the first) has no way to ask cress
"what posts exist?" without building the whole site. The concrete driver is a latest-posts strip
on the BGDB homepage: its build order is fixed at `vite build` → `cress build` (cress consumes
the vite CSS manifest), so nothing cress emits *during* a site build can be consumed at SPA
build time. The SPA build needs the post list *before* cress builds — which today means either
runtime-fetching the site's own RSS (pop-in, client-side XML parsing, invisible in dev) or
duplicating cress's frontmatter/draft/slug logic in a vite plugin.

More generally: any integration surface — a homepage widget, an email digest, a deploy
notification — wants "title, date, URL, summary" as structured data, and cress already computes
all of it but only exposes it as rendered HTML and RSS.

## 2. Findings / constraints

Read from the codebase on 2026-08-18:

- **The slug wrinkle (load-bearing).** A brand-new post has no `slug:` in frontmatter until
  `cress build` writes one back — and `index` runs *before* build in the BGDB pipeline. But
  `plan_slug_writebacks()` (`src/cress/post.py`) is already a pure function: `index` can compute
  the slug a post *will* receive without touching disk, and because it is the same deterministic
  function, the emitted URL is guaranteed to match what build produces later.
- **Image URLs are pure too.** `plan_attachment()` (`src/cress/attachments.py`) derives the
  hashed public URL (`{url_prefix}/assets/{slug}/{sha256[:8]}-{name}`) from file bytes alone;
  disk writes happen separately via the manifest writer. `index` can emit the exact image URL
  build will produce while remaining read-only. Cost: it must read image bytes for posts that
  declare `image:` frontmatter.
- **An output convention already exists.** All four commands emit a
  `{version, ok, result, warnings, errors}` envelope under `--json` and human text without it
  (`src/cress/cli.py`). `build` is lenient (per-post errors become warnings), `validate` is
  strict.
- **Three URL representations exist internally:** `url_path` (site-root-relative, no prefix),
  the prefix-relative form in-site links use (`/blog/my-post/`), and the absolute form RSS and
  the sitemap emit (`feeds.py:_post_url`). Different consumers need different ones.
- **cress is a public, reusable tool.** The feature must be generic — "machine-readable post
  index for integrating a cress blog into a host app" — not a BGDB special case. The consuming
  vite plugin lives in the BGDB repo and is out of scope here.
- **Deploys of the first consumer are atomic** (SPA + blog ship as one `dist/`), so URLs that
  are promises at index time (hashed image assets, new-post pages) are live by the time any
  page embedding them is served.

## 3. Design

A fifth subcommand alongside `build` / `validate` / `serve` / `publish`:

```
cress index [--target DIR] [--vault DIR] [--config FILE] [--drafts] [--json]
```

Config and vault resolve exactly as in the other commands (`_resolve_vault_option`). The
command parses frontmatter for every `*.md` under the vault subfolder, computes final slugs
purely via `plan_slug_writebacks` (never writing back), stamps `url_path` via
`compute_url_path`, resolves hero images purely via `plan_attachment`, sorts, and emits. **No
rendering, no vite-manifest dependency, no disk writes** — it can run before or during a host
app's build.

Without `--json`: a human-readable listing, one post per line (`<date>  <path>  <title>`, with
`-` for a null date and a trailing ` [draft]` marker under `--drafts` — settled in the plan:
`path` beats `slug` because it shows the prefix and static-mode nesting), a free "list my
posts" utility. With `--json`: the standard envelope, with the array at `result.posts`:

```json
{
  "version": 1,
  "ok": true,
  "result": {
    "posts": [
      {
        "title": "Opening rolls, revisited",
        "slug": "opening-rolls-revisited",
        "path": "/blog/opening-rolls-revisited/",
        "url": "https://backgammondb.com/blog/opening-rolls-revisited/",
        "date": "2026-08-14",
        "updated": null,
        "summary": "First 160 chars or frontmatter summary…",
        "author": "Nick",
        "tags": ["study"],
        "categories": [],
        "reading_time_minutes": 3,
        "draft": false,
        "image": "/blog/assets/opening-rolls-revisited/3fa9c2d1-hero.png",
        "image_alt": "Opening position heatmap"
      }
    ]
  },
  "warnings": [],
  "errors": []
}
```

- `path` is prefix-relative (what a same-site consumer embeds in `<a href>`); `url` is absolute
  (what RSS emits; for cross-domain consumers such as digests).
- Dates are ISO 8601 strings as authored (date or datetime); absent optionals are `null`.
- `image` is the content-hashed public URL, or `null` when the post has none or the file is
  missing (warning emitted, mirroring build's `missing_hero_image`). Absolute image references
  (`http(s)://`, `//`, `/`, `data:`) pass through unchanged, as in build.
- Lenient like `build`: an unparseable post becomes a `post_parse_error` warning and the rest
  of the index still emits. Duplicate slugs are the exception — hard failure (D6).
- Sort: blog mode by date descending with a deterministic slug tie-break; static-pages mode by
  `url_path` ascending (each mode mirrors what its own index page already does). `date` may be
  `null` in static mode only, where parsing permits dateless pages.

The first consumer's glue (a vite plugin exposing `virtual:latest-posts`, taking the top two
posts) lives in the BGDB repo and is specified in its
[latest-posts-widget spec](../../../backgammondb/docs/specs/2026-08-17-latest-posts-widget.md).

## 4. Decisions

- **D1 — A read-only `index` subcommand, not an artifact of `build`.** Emitting during build
  can't work for the first consumer (cress runs after vite) and a query command that mutates
  nothing can run safely from any build step, watcher, or script.
- **D2 — Output follows the existing CLI conventions.** Human listing by default, `--json` for
  the `{version, ok, result, warnings, errors}` envelope with `result.posts`; beats the bare
  JSON array the BGDB spec sketched because it keeps all five commands uniform and gives
  lenient-mode warnings a home without corrupting parseable stdout.
- **D3 — Slugs for not-yet-built posts are computed purely by reusing `plan_slug_writebacks`.**
  Same deterministic function build uses, so emitted URLs match the eventual build; beats
  having `index` apply write-backs, because a query command mutating the vault is a surprise
  and would break running it from watchers or parallel builds.
- **D4 — Full record, both URL forms, hashed image URLs.** Every cheap field `parse_post`
  already produces rides along; `path` (prefix-relative) and `url` (absolute) are both emitted
  because both already exist internally and different consumers need different ones; `image`
  reuses `plan_attachment`'s pure hashing so card-style widgets work without a build. Beats the
  minimal five-field record because the extra fields cost nothing and trimming them buys
  nothing.
- **D5 — Drafts excluded by default; `--drafts` opts in.** Opposite default to `build`, because
  `index` feeds production surfaces and the failure mode of an inclusive default is silently
  leaking an unpublished title onto a homepage. `draft` is always present in the record;
  included drafts carry their real `_drafts/…` path.
- **D6 — Duplicate slugs hard-fail, exactly like `build`.** With a collision the `path`/`url`
  fields are ambiguous, and the vault is un-deployable anyway (build will fail); failing loudly
  at index time is the earliest, cheapest place to hear it. Beats lenient dropping, which turns
  a must-fix vault state into a silently shorter list.
- **D7 — Static-pages mode is supported, not special-cased.** The same parse path serves both
  modes; sort follows each mode's own index page. Beats scoping `index` to blog mode, which
  would make the feature less generic for no saving.

## 5. Rejected alternatives

- **Bare JSON array on stdout, warnings on stderr** (the BGDB spec's sketch) — friendlier for
  one-line `jq`, but breaks the envelope convention shared by every other command and splits
  diagnostics across streams; a consumer reads `.result.posts` instead of `.`, which is one
  property access.
- **JSON-only command (no human default)** — simplest, but inconsistent with the other four
  commands, and the human listing is a genuinely useful `ls`-for-posts.
- **`index` applies slug write-backs** — would make emitted slugs "real" instead of promised,
  but a query command mutating source files is a surprise, and purity is what makes `index`
  safe to call from watchers, CI, and parallel builds. Determinism already guarantees the
  promised slug is the real one.
- **Raw frontmatter `image` value, or omitting images** — the raw value is a vault filename
  that's useless without the attachment pipeline; omission was the earlier lean until the pure
  `plan_attachment` reuse turned out to give exact final URLs read-only.
- **Lenient duplicate-slug handling** — keeps consumers alive during authoring, but a homepage
  strip silently missing the newest post is a subtler bug than a loud error, and the vault
  must be fixed before deploy regardless.
- **A `--limit N` flag** — the consumer slices; sorting is pinned, so "top two" is a
  well-defined one-liner downstream. Additive later if a giant vault ever makes it worth it.
- **Fetch-based mechanisms (RSS at runtime, JSON Feed, patching the host's `index.html`)** —
  rejected in the [BGDB spec §5](../../../backgammondb/docs/specs/2026-08-17-latest-posts-widget.md);
  recorded there, not re-litigated here.

## 6. Open questions

- Whether `result` should also carry a small `site` block (`title`, `base_url`, `url_prefix`)
  so consumers don't parse the YAML config themselves — additive, decide when a consumer wants
  it.

## 7. Non-goals

- Rendering anything, reading the vite manifest, or writing any file (including slug
  write-backs) — `index` is a pure query.
- Body content in the output (markdown or HTML) — that's what `build` produces.
- The consumer-side glue (BGDB's vite plugin, virtual module, and hero strip) — specified and
  planned in the BGDB repo.
- A JSON Feed (`feed.json`) for the blog — a worthy separate backlog item, noted in the BGDB
  spec; `index` does not replace or provide it.
- Pagination, filtering by tag/category, or any query language — consumers filter the array.

---

## Edit History

### 2026-08-18 — Spec created

Brainstormed against the BGDB latest-posts-widget spec (2026-08-17), which settled the
mechanism cross-repo. This session settled the cress-side CLI shape (envelope over bare
array), the record schema (full field set, both URL forms, hashed image URLs), and semantics
(pure slug computation, drafts excluded by default, duplicates hard-fail, static-pages mode
supported).

### 2026-08-18 — Implemented

The plan executed with no drift in the JSON contract — the record schema, both URL forms,
promised slugs, hashed image URLs, draft semantics, and sort orders all shipped as specified
(`src/cress/index.py`, the `index` command in `src/cress/cli.py`). The previously open
human-line-format question was settled in the plan and is now recorded in §3: one post per
line as `<date>  <path>  <title>` (`-` for a null date, ` [draft]` marker under `--drafts`),
with warnings on stderr so stdout stays a clean listing. Two edge semantics the spec left
implicit were pinned at plan level: an empty vault is a legitimate answer (`ok: true`, empty
`posts`, an `empty_vault` warning, exit 0), while a vault whose every file fails to parse is a
hard `ConfigError` mirroring `build` (per D6's un-deployable-vault reasoning).
