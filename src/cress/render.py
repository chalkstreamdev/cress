"""Markdown + Django template rendering.

Two responsibilities:

* Markdown → HTML via mistune 3 with cress-specific plugins (wikilinks,
  embeds, shortcodes, heading anchors, pygments highlighting).
* Django template engine setup (standalone, no ORM, no settings module).
  A fresh :class:`~django.template.Engine` is built per :meth:`cress.build`
  call so template filters/globals registered by plugins don't leak across
  builds.
"""

import base64
import importlib.resources
import re
from dataclasses import dataclass, field
from re import Match
from typing import Any

import django
import mistune
from django.conf import settings
from django.template import Context, Engine
from django.template import TemplateDoesNotExist as DjangoTemplateDoesNotExist
from mistune import HTMLRenderer, Markdown
from mistune.block_parser import BlockParser
from mistune.core import BlockState, InlineState
from mistune.inline_parser import InlineParser
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from cress.config import SiteConfig
from cress.exceptions import TemplateNotFound
from cress.plugins import PluginRegistry
from cress.slugify import slugify
from cress.template_library import install_plugin_registrations

_INLINE_TAG_RE = re.compile(r"<[^>]+>")

_WIKILINK_PATTERN = r"\[\[(?P<wikilink_target>[^\]\n|]+?)(?:\|(?P<wikilink_alias>[^\]\n]+))?\]\]"
_EMBED_PATTERN = r"!\[\[(?P<embed_target>[^\]\n|]+?)(?:\|(?P<embed_alias>[^\]\n]+))?\]\]"

# Obsidian-style callouts: a block quote whose first line is ``[!type] Title``.
# Detected by wrapping the block_quote parser (see _parse_block_quote_or_callout)
# rather than a competing block rule, because mistune's list parser hard-codes
# block_quote as a list terminator — a separate rule would be bypassed for a
# callout placed directly after a list. The fold marker ``[+-]`` is ignored.
_CALLOUT_MARKER_RE = re.compile(r"^ *\[!(?P<kind>[A-Za-z][\w-]*)\][-+]? *(?P<title>[^\n]*)\n?")

# Author-facing type aliases → the four canonical styles.
_CALLOUT_ALIASES = {
    "info": "info", "information": "info", "note": "info", "todo": "info",
    "success": "success", "tip": "success", "check": "success", "done": "success",
    "hint": "success", "warning": "warning", "caution": "warning", "attention": "warning",
    "important": "warning", "error": "error", "danger": "error", "fail": "error",
    "failure": "error", "bug": "error",
}

# Default title when the author gives none (just ``> [!warning]``).
_CALLOUT_LABELS = {
    "info": "Information",
    "success": "Success",
    "warning": "Warning",
    "error": "Error"
}

# Lucide-style icon paths (drawn with stroke=currentColor so they pick up the
# callout's accent colour).
_CALLOUT_ICONS = {
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "success": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "warning":
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'
        '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "error": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
}


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Per-build render configuration.

    ``shortcode_names`` comes from the shortcode registry; markdown rendering
    only needs the name set to decide dispatch in ``block_code``.
    """

    shortcode_names: set[str] = field(default_factory=set)
    pygments_style: str = "default"


class CressRenderer(HTMLRenderer):
    """Subclass of mistune's HTMLRenderer with cress extensions."""

    def __init__(self, ctx: RenderContext) -> None:
        super().__init__(escape=False)
        self._ctx = ctx

    def heading(self, text: str, level: int, **attrs: Any) -> str:
        del attrs
        stripped = _INLINE_TAG_RE.sub("", text)
        anchor = slugify(stripped)
        return f'<h{level} id="{anchor}">{text}</h{level}>\n'

    def block_code(self, code: str, info: str | None = None, **_attrs: Any) -> str:
        info_token = (info or "").strip().split(None, 1)[0] if info else ""
        if info_token and info_token in self._ctx.shortcode_names:
            encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
            return (
                f'<div data-cress-shortcode="{mistune.escape(info_token)}" '
                f'data-cress-body="{encoded}"></div>\n'
            )
        if info_token:
            try:
                lexer = get_lexer_by_name(info_token, stripall=False)
            except ClassNotFound:
                return f"<pre><code>{mistune.escape(code)}</code></pre>\n"
            formatter = HtmlFormatter(
                style=self._ctx.pygments_style, nowrap=False, cssclass="codehilite"
            )
            result = highlight(code, lexer, formatter)
            assert isinstance(result, str)
            return result
        return f"<pre><code>{mistune.escape(code)}</code></pre>\n"

    def cress_wikilink(self, target: str, alias: str) -> str:
        inner = alias if alias else target
        return (
            f'<a data-cress-wikilink="{mistune.escape(target)}" '
            f'data-cress-alias="{mistune.escape(alias)}">{mistune.escape(inner)}</a>'
        )

    def cress_embed(self, target: str, alias: str) -> str:
        alias_attr = f' data-cress-embed-alias="{mistune.escape(alias)}"' if alias else ""
        return f'<span data-cress-embed="{mistune.escape(target)}"{alias_attr}></span>'


def _parse_cress_embed(inline: InlineParser, m: Match[str], state: InlineState) -> int:
    del inline
    target = m.group("embed_target")
    alias = m.group("embed_alias") or ""
    state.append_token({"type": "cress_embed", "attrs": {"target": target, "alias": alias}})
    return m.end()


def _parse_cress_wikilink(inline: InlineParser, m: Match[str], state: InlineState) -> int:
    del inline
    target = m.group("wikilink_target")
    alias = m.group("wikilink_alias") or ""
    state.append_token({"type": "cress_wikilink", "attrs": {"target": target, "alias": alias}})
    return m.end()


def _parse_block_quote_or_callout(block: BlockParser, m: Match[str], state: BlockState) -> int:
    """Drop-in replacement for mistune's ``block_quote`` parser.

    Extracts the quote exactly as mistune does, then — if the quote's first line
    is a ``[!type]`` callout marker — emits a ``callout`` token whose body is the
    remaining quote text parsed as markdown. Otherwise behaves identically to the
    stock block_quote parser. Wrapping block_quote (rather than adding a rule)
    means callouts work everywhere a quote can appear, including right after a
    list, where mistune hard-codes block_quote as the terminating rule.
    """
    text, end_pos = block.extract_block_quote(m, state)
    marker = _CALLOUT_MARKER_RE.match(text)

    if state.depth() >= block.max_nested_level - 1:
        rules = list(block.block_quote_rules)
        rules.remove("block_quote")
    else:
        rules = block.block_quote_rules

    if marker:
        kind = _CALLOUT_ALIASES.get(marker.group("kind").lower(), "info")
        title = (marker.group("title") or "").strip()
        child = state.child_state(text[marker.end():])
        block.parse(child, rules)
        token: dict[str, Any] = {
            "type": "callout",
            "attrs": {"callout_kind": kind, "callout_title": title},
            "children": child.tokens,
        }
    else:
        child = state.child_state(text)
        block.parse(child, rules)
        token = {"type": "block_quote", "children": child.tokens}

    if end_pos:
        state.prepend_token(token)
        return end_pos
    state.append_token(token)
    return state.cursor


def _render_callout(
        renderer: HTMLRenderer,
        text: str,
        callout_kind: str,
        callout_title: str) -> str:
    del renderer
    label = callout_title or _CALLOUT_LABELS[callout_kind]
    svg = (
        '<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{_CALLOUT_ICONS[callout_kind]}</svg>"
    )
    title_html = f'<div class="callout-title">{svg}<span>{mistune.escape(label)}</span></div>'
    body_html = f'<div class="callout-content">{text}</div>' if text.strip() else ""
    return f'<div class="callout callout-{callout_kind}">{title_html}{body_html}</div>\n'


def _plugin_cress_embed(md: Markdown) -> None:
    # Embed pattern starts with `!` — must be registered BEFORE wikilinks so
    # `![[x]]` isn't split as `!` + `[[x]]`.
    md.inline.register("cress_embed", _EMBED_PATTERN, _parse_cress_embed, before="link")


def _plugin_cress_wikilink(md: Markdown) -> None:
    md.inline.register("cress_wikilink", _WIKILINK_PATTERN, _parse_cress_wikilink, before="link")


def _plugin_callout(md: Markdown) -> None:
    # Swap the block_quote parser for our callout-aware wrapper (pattern + rule
    # position unchanged — passing None keeps the existing block_quote spec).
    md.block.register("block_quote", None, _parse_block_quote_or_callout)
    if md.renderer and md.renderer.NAME == "html":
        md.renderer.register("callout", _render_callout)


def _build_parser(ctx: RenderContext) -> Markdown:
    renderer = CressRenderer(ctx)
    return mistune.create_markdown(
        renderer=renderer,
        plugins=[
            _plugin_cress_embed,
            _plugin_cress_wikilink,
            _plugin_callout,
            "strikethrough",
            "table",
        ],
    )


def render_markdown_text(source: str, ctx: RenderContext) -> str:
    """Render a markdown body to HTML with cress placeholders.

    Wikilinks and embeds are left as ``data-cress-*`` placeholders for the
    later wikilink/embed substitution passes to resolve; shortcodes are emitted
    as ``<div data-cress-shortcode>`` for the shortcode substitution pass.
    Heading ids and pygments highlighting happen here.
    """
    result = _build_parser(ctx)(source)
    assert isinstance(result, str)
    return result


def _ensure_django_setup() -> None:
    """``settings.configure()`` + ``django.setup()`` — idempotent."""
    if not settings.configured:
        settings.configure(
            USE_I18N=False,
            USE_L10N=False,
            USE_TZ=False,
            DEBUG=False,
            INSTALLED_APPS=[],
        )
        django.setup()


def _default_templates_root() -> str:
    """Filesystem path to cress's shipped templates parent dir.

    Returns the **parent** of ``defaults/`` so ``{% extends "defaults/post.html" %}``
    resolves correctly from either a product override or another default.
    """
    return str(importlib.resources.files("cress").joinpath("templates"))


def build_engine(config: SiteConfig, registry: PluginRegistry) -> Engine:
    """Build a fresh standalone Django template :class:`Engine` for this build.

    A new engine is returned on every call so plugin-registered filters and
    globals attach only to this build's engine — stale registrations die with
    the previous instance, giving template-filter/global hot-reload for free.
    """
    _ensure_django_setup()
    install_plugin_registrations(registry)

    dirs: list[str] = []
    if config.template_dir is not None:
        dirs.append(str(config.template_dir))
    dirs.append(_default_templates_root())

    return Engine(
        dirs=dirs,
        app_dirs=False,
        debug=False,
        builtins=["cress.template_library"],
        autoescape=True,
    )


def resolve_template_name(page_type: str, config: SiteConfig) -> str:
    """Return the per-build template name for a page type — override or shipped default."""
    override = config.templates.get(page_type)
    if override is not None:
        return override
    return f"defaults/{page_type}.html"


def render_template(engine: Engine, name: str, context: dict[str, Any]) -> str:
    """Resolve and render a named template. Raises :class:`TemplateNotFound` on miss."""
    try:
        template = engine.get_template(name)
    except DjangoTemplateDoesNotExist as exc:
        raise TemplateNotFound(f"template not found: {name}") from exc
    result = template.render(Context(context))
    assert isinstance(result, str)
    return result
