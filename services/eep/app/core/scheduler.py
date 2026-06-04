import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")

_WINDOW_SECONDS = float(os.environ["WINDOW_SECONDS"])


def start_scheduler() -> None:
    from app.tasks.camera_scheduler import evaluate_schedules

    scheduler.add_job(
        evaluate_schedules,
        trigger="interval",
        seconds=_WINDOW_SECONDS,
        id="camera_schedule_evaluator",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    log.info(
        "Scheduler started — job=camera_schedule_evaluator interval=%.0fs",
        _WINDOW_SECONDS,
    )


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
    log.info("Scheduler stopped")
