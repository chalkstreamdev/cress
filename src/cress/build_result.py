"""The :class:`BuildResult` returned by :meth:`cress.cress.build`.

Lives in its own module so :mod:`cress.site` and the CLI can both import it
without pulling in the orchestrator's heavy dependency graph.
"""

from dataclasses import dataclass, field

from cress.reports import BuildWarning


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Summary of a completed build."""

    pages_written: int = 0
    skipped_posts: int = 0
    warnings: list[BuildWarning] = field(default_factory=list)
    errors: list[BuildWarning] = field(default_factory=list)
    duration_ms: int = 0
