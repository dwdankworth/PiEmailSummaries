from __future__ import annotations

import signal
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from common.config import load_config
from common.db import connect, init_schema
from common.logging_utils import get_logger
from summarizer.service import run_summarizer_cycle, validate_ollama_model

LOGGER = get_logger("summarizer")


def main() -> None:
    config = load_config()

    # Initialize DB schema once at startup
    connection = connect()
    init_schema(connection)
    connection.close()

    validate_ollama_model(config)
    # Allow up to 15 minutes of grace so jobs still fire after device
    # sleep / wake cycles instead of being silently skipped (default is 1 s).
    scheduler = BackgroundScheduler(
        timezone=config.timezone,
        job_defaults={"misfire_grace_time": 900},
    )
    scheduler.add_job(
        run_summarizer_cycle,
        "interval",
        minutes=config.summarizer_interval_minutes,
        next_run_time=datetime.now(ZoneInfo(config.timezone)),
        id="summarizer-interval",
        kwargs={"trigger_digest": False},
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    LOGGER.info(
        "Summarizer scheduler started",
        extra={"extra_json": {"interval_minutes": config.summarizer_interval_minutes, "timezone": config.timezone}},
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
