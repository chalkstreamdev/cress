# Changelog

All notable changes to cress are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/chalkstreamdev/cress/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/chalkstreamdev/cress/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/chalkstreamdev/cress/releases/tag/v0.1.0
