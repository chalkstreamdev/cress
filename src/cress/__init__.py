"""cress — Obsidian-to-static-site generator.

Public API surface: the :class:`cress` orchestrator class, the :data:`plugin`
singleton used by plugin authors, the :class:`SiteConfig` dataclass, and
``__version__`` (read from installed package metadata).

The public symbols here are deliberately minimal — every decorator and subsystem
hangs off the :data:`plugin` singleton or is exposed only to direct callers of
the ``cress`` class (CLI, tests, notebooks).
"""

from importlib.metadata import PackageNotFoundError, version

from cress.config import SiteConfig
from cress.plugins import plugin
from cress.site import cress

try:
    __version__: str = version("cress")
except PackageNotFoundError:  # pragma: no cover — only when running from source without install
    __version__ = "0.0.0+unknown"


__all__ = ["SiteConfig", "__version__", "cress", "plugin"]
