#!/usr/bin/env python3
import argparse
import http.client
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _api_proxy_target() -> str | None:
    raw = os.getenv("WEB_API_PROXY_TARGET", "").strip()
    if not raw:
        return None
    if "://" not in raw:
        return f"http://{raw}"
    return raw


def _is_api_route(path: str) -> bool:
    normalized = path or "/"
    return (
        normalized.startswith("/api")
        or normalized == "/openapi.json"
        or normalized.startswith("/docs")
        or normalized.startswith("/redoc")
    )


class WebSurfaceHandler(SimpleHTTPRequestHandler):
    @staticmethod
    def _root() -> Path:
        return Path(os.getcwd()).resolve()

    def _resolved_request_path(self) -> Path | None:
        raw_path = urlparse(self.path).path
        normalized = unquote(raw_path).lstrip("/")
        candidate = (self._root() / normalized).resolve()
        root = self._root()
        if candidate == root or root in candidate.parents:
            return candidate
        return None

    def _serve_index_fallback(self) -> bool:
        index_path = self._root() / "index.html"
        if not index_path.exists() or not index_path.is_file():
            return False
        content = index_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)
        return True

    def _proxy_api_request(self) -> bool:
        target = _api_proxy_target()
        if not target:
            return False

        parsed_request = urlparse(self.path)
        if not _is_api_route(parsed_request.path):
            return False

        parsed_target = urlparse(target)
        host = parsed_target.hostname
        if not host:
            self.send_error(502, "Invalid WEB_API_PROXY_TARGET")
            return True
        port = parsed_target.port or (443 if parsed_target.scheme == "https" else 80)
        upstream_path = parsed_request.path or "/"
        if parsed_request.query:
            upstream_path = f"{upstream_path}?{parsed_request.query}"

        headers = {}
        for key, value in self.headers.items():
            normalized = key.strip().lower()
            if normalized in HOP_BY_HOP_HEADERS or normalized == "host":
                continue
            headers[key] = value
        headers["Host"] = parsed_target.netloc
        headers["X-Forwarded-Proto"] = "https" if parsed_target.scheme == "https" else "http"

        body = None
        if self.command in {"POST", "PUT", "PATCH"}:
            raw_length = self.headers.get("Content-Length")
            if raw_length:
                try:
                    length = max(0, int(raw_length))
                except ValueError:
                    length = 0
                if length > 0:
                    body = self.rfile.read(length)

        connection_cls = http.client.HTTPSConnection if parsed_target.scheme == "https" else http.client.HTTPConnection
        try:
            conn = connection_cls(host, port, timeout=15)
            conn.request(self.command, upstream_path, body=body, headers=headers)
            response = conn.getresponse()
            response_body = response.read()
        except Exception as exc:  # noqa: BLE001
            self.send_error(502, f"API upstream unavailable: {exc}")
            return True
        finally:
            try:
                conn.close()  # type: ignore[name-defined]
            except Exception:  # noqa: BLE001
                pass

        self.send_response(response.status)
        for key, value in response.getheaders():
            normalized = key.strip().lower()
            if normalized in HOP_BY_HOP_HEADERS:
                continue
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(response_body)
        return True

    def _handle_request(self) -> None:
        if self.path == "/health":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self._proxy_api_request():
            return

        if self.command != "GET":
            self.send_error(405, "Method Not Allowed")
            return

        candidate = self._resolved_request_path()
        if candidate is not None:
            if candidate.exists():
                super().do_GET()
                return
            # For SPA route paths (no file extension), fallback to index.html.
            if not candidate.suffix and self._serve_index_fallback():
                return

        super().do_GET()

    def do_GET(self) -> None:  # noqa: N802
        self._handle_request()

    def do_POST(self) -> None:  # noqa: N802
        self._handle_request()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle_request()

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle_request()

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle_request()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._handle_request()

    def log_message(self, format: str, *args):
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a static web surface with /health")
    parser.add_argument("--root", required=True, help="Directory to serve")
    parser.add_argument("--port", required=True, type=int, help="Port to bind")
    parser.add_argument(
        "--api-target",
        default="",
        help="Optional API upstream for /api proxying (example: http://127.0.0.1:8101)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Invalid web root: {root}")

    if args.api_target:
        os.environ["WEB_API_PROXY_TARGET"] = args.api_target.strip()

    os.chdir(root)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), WebSurfaceHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
