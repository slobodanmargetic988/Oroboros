import logging
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return

        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args):
        return


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [worker] %(message)s",
    )


def start_health_server() -> None:
    host = os.getenv("WORKER_HEALTH_HOST", "0.0.0.0")
    port = int(os.getenv("WORKER_HEALTH_PORT", "8090"))
    server = HTTPServer((host, port), HealthHandler)
    logging.info("Worker health endpoint available at http://%s:%s/health", host, port)
    server.serve_forever()


def main() -> None:
    configure_logging()
    poll_interval = int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5"))

    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    logging.info("Ouroboros worker scaffold started")
    logging.info("Polling interval: %s seconds", poll_interval)

    while True:
        logging.info("worker heartbeat")
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
