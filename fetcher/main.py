from __future__ import annotations

import signal
import time
from datetime import UTC, datetime
from pathlib import Path
import sys

from apscheduler.schedulers.background import BackgroundScheduler

sys.path.append(str(Path(__file__).resolve().parents[1]))

from common.config import load_config
from common.logging_utils import get_logger
from fetcher.service import run_fetch_cycle

LOGGER = get_logger("fetcher")


def main() -> None:
    config = load_config()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_fetch_cycle,
        "interval",
        minutes=config.fetch_interval_minutes,
        next_run_time=datetime.now(UTC),
    )
    scheduler.start()
    LOGGER.info(
        "Fetcher scheduler started",
        extra={"extra_json": {"interval_minutes": config.fetch_interval_minutes}},
    )

    def _shutdown(*_: object) -> None:
        scheduler.shutdown(wait=False)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
