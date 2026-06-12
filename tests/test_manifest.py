"""Tests for cress.manifest — write_outputs, load_manifest, stale-file cleanup."""

import json
from pathlib import Path

from cress.manifest import MANIFEST_FILENAME, OutputFile, load_manifest, write_outputs


def _output(path: str, content: str | bytes) -> OutputFile:
    return OutputFile(relative_path=path, content=content)


def test_first_build_writes_all_files_and_creates_manifest(tmp_path: Path) -> None:
    outputs = [
        _output("index.html", "<html>home</html>"),
        _output("about/index.html", "<html>about</html>"),
        _output("assets/logo.png", b"\x89PNG"),
    ]
    manifest = write_outputs(outputs, tmp_path, old_manifest=None)
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "<html>home</html>"
    assert (tmp_path / "about" / "index.html").exists()
    assert (tmp_path / "assets" / "logo.png").read_bytes() == b"\x89PNG"
    assert set(manifest.files) == {"index.html", "about/index.html", "assets/logo.png"}
    # Manifest persisted
    data = json.loads((tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert set(data["files"]) == {"index.html", "about/index.html", "assets/logo.png"}


def test_second_build_renamed_post_deletes_old(tmp_path: Path) -> None:
    first = [
        _output("old-slug/index.html", "A"),
        _output("shared.html", "S"),
    ]
    m1 = write_outputs(first, tmp_path, old_manifest=None)
    second = [
        _output("new-slug/index.html", "A"),
        _output("shared.html", "S"),
    ]
    write_outputs(second, tmp_path, old_manifest=m1)
    assert not (tmp_path / "old-slug" / "index.html").exists()
    assert not (tmp_path / "old-slug").exists()  # empty dir pruned
    assert (tmp_path / "new-slug" / "index.html").exists()
    assert (tmp_path / "shared.html").exists()


def test_user_placed_file_survives_across_builds(tmp_path: Path) -> None:
    user_file = tmp_path / "custom.html"
    user_file.write_text("user wrote this", encoding="utf-8")
    m1 = write_outputs([_output("index.html", "x")], tmp_path, old_manifest=None)
    write_outputs([_output("index.html", "x")], tmp_path, old_manifest=m1)
    assert user_file.exists()
    assert user_file.read_text(encoding="utf-8") == "user wrote this"


def test_user_placed_file_in_subdir_survives(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    user_file = sub / "readme.txt"
    user_file.write_text("user", encoding="utf-8")
    m1 = write_outputs([_output("sub/cress.html", "x")], tmp_path, old_manifest=None)
    # Remove cress.html on second build
    write_outputs([], tmp_path, old_manifest=m1)
    assert user_file.exists()
    assert sub.exists()  # dir NOT pruned because user file is still there


def test_corrupt_manifest_treated_as_first_build(tmp_path: Path) -> None:
    (tmp_path / MANIFEST_FILENAME).write_text("not json {[", encoding="utf-8")
    loaded = load_manifest(tmp_path)
    assert loaded is None


def test_backslash_paths_normalised_to_forward_slashes(tmp_path: Path) -> None:
    outputs = [OutputFile(relative_path=r"posts\slug\index.html", content="X")]
    manifest = write_outputs(outputs, tmp_path, old_manifest=None)
    assert manifest.files == ["posts/slug/index.html"]
    # File still written correctly on disk
    assert (tmp_path / "posts" / "slug" / "index.html").read_text(encoding="utf-8") == "X"


def test_load_manifest_returns_none_when_absent(tmp_path: Path) -> None:
    assert load_manifest(tmp_path) is None


def test_load_manifest_round_trips(tmp_path: Path) -> None:
    outputs = [_output("a.html", "a"), _output("b/c.html", "c")]
    written = write_outputs(outputs, tmp_path, old_manifest=None)
    loaded = load_manifest(tmp_path)
    assert loaded is not None
    assert set(loaded.files) == set(written.files)
    assert loaded.version == 1


def test_binary_content_written_as_bytes(tmp_path: Path) -> None:
    data = b"\x00\x01\x02binary"
    write_outputs([_output("bin/file.bin", data)], tmp_path, old_manifest=None)
    assert (tmp_path / "bin" / "file.bin").read_bytes() == data
