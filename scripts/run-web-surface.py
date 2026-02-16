#!/usr/bin/env python3
import argparse
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class WebSurfaceHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
