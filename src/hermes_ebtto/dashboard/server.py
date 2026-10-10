"""Local HTTP server for the EBTTO dashboard.

Loopback-only (127.0.0.1), stdlib-only, read-only. Serves a static single-page
UI from ``assets/`` plus a small JSON API under ``/api/`` that delegates to
:mod:`hermes_ebtto.dashboard.queries`. No mutating endpoint exists.
"""

from __future__ import annotations

import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from hermes_ebtto.dashboard import queries

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
DEFAULT_PORT = 8797
HOST = "127.0.0.1"

JSON_CT = "application/json; charset=utf-8"
ALLOWED_ASSETS = {"index.html", "app.js", "styles.css"}


def _json_response(handler: "_Handler", code: int, payload: dict) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", JSON_CT)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


class _Handler(BaseHTTPRequestHandler):
    server_version = "EBTTODashboard/0.1"
    db_path: str = ""  # set per-server

    # -- helpers -----------------------------------------------------------

    def log_message(self, fmt: str, *args: object) -> None:
        # Keep the terminal clean; the CLI prints the URL and Ctrl+C stops.
        pass

    def _conn(self):
        return queries.open_ro(self.db_path)

    def _query(self) -> dict:
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    # -- routing -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/"):
                self._api(path)
            elif path in ("/", "/index.html"):
                self._asset("index.html")
            elif path.lstrip("/") in ALLOWED_ASSETS:
                self._asset(path.lstrip("/"))
            else:
                _json_response(self, 404, {"error": "not found"})
        except queries.DashboardError as exc:
            _json_response(self, 503, {"error": str(exc)})
        except Exception as exc:  # never leak stack traces to the browser
            _json_response(self, 500, {"error": f"internal error: {type(exc).__name__}"})

    def _asset(self, name: str) -> None:
        f = ASSETS_DIR / name
        if not f.is_file():
            _json_response(self, 404, {"error": "asset missing from install"})
            return
        body = f.read_bytes()
        ctype = {
            "index.html": "text/html; charset=utf-8",
            "app.js": "application/javascript; charset=utf-8",
            "styles.css": "text/css; charset=utf-8",
        }[name]
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _api(self, path: str) -> None:
        q = self._query()
        with self._conn() as conn:
            if path == "/api/overview":
                _json_response(self, 200, queries.overview(conn, q.get("window", "24h")))
            elif path == "/api/tool_calls":
                _json_response(self, 200, queries.tool_calls(
                    conn, status=q.get("status"), tool=q.get("tool"),
                    window=q.get("window", "24h"), search=q.get("q"),
                    task_id=q.get("task_id"), page=q.get("page"),
                    page_size=q.get("page_size")))
            elif path == "/api/tool_call":
                _json_response(self, 200, queries.tool_call_detail(
                    conn, q.get("id", "")) or {"error": "not found"})
            elif path == "/api/failures":
                _json_response(self, 200, queries.failures(
                    conn, window=q.get("window", "24h"), page=q.get("page"),
                    page_size=q.get("page_size")))
            elif path == "/api/tasks":
                _json_response(self, 200, queries.tasks(
                    conn, window=q.get("window", "24h"), search=q.get("q"),
                    page=q.get("page"), page_size=q.get("page_size")))
            elif path == "/api/task":
                _json_response(self, 200, queries.task_timeline(
                    conn, q.get("id", "")) or {"error": "not found"})
            elif path == "/api/strategies":
                _json_response(self, 200, queries.strategies(
                    conn, status=q.get("status"), family=q.get("family"),
                    search=q.get("q"), page=q.get("page"),
                    page_size=q.get("page_size")))
            elif path == "/api/strategy":
                _json_response(self, 200, queries.strategy_detail(
                    conn, q.get("id", "")) or {"error": "not found"})
            elif path == "/api/patterns":
                _json_response(self, 200, queries.patterns(
                    conn, page=q.get("page"), page_size=q.get("page_size")))
            elif path == "/api/guidance":
                _json_response(self, 200, queries.guidance_events(
                    conn, reason_code=q.get("reason"), page=q.get("page"),
                    page_size=q.get("page_size")))
            elif path == "/api/evaluations":
                _json_response(self, 200, {"rows": queries.evaluations(conn)})
            elif path == "/api/system":
                _json_response(self, 200, queries.system_status(conn, self.db_path))
            else:
                _json_response(self, 404, {"error": "unknown endpoint"})


def find_free_port(start: int = DEFAULT_PORT, tries: int = 20) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    raise OSError(f"no free port in {start}..{start + tries - 1}")


def serve(*, port: int = 0, db_path: str = "", open_browser: bool = True) -> int:
    """Start the dashboard. Returns the port; blocks until Ctrl+C."""
    if port <= 0:
        port = find_free_port()
    _Handler.db_path = db_path
    httpd = ThreadingHTTPServer((HOST, port), _Handler)
    url = f"http://{HOST}:{port}/"
    print(f"EBTTO dashboard (read-only) listening on {url}")
    print(f"Database: {queries.resolve_db_path(db_path)}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return port
