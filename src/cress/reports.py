"""Build-time report types — warnings and errors surfaced to callers.

Populated across the pipeline (wikilinks, attachments, taxonomy, shortcodes,
plugins, etc.) and aggregated in the :class:`BuildResult` returned by
:meth:`cress.cress.build`. Serialisable to the CLI's ``--json`` envelope with
identical field names.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BuildWarning:
    """A soft error surfaced during a build — the build continues."""

    type: str
    file: str
    message: str
