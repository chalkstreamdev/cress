# Changelog

All notable changes to cress are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Static-pages mode (`static_pages: true`) for evergreen documentation sites:
  folder-hierarchy URLs, optional dates, per-folder slug uniqueness, and a
  sidebar/breadcrumb navigation tree derived from each page's `url_path`.
- Stylesheet wiring via a build tool's Vite manifest (`vite_manifest`,
  `vite_asset_prefix`, `extra_stylesheets`).

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

[Unreleased]: https://github.com/chalkstreamdev/cress/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/chalkstreamdev/cress/releases/tag/v0.1.0
