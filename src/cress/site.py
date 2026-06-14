"""Site orchestrator — the ``cress`` class.

Top-level object tying the pipeline together. ``__init__`` is cheap (config
only); ``build()`` discovers plugins, builds a fresh Django engine, parses
posts, plans and applies slug write-backs, renders everything, and writes
the output tree via the manifest writer.
"""

import time
from dataclasses import replace as _replace
from datetime import datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

from pygments.formatters import HtmlFormatter

from cress.attachments import (
    plan_attachment,
    reset_attachment_cache,
    resolve_attachment,
    substitute_embeds,
    substitute_standard_images,
)
from cress.build_result import BuildResult
from cress.config import SiteConfig, load_site_config
from cress.exceptions import ConfigError, DuplicateSlugError, PostParseError
from cress.feeds import render_rss, render_sitemap
from cress.manifest import OutputFile, load_manifest, write_outputs
from cress.pages import (
    PageContext,
    render_category_list,
    render_category_pages,
    render_draft_page,
    render_index_pages,
    render_post_page,
    render_tag_list,
    render_tag_pages,
)
from cress.plugins import PluginRegistry, discover_plugins
from cress.post import (
    Post,
    apply_slug_writebacks,
    compute_url_path,
    parse_post,
    plan_slug_writebacks,
    vault_rel_dir,
)
from cress.render import RenderContext, build_engine, render_markdown_text
from cress.reports import BuildWarning
from cress.shortcodes import ShortcodeRegistry, substitute_shortcodes
from cress.taxonomy import Taxonomy
from cress.vite_manifest import resolve_stylesheets
from cress.wikilinks import build_slug_map, substitute_wikilinks


def _version() -> str:
    try:
        return _pkg_version("cress")
    except PackageNotFoundError:
        return "0.0.0+unknown"


class cress:  # noqa: N801 — spec fixes the class name as lowercase
    """Site orchestrator. Loads config on construction; builds lazily."""

    def __init__(self, vault: Path, target: Path, config_path: Path | None = None) -> None:
        if not vault.is_dir():
            raise ConfigError(f"vault does not exist: {vault}")
        if not target.is_dir():
            raise ConfigError(f"target does not exist: {target}")
        self.vault: Path = vault
        self.target: Path = target
        self.config: SiteConfig = load_site_config(target, config_path)

    def build(self, drafts_only: bool = False, no_drafts: bool = False) -> BuildResult:
        """Run the full build pipeline (steps numbered inline below)."""
        started = time.perf_counter()
        warnings: list[BuildWarning] = []
        errors: list[BuildWarning] = []

        if drafts_only and no_drafts:
            raise ConfigError("drafts_only and no_drafts cannot both be true")

        # Step 1: discover plugins, build engine, instantiate shortcode registry.
        reset_attachment_cache()
        registry = discover_plugins(self.target, warnings)
        engine = build_engine(self.config, registry)
        shortcode_registry = self._build_shortcode_registry(registry, engine)

        # Step 2: before_build hook.
        self._fire_hook(registry, "before_build", [self.config])

        # Step 3: discover posts.
        vault_posts_dir = self.vault / self.config.vault_subfolder
        if not vault_posts_dir.is_dir():
            raise ConfigError(f"vault subfolder does not exist: {vault_posts_dir}")
        md_paths = sorted(vault_posts_dir.rglob("*.md"))
        if not md_paths:
            raise ConfigError(f"no markdown posts under {vault_posts_dir}")

        # Step 4: parse posts.
        posts: list[Post] = []
        for md_path in md_paths:
            try:
                posts.append(parse_post(md_path, self.config))
            except PostParseError as exc:
                warnings.append(
                    BuildWarning(
                        type="post_parse_error",
                        file=str(md_path),
                        message=str(exc),
                    )
                )

        if not posts:
            # Every post failed to parse — treat as empty input.
            raise ConfigError("no parseable posts — every file failed to parse")

        # Slug-uniqueness namespace: global in blog mode, per-folder in static
        # mode so identically-named leaves in different folders don't collide.
        def _namespace(post: Post) -> str:
            return vault_rel_dir(
                post.source_path, vault_posts_dir, static_pages=self.config.static_pages
            )

        # Steps 5 and 6: plan and apply slug write-backs (hard error on duplicates).
        plan = plan_slug_writebacks(posts, namespace=_namespace)
        if plan.duplicates:
            detail = "; ".join(
                f"{d.slug}: {', '.join(str(p) for p in d.paths)}" for d in plan.duplicates
            )
            raise DuplicateSlugError(f"duplicate slugs detected: {detail}")

        if plan.writebacks:
            apply_slug_writebacks(plan)

            # Reparse affected posts so their in-memory slug reflects disk.
            rewritten = {p for p, _ in plan.writebacks}
            posts = [
                parse_post(p.source_path, self.config) if p.source_path in rewritten else p
                for p in posts
            ]

        # Step 6b: stamp each post's site-root-relative ``url_path``. Now that
        # every slug is final, compute the single source of truth the page,
        # feed, and wikilink URL producers all read. Blog mode → ``slug``;
        # static mode → ``<rel_dir>/<slug>`` mirroring the vault hierarchy.
        posts = [
            _replace(
                post,
                url_path=compute_url_path(
                    post.source_path,
                    post.slug,
                    vault_posts_dir,
                    static_pages=self.config.static_pages,
                ),
            )
            if post.slug is not None
            else post
            for post in posts
        ]

        # Step 7: partition drafts / published and apply filters.
        filtered = [
            p for p in posts if (not no_drafts or not p.draft) and (not drafts_only or p.draft)
        ]
        if not filtered:
            warnings.append(
                BuildWarning(
                    type="empty_filtered_build",
                    file="",
                    message="no posts matched the active filter",
                )
            )

        # Step 8: build slug map (duplicate check already done).
        slug_map = build_slug_map(filtered, namespace=_namespace)

        # Step 9: resolve hero images *before* building taxonomies so every
        # downstream consumer (tag/category pages, RSS, feeds) sees the same
        # resolved ``Post.image`` — otherwise the tag page renders post cards
        # with the raw frontmatter filename.
        attachment_outputs: list[OutputFile] = []
        filtered = [self._resolve_hero_image(p, attachment_outputs, warnings) for p in filtered]

        # Step 10: taxonomies (use the hero-resolved posts).
        tag_tax = Taxonomy()
        cat_tax = Taxonomy()
        for post in filtered:
            for tag in post.tags:
                tag_tax.add(tag, post, warnings)
            for cat in post.categories:
                cat_tax.add(cat, post, warnings)

        # Step 11: site default image.
        og_image_url: str | None = self._resolve_default_image(attachment_outputs, warnings)

        # Step 12: per-post render loop.
        render_ctx = RenderContext(
            shortcode_names=shortcode_registry.names(),
            pygments_style=self.config.pygments_style,
        )
        posts_with_html: list[tuple[Post, str]] = []
        for post in filtered:
            body_html = render_markdown_text(post.body_md, render_ctx)
            body_html = substitute_wikilinks(
                body_html, slug_map, warnings, post.source_path, self.config.url_prefix
            )
            body_html = substitute_embeds(
                body_html,
                post,
                self.config,
                warnings,
                attachment_outputs,
                vault=self.vault,
                slug_map=slug_map,
                render_ctx=render_ctx,
            )
            body_html = substitute_standard_images(
                body_html,
                post,
                self.config,
                warnings,
                attachment_outputs,
                vault=self.vault,
            )
            body_html = substitute_shortcodes(
                body_html, shortcode_registry, warnings, post.source_path
            )
            posts_with_html.append((post, body_html))
            self._fire_hook(registry, "after_post", [post])

        # Step 12: page + feed + custom-page generators.
        page_ctx = PageContext(
            config=self.config,
            engine=engine,
            now=datetime.now(),
            cress_version=_version(),
            stylesheets=tuple(resolve_stylesheets(self.config)),
            default_image_url=og_image_url,
        )
        page_outputs: list[OutputFile] = []
        for post, body_html in posts_with_html:
            if post.draft:
                page_outputs.append(render_draft_page(post, body_html, page_ctx))
            else:
                page_outputs.append(render_post_page(post, body_html, page_ctx))
        page_outputs.extend(render_index_pages(posts_with_html, page_ctx))
        page_outputs.extend(render_tag_pages(tag_tax, page_ctx))
        page_outputs.extend(render_category_pages(cat_tax, page_ctx))
        page_outputs.append(render_tag_list(tag_tax, page_ctx))
        page_outputs.append(render_category_list(cat_tax, page_ctx))

        feed_outputs = [
            *render_sitemap([p for p, _ in posts_with_html], tag_tax, cat_tax, page_ctx),
            *render_rss([p for p, _ in posts_with_html], page_ctx),
        ]

        custom_outputs = self._run_custom_pages(registry, page_ctx, warnings)

        # Step 13: pygments CSS as an OutputFile.
        pygments_outputs: list[OutputFile] = []
        if self.config.features.syntax_highlighting:
            pygments_outputs.append(self._pygments_css_output())

        # Step 14: concatenate.
        all_outputs: list[OutputFile] = (
            page_outputs
            + list(feed_outputs)
            + custom_outputs
            + attachment_outputs
            + pygments_outputs
        )

        # Step 15: before_write hook — may replace the output list.
        hook_result = self._fire_hook_with_return(registry, "before_write", [all_outputs])
        if isinstance(hook_result, list):
            all_outputs = hook_result

        # Step 16: write via manifest.
        old_manifest = load_manifest(self.config.output_dir)
        write_outputs(all_outputs, self.config.output_dir, old_manifest)

        duration_ms = int((time.perf_counter() - started) * 1000)
        result = BuildResult(
            pages_written=len([o for o in all_outputs if o.relative_path.endswith(".html")]),
            skipped_posts=len(posts) - len(filtered),
            warnings=warnings,
            errors=errors,
            duration_ms=duration_ms,
        )

        # Step 17: after_build hook.
        self._fire_hook(registry, "after_build", [result])
        return result

    # -- helpers ------------------------------------------------------------
    def _resolve_hero_image(
        self,
        post: Post,
        attachment_outputs: list[OutputFile],
        warnings: list[BuildWarning],
    ) -> Post:
        """Route a post's frontmatter ``image:`` through the attachment pipeline.

        Absolute references (``http(s)://``, ``//``, ``/``, ``data:``) pass
        through unchanged. A relative reference is resolved against the vault's
        attachments folder (then the post's own directory); if found it's
        hashed + staged into ``attachment_outputs`` and ``post.image`` is
        rewritten to the public URL. Missing files emit a warning and
        ``post.image`` is cleared so templates can ``{% if page.image_url %}``
        past it cleanly.
        """
        if post.image is None:
            return post
        if post.image.startswith(("http://", "https://", "//", "/", "data:")):
            return post
        assert post.slug is not None, "hero image resolution runs after slug write-back"
        resolved = resolve_attachment(post.image, post, self.config, self.vault)
        if resolved is None:
            warnings.append(
                BuildWarning(
                    type="missing_hero_image",
                    file=str(post.source_path),
                    message=f"hero image {post.image!r} not found",
                )
            )
            return _replace(post, image=None)
        plan = plan_attachment(resolved, post.slug, self.config)
        if plan.output_file not in attachment_outputs:
            attachment_outputs.append(plan.output_file)
        return _replace(post, image=plan.public_url)

    def _resolve_default_image(
        self,
        attachment_outputs: list[OutputFile],
        warnings: list[BuildWarning],
    ) -> str | None:
        default_image = self.config.site.default_image
        if default_image is None:
            return None
        path = self.vault / self.config.attachments_subfolder / default_image
        if not path.is_file():
            path = self.target / default_image
        if not path.is_file():
            warnings.append(
                BuildWarning(
                    type="missing_default_image",
                    file=str(self.config.target),
                    message=f"site.default_image {default_image!r} not found",
                )
            )
            return None
        plan = plan_attachment(path, "_site", self.config)
        if plan.output_file not in attachment_outputs:
            attachment_outputs.append(plan.output_file)
        return plan.public_url

    def _build_shortcode_registry(self, registry: PluginRegistry, engine: Any) -> ShortcodeRegistry:
        sc = ShortcodeRegistry()
        # Template-only shortcodes declared in config.
        for name, template_path in self.config.shortcodes.items():
            sc.register_template(name, template_path, engine)
        # Python shortcodes from the plugin registry.
        for name, func in registry.shortcodes.items():
            sc.register_python(name, func)
        return sc

    def _pygments_css_output(self) -> OutputFile:
        formatter = HtmlFormatter(style=self.config.pygments_style, cssclass="codehilite")
        css = formatter.get_style_defs(".codehilite")
        rel = f"assets/pygments-{self.config.pygments_style}.css"
        return OutputFile(relative_path=rel, content=css)

    def _fire_hook(self, registry: PluginRegistry, name: str, args: list[Any]) -> None:
        for fn in registry.hooks.get(name, []):
            fn(*args)

    def _fire_hook_with_return(self, registry: PluginRegistry, name: str, args: list[Any]) -> Any:
        last_return: Any = None
        for fn in registry.hooks.get(name, []):
            result = fn(*args)
            if result is not None:
                last_return = result
        return last_return

    def _run_custom_pages(
        self,
        registry: PluginRegistry,
        page_ctx: PageContext,
        warnings: list[BuildWarning],
    ) -> list[OutputFile]:
        outputs: list[OutputFile] = []
        for fn in registry.custom_pages:
            try:
                result = fn(page_ctx)
            except Exception as exc:
                warnings.append(
                    BuildWarning(
                        type="custom_page_error",
                        file=str(self.config.target),
                        message=f"{fn.__name__} raised: {exc}",
                    )
                )
                continue
            if not isinstance(result, list):
                continue
            for item in result:
                if isinstance(item, OutputFile):
                    outputs.append(item)
        return outputs
