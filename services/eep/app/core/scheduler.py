import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")

_WINDOW_SECONDS = float(os.environ["WINDOW_SECONDS"])


def start_scheduler() -> None:
    from app.tasks.camera_scheduler import evaluate_store_hours

    scheduler.add_job(
        evaluate_store_hours,
        trigger="interval",
        seconds=_WINDOW_SECONDS,
        id="store_hours_evaluator",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    log.info(
        "Scheduler started — job=store_hours_evaluator interval=%.0fs",
        _WINDOW_SECONDS,
    )


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
    log.info("Scheduler stopped")
