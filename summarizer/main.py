from __future__ import annotations

import signal
import time
from pathlib import Path
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

sys.path.append(str(Path(__file__).resolve().parents[1]))

from common.config import load_config
from common.logging_utils import get_logger
from summarizer.service import run_summarizer_cycle

LOGGER = get_logger("summarizer")


def main() -> None:
    config = load_config()
    scheduler = BackgroundScheduler(timezone="UTC")
    for index, cron_expr in enumerate(config.summarizer_schedule):
        scheduler.add_job(
            run_summarizer_cycle,
            trigger=CronTrigger.from_crontab(cron_expr, timezone="UTC"),
            id=f"summarizer-cron-{index}",
            kwargs={"trigger_digest": True},
        )
    scheduler.start()
    LOGGER.info(
        "Summarizer scheduler started",
        extra={"extra_json": {"schedules": config.summarizer_schedule}},
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
