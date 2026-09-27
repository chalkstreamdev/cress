# Changelog

All notable changes to cress are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-09-27

### Added

- `og_image` post frontmatter field: a separate social-share card. It is
  resolved through the attachment pipeline exactly like `image` (hashed,
  staged, absolutized) and wins for the `og:image` tag only — the page hero
  stays `image`. A missing file emits a `missing_og_image` warning.
- `site.name` config field: the value of the new `og:site_name` meta tag,
  which the shipped `_meta.html` now emits on every page. It defaults to
  `site.title`, so single-site products configure nothing. Set it when one
  product ships several cress sites, so each attributes to the product rather
  than to its own title.

### Fixed

- `twitter:card` is no longer gated on `site.twitter_handle`. Sites configured
  without a handle now emit `<meta name="twitter:card" content="summary_large_image">`
  where they previously emitted no card declaration at all, so their X unfurls
  change from a small square thumbnail to a large card. `twitter:site` stays
  gated on the handle.

## [0.3.0] - 2026-08-18

### Added

- `cress index` subcommand: emits the vault's post list as structured data
  without building the site — no vite-manifest dependency, no disk writes, so
  a host app can run it before or during its own build. Human listing by
  default (`<date>  <path>  <title>`); `--json` puts one record per post at
  `result.posts` in the standard envelope (title, slug, prefix-relative
  `path`, absolute `url`, dates, summary, author, tags, categories, reading
  time, draft flag, content-hashed hero-image URL). Slugless posts get the
  same slug `cress build` will write back later; `--drafts` opts drafts in
  with their unlisted preview paths.
- Public `cress.pages.post_path` / `post_url` helpers (previously private) for
  code that needs a post's site-root-relative or prefix-applied URL.

## [0.2.0] - 2026-08-12

### Added

- `--list-drafts` option for `cress serve`: includes drafts in the article
  index with links to their previews.
- Obsidian-style callout boxes (`> [!note] Title`), with the usual Obsidian
  type aliases mapped onto the info / success / warning / error styles.
- `paginate: 0` disables pagination: every post on a single index, tag, or
  category page.
- Static-pages mode (`static_pages: true`) for evergreen documentation sites:
  folder-hierarchy URLs, optional dates, per-folder slug uniqueness, and a
  sidebar/breadcrumb navigation tree derived from each page's `url_path`.
- Stylesheet wiring via a build tool's Vite manifest (`vite_manifest`,
  `vite_asset_prefix`, `extra_stylesheets`).

### Changed

- `vault_subfolder` is now optional; omit it to publish the whole vault.
- `cress serve --live-reload` now watches the template directory as well, so
  template edits trigger a rebuild.

## [0.1.0] - 2026-06-15

### Added

- Initial public release.
- Render an Obsidian vault to static HTML: frontmatter parsing, draft
  partitioning, slug planning with write-back, wikilinks, embeds, inline tags,
  shortcodes, heading anchors, and Pygments syntax highlighting.
- `build`, `validate`, `serve` (with `--live-reload`), and `publish` commands,
  each with a `--json` machine-readable envelope.
- RSS/Atom feeds and sitemap generation.
- Plugin API with six decorators (`shortcode`, `inline`, `template_filter`,
  `template_global`, `hook`, `page`).
- Manifest-tracked output writer so only cress-owned files are cleaned up.

[Unreleased]: https://github.com/chalkstreamdev/cress/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/chalkstreamdev/cress/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/chalkstreamdev/cress/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/chalkstreamdev/cress/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/chalkstreamdev/cress/releases/tag/v0.1.0
