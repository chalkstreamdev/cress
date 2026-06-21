"""Minimal tests for cress.server — live-reload script, SSE bus mechanics."""

import contextlib
import queue
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from cress.server import (
    _emit_routes,
    _emit_serve_url,
    _enumerate_routes,
    _make_handler,
    _QuietHTTPServer,
    _ReloadBus,
    _watch_roots,
    inject_live_reload,
)
from cress.site import cress

_CONFIG_NO_TEMPLATE_DIR = """\
vault_subfolder: "Blogs/Demo"
output_dir: "out"
site:
  title: "T"
  description: "D"
  base_url: "https://x.test"
"""

_CONFIG_WITH_TEMPLATE_DIR = """\
vault_subfolder: "Blogs/Demo"
output_dir: "out"
template_dir: "templates"
site:
  title: "T"
  description: "D"
  base_url: "https://x.test"
"""


def _set_up_site(tmp_path: Path, config: str) -> cress:
    vault = tmp_path / "vault"
    (vault / "Blogs/Demo").mkdir(parents=True)
    (vault / "_attachments").mkdir()
    target = tmp_path / "target"
    (target / ".cress").mkdir(parents=True)
    (target / ".cress" / "config.yaml").write_text(config, encoding="utf-8")
    (target / "out").mkdir()
    return cress(vault, target)


def test_inject_live_reload_adds_script_before_body_close() -> None:
    out = inject_live_reload("<html><body>hi</body></html>")
    assert "EventSource('/_cress/reload')" in out
    assert out.endswith("</body></html>")


def test_inject_live_reload_no_body_tag_is_noop() -> None:
    assert inject_live_reload("raw") == "raw"


def test_reload_bus_broadcasts_to_subscribers() -> None:
    bus = _ReloadBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    bus.publish()
    assert q1.get(timeout=1) == 1
    assert q2.get(timeout=1) == 1
    bus.unsubscribe(q1)
    bus.publish()
    assert q2.get(timeout=1) == 2
    try:
        q1.get_nowait()
        raise AssertionError("expected q1 to receive no further events after unsubscribe")
    except queue.Empty:
        pass


def test_watch_roots_includes_template_dir_when_configured(tmp_path: Path) -> None:
    site = _set_up_site(tmp_path, _CONFIG_WITH_TEMPLATE_DIR)
    roots = _watch_roots(site)
    assert site.config.template_dir is not None
    assert site.config.template_dir in roots


def test_watch_roots_omits_template_dir_when_unset(tmp_path: Path) -> None:
    site = _set_up_site(tmp_path, _CONFIG_NO_TEMPLATE_DIR)
    roots = _watch_roots(site)
    assert site.config.template_dir is None
    assert None not in roots


def _find_free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_http_handler_serves_static_file(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    bus = _ReloadBus()
    handler_cls = _make_handler(tmp_path, live_reload=False, bus=bus)
    port = _find_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Give the server a moment to start.
        time.sleep(0.1)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            body = resp.read().decode("utf-8")
        assert "hi" in body
        assert "EventSource" not in body  # live-reload off
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_http_handler_injects_live_reload_when_enabled(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    bus = _ReloadBus()
    handler_cls = _make_handler(tmp_path, live_reload=True, bus=bus)
    port = _find_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.1)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            body = resp.read().decode("utf-8")
        assert "EventSource" in body
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_emit_serve_url_no_prefix(capsys: pytest.CaptureFixture[str]) -> None:
    _emit_serve_url(port=8000, url_prefix="", json_output=False)
    err = capsys.readouterr().err
    assert "http://127.0.0.1:8000/" in err


def test_emit_serve_url_with_prefix(capsys: pytest.CaptureFixture[str]) -> None:
    _emit_serve_url(port=8000, url_prefix="/blog", json_output=False)
    err = capsys.readouterr().err
    assert "http://127.0.0.1:8000/blog/" in err


def test_emit_serve_url_json_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    _emit_serve_url(port=8000, url_prefix="/blog", json_output=True)
    out = capsys.readouterr().out
    assert '"event": "listening"' in out
    assert '"url": "http://127.0.0.1:8000/blog/"' in out


def test_enumerate_routes_index_and_nested(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("", encoding="utf-8")
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "index.html").write_text("", encoding="utf-8")
    (tmp_path / "tag").mkdir()
    (tmp_path / "tag" / "x").mkdir()
    (tmp_path / "tag" / "x" / "index.html").write_text("", encoding="utf-8")
    (tmp_path / "rss.xml").write_text("", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "pygments.css").write_text("", encoding="utf-8")  # ignored
    routes = _enumerate_routes(tmp_path, url_prefix="/blog")
    assert routes == [
        "/blog/",
        "/blog/foo/",
        "/blog/rss.xml",
        "/blog/tag/x/",
    ]


def test_enumerate_routes_no_prefix(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("", encoding="utf-8")
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "index.html").write_text("", encoding="utf-8")
    routes = _enumerate_routes(tmp_path, url_prefix="")
    assert routes == ["/", "/hello/"]


def test_emit_routes_prints_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "index.html").write_text("", encoding="utf-8")
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "index.html").write_text("", encoding="utf-8")
    _emit_routes(tmp_path, url_prefix="/blog", json_output=False)
    err = capsys.readouterr().err
    assert "2 routes" in err
    assert "/blog/" in err
    assert "/blog/foo/" in err


def test_emit_routes_json_envelope(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "index.html").write_text("", encoding="utf-8")
    _emit_routes(tmp_path, url_prefix="", json_output=True)
    out = capsys.readouterr().out
    assert '"event": "routes"' in out
    assert '"/"' in out


def test_http_handler_logs_requests_to_stderr(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "index.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    bus = _ReloadBus()
    handler_cls = _make_handler(tmp_path, live_reload=False, bus=bus)
    port = _find_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.1)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            resp.read()
        with contextlib.suppress(urllib.error.HTTPError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope")
        time.sleep(0.1)  # let the handler thread finish its logging
    finally:
        server.shutdown()
        thread.join(timeout=2)
    err = capfd.readouterr().err
    assert "GET / → 200" in err
    assert "GET /nope → 404" in err


def test_quiet_server_suppresses_client_disconnect_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Browsers abort speculative/keep-alive connections; socketserver's
    # handle_error would print a full traceback for each one. _QuietHTTPServer
    # swallows ConnectionError (incl. Windows' ConnectionAbortedError 10053).
    from http.server import SimpleHTTPRequestHandler

    server = _QuietHTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler, bind_and_activate=False)
    try:
        try:
            raise ConnectionAbortedError(10053, "aborted by host machine")
        except ConnectionAbortedError:
            server.handle_error(None, ("127.0.0.1", 60505))
    finally:
        server.server_close()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_quiet_server_still_reports_non_connection_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from http.server import SimpleHTTPRequestHandler

    server = _QuietHTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler, bind_and_activate=False)
    try:
        try:
            raise ValueError("genuine handler bug")
        except ValueError:
            server.handle_error(None, ("127.0.0.1", 60505))
    finally:
        server.server_close()
    assert "ValueError" in capsys.readouterr().err


def test_http_handler_with_url_prefix_falls_back_to_site_root_files(tmp_path: Path) -> None:
    # When output_dir's trailing segments match the url_prefix (dist/blog
    # mounted at /blog), requests outside the prefix serve files from the
    # directory production treats as the site root (dist/) — so manifest-
    # linked CSS and logo files resolve in preview just like behind nginx.
    output_dir = tmp_path / "dist" / "blog"
    output_dir.mkdir(parents=True)
    (output_dir / "index.html").write_text("<html><body>blog</body></html>", encoding="utf-8")
    (tmp_path / "dist" / "assets").mkdir()
    (tmp_path / "dist" / "assets" / "style-abc.css").write_text("body{color:red}", encoding="utf-8")
    bus = _ReloadBus()
    handler_cls = _make_handler(output_dir, live_reload=False, bus=bus, url_prefix="/blog")
    port = _find_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.1)
        # Prefixed paths serve from output_dir as before.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/blog/") as resp:
            assert "blog" in resp.read().decode("utf-8")
        # Site-root files outside the prefix are served from dist/.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/assets/style-abc.css") as resp:
            assert "color:red" in resp.read().decode("utf-8")
        # Missing site-root files still 404.
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/assets/nope.css")
            raise AssertionError("expected 404 for missing site-root file")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_http_handler_with_url_prefix_serves_under_prefix(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>root</body></html>", encoding="utf-8")
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "index.html").write_text(
        "<html><body>foo-post</body></html>", encoding="utf-8"
    )
    bus = _ReloadBus()
    handler_cls = _make_handler(tmp_path, live_reload=False, bus=bus, url_prefix="/blog")
    port = _find_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.1)
        # /blog and /blog/ both serve the output-dir root
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/blog/") as resp:
            assert "root" in resp.read().decode("utf-8")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/blog/foo/") as resp:
            assert "foo-post" in resp.read().decode("utf-8")
        # Anything outside the prefix is 404
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            raise AssertionError("expected 404 for root request outside prefix")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/foo/")
            raise AssertionError("expected 404 for path outside prefix")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=2)
