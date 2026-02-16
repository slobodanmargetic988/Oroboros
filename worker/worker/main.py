import logging
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from .observability import emit_worker_log
from .orchestrator import WorkerOrchestrator


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
        format="%(message)s",
    )


def start_health_server() -> None:
    host = os.getenv("WORKER_HEALTH_HOST", "0.0.0.0")
    port = int(os.getenv("WORKER_HEALTH_PORT", "8090"))
    server = HTTPServer((host, port), HealthHandler)
    emit_worker_log(event="health_server_started", host=host, port=port)
    server.serve_forever()


def main() -> None:
    configure_logging()
    poll_interval = int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5"))
    orchestrator = WorkerOrchestrator()

    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    emit_worker_log(event="worker_started", poll_interval_seconds=poll_interval)

    while True:
        try:
            processed = orchestrator.process_next_run()
            if processed:
                emit_worker_log(event="worker_cycle_processed_run")
            else:
                emit_worker_log(event="worker_heartbeat")
        except Exception:
            emit_worker_log(event="worker_cycle_failed", level=logging.ERROR)
            logging.exception("worker_cycle_failed")
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
