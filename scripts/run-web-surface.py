#!/usr/bin/env python3
import argparse
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


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

    def do_GET(self):
        if self.path == "/health":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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

    def log_message(self, format: str, *args):
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a static web surface with /health")
    parser.add_argument("--root", required=True, help="Directory to serve")
    parser.add_argument("--port", required=True, type=int, help="Port to bind")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Invalid web root: {root}")

    os.chdir(root)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), WebSurfaceHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
