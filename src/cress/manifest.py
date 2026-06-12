"""Manifest-based output writer.

Defines :class:`OutputFile` — the single output contract every generator
returns — and owns the one place where cress touches ``<output_dir>``.
Persists ``<output_dir>/.cress-manifest.json`` so subsequent builds can delete
files that dropped out of the tree, without ever touching user-placed files.
"""

import contextlib
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_FILENAME = ".cress-manifest.json"
MANIFEST_VERSION = 1


@dataclass(frozen=True, slots=True)
class OutputFile:
    """A single artefact cress will write under ``output_dir``.

    ``relative_path`` is POSIX-form (forward slashes) relative to the output
    directory. ``content`` is either text (for HTML/XML) or bytes (for
    attachments and pygments CSS stored as bytes).
    """

    relative_path: str
    content: str | bytes


@dataclass(frozen=True, slots=True)
class Manifest:
    """Cress's record of what it owns under ``output_dir``.

    Deliberately timestamp-free: two rebuilds over the same inputs produce
    byte-identical manifests, so ``cress publish`` doesn't commit noise when
    only the manifest's wall-clock would have changed.
    """

    version: int = MANIFEST_VERSION
    files: list[str] = field(default_factory=list)


def _normalise(relative_path: str) -> str:
    """Collapse ``\\`` to ``/`` so Windows + Linux builds produce byte-identical manifests."""
    return PurePosixPath(relative_path.replace("\\", "/")).as_posix()


def load_manifest(output_dir: Path) -> Manifest | None:
    """Load ``<output_dir>/.cress-manifest.json``. None if absent or corrupt."""
    path = output_dir / MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    version = raw.get("version")
    files = raw.get("files")
    if version != MANIFEST_VERSION or not isinstance(files, list):
        return None
    files_str = [str(f) for f in files if isinstance(f, str)]
    return Manifest(version=MANIFEST_VERSION, files=files_str)


def write_outputs(
    outputs: list[OutputFile],
    output_dir: Path,
    old_manifest: Manifest | None,
) -> Manifest:
    """Write ``outputs`` to disk and return the new manifest.

    Every byte cress produces flows through here. On a second build, files
    that were in ``old_manifest.files`` but are not in ``outputs`` are
    deleted. Files outside ``old_manifest.files`` are never touched.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write outputs first so a crash mid-write doesn't leave the site missing
    # cress-owned files before we've staged the new manifest.
    normalised: list[str] = []
    for of in outputs:
        rel = _normalise(of.relative_path)
        normalised.append(rel)
        dest = output_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(of.content, bytes):
            dest.write_bytes(of.content)
        else:
            dest.write_text(of.content, encoding="utf-8")

    new_files: set[str] = set(normalised)
    if old_manifest is not None:
        old_files = {_normalise(f) for f in old_manifest.files}
        stale = old_files - new_files
        for rel in sorted(stale, key=lambda p: -p.count("/")):
            path = output_dir / rel
            if path.is_file():
                path.unlink()
        _prune_empty_dirs(output_dir, {path_to_walk(output_dir / rel) for rel in old_files})

    manifest = Manifest(version=MANIFEST_VERSION, files=sorted(new_files))
    _save_manifest(manifest, output_dir)
    return manifest


def path_to_walk(path: Path) -> Path:
    """Internal: parents of a file are candidates for empty-dir pruning."""
    return path.parent


def _prune_empty_dirs(output_dir: Path, candidate_dirs: set[Path]) -> None:
    """Remove empty directories — but only those that were on the old-manifest paths."""
    # Sort deepest-first so children are removed before their parents get a chance.
    for candidate in sorted(candidate_dirs, key=lambda p: -len(p.parts)):
        if candidate == output_dir:
            continue
        if not candidate.is_dir():
            continue
        with contextlib.suppress(OSError):
            candidate.rmdir()  # only removes if empty


def _save_manifest(manifest: Manifest, output_dir: Path) -> None:
    payload: dict[str, Any] = {
        "version": manifest.version,
        "files": manifest.files,
    }
    path = output_dir / MANIFEST_FILENAME
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
