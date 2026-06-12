"""Tag and category normalisation.

Collects tags/categories across posts, normalises values for grouping and URL
generation, preserves the first-seen display form, and produces the indices
consumed by the tag/category page generators.

Display forms can differ for the same tag slug because of stripping and slugifying
the text.
"""

from dataclasses import dataclass, field
from pathlib import Path

from cress.post import Post
from cress.reports import BuildWarning
from cress.slugify import slugify


@dataclass(slots=True)
class _TaxonomyBucket:
    display: str
    first_source: Path
    posts: list[Post] = field(default_factory=list)


class Taxonomy:
    """Collects and groups tag or category values across posts."""

    def __init__(self) -> None:
        self._buckets: dict[str, _TaxonomyBucket] = {}

    def add(self, value: str, post: Post, warnings: list[BuildWarning]) -> None:
        """Record ``value`` as a taxonomy term for ``post``.

        The first display form wins; subsequent mismatches emit a
        ``display_mismatch`` warning (post path + both forms). Empty values
        are rejected with a ``empty_taxonomy_value`` warning.
        """
        stripped = value.strip()
        if not stripped:
            warnings.append(
                BuildWarning(
                    type="empty_taxonomy_value",
                    file=str(post.source_path),
                    message="taxonomy value is empty after trimming whitespace",
                )
            )
            return
        slug = slugify(stripped)
        bucket = self._buckets.get(slug)
        if bucket is None:
            self._buckets[slug] = _TaxonomyBucket(
                display=stripped,
                first_source=post.source_path,
                posts=[post],
            )
            return
        if stripped != bucket.display:
            warnings.append(
                BuildWarning(
                    type="display_mismatch",
                    file=str(post.source_path),
                    message=(
                        f"taxonomy term {stripped!r} uses a different display form than "
                        f"first-seen {bucket.display!r} (first at {bucket.first_source})"
                    ),
                )
            )
        bucket.posts.append(post)

    def grouped(self) -> list[tuple[str, str, list[Post]]]:
        """Return ``(slug, display, posts)`` tuples sorted by slug; posts reverse-chronological."""
        return [
            (slug, bucket.display, sorted(bucket.posts, key=_sort_key_post, reverse=True))
            for slug, bucket in sorted(self._buckets.items())
        ]


def _sort_key_post(post: Post) -> str:
    # Compare dates by ISO string — works for both date and datetime; stable tiebreak on slug.
    date_str = post.date.isoformat() if post.date is not None else ""
    slug = post.slug or ""
    return f"{date_str}|{slug}"
