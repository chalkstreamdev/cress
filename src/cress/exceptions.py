"""Typed exceptions raised by cress.

Every error raised from inside the library inherits from :class:`CressError`
so callers can catch-all at the boundary if they need to. Each subclass
corresponds to a well-defined failure mode documented in the spec.

Modules define their own subclasses where they live, but they all root here
to keep ``except`` clauses short and the class graph discoverable.
"""


class CressError(Exception):
    """Base class for all cress-specific errors."""


class ConfigError(CressError):
    """Raised when site or user config is missing or invalid."""


class PostParseError(CressError):
    """Raised when a post's frontmatter or body cannot be parsed."""


class DuplicateSlugError(CressError):
    """Raised when two posts would occupy the same slug."""


class TemplateNotFound(CressError):
    """Raised when a named template cannot be resolved."""


class PublishError(CressError):
    """Raised when ``cress publish`` cannot proceed (e.g. gitignored output_dir)."""
