"""Shortcode registry.

Maps fenced ```` ```name\\n...``` ```` blocks to either a Django template
(registered from config's ``shortcodes:`` map) or a Python function (registered
via ``@plugin.shortcode``). Parses the YAML body and dispatches.
"""

import base64
import html
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from django.template import Engine

from cress.reports import BuildWarning

_SHORTCODE_PLACEHOLDER_RE = re.compile(
    r'<div data-cress-shortcode="(?P<name>[^"]+)" data-cress-body="(?P<body>[^"]*)"></div>'
)


@dataclass(frozen=True, slots=True)
class Shortcode:
    """A registered shortcode — ``kind`` determines the handler contract."""

    name: str
    kind: Literal["template", "python"]
    handler: Callable[..., str]


class ShortcodeRegistry:
    """Holds the shortcode dispatch table for one build."""

    def __init__(self) -> None:
        self._codes: dict[str, Shortcode] = {}

    def register_template(self, name: str, template_path: str, engine: Engine) -> None:
        """Register ``name`` to render via a Django template with YAML body as context."""

        def handler(body: str, **ctx: Any) -> str:
            del ctx  # template shortcodes receive only the YAML body as context
            data = yaml.safe_load(body) or {}
            if not isinstance(data, dict):
                data = {"value": data}
            template = engine.get_template(template_path)
            from django.template import Context  # local import keeps top clean

            result = template.render(Context(data))
            assert isinstance(result, str)
            return result

        self._codes[name] = Shortcode(name=name, kind="template", handler=handler)

    def register_python(self, name: str, func: Callable[..., str]) -> None:
        """Register a Python ``@plugin.shortcode(name)`` handler."""
        self._codes[name] = Shortcode(name=name, kind="python", handler=func)

    def names(self) -> set[str]:
        """Every registered shortcode name — used by :mod:`cress.render`'s code-block dispatcher."""
        return set(self._codes.keys())

    def render(
        self,
        name: str,
        body: str,
        source_path: Path,
        warnings: list[BuildWarning],
        extra_context: dict[str, Any] | None = None,
    ) -> str:
        """Render one shortcode invocation. Emits a warning and error HTML on failure."""
        code = self._codes.get(name)
        if code is None:
            warnings.append(
                BuildWarning(
                    type="shortcode_error",
                    file=str(source_path),
                    message=f"unknown shortcode {name!r}",
                )
            )
            return _error_html(name, "unknown shortcode")
        # YAML-validate the body even for Python shortcodes — per spec, malformed
        # bodies are a surfaceable error regardless of handler kind.
        try:
            yaml.safe_load(body)
        except yaml.YAMLError as exc:
            warnings.append(
                BuildWarning(
                    type="shortcode_error",
                    file=str(source_path),
                    message=f"shortcode {name!r}: invalid YAML: {exc}",
                )
            )
            return _error_html(name, "invalid YAML")
        try:
            if code.kind == "template":
                return code.handler(body)
            return code.handler(body, **(extra_context or {}))
        except Exception as exc:  # plugin handlers may raise anything; isolate and warn
            warnings.append(
                BuildWarning(
                    type="shortcode_error",
                    file=str(source_path),
                    message=f"shortcode {name!r} raised: {exc}",
                )
            )
            return _error_html(name, str(exc))


def substitute_shortcodes(
    html_body: str,
    registry: ShortcodeRegistry,
    warnings: list[BuildWarning],
    source_path: Path,
    extra_context: dict[str, Any] | None = None,
) -> str:
    """Replace every shortcode placeholder in ``html_body`` with its rendered output."""

    def _repl(match: re.Match[str]) -> str:
        name = match.group("name")
        encoded = match.group("body")
        try:
            body = base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            warnings.append(
                BuildWarning(
                    type="shortcode_error",
                    file=str(source_path),
                    message=f"shortcode {name!r}: body decode failed: {exc}",
                )
            )
            return _error_html(name, "body decode failed")
        return registry.render(name, body, source_path, warnings, extra_context)

    return _SHORTCODE_PLACEHOLDER_RE.sub(_repl, html_body)


def _error_html(name: str, reason: str) -> str:
    return (
        f'<div class="cress-shortcode-error" data-name="{html.escape(name)}">'
        f"{html.escape(reason)}</div>"
    )
