import logging
import os
import time


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [worker] %(message)s",
    )


def main() -> None:
    configure_logging()
    poll_interval = int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5"))
    logging.info("Ouroboros worker scaffold started")
    logging.info("Polling interval: %s seconds", poll_interval)

    while True:
        logging.info("worker heartbeat")
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
