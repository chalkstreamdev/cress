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
---
```

Dates must be ISO 8601. Missing `slug` values are generated from `title` and written back to the source file at build time.

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
