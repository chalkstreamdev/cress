# cress

Publish an Obsidian vault to a static HTML blog that lives under a product repo's `/blog` path. No runtime, no server — just HTML files the product's existing static host can serve.

## Install

```bash
uv add cress
# or inside the cress repo itself:
uv sync
```

cress targets Python 3.14.

## Quickstart

1. **Tell cress where your vault lives.** cress resolves the vault path from the first source available, in this order:

   1. `--vault` on the command line
   2. `vault:` in the user config (`~/.config/cress/config.yaml`)
   3. `vault:` in the site config (`<target>/.cress/config.yaml`)
   4. the `CRESS_VAULT` environment variable

```yaml
# ~/.config/cress/config.yaml
vault: /Users/me/Obsidian/Main
```

   Setting `vault:` in the **site config** is what makes a synced-drive,
   multi-machine setup zero-config: the path travels with the repo, so a second
   machine that shares the same repos+vault tree needs no per-user setup. A
   relative `vault:` there is resolved against the target repo (e.g. `../Vault`).

2. **Add `.cress/config.yaml` to your product repo**:

```yaml
vault_subfolder: "Blogs/MyProduct"
output_dir: "public/blog"

site:
  title: "My Product Blog"
  description: "Shipping notes and deep dives."
  base_url: "https://myproduct.com/blog"
```

3. **Build** (from the product repo root — `--target` defaults to the current directory):

```bash
uv run cress build
```

4. **Publish** (commits `public/blog` in the product repo; pushes if `git.auto_push: true`):

```bash
uv run cress publish
```

5. **Live-reload while writing**:

```bash
uv run cress serve --live-reload
```

## Commands

| Command | What it does |
| --- | --- |
| `cress build` | Renders the vault into `<output_dir>`. Continues past per-post errors (they surface as warnings). |
| `cress validate` | Parses every post without writing. Exits non-zero on any issue. `--fix` writes missing slugs. |
| `cress serve` | Builds once, serves `<output_dir>` on localhost, rebuilds on source changes. `--live-reload` reloads the browser. |
| `cress publish` | Builds, stages `<output_dir>` in the target repo, commits with the configured prefix, and optionally pushes. |

Every command accepts `--config PATH` to build from an alternate config file (default `<target>/.cress/config.yaml`) — this is how one product repo hosts both a blog and a docs site (see [Static pages mode](#static-pages-mode)).

Every command accepts `--json` for a machine-readable envelope:

```json
{
  "version": 1,
  "ok": true,
  "result": {"pages_written": 42, "duration_ms": 312, "skipped_posts": 0},
  "warnings": [],
  "errors": []
}
```

## Configuration

The full `.cress/config.yaml` schema:

```yaml
# Required
vault_subfolder: "Blogs/MyProduct"   # relative to the vault root
output_dir: "public/blog"             # relative to the target repo

# Optional — vault location fallback (see Quickstart step 1 for the full
# resolution order). A relative path is resolved against this repo.
vault: "../Vault"

site:
  title: "My Blog"
  description: "Fallback meta description"
  base_url: "https://myproduct.com/blog"
  locale: "en_US"
  twitter_handle: "@myproduct"
  default_image: "og-default.png"

# Optional
template_dir: "blog-templates"
assets_dir: "public/blog/assets"     # must live under output_dir
attachments_subfolder: "_attachments"
paginate: 10
default_author: "Author"
static_pages: false                   # true → evergreen docs mode (see below)

templates:
  base: "templates/blog-base.html"

shortcodes:
  youtube: "templates/shortcodes/youtube.html"

features:
  rss: true
  rss_count: 20
  sitemap: true
  syntax_highlighting: true
  json_ld: false

pygments_style: "default"

# Stylesheet wiring (see "Hooking up your build tool's CSS" below)
vite_manifest: "frontend/dist/.vite/manifest.json"
vite_asset_prefix: "/"
extra_stylesheets:
  - "https://fonts.googleapis.com/css2?family=Inter&display=swap"

git:
  auto_commit: false
  auto_push: false
  remote: "origin"
  commit_prefix: "blog:"
```

### Hooking up your build tool's CSS

The default `base.html` is unstyled — cress doesn't ship a theme. To make blog pages share styles with the rest of your product, point cress at your frontend build's manifest:

```yaml
vite_manifest: "frontend/dist/.vite/manifest.json"
vite_asset_prefix: "/"            # default; set to "/app/" if your SPA mounts under a subpath
extra_stylesheets:                  # optional; appended after the manifest entries
  - "https://fonts.googleapis.com/css2?family=Inter&display=swap"
```

cress reads the manifest after every `vite build`, walks every entry chunk (and any chunks they import), and emits one `<link rel="stylesheet">` per resolved CSS asset into `<head>` — in manifest order, with `extra_stylesheets` last. Builds with `cssCodeSplit: false` (including rolldown-vite v8) emit the whole bundle as a top-level `style.css` manifest entry instead of per-chunk `css` arrays; cress picks that up too. No marker comments, no post-build inject script, no duplicated `@theme` blocks. The manifest is read once per build.

`cress serve` mirrors production's URL layout: when `output_dir`'s trailing folders match the `base_url` path (e.g. `dist/blog` served at `/blog`), requests outside the prefix fall back to files under the site root (`dist/`), so manifest-linked CSS, logos, and fonts resolve in preview exactly as they do behind your real web server.

For Tailwind to scan cress's output for utility classes used in markdown bodies, add a `@source` directive in your SPA's CSS pointing at the rendered HTML directory (Tailwind v4 syntax):

```css
@source "../../public/blog/**/*.html";
```

esbuild and webpack manifests have different shapes — open an issue if you need them; the dispatch behind `vite_manifest` is straightforward to extend.

## Static pages mode

By default a cress site is a dated, reverse-chronological **blog**. Setting `static_pages: true` flips that whole build to an evergreen **documentation** site:

```yaml
static_pages: true
```

What changes when the flag is on (everything else is identical):

| | Blog (default) | Static pages (`static_pages: true`) |
| --- | --- | --- |
| `date` frontmatter | Required | **Optional** (a dateless page is fine) |
| Output path / URL | Flat `/<slug>/` | **Folder hierarchy preserved** — `guides/install.md` → `/guides/install/` |
| Index order | `date`, newest first | `url_path`, ascending |
| RSS | Generated | **Disabled** (an undated doc set is not a feed) |
| Sitemap | `lastmod` from date | Present; `lastmod` omitted for dateless pages |
| Slug uniqueness | Global | Per-folder — `guides/index.md` and `api/index.md` coexist |

A page's URL mirrors its location under `vault_subfolder`; the file's leaf name is still the slug. `cress validate` reports a dateless page as an informational `missing_date` warning (it does not fail the run). Wikilinks still resolve by filename/title and now point at the target's hierarchical URL.

### Running a blog and a docs site from one repo

Docs live in their **own vault** (or `vault_subfolder`) with their own config and output dir, built as a second, independent cress site that shares the product's CSS bundle exactly as the blog does. Add a second config beside the blog's, e.g. `.cress/docs.config.yaml`:

```yaml
vault_subfolder: "Docs"
output_dir: "public/docs"
static_pages: true
vault: "../DocsVault"          # the docs' own Obsidian vault
site:
  title: "Docs"
  description: "Product documentation"
  base_url: "https://myproduct.com/docs"
vite_manifest: "frontend/dist/.vite/manifest.json"   # same bundle as the blog
```

Then build each site by selecting its config:

```bash
cress build                                  # the blog (default config)
cress build --config .cress/docs.config.yaml # the docs site
```

Both emit into the same product repo at different paths (`/blog`, `/docs`), each styled by the shared Vite bundle. No "sections" concept — they are simply two cress invocations.

### Navigation (static-pages mode)

In static-pages mode cress reconstructs the vault's folder hierarchy into two navigation primitives, both derived purely from each page's `url_path` and injected into every template's context:

- **`nav`** — a nested tree. The default `base.html` renders it as a recursive sidebar (`_nav.html`), to arbitrary depth.
- **`breadcrumbs`** — the Home → … → current-page trail for the page being rendered (`_breadcrumbs.html`).

Both are gated on `static_pages` in the default templates, so **blog output is byte-for-byte unchanged**. Override `_nav.html` / `_breadcrumbs.html` (or `base.html`) via `template_dir` to restyle them.

How the tree is built:

- **Section landing ↔ folder merge.** A top-level file beside a same-named folder (`position-tagging.md` + `position-tagging/`) becomes **one** node: the file is its clickable page, the folder's contents are its children.
- **Page-less folder.** A folder with no landing file (`api/` with only `api/install.md`) becomes a **non-clickable section header** (`<span>`, no synthesized landing page).
- **Home node.** The auto-generated index is prepended as a synthetic Home node (`title = site.title`), and breadcrumbs always begin with it.
- **Ordering.** Per level: `nav_order` ascending first, then unordered pages alphabetically by label.

Three optional frontmatter fields control a page's place in the tree (all static-pages-only; ignored in blog mode):

| Field | Effect |
| --- | --- |
| `nav_order: <int>` | Sort key within its level (ascending). Unset pages sort after ordered ones, then alphabetically. |
| `nav_title: "<label>"` | Overrides the sidebar/breadcrumb label (falls back to `title`). |
| `nav_hidden: true` | Drops the page from the tree. It still builds and is reachable by URL. |

> Still not in this phase: a dedicated `doc` template type. Static pages render through the existing `post` template, overridable via `templates:` / `template_dir` like any blog.

## Post frontmatter

```yaml
---
# required
title: "Smart Chart Defaults"
date: 2026-04-19

# optional
slug: smart-chart-defaults        # cress writes this back if absent
updated: 2026-04-20
author: "Nick"
summary: "One-liner for index and meta description"
image: images/hero.png
image_alt: "Chart picking UI"
categories: [engineering, product]
tags: [charts, defaults, ux]
draft: false
canonical: https://example.com/x

# static-pages navigation (ignored in blog mode)
nav_order: 3                      # sidebar sort key within its folder level
nav_title: "Phases"              # sidebar/breadcrumb label override
nav_hidden: false                 # true → omit from the sidebar tree (still builds)
---
```

Dates must be ISO 8601. `date` is required in blog mode but optional under [`static_pages`](#static-pages-mode). Missing `slug` values are generated from `title` and written back to the source file at build time. The `nav_*` fields shape the [static-pages sidebar](#navigation-static-pages-mode) and have no effect in blog mode.

## Authoring features

- **Wikilinks:** `[[Target Filename]]` or `[[Target|alias]]` resolve against the site's slug map; broken links render as `<span class="broken-link">` and surface a warning.
- **Embeds:** `![[image.png]]` / `![[video.mp4]]` / `![[audio.mp3]]`, plus `![[another-post.md]]` for single-level markdown transclusion. Obsidian's pipe segment is honored, each `|`-separated piece classified independently: `300` / `300x200` set width/height, `left` / `right` emit a `class="embed-left"`/`"embed-right"` hook (cress ships no float styling — define those classes in your stylesheet), and anything else is alt text — so `![[image.png|Board view|right|300]]` combines all three. Without an alias, alt falls back to the filename stem.
- **Inline tags:** `#tag` in body text is harvested and merged with frontmatter tags (code blocks and ATX heading lines are excluded).
- **Shortcodes:** fenced `` ```name …``` `` blocks dispatch to Python plugins or YAML-rendered Django templates (see `docs/plugins.md`).
- **Heading anchors:** every `<h1..6>` gets a stable `id` slugified from its text.
- **Syntax highlighting:** fenced `` ```python `` renders via pygments and ships a CSS file under `<assets_dir>/pygments-<style>.css`.

## Publishing

`cress publish` delegates credentials to the user's git setup — ssh-agent, the system credential helper, or the CI platform's injected auth. cress sets `GIT_TERMINAL_PROMPT=0` so a misconfigured auth stack fails fast rather than hanging, and raises `PublishError` early if `output_dir` is matched by a `.gitignore` rule.

## Plugins

See `docs/plugins.md` for the six decorators: `@plugin.shortcode`, `@plugin.inline`, `@plugin.template_filter`, `@plugin.template_global`, `@plugin.hook`, `@plugin.page`.

## Development

```bash
uv sync
uv run pytest
uv run mypy --strict src/cress
uv run ruff check .
```

Philosophy, architecture, and the bootstrap plan live under `docs/`.
