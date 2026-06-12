"""Dev server and file watcher — powers ``cress serve``.

Runs a stdlib ThreadingHTTPServer over ``<output_dir>``, watches the vault
and local-plugin paths via watchdog, rebuilds on change (debounced 250ms),
and optionally notifies connected browsers via a Server-Sent Events endpoint
at ``/_cress/reload``.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from cress.build_result import BuildResult
from cress.site import cress

_LIVE_RELOAD_SCRIPT = """
<script>
(function(){
  if (window.EventSource) {
    var es = new EventSource('/_cress/reload');
    es.addEventListener('reload', function(){ location.reload(); });
  }
})();
</script>
"""

_DEBOUNCE_SECONDS = 0.25


class _ReloadBus:
    """Thread-safe broadcaster for rebuild notifications.

    Each subscriber holds a :class:`queue.Queue` that receives the current
    build version. The SSE handler drains it on every poll.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[int]] = []
        self._version: int = 0

    @property
    def version(self) -> int:
        return self._version

    def subscribe(self) -> queue.Queue[int]:
        q: queue.Queue[int] = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[int]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self) -> None:
        with self._lock:
            self._version += 1
            for q in self._subscribers:
                q.put_nowait(self._version)


def _site_root_for(output_dir: Path, url_prefix: str) -> Path | None:
    """Directory that maps to ``/`` when ``output_dir`` is mounted at ``url_prefix``.

    ``dist/blog`` mounted at ``/blog`` → ``dist``. Returns None when the
    prefix is empty or ``output_dir``'s trailing segments don't match it —
    then there is no site root to fall back to.
    """
    parts = [p for p in url_prefix.split("/") if p]
    if not parts:
        return None
    root = output_dir
    for part in reversed(parts):
        if root.name != part:
            return None
        root = root.parent
    return root


def _make_handler(
    output_dir: Path, live_reload: bool, bus: _ReloadBus, url_prefix: str = ""
) -> type[SimpleHTTPRequestHandler]:
    """Build a handler class bound to this server's output directory.

    When ``url_prefix`` is non-empty (e.g. ``"/blog"``), requests under the
    prefix have it stripped before being served from ``output_dir``, so
    dev-server URLs match production URLs 1:1. Requests outside the prefix
    fall back to files under the site root (``output_dir`` minus the prefix
    segments — production's web root), so assets the pages reference at
    ``/assets/...`` etc. resolve in preview too; anything else returns 404.
    """
    site_root = _site_root_for(output_dir, url_prefix)

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(output_dir), **kwargs)

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            # Compact per-request log: ``GET /blog/foo/ → 200``. SSE keepalives
            # on ``/_cress/reload`` are filtered out — otherwise they'd spam
            # every 15 seconds of idle.
            del size
            if self.path.startswith("/_cress/"):
                return
            status = str(code) if code != "-" else "-"
            print(f"  {self.command} {self.path} → {status}", file=sys.stderr)

        def log_message(self, format: str, *args: Any) -> None:
            # Silence other ``log_message`` calls — ``log_request`` already
            # reports every response's status (including 404s via
            # ``send_error`` → ``send_response`` → ``log_request``).
            del format, args

        def do_GET(self) -> None:
            if self.path == "/_cress/reload":
                self._serve_sse()
                return
            if not self._apply_url_prefix():
                return
            if live_reload and self._looks_like_html_path():
                self._serve_html_with_reload_injection()
                return
            super().do_GET()

        def _apply_url_prefix(self) -> bool:
            """Strip ``url_prefix`` from ``self.path``; False if the response was already sent."""
            if not url_prefix:
                return True
            if self.path == url_prefix or self.path == f"{url_prefix}/":
                self.path = "/"
                return True
            if self.path.startswith(f"{url_prefix}/"):
                self.path = self.path[len(url_prefix) :]
                return True
            if site_root is not None:
                rel = self.path.split("?", 1)[0].split("#", 1)[0].lstrip("/")
                if ".." not in rel.split("/") and (site_root / rel).is_file():
                    self.directory = str(site_root)
                    return True
            self.send_error(404)
            return False

        def _looks_like_html_path(self) -> bool:
            path = self.path.split("?", 1)[0].split("#", 1)[0]
            return path.endswith(".html") or path.endswith("/")

        def _serve_html_with_reload_injection(self) -> None:
            # Resolve the requested path the same way SimpleHTTPRequestHandler
            # would — against self.directory, which _apply_url_prefix may have
            # repointed at the site root for out-of-prefix files.
            rel = self.path.split("?", 1)[0].split("#", 1)[0].lstrip("/")
            target = Path(self.directory) / rel
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                self.send_error(404)
                return
            body = target.read_bytes()
            try:
                html = body.decode("utf-8")
                injected = html.replace("</body>", f"{_LIVE_RELOAD_SCRIPT}</body>", 1).encode(
                    "utf-8"
                )
            except UnicodeDecodeError:
                injected = body
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(injected)))
            self.end_headers()
            self.wfile.write(injected)

        def _serve_sse(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = bus.subscribe()
            try:
                # Send an initial hello event so the browser wires up.
                self.wfile.write(b"event: hello\ndata: ok\n\n")
                self.wfile.flush()
                while True:
                    try:
                        version = q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    self.wfile.write(f"event: reload\ndata: {version}\n\n".encode())
                    self.wfile.flush()
            except ConnectionError:
                # Client went away (browser navigated/closed, tab reloaded).
                # Covers BrokenPipeError, ConnectionResetError, and Windows'
                # ConnectionAbortedError (WinError 10053).
                pass
            finally:
                bus.unsubscribe(q)

    return _Handler


class _DebouncedRebuilder(FileSystemEventHandler):
    """Coalesces watchdog events and triggers a rebuild once per debounce window."""

    def __init__(self, trigger: threading.Event) -> None:
        self._trigger = trigger

    def on_any_event(self, event: FileSystemEvent) -> None:
        self._trigger.set()


def serve(
    site: cress,
    *,
    port: int = 8000,
    live_reload: bool = False,
    drafts_only: bool = False,
    no_drafts: bool = False,
    json_output: bool = False,
) -> None:
    """Build once, start the HTTP server, watch vault + plugin dirs, rebuild on change."""
    result = site.build(drafts_only=drafts_only, no_drafts=no_drafts)
    _emit_build(result, json_output)

    bus = _ReloadBus()
    handler_cls = _make_handler(site.config.output_dir, live_reload, bus, site.config.url_prefix)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    _emit_serve_url(port, site.config.url_prefix, json_output)
    _emit_routes(site.config.output_dir, site.config.url_prefix, json_output)

    trigger = threading.Event()
    rebuilder = _DebouncedRebuilder(trigger)
    observer = Observer()
    for watch_root in _watch_roots(site):
        if watch_root.is_dir():
            observer.schedule(rebuilder, str(watch_root), recursive=True)
    observer.start()

    try:
        while True:
            trigger.wait()
            time.sleep(_DEBOUNCE_SECONDS)
            trigger.clear()
            try:
                result = site.build(drafts_only=drafts_only, no_drafts=no_drafts)
                bus.publish()
                _emit_build(result, json_output)
            except Exception as exc:  # pragma: no cover — surfaced but non-fatal
                print(f"rebuild failed: {exc}", file=sys.stderr)
    finally:
        observer.stop()
        observer.join()
        server.shutdown()


def _watch_roots(site: cress) -> list[Path]:
    return [
        site.vault / site.config.vault_subfolder,
        site.vault / site.config.attachments_subfolder,
        site.target / ".cress" / "plugins",
    ]


def _emit_serve_url(port: int, url_prefix: str, json_output: bool) -> None:
    """Print the address the dev server is listening on, including ``url_prefix``."""
    url = f"http://127.0.0.1:{port}{url_prefix}/"
    print(f"cress serve: {url}", file=sys.stderr)
    if json_output:
        print(json.dumps({"version": 1, "event": "listening", "url": url}), flush=True)


def _emit_routes(output_dir: Path, url_prefix: str, json_output: bool) -> None:
    """List every HTML/XML page under ``output_dir`` as a URL at startup."""
    routes = _enumerate_routes(output_dir, url_prefix)
    if not routes:
        return
    print(f"  {len(routes)} route{'s' if len(routes) != 1 else ''}:", file=sys.stderr)
    for url in routes:
        print(f"    {url}", file=sys.stderr)
    if json_output:
        print(json.dumps({"version": 1, "event": "routes", "urls": routes}), flush=True)


def _enumerate_routes(output_dir: Path, url_prefix: str) -> list[str]:
    """Return the URL for every ``.html`` or ``.xml`` file under ``output_dir``, sorted."""
    routes: list[str] = []
    for path in output_dir.rglob("*"):
        if not path.is_file() or path.suffix not in (".html", ".xml"):
            continue
        rel = path.relative_to(output_dir).as_posix()
        if rel == "index.html":
            url = f"{url_prefix}/"
        elif rel.endswith("/index.html"):
            url = f"{url_prefix}/{rel[: -len('index.html')]}"
        else:
            url = f"{url_prefix}/{rel}"
        routes.append(url)
    return sorted(routes)


def _emit_build(result: BuildResult, json_output: bool) -> None:
    print(
        f"built {result.pages_written} pages in {result.duration_ms}ms "
        f"({len(result.warnings)} warnings)",
        file=sys.stderr,
    )
    if json_output:
        envelope = {
            "version": 1,
            "ok": not result.errors,
            "result": {
                "pages_written": result.pages_written,
                "skipped_posts": result.skipped_posts,
                "duration_ms": result.duration_ms,
            },
            "warnings": [asdict(w) for w in result.warnings],
            "errors": [asdict(e) for e in result.errors],
        }
        print(json.dumps(envelope), flush=True)


def inject_live_reload(html: str) -> str:
    """Public helper used by the test suite to assert injection behaviour."""
    return html.replace("</body>", f"{_LIVE_RELOAD_SCRIPT}</body>", 1)
