"""Pure slug helper.

Single source of truth for every slug cress generates — post slugs, heading
anchors, tag/category URLs. Pure function, zero dependencies.
"""

import re
import unicodedata

_SLUG_NONALPHANUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Normalise ``text`` into a URL-safe kebab-case slug.

    Steps: unicode-normalise (NFKD) → strip combining marks → encode as
    ASCII (drop unrepresentable chars) → lowercase → non-alphanumeric to
    ``-`` → collapse dashes → strip leading/trailing dashes. Empty / all-
    symbol input returns ``"untitled"``.
    """
    normalised = unicodedata.normalize("NFKD", text)
    ascii_bytes = normalised.encode("ascii", "ignore")
    ascii_text = ascii_bytes.decode("ascii").lower()
    hyphenated = _SLUG_NONALPHANUM.sub("-", ascii_text).strip("-")
    return hyphenated or "untitled"
