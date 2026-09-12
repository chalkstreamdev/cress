# Implementation Plan: `og:site_name` and an ungated `twitter:card`

- **Date:** 2026-08-19
- **Status:** Ready to execute
- **Scope:** Two defects in the shipped `<head>` meta partial — `twitter:card` gated behind an unrelated config field, and `og:site_name` never emitted at all. Covers `defaults/_meta.html`, one new optional `site:` field, their tests, and retiring the downstream workaround already in BackgammonDB. Deliberately does **not** touch `og:image` sizing, JSON-LD, or template resolution order.
- **Depends on:** Nothing
- **Blocks:** Nothing in this repo. Task 3 (cross-repo) cannot start until Tasks 1–2 ship.
- **Related:**
  - `src/cress/templates/defaults/_meta.html`
  - `src/cress/config.py`
  - [`../../../backgammondb/static-templates/base.html`](../../../backgammondb/static-templates/base.html) — carries the local workaround this plan retires
  - [`completed/2026-08-18-index-subcommand.md`](completed/2026-08-18-index-subcommand.md)

## Edit Summary

| Date | Changes | Summary |
|------|---------|---------|
| 2026-08-19 | Plan created | One optional config field, two template lines, a no-handle test fixture, and a cross-repo cleanup |

Two independent defects, both surfaced while auditing how BackgammonDB's blog and manual unfurl
on social platforms.

**`twitter:card` is gated on `site.twitter_handle`** — `defaults/_meta.html:11-12`:

```html
{% if site.twitter_handle %}<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="{{ site.twitter_handle }}">{% endif %}
```

Those two tags answer different questions. `twitter:card` declares the *card format* and stands
on its own; `twitter:site` attributes the card to an account. Gating the format on the
attribution means any site without an X account gets no `twitter:card` at all, so X renders a
small square thumbnail even though cress already emitted a 1200x630 `og:image` for that page.
That is every cress site whose config omits `twitter_handle` — including both BackgammonDB
sites, 47 pages between them.

**`og:site_name` is never emitted.** No shipped template references it. Facebook, LinkedIn and
Slack use it for the small attribution line above the card title; without it they fall back to
showing the bare hostname.

The suite stays green through both because every fixture in `tests/test_default_templates.py`
sets `twitter_handle="@example"` (lines 30 and 44), so only the gated branch is ever rendered.
Task 2's first job is a fixture without a handle.

**The source of `og:site_name` is the one real decision.** `site.title` is the obvious candidate
and is correct for a single-site product. It is wrong for a product running more than one cress
site, which cress already supports through separate config files: BackgammonDB builds a blog and
a manual whose `site.title` values are "BackgammonDB Blog" and "BackgammonDB Manual", while the
correct `og:site_name` for both is "BackgammonDB". So:

- **Rejected — hardcode `{{ site.title }}`.** Zero config, but produces the wrong value in
  exactly the multi-site case cress is already used for, with no way to override it short of
  shadowing the whole partial.
- **Chosen — a new optional `site.name`, falling back to `site.title`.** Single-site users
  configure nothing and get the existing title; multi-site users add one line per config.

**Out of scope, with reasons:**

- `og:image:width` / `og:image:height` — cress would have to read pixel dimensions off each hero
  image. Feasible with stdlib header parsing, but it carries its own failure modes (SVG, WebP,
  truncated files) and is independent of these two tags.
- `twitter:image` / `twitter:description` — X falls back to the `og:` equivalents, so these
  would add bytes to every page for no behaviour change.
- The unmapped `tag` / `category` templates in static-pages mode, which fall back to cress's own
  base and so miss any host `base.html` customisation entirely. A real issue, visible on
  BackgammonDB's four orphan `/manual/tags/` pages, but a separate defect with a separate fix.

**Tech Stack:** Python 3, cress's Django-template render engine, pytest, mypy strict, ruff.

**Reuse:** Task 1 extends the existing `SiteMetaConfig` dataclass and parses through the
`_maybe(..., _as_str)` helper already used for `twitter_handle` and `default_image` — no new
parsing machinery. Task 2 edits one shipped partial and adds no new template. Per CLAUDE.md § 2,
default HTML templates are TDD-exempt (declarative, pinned by render-snapshot tests afterwards),
so Task 2 edits the template then adds assertions; Task 1 is ordinary code and is test-first.

---

## Task 1: Add the optional `site.name` config field

**Status:** Not started

**Files:**
- Modify: `src/cress/config.py`
- Modify: `tests/test_config.py`

**Step 1: Write the tests first.**

Extend the YAML fixture around `tests/test_config.py:35` (which already sets `twitter_handle`
and `default_image`) and the assertion block around `:118`:

- `test_site_name_parsed_when_present` — a `site:` block with `name: "Acme"` yields
  `config.site.name == "Acme"`.
- `test_site_name_defaults_to_none_when_absent` — a `site:` block without `name` yields
  `config.site.name is None`. The template, not the parser, applies the title fallback, so the
  parsed value stays `None`.

Run them and confirm both fail on `SiteMetaConfig` having no `name` attribute.

**Step 2: Add the field.**

In `SiteMetaConfig` (`src/cress/config.py:24-33`), append `name: str | None = None` **after**
`default_image`, at the end of the defaulted fields. Appending rather than grouping it next to
`title` keeps every existing positional construction of this frozen dataclass valid.

**Step 3: Parse it.**

In the `SiteMetaConfig(...)` construction at `src/cress/config.py:147-155`, add:

```python
name=_maybe(site_raw.get("name"), "site.name", _as_str),
```

**Tests:** the two named above.

**Success criteria:** `./.venv/Scripts/pytest.exe tests/test_config.py` green,
`./.venv/Scripts/mypy.exe --strict src/cress` clean, `./.venv/Scripts/ruff.exe check .` clean.

---

## Task 2: Emit `og:site_name` and ungate `twitter:card`

**Status:** Not started

**Files:**
- Modify: `src/cress/templates/defaults/_meta.html`
- Modify: `tests/test_default_templates.py`

**Step 1: Add `og:site_name`.**

Insert after the `og:title` line (`_meta.html:4`):

```html
<meta property="og:site_name" content="{{ site.name|default:site.title }}">
```

`default` rather than `default_if_none` on purpose: it also catches an empty `name: ""` in YAML,
which should fall back to the title rather than emit a blank attribution.

**Step 2: Ungate the card type.**

Replace `_meta.html:11-12` with:

```html
<meta name="twitter:card" content="summary_large_image">
{% if site.twitter_handle %}<meta name="twitter:site" content="{{ site.twitter_handle }}">{% endif %}
```

The card declaration is now unconditional; only the attribution stays gated.

**Step 3: Add a no-handle fixture.**

Mirror the `site` fixture at `tests/test_default_templates.py:37-45` as
`site_without_handle`, identical but with `twitter_handle=None`. Its absence is why both
defects shipped.

**Tests:**

- `test_meta_emits_twitter_card_without_handle` — renders `defaults/post.html` with
  `site_without_handle`; asserts `twitter:card" content="summary_large_image"` is present and
  `twitter:site` is absent.
- `test_meta_emits_twitter_site_when_handle_set` — the existing `site` fixture; asserts both
  tags present, pinning that ungating did not drop the attribution.
- `test_meta_site_name_falls_back_to_title` — no `name` set; asserts
  `og:site_name" content="Example"`.
- `test_meta_site_name_prefers_explicit_name` — `name="Example Product"`; asserts that value
  wins over the title.

**Success criteria:** full `./.venv/Scripts/pytest.exe` green, including the existing
`_assert_well_formed_html` checks on the post, index, tag and category renders — the two new
tags are void elements inside `{% spaceless %}` and must not disturb it.

---

## Task 3: Retire the BackgammonDB workaround (cross-repo)

**Status:** Not started — blocked on Tasks 1–2

**Files:**
- Modify: `../../../backgammondb/static-templates/base.html`
- Modify: `../../../backgammondb/.cress/blog.config.yaml`
- Modify: `../../../backgammondb/.cress/manual.config.yaml`

BackgammonDB currently overrides `{% block meta %}` in its shared `base.html` to append exactly
these two tags, as a workaround for the defects above. Once cress emits them, that override
duplicates both on all 47 pages, so the two changes must land together.

**Step 1:** Revert the meta block in `static-templates/base.html` to the one-liner it was, and
delete the `{% comment %}` block that explains the workaround:

```html
{% block meta %}{% include "defaults/_meta.html" %}{% endblock %}
```

**Step 2:** Add `name: "BackgammonDB"` to the `site:` block of both `.cress` configs, so the two
sites attribute to the product rather than to "BackgammonDB Blog" and "BackgammonDB Manual".

**Step 3:** Rebuild both sites. BackgammonDB runs cress from this repo's venv via an editable
install (`.venv/Lib/site-packages/cress.pth`), so it picks up the `src/` changes with no
reinstall or release:

```
cmd.exe /c "..\cress\.venv\Scripts\cress.exe build --config .cress/blog.config.yaml && ..\cress\.venv\Scripts\cress.exe build --config .cress/manual.config.yaml"
```

**Tests:** no unit tests — this is configuration and a template revert, verified by inspecting
the build output.

**Success criteria:** across `dist/blog` (20 pages) and `dist/manual` (27), every page carries
exactly one `og:site_name` and one `twitter:card`, and `og:site_name` reads "BackgammonDB" on
both sites. Confirm the count is 1 and not 2 on a sample page — duplication is the specific
failure this task exists to prevent:

```
grep -c 'og:site_name' dist/blog/study-mode/index.html
```

---

## Task 4: Update Documentation

**Status:** Not started

- `README.md` — add `name: "My Product"` to the `site:` schema block (around line 214, beside
  `twitter_handle`), with a one-line note that it sets `og:site_name`, defaults to `title`, and
  earns its place when one product ships several cress sites. The claims at lines 27 and 278
  that the shipped templates emit "correct meta tags and Open Graph properties" need no edit —
  they become more true.
- `CHANGELOG.md` — under `## [Unreleased]`, an `### Added` entry for `site.name` and a
  `### Fixed` entry for the `twitter:card` gate. The Fixed entry must state the behaviour
  change plainly: sites configured without `twitter_handle` now emit `twitter:card` where they
  previously emitted none, so their X unfurls change from a small thumbnail to a large card.
- `CLAUDE.md` — no change. No convention, command, or module boundary moved.

---

## Edit History

<!-- Created by /critique on its first pass, or by /complete-task at the end. Newest last. -->
